#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_probe.py -- 最小的 MCP 探针（仅标准库）。

用途：doctor 用它判断一个 MCP 服务是 OK / DOWN / FAIL。
只做 initialize + tools/list，不做任何工具调用。

  python mcp_probe.py --stdio -- "<命令>" [参数...]
  python mcp_probe.py --http http://127.0.0.1:8765/mcp [--token-file /path/daemon.json]

输出：单行 JSON
  {"ok": true, "transport": "stdio", "tools": 18, "names": ["..."], "elapsed_ms": 123}
  {"ok": false, "state": "down", "error": "..."}   服务没起
  {"ok": false, "state": "fail", "error": "..."}   起了但协议/工具不对

状态判定口径：
  down   连接被拒、进程起不来、port 未监听  -> 不是故障，是没开
  fail   握手报错、tools/list 为空、协议不符 -> 真故障
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = float(os.environ.get("MCP_PROBE_TIMEOUT", "20"))
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "ctf-doctor", "version": "1"},
    },
}
INITED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0 if obj.get("ok") else 1)


def classify(exc_text):
    low = exc_text.lower()
    down_marks = (
        "connection refused", "actively refused", "积极拒绝",
        "no route", "timed out", "timeout", "cannot connect",
        "failed to connect", "无法连接", "拒绝",
    )
    return "down" if any(m in low for m in down_marks) else "fail"


# ------------------------------------------------------------------ stdio
def probe_stdio(cmd, call_tool=None, call_args=None):
    start = time.time()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines = queue.Queue()

    def pump():
        try:
            for line in proc.stdout:
                lines.put(line)
        except Exception:
            pass

    threading.Thread(target=pump, daemon=True).start()

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait_for(rid):
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                if proc.poll() is not None:
                    err = (proc.stderr.read() or "")[-800:]
                    raise RuntimeError(f"进程已退出 rc={proc.returncode}: {err}")
                continue
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid:
                return msg
        raise RuntimeError("等待 JSON-RPC 响应超时")

    try:
        send(INIT)
        init = wait_for(1)
        if "error" in init:
            raise RuntimeError("initialize 返回错误: " + json.dumps(init["error"], ensure_ascii=False))
        send(INITED)
        send(LIST)
        res = wait_for(2)
        tools = (res.get("result") or {}).get("tools") or []
        if not tools:
            raise RuntimeError("tools/list 为空")
        out = {
            "ok": True,
            "transport": "stdio",
            "tools": len(tools),
            "names": [t.get("name") for t in tools][:40],
            "server": ((init.get("result") or {}).get("serverInfo") or {}).get("name"),
            "elapsed_ms": int((time.time() - start) * 1000),
        }

        if call_tool:
            send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": call_tool, "arguments": call_args or {}}})
            cres = wait_for(3)
            if "error" in cres:
                out["call_ok"] = False
                out["call_error"] = json.dumps(cres["error"], ensure_ascii=False)
            else:
                content = (cres.get("result") or {}).get("content") or []
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                out["call_ok"] = not (cres.get("result") or {}).get("isError", False)
                out["call_result"] = "\n".join(texts)[:1500]
        return out
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ------------------------------------------------------------------ http
def read_token(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["token"]


def probe_http(url, token_file=None):
    start = time.time()
    token = read_token(token_file) if token_file else None
    sid = None

    def post(obj):
        nonlocal sid
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        if sid:
            headers["mcp-session-id"] = sid
        req = urllib.request.Request(url, json.dumps(obj).encode(), headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            sid = resp.headers.get("mcp-session-id") or sid
            body = resp.read().decode("utf-8", "replace")
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                line = line[6:]
            if line.startswith("{"):
                return json.loads(line)
        return {}

    post(INIT)
    post(INITED)
    res = post(LIST)
    tools = (res.get("result") or {}).get("tools") or []
    if not tools:
        raise RuntimeError("tools/list 为空")
    return {
        "ok": True,
        "transport": "http",
        "tools": len(tools),
        "names": [t.get("name") for t in tools][:40],
        "elapsed_ms": int((time.time() - start) * 1000),
    }


def main():
    args = sys.argv[1:]
    try:
        if args[:1] == ["--http"]:
            url = args[1]
            token_file = None
            if "--token-file" in args:
                token_file = args[args.index("--token-file") + 1]
            emit(probe_http(url, token_file))

        if args[:1] == ["--stdio"]:
            call_tool = None
            call_args = None
            if "--call" in args:
                call_tool = args[args.index("--call") + 1]
            if "--call-args" in args:
                call_args = json.loads(args[args.index("--call-args") + 1])
            if "--" not in args:
                emit({"ok": False, "state": "fail", "error": "stdio 模式需要 -- 分隔命令"})
            rest = args[args.index("--") + 1:]
            if not rest:
                emit({"ok": False, "state": "fail", "error": "缺少 stdio 命令"})
            emit(probe_stdio(rest, call_tool, call_args))

        emit({"ok": False, "state": "fail", "error": "用法: --stdio [--call NAME [--call-args JSON]] -- <cmd...> | --http <url>"})
    except urllib.error.URLError as exc:
        emit({"ok": False, "state": classify(str(exc)), "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        emit({"ok": False, "state": classify(str(exc)), "error": str(exc)})


if __name__ == "__main__":
    main()

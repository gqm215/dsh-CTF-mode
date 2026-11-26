#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py -- WSL 侧工具链体检（与 Windows 的 doctor.ps1 同构）。

用法：python3 doctor.py [--json] [--registry PATH]

状态口径：
  OK        探针成功
  DOWN      MCP 服务没开（连接被拒）
  FAIL      探针失败 / 命令缺失
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY = os.path.join(HERE, "registry.json")


def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def probe_cmd(entry):
    name = entry.get("cmd") or entry["name"]
    path = shutil.which(name)
    if not path:
        return "FAIL", f"not found: {name}"
    if entry.get("version"):
        rc, out, err = run(entry["version"])
        if rc != 0:
            return "FAIL", f"{path} (version rc={rc})"
        return "OK", f"{path} :: {first_line(out) or first_line(err)}"
    return "OK", path


def probe_probe(entry):
    rc, out, err = run(entry["probe"])
    detail = first_line(out) or first_line(err)
    return ("OK" if rc == 0 else "FAIL"), (detail or f"rc={rc}")


def probe_path(entry):
    p = os.path.expanduser(entry["path"])
    return ("OK" if os.path.exists(p) else "FAIL"), p


INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "wsl-doctor", "version": "1"}},
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _post(url, obj, sid=None, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if sid:
        headers["mcp-session-id"] = sid
    req = urllib.request.Request(url, json.dumps(obj).encode(), headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        new_sid = resp.headers.get("mcp-session-id") or sid
        body = resp.read().decode("utf-8", "replace")
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            line = line[6:]
        if line.startswith("{"):
            return json.loads(line), new_sid
    return {}, new_sid


def probe_http(entry):
    token = None
    if entry.get("token_file"):
        try:
            with open(os.path.expanduser(entry["token_file"])) as f:
                token = json.load(f)["token"]
        except Exception as exc:  # noqa: BLE001
            return "FAIL", f"token unreadable: {exc}"
    try:
        _, sid = _post(entry["url"], INIT, None, token)
        _post(entry["url"], {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid, token)
        res, _ = _post(entry["url"], LIST, sid, token)
        tools = (res.get("result") or {}).get("tools") or []
        if not tools:
            return "FAIL", "tools/list empty"
        return "OK", f"{len(tools)} tools"
    except urllib.error.URLError as exc:
        state = "DOWN" if "refused" in str(exc).lower() or "连接" in str(exc) else "FAIL"
        return state, str(exc)
    except Exception as exc:  # noqa: BLE001
        return "FAIL", str(exc)


HANDLERS = {"cmd": probe_cmd, "probe": probe_probe, "path": probe_path, "http": probe_http}


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    registry = DEFAULT_REGISTRY
    if "--registry" in args:
        registry = args[args.index("--registry") + 1]

    with open(registry, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for entry in data["entries"]:
        kind = entry.get("kind", "cmd")
        handler = HANDLERS.get(kind)
        if not handler:
            rows.append({"name": entry["name"], "kind": kind, "status": "FAIL", "detail": "unknown kind"})
            continue
        status, detail = handler(entry)
        if status != "OK" and entry.get("optional"):
            status = "SKIP"
        rows.append({"name": entry["name"], "kind": kind, "status": status, "detail": detail})

    counts = {"ok": 0, "down": 0, "fail": 0, "skip": 0}
    for r in rows:
        counts[r["status"].lower()] = counts.get(r["status"].lower(), 0) + 1

    if as_json:
        print(json.dumps({"summary": counts, "entries": rows}, ensure_ascii=False, indent=2))
    else:
        print("\n== WSL toolchain doctor ==")
        print("registry: " + registry + "\n")
        for r in rows:
            print(f"{r['status']:<5} {r['name']:<18} {r['kind']:<7} {r['detail']}")
        print(f"\nsummary: {counts['ok']} OK / {counts['down']} DOWN / {counts['fail']} FAIL / {counts['skip']} SKIP\n")

    return counts["fail"]


if __name__ == "__main__":
    sys.exit(main())

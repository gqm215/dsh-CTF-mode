"""ida_mcp_start.py -- 在 IDA 里启动 ida-pro-mcp 的 HTTP 服务（端口 13337）。

用法（由 idat/ida 的 -S 调用）：
    ida.exe -A -S"D:\\CTF\\Toolchain\\scripts\\ida_mcp_start.py" <sample>

背景：mcp-plugin.py 加载时只注册插件，服务要等 MCP.run() 才启动。
      这里绕过菜单/热键，直接 load_and_run_plugin，失败再按路径 import 兜底。

注意：插件的请求分发走 idaapi.execute_sync（主线程执行），
      所以主线程不能阻塞 —— 只能用于 GUI/带事件循环的 IDA，不要用在批处理 idat 里空转。
"""
import os
import sys
import time
import traceback

import ida_auto
import idaapi

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "ida-mcp.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass
    try:
        print("[ida-mcp] " + msg)
    except Exception:
        pass


def start_server():
    for name in ("mcp_plugin", "mcp-plugin", "mcp"):
        try:
            if idaapi.load_and_run_plugin(name, 0):
                log("load_and_run_plugin(%r) ok" % name)
                return True
        except Exception as exc:  # noqa: BLE001
            log("load_and_run_plugin(%r) failed: %r" % (name, exc))

    try:
        import importlib.util

        path = os.path.join(os.environ["APPDATA"], "Hex-Rays", "IDA Pro", "plugins", "mcp-plugin.py")
        spec = importlib.util.spec_from_file_location("mcp_plugin_manual", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.Server().start()
        log("importlib fallback ok: " + path)
        return True
    except Exception:  # noqa: BLE001
        log("fallback failed:\n" + traceback.format_exc())
        return False


def main():
    log("script start")
    try:
        ida_auto.auto_wait()
        log("auto_wait done")
    except Exception as exc:  # noqa: BLE001
        log("auto_wait failed: %r" % exc)

    ok = start_server()
    log("SERVER STARTED" if ok else "SERVER NOT STARTED")
    if os.environ.get("IDA_MCP_HOLD") == "1":
        log("HOLD=1, blocking forever (debug only)")
        while True:
            time.sleep(5)


main()

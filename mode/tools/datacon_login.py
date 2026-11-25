#!/usr/bin/env python3
"""One-time DataCon login/refresh helper (headed browser).

DataCon SSO puts a short-lived `Token` into localStorage; `bin/datacon.py`
reads it from ~/.datacon/session.json. When the token expires (API answers
`{"code":302,"msg":"无效的token"}`) run this once:

    python ~/.agents/ctf-mode/tools/datacon_login.py

A Chromium window opens on the DataCon login/training page. If you are already
logged in via SSO it auto-detects; otherwise log in once. On success the Token
and cookies are written to ~/.datacon/session.json (0600) and verified against
/api03/user-info.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path.home()
PROFILE = HOME / ".datacon" / "browser-profile"
SESSION = HOME / ".datacon" / "session.json"
TARGET = "https://www.datacon.org.cn/datacon-ui-infos/training/home"


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            no_viewport=True, locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(TARGET, wait_until="domcontentloaded", timeout=120000)
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            time.sleep(3)
            try:
                token = page.evaluate("() => localStorage.getItem('Token')")
            except Exception:
                continue
            if not token:
                print("[datacon-login] waiting for login...", flush=True)
                continue
            probe = page.evaluate("""async () => {
                const t = localStorage.getItem('Token');
                const r = await fetch('/api03/user-info',
                    {headers: {'Accept': 'application/json', 'Token': t}});
                return {body: await r.text()};
            }""")
            body = probe.get("body") or ""
            if '"code":200' in body:
                rec = {"ready": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "token": token,
                       "cookies": ctx.cookies(),
                       "storage": page.evaluate("""() => ({
                           localStorage: Object.fromEntries(Object.entries(localStorage)),
                           sessionStorage: Object.fromEntries(Object.entries(sessionStorage))})"""),
                       "user_info": body,
                       "user_agent": page.evaluate("navigator.userAgent")}
                SESSION.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                try:
                    os.chmod(SESSION, stat.S_IRUSR | stat.S_IWUSR)
                except Exception:
                    pass
                print(f"[datacon-login] OK: session saved to {SESSION}", flush=True)
                print(f"[datacon-login] user: {body[:200]}", flush=True)
                page.wait_for_timeout(1500)
                ctx.close()
                return 0
            print(f"[datacon-login] token present but not accepted yet: {body[:120]}", flush=True)
        print("[datacon-login] TIMEOUT: no valid session detected", file=sys.stderr)
        ctx.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())

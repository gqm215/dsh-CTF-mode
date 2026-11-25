"""Guided one-time login for the GZ::CTF platform, then persist the session.

Opens a visible Chromium window on the platform config base_url. Log in there
(invite code / SSO / password as the platform offers). As soon as
GET /api/account/profile answers 200 in that browser, the script exports the
cookies + any localStorage token to ~/.gzctf/cookies_auto.json and runs
`gzctf import-cookies` so every CLI/adapter command is authenticated.

Nothing prints the cookie/token values.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path.home()
GZ = HOME / ".gzctf"
PROFILE = GZ / "browser-profile"
SESSION = GZ / "session.json"
AUTO = GZ / "cookies_auto.json"


def base_url() -> str:
    cfg = json.loads((GZ / "config.json").read_text(encoding="utf-8"))
    return cfg.get("base_url", "http://43.138.89.233:14455").rstrip("/")


def main() -> int:
    GZ.mkdir(parents=True, exist_ok=True)
    base = base_url()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                   viewport={"width": 1300, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(base, wait_until="domcontentloaded", timeout=90000)
        print(f"[gzctf-login] window open at {base} — please log in there.", flush=True)
        print("[gzctf-login] waiting up to 20 minutes for an authenticated session...", flush=True)

        deadline = time.time() + 20 * 60
        ok = False
        while time.time() < deadline:
            try:
                status = page.evaluate(
                    "() => fetch('/api/account/profile', {credentials: 'include'})"
                    ".then(r => r.status).catch(() => 0)")
            except Exception:
                status = 0
            if status == 200:
                ok = True
                break
            time.sleep(2)

        if not ok:
            print("[gzctf-login] TIMEOUT: no authenticated session detected.", flush=True)
            ctx.close()
            return 2

        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        token = ""
        try:
            token = page.evaluate(
                "() => localStorage.getItem('token') || localStorage.getItem('access_token') || ''") or ""
        except Exception:
            pass
        if not token:
            try:
                token = page.evaluate(
                    "() => { for (const k of Object.keys(localStorage)) { const v = localStorage.getItem(k) || '';"
                    " if (k.toLowerCase().includes('token') && v.length > 20) return v; } return ''; }") or ""
            except Exception:
                pass

        AUTO.write_text(json.dumps({"cookies": cookies, "token": token,
                                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                   ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(AUTO, 0o600)
        except Exception:
            pass
        print(f"[gzctf-login] authenticated; {len(cookies)} cookie(s), token={'yes' if token else 'no'}", flush=True)

        import_proc = subprocess.run([sys.executable, str(Path.home() / ".local" / "lib" / "gzctf" / "gzctf.py"),
                                      "import-cookies", str(AUTO)], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=120)
        print(import_proc.stdout.strip()[-500:], flush=True)
        who = subprocess.run(["gzctf", "whoami"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60, shell=True)
        print("[gzctf-login] whoami:", who.stdout.strip()[-300:], flush=True)
        ctx.close()
        return 0 if import_proc.returncode == 0 else 3


if __name__ == "__main__":
    sys.exit(main())

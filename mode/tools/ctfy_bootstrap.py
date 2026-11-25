#!/usr/bin/env python3
"""One-time (or repeatable) CTFy bootstrap: guided login + automated API token.

The CTFy platform is built for automated agents: every access method (SDK, CLI,
MCP, REST) shares one `pf_` API token. This script removes both manual steps:

  1. If ~/.ctfy/browser-profile is not logged in, it opens a visible Chromium
     window and waits for the human to log in once (any method the platform
     offers: SSO / invite code / password). Nothing is typed by this script.
  2. If no token is saved yet, it drives Settings -> API tokens -> "AI 智能体 ——
     参赛" template (challenges:read submissions:write instances:write teams:write
     profile:read, 30 days) and captures the one-time plaintext into
     ~/.ctfy/api_token.txt (0600). Only a masked prefix is printed.
  3. Verifies the token against /api/v1/me and prints the identity.

After this, every ctf-mode tool picks the token up automatically (CTFY_TOKEN >
~/.ctfy/api_token.txt > ~/.ctfy/session.json).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path.home()
CTFY = HOME / ".ctfy"
PROFILE = CTFY / "browser-profile"
TOKEN_FILE = CTFY / "api_token.txt"
SESSION = CTFY / "session.json"
BASE = "https://ctfy.tsinghua.edu.cn"
API = BASE + "/api/v1"
TEMPLATE_LABEL = "AI 智能体 —— 参赛"
TOKEN_NAME = "dsh-ctf-mode"


def api_me(token: str):
    try:
        req = urllib.request.Request(API + "/me",
                                     headers={"Authorization": "Bearer " + token,
                                              "Accept": "application/json",
                                              "User-Agent": "dsh-ctf-mode/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as exc:
        return 0, str(exc)


def saved_token() -> str:
    if TOKEN_FILE.exists():
        try:
            return TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def create_token_via_ui(page) -> str:
    page.goto(BASE + "/settings/tokens", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    page.get_by_text("生成新令牌", exact=False).first.click(timeout=8000)
    page.wait_for_timeout(1200)
    page.get_by_text(TEMPLATE_LABEL, exact=False).first.click(timeout=6000)
    page.wait_for_timeout(600)
    page.get_by_role("button", name="下一步").first.click(timeout=6000)
    page.wait_for_timeout(1200)
    inputs = page.locator("input[type=text], input:not([type])")
    for i in range(inputs.count()):
        el = inputs.nth(i)
        try:
            if el.is_visible():
                el.fill(TOKEN_NAME)
                break
        except Exception:
            pass
    page.get_by_role("button", name="下一步").first.click(timeout=6000)
    page.wait_for_timeout(1200)
    page.get_by_role("button", name=re.compile("创建令牌|创建")).first.click(timeout=8000)
    page.wait_for_timeout(2500)
    body = page.locator("body").inner_text(timeout=10000)
    token = ""
    for i in range(page.locator("input, textarea").count()):
        el = page.locator("input, textarea").nth(i)
        try:
            v = el.input_value() or ""
            if v.startswith("pf_"):
                token = v
                break
        except Exception:
            pass
    if not token:
        m = re.search(r"pf_[A-Za-z0-9_\-]{20,}", body)
        token = m.group(0) if m else ""
    return token


def main() -> int:
    CTFY.mkdir(parents=True, exist_ok=True)

    # 0. a working saved token already? nothing to do.
    tok = saved_token()
    if tok:
        status, me = api_me(tok)
        if status == 200:
            print(f"[ctfy-bootstrap] saved API token still valid ({tok[:5]}...{len(tok)} chars)")
            print("[ctfy-bootstrap] identity:",
                  (me.get("display_name") or me.get("name") or me.get("email") or "?") if isinstance(me, dict) else me)
            return 0

    with sync_playwright() as p:
        headless = bool(tok)  # only need a window when a human must log in
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=headless,
                                                   viewport={"width": 1400, "height": 950})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)
        logged_in = page.evaluate(
            "() => fetch('/api/v1/me', {credentials: 'include'}).then(r => r.status === 200).catch(() => false)")
        if not logged_in:
            print("[ctfy-bootstrap] not logged in: a Chromium window opened on the platform.", flush=True)
            print("[ctfy-bootstrap] please log in there once (form / SSO / code); waiting up to 20 min...", flush=True)
            deadline = time.time() + 20 * 60
            while time.time() < deadline:
                try:
                    logged_in = page.evaluate(
                        "() => fetch('/api/v1/me', {credentials: 'include'}).then(r => r.status === 200).catch(() => false)")
                except Exception:
                    logged_in = False
                if logged_in:
                    break
                time.sleep(2)
            if not logged_in:
                print("[ctfy-bootstrap] TIMEOUT waiting for login.", file=sys.stderr)
                ctx.close()
                return 2
            print("[ctfy-bootstrap] login detected; creating an agent API token...", flush=True)
        else:
            print("[ctfy-bootstrap] browser profile already logged in.")

        token = create_token_via_ui(page)
        if not token:
            print("[ctfy-bootstrap] failed to capture a new API token from the UI", file=sys.stderr)
            ctx.close()
            return 3
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass
        print(f"[ctfy-bootstrap] API token saved to {TOKEN_FILE} ({len(token)} chars)")
        ctx.close()

    status, me = api_me(saved_token())
    if status != 200:
        print(f"[ctfy-bootstrap] token verification failed: HTTP {status} {str(me)[:200]}", file=sys.stderr)
        return 4
    ident = me.get("display_name") or me.get("name") or me.get("email") or "?"
    print(f"[ctfy-bootstrap] token verified; identity={ident}")
    print("[ctfy-bootstrap] OK — ctf-mode tools will use this token automatically")
    return 0


if __name__ == "__main__":
    sys.exit(main())

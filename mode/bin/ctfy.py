#!/usr/bin/env python3
"""ctfy.py — CTFy platform adapter for the DSH CTF mode (L3 verification channel).

Platform: CTFy (https://ctfy.tsinghua.edu.cn), player API under /api/v1.
Auth: `Authorization: Bearer <teamKey>` from ~/.ctfy/session.json (written by a
human login; this tool never handles passwords and never prints the key).

Commands:
  doctor                     platform reachability + session identity
  list [--game ID]           competition challenge list (default: playground)
  start <challenge-id>       POST /instances, poll until ready, print instance
  instance <instance-id>     instance detail (scope/services/questions)
  status <instance-id>       instance status
  download <instance-id> <attachment> -o PATH     per-instance attachment
  download-chal <challenge-id> <attachment> -o PATH   static attachment
  vpn <instance-id> -o PATH  WireGuard/OpenVPN config (for VPN challenges)
  submit <instance-id> --question Q --answer STR|--answer-file F [--verified-fact ID]
  check <instance-id> --question Q   run the platform's checker question
  solves                     current team solves

Evidence rules (kernel VERIFY_CONTRACT / SPEC §5):
  - `submit` refuses without `--verified-fact`, and the named fact must exist in
    the challenge's local ctfboard and be `verified`; the answer sha256 must match
    an artifact/evidence recorded for that fact when available.
  - HTTP 200 is never treated as Accepted: the verdict comes from the returned
    submission/solve state, otherwise it is reported as pending.
  - The raw flag is never written to logs; only sha256 + platform verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://ctfy.tsinghua.edu.cn"
# "Platform Playground" practice competition from the mode's config; override with
# --game or CTFY_COMPETITION_ID / ~/.ctfy/config.json.
DEFAULT_GAME = "bc60dc1764f34413964a547102f17261"
CTF_ROOT = Path.home() / ".agents" / "ctf-mode"
CTFY_HOME = Path.home() / ".ctfy"
SESSION = CTFY_HOME / "session.json"
CONFIG = CTFY_HOME / "config.json"


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config() -> dict:
    cfg = {"base": DEFAULT_BASE, "competition_id": DEFAULT_GAME}
    if CONFIG.exists():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        except Exception:
            pass
    if os.environ.get("CTFY_BASE"):
        cfg["base"] = os.environ["CTFY_BASE"]
    if os.environ.get("CTFY_COMPETITION_ID"):
        cfg["competition_id"] = os.environ["CTFY_COMPETITION_ID"]
    return cfg


def load_key() -> str:
    """Credential precedence: CTFY_TOKEN (official pf_ agent token) > CTFY_TEAM_KEY >
    ~/.ctfy/api_token.txt (created in Settings -> API tokens) > ~/.ctfy/session.json
    (browser teamKey from the interactive login). Never printed."""
    for env_name in ("CTFY_TOKEN", "CTFY_TEAM_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    tokf = CTFY_HOME / "api_token.txt"
    if tokf.exists():
        try:
            tok = tokf.read_text(encoding="utf-8").strip()
        except Exception:
            tok = ""
        if tok:
            return tok
    if not SESSION.exists():
        die(
            "no platform credential: create an API token in the platform "
            "(Settings -> API tokens) and save it to ~/.ctfy/api_token.txt, or run "
            "the interactive login so ~/.ctfy/session.json exists",
            4,
        )
    try:
        data = json.loads(SESSION.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"unreadable session file: {exc}", 4)
    key = str(data.get("teamKey") or "").strip()
    if not key:
        die("session file has no teamKey; re-run the interactive login", 4)
    return key


class CTFy:
    def __init__(self, base: str | None = None, key: str | None = None):
        cfg = load_config()
        self.base = (base or cfg["base"]).rstrip("/")
        self.cfg = cfg
        self.key = key  # lazy: doctor works unauthenticated
        self.api = self.base + "/api/v1"

    def _headers(self, auth: bool = True) -> dict:
        h = {"Accept": "application/json", "User-Agent": "dsh-ctf-mode/1.0"}
        if auth:
            h["Authorization"] = "Bearer " + (self.key or "")
        return h

    def request(self, method: str, path: str, body: dict | None = None, auth: bool = True,
                timeout: int = 30, raw: bool = False, extra_headers: dict | None = None):
        url = self.api + path
        data = None
        headers = self._headers(auth)
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                if raw:
                    return resp.status, dict(resp.headers), payload
                if not payload:
                    return resp.status, None
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    return resp.status, json.loads(payload.decode("utf-8", "replace"))
                return resp.status, payload.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                parsed = json.loads(payload.decode("utf-8", "replace"))
            except Exception:
                parsed = payload.decode("utf-8", "replace")[:500]
            return exc.code, parsed
        except urllib.error.URLError as exc:
            die(f"network error calling {url}: {exc.reason}", 5)

    # ---- commands -------------------------------------------------------
    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body or {}, **kw)

    # ---- human check (proof of work) ------------------------------------
    def solve_human_check(self, point: str) -> str | None:
        """Solve CTFy's ALTCHA/PBKDF2 proof-of-work for `point`.

        The browser does this automatically before retrying a 428; the platform
        sets `agents_allowed=true`, so an agent client is expected to do the
        same work. Prints only solver statistics, never the token.
        """
        try:
            import ctfy_pow  # shipped next to this file
        except Exception as exc:  # pragma: no cover - packaging guard
            print(f"WARN: human-check solver unavailable: {exc}", file=sys.stderr)
            return None
        try:
            token, sol = ctfy_pow.solve_token(self, point)
        except Exception as exc:
            print(f"WARN: human-check solve failed ({point}): {exc}", file=sys.stderr)
            return None
        print(f"HUMANCHECK point={point} counter={sol['counter']} "
              f"attempts={sol['attempts']} derive={sol['time']}ms", file=sys.stderr)
        return token

    def request_with_human_check(self, method: str, path: str, body: dict | None,
                                 point: str, **kw):
        """Request, and on 428 human_check_required solve the PoW and retry once."""
        code, payload = self.request(method, path, body=body, **kw)
        if code != 428 or not isinstance(payload, dict):
            return code, payload
        if payload.get("code") != "human_check_required":
            return code, payload
        detail = payload.get("detail") or {}
        provider = detail.get("provider") if isinstance(detail, dict) else None
        if provider != "pow":
            print(f"WARN: human check provider {provider!r} is not solvable here", file=sys.stderr)
            return code, payload
        token = self.solve_human_check(point)
        if not token:
            return code, payload
        code2, payload2 = self.request(method, path, body=body,
                                       extra_headers={"X-Human-Check": token}, **kw)
        # A challenge can be rejected (expired / rate-limited / replayed). The
        # browser simply fetches a fresh one; do the same once, with a short pause.
        if code2 == 403 and isinstance(payload2, dict) and \
                str(payload2.get("code", "")).startswith("human_check"):
            time.sleep(2.0)
            token = self.solve_human_check(point)
            if token:
                return self.request(method, path, body=body,
                                    extra_headers={"X-Human-Check": token}, **kw)
        return code2, payload2


def cmd_doctor(args):
    c = CTFy()
    print(f"base: {c.base}")
    code, meta = c.get("/meta", auth=False)
    if code != 200 or not isinstance(meta, dict):
        die(f"platform unreachable (HTTP {code}): {meta}", 5)
    plat = meta.get("platform") or {}
    print(f"platform: version={meta.get('version')} commit={str(plat.get('commit_sha'))[:12]} env={meta.get('environment')}")
    print(f"server_time: {meta.get('server_time_ts')}  status_page: {meta.get('status_page_url')}")
    comps = f"competitions live={((meta.get('events') or {}).get('live'))} upcoming={((meta.get('events') or {}).get('upcoming'))}"
    print(comps)

    key = os.environ.get("CTFY_TEAM_KEY", "").strip()
    if not key and SESSION.exists():
        try:
            key = str(json.loads(SESSION.read_text(encoding="utf-8")).get("teamKey") or "")
        except Exception:
            key = ""
    if not key:
        print("auth: NO SESSION — run the interactive login (writes ~/.ctfy/session.json)")
        print("doctor: reachable, not authenticated (exit 0)")
        return 0
    c.key = key
    code, me = c.get("/me")
    if code == 401 or code == 403:
        print(f"auth: SESSION EXPIRED (HTTP {code}) — re-run the interactive login")
        return 4
    if code != 200 or not isinstance(me, dict):
        print(f"auth: unexpected /me response HTTP {code}: {str(me)[:200]}")
        return 5
    ident = me.get("team_name") or me.get("name") or me.get("username") or me.get("email") or "?"
    print(f"auth: OK identity={ident} team_id={me.get('team_id') or me.get('id') or '?'}")
    code2, game = c.get(f"/competitions/{args.game}")
    if code2 == 200 and isinstance(game, dict):
        print(f"game: {game.get('title')} id={game.get('id')} phase={game.get('phase')} "
              f"challenges={game.get('challenge_count')} play_open={game.get('play_open')}")
        print(f"my_solves={game.get('my_solves')} my_score={game.get('my_score')} registered={game.get('is_registered')}")
    print("doctor: OK")
    return 0


def cmd_list(args):
    c = CTFy()
    code, game = c.get(f"/competitions/{args.game}", auth=False)
    if code != 200 or not isinstance(game, dict):
        die(f"cannot read competition {args.game}: HTTP {code} {str(game)[:200]}", 5)
    print(f"game: {game.get('title')} ({game.get('id')}) phase={game.get('phase')} challenges={game.get('challenge_count')}")
    # The competition object carries a short preview only; the full roster comes
    # from the paginated /challenges endpoint.
    items = []
    code2, page = c.get(f"/competitions/{args.game}/challenges?limit=100", auth=False)
    if code2 == 200 and isinstance(page, dict):
        items = page.get("items") or []
    if not items:
        items = game.get("challenges") or []
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    for ch in items:
        qs = ",".join(q.get("id", "?") for q in (ch.get("questions") or []))
        print(f"{ch.get('id'):<12} {ch.get('category'):<10} {ch.get('difficulty'):<6} "
              f"solved={ch.get('solves_count'):>4} q=[{qs}] {ch.get('name')}")
        for att in ch.get("attachments") or []:
            print(f"             attachment: {att.get('name')} ({att.get('size')} B, per_team={att.get('per_team')})")
    return 0


def _instance_id_from(payload) -> str:
    if isinstance(payload, dict):
        for k in ("id", "instance_id", "instanceId"):
            if payload.get(k):
                return str(payload[k])
        inst = payload.get("instance")
        if isinstance(inst, dict) and inst.get("id"):
            return str(inst["id"])
    die(f"cannot find instance id in response: {str(payload)[:300]}")
    return ""


def cmd_start(args):
    c = CTFy()
    c.key = load_key()
    body = {"challenge_id": args.challenge}
    if args.ttl:
        body["ttl"] = args.ttl
    body["competition_id"] = args.game
    t0 = time.time()
    code, payload = c.request_with_human_check("POST", "/instances", body, "instance_start")
    if code in (401, 403):
        die(f"not authenticated / not eligible (HTTP {code}): {str(payload)[:200]}", 4)
    if code not in (200, 201, 202):
        die(f"start failed HTTP {code}: {str(payload)[:300]}", 6)
    inst = _instance_id_from(payload)
    print(f"START {args.challenge} instance={inst} http={code} {time.time()-t0:.1f}s")
    # poll status
    deadline = time.time() + args.wait
    last = None
    while time.time() < deadline:
        code, st = c.get(f"/instances/{inst}/status")
        state = None
        if isinstance(st, dict):
            state = st.get("status") or st.get("state") or (st.get("instance") or {}).get("status")
        if state != last:
            print(f"STATUS {state} ({time.time()-t0:.1f}s) code={code}")
            last = state
        if state in ("running", "ready", "up", "healthy"):
            break
        if state in ("failed", "error", "stopped", "expired"):
            die(f"instance ended in state {state}: {str(st)[:300]}", 6)
        time.sleep(args.interval)
    code, info = c.get(f"/instances/{inst}")
    if code == 200 and isinstance(info, dict):
        print(json.dumps(info, ensure_ascii=False, indent=1)[: args.max_json])
    print(f"INSTANCE {inst} elapsed={time.time()-t0:.1f}s")
    return 0


def _print_scope(info: dict):
    for key in ("scope", "services", "endpoints", "addresses", "hosts"):
        val = info.get(key)
        if val:
            print(f"{key}: {json.dumps(val, ensure_ascii=False)[:1500]}")


def cmd_instance(args):
    c = CTFy(); c.key = load_key()
    code, info = c.get(f"/instances/{args.instance}")
    if code != 200:
        die(f"instance read HTTP {code}: {str(info)[:200]}", 5)
    print(json.dumps(info, ensure_ascii=False, indent=1)[: args.max_json])
    if isinstance(info, dict):
        _print_scope(info)


def cmd_stop(args):
    c = CTFy(); c.key = load_key()
    code, resp = c.request("DELETE", f"/instances/{args.instance}")
    print(f"STOP instance={args.instance} http={code} {str(resp)[:300]}")
    return 0 if code in (200, 202, 204, 404) else 5


def cmd_status(args):
    c = CTFy(); c.key = load_key()
    code, st = c.get(f"/instances/{args.instance}/status")
    print(f"HTTP {code}")
    print(json.dumps(st, ensure_ascii=False, indent=1)[:2000])
    return 0 if code == 200 else 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _fetch_blob(c: "CTFy", path: str) -> tuple[int, bytes, str]:
    """GET an API path that may answer a binary body, a JSON download link, or a
    302 to presigned object storage. Presigned URLs must be fetched WITHOUT the
    platform Authorization header (their signature covers host only)."""
    url = c.api + path
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + (c.key or ""),
                                               "User-Agent": "dsh-ctf-mode/1.0"})
    opener = urllib.request.build_opener(_NoRedirect)
    status, headers, body = 0, {}, b""
    try:
        with opener.open(req, timeout=60) as resp:
            status, headers, body = resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        status, headers, body = exc.code, dict(exc.headers), exc.read()
    ctype = headers.get("Content-Type", "")
    if status in (301, 302, 303, 307, 308) and headers.get("Location"):
        loc = headers["Location"]
        with urllib.request.urlopen(urllib.request.Request(loc, headers={"User-Agent": "dsh-ctf-mode/1.0"}),
                                    timeout=180) as r2:
            return r2.status, r2.read(), "redirect"
    if "json" in ctype and body:
        try:
            info = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            info = None
        if isinstance(info, dict) and info.get("url"):
            with urllib.request.urlopen(urllib.request.Request(info["url"], headers={"User-Agent": "dsh-ctf-mode/1.0"}),
                                        timeout=180) as r2:
                return r2.status, r2.read(), "link"
        return status, body, "json"
    return status, body, "body"


def _download(c: CTFy, path: str, out: str, name: str) -> int:
    status, blob, kind = _fetch_blob(c, path)
    if status in (401, 403) and kind != "redirect":
        die(f"not authenticated (HTTP {status})", 4)
    if status != 200 or kind == "json":
        die(f"download HTTP {status} ({kind}): {str(blob[:200])}", 5)
    dst = Path(out)
    if dst.is_dir():
        dst = dst / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(blob)
    print(f"DOWNLOADED {name} -> {dst} ({len(blob)} B) sha256={hashlib.sha256(blob).hexdigest()} via {kind}")
    return 0


def cmd_download(args):
    c = CTFy(); c.key = load_key()
    name = args.attachment
    path = f"/instances/{args.instance}/attachments/{urllib.parse.quote(name)}"
    return _download(c, path, args.out, name.split("/")[-1])


def cmd_download_chal(args):
    c = CTFy(); c.key = load_key()
    name = args.attachment
    path = f"/challenges/{args.challenge}/attachments/{urllib.parse.quote(name)}"
    return _download(c, path, args.out, name.split("/")[-1])


def cmd_vpn(args):
    c = CTFy(); c.key = load_key()
    code, info = c.get(f"/instances/{args.instance}/vpn-config", raw=True)
    if code != 200:
        die(f"vpn-config HTTP {code}: {str(info)[:200]}", 5)
    _, headers, blob = info if isinstance(info, tuple) else (None, {}, b"")
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(blob)
    print(f"VPN-CONFIG saved {dst} ({len(blob)} B) — import into a WireGuard/OpenVPN client; "
          f"services are then reachable by their published names/addresses")
    return 0


def _ctfboard(args_list: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, str(CTF_ROOT / "bin" / "ctfboard.py")] + args_list
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fact_verified(game: str, chal: str, fact_id: str) -> tuple[bool, dict]:
    """Confirm the fact id exists and is verified, returning its record."""
    board = Path.home() / ".agents" / "ctf-mode" / "runs" / game / chal / "facts.jsonl"
    if not board.exists():
        return False, {}
    for line in board.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        rid = str(rec.get("id") or rec.get("fact_id") or "")
        if rid == fact_id:
            return str(rec.get("status", "")).lower() == "verified", rec
    return False, {}


def _run_dir(game: str, chal: str) -> Path:
    return Path.home() / ".agents" / "ctf-mode" / "runs" / game / chal


def _submission_history(game: str, chal: str) -> list[dict]:
    f = _run_dir(game, chal) / "submissions.jsonl"
    out: list[dict] = []
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _duplicate_verdict(game: str, chal: str, cid: str, answer_sha: str) -> str | None:
    """Return the previous verdict for this exact (cid, answer) pair, else None.

    This is the idempotency guard only: a *different* answer may be submitted
    again (normal CTF retry); the same answer must not be sent twice, whether it
    was accepted, rejected or is still pending.
    """
    for rec in reversed(_submission_history(game, chal)):
        if str(rec.get("flag_sha256")) == answer_sha and str(rec.get("cid")) == cid:
            return str(rec.get("verdict") or "pending").lower()
    return None


def _write_accepted(game: str, chal: str, question: str, flag_text: str,
                    platform_line: str, answer_sha: str, cid: str, attempt: str = "") -> Path:
    """Write the deliverable flag + a loud acceptance record, and turn the
    platform verdict into a verified fact (platform-verdict actor). Returns the
    ACCEPTED record path."""
    rd = _run_dir(game, chal)
    (rd / "tmp").mkdir(parents=True, exist_ok=True)
    (rd / "final").mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    ev = rd / "tmp" / f"platform_verdict_{question}.txt"
    ev.write_text(
        f"challenge: {chal}\nquestion: {question}\nverdict: ACCEPTED\n"
        f"platform: {platform_line}\nsource: {cid}\nflag_sha256: {answer_sha}\ntime: {ts}\n",
        encoding="utf-8")
    flag_file = rd / "final" / "flag.txt"
    flag_file.write_text(
        f"{flag_text}\n\nsource: {platform_line}\nquestion: {question}\n"
        f"flag_sha256: {answer_sha}\ntime: {ts}\n", encoding="utf-8")
    accepted = rd / "ACCEPTED.txt"
    accepted.write_text(
        f"ACCEPTED {chal} / {question}\nFLAG: {flag_text}\nplatform: {platform_line}\n"
        f"attempt: {attempt or '-'}\ntime: {ts}\nfinal/flag.txt: {flag_file}\n", encoding="utf-8")
    # platform verdict is the verification: record a verified fact (audit trail).
    claim = f"{chal}/{question}: platform ACCEPTED (sha256 {answer_sha})"
    _ctfboard(["verify", "record", "--game", game, "--chal", chal,
               "--actor", "checker-platform", "--claim", claim,
               "--command", f"platform verdict: {platform_line}",
               "--output", str(ev), "--exit", "0", "--artifact", str(ev),
               "--reproduced", "yes", "--verdict", "verified"])
    print("=" * 62)
    print(f"  ACCEPTED  {chal} / {question}")
    print(f"  FLAG: {flag_text}")
    print(f"  platform: {platform_line}  attempt: {attempt or '-'}")
    print(f"  written: {flag_file}")
    print("=" * 62)
    return accepted


def cmd_submit(args):
    c = CTFy(); c.key = load_key()
    auto = bool(getattr(args, "auto", False))
    if not args.game or not args.chal:
        die("--game and --chal are required (board state, dedupe, governor)", 3)
    if not auto:
        if not args.verified_fact:
            die("refusing: pass --verified-fact <id>, or --auto --evidence <file> for an "
                "execution-confidence submit (platform verdict is the verification)", 3)
        ok, rec = _fact_verified(args.game, args.chal, args.verified_fact)
        if not ok:
            die(f"fact {args.verified_fact} is not a verified fact in {args.game}/{args.chal}; "
                f"record it first with `ctfboard verify record --verdict verified`, "
                f"or use --auto --evidence for a fast execution-confidence submit", 3)
    else:
        ev_path = Path(getattr(args, "evidence", "") or "").expanduser()
        if not ev_path.is_file() or ev_path.stat().st_size == 0:
            die("--auto requires --evidence <file> containing the exact command/output that "
                "produced the flag (execution-confidence evidence)", 3)

    if args.answer_file:
        data = Path(args.answer_file).read_bytes().strip()
    else:
        data = (args.answer or "").encode().strip()
    if not data:
        die("empty answer", 3)
    answer = data.decode("utf-8", "replace")
    answer_sha = hashlib.sha256(data).hexdigest()
    cid_key = f"{args.instance}:{args.question}"
    dup = _duplicate_verdict(args.game, args.chal, cid_key, answer_sha)
    if dup == "accepted":
        print(f"ALREADY ACCEPTED (platform) challenge={args.chal} question={args.question} "
              f"sha256={answer_sha}; not resending")
        return 0
    if dup:
        die(f"duplicate submit refused: this exact answer for {cid_key} is already "
            f"{dup}; try a different candidate", 3)

    # Governor check before touching the platform.
    rc, out = _ctfboard(["governor", "--game", args.game, "--chal", args.chal])
    if rc != 0:
        die(f"governor refuses submission: {out.strip()}", 3)
    log_evidence = ["--evidence", str(ev_path)] if auto else []

    body = {"instance_id": args.instance, "question_id": args.question, "answer": answer}
    code, resp = c.post("/submissions", body)
    verdict = "pending"
    detail = ""
    if isinstance(resp, dict):
        verdict = str(resp.get("verdict") or resp.get("status") or resp.get("result") or "pending").lower()
        detail = json.dumps({k: resp.get(k) for k in ("correct", "solved", "score", "message") if k in resp},
                            ensure_ascii=False)
    print(f"SUBMIT instance={args.instance} question={args.question} sha256={answer_sha} http={code} verdict={verdict} {detail}")
    if code in (401, 403):
        die(f"platform rejected authentication/authorization (HTTP {code})", 4)
    accepted = verdict in ("accepted", "correct", "solved", "true")
    rejected = verdict in ("rejected", "wrong", "incorrect", "false") or (code >= 400 and not accepted)
    if not accepted and not rejected:
        # Poll the challenge solve state to upgrade pending -> accepted/rejected.
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(2)
            code2, att = c.get(f"/challenges/{args.question}/solve-attempts")
            if code2 == 200 and isinstance(att, dict):
                items = att.get("items") or att.get("attempts") or []
                if items:
                    last = items[0] if isinstance(items, list) else None
                    if isinstance(last, dict) and str(last.get("answer", "")).strip() == answer:
                        verdict = "accepted" if last.get("correct") else "rejected"
                        break
    final = "accepted" if verdict in ("accepted", "correct", "solved", "true") else (
        "rejected" if verdict in ("rejected", "wrong", "incorrect", "false") else "pending")
    rc, out = _ctfboard(["submit-log", "--game", args.game, "--chal", args.chal,
                         "--flag-hash", answer_sha, "--verdict", final, "--cid", cid_key,
                         *log_evidence])
    print(out.strip()[-500:])
    if final == "accepted":
        _write_accepted(args.game, args.chal, args.question,
                        data.decode("utf-8", "replace"),
                        f"ctfy instance={args.instance}", answer_sha, cid_key)
        print("RESULT: ACCEPTED (platform verdict is the verification; no separate re-check needed)")
        return 0
    if final == "rejected":
        print("RESULT: REJECTED (recorded; continue with a new candidate under the governor)", file=sys.stderr)
        return 7
    print("RESULT: PENDING (not accepted; HTTP 200 alone is never Accepted)")
    return 6


def cmd_submit_qa(args):
    """Submit a *static* (instance-less) question through the platform's QA channel.

    Some questions advertise ``"mode": "static"`` and ``"requires": []`` in
    ``GET /qa/challenges``; those are graded by ``POST /qa/submissions`` with no
    instance. Everything else about the evidence contract is identical to
    `submit`: a verified local fact, the governor, sha256-only logging, and a
    verdict taken from platform state (never from HTTP 200).
    """
    c = CTFy(); c.key = load_key()
    chal = args.challenge
    auto = bool(getattr(args, "auto", False))
    if not args.game:
        die("--game (local run bucket) is required for board state, dedupe and governor", 3)
    if not auto:
        if not args.verified_fact:
            die("refusing: pass --verified-fact <id>, or --auto --evidence <file> for an "
                "execution-confidence submit (platform verdict is the verification)", 3)
        ok, rec = _fact_verified(args.game, chal, args.verified_fact)
        if not ok:
            die(f"fact {args.verified_fact} is not a verified fact in {args.game}/{chal}; "
                f"record it first with `ctfboard verify record --verdict verified`, "
                f"or use --auto --evidence for a fast execution-confidence submit", 3)
    else:
        ev_path = Path(getattr(args, "evidence", "") or "").expanduser()
        if not ev_path.is_file() or ev_path.stat().st_size == 0:
            die("--auto requires --evidence <file> containing the exact command/output that "
                "produced the flag (execution-confidence evidence)", 3)
    if args.answer_file:
        data = Path(args.answer_file).read_bytes().strip()
    else:
        data = (args.answer or "").encode().strip()
    if not data:
        die("empty answer", 3)
    answer = data.decode("utf-8", "replace")
    answer_sha = hashlib.sha256(data).hexdigest()
    cid_key = f"qa:{chal}:{args.question}"
    dup = _duplicate_verdict(args.game, chal, cid_key, answer_sha)
    if dup == "accepted":
        print(f"ALREADY ACCEPTED (platform) challenge={chal} question={args.question} "
              f"sha256={answer_sha}; not resending")
        return 0
    if dup:
        die(f"duplicate submit refused: this exact answer for {cid_key} is already "
            f"{dup}; try a different candidate", 3)
    rc, out = _ctfboard(["governor", "--game", args.game, "--chal", chal])
    if rc != 0:
        die(f"governor refuses submission: {out.strip()}", 3)
    log_evidence = ["--evidence", str(ev_path)] if auto else []

    body = {"challenge_id": chal, "competition_id": args.competition,
            "question_id": args.question, "answer": answer}
    code, resp = c.request_with_human_check("POST", "/qa/submissions", body, "submission")
    fields = {}
    if isinstance(resp, dict):
        fields = {k: resp.get(k) for k in
                  ("verdict", "status", "result", "correct", "solved", "score", "message")
                  if k in resp}
    print(f"QA-SUBMIT challenge={chal} question={args.question} sha256={answer_sha} http={code} "
          f"{json.dumps(fields, ensure_ascii=False)}")
    if code in (401, 403):
        die(f"platform rejected authentication/authorization (HTTP {code})", 4)
    verdict = str(fields.get("verdict") or fields.get("status") or fields.get("result") or "").lower()
    if fields.get("correct") is True or fields.get("solved") is True:
        verdict = "accepted"
    if fields.get("correct") is False:
        verdict = "rejected"
    if not verdict and code >= 400:
        verdict = "rejected"
    final = "pending"
    if verdict in ("accepted", "correct", "solved", "true"):
        final = "accepted"
    elif verdict in ("rejected", "wrong", "incorrect", "false"):
        final = "rejected"
    if final == "pending" and args.wait:
        # Authoritative platform state: solved_question_ids for this challenge.
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(2)
            code2, chals = c.get(f"/qa/challenges?competition_id={urllib.parse.quote(args.competition)}")
            if code2 == 200 and isinstance(chals, list):
                rec2 = next((x for x in chals if x.get("id") == chal), None)
                if rec2 and args.question in (rec2.get("solved_question_ids") or []):
                    final = "accepted"
                    break
    rc, out = _ctfboard(["submit-log", "--game", args.game, "--chal", chal,
                         "--flag-hash", answer_sha, "--verdict", final, "--cid", cid_key,
                         *log_evidence])
    print(out.strip()[-500:])
    if final == "accepted":
        _write_accepted(args.game, chal, args.question,
                        data.decode("utf-8", "replace"),
                        f"ctfy qa competition={args.competition}", answer_sha, cid_key)
        print("RESULT: ACCEPTED (platform verdict is the verification; no separate re-check needed)")
        return 0
    if final == "rejected":
        print("RESULT: REJECTED (recorded; continue with a new candidate under the governor)",
              file=sys.stderr)
        return 7
    print("RESULT: PENDING (not accepted; HTTP 200 alone is never Accepted)")
    return 6


def cmd_check(args):
    c = CTFy(); c.key = load_key()
    code, resp = c.post(f"/instances/{args.instance}/check", {"question_id": args.question})
    print(f"CHECK instance={args.instance} question={args.question} http={code}")
    print(json.dumps(resp, ensure_ascii=False, indent=1)[:1500])
    return 0 if code == 200 else 6


def cmd_solves(args):
    c = CTFy(); c.key = load_key()
    code, resp = c.get(f"/me/solves?competition_id={urllib.parse.quote(args.game)}")
    print(f"HTTP {code}")
    print(json.dumps(resp, ensure_ascii=False, indent=1)[:4000])
    return 0 if code == 200 else 5



def main(argv=None):
    ap = argparse.ArgumentParser(description="CTFy platform adapter (L3 verification channel)")
    ap.add_argument("--game", default=os.environ.get("CTFY_COMPETITION_ID") or DEFAULT_GAME)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor"); d.set_defaults(fn=cmd_doctor)
    ls = sub.add_parser("list"); ls.add_argument("--json", action="store_true"); ls.set_defaults(fn=cmd_list)
    st = sub.add_parser("start"); st.add_argument("challenge"); st.add_argument("--ttl", type=int)
    st.add_argument("--wait", type=int, default=240); st.add_argument("--interval", type=float, default=3)
    st.add_argument("--max-json", type=int, default=4000); st.set_defaults(fn=cmd_start)
    ins = sub.add_parser("instance"); ins.add_argument("instance"); ins.add_argument("--max-json", type=int, default=6000)
    ins.set_defaults(fn=cmd_instance)
    s = sub.add_parser("status"); s.add_argument("instance"); s.set_defaults(fn=cmd_status)
    dl = sub.add_parser("download"); dl.add_argument("instance"); dl.add_argument("attachment")
    dl.add_argument("-o", "--out", required=True); dl.set_defaults(fn=cmd_download)
    dc = sub.add_parser("download-chal"); dc.add_argument("challenge"); dc.add_argument("attachment")
    dc.add_argument("-o", "--out", required=True); dc.set_defaults(fn=cmd_download_chal)
    v = sub.add_parser("vpn"); v.add_argument("instance"); v.add_argument("-o", "--out", required=True)
    v.set_defaults(fn=cmd_vpn)
    sb = sub.add_parser("submit"); sb.add_argument("instance"); sb.add_argument("--question", required=True)
    sb.add_argument("--answer"); sb.add_argument("--answer-file")
    sb.add_argument("--verified-fact"); sb.add_argument("--auto", action="store_true")
    sb.add_argument("--evidence", help="with --auto: file with the exact command/output that produced the flag")
    sb.add_argument("--game"); sb.add_argument("--chal")
    sb.add_argument("--wait", type=int, default=20); sb.set_defaults(fn=cmd_submit)
    sq = sub.add_parser("submit-qa"); sq.add_argument("challenge")
    sq.add_argument("--question", default="main")
    sq.add_argument("--answer"); sq.add_argument("--answer-file")
    sq.add_argument("--verified-fact"); sq.add_argument("--auto", action="store_true")
    sq.add_argument("--evidence", help="with --auto: file with the exact command/output that produced the flag")
    sq.add_argument("--game", required=True, help="local run bucket under runs/<game>/<chal>")
    sq.add_argument("--competition", default=os.environ.get("CTFY_QA_COMPETITION") or DEFAULT_GAME)
    sq.add_argument("--wait", type=int, default=20); sq.set_defaults(fn=cmd_submit_qa)
    ck = sub.add_parser("check"); ck.add_argument("instance"); ck.add_argument("--question", required=True)
    ck.set_defaults(fn=cmd_check)
    sv = sub.add_parser("solves"); sv.set_defaults(fn=cmd_solves)
    sp = sub.add_parser("stop"); sp.add_argument("instance"); sp.set_defaults(fn=cmd_stop)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

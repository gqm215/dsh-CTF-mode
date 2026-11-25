#!/usr/bin/env python3
"""datacon.py — DataCon 竞赛训练营 adapter (training camp: major + jeopardy).

Platform: https://www.datacon.org.cn (Next.js training UI under /datacon-ui-infos).
Auth: SSO ticket -> `Token` in localStorage; exported once to
`~/.datacon/session.json` by the headed-login helper. Requests carry
`Token: <token>` and `Referer: https://www.datacon.org.cn/`. The API prefix
`/api/ctf/v3/tng` is rewritten by the web client to `/api03` (same for
competition-* -> /api04/*, platform -> /api01/*); this adapter talks to the
backend prefixes directly.

Commands:
  doctor                         identity + pool statistics
  list --type major|jeopardy     question list (JSON with answerStatus)
  show <id> --type major|jeopardy   question detail (form / attachments)
  submit-major <id> --answers FILE  answer a "major" training question (form2/form)
  submit-flag <id> --flag-file FILE   submit a jeopardy flag
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
SESSION = HOME / ".datacon" / "session.json"
CTF = HOME / ".agents" / "ctf-mode"
BOARD = CTF / "bin" / "ctfboard.py"
BASE = "https://www.datacon.org.cn"
REFERER = "https://www.datacon.org.cn/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def die(msg: str, code: int = 3):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_session() -> dict:
    if not SESSION.is_file():
        die(f"no DataCon session at {SESSION}; run tools/datacon_login.py once", 4)
    try:
        rec = json.loads(SESSION.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"unreadable session file: {exc}", 4)
    tok = str(rec.get("token") or "")
    if not tok:
        die("session file has no token; log in again", 4)
    return rec


def request(method: str, path: str, body: dict | None = None,
            form: dict | list[tuple[str, str]] | None = None,
            timeout: int = 30) -> tuple[int, dict | str]:
    sess = load_session()
    headers = {"Accept": "application/json", "Token": sess["token"],
               "Referer": REFERER, "User-Agent": sess.get("user_agent") or UA}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        pairs = form.items() if isinstance(form, dict) else form
        encoded: list[tuple[str, str]] = []
        for k, v in pairs:
            if isinstance(v, (list, tuple)):
                encoded.extend((str(k), str(x)) for x in v)
            else:
                encoded.append((str(k), str(v)))
        data = urllib.parse.urlencode(encoded).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, raw
    try:
        return 0, json.loads(raw)
    except Exception:
        return 0, raw


def api(method: str, path: str, **kw) -> dict:
    status, payload = request(method, path, **kw)
    if status not in (0, 200):
        die(f"HTTP {status} on {path}: {str(payload)[:200]}", 5)
    if isinstance(payload, str):
        die(f"non-JSON reply on {path}: {payload[:200]}", 5)
    return payload


def user_info() -> dict:
    payload = api("GET", "/api03/user-info")
    if isinstance(payload, dict) and payload.get("code") == 302:
        die("DataCon session expired (code 302 无效的token); run once: "
            f"python {CTF / 'tools' / 'datacon_login.py'}", 4)
    return payload.get("data") or {}


def cmd_doctor(args) -> int:
    me = user_info()
    stats = api("GET", "/api03/question/statistics").get("data") or {}
    print(f"user: {me.get('username')} / {me.get('nickname')} (id={me.get('userId')}) "
          f"score={me.get('totalScore')} ranking={me.get('ranking')}")
    for agg in stats.get("aggs") or []:
        print(f"pool {agg.get('type')}: questions={agg.get('questionCount')} "
              f"users={agg.get('numOfUsers')}")
    print("doctor: OK")
    return 0


def cmd_list(args) -> int:
    data = api("POST", "/api03/question/list",
               body={"type": args.type, "page": args.page, "limit": args.limit})
    items = (data.get("data") or {}).get("data") or []
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    print(f"{args.type}: {len(items)} items")
    for it in items:
        print(f"  {it.get('id'):<5} {it.get('level'):<8} {str(it.get('score')):<6} "
              f"{it.get('answerStatus')}  {it.get('name')}")
    return 0


def _parse_form(detail: dict) -> tuple[str, list[dict]]:
    st = str(detail.get("submitType") or "")
    raw = detail.get("questionForm")
    form = []
    if raw:
        try:
            form = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            form = []
    return st, form or []


def cmd_show(args) -> int:
    kind = args.type or "major"
    detail = api("GET", f"/api03/{kind}/question/{args.id}").get("data") or {}
    if args.json:
        print(json.dumps(detail, ensure_ascii=False, indent=1))
        return 0
    print(f"{kind}/{detail.get('id')}: {detail.get('name')}")
    print(f"level={detail.get('level')} score={detail.get('score')} "
          f"submitType={detail.get('submitType')} status={detail.get('answerStatus')}")
    st, form = _parse_form(detail)
    if form and isinstance(form, list) and form and isinstance(form[0], dict) and "formType" in form[0]:
        for f in form:
            print(f"  [{f.get('formType')}] field={f.get('fieldName')} required={f.get('required')} "
                  f"{f.get('name')}")
            for it in f.get("items") or []:
                print(f"      {it.get('key')}: {it.get('name')}")
    elif form:
        print("  form:", json.dumps(form, ensure_ascii=False)[:600])
    print("  desc:", re.sub(r"<[^>]+>", " ", str(detail.get("description") or ""))[:300])
    return 0


def _board_init(game: str, chal: str, title: str):
    state = CTF / "runs" / game / chal / "state.json"
    if state.exists():
        return
    import subprocess
    subprocess.run([sys.executable, str(BOARD), "init", "--game", game, "--chal", chal,
                    "--title", title, "--category", "datacon"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")


def _evidence(game: str, chal: str, name: str, text: str) -> Path:
    rd = CTF / "runs" / game / chal / "tmp"
    rd.mkdir(parents=True, exist_ok=True)
    p = rd / name
    p.write_text(text, encoding="utf-8")
    return p


def _submit_log(game: str, chal: str, sha: str, verdict: str, cid: str, ev: Path | None):
    import subprocess
    cmd = [sys.executable, str(BOARD), "submit-log", "--game", game, "--chal", chal,
           "--flag-hash", sha, "--verdict", verdict, "--cid", cid]
    if ev is not None:
        cmd += ["--evidence", str(ev)]
    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _accepted_files(game: str, chal: str, payload: str, platform: str) -> None:
    rd = CTF / "runs" / game / chal
    (rd / "final").mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (rd / "final" / "flag.txt").write_text(
        f"{payload}\n\nsource: {platform}\ntime: {ts}\n", encoding="utf-8")
    (rd / "ACCEPTED.txt").write_text(
        f"ACCEPTED {game}/{chal}\nPAYLOAD: {payload}\nplatform: {platform}\ntime: {ts}\n",
        encoding="utf-8")
    print("=" * 62)
    print(f"  ACCEPTED  {chal}")
    print(f"  PAYLOAD: {payload[:300]}")
    print(f"  platform: {platform}")
    print(f"  written: {rd / 'final' / 'flag.txt'}")
    print("=" * 62)


def cmd_submit_major(args) -> int:
    detail = api("GET", f"/api03/major/question/{args.id}").get("data") or {}
    if not detail.get("id"):
        die(f"major question {args.id} not found", 2)
    st, form = _parse_form(detail)
    if st not in ("form", "form2"):
        die(f"question {args.id} submitType={st!r}; only form/form2 is supported here "
            f"(remote/server_check needs the virtual environment)", 3)
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else {}
    if not isinstance(answers, dict):
        die("--answers must be a JSON object {fieldName: value|[values]}", 2)
    if st == "form":
        fields = ((form or {}).get("items") or [])
    else:
        fields = form
    name_by_field = {str(f.get("fieldName")): f for f in fields if isinstance(f, dict)}
    unknown = [k for k in answers if k not in name_by_field]
    if unknown:
        die(f"--answers contains unknown fields: {unknown}; known: {sorted(name_by_field)}", 2)
    missing = [k for k, f in name_by_field.items() if f.get("required") and k not in answers]
    if missing:
        die(f"missing required fields: {missing}", 2)
    # form payload: form -> answer:form.json; form2 -> fieldName=value pairs
    if st == "form":
        form_payload = {"answer:form.json": json.dumps(answers, ensure_ascii=False)}
    else:
        form_payload = [(k, v) for k, v in answers.items()]
    payload_hash = hashlib.sha256(json.dumps(answers, sort_keys=True).encode()).hexdigest()
    game, chal = args.game, args.chal or f"major-{args.id}"
    ev = None
    if game:
        _board_init(game, chal, str(detail.get("name") or chal))
        ev = _evidence(game, chal, f"answers_{args.id}.json",
                       json.dumps(answers, ensure_ascii=False, indent=1))
        _submit_log(game, chal, payload_hash, "pending", f"major:{args.id}", ev)
    status, resp = request("POST", f"/api03/major/question/{args.id}/submit-answer",
                           form=form_payload)
    if isinstance(resp, dict) and resp.get("code") == 200:
        msg = str(resp.get("msg") or "submitted")
        print(f"SUBMITTED major/{args.id}: {msg}")
        # poll platform for grading result (score/answerStatus)
        solved = False
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(3)
            d2 = api("GET", f"/api03/major/question/{args.id}").get("data") or {}
            st2 = str(d2.get("answerStatus") or "")
            me = user_info()
            if "解出" in st2 or "Solved" in st2 or float(me.get("totalScore") or 0) > args.base_score:
                solved = True
                break
        me = user_info()
        if game:
            _submit_log(game, chal, payload_hash, "accepted" if solved else "pending",
                        f"major:{args.id}", ev)
        if solved:
            if game:
                _accepted_files(game, chal, json.dumps(answers, ensure_ascii=False),
                                f"datacon major/{args.id} score={me.get('totalScore')}")
            else:
                print(f"ACCEPTED datacon major/{args.id} score={me.get('totalScore')}")
            return 0
        print(f"submitted; not graded as solved yet (score={me.get('totalScore')})")
        return 6
    print(f"SUBMIT reply: HTTP {status} {json.dumps(resp, ensure_ascii=False)[:400]}")
    return 1


def cmd_attach(args) -> int:
    rec = api("GET", f"/api03/jeopardy/question/{args.id}").get("data") or {}
    print(f"jeopardy/{args.id}: {rec.get('name')} hasAttachment={rec.get('hasAttachment')}")
    status, d = request("GET", f"/api03/jeopardy/question/{args.id}/attach")
    if isinstance(d, dict) and d.get("code") == 200 and (d.get("data") or {}).get("url"):
        url = d["data"]["url"]
        out = Path(args.out) if args.out else (CTF / "runs" / "datacon" / f"jp-{args.id}" / "artifacts")
        out.mkdir(parents=True, exist_ok=True)
        name = url.split("?")[0].rstrip("/").split("/")[-1] or f"{args.id}.bin"
        dst = out / name
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            dst.write_bytes(r.read())
        print(f"DOWNLOADED {dst} ({dst.stat().st_size} B)")
        return 0
    msg = d.get("msg") if isinstance(d, dict) else str(d)
    print(f"ATTACH-FAILED jeopardy/{args.id}: {msg}", file=sys.stderr)
    return 1


def cmd_take(args) -> int:
    d = api("GET", f"/api03/jeopardy/question/{args.id}/take").get("data") or {}
    print(json.dumps(d, ensure_ascii=False, indent=1))
    srv = d.get("server") or {}
    if srv.get("addr"):
        print(f"TARGET addr={srv.get('addr')} port={srv.get('port')} status={srv.get('taskStatus')}")
    return 0


def cmd_start(args) -> int:
    rec = api("GET", f"/api03/jeopardy/question/{args.id}").get("data") or {}
    print(f"jeopardy/{args.id}: {rec.get('name')} hasServer={rec.get('hasServer')}")
    status, resp = request("GET", f"/api03/jeopardy/question/{args.id}/take-server")
    if not (isinstance(resp, dict) and resp.get("code") in (200, 7003)):
        print(f"START-FAILED: {json.dumps(resp, ensure_ascii=False)[:300]}", file=sys.stderr)
        return 1
    if resp.get("code") == 7003:
        d = api("GET", "/api03/jeopardy/question/container-list").get("data") or {}
        print("already running containers:", json.dumps(d, ensure_ascii=False)[:500])
    deadline = time.time() + args.wait
    while time.time() < deadline:
        d = api("GET", f"/api03/jeopardy/question/{args.id}/take").get("data") or {}
        srv = d.get("server") or {}
        if srv.get("addr"):
            print(f"STARTED addr={srv.get('addr')} port={srv.get('port')} "
                  f"status={srv.get('taskStatus')} ret={srv.get('taskRet')}")
            return 0
        time.sleep(5)
    print(f"START-PENDING: no addr after {args.wait}s; poll `datacon.py take {args.id}`", file=sys.stderr)
    return 6


def cmd_stop(args) -> int:
    status, resp = request("POST", "/api03/jeopardy/question/delete-server",
                           form=[("questionIds", str(args.id))])
    print(f"STOP jeopardy/{args.id}: {json.dumps(resp, ensure_ascii=False)[:300]}")
    return 0 if isinstance(resp, dict) and resp.get("code") == 200 else 1


def cmd_containers(args) -> int:
    d = api("GET", "/api03/jeopardy/question/container-list").get("data") or {}
    print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0


def cmd_submit_flag(args) -> int:
    detail = api("GET", f"/api03/jeopardy/question/{args.id}").get("data") or {}
    flag = Path(args.flag_file).read_text(encoding="utf-8").strip() if args.flag_file else args.flag
    if not flag:
        die("provide --flag or --flag-file", 2)
    sha = hashlib.sha256(flag.encode()).hexdigest()
    game, chal = args.game, args.chal or f"jp-{args.id}"
    ev = None
    if game:
        _board_init(game, chal, str(detail.get("name") or chal))
        ev = _evidence(game, chal, f"flag_{args.id}.txt",
                       f"jeopardy: {detail.get('name')}\nflag_sha256: {sha}\n")
        _submit_log(game, chal, sha, "pending", f"jeopardy:{args.id}", ev)
    status, resp = request("POST", f"/api03/jeopardy/question/{args.id}/submit-flag",
                           form=[("flag", flag)])
    text = json.dumps(resp, ensure_ascii=False) if isinstance(resp, dict) else str(resp)
    print(f"SUBFLAG jeopardy/{args.id}: HTTP {status} {text[:300]}")
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    ok = isinstance(resp, dict) and resp.get("code") == 200 and bool(data.get("takeFlag"))
    if game:
        _submit_log(game, chal, sha, "accepted" if ok else "rejected", f"jeopardy:{args.id}", ev)
    if ok:
        if game:
            _accepted_files(game, chal, flag, f"datacon jeopardy/{args.id}")
        else:
            print(f"ACCEPTED datacon jeopardy/{args.id}")
        return 0
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DataCon training-camp adapter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor"); d.set_defaults(fn=cmd_doctor)

    ls = sub.add_parser("list")
    ls.add_argument("--type", choices=["major", "jeopardy"], default="major")
    ls.add_argument("--page", type=int, default=1)
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=cmd_list)

    sh = sub.add_parser("show"); sh.add_argument("id")
    sh.add_argument("--type", choices=["major", "jeopardy"], default="major")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(fn=cmd_show)

    sm = sub.add_parser("submit-major"); sm.add_argument("id")
    sm.add_argument("--answers", help="JSON object {fieldName: value|[values]}")
    sm.add_argument("--game"); sm.add_argument("--chal")
    sm.add_argument("--wait", type=int, default=20)
    sm.add_argument("--base-score", type=float, default=0.0)
    sm.set_defaults(fn=cmd_submit_major)

    at = sub.add_parser("attach"); at.add_argument("id")
    at.add_argument("-o", "--out", help="output directory")
    at.set_defaults(fn=cmd_attach)

    tk = sub.add_parser("take"); tk.add_argument("id"); tk.set_defaults(fn=cmd_take)
    stp = sub.add_parser("start"); stp.add_argument("id")
    stp.add_argument("--wait", type=int, default=90); stp.set_defaults(fn=cmd_start)
    sst = sub.add_parser("stop"); sst.add_argument("id"); sst.set_defaults(fn=cmd_stop)
    cl = sub.add_parser("containers"); cl.set_defaults(fn=cmd_containers)

    sf = sub.add_parser("submit-flag"); sf.add_argument("id")
    sf.add_argument("--flag"); sf.add_argument("--flag-file")
    sf.add_argument("--game"); sf.add_argument("--chal")
    sf.set_defaults(fn=cmd_submit_flag)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

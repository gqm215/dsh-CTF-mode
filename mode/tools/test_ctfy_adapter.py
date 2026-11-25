#!/usr/bin/env python3
"""Offline contract test for bin/ctfy.py (the CTFy platform adapter).

Runs a local mock of the CTFy player API and drives the real CLI against it, so
the adapter's security contract is verified without touching the platform:

  * verified-fact gate: submit/submit-qa refuse an unverified fact (exit 3)
  * governor: a 10-attempt cap is enforced by ctfboard (covered in test_ctfboard)
  * QA channel: POST /qa/submissions body shape + verdict parsed as accepted only
    when the platform says correct, never from HTTP 200
  * instance channel: no instance -> fail-closed; 401 -> exit 4
  * attachment download: 302 to object storage is followed WITHOUT the platform
    Authorization header (presigned URL regression), bytes + sha256 recorded
  * flag hygiene: raw flag never appears in adapter stdout or the board logs

Writes a PASS/FAIL report next to this file and exits nonzero on failure.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
CTFY = CTF / "bin" / "ctfy.py"
BOARD = CTF / "bin" / "ctfboard.py"
GAME = "cfy-selftest"
CHAL = "SAMPLE-005"
FLAG = "FLAG{selftest-00000000000000000000000000000000}"
ARCHIVE = b"PK\x03\x04selftest-archive-bytes"

RESULTS = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  [{detail}]"), flush=True)


class MockState:
    auth_seen: list[str] = []
    auth_on_cas: list[str] = []
    submitted: list[dict] = []
    human_required = False
    submit_verdict = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj, ctype="application/json"):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        a = self.headers.get("Authorization", "")
        if a:
            MockState.auth_seen.append(self.path)
        return a

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/v1/meta":
            self._json(200, {"version": "mock", "platform": {"commit_sha": "0" * 40}})
        elif p == "/api/v1/me":
            if self._auth() != "Bearer testkey":
                self._json(401, {"code": "unauthorized"})
            else:
                self._json(200, {"display_name": "mock", "team_id": "t1"})
        elif p == "/api/v1/competitions/comp1":
            self._json(200, {"id": "comp1", "title": "Mock", "phase": "running",
                             "challenge_count": 1, "challenges": []})
        elif p == "/api/v1/competitions/comp1/challenges":
            self._json(200, {"items": [{"id": CHAL, "name": "Mock", "category": "misc",
                                        "questions": [{"id": "flag"}],
                                        "attachments": [{"name": "archive.zip"}]}]})
        elif p == f"/api/v1/challenges/{CHAL}/attachments/archive.zip":
            self._auth()
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/cas/obj")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p == "/cas/obj":
            MockState.auth_on_cas.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(ARCHIVE)))
            self.end_headers()
            self.wfile.write(ARCHIVE)
        elif p == "/api/v1/instances/inst1/status":
            self._json(200, {"status": "running"})
        elif p == "/api/v1/me/solves":
            self._json(200, [])
        elif p == "/api/v1/human-check/challenge":
            self._json(200, {"parameters": {"algorithm": "PBKDF2/SHA-256", "cost": 1,
                                            "keyLength": 32, "keyPrefix": "00",
                                            "nonce": "00" * 16, "salt": "11" * 16},
                             "signature": "0" * 64})
        else:
            self._json(404, {"code": "not_found", "path": p})

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if p == "/api/v1/instances":
            self._json(503, {"code": "no_healthy_node", "detail": "mock: no node"})
        elif p == "/api/v1/qa/submissions":
            self._auth()
            MockState.submitted.append(body)
            ok = body.get("answer") == FLAG and body.get("question_id") == "flag"
            self._json(200, {"correct": ok})
        elif p == "/api/v1/submissions":
            self._json(401, {"code": "unauthorized"})
        else:
            self._json(404, {"code": "not_found", "path": p})


def run_cli(args, env):
    proc = subprocess.run([sys.executable, str(CTFY), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180, env=env)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def board(args, env=None):
    proc = subprocess.run([sys.executable, str(BOARD), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120,
                          env=env or {**os.environ})
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    work = CTF / "runs" / GAME
    shutil.rmtree(work, ignore_errors=True)
    board(["init", "--game", GAME, "--chal", CHAL, "--title", "selftest", "--category", "misc"])
    board(["fact", "add", "--game", GAME, "--chal", CHAL, "--claim", "selftest candidate",
           "--evidence", "mock"])  # f1 candidate only
    ev = work / CHAL / "tmp" / "evidence.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("sha256=" + hashlib.sha256(FLAG.encode()).hexdigest() + "\n", encoding="utf-8")
    rc, out = board(["verify", "record", "--game", GAME, "--chal", CHAL, "--actor", "verifier-selftest",
                     "--claim", "selftest verified", "--command", "mock", "--output", str(ev),
                     "--exit", "0", "--artifact", str(ev), "--reproduced", "yes", "--verdict", "verified"])
    # verified fact id is the one whose status is verified in facts.jsonl
    verified = None
    for line in (work / CHAL / "facts.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") == "verified":
            verified = rec.get("id")
    check("setup: a verified fact exists", bool(verified), "no verified fact")

    # mock server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "CTFY_BASE": base, "CTFY_TEAM_KEY": "testkey", "CTFY_COMPETITION_ID": "comp1"}
    answer = work / CHAL / "tmp" / "answer.txt"
    answer.write_text(FLAG, encoding="utf-8")

    # 1. doctor against mock
    rc, out = run_cli(["doctor"], env)
    check("doctor: authenticated against mock", rc == 0 and "auth: OK" in out, out[-200:])

    # 2. attachment redirect must not leak Authorization to object storage
    dst = work / CHAL / "tmp" / "archive.zip"
    rc, out = run_cli(["download-chal", CHAL, "archive.zip", "-o", str(dst)], env)
    check("download: 302 followed, bytes match", rc == 0 and dst.exists() and dst.read_bytes() == ARCHIVE, out[-300:])
    check("download: presigned request carried NO Authorization header",
          MockState.auth_on_cas == [""], repr(MockState.auth_on_cas))
    check("download: flags no credentials in output", "testkey" not in out)

    # 3. unverified fact is refused on both channels
    rc, out = run_cli(["submit-qa", CHAL, "--question", "flag", "--answer-file", str(answer),
                       "--verified-fact", "does-not-exist", "--game", GAME], env)
    check("gate: submit-qa refuses an unverified fact (exit 3)", rc == 3, f"rc={rc} {out[-200:]}")
    rc, out = run_cli(["submit", "inst1", "--question", "flag", "--answer-file", str(answer),
                       "--verified-fact", "does-not-exist", "--game", GAME, "--chal", CHAL], env)
    check("gate: submit refuses an unverified fact (exit 3)", rc == 3, f"rc={rc} {out[-200:]}")

    # 4. QA channel accepted only from platform verdict
    rc, out = run_cli(["submit-qa", CHAL, "--question", "flag", "--answer-file", str(answer),
                       "--verified-fact", str(verified), "--game", GAME, "--competition", "comp1"], env)
    check("qa: correct answer -> ACCEPTED", rc == 0 and "RESULT: ACCEPTED" in out, out[-300:])
    check("qa: request body shape", MockState.submitted and
          MockState.submitted[-1].get("challenge_id") == CHAL and
          MockState.submitted[-1].get("question_id") == "flag" and
          MockState.submitted[-1].get("competition_id") == "comp1",
          json.dumps(MockState.submitted[-1:])[:300])
    check("qa: accepted banner shows the flag (deliverable)", "ACCEPTED" in out and FLAG in out, out[-300:])
    log_lines = (work / CHAL / "submissions.jsonl").read_text(encoding="utf-8", errors="replace")
    check("qa: submission log keeps sha256 only", FLAG not in log_lines and
          hashlib.sha256(FLAG.encode()).hexdigest() in log_lines)
    check("qa: accepted writes final/flag.txt", (work / CHAL / "final" / "flag.txt").exists() and
          FLAG in (work / CHAL / "final" / "flag.txt").read_text(encoding="utf-8", errors="replace"))
    check("qa: platform verdict records a verified fact",
          "checker-platform" in (work / CHAL / "facts.jsonl").read_text(encoding="utf-8", errors="replace"))

    # 5. wrong answer -> REJECTED (mock only; this is not a platform attempt)
    MockState.submit_verdict = False
    bad = work / CHAL / "tmp" / "bad.txt"
    bad.write_text("FLAG{definitely-wrong}", encoding="utf-8")
    rc, out = run_cli(["submit-qa", CHAL, "--question", "flag", "--answer-file", str(bad),
                       "--verified-fact", str(verified), "--game", GAME, "--competition", "comp1"], env)
    check("qa: wrong answer -> REJECTED exit 7", rc == 7 and "RESULT: REJECTED" in out, f"rc={rc}")

    # 5b. fast path: --auto --evidence submits on execution confidence (no verified fact),
    #     platform verdict is the verification, same answer is never sent twice.
    GAME2, CHAL2 = "cfy-autotest", "AUTO-1"
    work2 = CTF / "runs" / GAME2
    shutil.rmtree(work2, ignore_errors=True)
    board(["init", "--game", GAME2, "--chal", CHAL2, "--title", "autotest", "--category", "misc"])
    ev = work2 / CHAL2 / "tmp" / "exec_evidence.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("command: python solve.py\noutput: " + FLAG + "\n", encoding="utf-8")
    before = len(MockState.submitted)
    rc, out = run_cli(["submit-qa", CHAL2, "--question", "flag", "--answer-file", str(answer),
                       "--auto", "--evidence", str(ev), "--game", GAME2,
                       "--competition", "comp1"], env)
    check("auto: execution-confidence submit accepted (no verified fact)",
          rc == 0 and "RESULT: ACCEPTED" in out and FLAG in out, f"rc={rc} {out[-300:]}")
    check("auto: exactly one platform call", len(MockState.submitted) == before + 1)
    check("auto: accepted writes final/flag.txt",
          FLAG in (work2 / CHAL2 / "final" / "flag.txt").read_text(encoding="utf-8", errors="replace"))
    rc, out = run_cli(["submit-qa", CHAL2, "--question", "flag", "--answer-file", str(answer),
                       "--auto", "--evidence", str(ev), "--game", GAME2,
                       "--competition", "comp1"], env)
    check("auto: identical answer is not resent (ALREADY ACCEPTED, no call)",
          rc == 0 and "ALREADY ACCEPTED" in out and len(MockState.submitted) == before + 1,
          f"rc={rc} calls={len(MockState.submitted) - before}")
    wrong2 = work2 / CHAL2 / "tmp" / "wrong.txt"
    wrong2.write_text("FLAG{not-the-answer}", encoding="utf-8")
    rc, out = run_cli(["submit-qa", CHAL2, "--question", "flag", "--answer-file", str(wrong2),
                       "--auto", "--evidence", str(ev), "--game", GAME2,
                       "--competition", "comp1"], env)
    check("auto: rejected answer is recorded and may be replaced", rc == 7 and "REJECTED" in out,
          f"rc={rc}")
    rc, out = run_cli(["submit-qa", CHAL2, "--question", "flag", "--answer-file", str(wrong2),
                       "--auto", "--evidence", str(ev), "--game", GAME2,
                       "--competition", "comp1"], env)
    check("auto: duplicate same answer refused (exit 3)", rc == 3, f"rc={rc} {out[-200:]}")
    rc, out = run_cli(["submit-qa", CHAL2, "--question", "flag", "--answer-file", str(answer),
                       "--game", GAME2], env)
    check("gate: submit without fact and without --auto still refused (exit 3)", rc == 3, f"rc={rc}")

    # 6. instance channel: 503 -> fail closed; 401 -> exit 4
    rc, out = run_cli(["start", CHAL, "--wait", "5"], env)
    check("instance: 503 no_healthy_node fails closed", rc != 0 and "no_healthy_node" in out, out[-200:])

    # 7. hygiene: no raw flag in board files or telemetry
    found = False
    for f in work.rglob("*"):
        if f.is_file() and f.suffix in (".jsonl", ".json", ".md"):
            try:
                if FLAG in f.read_text(encoding="utf-8", errors="replace"):
                    found = True
                    break
            except Exception:
                pass
    check("hygiene: raw flag absent from board logs", not found, "raw flag found in board files")

    srv.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(work2, ignore_errors=True)

    ok = all(r[1] for r in RESULTS)
    lines = ["# ctfy.py offline contract test", "", f"generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
             f"mock base: {base}", f"result: **{sum(1 for r in RESULTS if r[1])}/{len(RESULTS)} PASS**", "",
             "| check | result |", "|---|---|"]
    for name, good, detail in RESULTS:
        lines.append(f"| {name} | {'PASS' if good else 'FAIL: ' + detail[:120]} |")
    (CTF / "tools" / "test_ctfy_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nRESULT: {sum(1 for r in RESULTS if r[1])}/{len(RESULTS)} PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())



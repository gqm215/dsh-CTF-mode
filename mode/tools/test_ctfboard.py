#!/usr/bin/env python3
"""End-to-end test for the CTF-mode state plane (ctfboard.py + ctf-submit.py).

Runs entirely inside a TEMP, clearly marked game/chal id:

    game=selftest  chal=gate-001   ->   ~/.agents/ctf-mode/runs/selftest/gate-001

It removes any previous selftest run at startup (idempotent re-runs), scrubs
selftest lines from the global telemetry file, then drives the real CLIs with
subprocess and asserts:

  (a) init + fact add + fact list + deadend add roundtrip, dedupe, status/path/log
  (b) an executor is DENIED writing a verified fact / verified verdict (exit 2)
  (c) an injected false positive ("flag from HTTP 200", reproduced=no, exit=1,
      --verdict verified) is downgraded to candidate and never becomes verified;
      a proper verifier record (reproduced=yes, exit=0, artifact) becomes verified
  (d) submit-log refuses with no verified fact (exit 3) and denies the 11th attempt
      after 10; the submit governor guidance appears at 3 attempts
  (e) board.db exists (delegated to blackboard.py), verify.md holds evidence
      blocks, run + global telemetry JSONL lines exist, state.json matches schema
  (f) ctf-submit.py: dry-run, unverified-fact refusal (exit 3), 401 handling with
      a stub gzctf shim (exit 4, no attempt consumed), pending/HTTP-200 text is
      NOT accepted (exit 6), raw flag never persisted (sha256 only)
  (g) `gzctf doctor` is run once to record the live platform state (401 expected,
      non-blocking)

Prints PASS/FAIL lines, writes the transcript to tools/test_ctfboard_report.md,
and exits nonzero on any failure.  The selftest run directory is kept as
evidence and is clearly marked; delete it with:

    Remove-Item -Recurse -Force ~\\.agents\\ctf-mode\\runs\\selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]  # ~/.agents/ctf-mode
BIN = ROOT / "bin"
CTFBOARD = BIN / "ctfboard.py"
CTFSUBMIT = BIN / "ctf-submit.py"
REPORT = Path(__file__).resolve().with_name("test_ctfboard_report.md")

GAME = "selftest"
CHAL = "gate-001"
RUN = ROOT / "runs" / GAME / CHAL
RAW_FLAG = "selftest{not-a-real-flag-0x0}"
FLAG_HASH = hashlib.sha256(RAW_FLAG.strip().encode("utf-8")).hexdigest()

PYTHON = sys.executable
STARTED = datetime.now().astimezone()

# Keep the deliverable directories free of __pycache__ from the local import below.
sys.dont_write_bytecode = True

TRANSCRIPT: List[str] = []
RESULTS: List[Tuple[bool, str, str]] = []


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def log(line: str = "") -> None:
    print(line)
    TRANSCRIPT.append(line)


def log_block(text: str) -> None:
    for line in text.rstrip().splitlines():
        log(line)


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    if ok:
        log(f"PASS {name}")
    else:
        log(f"FAIL {name}" + (f"  [{detail}]" if detail else ""))


def _base_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _run(command: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None,
         timeout: float = 180) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_base_env(env),
        cwd=str(cwd or ROOT),
        timeout=timeout,
        check=False,
    )
    return proc


def run_board(args: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    command = [PYTHON, str(CTFBOARD)] + args
    log("$ " + " ".join([Path(CTFBOARD).name] + args))
    proc = _run(command, env)
    if proc.stdout.strip():
        log_block(proc.stdout)
    if proc.stderr.strip():
        log_block("[stderr] " + proc.stderr.rstrip().replace("\n", "\n[stderr] "))
    log(f"[exit {proc.returncode}]")
    return proc


def run_submit(args: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    command = [PYTHON, str(CTFSUBMIT)] + args
    log("$ " + " ".join([Path(CTFSUBMIT).name] + args))
    proc = _run(command, env)
    if proc.stdout.strip():
        log_block(proc.stdout)
    if proc.stderr.strip():
        log_block("[stderr] " + proc.stderr.rstrip().replace("\n", "\n[stderr] "))
    log(f"[exit {proc.returncode}]")
    return proc


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def read_state() -> Dict[str, Any]:
    return json.loads((RUN / "state.json").read_text(encoding="utf-8"))


def scrub_selftest_global_telemetry() -> int:
    """Drop previous selftest lines from the global telemetry file (idempotency)."""
    path = ROOT / "traces" / "events.jsonl"
    if not path.is_file():
        return 0
    kept: List[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            kept.append(line)
            continue
        if isinstance(record, dict) and record.get("game") == GAME and record.get("chal") == CHAL:
            removed += 1
            continue
        kept.append(line)
    path.write_text("".join(line + "\n" for line in kept), encoding="utf-8", newline="\n")
    return removed


def main() -> int:
    log("# ctfboard / ctf-submit end-to-end selftest")
    log("")
    log(f"- started: {STARTED.isoformat(timespec='seconds')}")
    log(f"- python: {sys.version.split()[0]} ({PYTHON})")
    log(f"- ctf root: {ROOT}")
    log(f"- selftest run: {RUN}  (game={GAME}, chal={CHAL}; clearly disposable)")
    log(f"- platform: gzctf CLI + ~/.gzctf/config.json (session.json is never read by these tools)")
    log("")

    # -- setup: remove previous selftest run, scrub global telemetry ----------
    if RUN.exists():
        shutil.rmtree(RUN)
    removed = scrub_selftest_global_telemetry()
    log(f"[setup] removed previous selftest run dir; scrubbed {removed} old selftest line(s) "
        "from the global telemetry file")
    log("")

    # =====================================================================
    # (a) init / fact / deadend roundtrip
    # =====================================================================
    log("## (a) init + fact add + fact list + deadend add roundtrip")
    proc = run_board(["init", "--game", GAME, "--chal", CHAL, "--title", "Gate selftest",
                      "--category", "misc"])
    check("(a1) init exits 0", proc.returncode == 0, f"exit {proc.returncode}")
    check("(a2) init reports INIT marker", "INIT selftest/gate-001" in proc.stdout, proc.stdout)
    expected = ["board.db", "verify.md", "state.json", "traces/events.jsonl",
                "tmp", "draft", "final", "artifacts"]
    missing = [item for item in expected if not (RUN / item).exists()]
    check("(a3) init creates the full challenge tree", not missing, f"missing: {missing}")

    proc = run_board(["init", "--game", GAME, "--chal", CHAL])
    attempts_after_reinit = int(read_state()["attempts"])
    check("(a4) init is idempotent (no reset of counters, no duplicate seed)",
          proc.returncode == 0 and attempts_after_reinit == 0
          and (RUN / "board.db").is_file(), proc.stderr)

    proc = run_board(["path", "--game", GAME, "--chal", CHAL])
    check("(a5) path prints the challenge directory",
          proc.stdout.strip() == str(RUN), proc.stdout)

    proc = run_board(["fact", "add", "--game", GAME, "--chal", CHAL,
                      "--claim", "HTTP 200 from /admin implies the flag is in the response",
                      "--evidence", "curl -i http://target/admin -> 200 OK",
                      "--source", "exec"])
    check("(a6) fact add candidate exits 0 and prints FACT f1",
          proc.returncode == 0 and proc.stdout.strip().startswith("FACT f1 candidate"), proc.stdout)

    proc = run_board(["fact", "add", "--game", GAME, "--chal", CHAL,
                      "--claim", "  http 200 from /ADMIN implies the flag is in the response  ",
                      "--evidence", "same claim, different spacing/case",
                      "--source", "exec"])
    check("(a7) identical normalized candidate claim dedupes",
          proc.returncode == 0 and proc.stdout.strip() == "DUPLICATE f1", proc.stdout)
    check("(a8) dedupe did not create a second fact",
          len(read_jsonl(RUN / "facts.jsonl")) == 1,
          f"{len(read_jsonl(RUN / 'facts.jsonl'))} facts")

    proc = run_board(["fact", "list", "--game", GAME, "--chal", CHAL])
    check("(a9) fact list shows the candidate row",
          proc.returncode == 0 and "f1" in proc.stdout and "candidate" in proc.stdout, proc.stdout)

    proc = run_board(["deadend", "add", "--game", GAME, "--chal", CHAL,
                      "--scope", "directory brute force on /admin",
                      "--tests", "12 wordlists x 2 methods",
                      "--invariant", "all 404/302 with no length difference",
                      "--reopen-if", "a new parameter or auth bypass is discovered"])
    check("(a10) deadend add exits 0 and prints DEADEND d1",
          proc.returncode == 0 and proc.stdout.strip().startswith("DEADEND d1"), proc.stdout)

    proc = run_board(["deadend", "add", "--game", GAME, "--chal", CHAL,
                      "--scope", "directory brute force on /admin",
                      "--tests", "same scope again",
                      "--invariant", "same",
                      "--reopen-if", "same"])
    check("(a11) deadend dedupes by scope",
          proc.returncode == 0 and proc.stdout.strip() == "DUPLICATE d1", proc.stdout)

    proc = run_board(["deadend", "add", "--game", GAME, "--chal", CHAL,
                      "--scope", "missing-reopen-if probe",
                      "--tests", "one", "--invariant", "two"])
    check("(a12) deadend missing --reopen-if exits 2",
          proc.returncode == 2 and "--reopen-if" in proc.stderr, proc.stderr)

    proc = run_board(["log", "--game", GAME, "--chal", CHAL,
                      "--event", "skill_load", "--data", '{"skill": "ctf-submit"}'])
    check("(a13) log accepts arbitrary telemetry events",
          proc.returncode == 0 and proc.stdout.strip() == "LOG skill_load", proc.stdout)
    proc = run_board(["log", "--game", GAME, "--chal", CHAL,
                      "--event", "tool_call", "--data", "{not-json"])
    check("(a14) log rejects malformed --data JSON (exit 2)", proc.returncode == 2, proc.stderr)

    proc = run_board(["log", "--game", GAME, "--chal", CHAL,
                      "--event", "route", "--data", '{"from": "web", "to": "reverse"}'])
    global_names_now = {str(r.get("event")) for r in read_jsonl(ROOT / "traces" / "events.jsonl")
                        if r.get("game") == GAME and r.get("chal") == CHAL}
    run_names_now = {str(r.get("event")) for r in read_jsonl(RUN / "traces" / "events.jsonl")}
    check("(a14b) route telemetry mirrors to the global file; skill_load stays run-local",
          proc.returncode == 0 and "route" in global_names_now
          and "skill_load" in run_names_now and "skill_load" not in global_names_now,
          f"global={sorted(global_names_now)} run={sorted(run_names_now)}")

    proc = run_board(["status", "--game", GAME, "--chal", CHAL])
    check("(a15) status prints compact summary (challenge/phase/facts/deadends/attempts)",
          proc.returncode == 0
          and "CHALLENGE selftest/gate-001" in proc.stdout
          and "PHASE execute" in proc.stdout
          and "DEADENDS 1" in proc.stdout
          and "ATTEMPTS 0/10" in proc.stdout,
          proc.stdout)
    proc = run_board(["governor", "--game", GAME, "--chal", CHAL])
    check("(a16) governor reports attempts/remaining/approval",
          proc.returncode == 0 and "attempts=0" in proc.stdout
          and "remaining=10" in proc.stdout and "approval_required=no" in proc.stdout,
          proc.stdout)
    log("")

    # =====================================================================
    # (b) executor cannot write verified
    # =====================================================================
    log("## (b) executor writing verified is DENIED")
    proc = run_board(["fact", "add", "--game", GAME, "--chal", CHAL,
                      "--claim", "executor should never verify this",
                      "--evidence", "no reproducible evidence",
                      "--status", "verified"])
    check("(b1) fact add --status verified as executor exits 2",
          proc.returncode == 2 and "DENIED" in proc.stderr and "verifier" in proc.stderr,
          proc.stderr)
    facts = read_jsonl(RUN / "facts.jsonl")
    check("(b2) executor proposal wrote no fact at all",
          all("executor should never verify this" not in str(f.get("claim")) for f in facts))
    check("(b3) no verified fact exists after the denial",
          not any(f.get("status") == "verified" for f in facts))
    log("")

    # =====================================================================
    # (d1) submit-log refuses before any verified fact exists
    # =====================================================================
    log("## (d1) submit-log refuses with no verified fact")
    proc = run_board(["submit-log", "--game", GAME, "--chal", CHAL,
                      "--flag-hash", "a" * 64, "--verdict", "pending", "--cid", "9999"])
    check("(d1) submit-log exits 3 with no verified fact",
          proc.returncode == 3 and "REFUSED" in proc.stderr and "verified" in proc.stderr,
          proc.stderr)
    check("(d2) refused submit-log did not consume an attempt",
          int(read_state()["attempts"]) == 0, str(read_state()["attempts"]))
    log("")

    # =====================================================================
    # (c) injected false positive is caught; proper verifier record passes
    # =====================================================================
    log("## (c) false-positive gate: HTTP 200 claim is downgraded, proper verifier record verifies")
    proc = run_board(["verify", "record", "--game", GAME, "--chal", CHAL,
                      "--claim", "flag from HTTP 200 response",
                      "--command", "curl -s -o /dev/null -w '%{http_code}' http://target/admin",
                      "--output", "200",
                      "--exit", "1",
                      "--reproduced", "no",
                      "--verdict", "verified"])
    check("(c1) insufficient evidence downgrades verdict=verified to candidate (exit 0)",
          proc.returncode == 0 and "VERIFY v1 verdict=candidate" in proc.stdout,
          proc.stdout + proc.stderr)
    check("(c2) downgrade prints a WARN with reasons",
          "WARN" in proc.stderr and "downgraded" in proc.stderr, proc.stderr)
    facts = read_jsonl(RUN / "facts.jsonl")
    fp = next((f for f in facts if "flag from http 200" in str(f.get("claim")).lower()), None)
    check("(c3) false-positive claim is recorded as candidate, never verified",
          fp is not None and fp.get("status") == "candidate",
          json.dumps(fp, ensure_ascii=False) if fp else "missing")
    check("(c4) board still has zero verified facts", 
          not any(f.get("status") == "verified" for f in facts))

    # executor with otherwise-complete evidence still cannot self-verify
    proc = run_board(["verify", "record", "--game", GAME, "--chal", CHAL,
                      "--claim", "executor authority probe",
                      "--command", "echo probe", "--output", "probe",
                      "--exit", "0", "--reproduced", "yes", "--verdict", "verified"])
    check("(c5) executor requesting verified with good-looking evidence is DENIED (exit 2)",
          proc.returncode == 2 and "DENIED" in proc.stderr, proc.stderr)
    check("(c6) denied verify record left no evidence block",
          len(read_jsonl(RUN / "verifies.jsonl")) == 1,
          f"{len(read_jsonl(RUN / 'verifies.jsonl'))} verify records")

    artifact = RUN / "artifacts" / "proof.txt"
    artifact.write_text("selftest artifact: local reproduction output\n", encoding="utf-8")
    proc = run_board(["verify", "record", "--game", GAME, "--chal", CHAL,
                      "--claim", "decoded flag is reproduced locally from the artifact",
                      "--command", "python solve.py --input artifacts/proof.txt",
                      "--output", "reproduction ok: artifact hash matches (selftest)",
                      "--exit", "0",
                      "--reproduced", "yes",
                      "--artifact", str(artifact),
                      "--verdict", "verified",
                      "--actor", "verifier-selftest"])
    check("(c7) proper verifier record becomes verified (exit 0)",
          proc.returncode == 0 and "VERIFY v2 verdict=verified" in proc.stdout,
          proc.stdout + proc.stderr)
    check("(c8) verified verdict promotes/creates exactly one verified fact",
          len([f for f in read_jsonl(RUN / "facts.jsonl") if f.get("status") == "verified"]) == 1,
          json.dumps(read_jsonl(RUN / "facts.jsonl"), ensure_ascii=False)[:600])

    # a verifier asking for verified with a non-existent artifact is downgraded too
    proc = run_board(["verify", "record", "--game", GAME, "--chal", CHAL,
                      "--claim", "artifact-backed claim with a missing artifact",
                      "--command", "python solve.py",
                      "--output", "ok",
                      "--exit", "0", "--reproduced", "yes",
                      "--artifact", str(RUN / "artifacts" / "does-not-exist.bin"),
                      "--verdict", "verified", "--actor", "verifier-selftest"])
    check("(c11) missing --artifact downgrades verdict=verified to candidate (exit 0)",
          proc.returncode == 0 and "VERIFY v3 verdict=candidate" in proc.stdout
          and "artifact" in proc.stderr and "downgraded" in proc.stderr,
          proc.stdout + proc.stderr)
    verified_count = len([f for f in read_jsonl(RUN / "facts.jsonl")
                          if f.get("status") == "verified"])
    check("(c12) missing-artifact record did not create a verified fact", verified_count == 1,
          str(verified_count))

    verify_md = (RUN / "verify.md").read_text(encoding="utf-8")
    check("(c9) verify.md has three evidence blocks (downgraded, verified, missing-artifact)",
          verify_md.count("## Claim") == 3, f"{verify_md.count('## Claim')} blocks")
    check("(c10) evidence blocks contain command/output/exit/artifact sha256/reproduced/verdict/timestamp/actor",
          all(token in verify_md for token in
              ["- command:", "- output:", "- exit:", "sha256:", "- reproduced:",
               "- timestamp:", "- actor:", "## Verdict", "verified", "candidate"]),
          "missing evidence fields")
    log("")

    # =====================================================================
    # (f) ctf-submit.py gates (before attempts are consumed)
    # =====================================================================
    log("## (f) ctf-submit.py: verified-fact gate, dry-run, 401, HTTP-200-is-not-Accepted")
    flag_file = RUN / "tmp" / "dummy.flag"
    flag_file.write_text(RAW_FLAG + "\n", encoding="utf-8")
    facts = read_jsonl(RUN / "facts.jsonl")
    verified_id = next(f["id"] for f in facts if f.get("status") == "verified")
    candidate_id = next(f["id"] for f in facts if f.get("status") == "candidate")

    proc = run_submit(["--game", GAME, "--chal", CHAL,
                       "--verified-fact", verified_id, "--cid", "9999",
                       "--flag-file", str(flag_file), "--dry-run"])
    check("(f1) dry-run prints the gzctf command and makes no call",
          proc.returncode == 0 and "DRY-RUN" in proc.stdout
          and "gzctf" in proc.stdout and "flag_sha256=" in proc.stdout
          and RAW_FLAG not in proc.stdout, proc.stdout)
    check("(f2) dry-run did not consume an attempt",
          int(read_state()["attempts"]) == 0, str(read_state()["attempts"]))
    check("(f3) dry-run did not create submissions.jsonl",
          not (RUN / "submissions.jsonl").is_file())

    proc = run_submit(["--game", GAME, "--chal", CHAL,
                       "--verified-fact", candidate_id, "--cid", "9999",
                       "--flag", RAW_FLAG])
    check("(f4) unverified fact is refused with exit 3",
          proc.returncode == 3 and "REFUSED" in proc.stderr, proc.stderr)

    proc = run_submit(["--game", GAME, "--chal", CHAL,
                       "--verified-fact", "f-does-not-exist", "--cid", "9999",
                       "--flag", RAW_FLAG])
    check("(f5) unknown fact id is refused with exit 3", proc.returncode == 3, proc.stderr)

    proc = run_submit(["--verify-prefix", "selftest", "--dry-run"])
    check("(f5b) final-review mode dry-run prints the `gzctf verify --prefix` command",
          proc.returncode == 0 and "mode=verify" in proc.stdout
          and "gzctf" in proc.stdout and "verify" in proc.stdout,
          proc.stdout)

    # stub gzctf shim: satisfies the adapter without touching the real platform
    stub_dir = Path(tempfile.mkdtemp(prefix="ctf-selftest-gzctf-"))
    stub = stub_dir / "gzctf.cmd"
    stub.write_text(
        "@echo off\r\n"
        "echo chal=9999 submit_id=None STATUS=HTTP401\r\n"
        "exit /b 1\r\n",
        encoding="ascii",
    )
    env401 = {"PATH": str(stub_dir) + os.pathsep + os.environ.get("PATH", "")}
    proc = run_submit(["--game", GAME, "--chal", CHAL,
                       "--verified-fact", verified_id, "--cid", "9999",
                       "--flag-file", str(flag_file)], env=env401)
    check("(f6) platform 401 is reported clearly (exit 4) and points at gzctf login",
          proc.returncode == 4 and "401" in proc.stderr and "gzctf login" in proc.stderr,
          proc.stderr)
    check("(f7) 401 path consumed no governor attempt and logged no submission",
          int(read_state()["attempts"]) == 0
          and not (RUN / "submissions.jsonl").is_file(),
          f"attempts={read_state()['attempts']}")

    # pending (platform 200-like non-terminal) must NOT be accepted; it is logged pending
    stub.write_text(
        "@echo off\r\n"
        "echo chal=9999 submit_id=None STATUS=Pending\r\n"
        "exit /b 0\r\n",
        encoding="ascii",
    )
    proc = run_submit(["--game", GAME, "--chal", CHAL,
                       "--verified-fact", verified_id, "--cid", "9999",
                       "--flag-file", str(flag_file)], env=env401)
    check("(f8) non-terminal status is NOT accepted (exit 6, verdict=pending, no 200-as-accepted)",
          proc.returncode == 6 and "verdict=pending" in proc.stdout
          and "http_200_is_not_accepted=yes" in proc.stdout
          and "accepted_by_solved_set=no" in proc.stdout,
          proc.stdout + proc.stderr)
    submissions = read_jsonl(RUN / "submissions.jsonl")
    check("(f9) pending submission logged via submit-log with sha256 only",
          len(submissions) == 1 and submissions[0].get("verdict") == "pending"
          and submissions[0].get("flag_sha256") == FLAG_HASH
          and RAW_FLAG not in json.dumps(submissions, ensure_ascii=False),
          json.dumps(submissions, ensure_ascii=False))
    check("(f10) pending submission consumed exactly one attempt",
          int(read_state()["attempts"]) == 1, str(read_state()["attempts"]))
    shutil.rmtree(stub_dir, ignore_errors=True)

    # reset the selftest counter so the governor loop below starts from 0
    state = read_state()
    state["attempts"] = 0
    (RUN / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    (RUN / "submissions.jsonl").unlink(missing_ok=True)
    log("[setup] reset the selftest attempt counter to 0 before the governor loop")
    log("")

    # =====================================================================
    # (d2) governor: guidance at 3, deny the 11th after 10
    # =====================================================================
    log("## (d2) submit governor: guidance at 3 attempts, deny the 11th after 10")
    guidance_seen = False
    loop_ok = True
    for attempt in range(1, 11):
        proc = run_board(["submit-log", "--game", GAME, "--chal", CHAL,
                          "--flag-hash", FLAG_HASH, "--verdict", "rejected",
                          "--cid", "9999"])
        if proc.returncode != 0 or f"attempt={attempt}/10" not in proc.stdout:
            loop_ok = False
            break
        if "GUIDANCE" in proc.stderr and "independent review" in proc.stderr:
            guidance_seen = True
        if attempt == 3:
            check("(d3) governance guidance appears after the 3rd attempt",
                  "GUIDANCE" in proc.stderr and "independent review" in proc.stderr,
                  proc.stderr)
    check("(d4) ten submit-log calls are accepted (attempts 1..10)", loop_ok)
    check("(d5) independent-review/approval guidance was printed", guidance_seen)

    proc = run_board(["submit-log", "--game", GAME, "--chal", CHAL,
                      "--flag-hash", FLAG_HASH, "--verdict", "rejected", "--cid", "9999"])
    check("(d6) the 11th submit-log is denied with exit 3",
          proc.returncode == 3 and "REFUSED" in proc.stderr and "exhausted" in proc.stderr,
          proc.stderr)
    check("(d7) attempts stay capped at 10",
          int(read_state()["attempts"]) == 10, str(read_state()["attempts"]))
    proc = run_board(["governor", "--game", GAME, "--chal", CHAL])
    check("(d8) governor reports exhausted/denied state",
          "attempts=10" in proc.stdout and "remaining=0" in proc.stdout
          and "denied=yes" in proc.stdout, proc.stdout)
    log("")

    # =====================================================================
    # (e) artifacts on disk: board.db, verify.md, telemetry, state.json, schemas
    # =====================================================================
    log("## (e) artifacts: board.db (blackboard delegation), verify.md, telemetry, state.json")
    check("(e1) board.db exists", (RUN / "board.db").is_file(), str(RUN / "board.db"))
    kinds: List[str] = []
    verified_events = 0
    try:
        connection = sqlite3.connect(str(RUN / "board.db"))
        try:
            kinds = [row[0] for row in connection.execute("SELECT DISTINCT kind FROM events")]
            verified_events = connection.execute(
                "SELECT COUNT(*) FROM events WHERE kind='fact_added' AND verified=1"
            ).fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        log(f"[sqlite error] {exc}")
    check("(e2) board.db holds delegated fact/dead_end records",
          "fact_added" in kinds and "dead_end" in kinds, str(kinds))
    check("(e3) board.db records exactly one verified fact_added event",
          verified_events == 1, str(verified_events))

    run_events = read_jsonl(RUN / "traces" / "events.jsonl")
    run_event_names = {str(record.get("event")) for record in run_events}
    check("(e4) run telemetry has fact/deadend/verify/submit events",
          {"fact", "deadend", "verify", "submit"} <= run_event_names, str(sorted(run_event_names)))
    check("(e5) telemetry records have the required shape {ts,event,game,chal,actor,data}",
          all(set(record) == {"ts", "event", "game", "chal", "actor", "data"} for record in run_events),
          "bad telemetry record shape")
    global_events = [
        record for record in read_jsonl(ROOT / "traces" / "events.jsonl")
        if record.get("game") == GAME and record.get("chal") == CHAL
    ]
    global_names = {str(record.get("event")) for record in global_events}
    check("(e6) global telemetry mirrors fact/deadend/verify/submit for this run",
          {"fact", "deadend", "verify", "submit"} <= global_names, str(sorted(global_names)))

    state = read_state()
    required_state = {"challenge_id", "game", "title", "category", "phase", "budget",
                      "spent", "attempts", "created", "updated"}
    check("(e7) state.json has the SPEC §4 state keys",
          required_state <= set(state), str(sorted(set(state))))
    check("(e8) state.json phase advanced past execute (now submit/record)",
          state.get("phase") in ("submit", "record"), str(state.get("phase")))

    verify_md = (RUN / "verify.md").read_text(encoding="utf-8")
    check("(e9) verify.md retains the L1/L2/L3 contract text and evidence blocks",
          "三层验证" in verify_md and verify_md.count("## Verdict") == 3,
          "contract text or verdict count")

    # schemas: valid JSON draft-07 and usable by ctfboard's own validator
    sys.path.insert(0, str(ROOT / "bin"))
    import ctfboard  # noqa: E402  (local import; the test drives the same code)
    schema_ok = True
    for name in ("challenge.schema.json", "fact.schema.json", "verify.schema.json"):
        try:
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            schema_ok = schema_ok and schema.get("$schema", "").endswith("draft-07/schema#")
            schema_ok = schema_ok and bool(schema.get("required")) and bool(schema.get("properties"))
        except (OSError, ValueError):
            schema_ok = False
    check("(e10) three draft-07 schemas exist and are strict JSON objects", schema_ok)
    try:
        ctfboard.validate_record({"id": "f1", "claim": "c", "evidence": "e", "status": "candidate",
                                  "source": "exec", "actor": "executor",
                                  "ts": ctfboard.now_iso(), "artifact": None},
                                 "fact.schema.json")
        ctfboard.validate_record({"claim": "c", "command": "cmd", "output": "out", "exit": 0,
                                  "artifact_sha256": None, "reproduced": "no",
                                  "verdict": "candidate", "actor": "executor",
                                  "ts": ctfboard.now_iso()}, "verify.schema.json")
        ctfboard.validate_record({"id": "web-01", "game": "g", "title": "t", "category": "web",
                                  "budget": {"tokens": 1, "minutes": 1}, "phase": "intake"},
                                 "challenge.schema.json")
        schemas_validate = True
    except ctfboard.CliError as exc:
        log(f"[schema validator] {exc}")
        schemas_validate = False
    check("(e11) sample fact/verify/challenge records pass the strict schemas", schemas_validate)
    check("(e12) every stored fact/verify record passes its schema",
          _all_records_valid(ctfboard))

    check("(e13) raw flag never persisted outside the selftest input file",
          _raw_flag_leak_check(flag_file))
    log("")

    # =====================================================================
    # (h) live platform state: gzctf doctor once (401 expected, non-blocking)
    # =====================================================================
    log("## (h) live platform state: gzctf doctor (401 expected, non-blocking)")
    doctor = _run(["gzctf", "doctor"], timeout=90) if os.name != "nt" else \
        _run(["cmd", "/c", "gzctf", "doctor"], timeout=90)
    if doctor.stdout.strip():
        log_block(doctor.stdout)
    if doctor.stderr.strip():
        log_block("[stderr] " + doctor.stderr.rstrip())
    log(f"[exit {doctor.returncode}]")
    doctor_text = doctor.stdout + doctor.stderr
    check("(h1) gzctf doctor runs and records platform reachability",
          "平台可达" in doctor_text or "platform" in doctor_text.lower(), doctor_text[:300])
    logged_out = ("401" in doctor_text) or ("未登录" in doctor_text) or ("warn" in doctor_text.lower())
    check("(h2) gzctf doctor exits without blocking even while logged out",
          doctor.returncode in (0, 1), f"exit {doctor.returncode}")
    log(f"[platform-state] {'logged out (401) - submit path exits 4 until `gzctf login` is run' if logged_out else 'logged in'}")
    log("")

    # =====================================================================
    # Summary
    # =====================================================================
    passed = sum(1 for ok, _name, _detail in RESULTS if ok)
    failed = len(RESULTS) - passed
    log("## Summary")
    log("")
    for ok, name, detail in RESULTS:
        log(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail and not ok else ""))
    log("")
    log(f"RESULT {passed}/{len(RESULTS)} PASS, {failed} FAIL")
    log("")
    log("The selftest run directory is intentionally kept as evidence and is clearly marked:")
    log(f"  {RUN}")
    log("Delete it with: Remove-Item -Recurse -Force ~\\.agents\\ctf-mode\\runs\\selftest")
    log("")
    log("Re-run: python " + str(Path(__file__).resolve()))

    _write_report(passed, failed)
    return 0 if failed == 0 else 1


def _all_records_valid(ctfboard: Any) -> bool:
    ok = True
    for fact in read_jsonl(RUN / "facts.jsonl"):
        try:
            ctfboard.validate_record(fact, "fact.schema.json")
        except ctfboard.CliError as exc:
            log(f"[schema] stored fact invalid: {exc}")
            ok = False
    for verify in read_jsonl(RUN / "verifies.jsonl"):
        try:
            ctfboard.validate_record(verify, "verify.schema.json")
        except ctfboard.CliError as exc:
            log(f"[schema] stored verify invalid: {exc}")
            ok = False
    return ok


def _raw_flag_leak_check(input_flag_file: Path) -> bool:
    """The raw flag must not appear in any persisted record except the input file."""
    needles = [RAW_FLAG, RAW_FLAG + "\n"]
    for path in RUN.rglob("*"):
        if not path.is_file() or path.resolve() == input_flag_file.resolve():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(needle.encode("utf-8") in data for needle in needles):
            log(f"[leak] raw flag found in {path}")
            return False
    return True


def _write_report(passed: int, failed: int) -> None:
    lines = [
        "# ctfboard.py / ctf-submit.py end-to-end selftest report",
        "",
        f"- generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- started: {STARTED.isoformat(timespec='seconds')}",
        f"- python: {sys.version.split()[0]} ({PYTHON})",
        f"- ctf-mode root: `{ROOT}`",
        f"- selftest run dir: `{RUN}` (game=`{GAME}`, chal=`{CHAL}`; disposable, kept as evidence)",
        f"- result: **{passed}/{passed + failed} PASS, {failed} FAIL**",
        "",
        "## PASS/FAIL list",
        "",
    ]
    for ok, name, detail in RESULTS:
        line = f"- {'PASS' if ok else 'FAIL'} — {name}"
        if detail and not ok:
            line += f"  \n  `{detail[:400]}`"
        lines.append(line)
    lines.extend([
        "",
        "## Notes",
        "",
        "- Records are stored by `~/.agents/skills/multi-agentcollaboration-blackboard/blackboard.py`",
        "  (`--db runs/selftest/gate-001/board.db --run-id selftest/gate-001 --actor ...`).",
        "- `ctf-submit.py` is exercised with a stub `gzctf.cmd` shim so no request or fake flag",
        "  ever reaches the live platform; `gzctf doctor` is run separately once for the live state.",
        "- The live platform session is currently logged out (HTTP 401): ctf-submit exits 4 with a",
        "  clear `gzctf login -u <user>` instruction and never attempts authentication.",
        "- The attempt counter is reset once inside the test (documented in the transcript) so the",
        "  governor loop can start from 0 after the pending-submission check.",
        "- Re-run: `python " + str(Path(__file__).resolve()) + "`",
        "",
        "## Transcript",
        "",
        "```text",
    ])
    lines.extend(TRANSCRIPT)
    lines.append("```")
    lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())

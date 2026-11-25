#!/usr/bin/env python3
"""Offline test for bin/ctf-audit.py (the compliance auditor / 监察员).

Builds a synthetic run that follows the rules and then injects one violation at a
time, asserting the auditor reports the right code and exits nonzero. The auditor
must never decide flag correctness; these tests only cover behavior discipline.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
AUDIT = CTF / "bin" / "ctf-audit.py"
BOARD = CTF / "bin" / "ctfboard.py"
GAME = "audit-test"
FLAG = "FLAG{audit-test-0000000000000000000000000}"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  [{detail}]"))


def run(cmd, timeout=120):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def board(*a):
    return run([str(BOARD), *a])


def audit(chal):
    return run([str(AUDIT), "--game", GAME, "--chal", chal])


def fresh(chal):
    board("init", "--game", GAME, "--chal", chal, "--title", chal, "--category", "misc")


def good_run(chal):
    fresh(chal)
    rd = CTF / "runs" / GAME / chal
    ev = rd / "tmp" / "evidence.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("command: python solve.py\noutput: " + FLAG + "\n", encoding="utf-8")
    sha = hashlib.sha256(FLAG.encode()).hexdigest()
    rc, out = board("submit-log", "--game", GAME, "--chal", chal, "--flag-hash", sha,
                    "--verdict", "accepted", "--cid", f"qa:{chal}:flag", "--evidence", str(ev))
    (rd / "final").mkdir(parents=True, exist_ok=True)
    (rd / "final" / "flag.txt").write_text(FLAG + "\n", encoding="utf-8")
    (rd / "final" / "writeup.md").write_text("# writeup\n" + FLAG + "\n", encoding="utf-8")
    (rd / "ACCEPTED.txt").write_text(f"ACCEPTED {chal}\nFLAG: {FLAG}\n", encoding="utf-8")
    return rd, sha


def main():
    run([str(AUDIT), "--bless"])
    shutil.rmtree(CTF / "runs" / GAME, ignore_errors=True)

    # 1. clean run -> OK
    chal = "clean"
    good_run(chal)
    rc, out = audit(chal)
    check("clean: no breach (exit 0)", rc == 0 and "verdict: **OK**" in out, out[-400:])

    # 2. raw flag leaked into a log/state file -> FLAG_HYGIENE breach
    chal = "flagleak"
    rd, sha = good_run(chal)
    with (rd / "facts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "f9", "claim": "leak " + FLAG, "status": "candidate"}) + "\n")
    rc, out = audit(chal)
    check("flag leak: FLAG_HYGIENE breach (exit 1)", rc == 1 and "FLAG_HYGIENE" in out, out[-400:])

    # 3. same (cid, sha) submitted twice -> IDEMPOTENCY breach
    chal = "dupe"
    rd, sha = good_run(chal)
    with (rd / "submissions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "x", "cid": f"qa:{chal}:flag", "flag_sha256": sha,
                             "verdict": "rejected", "attempt": 2, "actor": "executor",
                             "basis": "platform-auto", "evidence": str(rd / "tmp" / "evidence.txt")}) + "\n")
    rc, out = audit(chal)
    check("duplicate answer: IDEMPOTENCY breach (exit 1)", rc == 1 and "IDEMPOTENCY" in out, out[-400:])

    # 4. unproven success: final/flag.txt with no accepted verdict -> ACCEPTANCE breach
    chal = "unproven"
    fresh(chal)
    rd = CTF / "runs" / GAME / chal
    (rd / "final").mkdir(parents=True, exist_ok=True)
    (rd / "final" / "flag.txt").write_text(FLAG + "\n", encoding="utf-8")
    rc, out = audit(chal)
    check("unproven success: ACCEPTANCE breach (exit 1)", rc == 1 and "ACCEPTANCE" in out, out[-400:])

    # 5. verified fact written by a non-verifier actor -> ACCEPTANCE breach
    chal = "rogueverifier"
    rd, sha = good_run(chal)
    with (rd / "facts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "f7", "claim": "rogue verified", "status": "verified",
                             "actor": "executor", "source": "fact"}) + "\n")
    rc, out = audit(chal)
    check("rogue verified actor: ACCEPTANCE breach (exit 1)", rc == 1 and "ACCEPTANCE" in out, out[-400:])

    # 6. credential material in the run dir -> CREDENTIAL_HYGIENE breach
    chal = "credleak"
    rd, sha = good_run(chal)
    (rd / "tmp" / "notes.txt").write_text("token pf_" + "A" * 32 + "\n", encoding="utf-8")
    rc, out = audit(chal)
    check("credential leak: CREDENTIAL_HYGIENE breach (exit 1)",
          rc == 1 and "CREDENTIAL_HYGIENE" in out, out[-400:])

    # 7. fallback basis: a verifier recorded the fact before submitting -> OK
    chal = "verifiedbasis"
    fresh(chal)
    rd = CTF / "runs" / GAME / chal
    sha = hashlib.sha256(FLAG.encode()).hexdigest()
    ev = rd / "tmp" / "verify_evidence.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(f"command: python solve.py\nexit: 0\nsha256: {sha}\nreproduced: yes\n",
                  encoding="utf-8")
    board("verify", "record", "--game", GAME, "--chal", chal, "--actor", "verifier-team",
          "--claim", f"{chal}: independent reproduction", "--command", "python solve.py",
          "--output", str(ev), "--exit", "0", "--artifact", str(ev),
          "--reproduced", "yes", "--verdict", "verified")
    board("submit-log", "--game", GAME, "--chal", chal, "--flag-hash", sha,
          "--verdict", "accepted", "--cid", f"qa:{chal}:flag")
    (rd / "final").mkdir(parents=True, exist_ok=True)
    (rd / "final" / "flag.txt").write_text(FLAG + "\n", encoding="utf-8")
    (rd / "final" / "writeup.md").write_text("# writeup\n" + FLAG + "\n", encoding="utf-8")
    (rd / "ACCEPTED.txt").write_text(f"ACCEPTED {chal}\nFLAG: {FLAG}\n", encoding="utf-8")
    rc, out = audit(chal)
    check("verified-fact basis: no breach (exit 0)", rc == 0 and "verdict: **OK**" in out, out[-500:])

    shutil.rmtree(CTF / "runs" / GAME, ignore_errors=True)
    ok = all(r[1] for r in RESULTS)
    lines = ["# ctf-audit.py offline test", "",
             f"generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
             f"result: **{sum(1 for r in RESULTS if r[1])}/{len(RESULTS)} PASS**", "",
             "| check | result |", "|---|---|"]
    for name, good, detail in RESULTS:
        lines.append(f"| {name} | {'PASS' if good else 'FAIL: ' + detail[:120]} |")
    (CTF / "tools" / "test_ctf_audit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nRESULT: {sum(1 for r in RESULTS if r[1])}/{len(RESULTS)} PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

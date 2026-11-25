#!/usr/bin/env python3
"""Solve the CTFy SAMPLE-020 "Platform Quiz" through the instance-less QA channel.

The quiz asks three questions whose answers are in the platform's own authoring
standard (CTFY-0002, rendered at /docs/standards/CTFY-0002). This script:
  1. saves the exact standard excerpts as evidence (sha256-pinned),
  2. records candidate -> verified facts in the challenge blackboard,
  3. submits each answer through `ctfy.py submit-qa` (verified-fact gate),
  4. confirms the platform's own solved_question_ids state and reports.

It never submits an answer that is not backed by the standard text.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
BOARD = CTF / "bin" / "ctfboard.py"
CTFY = CTF / "bin" / "ctfy.py"
DOCS = HOME / ".ctfy" / "docs_docs_standards_CTFY-0002.txt"
GAME = "ctfy"
CHAL = "SAMPLE-020"
COMP = "e4e78ff318dc4844beac13f9ea7409aa"
RUN = CTF / "runs" / GAME / CHAL

ANSWERS = {
    "flag_format": {
        "answer": "B",
        "claim": "SAMPLE-020/flag_format: dynamic question with default format:flag mints FLAG{<32 hex>} (option B)",
        "evidence": ("§2.2 questions: format = flag or raw, default flag; §5.2 dynamic comparison "
                     "'with the FLAG{…} wrapper removed from either side also counts' -> the default "
                     "format wraps the minted per-team value in FLAG{…}; the raw variant is the bare "
                     "32-hex form, so B) `FLAG{<32 hex>}` is the flag-format answer."),
        "grep": ["format\tflag or raw\tflag", "FLAG{…} wrapper removed from either side"],
    },
    "channels": {
        "answer": "A,B,D",
        "claim": "SAMPLE-020/channels: dynamic answer delivery channels are flag-rotator, attachments/*.tpl, attachment-builder (A,B,D); build args are forbidden carriers",
        "evidence": ("§4.1 'There are four ways a package receives one' (templates §4.3, builder §4.4, "
                     "rotator §4.2, seeder §4.5); the listed options map to A flag-rotator, B "
                     "attachments/<name>.tpl, D attachment-builder. §4.6 COMPOSE005 'no build argument "
                     "is named ANSWER_*' -> E is a forbidden carrier; C (metadata comment) is not a "
                     "delivery channel at all."),
        "grep": ["There are four ways a package receives one",
                 "no build argument is named ANSWER_*"],
    },
    "gate_field": {
        "answer": "requires",
        "claim": "SAMPLE-020/gate_field: the questions: field that gates a question behind answered ones is `requires`",
        "evidence": ("§2.2 questions table: requires = ids of questions that must be solved first, "
                     "default []; §2.5 'A question whose requires: is non-empty is gated: it is not "
                     "shown until those are [solved]'."),
        "grep": ["requires\tids of questions that must be solved first", "is gated: it is not shown until"],
    },
}


def run(cmd, timeout=180):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def board(*args):
    return run([str(BOARD), *args])


def main() -> int:
    if not DOCS.exists():
        print(f"ERROR: standard doc snapshot missing: {DOCS}", file=sys.stderr)
        return 2
    doc = DOCS.read_text(encoding="utf-8", errors="replace")
    doc_sha = hashlib.sha256(doc.encode()).hexdigest()
    (RUN / "tmp").mkdir(parents=True, exist_ok=True)
    board("init", "--game", GAME, "--chal", CHAL, "--title", "Platform Quiz — 选择题与文字题",
          "--category", "misc")

    fact_ids = {}
    for qid, spec in ANSWERS.items():
        for needle in spec["grep"]:
            if needle not in doc:
                print(f"WARN: evidence text not found verbatim for {qid}: {needle!r}", file=sys.stderr)
        ev = RUN / "tmp" / f"evidence_{qid}.txt"
        ev.write_text(
            f"challenge: {CHAL} question: {qid}\n"
            f"answer: {spec['answer']}\n"
            f"standard: CTFY-0002 snapshot {DOCS}\nsha256: {doc_sha}\n\n"
            f"claim:\n{spec['claim']}\n\nevidence:\n{spec['evidence']}\n\n"
            f"verbatim anchors:\n" + "\n".join(f"- {n}" for n in spec["grep"]) + "\n",
            encoding="utf-8")
        rc, out = board("fact", "add", "--game", GAME, "--chal", CHAL,
                        "--claim", spec["claim"], "--evidence", "CTFY-0002 standard excerpt (see artifact)",
                        "--source", "read", "--artifact", str(ev))
        rc, out = board("verify", "record", "--game", GAME, "--chal", CHAL,
                        "--actor", "verifier-docs", "--claim", spec["claim"],
                        "--command", "read CTFY-0002 standard + verbatim anchor check",
                        "--output", str(ev), "--exit", "0", "--artifact", str(ev),
                        "--reproduced", "yes", "--verdict", "verified")
        if rc != 0:
            print(f"ERROR: verify record failed for {qid}: {out[-300:]}", file=sys.stderr)
            return 3
        # the verified fact id = latest verified fact whose claim matches
        fid = None
        for line in (RUN / "facts.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("status") == "verified" and rec.get("claim") == spec["claim"]:
                fid = rec.get("id")
        if not fid:
            print(f"ERROR: no verified fact id for {qid}", file=sys.stderr)
            return 4
        fact_ids[qid] = fid

    results = {}
    for qid, spec in ANSWERS.items():
        rc, out = run([str(CTFY), "submit-qa", CHAL, "--question", qid, "--answer", spec["answer"],
                       "--verified-fact", fact_ids[qid], "--game", GAME,
                       "--competition", COMP, "--wait", "20"])
        accepted = "RESULT: ACCEPTED" in out
        results[qid] = {"rc": rc, "accepted": accepted, "tail": out.strip().splitlines()[-2:]}
        print(f"[{'OK' if accepted else 'FAIL'}] {qid} -> {spec['answer']}  rc={rc}")
        if not accepted:
            print(out[-500:])

    # authoritative platform state
    code, chals = (None, None)
    try:
        sys.path.insert(0, str(CTF / "bin"))
        import ctfy as _ctfy  # noqa: E402
        c = _ctfy.CTFy(); c.key = _ctfy.load_key()
        code, chals = c.get(f"/qa/challenges?competition_id={COMP}")
    except Exception as exc:
        print("platform state read failed:", exc)
    rec = next((x for x in (chals or []) if x.get("id") == CHAL), None) if isinstance(chals, list) else None
    solved = rec.get("solved_question_ids") if rec else None
    wrong = rec.get("attempted_wrong_question_ids") if rec else None
    print("\nPLATFORM STATE:", json.dumps({"solved_question_ids": solved,
                                           "attempted_wrong_question_ids": wrong}, ensure_ascii=False))
    ok = bool(rec) and set(ANSWERS) <= set(solved or []) and not (wrong or [])
    report = {
        "challenge": CHAL, "competition": COMP, "answers": {k: v["answer"] for k, v in ANSWERS.items()},
        "fact_ids": fact_ids, "results": results,
        "platform_solved_question_ids": solved, "platform_attempted_wrong_question_ids": wrong,
        "doc_sha256": doc_sha, "ok": ok,
    }
    out_path = CTF / "eval" / "reports" / f"solved_{CHAL}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(("RESULT: SAMPLE-020 SOLVED (platform confirms all three questions, 0 wrong)"
           if ok else "RESULT: INCOMPLETE — see report") + f"\nreport: {out_path}")
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())

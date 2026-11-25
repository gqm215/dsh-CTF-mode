#!/usr/bin/env python3
"""qa_runner.py — plumbing for a CTFy QA speed run (benchmark MCQ pools).

The agent answers; this tool only lists unsolved questions and submits batches
through the normal adapter (ctfy.py submit-qa --auto --evidence), so every
accepted answer still gets the board record, deliverable files and audit trail.

Commands:
  list   --competition ID [--limit N] [--offset N] [--json] [--max-desc N]
         print unsolved single-select/static questions as JSON (skips solved and
         already-wrong questions).
  submit --competition ID --answers FILE [--game GAME]
         FILE = [{"challenge": "SECQA-0001", "question": "answer",
                  "answer": "A", "reason": "..."}, ...]
         creates the run bucket, writes an execution-evidence file, calls the
         adapter, and prints one compact line per item.

Exit codes: 0 all submitted items accepted or terminal; 2 usage; 3 gate/dup;
4 auth; 5 platform; 7 any rejected; 8 runner error.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
CTFY = CTF / "bin" / "ctfy.py"
BOARD = CTF / "bin" / "ctfboard.py"
DEFAULT_GAME = "ctfy-qa"


def load_ctfy():
    spec = importlib.util.spec_from_file_location("ctfy_mod", CTFY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ctfy_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def run(cmd, timeout=120):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cmd_list(args):
    m = load_ctfy()
    c = m.CTFy(); c.key = m.load_key()
    code, data = c.get(f"/qa/challenges?competition_id={args.competition}")
    if code != 200 or not isinstance(data, list):
        print(f"ERROR listing QA challenges: HTTP {code}: {str(data)[:200]}", file=sys.stderr)
        return 5
    rows = []
    for ch in data:
        solved = set(ch.get("solved_question_ids") or [])
        wrong = set(ch.get("attempted_wrong_question_ids") or [])
        desc = re.sub(r"\s+", " ", str(ch.get("description") or "")).strip()[: args.max_desc]
        for q in ch.get("questions") or []:
            qid = str(q.get("id") or "answer")
            if qid in solved or qid in wrong:
                continue
            rows.append({
                "challenge": ch.get("id"),
                "name": ch.get("name") or "",
                "question": qid,
                "mode": q.get("mode"),
                "prompt": q.get("prompt"),
                "choices": q.get("choices"),
                "description": desc,
            })
    start = max(0, args.offset)
    batch = rows[start:start + max(0, args.limit)]
    payload = {"competition": args.competition, "unsolved_total": len(rows),
               "offset": start, "count": len(batch), "items": batch}
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0


def ensure_bucket(game, chal, title):
    state = CTF / "runs" / game / chal / "state.json"
    if state.exists():
        return 0
    rc, out = run([str(BOARD), "init", "--game", game, "--chal", chal,
                   "--title", title or chal, "--category", "qa"], timeout=60)
    return rc


def cmd_submit(args):
    if not Path(args.answers).is_file():
        print(f"ERROR --answers not found: {args.answers}", file=sys.stderr)
        return 2
    try:
        items = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR bad answers JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(items, list) or not items:
        print("ERROR answers JSON must be a non-empty list", file=sys.stderr)
        return 2
    game = args.game or DEFAULT_GAME
    total = accepted = rejected = errors = gate = 0
    t0 = time.time()
    for item in items:
        chal = str(item.get("challenge") or "").strip()
        question = str(item.get("question") or "answer").strip()
        answer = str(item.get("answer") or "").strip()
        reason = re.sub(r"\s+", " ", str(item.get("reason") or "")).strip()[:200]
        if not chal or not answer:
            print(f"SKIP incomplete item: {item}", file=sys.stderr)
            continue
        total += 1
        rc = ensure_bucket(game, chal, item.get("name") or chal)
        if rc != 0:
            print(f"ERROR bucket init failed for {chal} (exit {rc})", file=sys.stderr)
            errors += 1
            continue
        rd = CTF / "runs" / game / chal
        ev_dir = rd / "tmp"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev = ev_dir / f"qa_evidence_{question}.txt"
        ev.write_text(
            "tool: qa_runner.py submit\n"
            f"challenge: {chal}\nquestion: {question}\n"
            f"prompt: {item.get('prompt') or ''}\n"
            f"answer: {answer}\nreason: {reason}\n"
            f"answer_sha256: {hashlib.sha256(answer.encode()).hexdigest()}\n",
            encoding="utf-8")
        rc, out = run([str(CTFY), "submit-qa", chal, "--question", question,
                       "--answer", answer, "--auto", "--evidence", str(ev),
                       "--game", game, "--competition", args.competition])
        line = out.strip().splitlines()[-1] if out.strip() else ""
        if rc == 0:
            accepted += 1
            print(f"ACCEPTED {chal}/{question} answer={answer} ({line[:120]})")
        elif rc == 7:
            rejected += 1
            print(f"REJECTED {chal}/{question} answer={answer} -> skip, no retry")
        elif rc == 3:
            gate += 1
            print(f"GATE {chal}/{question}: {line[:160]}")
        else:
            errors += 1
            print(f"ERROR rc={rc} {chal}/{question}: {line[:200]}", file=sys.stderr)
            if rc in (4,):
                print("AUTH problem: stop submitting and report.", file=sys.stderr)
                break
    elapsed = time.time() - t0
    rate = accepted / (elapsed / 60.0) if elapsed > 0 else 0.0
    print("=" * 62)
    print(f"BATCH total={total} accepted={accepted} rejected={rejected} "
          f"gate={gate} errors={errors} elapsed={elapsed:.1f}s rate={rate:.1f} AC/min")
    print("=" * 62)
    if errors:
        return 8
    return 7 if rejected else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="CTFy QA speed-run plumbing (agent answers)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="print unsolved questions as JSON")
    ls.add_argument("--competition", required=True)
    ls.add_argument("--limit", type=int, default=20)
    ls.add_argument("--offset", type=int, default=0)
    ls.add_argument("--max-desc", type=int, default=800)
    ls.set_defaults(fn=cmd_list)
    sb = sub.add_parser("submit", help="submit a batch of answers")
    sb.add_argument("--competition", required=True)
    sb.add_argument("--answers", required=True)
    sb.add_argument("--game", default=DEFAULT_GAME)
    sb.set_defaults(fn=cmd_submit)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

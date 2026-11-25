#!/usr/bin/env python3
"""Hash-only local judge for the offline archived eval challenges (eval harness).

The archived challenges in eval/cases/challenges.yaml are solved offline, so
there is no platform to return a verdict. This judge is the deterministic L3
substitute: it compares a candidate flag against `expected.sha256` in the trial
workspace and appends every attempt to `submissions.jsonl`.

It never stores or prints the expected flag, only ACCEPT/REJECT.

Usage:
  python judge.py --workspace <trial-workspace> --candidate 'flag{...}'
  python judge.py --workspace <trial-workspace> --candidate-file final/flag.txt

Exit codes: 0 ACCEPT, 1 REJECT, 2 usage/setup error.
wrong_submissions for a trial = number of REJECT lines in submissions.jsonl.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="trial workspace directory")
    parser.add_argument("--candidate", help="candidate flag string")
    parser.add_argument("--candidate-file", help="file containing one candidate flag")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    expected_path = workspace / "expected.sha256"
    if not expected_path.is_file():
        print(f"ERROR: missing {expected_path}", file=sys.stderr)
        return 2
    expected = expected_path.read_text(encoding="utf-8").strip().lower()
    candidate = args.candidate
    if candidate is None and args.candidate_file:
        candidate = Path(args.candidate_file).read_text(encoding="utf-8").strip()
    if not candidate:
        print("ERROR: provide --candidate or --candidate-file", file=sys.stderr)
        return 2
    candidate = candidate.strip()
    verdict = "ACCEPT" if hashlib.sha256(candidate.encode()).hexdigest() == expected else "REJECT"

    with (workspace / "submissions.jsonl").open("a", encoding="utf-8") as handle:
        record = {
            "candidate": candidate,
            "verdict": verdict,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(verdict)
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

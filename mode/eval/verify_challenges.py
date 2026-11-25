#!/usr/bin/env python3
"""Verify eval/cases/challenges.yaml end-to-end, offline and without an LLM.

For every archived challenge this tool:
  1. checks the required SPEC §6 fields and that categories are distinct;
  2. re-hashes the attachments it references and compares attachments_sha256;
  3. re-hashes eval/checkers/<id>_check.py and compares checker_sha256;
  4. re-hashes known_flag and compares evidence_sha256;
  5. runs check_cmd and asserts stdout == known_flag and exit code 0.

Usage: python verify_challenges.py [--cases PATH] [--json]
Exit 0 if every challenge verifies; 1 otherwise. Writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases" / "challenges.yaml"
REQUIRED_FIELDS = ("id", "category", "path", "known_flag", "check_cmd", "difficulty")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_one(challenge: dict) -> dict:
    """Run all local checks for one challenge; returns a result record."""
    cid = challenge.get("id", "<unknown>")
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not challenge.get(field):
            errors.append(f"missing required field {field}")

    attachments_dir = Path(challenge.get("attachments_dir", challenge.get("path", "")))
    attachments = challenge.get("attachments") or []
    hashes = challenge.get("attachments_sha256") or {}
    for name in attachments:
        target = attachments_dir / name
        if not target.is_file():
            errors.append(f"attachment missing: {target}")
            continue
        expected = hashes.get(name)
        if not expected:
            errors.append(f"no attachments_sha256 for {name}")
            continue
        actual = sha256_file(target)
        if actual != expected:
            errors.append(f"attachment hash mismatch for {name}: {actual} != {expected}")

    checker = challenge.get("checker")
    if checker:
        checker_path = Path(checker)
        if not checker_path.is_file():
            errors.append(f"checker missing: {checker_path}")
        else:
            actual = sha256_file(checker_path)
            expected = challenge.get("checker_sha256")
            if actual != expected:
                errors.append(f"checker_sha256 mismatch: {actual} != {expected}")

    known_flag = challenge.get("known_flag", "")
    actual_evidence = hashlib.sha256(known_flag.encode()).hexdigest()
    expected_evidence = challenge.get("evidence_sha256")
    if actual_evidence != expected_evidence:
        errors.append(f"evidence_sha256 mismatch: {actual_evidence} != {expected_evidence}")

    check_cmd = challenge.get("check_cmd")
    stdout = ""
    if check_cmd:
        try:
            completed = subprocess.run(
                check_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"check_cmd failed to run: {exc}")
        else:
            stdout = completed.stdout.strip()
            if completed.returncode != 0:
                errors.append(
                    f"check_cmd exit {completed.returncode}: {completed.stderr.strip()[:300]}"
                )
            if stdout != known_flag:
                errors.append(f"check_cmd output {stdout!r} != known_flag {known_flag!r}")

    return {
        "id": cid,
        "category": challenge.get("category"),
        "checker": checker,
        "output": stdout,
        "local_verified": not errors and bool(challenge.get("local_verified")),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cases_path = Path(args.cases)
    try:
        raw = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot load {cases_path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw, list) or not raw:
        print("ERROR: challenges.yaml must be a non-empty list", file=sys.stderr)
        return 1

    categories = [c.get("category") for c in raw]
    category_errors: list[str] = []
    if len(set(categories)) != 3:
        category_errors.append(f"expected 3 distinct categories, got {categories}")

    results = [verify_one(c) for c in raw]
    passed = all(r["local_verified"] for r in results) and not category_errors
    payload = {
        "tool": "verify_challenges.py",
        "cases_file": str(cases_path),
        "count": len(results),
        "categories": categories,
        "category_errors": category_errors,
        "results": results,
        "status": "PASS" if passed else "FAIL",
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for result in results:
            mark = "PASS" if result["local_verified"] else "FAIL"
            print(f"{mark}  {result['id']:<14} {result['category']:<10} {result['output']}")
            for error in result["errors"]:
                print(f"      - {error}")
        for error in category_errors:
            print(f"FAIL  categories: {error}")
        print()
        print(f"RESULT: {payload['status']} ({sum(r['local_verified'] for r in results)}/{len(results)} challenges verified locally)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CTF mode — routing grader (SPEC §6).

Grades an answer file against eval/cases/routing.yaml.

Answer file format: one `id: skill-name` per line, e.g.

    route-001: ctf-web
    route-010: ctf-forensics

Blank lines and `#` comments are ignored. Any other prose is a format error.
Skill names may be written with a leading `/` (e.g. `/ctf-web`).

Gate (SPEC §6): first-choice accuracy >= 0.8 AND forbidden hits == 0.

Usage:
  python run_routing.py <answers.txt> [--cases PATH] [--json] [--out PATH]
  python run_routing.py --self-test

Exit codes: 0 gate passed, 1 gate failed, 2 usage/format error.
Writes nothing unless --out is given.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("ERROR: PyYAML is required (python -m pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases" / "routing.yaml"
SAMPLE_FULL = HERE / "sample_answers_10of10.txt"
SAMPLE_PARTIAL = HERE / "sample_answers_partial.txt"

# The 12 model-invocable entry skills (SPEC §2).
VALID_SKILLS = (
    "ctf-triage",
    "ctf-web",
    "ctf-pwn",
    "ctf-reverse",
    "ctf-crypto",
    "ctf-forensics",
    "ctf-misc",
    "ctf-ai-ml",
    "ctf-malware",
    "ctf-osint",
    "ctf-blackboard",
    "ctf-submit",
)

ANSWER_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(/?[A-Za-z0-9_-]+)$")
FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*$")
ACCURACY_THRESHOLD = 0.8


class AnswerFormatError(ValueError):
    """Raised when the answer file contains a line that is not `id: skill`."""


def load_cases(path: Path) -> list[dict]:
    """Load and validate routing cases; raise ValueError on a broken contract."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"routing cases not found: {path}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("routing.yaml must be a non-empty list of cases")
    seen: set[str] = set()
    cases: list[dict] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"case #{index} is not a mapping")
        missing = [k for k in ("id", "prompt", "expected", "forbidden") if k not in item]
        if missing:
            raise ValueError(f"case #{index} missing keys: {', '.join(missing)}")
        cid = item["id"]
        if not isinstance(cid, str) or not cid:
            raise ValueError(f"case #{index} has an invalid id")
        if cid in seen:
            raise ValueError(f"duplicate case id: {cid}")
        seen.add(cid)
        expected = item["expected"]
        forbidden = item["forbidden"]
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"{cid}: expected must be a non-empty list")
        if not isinstance(forbidden, list) or not forbidden:
            raise ValueError(f"{cid}: forbidden must be a non-empty list")
        if not isinstance(item["prompt"], str) or not item["prompt"].strip():
            raise ValueError(f"{cid}: prompt must be a non-empty string")
        for skill in expected + forbidden:
            if skill not in VALID_SKILLS:
                raise ValueError(f"{cid}: unknown skill {skill!r} (not one of the 12 entries)")
        unknown_expected = [s for s in expected if s not in VALID_SKILLS]
        if unknown_expected:
            raise ValueError(f"{cid}: unknown expected skills {unknown_expected}")
        overlap = set(expected) & set(forbidden)
        if overlap:
            raise ValueError(f"{cid}: {sorted(overlap)} both expected and forbidden")
        cases.append(
            {
                "id": cid,
                "expected": list(expected),
                "forbidden": list(forbidden),
            }
        )
    return cases


def parse_answers(text: str) -> dict[str, str]:
    """Parse `id: skill` lines; raise AnswerFormatError on prose/malformed lines."""
    answers: dict[str, str] = {}
    duplicates: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if FENCE_RE.match(line):
            continue
        line = line.replace("`", "").strip()
        match = ANSWER_RE.match(line)
        if not match:
            raise AnswerFormatError(
                f"line {lineno}: expected `route-00X: <skill-name>`, got {raw_line.strip()!r}"
            )
        case_id, skill = match.group(1), match.group(2).lstrip("/").lower()
        if case_id in answers:
            duplicates.append(case_id)
        answers[case_id] = skill
    if duplicates:
        raise AnswerFormatError(f"duplicate case ids in answers: {sorted(set(duplicates))}")
    return answers


def grade(cases: list[dict], answers: dict[str, str]) -> dict:
    """Grade parsed answers; returns the machine-readable result payload."""
    per_case: list[dict] = []
    forbidden_hits: list[dict] = []
    missing: list[str] = []
    unexpected: list[str] = []
    first_choice_correct = 0
    acceptable_correct = 0
    case_ids = [c["id"] for c in cases]

    for case in cases:
        cid = case["id"]
        chosen = answers.get(cid)
        if chosen is None:
            missing.append(cid)
        first_hit = chosen == case["expected"][0]
        acceptable_hit = chosen in case["expected"]
        is_forbidden = chosen in case["forbidden"]
        first_choice_correct += int(first_hit)
        acceptable_correct += int(acceptable_hit)
        if is_forbidden:
            forbidden_hits.append({"id": cid, "skill": chosen, "forbidden": case["forbidden"]})
        if chosen is not None and chosen not in VALID_SKILLS:
            unexpected.append({"id": cid, "skill": chosen})
        per_case.append(
            {
                "id": cid,
                "expected": case["expected"],
                "forbidden": case["forbidden"],
                "chosen": chosen,
                "first_choice_hit": first_hit,
                "acceptable_hit": acceptable_hit,
                "forbidden_hit": is_forbidden,
            }
        )

    unexpected_ids = sorted(set(answers) - set(case_ids))
    total = len(cases)
    accuracy = first_choice_correct / total if total else 0.0
    acceptable_accuracy = acceptable_correct / total if total else 0.0
    accuracy_ok = accuracy >= ACCURACY_THRESHOLD
    forbidden_ok = not forbidden_hits
    return {
        "tool": "run_routing.py",
        "cases_count": total,
        "answered_count": len(answers),
        "first_choice_correct": first_choice_correct,
        "first_choice_accuracy": round(accuracy, 4),
        "acceptable_correct": acceptable_correct,
        "acceptable_accuracy": round(acceptable_accuracy, 4),
        "forbidden_count": len(forbidden_hits),
        "forbidden_hits": forbidden_hits,
        "missing": missing,
        "unexpected_ids": unexpected_ids,
        "unknown_skills": unexpected,
        "per_case": per_case,
        "gate": {
            "accuracy_threshold": ACCURACY_THRESHOLD,
            "accuracy_ok": accuracy_ok,
            "forbidden_zero": forbidden_ok,
            "passed": bool(accuracy_ok and forbidden_ok),
        },
        "status": "PASS" if (accuracy_ok and forbidden_ok) else "FAIL",
    }


def read_answers_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise AnswerFormatError(f"answers file not found: {path}") from exc
    return parse_answers(text)


def render_text(result: dict, answers_path: str) -> str:
    lines: list[str] = []
    lines.append(f"routing grader — {answers_path}")
    lines.append("")
    lines.append(f"{'case':<11} {'expected[0]':<14} {'chosen':<14} {'first':<6} forbidden")
    lines.append(f"{'-' * 11} {'-' * 14} {'-' * 14} {'-' * 6} {'-' * 9}")
    for row in result["per_case"]:
        chosen = row["chosen"] if row["chosen"] is not None else "(missing)"
        mark = "HIT" if row["first_choice_hit"] else "miss"
        if row["acceptable_hit"] and not row["first_choice_hit"]:
            mark = "alt"
        forbidden = "YES" if row["forbidden_hit"] else "-"
        lines.append(
            f"{row['id']:<11} {row['expected'][0]:<14} {chosen:<14} {mark:<6} {forbidden}"
        )
    lines.append("")
    lines.append(
        f"first-choice accuracy: {result['first_choice_correct']}/{result['cases_count']} "
        f"({result['first_choice_accuracy']:.3f})  gate >= {ACCURACY_THRESHOLD:.2f}"
    )
    lines.append(
        f"acceptable (any expected): {result['acceptable_correct']}/{result['cases_count']} "
        f"({result['acceptable_accuracy']:.3f})"
    )
    lines.append(f"forbidden hits: {result['forbidden_count']}")
    if result["missing"]:
        lines.append(f"missing answers: {', '.join(result['missing'])}")
    if result["unexpected_ids"]:
        lines.append(f"unexpected ids ignored: {', '.join(result['unexpected_ids'])}")
    if result["unknown_skills"]:
        pairs = ", ".join(f"{r['id']}={r['skill']}" for r in result["unknown_skills"])
        lines.append(f"unknown skill names (counted as miss): {pairs}")
    lines.append("")
    lines.append(
        f"RESULT: {result['status']} "
        f"(accuracy_ok={result['gate']['accuracy_ok']}, "
        f"forbidden_zero={result['gate']['forbidden_zero']})"
    )
    return "\n".join(lines)


def run_grading(answers_path: Path, cases_path: Path) -> dict:
    cases = load_cases(cases_path)
    answers = read_answers_file(answers_path)
    return grade(cases, answers)


def self_test() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, bool(condition), detail))

    try:
        cases = load_cases(DEFAULT_CASES)
    except ValueError as exc:
        print(f"SELF-TEST: FAIL — routing.yaml invalid: {exc}")
        return 1

    check("routing.yaml has exactly 10 cases", len(cases) == 10, f"got {len(cases)}")
    check("all case ids unique", len({c["id"] for c in cases}) == len(cases))

    result_full = run_grading(SAMPLE_FULL, DEFAULT_CASES)
    check(
        "sample_answers_10of10 passes",
        result_full["status"] == "PASS" and result_full["first_choice_accuracy"] == 1.0,
        f"status={result_full['status']} accuracy={result_full['first_choice_accuracy']}",
    )
    check(
        "sample_answers_10of10 forbidden == 0",
        result_full["forbidden_count"] == 0,
        f"forbidden={result_full['forbidden_count']}",
    )

    result_partial = run_grading(SAMPLE_PARTIAL, DEFAULT_CASES)
    check(
        "sample_answers_partial fails",
        result_partial["status"] == "FAIL",
        f"status={result_partial['status']}",
    )
    check(
        "sample_answers_partial is 7/10",
        result_partial["first_choice_correct"] == 7,
        f"correct={result_partial['first_choice_correct']}",
    )
    check(
        "sample_answers_partial has 1 forbidden hit",
        result_partial["forbidden_count"] == 1,
        f"forbidden={result_partial['forbidden_count']}",
    )

    # Boundary checks with synthetic answer sets.
    good = {case["id"]: case["expected"][0] for case in cases}
    result_8 = grade(cases, dict(list(good.items())[:8]) | {
        cases[8]["id"]: "ctf-submit",
        cases[9]["id"]: "ctf-triage",
    })
    check(
        "8/10 with no forbidden passes the accuracy gate",
        result_8["status"] == "PASS" and result_8["first_choice_correct"] == 8,
        f"status={result_8['status']} correct={result_8['first_choice_correct']}",
    )
    result_7 = grade(cases, dict(list(good.items())[:7]) | {
        cases[7]["id"]: "ctf-submit",
        cases[8]["id"]: "ctf-triage",
        cases[9]["id"]: "ctf-blackboard",
    })
    check(
        "7/10 without forbidden fails the accuracy gate",
        result_7["status"] == "FAIL" and result_7["forbidden_count"] == 0,
        f"status={result_7['status']} correct={result_7['first_choice_correct']}",
    )
    result_forbidden = dict(good)
    result_forbidden[cases[0]["id"]] = cases[0]["forbidden"][0]
    result_forbidden_grade = grade(cases, result_forbidden)
    check(
        "a single forbidden hit fails even at 9/10",
        result_forbidden_grade["status"] == "FAIL"
        and result_forbidden_grade["forbidden_count"] == 1,
        f"status={result_forbidden_grade['status']}",
    )
    alt = dict(good)
    alt[cases[9]["id"]] = cases[9]["expected"][1]
    result_alt = grade(cases, alt)
    check(
        "ambiguous second-ranked candidate is acceptable partial credit",
        result_alt["acceptable_correct"] == 10
        and result_alt["first_choice_correct"] == 9
        and result_alt["status"] == "PASS",
        f"acceptable={result_alt['acceptable_correct']} first={result_alt['first_choice_correct']}",
    )
    try:
        parse_answers("route-001 is ctf-web")
    except AnswerFormatError:
        check("prose lines are rejected as a format error", True)
    else:
        check("prose lines are rejected as a format error", False, "no error raised")
    check(
        "JSON payload has gate + per-case fields",
        {"gate", "per_case", "first_choice_accuracy", "forbidden_count"}
        <= set(grade(cases, good).keys()),
    )

    failed = [name for name, ok, _ in checks if not ok]
    for name, ok, detail in checks:
        suffix = f"  [{detail}]" if detail else ""
        print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")
    print()
    if failed:
        print(f"SELF-TEST: FAIL ({len(failed)}/{len(checks)} checks failed)")
        return 1
    print(f"SELF-TEST: PASS ({len(checks)}/{len(checks)} checks)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grade a CTF routing answer file (gate: accuracy >= 0.8 and forbidden == 0).",
    )
    parser.add_argument("answers", nargs="?", help="answer file with `route-00X: skill` lines")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="routing.yaml path")
    parser.add_argument("--json", action="store_true", help="print the JSON result instead of text")
    parser.add_argument("--out", metavar="PATH", help="write the JSON result to PATH")
    parser.add_argument("--self-test", action="store_true", help="run built-in assertions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.answers:
        print("ERROR: an answers file is required (or use --self-test)", file=sys.stderr)
        return 2
    cases_path = Path(args.cases)
    answers_path = Path(args.answers)
    try:
        result = run_grading(answers_path, cases_path)
    except (ValueError, AnswerFormatError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_text(result, str(answers_path)))
        if args.out:
            print(f"\nJSON written to {args.out}")
    return 0 if result["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

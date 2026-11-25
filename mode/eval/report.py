#!/usr/bin/env python3
"""CTF mode — eval report: matrix + acceptance gates (SPEC §6, kernel/EVAL_CASES.md §3-4).

Ingests a trials JSONL file, one row per (baseline config × challenge):

    {"config": "C0".."C3", "challenge": "crypto-01", "solved": true,
     "first_solve_s": 123, "tokens": 91234, "turns": 17,
     "wrong_submissions": 0, "compaction_events": 0, "verify_catches": 0,
     "dispatch_latency_s": null, "controller_busy_ratio": null,
     "handoff_loss": null, "context_peak_pct": null, "notes": ""}

`context_peak_pct` is an optional extension used by gate G6; if absent, G6 also
looks for `peak=<N>%` inside `notes`.

Gates (PASS / FAIL / NOT RUN; a FAIL on any gate that has data makes the run fail):
  G1  wrong_submissions total == 0
  G2  C3 solve rate >= C0 solve rate
  G3  mean tokens per solved challenge <= budget (default 150000)
  G4  verify_catches total >= 1
  G5  routing gate passed (reads eval/reports/routing_result.json; absent -> NOT RUN)
  G6  context: compaction events recorded, peak <= 70% when present

Usage:
  python report.py trials.jsonl [--out PATH] [--routing-result PATH] [--budget N] [--json]
  python report.py --self-test

Exit codes: 0 all data-bearing gates pass, 1 any data-bearing gate fails, 2 usage error.
Writes nothing unless --out is given.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROUTING_RESULT = HERE / "reports" / "routing_result.json"
DEFAULT_BUDGET = 150000
CONFIGS = ("C0", "C1", "C2", "C3")
PEAK_LIMIT_PCT = 70
PEAK_NOTE_RE = re.compile(r"peak(?:_pct)?\s*[=:]\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)


class TrialError(ValueError):
    """Raised when trials.jsonl violates the row contract."""


# --------------------------------------------------------------------------- input


def load_trials(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise TrialError(f"trials file not found: {path}") from exc
    trials: list[dict] = []
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TrialError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise TrialError(f"{path}:{lineno}: row must be a JSON object")
        config = str(row.get("config", "")).upper()
        if config not in CONFIGS:
            raise TrialError(f"{path}:{lineno}: config must be one of {CONFIGS}, got {row.get('config')!r}")
        if not isinstance(row.get("challenge"), str) or not row["challenge"]:
            raise TrialError(f"{path}:{lineno}: missing challenge name")
        if not isinstance(row.get("solved"), bool):
            raise TrialError(f"{path}:{lineno}: solved must be true/false")
        row["config"] = config
        trials.append(row)
    if not trials:
        raise TrialError(f"{path}: no trial rows found")
    return trials


def load_routing_result(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"_invalid": True, "path": str(path)}


# ---------------------------------------------------------------------- helpers


def num(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def fmt(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    if digits == 0 and float(value).is_integer():
        return str(int(value))
    return f"{value:.{digits}f}"


def peak_pct(row: dict) -> float | None:
    explicit = num(row, "context_peak_pct")
    if explicit is not None:
        return explicit
    match = PEAK_NOTE_RE.search(str(row.get("notes", "")))
    return float(match.group(1)) if match else None


def ordered(seq: list[str], order: tuple[str, ...]) -> list[str]:
    present = set(seq)
    return [item for item in order if item in present] + sorted(present - set(order))


def first_seen(seq: list[str]) -> list[str]:
    """Unique values in order of first appearance (deterministic for a given file)."""
    seen: set[str] = set()
    result: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _gate(gate_id: str, requirement: str, status: str, detail: str) -> dict:
    return {"id": gate_id, "requirement": requirement, "status": status, "detail": detail}


# --------------------------------------------------------------------- evaluate


def evaluate(trials: list[dict], routing_result: dict | None, budget: float = DEFAULT_BUDGET) -> dict:
    configs = ordered([t["config"] for t in trials], CONFIGS)
    challenges = first_seen([t["challenge"] for t in trials])

    by_key = {(t["config"], t["challenge"]): t for t in trials}
    duplicate_count = len(trials) - len(by_key)

    # G1 — wrong submissions total must be 0.
    wrong_numbers = [num(t, "wrong_submissions") for t in trials]
    if all(v is None for v in wrong_numbers):
        g1 = _gate("G1", "wrong_submissions total == 0", "NOT RUN", "wrong_submissions not recorded")
    else:
        wrong_total = int(sum(v for v in wrong_numbers if v is not None))
        g1 = _gate(
            "G1",
            "wrong_submissions total == 0",
            "PASS" if wrong_total == 0 else "FAIL",
            f"total={wrong_total}"
            + (f" (rows missing value: {sum(v is None for v in wrong_numbers)})" if any(v is None for v in wrong_numbers) else ""),
        )

    # G2 — C3 solve rate >= C0 solve rate.
    def solve_rate(config: str) -> tuple[int, int] | None:
        rows = [t for t in trials if t["config"] == config]
        if not rows:
            return None
        return sum(1 for t in rows if t["solved"]), len(rows)

    c0, c3 = solve_rate("C0"), solve_rate("C3")
    if c0 is None or c3 is None:
        g2 = _gate(
            "G2",
            "C3 solve rate >= C0 solve rate",
            "NOT RUN",
            f"missing config data (C0={'present' if c0 else 'absent'}, C3={'present' if c3 else 'absent'})",
        )
    else:
        r0 = c0[0] / c0[1]
        r3 = c3[0] / c3[1]
        g2 = _gate(
            "G2",
            "C3 solve rate >= C0 solve rate",
            "PASS" if r3 >= r0 else "FAIL",
            f"C0={c0[0]}/{c0[1]} ({r0:.3f}), C3={c3[0]}/{c3[1]} ({r3:.3f})",
        )

    # G3 — mean tokens per solved challenge <= budget (only where token data exists).
    solved_tokens = [num(t, "tokens") for t in trials if t["solved"]]
    solved_tokens = [v for v in solved_tokens if v is not None]
    if not solved_tokens:
        g3 = _gate("G3", f"mean tokens per solved challenge <= {int(budget)}", "NOT RUN", "no token data on solved rows")
    else:
        mean_tokens = sum(solved_tokens) / len(solved_tokens)
        g3 = _gate(
            "G3",
            f"mean tokens per solved challenge <= {int(budget)}",
            "PASS" if mean_tokens <= budget else "FAIL",
            f"mean={mean_tokens:.0f} over {len(solved_tokens)} solved rows",
        )

    # G4 — verification gate caught at least one injected false positive.
    verify_numbers = [num(t, "verify_catches") for t in trials]
    if all(v is None for v in verify_numbers):
        g4 = _gate("G4", "verify_catches total >= 1", "NOT RUN", "verify_catches not recorded")
    else:
        verify_total = int(sum(v for v in verify_numbers if v is not None))
        g4 = _gate(
            "G4",
            "verify_catches total >= 1",
            "PASS" if verify_total >= 1 else "FAIL",
            f"total={verify_total}",
        )

    # G5 — routing gate passed (reports/routing_result.json from run_routing.py --out).
    g5_passed: bool | None = None
    detail_parts: list[str] = []
    if routing_result is None:
        g5 = _gate("G5", "routing gate passed (accuracy >= 0.8, forbidden == 0)", "NOT RUN", "routing_result.json absent")
    elif routing_result.get("_invalid"):
        g5 = _gate("G5", "routing gate passed (accuracy >= 0.8, forbidden == 0)", "FAIL", "routing_result.json is not valid JSON")
    else:
        gate = routing_result.get("gate")
        if isinstance(gate, dict) and "passed" in gate:
            g5_passed = bool(gate["passed"])
        elif isinstance(routing_result.get("passed"), bool):
            g5_passed = bool(routing_result["passed"])
        elif str(routing_result.get("status", "")).upper() in ("PASS", "FAIL"):
            g5_passed = str(routing_result["status"]).upper() == "PASS"
        accuracy = routing_result.get("first_choice_accuracy", routing_result.get("accuracy"))
        forbidden = routing_result.get("forbidden_count")
        if accuracy is not None:
            detail_parts.append(f"accuracy={accuracy}")
        if forbidden is not None:
            detail_parts.append(f"forbidden={forbidden}")
        if g5_passed is None:
            g5 = _gate("G5", "routing gate passed (accuracy >= 0.8, forbidden == 0)", "FAIL", "unrecognised routing_result.json shape")
        else:
            g5 = _gate(
                "G5",
                "routing gate passed (accuracy >= 0.8, forbidden == 0)",
                "PASS" if g5_passed else "FAIL",
                ", ".join(detail_parts) or "gate.passed present",
            )

    # G6 — compaction events recorded; peak <= 70% when present.
    compaction_numbers = [num(t, "compaction_events") for t in trials]
    peaks = [peak_pct(t) for t in trials]
    peaks = [p for p in peaks if p is not None]
    if all(v is None for v in compaction_numbers):
        g6 = _gate("G6", f"compaction recorded and peak <= {PEAK_LIMIT_PCT}%", "NOT RUN", "compaction_events not recorded")
    else:
        events_total = int(sum(v for v in compaction_numbers if v is not None))
        if peaks:
            peak_max = max(peaks)
            g6_status = "PASS" if peak_max <= PEAK_LIMIT_PCT else "FAIL"
            g6_detail = f"events total={events_total}, peak={peak_max:.0f}%"
        else:
            g6_status = "PASS"
            g6_detail = f"events total={events_total}, peak not recorded"
        g6 = _gate("G6", f"compaction recorded and peak <= {PEAK_LIMIT_PCT}%", g6_status, g6_detail)

    gates = [g1, g2, g3, g4, g5, g6]
    required = [g for g in gates if g["status"] in ("PASS", "FAIL")]
    if any(g["status"] == "FAIL" for g in required):
        overall = "FAIL"
    elif all(g["status"] == "PASS" for g in gates):
        overall = "PASS"
    else:
        overall = "INCOMPLETE"

    summary: list[dict] = []
    for config in configs:
        rows = [t for t in trials if t["config"] == config]
        solved = sum(1 for t in rows if t["solved"])
        tokens = [num(t, "tokens") for t in rows if t["solved"] and num(t, "tokens") is not None]
        summary.append(
            {
                "config": config,
                "trials": len(rows),
                "solved": solved,
                "solve_rate": round(solved / len(rows), 4) if rows else 0.0,
                "mean_tokens_per_solved": round(sum(tokens) / len(tokens), 2) if tokens else None,
                "total_tokens": int(sum(num(t, "tokens") or 0 for t in rows)),
                "wrong_submissions": int(sum(num(t, "wrong_submissions") or 0 for t in rows)),
                "verify_catches": int(sum(num(t, "verify_catches") or 0 for t in rows)),
            }
        )

    return {
        "tool": "report.py",
        "trials_count": len(trials),
        "duplicate_config_challenge_rows": duplicate_count,
        "configs": configs,
        "challenges": challenges,
        "budget_tokens": int(budget),
        "gates": gates,
        "summary": summary,
        "status": overall,
    }


# ----------------------------------------------------------------------- render


def _cell(value: float | None, digits: int = 0) -> str:
    return fmt(value, digits)


def render_markdown(result: dict, trials: list[dict]) -> str:
    challenges = result["challenges"]
    configs = result["configs"]

    lines: list[str] = []
    lines.append("# CTF eval report")
    lines.append("")
    lines.append(f"- trials: {result['trials_count']}")
    lines.append(f"- configs: {', '.join(configs) or '(none)'}")
    lines.append(f"- challenges: {', '.join(challenges) or '(none)'}")
    lines.append(f"- token budget per solved challenge: {result['budget_tokens']}")
    if result["duplicate_config_challenge_rows"]:
        lines.append(f"- WARNING: {result['duplicate_config_challenge_rows']} duplicate (config, challenge) rows")
    lines.append("")

    # Solve matrix.
    lines.append("## 1. Solve matrix (config × challenge)")
    lines.append("")
    lines.append("| config | " + " | ".join(challenges) + " | solve rate |")
    lines.append("|---|" + "---|" * len(challenges) + "---|")
    by_key = {(t["config"], t["challenge"]): t for t in trials}
    for config in configs:
        cells = []
        for challenge in challenges:
            row = by_key.get((config, challenge))
            cells.append("✓" if row and row["solved"] else "✗")
        solved = sum(1 for c in challenges if by_key.get((config, c), {}).get("solved"))
        lines.append(f"| {config} | " + " | ".join(cells) + f" | {solved}/{len(challenges)} |")
    lines.append("")

    # Metric matrix.
    lines.append("## 2. Metric matrix (config × challenge)")
    lines.append("")
    lines.append("| config | challenge | solved | first_solve_s | tokens | turns | wrong_submissions |")
    lines.append("|---|---|---|---|---|---|---|")
    for config in configs:
        for challenge in challenges:
            row = by_key.get((config, challenge))
            if row is None:
                lines.append(f"| {config} | {challenge} | - | - | - | - | - |")
                continue
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    config,
                    challenge,
                    "✓" if row["solved"] else "✗",
                    _cell(num(row, "first_solve_s"), 1),
                    _cell(num(row, "tokens")),
                    _cell(num(row, "turns")),
                    _cell(num(row, "wrong_submissions")),
                )
            )
    lines.append("")

    # Per-config summary.
    lines.append("## 3. Config summary")
    lines.append("")
    lines.append("| config | trials | solved | solve_rate | mean_tokens_per_solved | total_tokens | wrong_submissions | verify_catches |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in result["summary"]:
        lines.append(
            "| {config} | {trials} | {solved} | {rate:.3f} | {mt} | {tt} | {ws} | {vc} |".format(
                config=row["config"],
                trials=row["trials"],
                solved=row["solved"],
                rate=row["solve_rate"],
                mt=_cell(row["mean_tokens_per_solved"], 0),
                tt=row["total_tokens"],
                ws=row["wrong_submissions"],
                vc=row["verify_catches"],
            )
        )
    lines.append("")

    # Gate table.
    lines.append("## 4. Acceptance gates")
    lines.append("")
    lines.append("| gate | requirement | status | detail |")
    lines.append("|---|---|---|---|")
    for gate in result["gates"]:
        lines.append(f"| {gate['id']} | {gate['requirement']} | **{gate['status']}** | {gate['detail']} |")
    lines.append("")
    lines.append("> PASS/FAIL gates are required: any FAIL exits non-zero. NOT RUN means the data was not recorded,")
    lines.append("> so the gate could not be judged (it is reported, not silently passed).")
    lines.append("> Overall status: PASS = all six gates PASS; INCOMPLETE = no gate FAILed but some data is")
    lines.append("> missing (NOT RUN); FAIL = at least one data-bearing gate FAILed.")
    lines.append("")
    lines.append(f"RESULT: {result['status']}")
    return "\n".join(lines)


# --------------------------------------------------------------------- self-test


def _passing_trials() -> list[dict]:
    """12 synthetic trials where every gate has data and passes."""
    plan = {
        "C0": {"crypto-01": True, "rev-01": False, "forensics-01": False},
        "C1": {"crypto-01": True, "rev-01": True, "forensics-01": False},
        "C2": {"crypto-01": True, "rev-01": True, "forensics-01": False},
        "C3": {"crypto-01": True, "rev-01": True, "forensics-01": True},
    }
    peak = {"C0": 42, "C1": 55, "C2": 63, "C3": 68}
    rows: list[dict] = []
    for config in CONFIGS:
        for index, (challenge, solved) in enumerate(plan[config].items()):
            rows.append(
                {
                    "config": config,
                    "challenge": challenge,
                    "solved": solved,
                    "first_solve_s": 120 + index * 40 if solved else None,
                    "tokens": 82000 + index * 5000 if solved else 120000,
                    "turns": 12 + index if solved else 30,
                    "wrong_submissions": 0,
                    "compaction_events": 1 if config in ("C2", "C3") else 0,
                    "verify_catches": 1 if config == "C3" and challenge == "crypto-01" else 0,
                    "dispatch_latency_s": None,
                    "controller_busy_ratio": None,
                    "handoff_loss": None,
                    "context_peak_pct": peak[config],
                    "notes": f"synthetic {config}/{challenge}",
                }
            )
    return rows


def _routing_pass() -> dict:
    return {
        "tool": "run_routing.py",
        "first_choice_accuracy": 1.0,
        "forbidden_count": 0,
        "gate": {"accuracy_threshold": 0.8, "accuracy_ok": True, "forbidden_zero": True, "passed": True},
        "status": "PASS",
    }


def _gates_by_id(result: dict) -> dict[str, dict]:
    return {g["id"]: g for g in result["gates"]}


def self_test() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, bool(condition), detail))

    trials = _passing_trials()
    with tempfile.TemporaryDirectory() as tmp:
        routing_path = Path(tmp) / "routing_result.json"
        routing_path.write_text(json.dumps(_routing_pass()), encoding="utf-8")
        routing = load_routing_result(routing_path)

        result = evaluate(trials, routing)
        gates = _gates_by_id(result)
        check("passing trials -> overall PASS", result["status"] == "PASS", f"status={result['status']}")
        check(
            "all six gates PASS on passing trials",
            all(g["status"] == "PASS" for g in result["gates"]),
            ", ".join(f"{g['id']}={g['status']}" for g in result["gates"]),
        )
        matrix = render_markdown(result, trials)
        check(
            "markdown contains matrix + gate table",
            "## 1. Solve matrix" in matrix and "## 4. Acceptance gates" in matrix and "RESULT: PASS" in matrix,
        )

        def variant(mutator) -> dict:
            rows = copy.deepcopy(trials)
            mutator(rows)
            return evaluate(rows, routing)

        bad_wrong = variant(lambda rows: rows[0].__setitem__("wrong_submissions", 1))
        check(
            "G1 fails on one wrong submission",
            _gates_by_id(bad_wrong)["G1"]["status"] == "FAIL" and bad_wrong["status"] == "FAIL",
            _gates_by_id(bad_wrong)["G1"]["detail"],
        )

        def regress_c3(rows: list[dict]) -> None:
            for row in rows:
                if row["config"] == "C3":
                    row["solved"] = False

        bad_regress = variant(regress_c3)
        check(
            "G2 fails when C3 solve rate drops below C0",
            _gates_by_id(bad_regress)["G2"]["status"] == "FAIL" and bad_regress["status"] == "FAIL",
            _gates_by_id(bad_regress)["G2"]["detail"],
        )

        def over_budget(rows: list[dict]) -> None:
            for row in rows:
                if row["solved"]:
                    row["tokens"] = 250000

        bad_tokens = variant(over_budget)
        check(
            "G3 fails when mean tokens exceed budget",
            _gates_by_id(bad_tokens)["G3"]["status"] == "FAIL" and bad_tokens["status"] == "FAIL",
            _gates_by_id(bad_tokens)["G3"]["detail"],
        )

        def no_catch(rows: list[dict]) -> None:
            for row in rows:
                row["verify_catches"] = 0

        bad_verify = variant(no_catch)
        check(
            "G4 fails when verify_catches total is 0",
            _gates_by_id(bad_verify)["G4"]["status"] == "FAIL" and bad_verify["status"] == "FAIL",
            _gates_by_id(bad_verify)["G4"]["detail"],
        )

        bad_routing = evaluate(trials, {**_routing_pass(), "gate": {"passed": False}})
        check(
            "G5 fails when routing gate failed",
            _gates_by_id(bad_routing)["G5"]["status"] == "FAIL" and bad_routing["status"] == "FAIL",
        )
        check(
            "G5 NOT RUN without routing_result.json",
            _gates_by_id(evaluate(trials, None))["G5"]["status"] == "NOT RUN",
        )

        def hot_context(rows: list[dict]) -> None:
            for row in rows:
                row["context_peak_pct"] = 85

        bad_context = variant(hot_context)
        check(
            "G6 fails when context peak > 70%",
            _gates_by_id(bad_context)["G6"]["status"] == "FAIL" and bad_context["status"] == "FAIL",
            _gates_by_id(bad_context)["G6"]["detail"],
        )

        def drop_compaction(rows: list[dict]) -> None:
            for row in rows:
                row["compaction_events"] = None
                row["context_peak_pct"] = None

        no_compaction = variant(drop_compaction)
        check(
            "G6 NOT RUN when compaction data absent; run is INCOMPLETE",
            _gates_by_id(no_compaction)["G6"]["status"] == "NOT RUN"
            and no_compaction["status"] == "INCOMPLETE",
        )

        # A completely unmeasured row set must be INCOMPLETE, never PASS.
        def strip_metrics(rows: list[dict]) -> None:
            for row in rows:
                for key in (
                    "tokens",
                    "turns",
                    "wrong_submissions",
                    "compaction_events",
                    "verify_catches",
                    "context_peak_pct",
                ):
                    row[key] = None

        incomplete = variant(strip_metrics)
        check(
            "missing instrumentation -> INCOMPLETE (not PASS)",
            incomplete["status"] == "INCOMPLETE"
            and _gates_by_id(incomplete)["G1"]["status"] == "NOT RUN",
            incomplete["status"],
        )

        # Notes-only peak parsing (explicit field takes precedence, so clear it on all rows).
        def notes_only_peak(rows: list[dict]) -> None:
            for row in rows:
                row["context_peak_pct"] = None
                row["notes"] = "peak=66%"

        notes_peak = variant(notes_only_peak)
        check(
            "G6 reads peak=<N>% from notes",
            _gates_by_id(notes_peak)["G6"]["detail"].find("peak=66") >= 0,
            _gates_by_id(notes_peak)["G6"]["detail"],
        )

        # JSON round-trip of the report payload.
        encoded = json.dumps(result, ensure_ascii=False)
        check("report payload is JSON-serialisable", isinstance(json.loads(encoded), dict))

        # Duplicate detection.
        dup = evaluate(trials + [copy.deepcopy(trials[0])], routing)
        check("duplicate (config, challenge) rows are reported", dup["duplicate_config_challenge_rows"] == 1)

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


# -------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the CTF eval matrix and check acceptance gates.")
    parser.add_argument("trials", nargs="?", help="trials JSONL file")
    parser.add_argument("--out", metavar="PATH", help="write the markdown report to PATH")
    parser.add_argument(
        "--routing-result",
        default=str(DEFAULT_ROUTING_RESULT),
        help="routing_result.json produced by run_routing.py --out (default: eval/reports/routing_result.json)",
    )
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET, help="token budget per solved challenge")
    parser.add_argument("--json", action="store_true", help="print the machine-readable result instead of markdown")
    parser.add_argument("--self-test", action="store_true", help="run built-in pass/fail assertions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.trials:
        print("ERROR: a trials JSONL file is required (or use --self-test)", file=sys.stderr)
        return 2
    try:
        trials = load_trials(Path(args.trials))
    except TrialError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    routing = load_routing_result(Path(args.routing_result))
    result = evaluate(trials, routing, budget=args.budget)

    if args.json:
        print(json.dumps({**result, "routing_result_loaded": routing is not None}, indent=2, ensure_ascii=False))
    else:
        markdown = render_markdown(result, trials)
        print(markdown)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(markdown + "\n", encoding="utf-8")
            print(f"\nReport written to {out_path}")

    failed_required = [g["id"] for g in result["gates"] if g["status"] == "FAIL"]
    if failed_required and not args.json:
        print(f"\nFAILED GATES: {', '.join(failed_required)}")
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""One-command preflight for a CTFy experiment session.

Checks, in one pass:
  1. credential file + /me identity
  2. CTF mode health (entry count, knowledge index, integrity manifest)
  3. registered suites: registration, my_solves, QA pool availability (unsolved q)
  4. instance channel probe (start -> immediate stop) for a deterministic challenge
  5. gzctf login (optional; skipped when the CLI is absent)

Writes eval/reports/preflight.json and prints a compact table.
Exit 0 = at least one solvable target exists now (QA unsolved or instance probe OK);
exit 2 = connected but no solvable target (e.g. instance nodes down and QA exhausted).

Usage:
  python ~/.agents/ctf-mode/tools/preflight.py [--probe-instance SAMPLE-018] [--json out]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
CTFY = CTF / "bin" / "ctfy.py"
REPORT = CTF / "eval" / "reports" / "preflight.json"
SUITES = {
    "SAMPLE": "e4e78ff318dc4844beac13f9ea7409aa",
    "Playground": "bc60dc1764f34413964a547102f17261",
    "SECQA": "ba65f88cbe674c0eb7795391bc6faec7",
    "MMLU-CS": "73e5785947414421bde36806ffe512dd",
    "CTI-MCQ": "821a8beda4114ec5885cf57082bf808a",
}


def load_ctfy():
    spec = importlib.util.spec_from_file_location("ctfy_mod", CTFY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ctfy_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description="CTFy experiment preflight")
    ap.add_argument("--probe-instance", default="SAMPLE-018",
                    help="challenge id used for an instance start probe ('' to skip)")
    ap.add_argument("--json", default=str(REPORT))
    args = ap.parse_args()

    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}, "suites": {},
           "solvable_targets": 0, "verdict": "unknown"}

    def fail(msg):
        print(f"PREFLIGHT FAIL: {msg}")
        out["verdict"] = "fail"
        out["error"] = msg
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 2

    token = HOME / ".ctfy" / "api_token.txt"
    if not token.is_file():
        return fail(f"missing credential file {token}")
    out["checks"]["token_file"] = f"OK ({token.stat().st_size} B)"

    entries = [p for p in (CTF / "roots" / "resident").glob("*/SKILL.md")] if (CTF / "roots" / "resident").exists() else []
    index_ok = (CTF / "index.json").is_file() and (CTF / "index.json").stat().st_size > 100_000
    manifest_ok = (CTF / "tools" / "integrity_manifest.json").is_file()
    out["checks"]["mode"] = {"entries": len(entries), "index": index_ok, "integrity_manifest": manifest_ok}
    m = load_ctfy()
    try:
        c = m.CTFy(); c.key = m.load_key()
        code, me = c.get("/me")
        out["checks"]["identity"] = {"http": code,
                                    "name": (me or {}).get("display_name"),
                                    "solves": (me or {}).get("solves")}
        if code != 200:
            return fail(f"/me returned HTTP {code}")
    except SystemExit as exc:  # load_key failing calls die()
        return fail(f"credential rejected: {exc}")

    probe_ok = False
    probe_detail = "skipped"
    if args.probe_instance:
        try:
            code, inst = c.post("/instances", {"challenge_id": args.probe_instance,
                                               "competition_id": SUITES["SAMPLE"]})
            if code == 200 and isinstance(inst, dict) and inst.get("id"):
                probe_ok, probe_detail = True, f"running id={inst.get('id')} (stopped after probe)"
                c.delete(f"/instances/{inst.get('id')}")
            else:
                probe_detail = f"HTTP {code}: {json.dumps(inst, ensure_ascii=False)[:180]}"
        except Exception as exc:
            probe_detail = f"error: {exc}"
    out["checks"]["instance_probe"] = {"challenge": args.probe_instance, "ok": probe_ok,
                                       "detail": probe_detail}

    for name, cid in SUITES.items():
        row = {"competition": cid}
        try:
            code, comp = c.get(f"/competitions/{cid}")
            if isinstance(comp, dict):
                row.update(registered=comp.get("is_registered"), my_solves=comp.get("my_solves"),
                           phase=comp.get("phase"), title=comp.get("title"))
            code2, qa = c.get(f"/qa/challenges?competition_id={cid}")
            if isinstance(qa, list):
                qs = [q for ch in qa for q in (ch.get("questions") or [])]
                solved = sum(len(ch.get("solved_question_ids") or []) for ch in qa)
                wrong = sum(len(ch.get("attempted_wrong_question_ids") or []) for ch in qa)
                row.update(qa_total=len(qs), qa_solved=solved, qa_wrong=wrong,
                           qa_unsolved=len(qs) - solved)
                out["solvable_targets"] += max(0, len(qs) - solved)
            else:
                row.update(qa_total=0, qa_unsolved=0)
        except Exception as exc:
            row["error"] = str(exc)
        out["suites"][name] = row

    if probe_ok:
        out["solvable_targets"] += 1

    # gzctf (optional, second platform)
    gz = shutil.which("gzctf")
    if gz:
        try:
            p = subprocess.run([gz, "doctor"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
            out["checks"]["gzctf"] = "OK" if p.returncode == 0 else f"exit {p.returncode}"
        except Exception as exc:
            out["checks"]["gzctf"] = f"error: {exc}"
    else:
        out["checks"]["gzctf"] = "not installed"

    out["verdict"] = "ready" if out["solvable_targets"] > 0 else "connected-no-target"
    print("=" * 72)
    print(f"PREFLIGHT {out['ts']}  ->  {out['verdict'].upper()}  "
          f"(solvable targets: {out['solvable_targets']})")
    print("=" * 72)
    print(f"identity       : {out['checks']['identity'].get('name')} "
          f"(solves={out['checks']['identity'].get('solves')})")
    print(f"mode           : entries={len(entries)} index={index_ok} manifest={manifest_ok}")
    print(f"instance probe : {'OK' if probe_ok else 'UNAVAILABLE'} - {probe_detail[:140]}")
    print(f"{'suite':<12} {'reg':<6} {'my_solves':<10} {'qa_total':<9} {'qa_unsolved':<12} {'qa_wrong'}")
    for name, row in out["suites"].items():
        print(f"{name:<12} {str(row.get('registered')):<6} {str(row.get('my_solves')):<10} "
              f"{str(row.get('qa_total','-')):<9} {str(row.get('qa_unsolved','-')):<12} {row.get('qa_wrong','-')}")
    print(f"gzctf          : {out['checks'].get('gzctf')}")
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report         : {args.json}")
    if out["verdict"] == "ready":
        print("VERDICT: READY — QA targets available now" +
              ("" if not probe_ok else "; instances provision" ) )
        return 0
    print("VERDICT: CONNECTED BUT NO SOLVABLE TARGET — instance nodes down and QA pools exhausted")
    return 2


if __name__ == "__main__":
    sys.exit(main())

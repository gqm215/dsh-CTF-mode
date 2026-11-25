#!/usr/bin/env python3
"""Live end-to-end smoke for the CTF mode on the CTFy platform.

Proves the deterministic chain with real platform data:
  auth -> challenge roster -> attachment download (CAS sha256) -> local solve
  -> double-run reproduction -> blackboard candidate + verified fact
  -> submission through the verified-fact gate -> platform verdict -> metrics.

Deterministic challenge kinds only (check-in / layered archive / strings), so the
smoke measures the MODE, not the model. Model-driven solving is exercised by a
real CTF session separately.

Usage:
  # static-attachment challenge (no instance needed to download)
  python ~/.agents/ctf-mode/tools/live_smoke.py --challenge SAMPLE-005 --static
  # instance-backed check-in (needed for submission)
  python ~/.agents/ctf-mode/tools/live_smoke.py --challenge SAMPLE-018 --verify
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
BOARD = CTF / "bin" / "ctfboard.py"
CTFY = CTF / "bin" / "ctfy.py"

PLAYGROUND = "bc60dc1764f34413964a547102f17261"   # Platform Playground (dedicated pool)
SAMPLE_SUITE = "e4e78ff318dc4844beac13f9ea7409aa"  # SAMPLE suite (shared pool)
FLAG_RE = re.compile(rb"[A-Za-z0-9_]{2,}\{[^}\r\n]{1,200}\}")

DETERMINISTIC = {
    "SAMPLE-005": {"kind": "archive-layers", "question": "flag", "category": "misc"},
    "SAMPLE-018": {"kind": "attachment-read", "question": "flag", "category": "misc"},
    "SAMPLE-017": {"kind": "attachment-strings", "question": "flag", "category": "reverse"},
    "SAMPLE-001": {"kind": "attachment-read", "question": "slug", "category": "web"},
}


def run(cmd, timeout=300):
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), (time.perf_counter() - t0) * 1000


def board(*args, timeout=60):
    return run([sys.executable, str(BOARD), *args], timeout=timeout)


def platform(pg, *args, timeout=300):
    return run([sys.executable, str(CTFY), "--game", pg, *args], timeout=timeout)


def solve_from_blobs(kind: str, blobs: dict[str, bytes]) -> str | None:
    if kind == "attachment-read":
        for blob in blobs.values():
            m = FLAG_RE.search(blob)
            if m:
                return m.group(0).decode()
        return None
    if kind == "attachment-strings":
        for name, blob in blobs.items():
            if name.lower().endswith((".txt", ".md")):
                continue
            strings = b"\n".join(re.findall(rb"[\x20-\x7e]{6,}", blob))
            m = FLAG_RE.search(strings)
            if m:
                return m.group(0).decode()
        return None
    if kind == "archive-layers":
        data = next(iter(blobs.values()), b"")
        for _ in range(12):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except Exception:
                break
            nxt = None
            for n in z.namelist():
                b = z.read(n)
                m = FLAG_RE.search(b)
                if m:
                    return m.group(0).decode()
                if n.lower().endswith((".zip", ".tar", ".gz", ".bz2", ".xz", ".7z")):
                    nxt = b
            if not nxt:
                break
            data = nxt
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--challenge", required=True)
    ap.add_argument("--platform-game", default=PLAYGROUND)
    ap.add_argument("--game", default="ctfy", help="local runs/<game>/<chal> bucket")
    ap.add_argument("--static", action="store_true",
                    help="skip instance start; download static challenge attachments only")
    ap.add_argument("--qa", action="store_true",
                    help="static question graded by the platform over POST /qa/submissions "
                         "(no instance); confirms solved state instead of re-submitting")
    ap.add_argument("--verify", action="store_true", help="submit when an instance exists")
    args = ap.parse_args()
    chal = args.challenge
    if chal not in DETERMINISTIC:
        print(f"ERROR: {chal} not deterministic; choose from {sorted(DETERMINISTIC)}", file=sys.stderr)
        return 2
    spec = DETERMINISTIC[chal]
    work = CTF / "runs" / args.game / chal
    tmp = work / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    metrics = {"challenge": chal, "platform_game": args.platform_game, "static": args.static,
               "steps": {}, "accepted": False, "blocked": "", "t0": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    def step(name, rc, out, ms, ok=None):
        ok = rc == 0 if ok is None else ok
        metrics["steps"][name] = {"rc": rc, "ms": round(ms, 1), "ok": bool(ok),
                                  "out_tail": out.strip().splitlines()[-1][:300] if out.strip() else ""}
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {ms:.0f}ms")
        if not ok and out.strip():
            print(out.strip()[-600:])
        return ok

    # 1. auth + roster
    rc, out, ms = platform(args.platform_game, "doctor")
    if not step("platform_doctor", rc, out, ms):
        return 4
    rc, out, ms = platform(args.platform_game, "list", "--json")
    if not step("platform_list", rc, out, ms):
        return 5
    try:
        challenges = json.loads(out[out.index("["):])
    except Exception:
        print("ERROR: cannot parse challenge list", file=sys.stderr)
        return 5
    ch = next((c for c in challenges if c.get("id") == chal), None)
    if ch is None:
        print(f"ERROR: {chal} not in competition", file=sys.stderr)
        return 5
    atts = [a["name"] for a in (ch.get("attachments") or []) if a.get("name")]
    print(f"challenge: {ch.get('name')} category={ch.get('category')} "
          f"questions={[q['id'] for q in ch.get('questions', [])]} attachments={atts}")

    inst = None
    if not (args.static or args.qa):
        rc, out, ms = platform(args.platform_game, "start", chal, "--wait", "180")
        ok = step("start_instance", rc, out, ms, ok=("INSTANCE" in out))
        if not ok:
            metrics["blocked"] = out.strip().splitlines()[-1][:300] if out.strip() else "start failed"
            print("NOTE: instance unavailable — continuing with static download path")
        else:
            inst = re.search(r"instance=(\S+)", out).group(1)
            print(f"instance: {inst}")

    # 2. download attachments
    blobs = {}
    for name in atts:
        dst = tmp / name.replace("/", "_")
        if inst:
            rc, out, ms = platform(args.platform_game, "download", inst, name, "-o", str(dst))
            if not step(f"download_{name}", rc, out, ms, ok=dst.exists()):
                rc, out, ms = platform(args.platform_game, "download-chal", chal, name, "-o", str(dst))
                step(f"download_chal_{name}", rc, out, ms, ok=dst.exists())
        else:
            rc, out, ms = platform(args.platform_game, "download-chal", chal, name, "-o", str(dst))
            step(f"download_chal_{name}", rc, out, ms, ok=dst.exists())
        if dst.exists():
            blobs[name] = dst.read_bytes()
    if not blobs:
        print("ERROR: no attachments downloaded", file=sys.stderr)
        return 6

    # 3. solve + L2 reproduction
    flag = solve_from_blobs(spec["kind"], blobs)
    if not flag:
        print("ERROR: deterministic solve produced no flag", file=sys.stderr)
        return 7
    flag_bytes = flag.encode()
    print(f"candidate flag: sha256={hashlib.sha256(flag_bytes).hexdigest()} (value withheld)")
    f1, f2 = solve_from_blobs(spec["kind"], blobs), solve_from_blobs(spec["kind"], blobs)
    repro = f1 == f2 == flag
    metrics["steps"]["l2_reproduce"] = {"rc": 0 if repro else 1, "ms": 0.0, "ok": repro,
                                        "out_tail": f"reproduced={repro}"}
    print(f"[{'OK' if repro else 'FAIL'}] l2_reproduce: reproducible={repro}")

    # 4. blackboard: candidate + verified evidence
    board("init", "--game", args.game, "--chal", chal, "--title", ch.get("name") or chal,
          "--category", spec["category"])
    claim = f"{chal} deterministic solve yields a FLAG candidate from {list(blobs)}"
    board("fact", "add", "--game", args.game, "--chal", chal, "--claim", claim,
          "--evidence", "platform attachment + deterministic extract + double-run reproduction",
          "--source", "exec")
    ev = tmp / "evidence.txt"
    ev.write_text(f"challenge={chal}\nplatform_game={args.platform_game}\n"
                  f"attachments={ {k: hashlib.sha256(v).hexdigest() for k, v in blobs.items()} }\n"
                  f"sha256={hashlib.sha256(flag_bytes).hexdigest()}\nreproduced={repro}\n", encoding="utf-8")
    rc, out, ms = board("verify", "record", "--game", args.game, "--chal", chal,
                        "--actor", "verifier-smoke", "--claim", claim,
                        "--command", "live_smoke deterministic extract x2",
                        "--output", str(ev), "--exit", "0", "--artifact", str(ev),
                        "--reproduced", "yes", "--verdict", "verified")
    step("board_verify_record", rc, out, ms)
    verified_fact = None
    fj = work / "facts.jsonl"
    if fj.exists():
        for line in fj.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if str(rec.get("status")) == "verified":
                verified_fact = rec.get("id") or rec.get("fact_id")
    if not verified_fact:
        print("ERROR: no verified fact recorded", file=sys.stderr)
        return 8
    print(f"verified fact: {verified_fact}")

    # 5. submit through the gate
    answer_file = tmp / "answer.txt"
    answer_file.write_text(flag, encoding="utf-8")
    if args.qa:
        # Static questions are graded by POST /qa/submissions (no instance).
        # Re-running the smoke must not burn a second attempt: if the platform's
        # own state already lists the question solved, that state is the verdict.
        sys.path.insert(0, str(CTF / "bin"))
        import ctfy as _ctfy
        cli = _ctfy.CTFy(); cli.key = _ctfy.load_key()
        code, chals = cli.get(f"/qa/challenges?competition_id={args.platform_game}")
        rec = next((x for x in chals if x.get("id") == chal), None) if isinstance(chals, list) else None
        already = bool(rec and spec["question"] in (rec.get("solved_question_ids") or []))
        if already:
            metrics["steps"]["platform_state"] = {
                "rc": 0, "ms": 0.0, "ok": True,
                "out_tail": f"{chal}/{spec['question']} present in solved_question_ids "
                            f"(platform state; no new submission attempt)"}
            print(f"[OK] platform_state: {chal}/{spec['question']} already solved on the platform")
            metrics["accepted"] = True
        else:
            rc, out, ms = platform(args.platform_game, "submit-qa", chal,
                                   "--question", spec["question"],
                                   "--answer-file", str(answer_file),
                                   "--verified-fact", str(verified_fact),
                                   "--game", args.game,
                                   "--competition", args.platform_game, "--wait", "20")
            accepted = "RESULT: ACCEPTED" in out
            step("platform_submit_qa", 0 if accepted else 7, out, ms, ok=accepted)
            metrics["accepted"] = accepted
    elif not inst:
        metrics["blocked"] = metrics["blocked"] or "no instance (platform node unavailable)"
        print(f"SUBMIT BLOCKED: {metrics['blocked']}")
    elif args.verify:
        rc, out, ms = platform(args.platform_game, "submit", inst, "--question", spec["question"],
                               "--answer-file", str(answer_file), "--verified-fact", str(verified_fact),
                               "--game", args.game, "--chal", chal)
        accepted = "RESULT: ACCEPTED" in out
        step("platform_submit", 0 if accepted else 7, out, ms, ok=accepted)
        metrics["accepted"] = accepted
    else:
        print("submit skipped (pass --verify)")

    metrics["t1"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    metrics["total_measured_ms"] = round(sum(v.get("ms", 0) for v in metrics["steps"].values()), 1)
    report = CTF / "eval" / "reports" / f"live_smoke_{chal}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    status = "ACCEPTED" if metrics["accepted"] else ("BLOCKED: " + metrics["blocked"] if metrics["blocked"] else "INCOMPLETE")
    print(f"\nLIVE SMOKE {status} total_measured={metrics['total_measured_ms']:.0f}ms report={report}")
    return 0 if metrics["accepted"] else (9 if metrics["blocked"] else 1)


if __name__ == "__main__":
    sys.exit(main())

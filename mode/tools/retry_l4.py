#!/usr/bin/env python3
"""Bounded retry: wait for a shared-pool node, then run the instance-backed
SAMPLE-018 acceptance chain (live_smoke --verify) exactly once.

Writes one line per attempt to eval/reports/l4_retry.log.
"""
import subprocess, sys, time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
SMOKE = CTF / "tools" / "live_smoke.py"
LOG = CTF / "eval" / "reports" / "l4_retry.log"
SUITE = "e4e78ff318dc4844beac13f9ea7409aa"   # SAMPLE suite (shared pool)

deadline = time.time() + 20 * 60
attempt = 0
while time.time() < deadline:
    attempt += 1
    t0 = time.time()
    p = subprocess.run([sys.executable, str(SMOKE), "--challenge", "SAMPLE-018",
                        "--platform-game", SUITE, "--verify"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    line = f"[{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}] attempt {attempt} rc={p.returncode} {time.time()-t0:.0f}s :: {tail[:300]}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if p.returncode == 0 and "ACCEPTED" in out:
        print("L4 CHAIN ACCEPTED", flush=True)
        sys.exit(0)
    time.sleep(120)
print("L4 retry window expired without a healthy node", flush=True)
sys.exit(2)

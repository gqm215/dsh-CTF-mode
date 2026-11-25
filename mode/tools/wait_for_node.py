#!/usr/bin/env python3
"""Wait for a CTFy healthy node, then run the instance-backed live smoke.

The platform is currently answering `no_healthy_node` for every instance start
(platform-side outage, 2026-11-25). This watcher retries on a fixed interval and,
the moment an instance can be provisioned, runs the full smoke (start -> download
-> deterministic solve -> verified fact -> submit -> verdict) and writes the
report. Each attempt is appended to eval/reports/node_wait.log.

Run in background:  python ~/.agents/ctf-mode/tools/wait_for_node.py --hours 2
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CTF = HOME / ".agents" / "ctf-mode"
CTFY = CTF / "bin" / "ctfy.py"
SMOKE = CTF / "tools" / "live_smoke.py"
LOG = CTF / "eval" / "reports" / "node_wait.log"
SAMPLE_SUITE = "e4e78ff318dc4844beac13f9ea7409aa"
CHALLENGE = "SAMPLE-018"  # per-team attachment check-in; deterministic


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd, timeout=420):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--interval", type=float, default=120.0)
    args = ap.parse_args()
    deadline = time.time() + args.hours * 3600
    attempt = 0
    log(f"watcher start: challenge={CHALLENGE} suite={SAMPLE_SUITE} hours={args.hours}")
    while time.time() < deadline:
        attempt += 1
        rc, out = run([sys.executable, str(CTFY), "--game", SAMPLE_SUITE, "start", CHALLENGE, "--wait", "30"], timeout=180)
        inst = None
        for line in out.splitlines():
            if line.startswith("INSTANCE "):
                inst = line.split()[1]
        if inst:
            log(f"attempt {attempt}: node available, instance={inst} — running full smoke")
            rc2, out2 = run([sys.executable, str(SMOKE), "--challenge", CHALLENGE,
                             "--platform-game", SAMPLE_SUITE, "--verify"], timeout=600)
            tail = out2.strip().splitlines()[-1] if out2.strip() else out2[-300:]
            log(f"smoke rc={rc2}: {tail}")
            if inst:
                run([sys.executable, str(CTFY), "--game", SAMPLE_SUITE, "stop", inst], timeout=60)
            if rc2 == 0 and "ACCEPTED" in out2:
                log("watcher done: live smoke ACCEPTED")
                return 0
            log("smoke did not reach ACCEPTED; continuing to retry")
        else:
            reason = "no_healthy_node" if "no_healthy_node" in out else out.strip()[-200:]
            log(f"attempt {attempt}: not ready ({reason})")
        time.sleep(args.interval)
    log("watcher timeout: platform node never became available")
    return 2


if __name__ == "__main__":
    sys.exit(main())

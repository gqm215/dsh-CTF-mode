"""Extract mode-session metrics from the newest CTF-preset DSH session log.

Usage: python ~/.agents/ctf-mode/tools/session_metrics.py [--session ID] [--json OUT]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import zstandard

HOME = Path.home()
SESSIONS = HOME / ".dsh" / "sessions"


def newest_ctf_session():
    cands = []
    for ws in SESSIONS.iterdir():
        if not ws.is_dir():
            continue
        for d in ws.iterdir():
            f = d / "session.v4.jsonl.zstd"
            if f.exists():
                cands.append((f.stat().st_mtime, d))
    cands.sort(reverse=True)
    for _, d in cands:
        f = d / "session.v4.jsonl.zstd"
        with open(f, "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as r:
            head = r.read(200000).decode("utf-8", "replace")
        m = re.search(r'"agentPreset":"([^"]+)"', head)
        if m and m.group(1) == "ctf":
            return d
    return None


def load(d: Path):
    f = d / "session.v4.jsonl.zstd"
    with open(f, "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as r:
        raw = r.read()
    out = []
    for ln in raw.decode("utf-8", "replace").splitlines():
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def main():
    args = sys.argv[1:]
    want = None
    out_path = None
    if "--session" in args:
        want = args[args.index("--session") + 1]
    if "--json" in args:
        out_path = args[args.index("--json") + 1]
    d = None
    if want:
        for ws in SESSIONS.iterdir():
            cand = ws / want
            if cand.is_dir():
                d = cand
                break
    if d is None:
        d = newest_ctf_session()
    if d is None:
        print("ERROR: no CTF-preset session found", file=sys.stderr)
        return 2
    events = load(d)
    preset = None
    created = None
    for e in events:
        if e.get("type") == "session":
            preset = e.get("agentPreset")
            created = e.get("createdAt")
    times = [e.get("time") for e in events if e.get("time")]
    wall_ms = (max(times) - min(times)) if len(times) > 1 else 0

    tool_calls = []
    skill_loads = []
    model_calls = 0
    tok = {"input": 0, "output": 0, "cache_read": 0, "total": 0, "peak_total": 0}
    turns = steps = 0
    final_text = ""
    for e in events:
        t = e.get("type")
        data = e.get("data") or {}
        if t == "turn/start":
            turns += 1
        elif t == "step/start":
            steps += 1
        elif t == "tool/call":
            name = data.get("name", "?")
            tool_calls.append({"name": name, "args": data.get("arguments", "")[:500]})
            if name == "skill":
                try:
                    skill_loads.append(json.loads(data.get("arguments") or "{}").get("name"))
                except Exception:
                    pass
        elif t == "assistant/message":
            usage = data.get("usage")
            if isinstance(usage, dict) and usage:
                model_calls += 1
                tok["input"] += int(usage.get("inputTokens") or 0)
                tok["output"] += int(usage.get("outputTokens") or 0)
                tok["cache_read"] += int(usage.get("cacheReadTokens") or 0)
                tok["total"] += int(usage.get("totalTokens") or 0)
                tok["peak_total"] = max(tok["peak_total"], int(usage.get("totalTokens") or 0))
            for block in (data.get("message", {}) or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    final_text = block.get("text") or final_text
    tool_counter = Counter(x["name"] for x in tool_calls)
    cmds = [x["args"] for x in tool_calls if x["name"] in ("pwsh", "bash", "shell")]
    ctfboard_calls = sum(1 for a in cmds if "ctfboard.py" in a)
    ctfy_calls = sum(1 for a in cmds if "ctfy.py" in a)
    search_calls = sum(1 for a in cmds if "skillctl.py ctf search" in a)
    report = {
        "session": d.name,
        "preset": preset,
        "createdAt": created,
        "wall_seconds": round(wall_ms / 1000, 1),
        "turns": turns,
        "steps": steps,
        "model_calls": model_calls,
        "tool_calls": len(tool_calls),
        "tool_names": dict(tool_counter),
        "skill_loads": skill_loads,
        "ctfboard_calls": ctfboard_calls,
        "ctfy_calls": ctfy_calls,
        "knowledge_search_calls": search_calls,
        "tokens": tok,
        "final_answer": final_text[-2500:],
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    print(text)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"\nwritten: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctf_search_test.py — retrieval-quality gate for the CTF deep-skill index.

Runs 30 realistic CTF challenges/technique queries through the real CLI:

    python ~/.agents/tools/skillctl.py ctf search "<query>" --limit 3 --json

A query HITS when the expected skill name, or the expected skill's category,
appears in the top-3 results.  The gate is >= 27/30 hits; the script exits
nonzero below that.

Writes a per-query table to search_test_report.md next to this file.

Usage:
  python ~/.agents/ctf-mode/tools/ctf_search_test.py
  python ~/.agents/ctf-mode/tools/ctf_search_test.py --limit 3 --quiet
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
SKILLCTL = HOME / ".agents" / "tools" / "skillctl.py"
CTF_INDEX = HOME / ".agents" / "ctf-mode" / "index.json"
REPORT = Path(__file__).with_name("search_test_report.md")
GATE = 27  # required hits out of 30

# (query, expected skill name, why this is the target); the expected category is
# resolved from index.json so the hit rule "name OR its category in top-3" is exact.
CASES = [
    # --- pwn -----------------------------------------------------------------
    ("64-bit ELF stack overflow canary", "stack-overflow-and-rop",
     "classic stack overflow / canary bypass"),
    ("kernel module exploit KASLR", "kernel-exploitation",
     "kernel UAF/OOB to privesc, KASLR defeat"),
    ("heap tcache poisoning", "heap-exploitation",
     "glibc heap exploitation via tcache/fastbin"),
    # --- web -----------------------------------------------------------------
    ("SSTI Jinja2 template injection", "ssti-server-side-template-injection",
     "server-side template injection"),
    ("JWT none algorithm", "jwt-attack",
     "JWT alg=none / claim forgery"),
    ("SSRF gopher redis", "web-ssrf-gopher-redis-rce",
     "SSRF to RCE over gopher://"),
    ("prototype pollution Node", "prototype-pollution",
     "prototype pollution in Node/JS"),
    ("SQL injection sqlmap", "sqli-sqlmap",
     "SQLi with sqlmap"),
    ("log4j JNDI injection", "jndi-injection",
     "Log4Shell-style JNDI lookup injection"),
    # --- reverse -------------------------------------------------------------
    ("Android APK decompile", "mobile-apk-reverse",
     "APK unpack/decompile/patch"),
    ("WebAssembly reverse", "vm-and-bytecode-reverse",
     "WASM / custom VM bytecode reversing"),
    ("binary ninja decompiler", "reverse-eng-binary-ninja",
     "Binary Ninja workflow"),
    ("Ghidra decompile binary", "reverse-eng-ghidra",
     "Ghidra decompilation"),
    # --- crypto --------------------------------------------------------------
    ("RSA small exponent e=3 broadcast", "rsa-attack-techniques",
     "RSA e=3 / broadcast / Hastad"),
    ("AES CBC padding oracle", "crypto-oracle-attacks",
     "padding oracle / CBC bit flipping"),
    # --- forensics -----------------------------------------------------------
    ("pcap TLS decrypt keylog", "traffic-analysis-pcap",
     "PCAP analysis + TLS decryption"),
    ("disk image deleted files carve", "ctf-forensics",
     "disk image / deleted-file carving"),
    ("PNG LSB steganography", "steganography-techniques",
     "LSB stego extraction"),
    ("Windows event log evtx", "ctf-forensics",
     "evtx / Windows event logs"),
    # --- ai-ml ---------------------------------------------------------------
    ("LLM prompt injection jailbreak", "ai-prompt-injection",
     "prompt injection / jailbreak"),
    ("prompt injection RAG poisoning", "ai-rag-poisoning",
     "indirect injection via RAG corpus"),
    # --- blue ----------------------------------------------------------------
    ("Sigma detection rule", "building-detection-rules-with-sigma",
     "Sigma detection engineering"),
    ("DFIR incident response triage", "defense-dfir-triage",
     "first-response DFIR triage"),
    # --- red -----------------------------------------------------------------
    ("NTLM relay hash capture", "ntlm-relay-coercion",
     "NTLM relay/coercion"),
    ("Kubernetes pod escape", "kubernetes-pentesting",
     "Kubernetes attack paths / pod escape"),
    # --- malware -------------------------------------------------------------
    ("YARA rule malware analysis", "malware-reverse-engineering",
     "malware triage + YARA"),
    # --- osint ---------------------------------------------------------------
    ("geolocation image OSINT satellite", "ctf-osint",
     "image geolocation / OSINT"),
    # --- misc ----------------------------------------------------------------
    ("Morse code audio", "ctf-misc",
     "Morse / audio puzzle"),
    ("pyjail python escape globals", "web-python-sandbox-escape",
     "python eval jail / sandbox escape (noor web-domain skill)"),
    ("encoding esolang QR puzzle", "ctf-misc",
     "encoding / esolang / QR puzzle"),
]


def run_search(query, limit=3):
    """Invoke the real CLI and return (top_results, error_text)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, str(SKILLCTL), "ctf", "search", query,
           "--limit", str(limit), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        return [], (proc.stderr or proc.stdout).strip()
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        return [], f"bad json from CLI: {exc}"
    return payload.get("results", []), ""


def load_index_meta():
    try:
        index = json.loads(CTF_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = None
    if not index:
        return None, {}
    return index, {skill["name"]: skill for skill in index.get("skills", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=3,
                        help="results inspected per query (default 3, the gate definition)")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    args = parser.parse_args()

    index, by_name = load_index_meta()
    rows, misses, errors = [], [], []
    if index is None:
        print(f"FATAL: no usable index at {CTF_INDEX}; run: "
              f"python {SKILLCTL} ctf index", file=sys.stderr)
        return 2

    for number, (query, expected, note) in enumerate(CASES, 1):
        meta = by_name.get(expected)
        if meta is None:
            print(f"FATAL: expected skill {expected!r} is not in the index; "
                  f"run: python {SKILLCTL} ctf index", file=sys.stderr)
            return 2
        expected_cat = meta["category"]
        results, error = run_search(query, args.limit)
        top_names = [r.get("name", "") for r in results]
        top_cats = [r.get("category", "") for r in results]
        if error:
            hit, reason = False, "CLI error: " + error[:120]
            errors.append((query, reason))
        else:
            hit = expected in top_names or expected_cat in top_cats
            if expected in top_names:
                reason = "expected name in top-%d" % args.limit
            elif expected_cat in top_cats:
                reason = "expected category %r in top-%d" % (expected_cat, args.limit)
            else:
                reason = "miss"
        if not hit:
            misses.append((number, query, expected, reason))
        rows.append({
            "number": number, "query": query, "expected": expected,
            "expected_cat": expected_cat, "note": note, "hit": hit,
            "reason": reason, "top": list(zip(top_names, top_cats)),
        })
        if not args.quiet:
            mark = "HIT " if hit else "MISS"
            tops = "; ".join(f"{n}[{c}]" for n, c in rows[-1]["top"]) or "(none)"
            print(f"{mark} {number:2d}. {query}")
            print(f"        expect {expected} [{expected_cat}] -> {tops}")

    hits = sum(1 for row in rows if row["hit"])
    passed = hits >= GATE
    now = datetime.datetime.now().isoformat(timespec="seconds")

    if not args.quiet:
        print()
    print(f"index: {CTF_INDEX} count={index.get('count')} "
          f"generated={index.get('generated')}")
    print(f"result: {hits}/{len(CASES)} hits (gate >= {GATE}/30) -> "
          f"{'PASS' if passed else 'FAIL'}")
    if misses:
        print("misses: " + "; ".join(f"#{n} {q}" for n, q, _, _ in misses))
    if errors:
        print("errors: " + "; ".join(f"{q}: {e}" for q, e in errors))

    report = build_report(rows, hits, passed, index, now, missed_rows=misses)
    REPORT.write_text(report, encoding="utf-8")
    if not args.quiet:
        print(f"report: {REPORT}")
    return 0 if passed else 1


def build_report(rows, hits, passed, index, now, missed_rows):
    total = len(rows)
    lines = [
        "# CTF deep-skill index — search quality report",
        "",
        f"- generated: {now}",
        f"- index: `{CTF_INDEX}` "
        f"(count={index.get('count')}, generated={index.get('generated')})",
        f"- pools_root: `{index.get('pools_root')}`",
        f"- CLI under test: `python ~/.agents/tools/skillctl.py ctf search \"<q>\" "
        f"--limit 3 --json`",
        f"- hit rule: expected skill name OR expected category in top-3",
        f"- **score: {hits}/{total} hits — gate >= {GATE}/{total} -> "
        f"{'PASS' if passed else 'FAIL'}**",
        "",
        "## Per-query table",
        "",
        "| # | query | expected (category) | top-3 (category) | hit |",
        "|---:|---|---|---|---|",
    ]
    for row in rows:
        tops = "<br>".join(f"{n} [{c}]" for n, c in row["top"]) or "(none)"
        lines.append(f"| {row['number']} | {row['query']} | "
                     f"{row['expected']} ({row['expected_cat']}) | {tops} | "
                     f"{'HIT' if row['hit'] else 'MISS'} |")
    lines += ["", "## Category coverage", ""]
    from collections import Counter
    covered = Counter(row["expected_cat"] for row in rows)
    hit_by_cat = Counter(row["expected_cat"] for row in rows if row["hit"])
    for cat, count in covered.most_common():
        lines.append(f"- {cat}: {hit_by_cat.get(cat, 0)}/{count} hits")
    lines += ["", "## Misses", ""]
    if missed_rows:
        for number, query, expected, reason in missed_rows:
            lines.append(f"- #{number} `{query}` — expected `{expected}` ({reason})")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Reproduce",
        "",
        "```powershell",
        "python ~/.agents/tools/skillctl.py ctf index        # refresh index",
        "python ~/.agents/ctf-mode/tools/ctf_search_test.py  # this gate",
        "python ~/.agents/tools/skillctl.py ctf doctor       # index vs pools",
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

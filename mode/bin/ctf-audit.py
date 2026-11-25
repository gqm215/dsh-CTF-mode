#!/usr/bin/env python3
"""ctf-audit.py — independent compliance auditor (监察员) for one CTF run.

The auditor does NOT decide whether a flag is correct (the platform verdict is the
verification) and never blocks a submission. It observes **behavior discipline**
and, when a run fails or a rule is broken, produces an accountability report:

  1. provenance      every submission has a recorded basis:
                     * `platform-auto` — execution evidence file produced BEFORE the
                       submit (the fast path; no verified fact needed);
                     * `verified-fact` — a Re-checker (checker-*, legacy verifier-*) recorded the fact beforehand
                       (fallback channel). A verified fact is never a precondition for
                       the fast path, and the `checker-platform` fact written after
                       acceptance is a record, not evidence-before-submit.
  2. governor        attempts <= max_attempts, attempt counter matches the log
  3. idempotency     no (challenge+question, answer) pair submitted twice
  4. acceptance      ACCEPTED.txt / final/flag.txt iff the platform said accepted;
                     no claimed success without a verdict
  5. flag hygiene    raw flag only in final/flag.txt, ACCEPTED.txt, writeup.md —
                     never in logs/telemetry/json state
  6. credential hygiene  no pf_ token / bearer / session cookie material in the
                     run directory or traces
  7. tooling integrity   the mode's own tooling was not modified during the
                     solve (requires --session; optional manifest comparison)
  8. session conduct (optional, --session)  scans the agent transcript for
                     process interference / edits to ~/.agents/ctf-mode / direct
                     platform submissions outside the adapters

Usage:
  python ctf-audit.py --game 5 --chal 51
  python ctf-audit.py --game 5 --chal 51 --session session-... --json audit.json
  python ctf-audit.py --bless          # write the tooling integrity manifest

Exit: 0 = no BREACH (warnings allowed), 1 = at least one BREACH.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

CTF = Path.home() / ".agents" / "ctf-mode"
BIN = CTF / "bin"
TOOLS = CTF / "tools"
RESIDENT = CTF / "roots" / "resident"
MANIFEST = TOOLS / "integrity_manifest.json"
SESSIONS = Path.home() / ".dsh" / "sessions"

FLAG_RE = re.compile(rb"[A-Za-z0-9_]{2,}\{[^}\r\n]{1,200}\}")
CRED_PATTERNS = [
    ("pf_token", re.compile(rb"pf_[A-Za-z0-9_\-]{20,}")),
    ("bearer", re.compile(rb"Bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("teamkey", re.compile(rb"[\"']teamKey[\"']\s*:\s*[\"'][A-Za-z0-9_\-]{16,}")),
]


def load_ctfboard():
    spec = importlib.util.spec_from_file_location("ctfboard_mod", BIN / "ctfboard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ctfboard_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def read_jsonl(path: Path):
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def walk_files(root: Path):
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            yield p


def read_bytes(p: Path, cap: int = 4_000_000):
    try:
        if p.stat().st_size > cap:
            return b""
        return p.read_bytes()
    except Exception:
        return b""


def tooling_files():
    for base in (BIN, TOOLS, RESIDENT):
        for p in walk_files(base):
            yield p


def hash_manifest() -> dict:
    return {str(p.relative_to(CTF)): hashlib.sha256(read_bytes(p)).hexdigest()
            for p in tooling_files() if p != MANIFEST}


def load_session_events(session_id: str):
    """Return (createdAt_ms, events) for the DSH session, or (None, []) when the
    session log/zstd reader is unavailable (the audit then skips conduct checks)."""
    for ws in SESSIONS.iterdir() if SESSIONS.exists() else []:
        if not ws.is_dir():
            continue
        d = ws / session_id
        f = d / "session.v4.jsonl.zstd"
        if not f.exists():
            continue
        try:
            import zstandard  # optional dependency; skip conduct checks if absent
        except Exception:
            return None, []
        with open(f, "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as reader:
            raw = reader.read()
        created = None
        events = []
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") == "session":
                created = rec.get("createdAt")
            events.append(rec)
        return created, events
    return None, []


def main() -> int:
    ap = argparse.ArgumentParser(description="CTF run compliance auditor (监察员)")
    ap.add_argument("--game")
    ap.add_argument("--chal")
    ap.add_argument("--session", help="DSH session id; enables conduct + live-integrity checks")
    ap.add_argument("--json", help="write the report JSON here")
    ap.add_argument("--bless", action="store_true", help="write the tooling integrity manifest")
    args = ap.parse_args()

    if args.bless:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                        "files": hash_manifest()}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"BLESSED integrity manifest: {MANIFEST} ({len(hash_manifest())} files)")
        return 0

    if not args.game or not args.chal:
        print("ERROR: --game and --chal are required (or use --bless)", file=sys.stderr)
        return 2
    ctfb = load_ctfboard()
    game, chal = ctfb.safe_component(args.game, "game"), ctfb.safe_component(args.chal, "chal")
    rd = ctfb.require_challenge(game, chal)
    findings = []

    def add(code, severity, detail):
        findings.append({"code": code, "severity": severity, "detail": detail})

    facts = read_jsonl(ctfb.facts_path(rd))
    verifies = read_jsonl(ctfb.verifies_path(rd))
    submissions = read_jsonl(ctfb.submissions_path(rd))
    state = ctfb.load_state(rd)
    governor = ctfb.governor_config()
    max_attempts = int(governor.get("max_attempts", 10) or 10)
    attempts = int(state.get("attempts", 0) or 0)

    # 1. provenance --------------------------------------------------------
    verified_claims = {ctfb.normalize_claim(str(f.get("claim", ""))) for f in facts
                       if str(f.get("status")) == "verified"}
    for i, rec in enumerate(submissions, 1):
        basis = str(rec.get("basis") or "")
        sha = str(rec.get("flag_sha256") or "").lower()
        if basis == "platform-auto":
            # Fast path: the submission must be backed by the execution evidence
            # the executor produced BEFORE submitting.
            ev = Path(str(rec.get("evidence") or "")).expanduser()
            if not ev.is_file() or ev.stat().st_size == 0:
                add("PROVENANCE", "BREACH",
                    f"submission #{i} (sha {sha[:12]}) is platform-auto but its evidence file is missing/empty: {ev}")
        elif basis == "verified-fact":
            # Fallback path: a Re-checker had recorded the fact before this submit.
            # Note a verified fact is NOT required for the fast path, and the
            # post-acceptance checker-platform fact is a record, not a precondition.
            if not verified_claims:
                add("PROVENANCE", "BREACH",
                    f"submission #{i} (sha {sha[:12]}) claims a verified-fact basis but the board has no verified fact")
            else:
                linked = False
                for f in facts:
                    if str(f.get("status")) != "verified":
                        continue
                    blob = str(f.get("evidence") or "") + " " + str(f.get("claim") or "")
                    artifact = Path(str(f.get("artifact") or "")).expanduser()
                    if artifact.is_file():
                        try:
                            blob += " " + artifact.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            pass
                    if sha and sha in blob.lower():
                        linked = True
                        break
                if not linked:
                    add("PROVENANCE", "WARN",
                        f"submission #{i} uses a verified-fact basis but no verified fact's evidence references its sha256")
        else:
            add("PROVENANCE", "WARN",
                f"submission #{i} has no recorded basis (legacy record; verify the evidence by hand)")

    # 2. governor ----------------------------------------------------------
    if attempts > max_attempts:
        add("GOVERNOR", "BREACH", f"attempts {attempts} exceed max_attempts {max_attempts}")
    if attempts != len(submissions):
        add("GOVERNOR", "WARN",
            f"state.attempts={attempts} but submissions.jsonl has {len(submissions)} entries")
    if attempts >= 3 and not any("review" in str(v).lower() for v in
                                 [str(state.get("review_required", "")), str(state.get("approval_required", ""))]):
        # governor guidance is advisory; only informational
        add("GOVERNOR", "INFO", f"{attempts} attempts used; confirm review/approval guidance was respected")

    # 3. idempotency -------------------------------------------------------
    seen = {}
    for rec in submissions:
        key = (str(rec.get("cid") or ""), str(rec.get("flag_sha256") or ""))
        seen[key] = seen.get(key, 0) + 1
    for (cid, sha), n in seen.items():
        if n > 1:
            add("IDEMPOTENCY", "BREACH", f"same (cid={cid}, sha={sha[:12]}) submitted {n} times")

    # 4. acceptance consistency -------------------------------------------
    verdicts = [str(r.get("verdict") or "").lower() for r in submissions]
    accepted = "accepted" in verdicts
    accepted_file = rd / "ACCEPTED.txt"
    flag_file = rd / "final" / "flag.txt"
    if accepted and not accepted_file.exists():
        add("ACCEPTANCE", "WARN", "platform accepted but ACCEPTED.txt is missing")
    if accepted and not flag_file.exists():
        add("ACCEPTANCE", "BREACH", "platform accepted but final/flag.txt is missing (flag deliverable lost)")
    if flag_file.exists() and not accepted:
        add("ACCEPTANCE", "BREACH",
            "final/flag.txt exists while no submission has an accepted verdict (unproven success claim)")
    for f in facts:
        if str(f.get("status")) == "verified" and not str(f.get("actor", "")).lower().startswith(("checker", "verifier")):
            add("ACCEPTANCE", "BREACH", f"verified fact {f.get('id')} was written by {f.get('actor')!r}")
        if str(f.get("claim", "")).strip().lower().startswith("accepted") and not accepted:
            add("ACCEPTANCE", "WARN", f"fact {f.get('id')} claims acceptance but no accepted verdict exists")

    # 5. flag hygiene ------------------------------------------------------
    # Authoritative flag values come from the deliverables; only those exact
    # values matter. Working areas (tmp/, final/, artifacts/) may legitimately
    # contain the flag (answer files, attachments); log/state files must not.
    authoritative = set()
    for p in (accepted_file, flag_file):
        if p.exists():
            authoritative.update(m.group(0) for m in FLAG_RE.finditer(read_bytes(p)))
    allowed_prefixes = ("final/", "tmp/", "artifacts/")
    for p in walk_files(rd):
        try:
            rel = p.relative_to(rd).as_posix()
        except Exception:
            continue
        if rel.startswith(allowed_prefixes) or rel == "ACCEPTED.txt":
            continue
        blob = read_bytes(p)
        for fl in authoritative:
            if fl in blob:
                add("FLAG_HYGIENE", "BREACH",
                    f"authoritative flag value appears outside the deliverables: {rel} ({fl[:24]}...)")
                break
    writeup = rd / "final" / "writeup.md"
    if accepted and writeup.exists() and authoritative:
        wb = read_bytes(writeup)
        if not any(fl in wb for fl in authoritative):
            add("FLAG_HYGIENE", "WARN", "writeup.md does not contain the accepted flag (writeups need the flag)")

    # 6. credential hygiene ------------------------------------------------
    for p in walk_files(rd):
        blob = read_bytes(p)
        for name, pat in CRED_PATTERNS:
            if pat.search(blob):
                try:
                    rel = p.relative_to(rd)
                except Exception:
                    rel = p
                add("CREDENTIAL_HYGIENE", "BREACH", f"credential material ({name}) found in {rel}")

    # 7/8. tooling integrity + conduct (needs --session) -------------------
    if args.session:
        created, events = load_session_events(args.session)
        if created is None and not events:
            add("CONDUCT", "INFO", f"session {args.session} log unavailable; conduct checks skipped")
        else:
            if created:
                start_s = created / 1000.0
                touched = []
                for p in tooling_files():
                    if p == MANIFEST:
                        continue
                    try:
                        if p.stat().st_mtime > start_s + 1:
                            touched.append(str(p.relative_to(CTF)))
                    except Exception:
                        pass
                if touched:
                    add("TOOLING_INTEGRITY", "BREACH",
                        "mode tooling modified during the solve window: " + ", ".join(touched[:8]))
            tool_paths = [str(p.relative_to(CTF)) for p in tooling_files()]
            for rec in events:
                if rec.get("type") != "tool/call":
                    continue
                args_s = str((rec.get("data") or {}).get("arguments") or "")
                name = str((rec.get("data") or {}).get("name") or "")
                if re.search(r"Stop-Process|taskkill|pkill\s|kill\s+-", args_s) and "ctf-mode" not in args_s:
                    add("CONDUCT", "WARN", f"{name}: process termination call observed (verify it targeted only its own children)")
                if re.search(r"ctf-mode[\\\\/](bin|tools|roots)", args_s) and re.search(r"\b(Set-Content|Out-File|write|edit)\b", args_s, re.I):
                    add("CONDUCT", "WARN", f"{name}: write to mode tooling path observed")
                if re.search(r"/api/v1/(submissions|qa/submissions)", args_s) and "ctfy.py" not in args_s:
                    add("CONDUCT", "WARN", f"{name}: direct platform submission outside the adapter observed")
            if os.environ.get("CTF_AUDIT_STRICT"):
                for p in tool_paths:
                    if not (CTF / p).exists():
                        add("TOOLING_INTEGRITY", "BREACH", f"tooling file disappeared: {p}")

    # integrity manifest comparison (if blessed)
    if MANIFEST.exists() and not args.session:
        try:
            blessed = json.loads(MANIFEST.read_text(encoding="utf-8")).get("files", {})
            current = hash_manifest()
            changed = [k for k in blessed if blessed.get(k) != current.get(k)]
            missing = [k for k in blessed if k not in current]
            if changed or missing:
                add("TOOLING_INTEGRITY", "BREACH",
                    f"tooling differs from the blessed manifest (changed={len(changed)}, missing={len(missing)})")
        except Exception as exc:
            add("TOOLING_INTEGRITY", "WARN", f"manifest unreadable: {exc}")

    # report ---------------------------------------------------------------
    breaches = [f for f in findings if f["severity"] == "BREACH"]
    warns = [f for f in findings if f["severity"] == "WARN"]
    infos = [f for f in findings if f["severity"] == "INFO"]
    verdict = "BREACH" if breaches else ("WARN" if warns else "OK")
    report = {
        "game": game, "chal": chal, "session": args.session, "audited_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verdict": verdict,
        "counts": {"breach": len(breaches), "warn": len(warns), "info": len(infos)},
        "attempts": attempts, "max_attempts": max_attempts,
        "submissions": len(submissions), "accepted": accepted,
        "findings": findings,
    }
    lines = [f"# Compliance audit — {game}/{chal}", "",
             f"- audited: {report['audited_at']}",
             f"- verdict: **{verdict}** ({len(breaches)} breach, {len(warns)} warn, {len(infos)} info)",
             f"- submissions: {len(submissions)} / attempts {attempts}/{max_attempts}; accepted={accepted}",
             "", "| severity | code | detail |", "|---|---|---|"]
    for f in findings:
        lines.append(f"| {f['severity']} | {f['code']} | {f['detail'][:220]} |")
    if not findings:
        lines.append("| OK | — | no rule violations found |")
    text = "\n".join(lines) + "\n"
    (rd / "audit.md").write_text(text, encoding="utf-8")
    print(text)
    if args.json:
        Path(args.json).expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
        print(f"json: {args.json}")
    return 0 if not breaches else 1


if __name__ == "__main__":
    sys.exit(main())

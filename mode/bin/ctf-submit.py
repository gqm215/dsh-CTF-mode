#!/usr/bin/env python3
"""ctf-submit.py -- thin, gated adapter over the global ``gzctf`` CLI (SPEC §5 L3).

It does NOT talk to the platform itself and does NOT own credentials:

  * platform config (base_url / game_id) is read from ``~/.gzctf/config.json``
    (or ``$GZCTF_CONFIG``) and passed through as ``GZCTF_BASE_URL`` /
    ``GZCTF_GAME_ID``; ``session.json`` is owned exclusively by ``gzctf`` and is
    never read, printed, copied or modified here;
  * two submission bases: (a) the fast path ``--auto --evidence <file>`` when the
    executor has conclusive execution evidence (the platform verdict IS the
    verification; this is the default for first-to-solve speed), or
    (b) ``--verified-fact`` naming a fact that is ``verified`` in facts.jsonl and
    backed by a ``verified`` record in verifies.jsonl (fallback when the platform
    channel is unavailable or an independent audit is wanted);
  * the same (challenge, answer) pair is never sent twice (idempotent dedupe);
    a different candidate may be submitted again subject to the governor;
  * the submit governor is checked before the platform is called
    (attempts >= max_attempts -> exit 3);
  * logs keep only the flag sha256; on ACCEPTED the flag is written to
    ``final/flag.txt`` + ``ACCEPTED.txt`` (the flag is the deliverable) and a
    verified fact with actor ``checker-platform`` is recorded;
  * HTTP 200 is NOT accepted.  Only the platform's terminal verdict
    (``STATUS=Accepted``) or membership of the challenge in the account's
    solved-id set counts;
  * a logged-out platform (HTTP 401) is reported clearly with exit 4 and the
    fix is documented; authentication is never attempted or bypassed here.

Exit codes:
  0  platform accepted the flag
  1  platform rejected the flag (terminal non-accepted verdict)
  2  usage/config error
  3  gate refusal (no verified fact / no --evidence / governor / duplicate)
  4  platform auth problem (401 / logged out) -- run ``gzctf login -u <user>``
  5  platform/transport error, no verdict
  6  submitted but not yet terminal (pending) -- poll with ``gzctf verify``

Examples (PowerShell):
  python ctf-submit.py --game 2026-fall --chal web-01 --verified-fact f3 \\
      --cid 12 --flag-file .\\final\\flag.txt --dry-run
  python ctf-submit.py --game 2026-fall --chal web-01 --verified-fact f3 \\
      --cid 12 --flag-file .\\final\\flag.txt
  python ctf-submit.py --verify-prefix p6-
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The CTF state plane lives next to this script; reuse its config/paths/telemetry
# helpers instead of duplicating them.  Keep the bin/ directory free of __pycache__.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctfboard  # noqa: E402  (import after sys.path is adjusted)

SUBMIT_ID_RE = re.compile(r"submit_id=(\S+)\s+STATUS=(\S+)")
SOLVED_IDS_RE = re.compile(r"已解题[^\d]*((?:\d+[,\s]*)*)", re.UNICODE)
AUTH_RE = re.compile(r"HTTP\s*401|\b401\b|未登录|登录态|会话过期|gzctf login", re.IGNORECASE)
NOT_PARTICIPATED_RE = re.compile(r"尚未参赛|没有参赛|未参赛")
REJECT_STATUSES = {"WrongAnswer", "NotFound", "CheatDetected"}
PENDING_STATUSES = {"Pending", "FlagSubmitted"}
MAX_OUTPUT_LINES = 40


# ---------------------------------------------------------------------------
# Platform config (never session.json)
# ---------------------------------------------------------------------------


def gzctf_home() -> Path:
    return Path(os.environ.get("GZCTF_HOME") or (Path.home() / ".gzctf"))


def platform_config_path() -> Path:
    return Path(os.environ.get("GZCTF_CONFIG") or (gzctf_home() / "config.json"))


def load_platform_config() -> Dict[str, Any]:
    path = platform_config_path()
    if not path.is_file():
        raise ctfboard.CliError(
            f"platform config not found: {path}\n"
            "  fix: gzctf init --base-url <url> --game <id>  (or set GZCTF_CONFIG)"
        )
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ctfboard.CliError(f"platform config is not valid JSON: {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ctfboard.CliError(f"platform config must be a JSON object: {path}")
    if not cfg.get("base_url"):
        raise ctfboard.CliError(f"platform config has no base_url: {path}")
    if cfg.get("game_id") in (None, ""):
        raise ctfboard.CliError(f"platform config has no game_id: {path}")
    return cfg


def find_gzctf_cli() -> List[str]:
    override = os.environ.get("CTF_GZCTF_EXE", "").strip()
    if override:
        return [override]
    for name in ("gzctf", "gzctf.cmd", "gzctf.exe"):
        found = shutil.which(name)
        if found:
            return [found]
    fallback = Path.home() / ".local" / "bin" / "gzctf.cmd"
    if fallback.is_file():
        return [str(fallback)]
    raise ctfboard.CliError(
        "gzctf CLI not found on PATH (expected a gzctf.cmd shim); "
        "install it or set CTF_GZCTF_EXE to its path"
    )


def platform_env(cfg: Dict[str, Any]) -> Dict[str, str]:
    env = os.environ.copy()
    # Explicit pass-through of the config file values (env overrides are the
    # documented way to steer the gzctf CLI; it still owns the session).
    env["GZCTF_BASE_URL"] = str(cfg["base_url"])
    env["GZCTF_GAME_ID"] = str(cfg["game_id"])
    if cfg.get("timeout") is not None:
        env["GZCTF_TIMEOUT"] = str(cfg["timeout"])
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _render(command: List[str]) -> str:
    """Render a command for dry-run output, quoting only when needed."""
    parts: List[str] = []
    for part in command:
        if part and all(ch.isalnum() or ch in "-_./:=+\\@" for ch in part):
            parts.append(part)
        else:
            parts.append('"' + part.replace('"', '\\"') + '"')
    return " ".join(parts)


def run_cli(command: List[str], env: Dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run the gzctf shim (wrapping .cmd/.bat in cmd.exe when needed)."""
    executable = command[0]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        argv = [comspec, "/c"] + command
    else:
        argv = command
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ctfboard.CliError(f"cannot run gzctf CLI ({_render(command)}): {exc}", code=5) from exc


def _combined_output(proc: subprocess.CompletedProcess[str]) -> str:
    return f"{proc.stdout or ''}\n{proc.stderr or ''}"


def _echo_platform(proc: subprocess.CompletedProcess[str]) -> None:
    lines: List[str] = []
    for stream in (proc.stdout or "", proc.stderr or ""):
        for line in stream.splitlines():
            line = line.strip()
            if line:
                lines.append(ctfboard.sanitize_line(line, 500))
    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[:MAX_OUTPUT_LINES] + [f"... ({len(lines) - MAX_OUTPUT_LINES} more lines)"]
    for line in lines:
        print(f"PLATFORM {line}")


# ---------------------------------------------------------------------------
# Board gate helpers
# ---------------------------------------------------------------------------


def find_verified_fact(directory: Path, fact_id: str) -> Dict[str, Any]:
    facts = ctfboard.read_jsonl(ctfboard.facts_path(directory))
    fact = next((item for item in facts if str(item.get("id")) == fact_id), None)
    if fact is None:
        ids = ", ".join(str(item.get("id")) for item in facts[:10]) or "(none)"
        raise ctfboard.CliError(
            f"REFUSED fact {fact_id!r} does not exist on the board (known: {ids}); "
            "submit only a verified fact id",
            code=3,
        )
    if str(fact.get("status")) != "verified":
        raise ctfboard.CliError(
            f"REFUSED fact {fact_id} has status {fact.get('status')!r}, not 'verified'; "
            "verify it first with `ctfboard.py verify record --verdict verified "
            "--reproduced yes --exit 0 --actor checker-<name>` (legacy verifier- accepted)",
            code=3,
        )
    # Cross-check the verification evidence, not just the status label.
    claim_key = ctfboard.normalize_claim(str(fact.get("claim", "")))
    verifies = ctfboard.read_jsonl(ctfboard.verifies_path(directory))
    backed = any(
        str(record.get("verdict")) == "verified"
        and ctfboard.normalize_claim(str(record.get("claim", ""))) == claim_key
        for record in verifies
    )
    if not backed:
        raise ctfboard.CliError(
            f"REFUSED fact {fact_id} is marked verified but has no matching verified "
            "evidence block in verifies.jsonl; re-record it with `ctfboard.py verify record`",
            code=3,
        )
    return fact


def governor_precheck(state: Dict[str, Any]) -> Dict[str, int]:
    governor = ctfboard.governor_config()
    attempts = int(state.get("attempts", 0) or 0)
    if attempts >= governor["max_attempts"]:
        raise ctfboard.CliError(
            f"REFUSED submit governor: attempts {attempts}/{governor['max_attempts']} "
            "exhausted; no further submissions allowed for this challenge",
            code=3,
        )
    if attempts >= governor["review_after"]:
        print(
            f"WARN governor: attempts {attempts}/{governor['max_attempts']}; independent "
            f"review and user approval are required before further submissions "
            f"(review_after={governor['review_after']})",
            file=sys.stderr,
        )
    return governor


# ---------------------------------------------------------------------------
# Verdict parsing (HTTP 200 is NOT accepted)
# ---------------------------------------------------------------------------


def _auth_failure(text: str) -> bool:
    return bool(AUTH_RE.search(text))


def _solved_ids(env: Dict[str, str], cli: List[str], timeout: float) -> Optional[set[int]]:
    proc = run_cli(cli + ["solved"], env, timeout)
    if proc.returncode != 0 or _auth_failure(_combined_output(proc)):
        return None
    match = SOLVED_IDS_RE.search(proc.stdout or "")
    if not match:
        return set()
    return {int(token) for token in re.findall(r"\d+", match.group(1))}


def classify(proc: subprocess.CompletedProcess[str], env: Dict[str, str], cli: List[str],
             cid: str, timeout: float) -> Tuple[str, str, str, bool]:
    """Return (verdict, status, submit_id, accepted_by_solved_set)."""
    stdout = proc.stdout or ""
    combined = _combined_output(proc)
    match = SUBMIT_ID_RE.search(stdout)
    if match:
        sid = match.group(1)
        status = match.group(2)
    else:
        sid, status = "-", ""

    if status.startswith("HTTP"):
        code = re.sub(r"\D", "", status) or "?"
        if code in ("401", "403") or _auth_failure(combined):
            return "auth", status, sid, False
        return "error", status, sid, False
    if not status:
        if _auth_failure(combined):
            return "auth", "HTTP401", sid, False
        if NOT_PARTICIPATED_RE.search(combined):
            return "error", "NOT_PARTICIPATED", sid, False
        if proc.returncode != 0:
            return "error", "NO_VERDICT", sid, False
        # rc==0 without a parseable verdict; fall through to the solved check.
        status = "Unknown"

    if status == "Accepted":
        return "accepted", status, sid, True
    if status in REJECT_STATUSES:
        return "rejected", status, sid, False
    if status == "NO_ROUTE":
        return "error", status, sid, False

    # Non-terminal: the authoritative platform read is the account's solved-id
    # set.  This is the only path that can promote a non-"Accepted" reply.
    solved = _solved_ids(env, cli, timeout)
    if solved is not None and cid.isdigit() and int(cid) in solved:
        return "accepted", status, sid, True
    if status in PENDING_STATUSES or status.startswith("Enum") or status == "Unknown":
        return "pending", status, sid, False
    return "pending", status, sid, False


def record_platform_accept(directory: Path, game: str, chal: str, cid: str,
                           flag_text: str, flag_hash: str) -> None:
    """The platform verdict IS the verification: write the deliverable flag, a loud
    acceptance record, and a verified fact (actor checker-platform)."""
    board_script = Path(__file__).resolve().with_name("ctfboard.py")
    tmp = directory / "tmp"
    final = directory / "final"
    tmp.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    ts = ctfboard.now_iso()
    ev = tmp / f"platform_verdict_{cid}.txt"
    ev.write_text(f"challenge: {chal}\nverdict: ACCEPTED\nplatform: gzctf cid={cid}\n"
                  f"flag_sha256: {flag_hash}\ntime: {ts}\n", encoding="utf-8")
    (final / "flag.txt").write_text(
        f"{flag_text}\n\nsource: gzctf cid={cid} (platform ACCEPTED)\n"
        f"flag_sha256: {flag_hash}\ntime: {ts}\n", encoding="utf-8")
    (directory / "ACCEPTED.txt").write_text(
        f"ACCEPTED {chal}\nFLAG: {flag_text}\nplatform: gzctf cid={cid}\n"
        f"time: {ts}\nfinal/flag.txt: {final / 'flag.txt'}\n", encoding="utf-8")
    claim = f"{chal}: platform ACCEPTED (sha256 {flag_hash})"
    command = [sys.executable, str(board_script), "verify", "record",
               "--game", game, "--chal", chal, "--actor", "checker-platform",
               "--claim", claim, "--command", f"platform verdict gzctf cid={cid}",
               "--output", str(ev), "--exit", "0", "--artifact", str(ev),
               "--reproduced", "yes", "--verdict", "verified"]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=60, check=False)
    if proc.returncode != 0:
        print(f"WARN verify-record failed (exit {proc.returncode}); platform verdict above "
              "is authoritative", file=sys.stderr)
    print("=" * 62)
    print(f"  ACCEPTED  {chal}  (cid={cid})")
    print(f"  FLAG: {flag_text}")
    print(f"  written: {final / 'flag.txt'}")
    print("=" * 62)


def log_submission(directory: Path, game: str, chal: str, fact: Dict[str, Any],
                   flag_hash: str, verdict: str, cid: str,
                   evidence: Optional[str] = None) -> None:
    board_script = Path(__file__).resolve().with_name("ctfboard.py")
    command = [
        sys.executable,
        str(board_script),
        "submit-log",
        "--game",
        game,
        "--chal",
        chal,
        "--flag-hash",
        flag_hash,
        "--verdict",
        verdict,
        "--cid",
        str(cid),
        "--actor",
        "ctf-submit",
    ]
    if evidence:
        command += ["--evidence", evidence]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        check=False,
    )
    for line in (proc.stderr or "").splitlines():
        if line.strip():
            print(f"BOARD {ctfboard.sanitize_line(line, 500)}", file=sys.stderr)
    if proc.returncode == 0:
        for line in (proc.stdout or "").splitlines():
            if line.strip():
                print(f"BOARD {ctfboard.sanitize_line(line, 500)}")
    else:
        print(
            f"WARN submit-log failed (exit {proc.returncode}); platform verdict above "
            "is authoritative but the board attempt counter was not updated",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_submit(args: argparse.Namespace) -> int:
    if not args.game or not args.chal:
        raise ctfboard.CliError("submit mode requires --game and --chal")
    game = ctfboard.safe_component(args.game, "game")
    chal = ctfboard.safe_component(args.chal, "chal")
    directory = ctfboard.require_challenge(game, chal)
    if not args.cid:
        raise ctfboard.CliError("submit mode requires --cid <platform challenge id>")
    if bool(args.flag) == bool(args.flag_file):
        raise ctfboard.CliError("provide exactly one of --flag or --flag-file")

    auto = bool(args.auto)
    if auto:
        ev = Path(args.evidence).expanduser() if args.evidence else None
        if ev is None or not ev.is_file() or ev.stat().st_size == 0:
            raise ctfboard.CliError(
                "--auto requires --evidence <file> with the exact command/output that "
                "produced the flag (execution-confidence evidence)", code=3)
        fact: Dict[str, Any] = {"id": "execution-confidence", "evidence": str(ev)}
    else:
        if not args.verified_fact:
            raise ctfboard.CliError(
                "pass --verified-fact <id>, or --auto --evidence <file> for an "
                "execution-confidence submit (platform verdict is the verification)", code=3)
        fact = find_verified_fact(directory, args.verified_fact)
    state = ctfboard.load_state(directory)
    governor_precheck(state)

    # ---- flag handling: hash only, never persist or echo the raw flag ----
    if args.flag_file:
        flag_path = Path(args.flag_file).expanduser()
        if not flag_path.is_file():
            raise ctfboard.CliError(f"--flag-file does not exist: {flag_path}")
        try:
            raw = flag_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ctfboard.CliError(f"cannot read --flag-file {flag_path}: {exc}") from exc
        flag = raw.strip()
        if not flag:
            raise ctfboard.CliError(f"--flag-file is empty: {flag_path}")
        flag_hash = hashlib.sha256(flag.encode("utf-8", "surrogatepass")).hexdigest()
        submit_args = ["submit", str(args.cid), "--flag-file", str(flag_path)]
        redacted_args = ["submit", str(args.cid), "--flag-file", str(flag_path)]
    else:
        flag = args.flag
        if not flag:
            raise ctfboard.CliError("--flag must not be empty")
        flag_hash = hashlib.sha256(flag.encode("utf-8", "surrogatepass")).hexdigest()
        submit_args = ["submit", str(args.cid), "--flag", flag]
        redacted_args = ["submit", str(args.cid), "--flag", f"<redacted sha256={flag_hash}>"]
    flag_text = flag  # deliverable: written to final/flag.txt on acceptance
    del flag

    cfg = load_platform_config()
    cli = find_gzctf_cli()
    env = platform_env(cfg)
    timeout = float(cfg.get("submit_poll_seconds", 12) or 12) + float(cfg.get("timeout", 20) or 20) + 90

    # Idempotency: the same (challenge, answer) must not be sent twice.
    cid_key = str(args.cid)
    for rec in ctfboard.read_jsonl(ctfboard.submissions_path(directory)):
        if str(rec.get("flag_sha256")) == flag_hash and str(rec.get("cid")) == cid_key:
            previous = str(rec.get("verdict") or "pending").lower()
            if previous == "accepted":
                print(f"ALREADY ACCEPTED (recorded) cid={cid_key} sha256={flag_hash}; not resending")
                return 0
            raise ctfboard.CliError(
                f"duplicate submit refused: this exact answer for cid={cid_key} is already "
                f"{previous}; try a different candidate", code=3)

    if args.dry_run:
        dry_command = cli + redacted_args
        print(
            f"DRY-RUN cid={args.cid} fact={fact['id']} base_url={cfg['base_url']} "
            f"game={cfg['game_id']} flag_sha256={flag_hash} "
            f"command={_render(dry_command)}"
        )
        print("GATES verified-fact=ok governor=ok (no platform call made)")
        return 0

    proc = run_cli(cli + submit_args, env, timeout)
    verdict, status, submit_id, by_solved = classify(proc, env, cli, str(args.cid), timeout)
    _echo_platform(proc)
    status_line = ctfboard.sanitize_line(status, 120) or "-"

    if verdict == "auth":
        print(
            "PLATFORM-AUTH session is not logged in (HTTP 401); ctf-submit does not "
            "handle credentials. Fix: run `gzctf login -u <user>` in a terminal "
            "(password is entered interactively and stored only in ~/.gzctf/session.json), "
            "then re-run this command.",
            file=sys.stderr,
        )
        print(f"SUBMIT cid={args.cid} fact={fact['id']} verdict=auth status={status_line} "
              "http_200_is_not_accepted=yes")
        return 4

    if verdict == "error":
        hint = " (platform says this account has not joined the game)" if status == "NOT_PARTICIPATED" else ""
        print(
            f"ERROR platform did not return a verdict ({status_line}); no submit attempt "
            f"was logged{hint}. Check `gzctf doctor` and retry.",
            file=sys.stderr,
        )
        print(f"SUBMIT cid={args.cid} fact={fact['id']} verdict=error status={status_line} "
              "http_200_is_not_accepted=yes")
        return 5

    # Terminally classified -> consume one governor attempt on the board.
    log_submission(directory, game, chal, fact, flag_hash, verdict, str(args.cid),
                   evidence=(str(Path(args.evidence).expanduser()) if auto else None))
    print(
        f"SUBMIT cid={args.cid} fact={fact['id']} submit_id={submit_id} status={status_line} "
        f"verdict={verdict} accepted_by_solved_set={'yes' if by_solved else 'no'} "
        "http_200_is_not_accepted=yes"
    )
    if verdict == "accepted":
        record_platform_accept(directory, game, chal, str(args.cid), flag_text, flag_hash)
        return 0
    if verdict == "rejected":
        print("NOTE platform rejected the flag (attempt recorded); continue with a new candidate "
              "under the governor", file=sys.stderr)
        return 1
    print(
        "NOTE submission is not terminal yet; poll with `gzctf verify --prefix <P>` or "
        "`gzctf solved`, then log the final verdict with `ctfboard.py submit-log` "
        "only if a new submission was actually made",
        file=sys.stderr,
    )
    return 6


def run_verify(args: argparse.Namespace) -> int:
    cfg = load_platform_config()
    cli = find_gzctf_cli()
    env = platform_env(cfg)
    command = cli + ["verify", "--prefix", str(args.verify_prefix)]
    if args.dry_run:
        print(
            f"DRY-RUN mode=verify prefix={args.verify_prefix} base_url={cfg['base_url']} "
            f"game={cfg['game_id']} command={_render(command)}"
        )
        return 0
    proc = run_cli(command, env, float(cfg.get("timeout", 20) or 20) + 90)
    _echo_platform(proc)
    combined = _combined_output(proc)
    if _auth_failure(combined):
        print(
            "PLATFORM-AUTH session is not logged in (HTTP 401); run `gzctf login -u <user>`.",
            file=sys.stderr,
        )
        return 4
    if args.game and args.chal:
        try:
            directory = ctfboard.challenge_dir(args.game, args.chal)
            if (directory / "state.json").is_file():
                ctfboard.telemetry(
                    directory,
                    ctfboard.safe_component(args.game, "game"),
                    ctfboard.safe_component(args.chal, "chal"),
                    "verify",
                    "ctf-submit",
                    {
                        "mode": "verify-all",
                        "prefix": str(args.verify_prefix),
                        "exit": proc.returncode,
                    },
                )
        except ctfboard.CliError:
            pass
    print(f"VERIFY-ALL prefix={args.verify_prefix} exit={proc.returncode}")
    return 0 if proc.returncode == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctf-submit.py",
        description=(
            "Adapter over the global `gzctf` CLI. Two submission bases: (a) a verified fact, or "
            "(b) --auto --evidence execution-confidence submit whose verification IS the "
            "platform verdict. Checks the governor, treats HTTP 200 as NOT accepted, logs only "
            "the flag sha256, writes final/flag.txt + ACCEPTED.txt on acceptance, and never "
            "touches credentials."
        ),
        epilog=(
            "Exit codes: 0 accepted, 1 rejected, 2 usage/config, 3 gate refusal, "
            "4 platform auth (401 / logged out), 5 platform error, 6 pending. "
            "session.json is owned by gzctf and never read or printed by this script."
        ),
    )
    parser.add_argument("--game", default=None, help="game id (needed to find the board)")
    parser.add_argument("--chal", default=None, help="challenge id")
    parser.add_argument("--verified-fact", default=None, metavar="ID",
                        help="verified fact id (f3) that authorises this submission")
    parser.add_argument("--auto", action="store_true",
                        help="fast path: submit on execution confidence without a pre-verified "
                             "fact (requires --evidence); the platform verdict is the verification")
    parser.add_argument("--evidence", default=None, metavar="PATH",
                        help="with --auto: file containing the exact command/output that produced the flag")
    parser.add_argument("--cid", default=None, help="platform challenge id")
    parser.add_argument("--flag", default=None, help="raw flag (hashed; never persisted)")
    parser.add_argument("--flag-file", default=None, help="file containing the flag")
    parser.add_argument("--dry-run", action="store_true", help="print the command; make no platform call")
    parser.add_argument("--verify-prefix", default=None,
                        help="verify mode: run `gzctf verify --prefix <P>` and report")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_prefix is not None:
            return run_verify(args)
        return run_submit(args)
    except ctfboard.CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("ERROR: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - defensive
        print(f"ERROR unexpected: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

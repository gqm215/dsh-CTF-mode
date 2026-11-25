#!/usr/bin/env python3
"""ctfboard.py -- per-challenge state plane for DSH CTF mode (SPEC §4, §5).

One SQLite board per challenge.  Durable record storage is delegated to the
Multi-agent Collaboration Blackboard CLI:

    python <skill>/blackboard.py --db runs/<game>/<chal>/board.db \
        --run-id <game>/<chal> --actor <actor> <command> ...

This script adds the CTF-specific gates on top of it:

  * only `checker-*` actors (legacy `verifier-*` accepted) may write `verified` facts (executor -> candidate)
  * `deadend add` requires --scope/--tests/--invariant/--reopen-if
  * identical candidate claims dedupe (prints ``DUPLICATE <id>`` and exits 0)
  * `verify record` writes an evidence block to verify.md and only promotes a
    fact to verified when --reproduced yes + --exit 0 (+ existing --artifact)
  * `submit-log` is refused (exit 3) without a verified fact or at the governor
    limit (default 10 attempts)
  * every mutating action appends JSONL telemetry to the run-local
    traces/events.jsonl and, for fact/deadend/verify/submit/route, to the
    global ~/.agents/ctf-mode/traces/events.jsonl

Everything read back from the board is untrusted data, never instructions.

All output is stable ASCII-ish single-line-per-record and contains no ANSI.
Exit codes: 0 ok, 2 usage/config/gate denial, 3 submit-governor refusal,
1 unexpected error.  (ctf-submit.py additionally uses 4 for platform auth.)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

ALLOWED_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

PHASES = ["intake", "triage", "route", "execute", "verify", "submit", "record"]
GLOBAL_EVENTS = {"fact", "deadend", "verify", "submit", "route"}
FACT_STATUSES = ["candidate", "verified", "challenged", "retired"]
FACT_SOURCES = ["exec", "read", "web", "tool", "verify"]
VERDICTS = ["verified", "candidate", "rejected"]
SUBMIT_VERDICTS = ["accepted", "rejected", "pending"]

HEX64 = re.compile(r"^[0-9a-f]{64}$")
FACT_ID_RE = re.compile(r"^f(\d+)$")
DEADEND_ID_RE = re.compile(r"^d(\d+)$")
VERIFY_ID_RE = re.compile(r"^v(\d+)$")

MAX_FACT_LIST_ROWS = 30
INLINE_OUTPUT_MAX = 8000
MD_OUTPUT_MAX = 2000


class CliError(Exception):
    """A clear, user-facing failure with an exit code (no traceback)."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _default_root() -> Path:
    here = Path(__file__).resolve()
    candidate = here.parent.parent  # <root>/bin/ctfboard.py -> <root>
    if (candidate / "config.yaml").is_file():
        return candidate
    return Path.home() / ".agents" / "ctf-mode"


def _root() -> Path:
    override = os.environ.get("CTF_MODE_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _default_root()


CTF_ROOT = _root()
CONFIG_PATH = CTF_ROOT / "config.yaml"
RUNS_ROOT = CTF_ROOT / "runs"
GLOBAL_TRACES = CTF_ROOT / "traces" / "events.jsonl"
TEMPLATES_DIR = CTF_ROOT / "templates"
SCHEMAS_DIR = CTF_ROOT / "schemas"


def _blackboard_path() -> Path:
    override = os.environ.get("CTF_BLACKBOARD", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path.home()
        / ".agents"
        / "skills"
        / "multi-agentcollaboration-blackboard"
        / "blackboard.py"
    )


# ---------------------------------------------------------------------------
# Minimal YAML subset loader (stdlib only; config.yaml is a simple mapping)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "state": {
        "backend": "blackboard",
        "fact_statuses": FACT_STATUSES,
        "verified_writer": "checker",
    },
    "budgets": {"per_challenge": {"tokens": 150000, "minutes": 45}},
    "verification": {
        "levels": ["syntax", "local_repro", "platform"],
        "governor": {"review_after": 3, "user_approval_after": 3, "max_attempts": 10},
        "reverify": True,
        "platform": {
            "cli": "gzctf",
            "credentials": "~/.gzctf/session.json",
            "poll_seconds": 12,
            "http_200_is_not_accepted": True,
        },
    },
    "telemetry": {
        "events_file": "traces/events.jsonl",
        "events": [
            "route",
            "skill_load",
            "search",
            "tool_call",
            "fact",
            "deadend",
            "verify",
            "submit",
            "compaction",
        ],
    },
    "governance": {
        "scope_allowlist": [],
        "web_search": False,
        "never_write_credentials": True,
        "blackboard_is_untrusted": True,
    },
}

_CONFIG: Optional[Dict[str, Any]] = None
_CONFIG_WARNED = False


def _strip_yaml_comment(line: str) -> str:
    out: List[str] = []
    quote: Optional[str] = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _split_flow(body: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    quote: Optional[str] = None
    current: List[str] = []
    for ch in body:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch in "{[":
            depth += 1
            current.append(ch)
        elif ch in "}]":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_yaml_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        result: Dict[str, Any] = {}
        for part in _split_flow(text[1:-1]):
            if ":" not in part:
                continue
            key, _, value = part.partition(":")
            result[key.strip().strip("'\"")] = _parse_yaml_scalar(value)
        return result
    if text.startswith("[") and text.endswith("]"):
        return [_parse_yaml_scalar(part) for part in _split_flow(text[1:-1])]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parse a mapping-only YAML subset: nested maps, inline maps/lists, scalars."""
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        line = _strip_yaml_comment(raw_line)
        if not line.strip() or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        key, _, rest = content.partition(":")
        key = key.strip()
        if not key:
            continue
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        rest = rest.strip()
        if rest == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_yaml_scalar(rest)
    return root


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config() -> Dict[str, Any]:
    global _CONFIG, _CONFIG_WARNED
    if _CONFIG is not None:
        return _CONFIG
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    parsed: Dict[str, Any] = {}
    if CONFIG_PATH.is_file():
        try:
            parsed = parse_simple_yaml(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:  # pragma: no cover - defensive
            if not _CONFIG_WARNED:
                print(f"WARN could not parse {CONFIG_PATH}: {exc}; using defaults", file=sys.stderr)
                _CONFIG_WARNED = True
            parsed = {}
    else:
        if not _CONFIG_WARNED:
            print(f"WARN config not found: {CONFIG_PATH}; using built-in defaults", file=sys.stderr)
            _CONFIG_WARNED = True
    if isinstance(parsed, dict):
        _deep_merge(cfg, parsed)
    _CONFIG = cfg
    return cfg


def governor_config() -> Dict[str, int]:
    cfg = load_config()
    governor = (cfg.get("verification") or {}).get("governor") or {}
    review_after = int(governor.get("review_after", 3) or 3)
    approval_after = int(governor.get("user_approval_after", review_after) or review_after)
    max_attempts = int(governor.get("max_attempts", 10) or 10)
    return {
        "review_after": review_after,
        "user_approval_after": approval_after,
        "max_attempts": max_attempts,
    }


def verified_writer_prefix() -> str:
    """Canonical actor prefix for evidence-writers (role: 复核员 / Re-checker)."""
    state = load_config().get("state") or {}
    return str(state.get("verified_writer") or "checker")


LEGACY_WRITER_PREFIXES = ("checker", "verifier")


def is_verifier(actor: str) -> bool:
    """True for a canonical `checker-*` actor or a legacy `verifier-*` actor.

    The role was renamed from Verifier to Re-checker (checker-*) when flag
    correctness moved to the platform verdict; legacy facts/logs keep working.
    """
    a = str(actor or "").lower()
    return any(a.startswith(p) for p in LEGACY_WRITER_PREFIXES)


# ---------------------------------------------------------------------------
# Small text / time / hash helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize_line(value: Any, max_chars: int = 4000) -> str:
    """Flatten untrusted text to one inert line (no ANSI, no control chars)."""
    text = ANSI_RE.sub("", str(value if value is not None else ""))
    text = CONTROL_RE.sub(" ", text)
    text = " ".join(text.split())
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def sanitize_block(value: Any, max_chars: int = INLINE_OUTPUT_MAX) -> str:
    """Keep line breaks/tabs, strip ANSI and control chars, bound the length."""
    text = ANSI_RE.sub("", str(value if value is not None else ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_RE.sub("", text.replace("\t", "    "))
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 4] + "\n..."
    return text


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_claim(text: str) -> str:
    """Match blackboard.py fact identity: strip one engine tag, fold, lower."""
    value = re.sub(r"^\[[a-z0-9 _.-]{1,40}\]\s*", "", text or "", flags=re.IGNORECASE)
    return " ".join(value.split()).strip().lower()


def phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _component(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise CliError(f"--{label} must not be empty")
    if not ALLOWED_COMPONENT.match(value):
        raise CliError(
            f"--{label} {value!r} is not a safe path component "
            "(letters, digits, dot, dash, underscore; must start alphanumeric)"
        )
    return value


def challenge_dir(game: str, chal: str) -> Path:
    return RUNS_ROOT / _component(game, "game") / _component(chal, "chal")


# Public alias: other CTF-mode tools (ctf-submit.py, skill code) use this.
safe_component = _component


def run_id(game: str, chal: str) -> str:
    return f"{_component(game, 'game')}/{_component(chal, 'chal')}"


def require_challenge(game: str, chal: str) -> Path:
    directory = challenge_dir(game, chal)
    if not (directory / "state.json").is_file() or not (directory / "board.db").is_file():
        raise CliError(
            f"challenge not initialized: {directory}\n"
            f"  run: python {Path(__file__).name} init --game {game} --chal {chal}"
        )
    return directory


# ---------------------------------------------------------------------------
# JSON / JSONL storage helpers
# ---------------------------------------------------------------------------


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc
    return records


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        raise CliError(f"cannot append {path}: {exc}") from exc


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp_name, path)
    except OSError as exc:
        raise CliError(f"cannot write {path}: {exc}") from exc


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except OSError as exc:
        raise CliError(f"cannot write {path}: {exc}") from exc


def facts_path(directory: Path) -> Path:
    return directory / "facts.jsonl"


def deadends_path(directory: Path) -> Path:
    return directory / "deadends.jsonl"


def verifies_path(directory: Path) -> Path:
    return directory / "verifies.jsonl"


def submissions_path(directory: Path) -> Path:
    return directory / "submissions.jsonl"


def state_path(directory: Path) -> Path:
    return directory / "state.json"


def load_state(directory: Path) -> Dict[str, Any]:
    path = state_path(directory)
    if not path.is_file():
        raise CliError(f"state.json missing in {directory}; run init first")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CliError(f"{path} is not a JSON object")
    return value


def save_state(directory: Path, state: Dict[str, Any]) -> None:
    state["updated"] = now_iso()
    write_json_atomic(state_path(directory), state)


def default_state(game: str, chal: str, title: str, category: str) -> Dict[str, Any]:
    cfg = load_config()
    budget = ((cfg.get("budgets") or {}).get("per_challenge") or {})
    stamp = now_iso()
    return {
        "challenge_id": f"{_component(game, 'game')}/{_component(chal, 'chal')}",
        "game": _component(game, "game"),
        "title": title or "",
        "category": category or "",
        "phase": "intake",
        "budget": {
            "tokens": int(budget.get("tokens", 150000) or 150000),
            "minutes": int(budget.get("minutes", 45) or 45),
        },
        "spent": {"tokens": 0, "minutes": 0},
        "attempts": 0,
        "created": stamp,
        "updated": stamp,
    }


def bump_phase(state: Dict[str, Any], target: str) -> None:
    if phase_index(target) > phase_index(str(state.get("phase", "intake"))):
        state["phase"] = target


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def telemetry(
    directory: Path,
    game: str,
    chal: str,
    event: str,
    actor: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    record = {
        "ts": now_iso(),
        "event": str(event),
        "game": game,
        "chal": chal,
        "actor": str(actor or ""),
        "data": data or {},
    }
    append_jsonl(directory / "traces" / "events.jsonl", record)
    if event in GLOBAL_EVENTS:
        append_jsonl(GLOBAL_TRACES, record)


# ---------------------------------------------------------------------------
# Minimal JSON-Schema (draft-07 subset) validation for records we write
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def load_schema(name: str) -> Optional[Dict[str, Any]]:
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    path = SCHEMAS_DIR / name
    schema: Optional[Dict[str, Any]] = None
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                schema = value
        except (OSError, ValueError):
            schema = None
    _SCHEMA_CACHE[name] = schema
    return schema


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return True


def _validate_value(value: Any, schema: Any, path: str, errors: List[str]) -> None:
    if not isinstance(schema, dict):
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']!r}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    expected = schema.get("type")
    if expected is not None:
        kinds = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, kind) for kind in kinds):
            errors.append(f"{path}: expected type {expected!r}, got {type(value).__name__}")
            return
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    elif isinstance(value, dict):
        for required in schema.get("required", []) or []:
            if required not in value:
                errors.append(f"{path}: missing required property {required!r}")
        properties = schema.get("properties") or {}
        for key, item in value.items():
            if key in properties:
                _validate_value(item, properties[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: more than maxItems {schema['maxItems']}")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_value(item, schema["items"], f"{path}[{index}]", errors)


def validate_record(record: Dict[str, Any], schema_name: str) -> None:
    schema = load_schema(schema_name)
    if schema is None:
        print(f"WARN schema not found: {SCHEMAS_DIR / schema_name}; record not validated", file=sys.stderr)
        return
    errors: List[str] = []
    _validate_value(record, schema, schema_name, errors)
    if errors:
        raise CliError("record violates " + schema_name + ": " + "; ".join(errors[:5]))


# ---------------------------------------------------------------------------
# Board creation (schema compatible with multi-agentcollaboration-blackboard)
# ---------------------------------------------------------------------------

BOARD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    challenge_id TEXT,
    actor TEXT,
    kind TEXT NOT NULL,
    payload TEXT,
    artifact_id TEXT,
    verified INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    dedupe_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    challenge_id TEXT,
    goal TEXT NOT NULL,
    worker TEXT,
    status TEXT NOT NULL,
    lease_until REAL,
    created_seq INTEGER,
    dispatch_state TEXT DEFAULT 'active',
    worker_class TEXT,
    route_hash TEXT,
    branch_id TEXT,
    close_reason TEXT,
    result_seq INTEGER,
    result_detail TEXT,
    to_fact_seq INTEGER
);
CREATE TABLE IF NOT EXISTS fact_states (
    fact_seq INTEGER PRIMARY KEY,
    challenge_id TEXT,
    state TEXT,
    verified_effective INTEGER,
    confidence_effective REAL,
    retired_seq INTEGER
);
CREATE TABLE IF NOT EXISTS fact_reviews (
    fact_seq INTEGER PRIMARY KEY,
    challenge_id TEXT,
    status TEXT,
    reason TEXT,
    verification_intent_id TEXT,
    challenged_seq INTEGER
);
CREATE TABLE IF NOT EXISTS routes (
    route_hash TEXT PRIMARY KEY,
    challenge_id TEXT,
    label TEXT,
    status TEXT,
    reason TEXT,
    until_policy TEXT,
    suppressed_seq INTEGER,
    reopened_seq INTEGER
);
CREATE TABLE IF NOT EXISTS branches (
    branch_id TEXT PRIMARY KEY,
    challenge_id TEXT,
    parent_id TEXT,
    title TEXT,
    assumption TEXT,
    prove_or_disprove TEXT,
    status TEXT,
    created_seq INTEGER
);
CREATE TABLE IF NOT EXISTS intent_products (
    intent_id TEXT NOT NULL,
    fact_seq INTEGER NOT NULL,
    PRIMARY KEY (intent_id, fact_seq)
);
CREATE TABLE IF NOT EXISTS operator_directives (
    directive_id TEXT PRIMARY KEY,
    challenge_id TEXT,
    action TEXT,
    text TEXT,
    status TEXT,
    priority INTEGER,
    received_seq INTEGER,
    bound_worker TEXT
);
CREATE TABLE IF NOT EXISTS board_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS activity_locks (
    activity_key TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL,
    worker TEXT NOT NULL,
    lease_until REAL NOT NULL,
    claimed_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_locks (
    lock_id TEXT PRIMARY KEY,
    challenge_id TEXT,
    resource_key TEXT,
    scope TEXT,
    risk_class TEXT,
    status TEXT,
    owner_worker TEXT,
    owner_intent TEXT,
    lease_until REAL,
    created_seq INTEGER,
    released_seq INTEGER,
    conflict_policy TEXT,
    cooldown_s REAL
);
"""


def ensure_board(db: Path, run: str) -> bool:
    """Create the board DB if absent; returns True when newly created."""
    created = not db.is_file()
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db), timeout=10, isolation_level=None)
    except (OSError, sqlite3.Error) as exc:
        raise CliError(f"cannot open board DB {db}: {exc}") from exc
    try:
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        if created:
            connection.executescript(BOARD_SCHEMA_SQL)
            connection.execute(
                "INSERT INTO events (ts,challenge_id,actor,kind,payload,verified,confidence) "
                "VALUES (?,?,?,?,?,0,1.0)",
                (time.time(), run, "coordinator", "challenge_started", "{}"),
            )
            connection.execute(
                "INSERT OR REPLACE INTO board_meta (key,value) VALUES ('default_challenge_id',?)",
                (run,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO board_meta (key,value) VALUES ('ctf_mode_schema','1')",
                (),
            )
        else:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            if row is None:
                raise CliError(
                    f"board DB exists but has no events table: {db} "
                    "(delete it or point --chal at a fresh challenge)"
                )
        connection.commit()
    except sqlite3.Error as exc:
        raise CliError(f"cannot initialise board DB {db}: {exc}") from exc
    finally:
        connection.close()
    return created


# ---------------------------------------------------------------------------
# Blackboard delegation
# ---------------------------------------------------------------------------


def call_blackboard(directory: Path, game: str, chal: str, actor: str, args: List[str]) -> str:
    """Run blackboard.py with explicit DB/run/actor; return its stdout text."""
    script = _blackboard_path()
    if not script.is_file():
        raise CliError(
            f"blackboard.py not found: {script} (the CTF state plane delegates record storage to it)"
        )
    command = [
        sys.executable,
        str(script),
        "--db",
        str(directory / "board.db"),
        "--run-id",
        run_id(game, chal),
        "--actor",
        str(actor or "executor"),
    ] + list(args)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("MULTI_AGENT_COLLABORATION_") or key.startswith("INFINITEX_"):
            env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
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
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliError(f"blackboard.py invocation failed: {exc}") from exc
    if proc.returncode != 0:
        detail = sanitize_line(proc.stderr or proc.stdout or "no output", 500)
        raise CliError(f"blackboard.py <{args[0]}> failed (exit {proc.returncode}): {detail}")
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            print(f"BOARD {sanitize_line(line, 800)}", file=sys.stderr)
    return proc.stdout


def board_fact_text(claim: str, evidence: str) -> str:
    """One actionable board fact; keeps the claim readable by other workers."""
    text = (
        f"[ctf] {sanitize_line(claim, 500)}"
        f" :: evidence: {sanitize_line(evidence, 500)}"
    )
    return sanitize_line(text, 1200)


# ---------------------------------------------------------------------------
# ID allocation
# ---------------------------------------------------------------------------


def _next_id(records: List[Dict[str, Any]], pattern: re.Pattern[str], prefix: str) -> str:
    highest = 0
    for record in records:
        match = pattern.match(str(record.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    directory = challenge_dir(game, chal)
    run = run_id(game, chal)

    for sub in ("traces", "tmp", "draft", "final", "artifacts"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    ensure_board(directory / "board.db", run)

    # verify.md from the kernel template (idempotent: never overwrite evidence)
    verify_md = directory / "verify.md"
    if not verify_md.is_file():
        template = TEMPLATES_DIR / "verify.md.template"
        if template.is_file():
            body = template.read_text(encoding="utf-8")
            replacements = {
                "{{game}}": game,
                "{{chal}}": chal,
                "{{title}}": sanitize_line(args.title or "", 200),
                "{{category}}": sanitize_line(args.category or "", 60),
                "{{created}}": now_iso(),
                "{{run_id}}": run,
            }
            for key, value in replacements.items():
                body = body.replace(key, value)
        else:  # pragma: no cover - template is a deliverable
            body = (
                f"# Verify - {run}\n\n"
                "No fresh evidence, no claim. Only checker-* (legacy verifier-*) writes verified.\n"
            )
        verify_md.write_text(body, encoding="utf-8", newline="\n")

    # run-local telemetry file must exist even before the first event
    (directory / "traces" / "events.jsonl").touch(exist_ok=True)
    GLOBAL_TRACES.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_TRACES.touch(exist_ok=True)

    state = load_state(directory) if state_path(directory).is_file() else None
    if state is None:
        state = default_state(game, chal, args.title or "", args.category or "")
    else:
        if args.title:
            state["title"] = sanitize_line(args.title, 200)
        if args.category:
            state["category"] = sanitize_line(args.category, 60)
        state.setdefault("spent", {"tokens": 0, "minutes": 0})
        state.setdefault("attempts", 0)
        state.setdefault("phase", "intake")
        state.setdefault("budget", default_state(game, chal, "", "")["budget"])
    save_state(directory, state)

    print(f"INIT {run} dir={directory}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    print(str(challenge_dir(args.game, args.chal)))
    return 0


def _find_fact_by_claim(facts: List[Dict[str, Any]], claim: str) -> Optional[Dict[str, Any]]:
    target = normalize_claim(claim)
    for record in facts:
        if normalize_claim(str(record.get("claim", ""))) == target:
            return record
    return None


def _update_fact(directory: Path, fact_id: str, **updates: Any) -> Dict[str, Any]:
    facts = read_jsonl(facts_path(directory))
    updated: Optional[Dict[str, Any]] = None
    for record in facts:
        if str(record.get("id")) == fact_id:
            record.update(updates)
            updated = record
            break
    if updated is None:
        raise CliError(f"fact {fact_id} not found in {facts_path(directory)}")
    write_jsonl(facts_path(directory), facts)
    return updated


def _make_fact_record(
    fact_id: str,
    claim: str,
    evidence: str,
    status: str,
    source: str,
    actor: str,
    artifact: Optional[str],
) -> Dict[str, Any]:
    record = {
        "id": fact_id,
        "claim": sanitize_line(claim, 2000),
        "evidence": sanitize_block(evidence, 2000),
        "status": status,
        "source": source,
        "actor": sanitize_line(actor, 120),
        "ts": now_iso(),
        "artifact": artifact,
    }
    validate_record(record, "fact.schema.json")
    return record


def cmd_fact_add(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    actor = (args.actor or "executor").strip()
    claim = (args.claim or "").strip()
    evidence = (args.evidence or "").strip()
    status = args.status or "candidate"
    if not claim:
        raise CliError("--claim must not be empty")
    if not evidence:
        raise CliError("--evidence must not be empty (candidate facts still need provenance)")

    if status == "verified" and not is_verifier(actor):
        raise CliError(
            f"DENIED: actor {actor!r} may not write verified facts; only actors starting "
            f"with {verified_writer_prefix()!r} can. Executor writes candidate only. "
            "Use: ctfboard.py verify record --verdict verified --reproduced yes --exit 0 "
            "--actor checker-<name> (legacy verifier- accepted)"
        )

    facts = read_jsonl(facts_path(directory))
    existing = _find_fact_by_claim(facts, claim)
    if existing is not None:
        print(f"DUPLICATE {existing['id']}")
        return 0

    artifact = args.artifact or None
    if artifact:
        candidate_path = Path(artifact).expanduser()
        if not candidate_path.is_absolute() and not candidate_path.is_file():
            local = directory / candidate_path
            if local.is_file():
                candidate_path = local
        artifact = str(candidate_path.resolve()) if candidate_path.is_file() else artifact

    fact = _make_fact_record(
        _next_id(facts, FACT_ID_RE, "f"),
        claim,
        evidence,
        status,
        args.source or "exec",
        actor,
        artifact,
    )

    board_args = ["write-fact", board_fact_text(claim, evidence)]
    if status == "verified":
        board_args.append("--verified")
    call_blackboard(directory, game, chal, actor, board_args)

    append_jsonl(facts_path(directory), fact)
    telemetry(
        directory,
        game,
        chal,
        "fact",
        actor,
        {
            "fact_id": fact["id"],
            "status": status,
            "source": fact["source"],
            "claim": fact["claim"],
            "artifact": artifact,
        },
    )

    state = load_state(directory)
    bump_phase(state, "verify" if status == "verified" else "execute")
    save_state(directory, state)

    suffix = f" artifact={sanitize_line(artifact, 200)}" if artifact else ""
    print(f"FACT {fact['id']} {status} actor={actor}{suffix}")
    return 0


def cmd_fact_list(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    facts = read_jsonl(facts_path(directory))
    selected: List[Dict[str, Any]] = []
    for record in facts:
        status = str(record.get("status", "candidate"))
        if args.status:
            if status == args.status:
                selected.append(record)
        elif args.all:
            selected.append(record)
        elif status != "retired":
            selected.append(record)
    if len(selected) > MAX_FACT_LIST_ROWS:
        selected = selected[-MAX_FACT_LIST_ROWS:]
    if not selected:
        print("# no facts")
        return 0
    print("# id status source actor ts claim")
    for record in selected:
        print(
            " ".join(
                [
                    str(record.get("id", "?")),
                    str(record.get("status", "?")),
                    sanitize_line(record.get("source", "-"), 20),
                    sanitize_line(record.get("actor", "-"), 40),
                    sanitize_line(record.get("ts", "-"), 40),
                    sanitize_line(record.get("claim", "-"), 160),
                ]
            )
        )
    return 0


def cmd_deadend_add(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    actor = (args.actor or "executor").strip()
    scope = (args.scope or "").strip()
    tests = (args.tests or "").strip()
    invariant = (args.invariant or "").strip()
    reopen_if = (args.reopen_if or "").strip()
    missing = [
        flag
        for flag, value in (
            ("--scope", scope),
            ("--tests", tests),
            ("--invariant", invariant),
            ("--reopen-if", reopen_if),
        )
        if not value
    ]
    if missing:
        raise CliError(
            "deadend add requires all four fields: " + ", ".join(missing) +
            " (format: <scope>; <tests>; <invariant>; reopen if <condition>)"
        )

    deadends = read_jsonl(deadends_path(directory))
    normalized_scope = normalize_claim(scope)
    for record in deadends:
        if normalize_claim(str(record.get("scope", ""))) == normalized_scope:
            print(f"DUPLICATE {record['id']}")
            return 0

    reason = f"{scope}; {tests}; {invariant}; reopen if {reopen_if}"
    call_blackboard(directory, game, chal, actor, ["mark-deadend", reason])

    record = {
        "id": _next_id(deadends, DEADEND_ID_RE, "d"),
        "scope": sanitize_line(scope, 500),
        "tests": sanitize_line(tests, 500),
        "invariant": sanitize_line(invariant, 500),
        "reopen_if": sanitize_line(reopen_if, 500),
        "actor": sanitize_line(actor, 120),
        "ts": now_iso(),
    }
    append_jsonl(deadends_path(directory), record)
    telemetry(
        directory,
        game,
        chal,
        "deadend",
        actor,
        {"deadend_id": record["id"], "scope": record["scope"], "reopen_if": record["reopen_if"]},
    )

    state = load_state(directory)
    bump_phase(state, "execute")
    save_state(directory, state)

    print(f"DEADEND {record['id']} scope={record['scope']}")
    return 0


def _initial_verdict(args: argparse.Namespace, artifact_exists: bool) -> Tuple[str, List[str]]:
    """Return (requested verdict, reasons it must be downgraded from verified)."""
    requested = args.verdict or "candidate"
    reasons: List[str] = []
    if requested == "verified":
        if (args.reproduced or "no") != "yes":
            reasons.append(f"--reproduced is {args.reproduced or 'unset'} (verified requires --reproduced yes)")
        if int(args.exit_code) != 0:
            reasons.append(f"--exit is {args.exit_code} (verified requires --exit 0)")
        if args.artifact and not artifact_exists:
            reasons.append(f"--artifact does not exist: {args.artifact}")
    return requested, reasons


def _format_verify_block(
    vid: str,
    claim: str,
    command: str,
    output_kind: str,
    output_body: str,
    exit_code: int,
    artifact_line: str,
    reproduced: str,
    actor: str,
    timestamp: str,
    verdict: str,
) -> str:
    lines = [
        "",
        "## Claim",
        sanitize_line(claim, 2000),
        "",
        "## Evidence",
        f"- command: `{sanitize_line(command, 1200).replace('`', '')}`",
    ]
    if output_kind == "file":
        lines.append(f"- output: `{sanitize_line(output_body, 240).replace('`', '')}`")
    else:
        lines.append("- output: inline (see below)")
    lines.extend(
        [
            f"- exit: {int(exit_code)}",
            f"- artifact: {artifact_line}",
            f"- reproduced: {reproduced}",
            f"- timestamp: {timestamp}",
            f"- actor: {sanitize_line(actor, 120)}",
            f"- verify_id: {vid}",
            "",
        ]
    )
    if output_kind != "file":
        body = sanitize_block(output_body, MD_OUTPUT_MAX).replace("```", "'''")
        lines.extend(["### Output", "```text", body, "```", ""])
    lines.extend(["## Verdict", verdict, ""])
    return "\n".join(lines)


def cmd_verify_record(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    actor = (args.actor or "executor").strip()
    claim = (args.claim or "").strip()
    command = (args.command or "").strip()
    if not claim:
        raise CliError("--claim must not be empty")
    if not command:
        raise CliError("--command must not be empty")

    # --- output (inline text or path to a file) --------------------------
    raw_output = args.output if args.output is not None else ""
    output_path: Optional[Path] = None
    if "\n" not in raw_output:
        candidate = Path(raw_output).expanduser()
        if not candidate.is_absolute() and not candidate.is_file():
            local = directory / candidate
            if local.is_file():
                candidate = local
        if candidate.is_file():
            output_path = candidate.resolve()
    if output_path is not None:
        output_value = str(output_path)
        output_sha: Optional[str] = sha256_file(output_path)
        output_kind = "file"
        output_body = output_value
    else:
        output_value = sanitize_block(raw_output, INLINE_OUTPUT_MAX)
        output_sha = None
        output_kind = "inline"
        output_body = output_value

    # --- artifact --------------------------------------------------------
    artifact_sha: Optional[str] = None
    artifact_path: Optional[Path] = None
    if args.artifact:
        candidate = Path(args.artifact).expanduser()
        if not candidate.is_absolute() and not candidate.is_file():
            local = directory / candidate
            if local.is_file():
                candidate = local
        if candidate.is_file():
            artifact_path = candidate.resolve()
            artifact_sha = sha256_file(artifact_path)
            artifact_line = f"`{sanitize_line(artifact_path, 240).replace('`', '')}` sha256: {artifact_sha}"
        else:
            artifact_line = f"`{sanitize_line(args.artifact, 240).replace('`', '')}` (missing)"
    else:
        artifact_line = "-"

    # --- verdict gate: evidence first, then actor authority --------------
    requested, downgrade_reasons = _initial_verdict(args, artifact_path is not None)
    if requested == "verified" and not downgrade_reasons and not is_verifier(actor):
        raise CliError(
            f"DENIED: verdict=verified requires an actor starting with "
            f"{verified_writer_prefix()!r} (got {actor!r}); executor may only record "
            "candidate/rejected"
        )
    verdict = "candidate" if downgrade_reasons else requested
    if downgrade_reasons:
        print(
            "WARN verdict=verified downgraded to candidate: " + "; ".join(downgrade_reasons),
            file=sys.stderr,
        )

    timestamp = now_iso()
    verifies = read_jsonl(verifies_path(directory))
    # verify records deliberately match verify.schema.json, which has no id
    # field; the id is the 1-based position of the evidence block.
    vid = f"v{len(verifies) + 1}"

    verify_record = {
        "claim": sanitize_line(claim, 2000),
        "command": sanitize_line(command, 1200),
        "output": output_value,
        "exit": int(args.exit_code),
        "artifact_sha256": artifact_sha,
        "reproduced": "yes" if (args.reproduced or "no") == "yes" else "no",
        "verdict": verdict,
        "actor": sanitize_line(actor, 120),
        "ts": timestamp,
    }
    validate_record(verify_record, "verify.schema.json")

    # --- evidence block --------------------------------------------------
    block = _format_verify_block(
        vid,
        claim,
        command,
        output_kind,
        output_body,
        int(args.exit_code),
        artifact_line,
        verify_record["reproduced"],
        actor,
        timestamp,
        verdict,
    )
    verify_md = directory / "verify.md"
    try:
        verify_md.parent.mkdir(parents=True, exist_ok=True)
        with open(verify_md, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(block)
    except OSError as exc:
        raise CliError(f"cannot append {verify_md}: {exc}") from exc

    append_jsonl(verifies_path(directory), verify_record)

    # --- fact promotion / downgrade -------------------------------------
    facts = read_jsonl(facts_path(directory))
    existing = _find_fact_by_claim(facts, claim)
    fact_id = "-"
    extra_flags: List[str] = []
    if verdict == "verified":
        evidence_note = (
            f"verified {timestamp} via `{sanitize_line(command, 300)}` "
            f"(exit 0, reproduced yes, artifact_sha256={artifact_sha or '-'})"
        )
        if existing is not None:
            fact_id = str(existing["id"])
            promoted = str(existing.get("status")) != "verified"
            evidence = str(existing.get("evidence") or "").strip()
            new_evidence = (evidence + " | " + evidence_note) if evidence else evidence_note
            artifact_value = existing.get("artifact")
            if not artifact_value and artifact_path:
                artifact_value = str(artifact_path)
            _update_fact(
                directory,
                fact_id,
                status="verified",
                source="verify",
                actor=sanitize_line(actor, 120),
                evidence=sanitize_block(new_evidence, 2000),
                artifact=artifact_value,
            )
            if promoted:
                extra_flags.append("promoted=yes")
        else:
            fact = _make_fact_record(
                _next_id(facts, FACT_ID_RE, "f"),
                claim,
                evidence_note,
                "verified",
                "verify",
                actor,
                str(artifact_path) if artifact_path else None,
            )
            validate_record(fact, "fact.schema.json")
            append_jsonl(facts_path(directory), fact)
            fact_id = fact["id"]
        call_blackboard(
            directory,
            game,
            chal,
            actor,
            [
                "write-fact",
                board_fact_text(
                    claim,
                    f"verify={vid} verdict=verified cmd={command} exit=0 "
                    f"reproduced=yes artifact_sha256={artifact_sha or '-'}",
                ),
                "--verified",
            ],
        )
    elif verdict == "candidate":
        if existing is None:
            fact = _make_fact_record(
                _next_id(facts, FACT_ID_RE, "f"),
                claim,
                f"verification candidate {timestamp}: {sanitize_line(command, 300)} "
                f"exit={args.exit_code} reproduced={verify_record['reproduced']}",
                "candidate",
                "verify",
                actor,
                str(artifact_path) if artifact_path else None,
            )
            validate_record(fact, "fact.schema.json")
            append_jsonl(facts_path(directory), fact)
            fact_id = fact["id"]
        else:
            fact_id = str(existing["id"])
    else:  # rejected
        if existing is not None:
            fact_id = str(existing["id"])
            new_status = "challenged" if str(existing.get("status")) == "verified" else "retired"
            _update_fact(directory, fact_id, status=new_status)
            if new_status == "challenged":
                print(
                    f"WARN rejected verdict challenges previously verified fact {fact_id}; "
                    "dependent work must stop until re-verified",
                    file=sys.stderr,
                )
            extra_flags.append("challenged=yes" if new_status == "challenged" else "retired=yes")

    telemetry(
        directory,
        game,
        chal,
        "verify",
        actor,
        {
            "verify_id": vid,
            "verdict": verdict,
            "fact_id": fact_id,
            "command": sanitize_line(command, 400),
            "exit": int(args.exit_code),
            "reproduced": verify_record["reproduced"],
            "artifact_sha256": artifact_sha,
            "output_sha256": output_sha,
            "downgraded": bool(downgrade_reasons),
        },
    )

    state = load_state(directory)
    if verdict == "verified":
        bump_phase(state, "verify")
    elif phase_index(str(state.get("phase", "intake"))) < phase_index("execute"):
        bump_phase(state, "execute")
    save_state(directory, state)

    flags = " ".join(extra_flags)
    suffix = f" {flags}" if flags else ""
    print(f"VERIFY {vid} verdict={verdict} fact={fact_id}{suffix}")
    return 0


def cmd_submit_log(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    actor = (args.actor or "executor").strip()
    governor = governor_config()
    state = load_state(directory)

    verified = [f for f in read_jsonl(facts_path(directory)) if str(f.get("status")) == "verified"]
    evidence_path = (getattr(args, "evidence", "") or "").strip()
    fast_path = bool(evidence_path)
    if fast_path:
        ep = Path(evidence_path).expanduser()
        if not ep.is_file() or ep.stat().st_size == 0:
            raise CliError(f"--evidence file does not exist or is empty: {ep}")
        evidence_path = str(ep)
    if not verified and not fast_path:
        print(
            "REFUSED no verified fact on the board for "
            f"{run_id(game, chal)}; use one of: (a) `ctfboard.py verify record "
            "--verdict verified --reproduced yes --exit 0 --actor checker-<name>` first, or "
            "(b) the fast path `submit-log --evidence <execution evidence file>` when the "
            "executor is confident the flag is real (platform verdict is the verification)",
            file=sys.stderr,
        )
        return 3

    attempts = int(state.get("attempts", 0) or 0)
    max_attempts = governor["max_attempts"]
    if attempts >= max_attempts:
        print(
            f"REFUSED submit governor: attempts {attempts}/{max_attempts} exhausted; "
            "no further submissions are allowed for this challenge",
            file=sys.stderr,
        )
        return 3

    raw_hash = (args.flag_hash or "").strip()
    if not raw_hash:
        raise CliError("--flag-hash must not be empty")
    if HEX64.match(raw_hash.lower()):
        flag_hash = raw_hash.lower()
    else:
        flag_hash = hashlib.sha256(raw_hash.encode("utf-8", "replace")).hexdigest()
        print(
            "WARN raw flag passed to --flag-hash; storing sha256 only (the raw flag is never persisted)",
            file=sys.stderr,
        )

    attempts += 1
    state["attempts"] = attempts
    verdict = args.verdict
    save_state(directory, state)

    append_jsonl(
        submissions_path(directory),
        {
            "ts": now_iso(),
            "cid": args.cid or "",
            "flag_sha256": flag_hash,
            "verdict": verdict,
            "attempt": attempts,
            "actor": sanitize_line(actor, 120),
            "basis": "platform-auto" if fast_path else "verified-fact",
            "evidence": sanitize_line(evidence_path, 300) if fast_path else "",
        },
    )
    remaining = max(0, max_attempts - attempts)
    approval_required = attempts >= governor["user_approval_after"]
    review_required = attempts >= governor["review_after"]

    telemetry(
        directory,
        game,
        chal,
        "submit",
        actor,
        {
            "attempt": attempts,
            "max_attempts": max_attempts,
            "remaining": remaining,
            "verdict": verdict,
            "cid": args.cid or "",
            "flag_sha256": flag_hash,
        },
    )

    bump_phase(state, "record" if verdict == "accepted" else "submit")
    save_state(directory, state)

    if approval_required or review_required:
        print(
            f"GUIDANCE attempts={attempts}/{max_attempts}: independent review and user approval "
            f"are required before further platform submissions "
            f"(review_after={governor['review_after']}, "
            f"user_approval_after={governor['user_approval_after']}); hard deny at "
            f"{max_attempts}",
            file=sys.stderr,
        )

    print(
        f"SUBMIT attempt={attempts}/{max_attempts} verdict={verdict} "
        f"remaining={remaining} approval_required={'yes' if approval_required else 'no'} "
        f"review_required={'yes' if review_required else 'no'} cid={args.cid or '-'}"
    )
    return 0


def cmd_governor(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    governor = governor_config()
    state = load_state(directory)
    attempts = int(state.get("attempts", 0) or 0)
    remaining = max(0, governor["max_attempts"] - attempts)
    approval_required = attempts >= governor["user_approval_after"]
    review_required = attempts >= governor["review_after"]
    denied = attempts >= governor["max_attempts"]
    print(
        f"GOVERNOR attempts={attempts} max={governor['max_attempts']} remaining={remaining} "
        f"approval_required={'yes' if approval_required else 'no'} "
        f"review_required={'yes' if review_required else 'no'} "
        f"denied={'yes' if denied else 'no'}"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    state = load_state(directory)
    facts = read_jsonl(facts_path(directory))
    deadends = read_jsonl(deadends_path(directory))
    verifies = read_jsonl(verifies_path(directory))
    governor = governor_config()

    counts = {status: 0 for status in FACT_STATUSES}
    for fact in facts:
        status = str(fact.get("status", "candidate"))
        counts[status] = counts.get(status, 0) + 1
    last_verdict = str(verifies[-1].get("verdict", "-")) if verifies else "none"
    attempts = int(state.get("attempts", 0) or 0)
    budget = state.get("budget") or {}
    spent = state.get("spent") or {}

    print(f"CHALLENGE {run_id(args.game, args.chal)}")
    print(f"TITLE {sanitize_line(state.get('title') or '-', 200)}")
    print(f"CATEGORY {sanitize_line(state.get('category') or '-', 60)}")
    print(f"PHASE {sanitize_line(state.get('phase') or 'intake', 40)}")
    print(
        "FACTS total={total} candidate={candidate} verified={verified} "
        "challenged={challenged} retired={retired}".format(
            total=len(facts),
            candidate=counts.get("candidate", 0),
            verified=counts.get("verified", 0),
            challenged=counts.get("challenged", 0),
            retired=counts.get("retired", 0),
        )
    )
    print(f"DEADENDS {len(deadends)}")
    print(f"ATTEMPTS {attempts}/{governor['max_attempts']}")
    print(f"LAST_VERIFY {last_verdict}")
    print(
        "BUDGET tokens={}/{} minutes={}/{}".format(
            spent.get("tokens", 0),
            budget.get("tokens", 0),
            spent.get("minutes", 0),
            budget.get("minutes", 0),
        )
    )
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    directory = require_challenge(args.game, args.chal)
    game = _component(args.game, "game")
    chal = _component(args.chal, "chal")
    actor = (args.actor or "executor").strip()
    event = (args.event or "").strip()
    if not event:
        raise CliError("--event must not be empty")
    if not re.fullmatch(r"[a-z0-9_.-]{1,60}", event):
        raise CliError(
            f"--event {event!r} must match [a-z0-9_.-]{{1,60}} (e.g. skill_load, search, tool_call)"
        )
    data: Dict[str, Any] = {}
    if args.data:
        try:
            parsed = json.loads(args.data)
        except ValueError as exc:
            raise CliError(f"--data is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise CliError("--data must be a JSON object")
        data = parsed

    telemetry(directory, game, chal, event, actor, data)

    if event == "route":
        state = load_state(directory)
        bump_phase(state, "route")
        save_state(directory, state)

    print(f"LOG {event}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _add_common(sub: argparse.ArgumentParser, *, actor_default: str = "executor") -> None:
    sub.add_argument("--game", required=True, help="game id (path component, e.g. 2026-fall)")
    sub.add_argument("--chal", required=True, help="challenge id (path component, e.g. web-01)")
    sub.add_argument(
        "--actor",
        default=actor_default,
        help=f"actor id recorded on the board (default {actor_default}; "
        "only actors starting with the checker prefix (legacy verifier accepted) may write verified facts)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctfboard.py",
        description=(
            "Per-challenge CTF state plane (SPEC §4). Durable records are stored by "
            "multi-agentcollaboration-blackboard/blackboard.py; this CLI enforces the "
            "candidate/verified gate and the submit governor."
        ),
        epilog=(
            "Exit codes: 0 ok, 2 usage/config/gate denial, 3 submit-governor refusal. "
            "Run `ctfboard.py <command> --help` for command details."
        ),
    )
    subs = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    _add_common(common)

    init = subs.add_parser("init", parents=[common], help="create/idempotently ensure challenge tree")
    init.add_argument("--title", default="", help="challenge title")
    init.add_argument("--category", default="", help="category (web/pwn/reverse/crypto/forensics/...)")
    init.set_defaults(func=cmd_init)

    path = subs.add_parser("path", parents=[common], help="print the challenge directory")
    path.set_defaults(func=cmd_path)

    fact = subs.add_parser("fact", help="fact operations")
    fact_subs = fact.add_subparsers(dest="fact_cmd", required=True)
    fact_add = fact_subs.add_parser("add", parents=[common], help="add a candidate/verified fact")
    fact_add.add_argument("--claim", required=True, help="one-sentence finding")
    fact_add.add_argument("--evidence", required=True, help="concrete evidence (command/output/path)")
    fact_add.add_argument("--source", choices=FACT_SOURCES, default="exec")
    fact_add.add_argument("--status", choices=["candidate", "verified"], default="candidate")
    fact_add.add_argument("--artifact", default=None, help="artifact path")
    fact_add.set_defaults(func=cmd_fact_add)
    fact_list = fact_subs.add_parser("list", parents=[common], help="compact fact table (max 30 rows)")
    fact_list.add_argument("--status", choices=FACT_STATUSES, default=None)
    fact_list.add_argument("--all", action="store_true", help="include retired facts too")
    fact_list.set_defaults(func=cmd_fact_list)

    deadend = subs.add_parser("deadend", help="dead-end operations")
    deadend_subs = deadend.add_subparsers(dest="deadend_cmd", required=True)
    deadend_add = deadend_subs.add_parser("add", parents=[common], help="record a scoped dead end")
    deadend_add.add_argument("--scope", required=True, help="what was ruled out")
    deadend_add.add_argument("--tests", required=True, help="test set actually performed")
    deadend_add.add_argument("--invariant", required=True, help="observed failure/invariant")
    deadend_add.add_argument("--reopen-if", required=True, dest="reopen_if", help="new evidence that reopens it")
    deadend_add.set_defaults(func=cmd_deadend_add)

    verify = subs.add_parser("verify", help="verification evidence operations")
    verify_subs = verify.add_subparsers(dest="verify_cmd", required=True)
    verify_record = verify_subs.add_parser(
        "record", parents=[common], help="append a verify.md evidence block"
    )
    verify_record.add_argument("--claim", required=True, help="one-sentence claim being verified")
    verify_record.add_argument("--command", required=True, help="exact reproduction command")
    verify_record.add_argument("--output", required=True, help="inline output text or path to output file")
    verify_record.add_argument("--exit", required=True, type=int, dest="exit_code", help="command exit code")
    verify_record.add_argument("--artifact", default=None, help="artifact path (sha256 recorded)")
    verify_record.add_argument("--reproduced", choices=["yes", "no"], default=None)
    verify_record.add_argument("--verdict", choices=VERDICTS, default=None)
    verify_record.set_defaults(func=cmd_verify_record)

    submit = subs.add_parser("submit-log", parents=[common], help="log a platform submission")
    submit.add_argument("--flag-hash", required=True, dest="flag_hash",
                        help="sha256 of the submitted flag (raw flags are hashed, never stored)")
    submit.add_argument("--verdict", required=True, choices=SUBMIT_VERDICTS)
    submit.add_argument("--cid", default="", help="platform challenge id")
    submit.add_argument("--evidence", default="",
                        help="execution-confidence evidence file; allows the fast path without a "
                             "pre-verified fact (the platform verdict is the verification)")
    submit.set_defaults(func=cmd_submit_log)

    governor = subs.add_parser("governor", parents=[common], help="print submit governor state")
    governor.set_defaults(func=cmd_governor)

    status = subs.add_parser("status", parents=[common], help="compact challenge summary")
    status.set_defaults(func=cmd_status)

    log = subs.add_parser("log", parents=[common], help="append one arbitrary telemetry event")
    log.add_argument("--event", required=True,
                     help="event name: route/skill_load/search/tool_call/compaction/...")
    log.add_argument("--data", default="", help="JSON object payload")
    log.set_defaults(func=cmd_log)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as exc:
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

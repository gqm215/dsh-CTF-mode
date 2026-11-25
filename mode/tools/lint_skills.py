#!/usr/bin/env python
"""Lint the 12 CTF-mode entry skills against SPEC.md section 2.

Usage:
    python ~/.agents/ctf-mode/tools/lint_skills.py [--json]

Checks per skill (roots/resident/<name>/SKILL.md):
  * exactly the 12 expected names exist (no extras, none missing)
  * directory name == frontmatter name, kebab-case
  * required frontmatter keys and required literal values
  * description: one line, starts "Use when", contains "do not use when",
    80..200 chars
  * disable-model-invocation is false, user-invocable is true
  * whole file <= 200 lines and <= 6 KB (6144 bytes)
  * required body sections present and in SPEC order
  * verbatim retrieval-protocol block for triage + the 9 category entries
  * Output contract names tmp/<chal>/, draft/notes.md, final/flag.txt,
    final/writeup.md, verify.md and the candidate-vs-verified rule
  * References has >= 1 markdown link; every local link target resolves
  * Anti-patterns has >= 3 bullets
  * no fenced code block longer than 25 lines

Exit code 0 only when every check passes; 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESIDENT = ROOT / "roots" / "resident"

EXPECTED = [
    "ctf-triage",
    "ctf-web",
    "ctf-pwn",
    "ctf-reverse",
    "ctf-crypto",
    "ctf-forensics",
    "ctf-misc",
    "ctf-ai-ml",
    "ctf-malware",
    "ctf-osint",
    "ctf-blackboard",
    "ctf-submit",
]

# Entries that must carry the SPEC section-2 retrieval protocol verbatim.
PROTOCOL_REQUIRED = EXPECTED[0:10]  # triage + 9 category entries

RETRIEVAL_BLOCK = "\n".join(
    [
        "需要入口页未覆盖的技法时：",
        '1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"',
        "2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载",
        "3) 按该包的 Method/Verify 执行；把新 fact 写黑板",
        "4) 无结果 → 回本页决策树，不要空转",
    ]
)

REQUIRED_KEYS = [
    "name",
    "description",
    "domain",
    "type",
    "tools",
    "license",
    "stability",
    "schema_version",
    "disable-model-invocation",
    "user-invocable",
]

REQUIRED_SECTIONS = [
    "## When it applies",
    "## 5 分钟检查表",
    "## 子技术决策树",
    "## Method（首步协议）",
    "## Output contract",
    "## Verify success（可观察）",
    "## References",
    "## Anti-patterns",
]

OUTPUT_CONTRACT_TOKENS = [
    "tmp/<chal>/",
    "draft/notes.md",
    "final/flag.txt",
    "final/writeup.md",
    "verify.md",
    "candidate",
    "verified",
]

MAX_BYTES = 6 * 1024
MAX_LINES = 200
DESC_MIN, DESC_MAX = 80, 200
MAX_FENCE_LINES = 25
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FM_DELIM = "---"


def load_yaml(text: str):
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - PyYAML is present on this host
        raise SystemExit(f"FATAL: PyYAML unavailable: {exc}")
    return yaml.safe_load(text)


def split_frontmatter(text: str):
    """Return (raw_frontmatter, body, error)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FM_DELIM:
        return None, text, "missing opening '---' frontmatter delimiter"
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_DELIM:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]), None
    return None, text, "missing closing '---' frontmatter delimiter"


def section_text(body: str, heading: str) -> str | None:
    """Body text from `heading` up to the next level-2 heading."""
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    out = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def local_links(section: str) -> list[str]:
    """Markdown link targets that are not http(s)/mailto/anchor."""
    targets = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", section):
        target = match.group(1).strip()
        if not target or target.startswith("#"):
            continue
        if re.match(r"^(?:https?:|mailto:|ftp:)", target, re.I):
            continue
        targets.append(target.split("#", 1)[0].split("?", 1)[0])
    return targets


def check_skill(name: str) -> dict:
    """Return {'name', 'errors': [...], 'bytes', 'lines'}."""
    errors: list[str] = []
    skill_dir = RESIDENT / name
    path = skill_dir / "SKILL.md"
    info = {"name": name, "errors": errors, "bytes": 0, "lines": 0}

    if not skill_dir.is_dir():
        errors.append("missing skill directory")
        return info
    if not path.is_file():
        errors.append("missing SKILL.md")
        return info

    raw = path.read_bytes()
    info["bytes"] = len(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"not valid UTF-8: {exc}")
        return info
    info["lines"] = len(text.splitlines())

    if info["bytes"] > MAX_BYTES:
        errors.append(f"file is {info['bytes']} bytes > {MAX_BYTES}")
    if info["lines"] > MAX_LINES:
        errors.append(f"file is {info['lines']} lines > {MAX_LINES}")

    fm_raw, body, fm_err = split_frontmatter(text)
    if fm_err:
        errors.append(fm_err)
        return info
    try:
        fm = load_yaml(fm_raw)
    except Exception as exc:
        errors.append(f"frontmatter YAML does not parse: {exc}")
        return info
    if not isinstance(fm, dict):
        errors.append("frontmatter is not a mapping")
        return info

    # --- frontmatter ---
    for key in REQUIRED_KEYS:
        if key not in fm:
            errors.append(f"frontmatter missing key '{key}'")

    fm_name = fm.get("name")
    if not isinstance(fm_name, str) or fm_name != name:
        errors.append(f"frontmatter name {fm_name!r} != directory {name!r}")
    if not KEBAB.match(name):
        errors.append(f"name {name!r} is not kebab-case")

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("description missing or not a string")
    else:
        if "\n" in desc:
            errors.append("description must be one line")
        if not desc.startswith("Use when"):
            errors.append("description must start with 'Use when'")
        if "do not use when" not in desc.lower():
            errors.append("description must contain 'do not use when'")
        if not (DESC_MIN <= len(desc) <= DESC_MAX):
            errors.append(
                f"description length {len(desc)} not in [{DESC_MIN},{DESC_MAX}]"
            )
        if "```" in desc or "$" in desc:
            errors.append("description must not contain workflow/payload markers")

    if fm.get("stability") != "learning":
        errors.append("stability must be 'learning'")
    if fm.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if str(fm.get("license", "")).strip().upper() != "MIT":
        errors.append("license must be MIT")
    if fm.get("disable-model-invocation") is not False:
        errors.append("disable-model-invocation must be false")
    if fm.get("user-invocable") is not True:
        errors.append("user-invocable must be true")
    if "tools" in fm and not isinstance(fm.get("tools"), (list, str)):
        errors.append("tools must be a list")
    if not fm.get("domain"):
        errors.append("domain must be non-empty")
    if not fm.get("type"):
        errors.append("type must be non-empty")

    # --- body sections ---
    found_positions = []
    for heading in REQUIRED_SECTIONS:
        pos = body.find(heading)
        if pos < 0:
            errors.append(f"missing section '{heading}'")
        else:
            found_positions.append((heading, pos))
    positions = [pos for _, pos in found_positions]
    if positions != sorted(positions):
        errors.append("required sections are not in SPEC order")

    # --- retrieval protocol ---
    if name in PROTOCOL_REQUIRED and RETRIEVAL_BLOCK not in text:
        errors.append("missing verbatim SPEC section-2 retrieval protocol block")

    # --- output contract ---
    contract = section_text(body, "## Output contract")
    if contract is None:
        pass  # already reported
    else:
        for token in OUTPUT_CONTRACT_TOKENS:
            if token not in contract:
                errors.append(f"Output contract missing '{token}'")

    # --- verify success ---
    verify = section_text(body, "## Verify success（可观察）")
    if verify is not None and "unverified" not in verify:
        errors.append("Verify success must mention '(unverified)' for failures")

    # --- references ---
    refs = section_text(body, "## References")
    if refs is None:
        pass
    else:
        all_links = re.findall(r"\[[^\]]*\]\([^)\s]+(?:\s+\"[^\"]*\")?\)", refs)
        if not all_links:
            errors.append("References has no markdown link")
        for target in local_links(refs):
            resolved = (skill_dir / target).resolve()
            if not resolved.exists():
                errors.append(f"References local link target missing: {target}")

    # --- anti-patterns ---
    anti = section_text(body, "## Anti-patterns")
    if anti is None:
        pass
    else:
        bullets = [
            line
            for line in anti.splitlines()
            if re.match(r"^\s*[-*]\s+\S", line)
        ]
        if len(bullets) < 3:
            errors.append(f"Anti-patterns has {len(bullets)} bullets, need >= 3")

    # --- fenced code blocks ---
    fence_open = None
    fence_len = 0
    fence_count = 0
    for line in body.splitlines():
        if line.strip().startswith("```"):
            if fence_open is None:
                fence_open = True
                fence_len = 0
                fence_count += 1
            else:
                fence_open = None
                if fence_len > MAX_FENCE_LINES:
                    errors.append(
                        f"fenced code block #{fence_count} has {fence_len} lines "
                        f"> {MAX_FENCE_LINES}"
                    )
        elif fence_open is not None:
            fence_len += 1
    if fence_open is not None:
        errors.append("unclosed fenced code block")

    return info


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    if not RESIDENT.is_dir():
        print(f"FATAL: missing resident root {RESIDENT}")
        return 1

    actual = sorted(
        p.name for p in RESIDENT.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
    extras = sorted(set(actual) - set(EXPECTED))
    missing = [n for n in EXPECTED if n not in actual]

    rows = []
    failures = 0
    total_bytes = 0
    for name in EXPECTED:
        info = check_skill(name)
        total_bytes += info["bytes"]
        if info["errors"]:
            failures += 1
        rows.append(info)

    if missing:
        print(f"FAIL catalog: missing entry skills: {', '.join(missing)}")
    if extras:
        print(f"FAIL catalog: unexpected skills under roots/resident: {', '.join(extras)}")
    catalog_errors = len(missing) + len(extras)
    count_ok = len(actual) == len(EXPECTED) and not catalog_errors

    if as_json:
        payload = {
            "root": str(RESIDENT),
            "count": {"actual": len(actual), "expected": len(EXPECTED), "ok": count_ok},
            "skills": rows,
            "total_bytes": total_bytes,
            "failures": failures + (0 if count_ok else 1),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for info in rows:
            if info["errors"]:
                reasons = "; ".join(info["errors"])
                print(f"FAIL {info['name']} ({info['bytes']} B, {info['lines']} lines): {reasons}")
            else:
                print(f"PASS {info['name']} ({info['bytes']} B, {info['lines']} lines)")

        passed = len(rows) - failures
        catalog_note = "" if count_ok else " [catalog count mismatch]"
        print(
            f"SUMMARY: {passed}/{len(EXPECTED)} PASS, {failures} failed, "
            f"total {total_bytes} B{catalog_note}"
        )
        if not count_ok:
            print(
                f"CATALOG: expected 12 dirs {EXPECTED}; actual {len(actual)} "
                f"(missing={missing}, extras={extras})"
            )

    return 0 if (failures == 0 and count_ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

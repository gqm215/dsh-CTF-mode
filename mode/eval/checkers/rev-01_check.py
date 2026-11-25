#!/usr/bin/env python3
"""Recompute the rev-01 (byte pipeline) flag from its attachment.

The challenge ships `checker.py` with `KEY` and `TARGET`. `checker.encode()` is
bijective: it XORs with a repeating key, adds i*7 per byte, then reverses the
whole buffer. This checker loads the shipped checker module (read-only), applies
the exact inverse, and proves the recovered flag through the checker's own
`encode()` before printing it.

Usage: python rev-01_check.py [--attachments-dir DIR]
Exit 0 and print `flag{...}` on success; exit 1 with a diagnostic otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

DEFAULT_DIR = Path(r"D:\AI_Lab\CTF_Agent\experiments\trackA\challenges\rev-01")
FLAG_RE = re.compile(r"^flag\{[a-z0-9_]+\}$")


def load_checker(path: Path):
    """Load the challenge's checker.py as a module without running __main__."""
    if not path.is_file():
        raise FileNotFoundError(f"missing attachment {path}")
    spec = importlib.util.spec_from_file_location("rev01_shipped_checker", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attachments-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)

    try:
        checker = load_checker(Path(args.attachments_dir) / "checker.py")
    except (FileNotFoundError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    key, target = checker.KEY, checker.TARGET

    # Invert: reverse -> subtract i*7 -> XOR key.
    out = bytearray()
    for i, byte in enumerate(bytes(reversed(target))):
        out.append(((byte - (i * 7)) & 0xFF) ^ key[i % len(key)])
    try:
        flag = bytes(out).decode("ascii")
    except UnicodeDecodeError:
        print("ERROR: inverse pipeline produced non-ASCII bytes", file=sys.stderr)
        return 1

    if not FLAG_RE.match(flag):
        print(f"ERROR: recovered text is not a flag: {flag!r}", file=sys.stderr)
        return 1
    if checker.encode(flag.encode()) != target:
        print("ERROR: inverse pipeline does not round-trip through the shipped checker", file=sys.stderr)
        return 1
    print(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

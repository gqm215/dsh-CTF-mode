#!/usr/bin/env python3
"""Recompute the crypto-01 (textbook RSA, small e) flag from its attachment.

The challenge ships only `params.json`; no solver script. This checker inverts
the announced construction deterministically:

    c = m^3 mod n  with  m^3 < n  =>  c is an exact perfect cube, so
    m = integer_cube_root(c) is unique (no modular ambiguity).

It then re-encodes m and asserts the challenge equation, and prints the flag.

Usage: python crypto-01_check.py [--attachments-dir DIR]
Exit 0 and print `flag{...}` on success; exit 1 with a diagnostic otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_DIR = Path(r"D:\AI_Lab\CTF_Agent\experiments\trackA\challenges\crypto-01")
FLAG_RE = re.compile(r"^flag\{[a-z0-9_]+\}$")


def integer_cube_root(value: int) -> int:
    """Exact floor(cuberoot(value)) for value >= 0, pure integer math."""
    if value < 0:
        raise ValueError("negative value")
    lo, hi = 0, 1
    while hi**3 <= value:
        hi *= 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid**3 <= value:
            lo = mid
        else:
            hi = mid - 1
    return lo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attachments-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)

    params_path = Path(args.attachments_dir) / "params.json"
    if not params_path.is_file():
        print(f"ERROR: missing attachment {params_path}", file=sys.stderr)
        return 1
    params = json.loads(params_path.read_text(encoding="utf-8"))
    n, e, c = int(params["n"]), int(params["e"]), int(params["c"])

    if e != 3:
        print(f"ERROR: unexpected public exponent e={e}", file=sys.stderr)
        return 1
    m = integer_cube_root(c)
    if m**3 != c:
        print("ERROR: c is not an exact perfect cube (unexpected construction)", file=sys.stderr)
        return 1
    if m**3 >= n:
        print("ERROR: m^e >= n, modular wraparound occurred (checker assumption broken)", file=sys.stderr)
        return 1
    if pow(m, e, n) != c:
        print("ERROR: recovered m does not re-encrypt to c", file=sys.stderr)
        return 1

    flag = m.to_bytes((m.bit_length() + 7) // 8, "big").decode("ascii")
    if not FLAG_RE.match(flag):
        print(f"ERROR: recovered text is not a flag: {flag!r}", file=sys.stderr)
        return 1
    print(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

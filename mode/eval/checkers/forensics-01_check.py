#!/usr/bin/env python3
"""Recompute the forensics-01 (PNG red-channel LSB) flag from its attachment.

The challenge ships only `capture.png`. The documented payload framing is:

    offset 0: magic b"LSB1"
    offset 4: payload length, 2 bytes big-endian
    offset 6: payload bytes (flag, ASCII)

Bits are the LSBs of the red channel, MSB-first, row-major, one bit per pixel.
This checker implements a pure-stdlib PNG reader (chunk walk + zlib decompress +
row filter handling for filter types 0/1/2) and extracts the flag.

Usage: python forensics-01_check.py [--attachments-dir DIR]
Exit 0 and print `flag{...}` on success; exit 1 with a diagnostic otherwise.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

DEFAULT_DIR = Path(r"D:\AI_Lab\CTF_Agent\experiments\trackA\challenges\forensics-01")
FLAG_RE = re.compile(r"^flag\{[a-z0-9_]+\}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_pixels(png_bytes: bytes) -> tuple[int, int, list[bytes]]:
    """Decode an 8-bit RGB/RGBA PNG to unfiltered row byte strings (no alpha drop)."""
    if png_bytes[:8] != PNG_MAGIC:
        raise ValueError("not a PNG file")
    pos = 8
    idat = bytearray()
    width = height = bit_depth = color_type = None
    while pos + 8 <= len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        tag = png_bytes[pos + 4 : pos + 8]
        chunk = png_bytes[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG missing IHDR")
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError(f"unsupported PNG format: bit_depth={bit_depth} color_type={color_type}")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    if len(raw) != height * (stride + 1):
        raise ValueError(f"unexpected raw size {len(raw)} != {height * (stride + 1)}")
    rows: list[bytearray] = []
    prev = bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        filter_type = raw[base]
        row = bytearray(raw[base + 1 : base + 1 + stride])
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(channels, stride):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter type {filter_type} on row {y}")
        rows.append(row)
        prev = row
    return width, height, channels, rows


def extract_red_lsb(png_bytes: bytes) -> bytes:
    width, height, channels, rows = png_pixels(png_bytes)
    bits: list[int] = []
    for row in rows:
        for x in range(width):
            bits.append(row[x * channels] & 1)
    payload = bytearray()
    for offset in range(0, len(bits) - 7, 8):
        byte = 0
        for bit in bits[offset : offset + 8]:
            byte = (byte << 1) | bit
        payload.append(byte)
    return bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attachments-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)

    png_path = Path(args.attachments_dir) / "capture.png"
    if not png_path.is_file():
        print(f"ERROR: missing attachment {png_path}", file=sys.stderr)
        return 1
    try:
        payload = extract_red_lsb(png_path.read_bytes())
    except (ValueError, zlib.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if payload[:4] != b"LSB1":
        print(f"ERROR: LSB1 magic missing (got {payload[:4]!r})", file=sys.stderr)
        return 1
    length = struct.unpack(">H", payload[4:6])[0]
    try:
        flag = payload[6 : 6 + length].decode("ascii")
    except UnicodeDecodeError:
        print("ERROR: payload is not ASCII", file=sys.stderr)
        return 1
    if not FLAG_RE.match(flag):
        print(f"ERROR: extracted text is not a flag: {flag!r}", file=sys.stderr)
        return 1
    print(flag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

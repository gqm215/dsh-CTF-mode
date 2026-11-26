#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""registry_init.py -- build a registry.json from the tools actually on PATH.

Portable by design: it never invents an entry for a missing tool. Run it on a
fresh host, then the side's gen_bin generates the entry shims and doctor
verifies them.

Usage:
  python3 registry_init.py --platform linux|kali|windows --registry PATH [--force]
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time

LINUX_CANDIDATES = [
    ("python3", "cmd", "python3 -V"), ("pip3", "cmd", "pip3 -V"),
    ("gdb", "cmd", "gdb --version"), ("gdb-multiarch", "cmd", None),
    ("objdump", "cmd", None), ("readelf", "cmd", None), ("strings", "cmd", None),
    ("r2", "cmd", "r2 -v"), ("rabin2", "cmd", None),
    ("binwalk", "cmd", None), ("foremost", "cmd", None), ("exiftool", "cmd", "exiftool -ver"),
    ("tshark", "cmd", "tshark -v"), ("tcpdump", "cmd", None),
    ("steghide", "cmd", None), ("stegseek", "cmd", None), ("zsteg", "cmd", None),
    ("sqlmap", "cmd", "sqlmap --version"), ("ffuf", "cmd", "ffuf -V"),
    ("gobuster", "cmd", None), ("nmap", "cmd", "nmap --version"),
    ("nikto", "cmd", None), ("hydra", "cmd", None),
    ("hashcat", "cmd", "hashcat --version"), ("john", "cmd", None),
    ("sqlite3", "cmd", None), ("docker", "cmd", "docker --version"),
    ("patchelf", "cmd", None),
    ("ROPgadget", "cmd", None), ("one_gadget", "cmd", None),
    ("seccomp-tools", "cmd", None),
    ("qemu-arm", "cmd", None), ("qemu-x86_64", "cmd", None),
    ("gp", "cmd", "gp --version"), ("java", "cmd", "java -version"),
    ("jadx", "cmd", "jadx --version"), ("apktool", "cmd", None),
    ("volatility3", "cmd", None),
]
LINUX_PROBES = [
    ("pwntools", "import pwn; print(pwn.__version__)"),
    ("z3", "import z3; print(z3.get_version_string())"),
    ("crypto", "import Crypto; print(Crypto.__version__)"),
    ("angr", "import angr; print(angr.__version__)"),
    ("fpylll", "import fpylll; print(fpylll.__version__)"),
    ("volatility", "import volatility3; print('ok')"),
]
WINDOWS_CANDIDATES = [
    ("python", ["python.exe"], ["-V"], "general"),
    ("node", ["node.exe"], ["--version"], "general"),
    ("java", ["java.exe"], ["-version"], "general"),
    ("jadx", ["jadx.bat", "jadx.exe"], ["--version"], "reverse"),
    ("apktool", ["apktool.bat"], ["--version"], "reverse"),
    ("tshark", ["tshark.exe"], ["-v"], "forensic"),
    ("adb", ["adb.exe"], ["version"], "mobile"),
    ("exiftool", ["exiftool.exe"], ["-ver"], "misc"),
    ("ffmpeg", ["ffmpeg.exe"], ["-version"], "misc"),
    ("es", ["es.exe"], None, "general"),
    ("vmrun", ["vmrun.exe"], None, "virtual"),
    ("cdb", ["cdb.exe"], None, "reverse"),
    ("sqlmap", ["sqlmap.py"], ["--version"], "web"),
]


def which_first(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def build_linux(platform):
    entries = []
    venv_py = os.path.expanduser("~/CTF_Lab/Environment/venv/bin/python")
    py = venv_py if os.path.exists(venv_py) else "python3"
    for name, kind, version in LINUX_CANDIDATES:
        if shutil.which(name):
            e = {"name": name, "kind": kind, "cmd": name}
            if version:
                e["version"] = version
            entries.append(e)
    for name, expr in LINUX_PROBES:
        entries.append({"name": name, "kind": "probe", "optional": True,
                        "probe": f"{py} -c \"{expr}\""})
    fixed = [
        ("ctf-venv", os.path.expanduser("~/CTF_Lab/Environment/venv/bin/python")),
        ("pwndbg", os.path.expanduser("~/.gdbinit")),
    ]
    for name, path in fixed:
        if os.path.exists(path):
            entries.append({"name": name, "kind": "path", "path": path})
    return entries


def build_windows():
    entries = []
    for name, names, args, category in WINDOWS_CANDIDATES:
        exe = which_first(names)
        if not exe:
            continue
        e = {"name": name, "kind": "cli", "side": "win", "exec": exe.replace("\\", "/"),
             "category": [category], "notes": "auto-detected on PATH by registry_init.py"}
        if args:
            e["probe"] = {"args": args}
        entries.append(e)
    seen = set()
    for p in glob.glob(r"D:/Major_CompuTech_Suite/IDA Pro*/ida.exe"):
        if p and os.path.exists(p) and p not in seen:
            seen.add(p)
            entries.append({"name": "ida", "kind": "gui", "side": "win",
                            "exec": p.replace("\\", "/"), "category": ["reverse"],
                            "notes": "auto-detected GUI launcher"})
    return entries


def main():
    ap = argparse.ArgumentParser(description="init a portable CTF toolchain registry")
    ap.add_argument("--platform", choices=["linux", "kali", "windows"], required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if os.path.exists(args.registry) and not args.force:
        print(f"registry exists: {args.registry} (use --force to overwrite)", file=sys.stderr)
        return 2
    entries = build_windows() if args.platform == "windows" else build_linux(args.platform)
    side = {"linux": "linux", "kali": "linux:kali", "windows": "win"}[args.platform]
    payload = {
        "schema": 1,
        "updated": time.strftime("%Y-%m-%d"),
        "side": side,
        "note": ("generated by toolchain/portable/registry_init.py from tools on PATH; "
                 "edit and rerun the side's gen_bin after changes"),
        "entries": entries,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.registry)), exist_ok=True)
    with open(args.registry, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"registry written: {args.registry} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

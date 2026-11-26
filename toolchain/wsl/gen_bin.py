#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_bin.py -- 由 WSL 侧 registry.json 生成 ~/CTF_Lab/Toolchain/bin 的统一入口。

规则：
  - 固定生成：ctf-py（venv python）、ctf-doctor、angr-py、ghidra-headless（存在才生成）
  - kind=cmd 的条目：在 PATH 里找到实体后，做同名 symlink
  - 只清理带 "managed-by ctflab" 标记的文件和 symlink，不碰用户自建文件
  - 幂等：可反复跑

用法（在 WSL 内）：
    python3 ~/CTF_Lab/Toolchain/scripts/gen_bin.py
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "registry.json")
BIN = os.path.join(os.path.dirname(HERE), "bin")
MARK = "managed-by ctflab"


def write_script(name, body):
    path = os.path.join(BIN, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n# %s\n%s\n" % (MARK, body))
    os.chmod(path, 0o755)
    return name


def clear_managed():
    removed = []
    for name in os.listdir(BIN):
        path = os.path.join(BIN, name)
        try:
            if os.path.islink(path):
                os.unlink(path)
                removed.append(name)
            elif os.path.isfile(path):
                with open(path, "r", errors="ignore") as f:
                    head = f.read(200)
                if MARK in head:
                    os.unlink(path)
                    removed.append(name)
        except OSError:
            pass
    return removed


def main():
    os.makedirs(BIN, exist_ok=True)
    removed = clear_managed()
    created = []

    venv = os.path.expanduser("~/CTF_Lab/Environment/venv/bin/python")
    if os.path.exists(venv):
        created.append(write_script("ctf-py", 'exec "%s" "$@"' % venv))

    created.append(write_script("ctf-doctor", 'exec python3 "%s/doctor.py" "$@"' % HERE))

    if os.path.exists("/opt/angr/bin/python"):
        created.append(write_script("angr-py", 'exec /opt/angr/bin/python "$@"'))

    if os.path.exists("/opt/ghidra/support/analyzeHeadless"):
        created.append(write_script("ghidra-headless", 'exec /opt/ghidra/support/analyzeHeadless "$@"'))

    with open(REG, encoding="utf-8") as f:
        data = json.load(f)

    for entry in data.get("entries", []):
        if entry.get("kind") != "cmd":
            continue
        cmd = entry.get("cmd") or entry["name"]
        src = shutil.which(cmd)
        if not src:
            continue
        dest = os.path.join(BIN, entry["name"])
        try:
            if os.path.lexists(dest):
                os.unlink(dest)
            os.symlink(src, dest)
            created.append(entry["name"])
        except OSError as exc:
            print("skip %s: %s" % (entry["name"], exc))

    print("bin: %s" % BIN)
    print("removed: %d | created: %d" % (len(removed), len(created)))
    print(" ".join(sorted(created)))


if __name__ == "__main__":
    main()

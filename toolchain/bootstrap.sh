#!/usr/bin/env bash
# Portable CTF toolchain bootstrap (Linux/WSL side).
# Usage: bash toolchain/bootstrap.sh [--prefix DIR]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${HOME}/CTF_Lab/Toolchain"
DEFAULT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; DEFAULT=0; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$PREFIX/scripts" "$PREFIX/bin"
cp "$ROOT/wsl/doctor.py" "$ROOT/wsl/gen_bin.py" "$ROOT/portable/registry_init.py" "$PREFIX/scripts/"
python3 "$PREFIX/scripts/registry_init.py" --platform linux --registry "$PREFIX/scripts/registry.json" --force
python3 "$PREFIX/scripts/gen_bin.py"
if [ "$DEFAULT" = "1" ]; then
  LINE='export PATH="$HOME/CTF_Lab/Toolchain/bin:$PATH" # managed-by ctflab'
  for f in "$HOME/.profile" "$HOME/.bashrc"; do
    touch "$f"
    grep -qxF "$LINE" "$f" || echo "$LINE" >> "$f"
  done
  echo "PATH marker written to ~/.profile and ~/.bashrc (new shell required)"
fi
python3 "$PREFIX/scripts/doctor.py"

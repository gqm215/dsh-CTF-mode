# Portable CTF toolchain framework（基础骨架）

> 本目录只搭框架（registry → bin → doctor/TOOLS.md），不安装、不分发任何重型或授权工具。
> 需要让 Agent 按本机现状装配时，用仓库 `prompts/toolchain-assembly.md`。

Registry-driven three-layer toolchain, deployable to any Windows or Linux/WSL host:

1. layer 1 — the tools themselves (this framework never installs them);
2. layer 2 — `registry.json` -> generated `bin/` entry shims + `doctor` probes + `TOOLS.md`;
3. layer 3 — agent docs (`TOOLS.md`, environment-entry blocks in skills, `AGENTS.md` pointers).

## Quick deploy on a new host

Linux / WSL:

```bash
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
bash dsh-CTF-mode/toolchain/bootstrap.sh
source ~/.profile    # or open a new shell
ctf-doctor
```

Windows (PowerShell 7):

```powershell
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
pwsh -File .\dsh-CTF-mode\toolchain\bootstrap.ps1
# open a new terminal, then:
ctf-doctor
```

`bootstrap` copies the framework to `~/CTF_Lab/Toolchain` (Windows: `D:\CTF\Toolchain`), detects the
tools actually on PATH into `registry.json` (never invents missing tools), generates `bin/` shims,
adds the bin directory to the shell/user PATH (marker `managed-by ctflab`), and runs `doctor` once.

## After deploying

- `doctor.py` / `doctor.ps1`: OK / DOWN (service not running, not a failure) / FAIL / SKIP.
- `gen_bin.py` / `gen_bin.ps1`: regenerate shims after editing `registry.json`; idempotent.
- `gen_tools.ps1`: regenerate `TOOLS.md` from the registry.
- Examples: `examples/registry.{win,wsl,kali}.example.json` are snapshots from the author's host,
  useful as field references, not as a replacement for a host-local registry.
- GUI/MCP tools are host-local: doctor will show DOWN unless that host has the app running.

See `docs/DEPLOY-REMOTE.md` in the repository for remote-host scenarios.

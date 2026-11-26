# 远端 / 其他机器部署 CTF 工具链

> 让 Agent 按本提示词装配：[`prompts/toolchain-assembly.md`](../prompts/toolchain-assembly.md)。

本仓库的 `toolchain/` 是**可移植的三层工具链框架**，不是本机快照。任何一台运行 DSH + CTF-mode 的
Windows 或 Linux/WSL 主机都能在几分钟内得到同一套结构：`registry.json` → `bin/` 入口 → `doctor` 体检 →
`TOOLS.md` / 技能"环境入口"。

## 先决条件

- 远端能访问 GitHub（clone 本仓库）。
- Python 3（bootstrap 用它做工具发现；Windows 上 `python` 或 `py`）。
- 可选：PowerShell 7（Windows 侧脚本要求）；Linux/WSL 用 bash。
- 工具实体不在框架内：bootstrap 只发现"已安装"的工具，missing 的直接不登记；缺哪些用 doctor 的
  FAIL/缺失报告看，再按需 apt/winget 安装。

## 快速部署（远端主机）

### Linux / WSL

```bash
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
bash dsh-CTF-mode/toolchain/bootstrap.sh
source ~/.profile        # 或新开 shell
ctf-doctor
```

### Windows (PowerShell 7)

```powershell
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
pwsh -File .\dsh-CTF-mode\toolchain\bootstrap.ps1
# 新终端后：
ctf-doctor
```

bootstrap 做的事：

1. 建 `~/CTF_Lab/Toolchain`（Windows：`D:\CTF\Toolchain`）；
2. 拷贝 `doctor` / `gen_bin` / `gen_tools` / MCP 探针等脚本；
3. 用 `portable/registry_init.py` 扫描 PATH，把**真实存在**的工具写进 `registry.json`；
4. 生成 `bin/` 入口（WSL 用 symlink，Windows 用 `.cmd` shim）；
5. 在 `~/.profile`/`~/.bashrc`（或用户 PATH）写带 `managed-by ctflab` 标记的路径；
6. 跑一次 doctor 输出 OK/DOWN/FAIL/SKIP。

`--prefix DIR` 可改为其他目录（测试/多实例）；此时不写 PATH。

## 远端怎么"享受"同一套结构

- CTF-mode bundle 装好后，persona 指向的就是同一契约：先 `ctf-doctor`，再用 `<prefix>/bin` 入口，
  DOWN=GUI 没开而非故障，路径不确定先看 `TOOLS.md`/`registry.json`。
- 远端 GUI/MCP 是**该主机自己的**：IDA/x64dbg/Burp 没装就是 DOWN/缺条目；框架不跨机转发 MCP。
- 若远端是纯 Linux 无 GUI，`ctf-doctor` 会只剩 CLI 条目，这正是预期；Web/PWN/Crypto 不受影响。
- 若远端还要带 WSL：Linux 侧再跑一次 `bootstrap.sh`；Windows 侧条目与 WSL 条目分开登记、各自 doctor。

## 升级与清理

- 框架更新：`git pull` 后重跑 bootstrap（幂等）。
- 注册表改完：Linux 跑 `python3 <prefix>/scripts/gen_bin.py`；Windows 跑
  `pwsh -File <prefix>/scripts/gen_bin.ps1`；再 `gen_tools.ps1` 刷新 TOOLS.md。
- 卸载：删 prefix 目录并从 shell/PATH 移除 `managed-by ctflab` 行即可，不碰其他工具。

## 已验证（2026-11-26）

- Windows bootstrap（临时 prefix）：5 OK / 0 FAIL，`bin/*.cmd` 生成正常。
- Ubuntu-26.04 bootstrap（临时 prefix）：34 OK / 0 FAIL / 4 SKIP（缺 venv 的库探针标 optional→SKIP）。
- 本机既有部署口径不变；`D:\CTF\Toolchain` 与 `~/CTF_Lab/Toolchain` 继续由各自 doctor 管理。

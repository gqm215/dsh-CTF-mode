# 本机 CTF 工具链交底（Agent 版）

> 数据来源：用户 2026-11-26 本机实测。改动工具/注册表后先重跑 doctor 再信任下列数字。
> 口径：① 工具链本机层（工具实体）② 软链/索引层（契约入口）③ Agent 认知层（文档与技能）。

## 0. 一句话

- 本机层：完整。Windows/WSL 两侧都装齐 RE、PWN、Web、Crypto、Misc/Forensic 主力工具。
- 索引层：两侧完整。Windows 有注册表 + 12 个 bin shim + 探针/生成器；WSL 两个发行版有 gen_bin.py 生成的入口（26.04 22 个、kali 21 个），PATH 已写入 `.bashrc`/`.profile`。
- 认知层：全局/项目 AGENTS、自动生成的 TOOLS.md、Burp 手册、进度与缺口报告齐全；9 个 CTF/RE 技能全部接线（顶部统一"环境入口"块）。

## 1. Windows（宿主）

| 域 | 入口 |
|---|---|
| RE | IDA Pro 9.3 `D:\Major_CompuTech_Suite\IDA Pro 9.3\ida.exe`；x64dbg/x32dbg；WinDbg `cdb.exe`；Wireshark/tshark 4.6.6；jadx 1.5.5（走 Android Studio JBR 21） |
| Web | Burp Suite Community 2026.3.1（MCP 扩展已加载，自动启动 9876） |
| 通用 | Everything + es 1.1.0.27；010 Editor；CFF Explorer；exiftool 13.59；adb/platform-tools；FFmpeg 8.1.2 |
| 虚拟化/移动 | VMware Workstation 26.0.0（vmrun.exe）；Android Studio 2026.1 |
| 运行时 | Python 3.14.5 / Node 24 / Java 8 / .NET + ilspycmd / Rust |

## 2. WSL Ubuntu-26.04（主分析环境）

- RE：Ghidra 12.1.3 + re-mcp 3.0.3（服务 8766）、angr 9.3.4（服务 8765）、radare2 6.0.7。
- PWN：pwntools 4.15、ROPgadget、one_gadget、seccomp-tools、patchelf；glibc 调试、gcc-multilib、libc6:i386、qemu-user、gdb-multiarch；libc-database / how2heap 已克隆。
- Crypto：PARI/GP 2.17.3；CTF venv（pycryptodome/fpylll/cysignals/ecdsa/xortool/hashpumpy/randcrack/primefac/pwntools/ROPGadget/cypari2）。SageMath 未装（optional，网络不可达）。
- Misc/Forensic：binwalk、exiftool、zsteg、steghide、stegseek、foremost、sleuthkit、ewf-tools、scalpel、testdisk、volatility3、tshark。
- 容器：Docker 29.1.3（daemon active）；miniconda3 26.9.4（为 Sage 准备，未用上）。

## 3. WSL kali-linux（工具集）

- apt 1920 包（部署前 665），kali-linux-headless 元包：sqlmap/ffuf/gobuster/nmap/hydra/nikto/wpscan/mitmproxy/msfconsole/binwalk/exiftool/hashcat/john/sqlite3/radare2/gdb-multiarch/qemu-user/jadx/apktool。
- Python：python3-pwntools 4.15、python3-z3、pycryptodome（系统级）。
- 缺：nuclei、dalfox。元包附带 metasploit/postgresql/mariadb/apache/kismet 等（约 3–4GB，未清理）。

## 4. 索引 / 契约入口

### Windows：`D:\CTF\Toolchain\`

- `registry.json`：17 条（cli 9 / gui 4 / mcp 4，含 burp-mcp；WSL 侧 angr/ghidra 不重复登记）。
- `bin\*.cmd` 12 个 shim：adb / burp / ctf-doctor / ctf-doctor-all / efind / es / ida / ida-mcp / idat / jadx / tshark / vmrun。
- `doctor.ps1`（OK/DOWN/FAIL，退出码=FAIL 数）、`scripts\doctor-all.ps1`（三边体检）、`gen_tools.ps1`（生成 TOOLS.md）、`discover.ps1`、`scripts\mcp_probe.py`、`scripts\smoke-mcp.ps1`、`scripts\ida_mcp_start.py`、`scripts\install-gui-pack.ps1`、`scripts\efind.ps1`、`docs\burp-mcp-setup.md`。
- PATH：`D:\CTF\Toolchain\bin` 已写用户级 PATH；**已运行的 DSH 会话不继承，新终端才生效**。

### WSL

- 两侧均有 `~/CTF_Lab/Toolchain/{scripts,bin,registry.json}`；`gen_bin.py` 从注册表生成 bin（26.04 22 个、kali 21 个），PATH 写入 `.bashrc`+`.profile`（带 managed-by ctflab 标记，幂等）。
- 生成器只清理带标记项，不碰用户自建文件；注册表新增 cmd 后重跑即可。

### 状态语义

- OK：探针通过；DOWN：服务没开（IDA 13337、x64dbg 27042），**不算故障**；FAIL：真故障；SKIP：optional（Sage）。

## 5. Agent 认知层

- 全局：`~/.agents/AGENTS.md`（58 行，4 条硬链接完好）。
- 项目：`D:\CTF\AGENTS.md`（25 行：工具归属、三步登记、DOWN 语义、WSL 分工、MCP 边界、产物约定）。
- 说明书：`D:\CTF\Toolchain\TOOLS.md`（自动生成：MCP/CLI/GUI/26.04/kali + 入口）。
- 9 个技能（`~/.agents/skills`）：ctf-crypto、ctf-pwn、ctf-web、ctf-reverse、ctf-misc、ctf-forensics、ctf-writeup、reverse-eng-binary-triage、reverse-eng-ghidra；均已插入"环境入口"块（Windows bin / WSL bin / efind / TOOLS.md / ctf-doctor）。

## 6. 验收证据（2026-11-26 实测）

| 侧 | 结果 |
|---|---|
| Windows doctor.ps1 | 15 OK / 2 DOWN / 0 FAIL |
| Ubuntu-26.04 doctor.py | 29 OK / 0 DOWN / 0 FAIL / 1 SKIP |
| kali-linux doctor.py | 23 OK / 0 DOWN / 0 FAIL |
| doctor-all | TOTAL FAIL: 0 |

MCP 工具数（实测）：angr 18、Ghidra 33、IDA 22、x64dbg 23、WinDbg/cdb 12、Burp 24（127.0.0.1:9876/mcp）。

## 7. 已知缺口与风险

1. PATH 生效边界：用户级 PATH 已加，但已运行会话/旧 shell 不继承；用 shim 或绝对路径，或开新终端。
2. Everything 依赖：es/efind 需 Everything 进程；efind 已做自动拉起，es 直接调用会报 IPC 失败。
3. WSL apt：26.04 必须 `Acquire::ForceIPv4`（已写 `/etc/apt/apt.conf.d/99force-ipv4`）。
4. WSL 自关机：`sleep infinity` 保活需重启/注销后重新拉起，否则 8765/8766 消失。
5. Sage 缺失：docker.io 不通、daocloud 403、conda-forge 无包；标 optional，用 fpylll+sympy+z3+pari 兜底。
6. kali 体量：headless 元包带入服务器组件约 3–4GB，未清理。
7. 目录卫生：`D:\SecTools\GUI` 留有安装包/BApp/jar/burp-data，`state/ida-mcp.log` 为调试残留。

## 8. 复验命令

```powershell
pwsh -File D:\CTF\Toolchain\scripts\doctor-all.ps1   # 三边体检，TOTAL FAIL 应为 0
pwsh -File D:\CTF\Toolchain\gen_tools.ps1            # 重生成 TOOLS.md
pwsh -File D:\CTF\Toolchain\scripts\smoke-mcp.ps1    # 真拉起 IDA/x64dbg 验证 MCP
```

```bash
# WSL 侧
python3 ~/CTF_Lab/Toolchain/scripts/doctor.py
```

## 9. 交接注意

- 新开终端才有 `D:\CTF\Toolchain\bin`；否则用绝对路径调 `doctor.ps1`。
- IDA / x64dbg 的 MCP 是"人机共用"形态：不开工具就是 DOWN，不要当故障。
- IDA 用 MCP：`ida.exe -A -S"D:\CTF\Toolchain\scripts\ida_mcp_start.py" <样本>`。
- Burp：扩展已加载并自动启动 9876；重装时 Extensions → Add → Java → `D:\SecTools\GUI\burp-mcp-all.jar`。
- WSL 服务挂了：`wsl -u root systemctl start angr-mcp re-mcp-ghidra`，确认 `sleep infinity` 在跑。

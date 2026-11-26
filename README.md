# DSH CTF Mode

DeepSeek Harness（DSH）的 CTF 解题模式：**可安装的 DSH bundle（agent preset `ctf`）** + 模式运行时（12 入口技能 / 按题黑板 / 快车道提交 / 独立监察审计 / 知识检索）+ 设计与验收文档。

> `main` 只负责这个**模式本身**：bundle、`mode/` 运行时、评测与文档。工具链不随仓库分发——仓库提供三层环境框架与「装配提示词」，工具与授权安装由用户本机决定（详见下面的「环境框架」）。

## 组成

| 目录 | 内容 |
|---|---|
| `package.json` / `cordis.patch.yml` | 可安装 bundle：声明 agent preset `ctf` 及其插件行 |
| `locale/`、`icon.svg`、`docs/DETAIL.md` | 插件管理里的标题/描述/详情页/图标 |
| `mode/` | 模式运行时：SPEC / PROTOCOL / 12 入口技能 / 平台适配器 / 黑板 / 监察审计 / 预算 / 路由评测 / config.example.yaml |
| `docs/` | 设计与实施报告、内核方法论、验收记录、内核模板、远端部署说明 |
| `toolchain/` | **基础环境框架**（只搭三层骨架，不装工具）：bootstrap + registry/bin/doctor 生成器 |
| `prompts/` | 装配提示词：短版（README 内置）+ 完整版（确认环境后装配工具链） |
| `examples/` | 自然指令版实验提示词 |

## 安装模式（DSH 插件管理 → 添加插件 → GitHub 地址）

本仓库根目录就是可安装的 bundle 包（`package.json` 的 `dsh.bundle.patch` 指向 `cordis.patch.yml`）。

**方式 A：跟随 main（每次更新后重装即生效）**

```text
github:gqm215/dsh-CTF-mode
```

**方式 B：钉住完整 commit（插件管理里可显示/执行 git 更新）**

```text
github:gqm215/dsh-CTF-mode#a8a955c35f4ddfc31e0185a16ba7a31009f7b6b7
```

**方式 C：本地目录**：把仓库根目录绝对路径填进「添加插件」。

- 兼容性：`engines.dsh = "0.2.2-rc.5"`，即只承诺与本机当前 DSH 版本兼容；DSH 升级后需要重测并更新该字段。
- 可选：发布到 npm 后可直接输包名 `dsh-ctf-mode` 安装；GitHub 来源方式不依赖 npm。

安装后新建会话选择 **CTF** 预设。bundle 只安装预设；模式运行时仍需部署到 `~/.agents/ctf-mode/`：

```text
mkdir %USERPROFILE%\.agents\ctf-mode
copy mode\* 到 %USERPROFILE%\.agents\ctf-mode\
copy mode\config.example.yaml 为 config.yaml
```

## 环境框架（三层，按需）

模式要真正做题，需要一个与本机工具对接的三层结构。**仓库只搭骨架，不安装、不分发工具**：

1. **工具实体层**：你本机已有的工具（IDA / Ghidra / angr / pwntools / jadx / sqlmap / tshark / exiftool …）。授权类 GUI（IDA Pro、Burp Pro、010 Editor、VMware、Android Studio）由你自行安装。
2. **契约层**：`registry.json`（单一事实源）→ `bin/` 入口 shim → `doctor` 体检 → `TOOLS.md`。
3. **认知层**：`AGENTS.md`、技能顶部「环境入口」块、`TOOLS.md` 指针；让 Agent「只走入口、不猜路径」。

### 步骤 1：部署基础框架（约 10 秒，只搭骨架）

Linux / WSL：

```bash
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
bash dsh-CTF-mode/toolchain/bootstrap.sh
source ~/.profile          # 或新开 shell
ctf-doctor
```

Windows（PowerShell 7）：

```powershell
git clone --depth 1 https://github.com/gqm215/dsh-CTF-mode
pwsh -File .\dsh-CTF-mode\toolchain\bootstrap.ps1
# 新终端后
ctf-doctor
```

bootstrap 只做：建 prefix → 拷贝 doctor/gen_bin/registry_init 脚本 → 扫描 PATH 生成 `registry.json` → 生成 `bin/` 入口 → 写 PATH 标记 → 跑一次 doctor。**不安装任何重型/授权工具。**

### 步骤 2：把本机已有工具接进 registry

```powershell
# Windows：编辑 <prefix>\registry.json 后
pwsh -File <prefix>\scripts\gen_bin.ps1      # 生成 bin\*.cmd 入口
pwsh -File <prefix>\gen_tools.ps1            # 刷新 TOOLS.md
pwsh -File <prefix>\doctor.ps1               # 验收：OK/DOWN/FAIL/SKIP
```

```bash
# Linux / WSL：编辑 <prefix>/scripts/registry.json 后
python3 <prefix>/scripts/gen_bin.py          # 生成 bin/ 入口
python3 <prefix>/scripts/doctor.py           # 验收
```

条目字段与示例见 `toolchain/README.md` 与 `toolchain/examples/registry.*.example.json`。路径不确定就先 `efind`/`es`，再登记；**不要猜绝对路径**。

### 步骤 3（可选）：交给 Agent 自动装配

- **短版提示词**（适合已有基本环境、只想接线）：

```text
按本仓库的三层结构（工具实体 / registry 契约 / 认知层）帮我接好本机工具链：
1) 先列出你计划使用的目录与该机已有工具，向我确认；
2) 用仓库 toolchain/ 的 bootstrap 搭框架，不安装任何重型或授权工具；
3) 扫描 PATH 与常见安装位置，把已有工具写进 registry.json；
4) 生成 bin 入口与 TOOLS.md，运行 doctor 并给我 OK/DOWN/FAIL/SKIP 汇总；
5) 只在约定目录内写文件，不改我已有技能内容，不读取任何凭据。
```

- **完整版提示词**：[prompts/toolchain-assembly.md](prompts/toolchain-assembly.md)。
  它会先与你确认主机环境、WSL 发行版、目录前缀、权限、网络与已有工具清单，再装配工具链、
  连接 registry/bin/doctor/TOOLS.md/技能入口，最后按 doctor 验收并出报告；适合换机、远端部署、
  或工具链大改。

## 验证（本机 2026-11-25/26 验收，非平台承诺）

- 入口技能 lint **12/12**；路由评测 10 例，accuracy 9/10、forbidden 0；
- 黑板 e2e **66/66**；CTFy 适配器契约 **23/23**；监察审计 **7/7**；
- 工具链框架 bootstrap：Windows 临时 prefix 5 OK/0 FAIL，Ubuntu-26.04 prefix 34 OK/0 FAIL/4 SKIP；
- 真实平台用例：CTFy SAMPLE-005 Accepted（1 次提交 0 错误）、SAMPLE-020 三问全对；DataCon 训练营 CTF 142 / 22 两题 Accepted。

## 平台注意事项（实测）

- DataCon 训练营有并发/速率限制：客户端应单飞（同时 1 个请求）、间隔 0.5–1s、5xx 指数退避；
  `500 获取附件失败` / `提交flag失败,操作异常` 多为限流外壳，单发可复现才算真实错误。
- gzctf / CTFy / DataCon 的登录态或 Token 需定期刷新；凭据只存本机指定文件，不出仓库。

## 安全边界

- 仓库不包含凭据、flag、cookie、session、浏览器 profile 与 `runs/`、`traces/`、`pools/`。
- 适配器只读本机凭据；日志与黑板只存 flag 的 sha256（flag 只写入运行目录的 `final/`）。
- 监察审计（`mode/bin/ctf-audit.py`）只做行为纪律复核，不判定 flag 对错。
- 装配提示词默认只读+约定目录写；安装任何软件前必须先征求你的同意。

## 状态

实验性研究项目；接口与实现可能变化。

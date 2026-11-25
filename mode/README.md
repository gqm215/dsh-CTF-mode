# CTF mode（DSH）

DSH 的 CTF 解题模式运行时。预设 `ctf` 由 `D:\AI_Lab\CTF_Agent\dsh-ctf-core` 声明并安装到
desktop profile；本目录是模式本身（技能入口、知识池、黑板、验证、评测）。

- 契约：`SPEC.md`（入口格式 / skillctl ctf / ctfboard / 验证门 / 评测 / bundle）
- 多智能体：`PROTOCOL.md`（C1/C2、三角色、采纳门）
- 内核方法论：`D:\AI_Lab\CTF_Agent\reports\CTF-Agent-内核方法论.md`
- 创建方案：`D:\AI_Lab\CTF_Agent\reports\DSH-CTF模式创建方案.md`

## 目录

```
~/.agents/ctf-mode/
├─ config.yaml              # 预算/状态/验证/telemetry 配置
├─ index.json               # 全量知识索引（生成物，500+ 技能）
├─ roots/resident/          # 12 个模型可见入口（catalog 只放这里）
├─ pools/                   # 只读知识池（12 个 repo 的 junction，不进扫描根）
├─ bin/ctfboard.py          # 每题状态平面 CLI（黑板/验证/提交治理）
├─ bin/ctf-submit.py        # gzctf 平台适配（三层验证的 L3）
├─ tools/                   # lint_skills.py、索引测试、ctfboard 测试
├─ templates/               # 内核模板 + verify.md.template
├─ schemas/                 # challenge/fact/verify + 扩展清单 schema
├─ extensions/              # 扩展注册区（加目录+manifest，不改核心）
├─ eval/                    # 路由用例、3 题×4 基线矩阵、报告
├─ runs/<game>/<chal>/      # 每题：board.db verify.md traces/ tmp/ draft/ final/
└─ traces/events.jsonl      # 全局 telemetry
```

## 常用命令

```powershell
# 知识检索（500+ 深挖包，不进 catalog）
python $env:USERPROFILE\.agents\tools\skillctl.py ctf search "堆 tcache 泄漏"
python $env:USERPROFILE\.agents\tools\skillctl.py ctf show ctf-web --head 40
python $env:USERPROFILE\.agents\tools\skillctl.py ctf doctor      # 索引与实体一致性

# 每题状态
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfboard.py init --game gzctf --chal web-01 --title "..." --category web
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfboard.py fact add --game gzctf --chal web-01 --claim "..." --evidence "..."
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfboard.py deadend add --game gzctf --chal web-01 --scope "..." --tests "..." --invariant "..." --reopen-if "..."
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfboard.py verify record --game gzctf --chal web-01 --actor checker-1 --claim "..." --command "..." --output out.txt --exit 0 --reproduced yes --verdict verified
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfboard.py status --game gzctf --chal web-01

# 平台（可选，需 gzctf login）
gzctf doctor
python $env:USERPROFILE\.agents\ctf-mode\bin\ctf-submit.py --game gzctf --chal web-01 --cid 12 --verified-fact f3 --flag-file final\flag.txt

# CTFy 平台（一次性引导登录 + 自动签发 pf_ API 令牌，之后全自动）
python $env:USERPROFILE\.agents\ctf-mode\tools\ctfy_bootstrap.py
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfy.py doctor
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfy.py list
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfy.py --game <comp> start SAMPLE-018
python $env:USERPROFILE\.agents\ctf-mode\bin\ctfy.py submit-qa SAMPLE-005 --question flag --answer-file final\flag.txt --verified-fact f1 --game ctfy --competition e4e78ff318dc4844beac13f9ea7409aa
# 纯问答自动求解示例（SAMPLE-020；答案来自平台标准 CTFY-0002，逐题 verified 后提交）
python $env:USERPROFILE\.agents\ctf-mode\tools\solve_SAMPLE020_quiz.py
# gzctf：一次性引导登录（浏览器里登录一次，随后 CLI 全自动）
python $env:USERPROFILE\.agents\ctf-mode\tools\gzctf_login_once.py
# 确定性全链路（下载→求解→复现→黑板→提交/平台状态→终态）+ 性能
python $env:USERPROFILE\.agents\ctf-mode\tools\live_smoke.py --challenge SAMPLE-005 --platform-game e4e78ff318dc4844beac13f9ea7409aa --qa
python $env:USERPROFILE\.agents\ctf-mode\tools\perf_profile.py
```

## 入口（12 个，模型可自动调用）

`ctf-triage`、`ctf-web`、`ctf-pwn`、`ctf-reverse`、`ctf-crypto`、`ctf-forensics`、
`ctf-misc`、`ctf-ai-ml`、`ctf-malware`、`ctf-osint`、`ctf-blackboard`、`ctf-submit`。

新题先 `ctf-triage` 分类；入口页覆盖不到的技法 → `skillctl ctf search` → 只读命中页；
结论先写 candidate fact，只有 checker 能写 verified；提交只走 L3 平台终态判定。

### 为什么这 12 个入口不在 `~/.agents/skills/`

它们是 **CTF preset 作用域**的技能根，由 bundle 的 `skill-filesystem` 行以
`customSkillDirs = ~/.agents/ctf-mode/roots/resident` 挂载：

- 只有选中 **CTF** preset 的会话，catalog 里才会出现这 12 个入口（实测 catalog 44 项 =
  12 入口 + 26 全局常驻 + dsh-doc + 5 内置；模型可用 `skill` 工具直接加载）；
- 把它们复制进全局根会让**每个** preset（含标准模式）都背上这 12 个入口，破坏
  "入口只在 CTF 会话可见 / catalog ≤12 入口" 的预算不变量，并与全局根里按需的旧
  `ctf-*` 技能（`disable-model-invocation: true`，只能 `/ctf-web` 显式调用）同名冲突。

所以在 **standard** 会话里看不到 `ctf-triage` / 模型无法加载 `ctf-*` 是预期行为：
CTF 模式的能力只在 CTF preset 会话里生效。验证方法：新建会话时在模式选择器选 **CTF**，
再让模型列出 `ctf-*` 技能；或看 `eval/reports/catalog_verification.json`。

## 验收（目标）

- 12/12 入口 lint 通过；catalog 只含入口 + 全局常驻，深挖包不进 catalog；
- 30 条检索 top-3 ≥ 27；路由 10 例首选 ≥ 8 且 forbidden = 0；
- 错误提交 0；验证门拦截人为注入假阳性；
- 3 道归档题 × 4 基线（C0/C1/C2/C3）可复算报告 —— **已按用户口径改为"真实平台跑通 + 性能短板"**；
- Standard/PTC/Minimal/Cordis 行为不变。

实测状态（2026-11-25）：12/12 lint、500 技能/30 检索、黑板与验证门 66/66、路由 9/10、
真会话 catalog 44 项（12+26+6）、CTFy 真实 **Accepted**（SAMPLE-005，1 次提交 0 错误）、
适配器契约 13/13、性能画像见 `tools/perf_report.md`。未闭环的外部项：CTFy 实例节点池离线
（`503 no_healthy_node`）、gzctf 未登录、human-check PoW 实验路径未复验。

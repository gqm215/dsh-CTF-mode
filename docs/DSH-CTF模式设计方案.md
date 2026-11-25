# DSH-CTF 模式设计方案（结构 / 布局 / 实施路线）

> 目标：在 DSH 上做一个独立的 CTF agent preset，同时满足三件事——**大而全**（CTF 全类别 + 红/蓝/AI 安全都能用到）、**精而深**（类别内到子技术、工具协议、验证）、**精确高效**（模型自动选得准、上下文不膨胀、成本可测）。
> 可执行创建方案见 `reports/DSH-CTF模式创建方案.md`（目标版，按依赖顺序实施）。
> 注：本文早前的版本化路线（V1–V4）已被目标版方案取代；以目标版的 P0–P6 为准。
> 依据：DSH 实际架构（agent preset / bundle / plugin / skill provider / per-scope 合并 / `disable-model-invocation` / `user-invocable` / catalog 渲染）；本机已有 149 个技能（26 常驻 + 123 按需）与 10.5MB skill-pool；文献综述与机制分析（L0–L8、上下文管理、黑板/租约、验证门）；本机 `gzctf`、WSL2、ai-toolchain（angr/Ghidra headless）。

---

## 0. 结论先行

- **不要做一个"装载 150 个技能"的 CTF 模式**。模型在 10–15 个入口里选择是可靠的，在 150 个里选择是随机的。
- 采用 **"3 层技能 + 1 个路由工具 + 1 个状态平面 + 1 个验证门"**：
  - 常驻模型可调用 **12–14 个类别入口**（triage + 8 类 + 管理/验证 + AI 安全）；
  - 类别内子技术写进类别 SKILL.md 的决策树与 `references/`，按需 `read`；
  - 全量库（ctf-skills、Noor、Trident、ferr079、llm-redteam 等）放 `ctf-mode/pools/`，由 `ctf_skill_search`/`ctf_skill_use` 工具检索并加载，不进 catalog；
  - 运行期用 SQLite 黑板（事实/死胡同/意图/租约）管理状态；
  - 提交前用确定性验证门（reverify + 本地复现 + flag 来源），不允许模型自报成功。
- **通用模式零影响**：CTF 能力全部在 `ctf` preset 的 scoped 层里（独立 skill provider + 独立工具），Host 层与 Standard preset 的组合完全不变。
- 分两版落地：**V1 零代码**（preset bundle + 常驻 12 技能 + 文件式协议）先跑通；**V2 插件**（搜索/激活工具 + 黑板工具 + 平台适配）做"大而全"。
- **可扩展性是一等要求**：核心只认四个契约（类别入口 category、深挖包 pack、工具 tool、平台适配 adapter），新增类别/包/工具/平台/验证后端只填清单或加独立 bundle，不改核心 preset 代码；扩展可独立启停/卸载，坏一个不拖垮整体。

---

## 1. 设计原则

| 原则 | 具体约束 |
|---|---|
| 目录小、深度大 | 模型可见 catalog ≤14 个技能；每个类别入口的正文控制 ≤200 行，细节放 `references/` |
| 选择在类别层 | 不让模型在 SQLi/SSRF/XSS 之间选；类别 skill 内部给出子技术决策树 |
| 全量可达但按需 | 150+ 技能通过搜索/激活工具可达，但默认不进上下文 |
| 状态外置 | 事实、死胡同、意图、资源锁写黑板；聊天历史只做短期记忆 |
| 验证前置 | 只有"有执行证据的 claim"才算事实；提交 flag 前必须过验证门 |
| 计量驱动 | 每次运行记录 token/步数/上下文峰值/压缩次数/误选，按数据调路由 |
| 通用隔离 | CTF preset 只加 scoped provider/tools；不改 Host、不改 ~/.agents/skills 全局语义 |
| 扩展靠契约，不靠改核心 | 新类别/包/工具/平台/验证器只实现对应 manifest 或接口；核心只加载清单，不硬编码扩展列表 |

---

## 2. 总体结构：五层

```
┌───────────────────────────────────────────────────────────────────┐
│ L5 治理：授权范围 / 隔离沙箱 / allow-list / 审计 / 凭据本地化       │
├───────────────────────────────────────────────────────────────────┤
│ L4 评测与复盘：solve rate / 成本 / 首次解出时间 / 误提交 / trace   │
├───────────────────────────────────────────────────────────────────┤
│ L3 运行协议：triage → route → execute → verify → record → writeup  │
│      ├─ 黑板（事实/死胡同/意图/租约/资源）                          │
│      ├─ 验证门（reverify + 本地复现 + flag 来源）                   │
│      └─ 子代理（隔离执行 + 结构化回传）                             │
├───────────────────────────────────────────────────────────────────┤
│ L2 技能体系：常驻路由 12–14 / 类别深挖 / pools 全量（工具检索）     │
├───────────────────────────────────────────────────────────────────┤
│ L1 CTF preset（bundle）：persona + 工具 + skill provider + 策略     │
├───────────────────────────────────────────────────────────────────┤
│ L0 Host：模型路由/会话/沙箱/技能注册表/tool-skill/压缩/子代理（共享）│
└───────────────────────────────────────────────────────────────────┘
```

- **L0 只复用，不改造**：Host 已有 `dsh-skill`（注册表）、`dsh-skill-filesystem`（默认根）、`dsh-tool-skill`（catalog+loader）、压缩、子代理、workflow；CTF 模式不重造这些。
- **L1 是唯一新增的安装物**：一个 bundle，声明 `preset=ctf`，挂自己的 `dsh-skill-filesystem`（`includeDefaultRoots:false` + `customSkillDirs`）和 CTF 专用工具/策略。
- **L2–L5 都是内容与协议**，尽量用 Markdown/JSON/SQLite 表达，减少代码。

---

## 3. L1：CTF preset 的组成

### 3.1 bundle 与安装

```
dsh-ctf-core/                  # 核心 bundle：稳定、少变
├─ package.json                # { "dsh": { "bundle": { "patch": "./cordis.patch.yml" } } }
├─ cordis.patch.yml            # insert preset-ctf（@deepseek-ai/dsh-agent-preset）
├─ schemas/                    # category/pack/tool/adapter/verifier 的 JSON Schema
├─ manifests/                  # 核心自带类别入口清单（扩展不写这里）
├─ tools/
│  └─ skill-router.mjs         # V2：ctf_skill_search / ctf_skill_use
├─ skills/                     # 12 个常驻入口（或指向用户 resident 根）
└─ README.md

dsh-ctf-ext-<name>/            # 扩展 bundle：独立安装/启停/卸载
├─ package.json
├─ cordis.patch.yml            # 只做“给 preset 增删 plugin id / 注册工具”这件事
├─ manifests/                  # 该扩展的 tool/adapter/verifier 清单
└─ README.md

# skill-only 扩展（不需要 bundle）：直接放 ~/.agents/ctf-mode/extensions/，
# 由 index.json 与搜索工具发现。
```

安装：`plugin_manager install_bundle <绝对目录>` → `list_bundles`/`list_plugins` 验证 → 新会话选择 "CTF"。
注意：bundle 安装会执行 Host 进程内插件代码，需 Full access/审批；**先 V1 纯声明式，V2 再加工具代码**。

### 3.2 preset.composition 插件清单

以 Standard 为基线，按 CTF 需求裁剪/增补：

| 类别 | 插件 | 用途 |
|---|---|---|
| 身份 | `dsh-persona` | "CTF solving agent" persona，写明先 triage、再加载类别、验证优先 |
| 指令 | `dsh-agent-instructions` | 读取工作区 `AGENTS.md` / 本次比赛规则 |
| 时间 | `dsh-time-context` | 比赛剩余时间感知（预算控制） |
| shell | `dsh-tool-bash` / `dsh-tool-pwsh` | 按平台二选一；Windows 下 pwsh |
| 文件 | `dsh-tool-fs`、`dsh-tool-fs-search` | 读附件、写 exploit、glob/grep |
| 技能 | `dsh-skill-filesystem`（自定义根，`includeDefaultRoots:false`）+ 复用 Host `dsh-tool-skill` | 只把 CTF 常驻/类别技能加进本 preset 的 scope |
| 任务 | `dsh-tool-jobs`、`dsh-tool-todo` | 长任务/后台任务 |
| 交互 | `dsh-tool-ask-user` | 仅在授权/范围/比赛规则歧义时问 |
| 输出 | `dsh-tool-present`、`dsh-tool-office`（可选） | 题解/报告 |
| 压缩 | `dsh-compaction-basic` + `dsh-compaction-tool-result-pruner` | 长题上下文管理；阈值按 CTF 调低（如 6k/3k/1k） |
| 子代理 | `dsh-tool-subagent`（spawn/fork）+ `dsh-tool-subagent-control` | 类别探索隔离、并行尝试 |
| 编排 | `dsh-tool-workflow`（可选）、`dsh-agent-team`（可选） | 多题并行/团队级任务板 |
| 网络 | `dsh-tool-web` | 查 writeup/CVE/文档；但 CTF 模式要加"禁止直接搜本题答案"的纪律 |
| 插件管理 | `dsh-plugin-manager/tools` | 默认禁用（比赛期不允许改环境） |

不在 CTF preset 里挂：`plan-mode`（默认关闭，避免"只计划不动手"）、office-长期文档、market。

### 3.3 关键：独立 skill provider 而不是全局开关

```yaml
- id: ctf-skill-fs
  name: '@deepseek-ai/dsh-skill-filesystem'
  config:
    providerName: ctf-filesystem
    includeDefaultRoots: false
    customSkillDirs:
      - "%USERPROFILE%/.agents/ctf-mode/roots/resident"
    watch: true
```

- 该 provider 只在 `ctf` preset 的 scope 层注册；Standard 会话看不到它。
- 由于 skill registry 是 **Host 层 + scope 层合并**，CTF 会话实际 catalog = 全局 26 常驻 + CTF 常驻 12–14。**不是完全隔离**；要"只见 CTF"需要独立 profile/DSH_HOME，代价大，不建议 V1 做。
- 常驻根里**不要**加 `disable-model-invocation`；packs/pools 里的技能加 `disable-model-invocation: true`，只给 `/名称` 或 V2 搜索工具用。

---

## 4. L2：技能体系（大而全 × 精而深）

### 4.1 目录布局

```
%USERPROFILE%\.agents\ctf-mode\
├─ roots\
│  ├─ resident\                 # 模型可见，12–14 个
│  │  ├─ ctf-triage\SKILL.md
│  │  ├─ ctf-web\SKILL.md
│  │  ├─ ctf-pwn\SKILL.md
│  │  ├─ ctf-reverse\SKILL.md
│  │  ├─ ctf-crypto\SKILL.md
│  │  ├─ ctf-forensics\SKILL.md
│  │  ├─ ctf-misc\SKILL.md
│  │  ├─ ctf-ai-ml\SKILL.md        # AI/LLM 题
│  │  ├─ ctf-malware\SKILL.md
│  │  ├─ ctf-osint\SKILL.md
│  │  ├─ ctf-blackboard\SKILL.md   # 管理机制
│  │  └─ ctf-verify\SKILL.md       # 验证门
│  └─ packs\                    # 不进 catalog（disable-model-invocation）
│     ├─ web\{sqli,ssrf,xss,...}\SKILL.md
│     ├─ pwn\{heap,rop,kernel,...}\SKILL.md
│     ├─ rev\{...}
│     ├─ red\{ad,cloud,...}
│     ├─ blue\{detection,dfir,...}
│     └─ ai\{prompt-injection,rag-poisoning,...}
├─ extensions\                  # 扩展注册区：新增能力只加这里 + manifests
│  ├─ categories\<id>\category.yaml
│  ├─ packs\<id>\pack.yaml
│  ├─ tools\<id>\tool.yaml
│  ├─ adapters\<id>\adapter.yaml
│  └─ verifiers\<id>\verifier.yaml
├─ schemas\                      # 清单 JSON Schema（扩展作者依赖）
├─ pools\                        # 原始全量库（ctf-skills/Noor/Trident/ferr079/...）
├─ index.json                    # 技能/扩展统一索引（带 schema_version）
├─ boards\                       # 黑板 SQLite（每题/每 run 一个）
├─ traces\                       # token/步骤/压缩/误选日志
└─ config.yaml                   # 预算、allow-list、压缩阈值、平台参数、extensions 开关
```

命名约定：`ctf-<category>` 为入口，`<category>-<technique>` 为深挖包；避免与全局 107 个技能重名。

### 4.2 常驻技能（12–14 个）职责

| 技能 | 触发（description 要写负例） | 内容 |
|---|---|---|
| `ctf-triage` | 新题/题包/远程服务；不是纯代码任务 | 读题 → 判类别 → 定预算 → 决定加载哪个入口；产出 `ctf_state.json` |
| `ctf-web` | HTTP/URL/源码/浏览器；不是 pwn/rev | 认证/注入/SSRF/文件上传/反序列化/竞态/模板；工具：curl、浏览器、Burp 替代 |
| `ctf-pwn` | ELF/内存破坏/远程服务；不是 Web | 保护检查、栈/堆/格式化串、ROP/SROP、glibc 版本、seccomp；工具：pwntools/gdb/patchelf |
| `ctf-reverse` | 二进制/字节码/APK/固件；不是 pwn 利用 | 静态/动态、反混淆、VM lift、Ghidra/r2、angr；工具协议 |
| `ctf-crypto` | 数学/密钥/协议；不是 Web 加密 | RSA/ECC/格/AES/PRNG/协议；sage/pycryptodome |
| `ctf-forensics` | 磁盘/内存/流量/日志/文件；不是 Web | 文件雕复、PCAP、内存镜像、时间线；tshark/volatility/binwalk |
| `ctf-misc` | 编码/社工/沙箱/游戏/杂项 | 编码、QR、pyjail、shell jail、游戏交互 |
| `ctf-ai-ml` | 模型权重/prompt/对抗样本 | 权重扰动、对抗样本、prompt injection、模型窃取 |
| `ctf-malware` | 可疑样本/家族分析 | 静态/动态、YARA、C2 配置提取（仅分析，不运行） |
| `ctf-osint` | 人/组织/域名/公开信息 | 搜索、账号关联、地图/元数据 |
| `ctf-blackboard` | 多步骤/多分支/并行 | 事实/死胡同/意图/租约/资源；调用 SQLite CLI |
| `ctf-verify` | 即将提交 flag/结论 | 复现、来源、格式、反作弊；失败则回退 |

每个入口正文结构固定：**适用/不适用 → 5 分钟检查表 → 子技术决策树 → 工具调用协议 → 常见失败 → references 索引**。

### 4.3 深挖包（packs）：只给搜索工具/人工用

- 内容来源：ctf-skills（web/pwn/rev/crypto/forensics/misc/osint/malware/ai-ml）、Noor（AD/云/Web/API/逆向/防御）、Trident（检测/DFIR/紫队/云/K8s）、ferr079（攻击/防御 runbook）、Decepticon llm-redteam（AATMF v3）。
- 每个包 **frontmatter**：`disable-model-invocation: true` + `user-invocable: true`；保留 `/名称` 人工调用能力。
- 包内只写"方法 + 命令 + 判断条件 + 证据要求"，不贴大段 payload（payload 放 references，按需读）。

### 4.4 全量索引 `index.json`

```json
{
  "generated": "2026-11-24",
  "resident": ["ctf-triage","ctf-web","..."],
  "packs": [
    {"name":"web-sqli","category":"web","path":"packs/web/web-sqli/SKILL.md",
     "triggers":["sqli","sql injection","waf"],"when_not":["xss"]}
  ]
}
```

由 `skillctl` 生成/更新；V2 搜索工具只读它，不扫描全盘。

---

## 5. L3：运行协议（精确高效的真正来源）

### 5.1 阶段机

```
INTAKE → TRIAGE → ROUTE → EXECUTE(loop) → VERIFY → SUBMIT → RECORD/WRITEUP
                    ↑          │失败≥2次
                    └── REROUTE ┘
```

- **INTAKE**：列出附件/服务/题面；写 `state.json`（题目 ID、类别候选、预算、deadline）。
- **TRIAGE**：调 `ctf-triage`；输出类别 + 置信度 + 首选入口；不确定时给 2 个候选并说明。
- **ROUTE**：`skill` 加载类别入口；读该入口的 references 前 1–2 个。
- **EXECUTE**：每次行动必须产出"事实候选"或"死胡同"写黑板；连续 2 次同类失败 → REROUTE；连续 5 分钟无新事实 → 换工具/换子目标。
- **VERIFY**：候选 flag 必须满足：出现于工具真实输出 / 本地复现 / 格式符合题面；否则标记 candidate，不提交。
- **SUBMIT**：只提交 verified；提交后记录平台判定（不把 HTTP 200 当成功）。
- **RECORD**：写题解骨架 + 失败路径 + 用时/token；供复盘与 ACE 式 playbook 更新。

### 5.2 黑板（管理机制）

用 `multi-agentcollaboration-blackboard` 的 SQLite CLI：

| 表/概念 | CTF 用法 |
|---|---|
| Fact (candidate/verified) | "端口 8080 返回版本 1.2"（candidate）；"复现 flag 通过本地校验"（verified） |
| Dead end | "盲注 12 组 payload 无差异；出现新 sink 时重开" |
| Intent lease | "分析认证流程" 只允许一个 agent 持有 |
| Activity | 去重 `decompile:chall`、`scan:target` |
| Resource | 互斥 `nc:session`、`browser:web1` |
| Directive | 用户/主控的方向调整 |

规则：**只有 `ctf-verify` 能把 fact 升为 verified**；executor 只写 candidate。

### 5.3 子代理与并行

- 单题默认单 agent；当出现 ≥2 个独立子目标（如同时逆两个二进制、爆破与源码审计）时，`spawn` 子代理，每个子代理只带一个入口技能 + 自己的 references，回传 `{claim, artifact, repro, evidence}`。
- 子代理**不写 verified**，不回传完整对话；主控通过黑板合并。
- 最多 3–4 个并行；第 4 个收益递减（文献：多 agent 收益偏工程性）。

### 5.4 上下文/注意力预算

| 阶段 | 预算 | 措施 |
|---|---|---|
| INTAKE/TRIAGE | ≤ 15% 上下文 | 只读题面/文件清单，不读大二进制 |
| EXECUTE | ≤ 60% | 工具结果 head/tail 截断、二进制只读关键段、`references` 按需 |
| 压缩 | 每次窗口 ~70–80% 触发 | compaction-basic + tool-result-pruner（6k/3k/1k） |
| 状态 | 黑板外置 | 早期事实不依赖聊天历史；每阶段回读黑板摘要 |
| 成本 | 每题预算（token/$/时间） | 超预算降级：换更便宜模型/停止并行/提交已验证结论 |

指标：上下文峰值、压缩次数、工具结果占比、事实保留率（早期 fact 在后续仍可检索）、漂移事件（重复尝试/丢失已排除路径）。

---

## 6. L4：评测与复盘

- **运行指标**：solve rate、首次解出时间、token/$、错误提交数（目标 0）、误报率、上下文事件（压缩/漂移）、技能误选率。
- **离线复盘**：解析 DSH session log / gzctf 历史 → 逐题时间线 → 失败归因到 L0–L8；把"误选/缺技能/工具错误/验证失败"分类。
- **对标**：NYU CTF Bench / Cybench 子集做回归；固定题集 × 4 配置（裸 agent / +resident / +search 工具 / +验证门）比较。
- **技能选择准确率**：标注 30 条题面 → 首选类别正确率；目标 ≥90%（10 类任务，随机 10%）。

---

## 7. L5：治理与安全

1. **授权**：只对已授权 CTF 靶场/比赛；`config.yaml` 写 scope allow-list；不对公网目标执行扫描。
2. **隔离**：pwn/web 在 WSL/Docker 里跑；桌面不留目标凭据；比赛期只读共享环境。
3. **凭据**：只要本地（`~/.gzctf/session.json`）；不写技能、不进 prompt、不落 trace；日志脱敏。
4. **双用途**：red/blue 包默认 `disable-model-invocation`，只允许人工 `/名称` 或显式搜索；C2/凭据攻击类不在个人机安装。
5. **技能供应链**：只从固定 pool 根加载；V2 工具限制 root（no path traversal）；装前用 SkillSpector 抽检；记录来源与 license。
6. **反作弊**：CTF 模式纪律禁止直接搜本题 writeup/flag；submission 前检查 flag 来源（工具输出 vs 记忆）；必要时用不同环境复核。
7. **审计**：每题一条 trace（技能选择、工具调用、黑板变更、验证证据），赛后复盘可回放。

---

## 8. 实施路线（V1 → V4）

### V1：零代码 MVP（1–2 天）
0. 先定 4 个 manifest schema（category / pack / tool / adapter）+ 扩展模板 `ctf-ext-kit/`；核心 preset 只读清单，不硬编码扩展。
1. 建 `~/.agents/ctf-mode/roots/resident/`：先做 8 个（triage + web/pwn/rev/crypto/forensics/misc/verify），从 ctf-skills/Noor 裁剪改写，加"适用/不适用/决策树/references"。
2. 写 bundle：`package.json` + `cordis.patch.yml`，preset `ctf` 挂 `dsh-skill-filesystem`（custom 根）+ 现有工具；`plugin_manager install_bundle`。
3. 新会话选 CTF，验证 catalog 只有 8–10 个 CTF 入口（+ 全局常驻）；在 3 道题上跑通 triage→execute→verify。
4. 验收：标准会话 catalog 不变；CTF 题能自动选中正确类别 ≥8/10；无错误 flag 提交。

### V2：搜索/激活工具（2–3 天）
1. 写 `ctf-skill-router` 插件（按 `dsh-doc` 的 host-plugin 流程）：
   - `ctf_skill_search(query, category?)` → index.json top-k（name/描述/路径/触发/负例）；
   - `ctf_skill_use(name|path)` → 读 SKILL.md 返回正文（受 root 限制）；
   - `ctf_skill_pack(category)` → 该类别深挖包清单。
2. 把 packs/pools 纳入 index；catalog 仍 ≤14。
3. 验收：30 条题面 top-3 命中 ≥27；上下文不因搜索增长 >2k token；禁用路径穿越。

### V3：管理/验证/平台（2–3 天）
1. `ctf-board` 工具封装黑板的常用操作（或直接用 skill+CLI）；`ctf-verify` 接 reverify + 本地复现脚本。
2. `gzctf` 适配（仅比赛/授权场景）：`ctf_platform_list/download/submit/verify`，凭据只读本地；**赛后复盘不依赖平台接口**。
3. 评测脚本：固定题集 × 4 配置；生成报告（solve/成本/误选/漂移）。
4. 验收：20 个 flag 提交 0 错误；trace 完整；复盘可归因。

### V4：知识演化（长期）
- 用 ACE 思路把每题复盘写成 playbook bullet（增量、可回滚），放 `packs/<category>/playbooks/`；
- 用评测数据调 description/触发词/路由；禁止无评测的自演化。

---

## 9. 关键权衡与风险

| 权衡 | 选择 | 理由 |
|---|---|---|
| 全量常驻 vs 类别常驻 | 类别常驻 12–14 | 选择准确率与 token 成本的平衡；150 个 catalog 已在本机导致发现超时 |
| 文件读取 vs skill 工具 | V1 用 skill 工具；V2 搜索工具返回正文 | `disable-model-invocation` 技能不能被 skill 工具加载，但工具可读文件 |
| 多 agent vs 单 agent | 单 agent 默认；独立子目标才 spawn | 文献：多 agent 收益偏工程性，且上下文/成本翻倍 |
| 通用隔离 vs 合并 | CTF scope 叠加，不隔离 | 完全隔离要独立 profile；叠加不伤害通用模式 |
| 自演化 vs 稳定 | 不自动改技能 | 评测不可控；人工复盘后再改 |
| 扩展机制 vs 过度设计 | V1 只做清单+schema+模板；工具/平台插件 V2/V3 再加 | 先保证核心可跑，再开放扩展面 |

**主要风险**：
1. DSH 插件 API/版本变化 → V2 前先用 `dsh-doc` 核对当前版本，锁版本。
2. Skill provider 的 per-scope 合并语义若与预期不符（全局技能混入）→ 用 `list` 工具验证 catalog，必要时接受"叠加"。
3. 类别入口写得太"百科" → 变回大 prompt；必须限定 200 行 + 决策树。
4. 平台适配引入凭据风险 → 只读本地 session，不写入技能/trace。
5. 红/蓝包供应链风险 → 默认禁用 + 人工启用 + 来源记录。

---

## 10. 交付物清单

1. `dsh-ctf` bundle（package.json + cordis.patch.yml + README）。
2. `~/.agents/ctf-mode/` 目录（resident/packs/pools/index.json/config.yaml/boards/traces）。
3. 12 个常驻入口 SKILL.md（从现有库裁剪改写）。
4. `skillctl` 扩展：`ctf index`（生成 index.json）、`ctf add-pack`。
5. V2 插件 `ctf-skill-router`（search/use/pack 三工具）。
6. 评测脚本与复盘模板。
7. 本设计文档 + 变更记录；内核方法论见 `reports/CTF-Agent-内核方法论.md`，可复制模板见 `kernel/`。
8. `schemas/`（category / pack / tool / adapter / verifier manifest，版本化）。
9. `ctf-ext-kit/` 扩展模板 + lint / contract 测试 + `skillctl ctf new-*` 命令。
10. 扩展清单与兼容性矩阵（core 版本 ↔ extension 版本）。

---

## 11. 可扩展性设计（extensibility）

> 目标：新增一个类别 / 10 个深挖包 / 一个工具 / 一个平台适配器 / 一个验证后端，**都不改核心 preset 代码**，只填清单或加目录；扩展可独立安装、启停、卸载，坏一个不拖垮整体。

### 11.1 核心不变量（不随扩展变）

- 常驻入口 ≤14 个、catalog 只放模型可调用入口；
- 运行协议固定：triage → route → execute → verify → submit → record；
- 黑板 schema 固定：Fact / Deadend / Intent / Activity / Resource；
- 验证门固定：只有 verified fact 才能提交 flag；
- `index.json` schema 固定，扩展统一注册；
- 命名约定固定：`ctf-<category>`、`<category>-<technique>`、`ext-<kind>-<id>`。

### 11.2 扩展点矩阵

| 扩展类型 | 契约 | 放置 | 加载方式 | 回滚 | 验收 |
|---|---|---|---|---|---|
| 新类别入口 | `category.yaml` | `roots/resident/ctf-<id>/` + `extensions/categories/` | 进 resident root + index + triage 表 | 删目录 + 重生成 index | 标注题面类别命中 ≥8/10 |
| 新深挖包 | `pack.yaml` | `roots/packs/<cat>/<id>/` + `extensions/packs/` | index + 搜索工具 | 默认 disabled；删 index 项 | top-3 命中、catalog 不增 |
| 新工具 | `tool.yaml` + DSH plugin | `dsh-ctf-ext-<id>/` | 独立 bundle 的 patch 注册工具 | 卸载 bundle | schema/超时/沙箱/权限测试 |
| 新平台适配 | `adapter.yaml`（6 方法） | `dsh-ctf-ext-platform-<id>/` | 独立 bundle | 卸载 bundle | mock 平台测试 + 无凭据泄漏 |
| 新验证后端 | `verifier.yaml` | `extensions/verifiers/` | 核心验证链按序调用 | 配置开关 | 误报/漏报用例 |
| 新模型路由 | `models.yaml` | `config.yaml` | 核心读配置 | 改配置 | A/B 成本与解决率 |
| 新评测指标 | `metrics.yaml` | `traces/schema` | 评测脚本 | 删指标 | 指标可复算 |
| 新 preset 变体 | 同 core 的 `preset` 声明 | 独立 bundle 或 profile patch | 选择器切换 | 切回默认 preset | 不影响其他变体 |

### 11.3 清单契约（示例）

```yaml
# category.yaml
schema_version: 1
id: ctf-web
entry: roots/resident/ctf-web/SKILL.md
category: web
triggers: [http, url, sqli, ssrf, xss]
when_not: [pwn, rev]
reference_index: references/web.md
requires: { tools: [bash, web], models: any }
provenance: { source: ctf-skills, license: MIT }
min_core: 0.1.0
```

```yaml
# pack.yaml
schema_version: 1
id: web-sqli
category: web
path: roots/packs/web/web-sqli/SKILL.md
triggers: [sqli, sql injection, waf]
when_not: [xss]
references: [references/payloads.md]
risk: offensive-ish
invocation: user-only          # disable-model-invocation: true
provenance: { source: noor, license: MIT, hash: "sha256:..." }
min_core: 0.1.0
```

`tool.yaml` / `adapter.yaml` / `verifier.yaml` 同样带 `schema_version`、`id`、`interface`、`permissions`、`min_core`、`provenance`；工具与适配器必须声明超时、网络与凭据权限。

### 11.4 打包与加载策略

- **core bundle**（`dsh-ctf-core`）：preset + 常驻入口 + schema + 核心工具；稳定、少变。
- **skill-only 扩展**：只放目录 + 清单，不需要装 bundle；由 `index.json` 与搜索工具发现，适合类别、深挖包、playbook。
- **bundle 扩展**：需要工具/平台插件时单独打包（`dsh-ctf-ext-*`）；通过 profile patch 给 `preset-ctf` 的 `plugins` 增删 plugin id，可独立启用/禁用/卸载。
- **feature flags**：`config.yaml` 的 `extensions: {web: true, red: false, platform_gzctf: true}`；关闭即不加载。
- **失败隔离**：扩展加载失败只标记 `degraded`，核心 triage/执行仍可用；搜索工具对不可用扩展返回空并提示。

### 11.5 版本与兼容

- 所有清单带 `schema_version` 与 `min_core`；核心拒绝不兼容扩展并给出诊断。
- 语义化版本：core `0.x` 允许 breaking；`1.0` 后扩展按 major 对齐。
- `index.json` 带 `schema_version`、`generated`、`core_version`；`skillctl ctf migrate` 做清单迁移。
- 弃用策略：旧清单保留一个 minor 周期（lint 警告），两个 minor 后移除。

### 11.6 扩展开发套件

- `ctf-ext-kit/`：category / pack / tool / adapter / verifier 模板 + lint 规则 + contract 测试 + 样例扩展。
- `skillctl ctf new-category | new-pack | new-tool | new-adapter`：一条命令生成骨架、清单与测试。
- 本地/仓库 CI：lint → 安全扫描（SkillSpector）→ 契约测试 → 小型 eval；不过不许合并。

### 11.7 质量与安全门

- frontmatter 必填；description 必须带正/负触发；正文 ≤200 行；
- 扩展必须声明 `provenance`（来源 / license / hash）与 `permissions`（工具 / 网络 / 凭据）；
- 红/蓝/AI 包默认 `user-only`；C2 / 凭据攻击类不进入默认扩展集；
- 平台适配器不得写死凭据路径，不把 flag/token 写入 trace。

### 11.8 反模式

- fork 核心去改路由；把新类别硬编码进 triage；无 manifest 的散装技能；
- 工具无超时/沙箱；扩展默认 model-invocable 导致 catalog 膨胀；
- 在技能包里存 API key / cookie；用"全部常驻"替代搜索。

### 11.9 可扩展性验收（Definition of Done）

- 新增一个类别 ≤30 分钟：加目录 + `category.yaml` + index + triage 表，不改代码；
- 新增一个深挖包 ≤10 分钟：加目录 + `pack.yaml` + 重生成 index；
- 新增工具 / 平台适配器：只写独立 bundle，不改 core；
- 任一扩展卸载后核心回归通过，Standard preset 行为不变；
- 所有扩展清单通过 lint / contract / 安全扫描。

---

## 12. 待确认（影响 V1 范围）

1. CTF 模式只做 **Jeopardy**，还是也要 A/D、CRS/漏洞复现？（决定是否挂 workflow/agent-team 与 CRS 工具）
2. 运行环境：Windows + WSL2 混合，还是统一 WSL？（决定 bash/pwsh、路径、Docker 工具）
3. 模型与预算：DeepSeek 默认路由是否够用？是否需要按类别切模型（便宜模型做 triage，强模型做深挖）？
4. 是否允许比赛期联网搜索？（反作弊纪律与 `dsh-tool-web` 配置）
5. 是否要把红/蓝/AI 安全包也放进 CTF 模式的"全量可达"范围，还是只保留 CTF 类别？
6. 扩展优先级：先做哪类扩展（新类别 / 深挖包 / 工具 / 平台适配 / 验证后端）？

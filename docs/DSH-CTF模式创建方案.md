# DSH-CTF 模式创建方案（目标版）

> 本文直接给出**目标形态**与**依赖驱动的实施顺序**，不设 V1/V1.5/V2 之类产品版本。所有组件——12 入口、黑板书、多智能体控制循环、全量知识检索、验证门、评测——都是目标的一部分；先后只由依赖决定，不为"分版本"而砍功能或拆阶段。
> 上游依据：`reports/CTF-Agent-内核方法论.md`（内核不变量）、`reports/开源技能生态_学习与梳理.md`（工程模式）、`reports/DSH-CTF模式设计方案.md`（DSH 装配架构）。

---

## 0. 目标与非目标

### 0.1 目标（一次性达到）

1. DSH 新增 `ctf` preset：新会话选 "CTF" 后，模型自动看到 **12 个类别入口**（不含深挖包），按内核协议工作。
2. **全量知识可达**：500+ 开源技能不进 catalog，但模型可通过 `ctf-mode/index.json` + `skillctl ctf search/show` 自主检索并读取任意深挖包；入口仍 ≤12。
3. **状态平面**：每题一个黑板 DB（Fact/DeadEnd/Intent/Activity/Resource/Review），事实分级、租约、去重、验证记录都在里面。
4. **多智能体按需**：默认单 agent；进入并行时主控切纯编排（C1→C2），三角色（Controller/Executor/Verifier），控制循环不阻塞。
5. **验证门**：语法/自检 → 本地复现 → 平台判定三层；提交 governor；错误提交 0。
6. **评测闭环**：3 道归档题 × 4 基线配置 + 10 条路由用例，产出可复算报告。
7. 通用模式零影响（Standard/PTC/Minimal/Cordis 不变）。

### 0.2 非目标

- 不做 A/D、CRS/漏洞复现模式（只做 Jeopardy）。
- 不做技能自动演化（playbook 人工审核后更新）。
- 不做 peer swarm / 固定角色大军。
- 不把全量库装进 catalog。
- 不依赖平台在线（评测用归档题；平台适配用本机 `gzctf`，可选）。

### 0.3 硬约束（本机实测）

- `disable-model-invocation: true` 的技能模型不能自动调用、不能用 skill 工具加载 → 模型入口必须 model-invocable。
- 嵌套 `SKILL.md` 不被发现；只扫顶层 `<name>/SKILL.md` 或 `<name>.md`。
- 一次装 >100 技能导致 discovery 超时 → 常驻入口只 12 个，全量库不进扫描根。
- skill provider 是 Host+scope 合并：CTF 会话 = 全局常驻（26）+ CTF 入口（12），不是隔离；可接受。
- Windows 宿主：pwsh；Linux 分析走 `wsl`；路径不写死。

---

## 1. 内核 → 目标形态映射

| 内核件 | 目标落点 | 目标实现 |
|---|---|---|
| 路由（≤12、正负触发、triage、reroute） | `roots/resident/ctf-*/SKILL.md` + `ctf-triage` | 12 入口；四列 triage 表；失败预算化 |
| 状态（Fact 分级/DeadEnd 重开/租约/双平面） | `runs/<game>/<chal>/board.db`（blackboard CLI） | Fact/DeadEnd/Intent/Activity/Resource/Review；CAS/租约 |
| 验证（三层/证据/提交 governor） | `ctf-verify` + `reverify` + 本地复现 + `gzctf verify` | `verify.md` 证据；错误提交 0 |
| 预算（catalog/单页/refs/压缩/失败） | persona + compaction + 技能内预算段 + trace | 12 入口、≤6KB/页、6k/3k/1k 压缩、150k/45min |
| 全量知识 | `ctf-mode/index.json` + `skillctl ctf search/show` + `pools/` | 500+ 技能可检索、按需读；catalog 不增 |
| 多智能体 | DSH subagent + 黑板 + C1/C2 控制循环 | 三角色；并发 2–3；批量派发；yield 合并 |
| 技能/状态/证据契约 | `kernel/` 模板 + lint | 12/12 过 lint；facts 可审计 |
| 扩展 | manifest 契约 + 独立 bundle（设计文档 §11） | 目标里只留目录/schema；扩展不改核心 |
| 评测 | `kernel/EVAL_CASES.md` + traces | 4 基线 × 3 题 + 10 路由 |

---

## 2. 目标架构

```
L0 Host（共享，不改）
  dsh-skill · dsh-skill-filesystem · dsh-tool-skill · bash/pwsh · fs · web
  compaction · subagent（spawn/fork/control）· jobs
        │
L1 ctf preset（bundle）
  persona（内核协议/C1-C2 纪律）· agent-instructions · time-context
  + ctf-skill-filesystem（providerName=ctf-filesystem, includeDefaultRoots:false,
                           customSkillDirs=[~/.agents/ctf-mode/roots/resident]）
  + compaction group（6k/3k/1k）· delegation group（subagent）
        │
L2 技能根（12 入口，model-invocable）
  ctf-triage · ctf-web · ctf-pwn · ctf-reverse · ctf-crypto · ctf-forensics
  ctf-misc · ctf-ai-ml · ctf-malware · ctf-osint · ctf-blackboard · ctf-verify
        │
L3 知识池（不扫描、不进 catalog；可检索）
  ~/.agents/ctf-mode/pools/{ctf-skills,noor,trident,ferr079,llm-redteam,...}
  + index.json（name/category/triggers/when_not/path）
  + skillctl ctf search/show
        │
L4 状态/验证/评测
  runs/<game>/<chal>/{board.db,verify.md,artifacts/,tmp/,draft/,final/}
  traces/events.jsonl · eval 报告
        │
L5 治理
  scope allow-list · 凭据本地 · 无 C2 · 报告脱敏 · 审计 trace
```

**目标内的知识可达路径**：模型遇到入口页覆盖不到的技法 → `skillctl ctf search "<关键词>"` → 读返回路径（`read`）→ 按包内协议执行。全程不进 catalog，不需要自定义 DSH 插件。

---

## 3. 目录与文件布局（目标）

```
%USERPROFILE%\.agents\ctf-mode\
├─ config.yaml
├─ index.json                    # 全量技能索引（生成物）
├─ roots\resident\               # 12 个入口（模型可见）
│  ├─ ctf-triage\SKILL.md
│  ├─ ctf-web\SKILL.md  ... ctf-verify\SKILL.md
├─ pools\                        # 只读知识池（复制/链接现有 skill-pool）
│  ├─ ctf-skills\  noor\  trident\  ferr079\  llm-redteam\ ...
├─ runs\<game>\<chal>\
│  ├─ board.db                   # 黑板（状态平面）
│  ├─ verify.md                  # 验证证据
│  ├─ traces\events.jsonl        # telemetry
│  ├─ tmp\  draft\  final\  artifacts\
└─ schemas\                      # manifest schema（扩展用）

D:\AI_Lab\CTF_Agent\dsh-ctf-core\ # bundle 源码
├─ package.json  cordis.patch.yml  README.md  CHANGELOG.md
```

---

## 4. 12 个入口（目标，一次定义）

| # | 技能 | description 要点（正/负触发） | 首步 | 深挖来源 |
|---|---|---|---|---|
| 1 | `ctf-triage` | 新题/类别不明/需分派；不是已明确类别的深挖 | 四列路由表 + 预算 + 知识检索协议 | kernel/ROUTER_TABLE |
| 2 | `ctf-web` | HTTP/URL/源码/浏览器；不是 pwn/rev | `curl -I`、路由/参数/源码 | ctf-skills web + Noor web |
| 3 | `ctf-pwn` | ELF/内存破坏/远程服务；不是 web/rev | `file`、`checksec`、本地跑 | ctf-skills pwn + Noor privesc |
| 4 | `ctf-reverse` | 二进制/字节码/APK/固件；不是 pwn | `file`、strings、Ghidra 入口 | ctf-skills rev + Noor re |
| 5 | `ctf-crypto` | 数学/密钥/协议；不是 web 加密 | 读参数/密文/源码 | ctf-skills crypto |
| 6 | `ctf-forensics` | 磁盘/内存/流量/日志/文件；不是 web | `file`、binwalk、tshark | ctf-skills forensics |
| 7 | `ctf-misc` | 编码/沙箱/游戏/杂项（fallback，不是默认） | 识别编码/交互协议 | ctf-skills misc |
| 8 | `ctf-ai-ml` | 权重/prompt/对抗样本；不是普通 rev | 文件类型、模型加载 | llm-redteam + mukul |
| 9 | `ctf-malware` | 可疑样本/家族；不是普通逆向 | 静态优先、只分析不执行 | Noor malware + ferr |
| 10 | `ctf-osint` | 人/组织/域名/公开信息 | 搜索面/元数据 | ctf-skills osint |
| 11 | `ctf-blackboard` | 多步骤/多分支/需并行/要协作 | 初始化/claim/写 fact | blackboard skill |
| 12 | `ctf-verify` | 即将提交/结论要落地；不是执行阶段 | 三层验证 + 来源 + hash | superpowers verification |

**统一 lint**：frontmatter 六字段；description 含 `Use when…; do not use when…`；≤200 行/≤6KB；六段骨架；Output Contract；references 链接存在；无大段 payload。

---

## 5. 路由与全量知识检索

### 5.1 triage 四列表（ctf-triage）

| 类别 | 首步探针 | 一句话覆盖 | 入口 |
|---|---|---|---|
| web | `curl -I` 有响应/源码/URL | 认证/注入/SSRF/上传/反序列化/竞态 | `/ctf-web` |
| pwn | ELF+远程服务/崩溃 | 栈/堆/格式化串/ROP/沙箱 | `/ctf-pwn` |
| reverse | 二进制/字节码/APK/固件 | 静态/动态/反混淆/VM | `/ctf-reverse` |
| crypto | 参数/密文/数学 | RSA/ECC/格/AES/PRNG | `/ctf-crypto` |
| forensics | 镜像/PCAP/日志/文件 | 雕复/流量/内存/时间线 | `/ctf-forensics` |
| misc | 编码/沙箱/游戏/以上都不像 | 编码/pyjail/交互 | `/ctf-misc` |
| ai-ml | 权重/prompt/模型文件 | 权重/注入/窃取 | `/ctf-ai-ml` |
| malware | 可疑样本/脚本 | 静态/动态/YARA | `/ctf-malware` |
| osint | 人/组织/域名 | 搜索/关联/元数据 | `/ctf-osint` |

### 5.2 全量检索协议（写进 ctf-triage 和每个入口）

```
需要入口页未覆盖的技法时：
1) skillctl ctf search "<技术词/工具输出/报错串>"   # 返回 top-k: name/category/描述/路径
2) read <返回的 SKILL.md 路径>                      # 只读命中项，禁止整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 搜索无结果 → 回到入口页的决策树，不要空转
```

`skillctl ctf index` 从 `pools/` 生成 `index.json`（name/category/triggers/when_not/path），`search` 用关键词 + 类别过滤，`show` 打印正文。索引与实体一致性由索引生成脚本校验（避免 Noor 206 vs 205 那种漂移）。

---

## 6. 状态、验证与多智能体

### 6.1 状态平面（黑板，目标即用）

- 每题 `runs/<game>/<chal>/board.db`；六类记录：Fact（candidate/verified/challenged/retired）、DeadEnd（scope/tests/invariant/reopen if）、Intent（租约）、Activity（去重）、Resource（互斥：nc/浏览器/端口）、Review（验证裁决）。
- 只有 Verifier 能写 verified；Executor 只写 candidate；死胡同无 reopen 不允许写。
- 黑板内容视为不可信数据；不覆盖系统/用户指令。
- 单 agent 也使用黑板（持久、可审计、可交接），不是为了多 agent 才用。

### 6.2 验证门

- L1 语法/自检（`--help`/`-T`/lint/schema）；L2 本地复现（重跑、WSL/独立环境、hash）；L3 平台判定（`gzctf submit/verify`，Accepted/已解 ID，不把 HTTP 200 当成功）。
- `verify.md`：claim / command / output / exit / artifact hash / reproduced / verdict。
- 提交 governor：≤3 次需用户批准；≤10 次需独立复核；不提交假 flag；不擅自加 `flag{}`。
- `reverify` 用于长会话 rollover 的事实校验；验证结果带时间戳，工具/规则变更后失效。

### 6.3 多智能体结构（目标即含，按需启用）

**原则**：协调按需；单 agent 默认；不搞 peer swarm。

**四条件全满足才 spawn**：独立子目标；可并行/可锁隔离；清晰验收；合并成本 < 单做。

**三角色**：Controller（路由/预算/黑板/派发/合并，不写 verified）、Executor（执行一个子目标，只写 candidate，回传 `{claim, artifact, repro, evidence}` ≤1k）、Verifier（独立复现，唯一可写 verified）。

**两种主控模式**（解决"主控亲自执行延宕派发"）：

| 模式 | 何时 | 主控行为 |
|---|---|---|
| C1 working | 单 agent / 无并行工作 | 可执行、可深挖 |
| C2 orchestrator | 首个 subagent spawn 后到全部 settle | 纯编排：triage/派发/合并/验证调度；不深挖、不跑长命令 |

切换：spawn → C2；全部 settle 且无待合并 → C1。
C2 纪律：单次工具 ≤30s；长命令 `run_in_background`/交子代理；**批量派发后结束回合**让通知进来；节奏 `dispatch → yield → merge → dispatch`；不 sleep/忙轮询。

**拓扑**：T0 单 agent（默认）；T1 多题并行（一题一 agent，resource 锁）；T2 题内 2–3 个独立分支；T3 控制-执行-验证（Verifier 独立）。不做同目标竞速、固定角色大军。

**通信/合并**：原生消息只用于解阻塞/改计划/冲突；黑板承载状态；合并只认 verified facts + artifacts；冲突标 challenged，以可复现证据裁决。

**资源/上下文**：并发 2–3（上限 4）；spawn（全新）用于独立子目标，fork 只用于需父上下文的延续；每个子代理只带 1 入口 + 必要 references。

**DSH 落点**：preset 的 delegation group（subagent spawn/fork/control）；黑板书用 `multi-agentcollaboration-blackboard` 的 CLI；`dsh-tool-jobs` 跑后台长任务；不引入 agent-team（目标不需要任务 DAG）。

**控制面指标**：dispatch latency、controller busy ratio、subagent idle、handoff loss、重复工作率；C2 无收益则回 C1。

---

## 7. 上下文预算与 telemetry

| 项 | 目标 |
|---|---|
| catalog | 12 入口；description ≤200；目标 ≤1.5k tokens |
| 单页 | ≤200 行/≤6KB；references ≤2 个/次 |
| 工具结果 | pruner 8192/4096/1024；大输出落文件 |
| 压缩 | 窗口 70–80%；压缩后回读黑板 verified 摘要 |
| 子代理 | 结构化结果 ≤1k tokens；不回传全轨迹 |
| 预算 | 每题 150k tokens/45min（config 可调；超限降级） |
| telemetry | `traces/events.jsonl`：skill_load、search、tool_call、fact、deadend、verify、submit、token/step |

---

## 8. 配置、persona 与 bundle

### 8.1 config.yaml

```yaml
catalog: { max_resident: 12, description_max: 200 }
budgets:
  per_challenge: { tokens: 150000, minutes: 45 }
  phase_pct: { intake: 10, triage: 5, route: 5, execute: 60, verify: 10, submit: 5, record: 5 }
  compaction: { threshold_chars: 8192, head: 4096, tail: 1024 }
state:
  backend: blackboard
  db: "%USERPROFILE%/.agents/ctf-mode/runs/<game>/<chal>/board.db"
knowledge:
  index: "%USERPROFILE%/.agents/ctf-mode/index.json"
  pools: "%USERPROFILE%/.agents/ctf-mode/pools"
verification:
  levels: [syntax, local_repro, platform]
  governor: { review_after: 3, user_approval_after: 3, max_attempts: 10 }
  reverify: true
telemetry: { events: [skill_load, search, tool_call, fact, deadend, verify, submit] }
governance:
  scope_allowlist: []
  web_search: false
  credentials: "%USERPROFILE%/.gzctf/session.json"
```

### 8.2 persona（短）

```text
You are a CTF solving agent. Follow the kernel:
- New challenge: load ctf-triage first; classify before acting.
- Use the 12 entries; for deeper techniques run `skillctl ctf search` then read the hit.
- Maintain the blackboard: candidate facts/dead ends; only verifier writes verified.
- Verify: syntax → local reproduction → platform verdict; HTTP 200 is not Accepted.
- Submit only verified flags; respect scope; never write credentials/flags to notes.
- Single agent: work directly. Once subagents are active (C2): orchestrate only,
  dispatch in batches, yield to collect results, never block on long commands.
```

### 8.3 bundle（目标草稿）

同前：`preset-ctf` + persona/agent-instructions/time-context + pwsh/bash/fs/fs-search/jobs + ctf-skill-filesystem(custom root) + compaction(6k/3k/1k) + delegation(subagent-control/spawn/fork) + ask-user/todo/web/present；`tool-skill` 由 Host 提供不重复挂。

安装：`plugin_manager install_bundle` → `list_bundles`/`list_plugins` → 新会话选 CTF → 校验 catalog=12+26、Standard 不变。

---

## 9. 评测（目标验收）

- **题集**：3 道归档题（web/pwn/rev，本地有附件与已知 flag），每题产出 `final/flag.txt`、`verify.md`、`writeup.md`、`traces/events.jsonl`、`board.db`。
- **路由**：10 条标注题面，首选 ≥8/10，forbidden 命中 0。
- **配置矩阵**（基线对照，不是版本）：C0 裸 agent；C1 +12 入口；C2 +知识检索；C3 +黑板+验证门。同题 ≥3 次。
- **指标**：solve、first-solve、tokens/$、轮次、错误提交、上下文事件（压缩/峰值/事实保留/漂移）、验证拦截、dispatch latency、controller busy、handoff loss。
- **门**：错误提交 0；验证门至少拦截 1 个人为注入的假阳性；上下文峰值 ≤70%；压缩后 5 条早期 fact 可检索；12/12 lint；Standard 回归不变；C3 solve ≥ C0。
- **多 agent 采纳门**：C2 相对 C1 solve 不降且时间/token 更优，或验证拦截显著增加；否则保持按需。

---

## 10. 实施顺序（依赖驱动，不是产品版本）

| 阶段 | 任务 | 产出 | 依赖 | 检查 |
|---|---|---|---|---|
| P0 基础 | T1 目录/config/schema；T2 模板落地；T3 index 生成器与 `skillctl ctf` 命令骨架 | `ctf-mode/` 骨架、`index.json`、`skillctl ctf index/search/show` | — | 目录可扫；index 与实体一致 |
| P1 入口 | T4 12 个入口 SKILL.md（triage/verify 先写） | 12×SKILL.md | T2 | lint 12/12 |
| P2 装配 | T5 bundle + provider；T6 安装/冒烟 | `dsh-ctf-core/`、CTF preset | T1 | 新会话 CTF；catalog=12+26；Standard 不变 |
| P3 状态/验证 | T7 黑板接入（每题 DB、CLI 协议、事实分级）；T8 verify 门 + reverify + governor；T9 gzctf 适配 | board.db 规范、verify.md 模板、`ctf-verify`、平台命令封装 | T4,T5 | 一题可写/读 fact；验证拦截注入假阳性 |
| P4 知识可达 | T10 pools 落位 + 索引全量生成；T11 triage/入口接检索协议 | pools、index.json、检索协议 | T3,T4 | 30 条查询 top-3 ≥27；catalog 不增 |
| P5 多智能体 | T12 C1/C2 协议 + Verifier 独立复现；T13 控制面指标 | persona 纪律、验证报告、C1/C2 对照 | T7,T8 | dispatch latency/busy/idle 有数据；C2 无收益则回 C1 |
| P6 评测/交付 | T14 3 题 × 4 基线；T15 路由 10 例；T16 验收报告/CHANGELOG/README | 评测报告、目标验收、文档 | 全部 | 第 9 节门全过 |

**关键路径**：P0→P1→P2→P3→P4→P5→P6；总工作量约 5–7 个 agent 工作日。所有任务都是目标的一部分；没有"先砍掉再补"的版本。

---

## 11. 风险与降级

| 风险 | 对策 |
|---|---|
| provider 合并语义不符 | 先只挂 `dsh-skill-filesystem`；catalog 校验；必要时掛 `dsh-skill`+`tool-skill`（接受 shadow 风险） |
| skill 工具不可用 | 文件读取 + index（模型可 `read`）；bundle 再挂 tool-skill |
| 12 入口仍过多 | 合并 malware→reverse、osint→misc；保 ≤8 |
| 黑板 CLI/环境问题 | 文件镜像（facts.jsonl）作为只读旁路；不引入第二事实源 |
| 检索索引漂移 | index 生成脚本 + 校验（数量/路径/name 一致）；CI 式检查 |
| 主控 C2 延宕 | 批量派发 + 结束回合 + jobs；指标不达标回 C1 |
| 上下文超预算 | 提前压缩、references 减半、子代理隔离、结果截断更激进 |
| 插件/DSH 版本变化 | `dsh-doc` 核对；bundle 锁版本；退纯声明式 |

---

## 12. 交付物与第一步

**交付物**：`dsh-ctf-core/` bundle；`~/.agents/ctf-mode/`（12 入口、pools、index、runs、schemas、config）；`skillctl ctf`；3 题产物 + 4 基线评测报告 + 验收报告。

**第一步（可立即执行）**：
1. 建 `ctf-mode` 目录 + `config.yaml` + `index.json` 生成器。
2. 用 `kernel/SKILL_TEMPLATE.md` 写 `ctf-triage` 与 `ctf-verify`（最关键两个）。
3. 写 `dsh-ctf-core/cordis.patch.yml` 并安装，确认 CTF 会话 catalog。
4. 写其余 10 个入口；lint。
5. 接黑板 + 验证门；跑 3 题；出报告。

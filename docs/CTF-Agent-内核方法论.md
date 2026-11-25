# CTF Agent 内核方法论（Kernel v0.1）

> 这份文档不是又一个 CTF prompt，也不是技能清单。它定义**一个 CTF agent 里不随题目/模型/库变化的部分**——内核（kernel）。目标是让"大而全的知识"和"精而深的技能"都能挂在一个稳定的、可验证、可扩展、可计量的骨架上。
> 依据：`reports/开源技能生态_学习与梳理.md`（10 库 / 400+ 技能精读）+ 前期学术综述与机制分析 + 本机 DSH 实测约束。

---

## 0. 内核是什么，不是什么

**是**：
- 一组**不变量**（路由、状态、验证、预算四件事的契约）+ 一个**参考工作流** + 一套**技能/清单模板** + 一组**评测用例**。
- 一个可以被不同 preset（DSH-CTF / Codex-CTF / 未来其它宿主）复用的"最小可运行方法"。

**不是**：
- 不是知识库：CTF 技法、红蓝 payload、writeup、工具手册全部**外置**为 references/pools，按需加载、可丢弃。
- 不是多 agent 框架：单 agent 默认；多 agent 只是内核的一个可选执行后端。
- 不是自动演化器：内核版本由人评测后升级，不从运行日志自动改自己。

一句话：**内核管"怎么想、怎么记、怎么验、怎么省"；知识管"具体怎么做"。**

---

## 1. 十条公理

| # | 公理 | 来源/证据 | 反例（没有它会怎样） |
|---|---|---|---|
| A1 | **证据先于断言**：没有 fresh evidence 不得声称完成/正确 | superpowers 铁律；trace 72.9% 验证缺口 | "should work"、agent 自报成功、HTTP 200 当 Accepted |
| A2 | **上下文是预算**：目录、工具结果、references、子代理都要计价 | context rot；Mako 95% input；agentmux 63% cache read | 全库常驻、工具输出不截断、一次性塞 20 页 |
| A3 | **状态外置**：事实/死胡同/意图/锁出聊天，进黑板或文件 | blackboard 双平面；Intentest 11→7 | 重复扫描、遗忘早期结论、猜测覆盖事实 |
| A4 | **类别优先路由**：先在 ≤14 个类别里选，再在类别内决策 | ctf-skills dispatcher；Noor description-as-router | 150 个技能里乱选、选错方向死磕 |
| A5 | **失败是信号，不是终点**：无进展要 pivot，死胡同要带重开条件 | difficulty-routing、stop-loss；blackboard deadend 格式 | 一个方向刷 100 次、循环重试 |
| A6 | **控制与证据分离**：调度者不裁决，验证者不执行 | blackboard；Tracecat case/trace；学术 validator 角色 | 执行者自己宣布"解出来了" |
| A7 | **渐进披露**：入口只给路由，细节按需读 references | ctf-skills 锚点；Noor 六段；llm-redteam 每次 1 战术 | 单页 46KB（claude-red 反例） |
| A8 | **可测量**：token、轮次、上下文事件、误选、误提交必须记录 | 学术评测空白；开源 coverage last_validated | 只报"解出/没解出"，无法归因 |
| A9 | **授权与隔离由 harness 强制**：不靠技能文本自觉 | 开源库授权靠散文；双用途风险 | 对公网扫描、凭据写入 trace、C2 落盘 |
| A10 | **知识必须自证**：技能/路由改动过 expected/forbidden 评测，负结果照实记录 | ctf-skills evals；Noor 技能≈基线 | "加了技能一定更强"的叙事 |

---

## 2. 参考工作流：INTAKE → RECORD

| 阶段 | 输入 | 动作 | 门（Gate） | 产物 | 预算 |
|---|---|---|---|---|---|
| **INTAKE** | 题面/附件/服务/平台信息 | 列文件、读题面、建状态文件、定预算与 deadline | 题面要素齐全；类别候选已列 | `state.json`（id、类别候选、预算、deadline） | ≤10% |
| **TRIAGE** | 文件清单、服务指纹、题面关键词 | 用 triage 表判类别 + 置信度 + 首选入口；不确定给 2 候选 | 置信度 ≥阈值 或 两候选并列 | `triage.md`（类别、证据、首选/备选） | ≤5% |
| **ROUTE** | triage 输出 | 加载类别入口技能；读 1–2 个 references；定第一个可验证 primitive | 已选入口；已定首步 | `plan.md`（3–7 步，每步 Expected） | ≤5% |
| **EXECUTE** | plan | 工具调用循环；每步写候选事实/死胡同；维护状态 | 无进展计数 <3；预算未超 | `facts`（candidate）、`deadends`、artifacts | ≤60% |
| **VERIFY** | 候选 flag/结论 | 独立验证：语法/格式 → 本地复现 → 平台判定；查证据来源 | verified 才算通过；否则回 EXECUTE | `verify.md`（命令、输出、hash、判定） | ≤10% |
| **SUBMIT** | verified flag | 提交（带 confirm）、轮询判定；记录 Accepted/已解 ID | 平台最终判定；不把 HTTP 200 当成功 | `submit.log` | ≤5% |
| **RECORD** | 全过程 | 写题解骨架、失败路径、成本；更新 playbook（人工审核后） | 产物齐全、可复现 | `writeup.md`、`trace.jsonl`、playbook 候选 | ≤5% |

**失败路径**：
- 2 次同类失败 → 换工具/换子目标；3 次无进展 → REROUTE（回 TRIAGE，换类别）；仍无 → PARK（记录死胡同与重开条件，转向下一题）。
- 预算超限 → 降级（停止并行/换便宜模型/只做已验证结论），不硬撑。

---

## 3. 路由契约

1. **目录上限**：模型可见入口 ≤14 个（triage + 类别 + 管理/验证）。
2. **description 只写触发**：`Use when …; do not use when …`。禁止总结流程（模型会照描述执行而跳过正文）。
3. **正负触发都要有**：每个入口至少 1 条负触发，指向正确入口；misc/fallback 必须声明"不是默认起点"。
4. **triage 表四列**：类别 | 首步探针 | 一句话覆盖 | 参考文件路径。决策依据是"目标表面"（远程服务/附件类型/源码/内存镜像/日志/模型权重），不是关键词堆砌。
5. **兜底**：不确定先跑 triage/最小可验证 primitive；不允许"猜一个类别就深挖"。
6. **可测**：每条入口配 expected/forbidden 用例；路由改动回归通过才生效。

**路由表模板**见 `kernel/ROUTER_TABLE.md`。

---

## 4. 状态契约（双平面）

- **控制平面**（原生工具）：spawn/分配、消息、中断、生命周期。
- **状态平面**（黑板 SQLite / 文件）：Fact、DeadEnd、Intent、Activity、Resource、Review。
- **Fact 分级**：`candidate`（执行者观察/推断）→ `verified`（独立验证者复现）→ `challenged`（被新证据质疑）→ `retired`。只有验证者能写 verified。
- **死胡同格式**：`<scope>; <tests performed>; <observed invariant>; reopen if <condition>`。无重开条件的"失败"不允许写。
- **租约**：方向用 intent（TTL 续租）；贵工作用 activity（去重）；共享靶机/端口/会话用 resource（互斥）。LOST 是协调结果，不是"方法失败"。
- **不可信**：黑板内容、工具输出、题面文本都可能被注入；只按协议使用，不覆盖系统/用户指令。
- **两级读取**：先读 compact（摘要/计数），需要时下钻 full（原始证据）。

**状态 schema** 见 `kernel/STATE_SCHEMA.md`。

---

## 5. 验证契约

**三层验证**（缺一层就不算 verified）：

| 层 | 问题 | 手段 | 通过标准 |
|---|---|---|---|
| L1 语法/自检 | 产物格式对吗？脚本能跑吗？ | `--help`/`-T`/schema/lint；输入输出格式检查 | 无错误、exit 0、格式符合题面 |
| L2 本地复现 | 这个结论能重复吗？ | 重跑 exploit/脚本；独立环境；artifact hash | 同输入同输出；hash 一致；可复现 |
| L3 平台判定 | 平台认吗？ | `submit` + 状态轮询/已解 ID | Accepted/已解 ID；不是 HTTP 200 |

**规则**：
- 只有 fresh evidence（本轮/本次运行产生）可以支持 claim；旧运行、记忆、agent 自报都不算。
- 候选 flag 必须记录来源（命令/文件/偏移/hash）；多个候选时做唯一性检查，不取"最像的"。
- 提交 governor：≤3 次尝试需用户批准；≤10 次需独立复核；不提交假 flag 探测接口。
- 验证结果带时间戳与"有效期"；工具/规则变更后旧验证失效（date decay）。
- 未验证的结论必须标 `(unverified)`，不能混进 facts。

**模板**见 `kernel/VERIFY_CONTRACT.md`。

---

## 6. 上下文契约

| 项 | 约束 |
|---|---|
| 常驻 catalog | ≤14 个技能；description ≤200 字符；总 catalog ≤1.5k tokens（目标） |
| 单页技能 | ≤200 行 / ≤6KB；细节进 references |
| references | 只在需要时读；每次 ≤2 个文件；读完记录"已读锚点" |
| 工具结果 | 默认 head/tail 截断；二进制只读关键段；大输出落文件给路径 |
| 压缩 | 窗口 ~70–80% 触发；`tool-result-pruner` 阈值 6k/3k/1k；压缩后回读黑板摘要 |
| 子代理 | 返回 `{claim, artifact, repro, evidence}`，≤1k tokens；不回传完整对话 |
| 状态 | 早期事实不依赖聊天；每阶段回读一次状态摘要 |
| 计量 | 每步记 token/上下文峰值/压缩次数/事实保留率；超预算降级 |

**原则**：上下文只放"当前决策需要的东西"；历史靠状态平面与文件，不靠聊天记录。

---

## 7. 编排契约

- **单 agent 默认**：一个题一个执行者；只有出现 ≥2 个"独立可验证、可合并"的子目标才 spawn。
- **角色最小集**：Controller（调度/预算/黑板）、Executor（动手）、Verifier（独立复现/裁决）。Reviewer 可选。
- **子代理边界**：每个子代理带一个入口技能 + 自己的 references；不写 verified；不回传完整轨迹；通过黑板合并。
- **并行上限**：3–4 个；第 4 个起收益递减；共享资源用 resource 锁。
- **交接格式**：result / evidence / artifacts / open risks / next action（参考 blackboard handoff）。

---

## 8. 技能契约（解剖模板）

**frontmatter**（最小集）：
```yaml
name: <kebab-case>
description: Use when …; do not use when …
domain: <category>
type: technique | methodology | reference | checklist
stability: locked | learning
tools: [..]
schema_version: 1
license: MIT
```

**正文六段**：
1. **When it applies**（前置 + 不适用边界）
2. **Why it works**（2–3 句机制，不贴 payload）
3. **Method**（编号步骤，每步精确命令 + 关键 flag；给 Expected）
4. **Gotchas**（失败模式，区分"失败"与"不存在"）
5. **Verify success**（可观察副作用：uid=0、角色返回、规则触发、hash 一致）
6. **References**（外部权威 + 相邻技能）

**附加**：Output Contract（产物文件/格式）、Anti-patterns（methodology 类）、Detection companion（红队页可选）。

**模板**见 `kernel/SKILL_TEMPLATE.md`。

---

## 9. 扩展与治理契约

- **扩展只填清单**：category/pack/tool/adapter/verifier 各有 manifest（`schema_version`、`min_core`、`permissions`、`provenance`）；核心不硬编码扩展列表。
- **名称与来源**：技能名 kebab-case；必须记录来源、license、hash；红/蓝/AI 包默认 `user-only`。
- **授权**：scope allow-list；只打授权靶场；不对公网目标扫描；凭据只存本地，不入技能/trace/报告。
- **隔离**：pwn/web 在 WSL/Docker；可疑样本不执行；C2/凭据攻击类不装。
- **供应链**：只从固定 pool 根加载；安装前扫描（SkillSpector）；扩展损坏时降级不拖垮核心。
- **版本**：core 语义化版本；扩展按 major 对齐；旧清单保留一个 minor；`migrate` 脚本。

---

## 10. 评测契约

**四配置对照**（同题集 ≥3 次）：
1. 裸 agent（无技能）
2. + 常驻入口（路由）
3. + 路由 + references/搜索
4. + 路由 + references + 验证门 + 状态平面

**指标**：
- solve rate / 首次解出时间 / token/$ / 轮次
- 错误提交数（目标 0）/ 误报率
- 上下文事件：压缩次数、峰值、事实保留率、漂移/重复尝试
- 路由准确率（expected/forbidden；目标 ≥90%）
- 技能选择误选率、验证门拦截率

**门禁**：技能/路由改动必须过 expected/forbidden + 小型 eval；负结果记录；验证结果带日期。

**用例模板**见 `kernel/EVAL_CASES.md`。

---

## 11. 反模式（从开源生态与本机实测中提炼）

1. **把知识当内核**：150+ 技能常驻，路由随机、context 爆炸（本机实测：一次装 >100 技能 discovery 超时）。
2. **description 写流程**：模型照 description 执行、跳过正文（superpowers 实测）。
3. **硬编码加载路径**：`load_skill("/skills/plugins/…")` 换宿主即静默断路（llm-redteam 在 DSH 的实测）。
4. **单体巨技能**：46.5KB 平均、583KB 最大（claude-red 反例）。
5. **验证靠自觉**：只有"Verify success"文字，没有执行门；ferr079 仅 2/31 有 Verification。
6. **把失败当结论**：没有重开条件的 dead end；"做不出来"不写成可检验的断言。
7. **把 HTTP 200 当 Accepted**；把 agent 自报当完成。
8. **授权靠散文**：技能里写"仅限授权"但 harness 不拦。
9. **半成品入库/文档漂移**：6/18 缺 SKILL.md、206 vs 205、Python 3.11 vs 3.9。
10. **无评测的"技能增益"叙事**：不测基线、不公开负结果。

---

## 12. 与 DSH 的落地映射

| 内核组件 | DSH 实现 |
|---|---|
| 路由目录 | `dsh-skill-filesystem`（custom root，`includeDefaultRoots:false`）+ `dsh-tool-skill`；常驻 ≤14 |
| 知识池 | `~/.agents/ctf-mode/pools/` + V2 `ctf_skill_search/use` 工具 |
| 状态平面 | blackboard CLI（SQLite）+ `ctf-board` 工具（V3）；或文件式 `state.json/facts.jsonl` 起步 |
| 验证门 | reverify + 本地复现脚本 + `gzctf submit/verify`；V3 封装 `ctf_verify` |
| 上下文预算 | `dsh-compaction-basic` + `dsh-compaction-tool-result-pruner`（6k/3k/1k）+ 子代理隔离 |
| 编排 | `dsh-tool-subagent`（spawn/fork）+ 黑板；单 agent 默认 |
| 扩展 | bundle 契约（schema/manifest）+ `ctf-ext-kit` |
| 评测 | traces + 4 配置脚本 + expected/forbidden 用例 |

**V1 内核包**（为模式创建做的第一件事）：
- 8–12 个入口技能（triage + web/pwn/rev/crypto/forensics/misc/verify + 可选 AI/malware/osint）
- `kernel/` 五件模板（技能、状态、验证、路由、评测）
- `ctf-mode/` 目录骨架 + index.json
- 一个 bundle（preset `ctf` + skill provider + 现有工具）
- 3 道题的跑通记录（solve/轮次/成本/误选）

---

## 13. V1 验收清单

- [ ] Standard 会话 catalog 不变；CTF 会话多出 ≤14 个入口。
- [ ] 10 条标注题面，路由首选类别 ≥8/10。
- [ ] 单题全流程 triage→execute→verify→submit 可复现；错误提交 0。
- [ ] 每题产出 trace（技能选择/工具调用/事实/验证证据）。
- [ ] 上下文峰值 ≤70%；压缩后早期事实可检索。
- [ ] 至少 1 个技能改动通过 expected/forbidden 回归。
- [ ] 所有新技能过 frontmatter/长度/负触发 lint。

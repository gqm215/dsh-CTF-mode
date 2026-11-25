# CTF 模式多智能体协议（C1 / C2）

> 内核依据：`reports/CTF-Agent-内核方法论.md` §多智能体；本文件是 CTF 会话内可执行的规则。
> 默认单 agent；并行按需；不做 peer swarm、不做固定角色大军、不做同目标竞速。

## 1. 触发条件（四条件全满足才 spawn）

1. 独立子目标（可单独验收，不依赖主控未定的决策）；
2. 可并行或可用锁隔离（不会同时写同一 artifact/端口/DB 记录）；
3. 验收清晰（能写成一句可观察的成功判据）；
4. 合并成本 < 单做成本（结构化结果 ≤1k tokens，不回传全轨迹）。

只满足 1–3 而不满足 4 → 主控自己做。不要为了"看起来并行"而 spawn。

## 2. 角色与权限边界

> CTF 抢速度时，"验证者"基本不需要常设：flag 对错由平台判定，本地复现只在通道不可用时兜底。
> 常设的第三个角色是**监察员（Supervisor / Auditor）**：不判 flag 对错，只管行为纪律——
> 过程中观察督导（发现违规倾向就喊停/提醒），失败或违规时追责检查（出审计报告）。
> 实现：`python ~/.agents/ctf-mode/bin/ctf-audit.py --game G --chal C [--session <id>]`。

| 角色 | 职责 | 可写 | 不可写 |
|---|---|---|---|
| Controller（主控） | triage、预算、派发、合并、安排监察 | intent/activity/resource、candidate fact、dead end | `verified` fact（平台判定除外）；不亲自深挖（C2 期间） |
| Executor（子代理） | 执行子目标，回传 `{claim, artifact, repro, evidence}` | candidate/dead end/activity；**执行证据确凿时快车道提交**（`--auto --evidence`） | 猜测/探测提交；同答案重复提交；改模式工具 |
| Supervisor / Auditor（监察员，独立上下文） | 观察行为纪律：scope 越界、探测/重复提交、凭据外泄、flag 进日志、擅自改工具、干扰他人进程、虚假成功声明；失败时出追责报告 | `audit.md`、Review 记录、向主控/用户发告警 | 不判 flag 是否真实（那是平台的判定）；不阻塞快车道提交；不亲自解题 |
| Re-checker / 复核员（可选，非常设；通道不可用时才 spawn） | 平台判定不可用/缓慢时做独立复现兜底 | `verified`/`rejected` fact、verify.md evidence | 不为"再确认一次"拖慢已 Accepted 的题 |

- 子代理只带 1 个入口技能 + 必要 references；spawn（全新上下文）用于独立子目标，fork 仅用于需要父上下文的延续。
- 并发 2–3（硬上限 4）。一个 challenge 同时最多 1 个 submit owner。

## 3. C1 / C2 两种主控模式

| 模式 | 何时 | 主控行为 |
|---|---|---|
| C1 working | 单 agent，或无并行子任务 | 可执行、可深挖、可跑长命令 |
| C2 orchestrator | 从第一次 spawn 起，到全部 settle 且合并完成为止 | 纯编排：triage/派发/合并/监察调度；不深挖、不跑长命令 |

切换：`spawn → C2`；全部 settle 且无待合并 → `C1`。

C2 纪律：
- 单次工具调用 ≤30s；长命令一律 `run_in_background`（jobs）或交子代理。
- 批量派发（一次消息里多个 spawn）→ 结束回合 → 等通知 → merge → 再派发。节奏：`dispatch → yield → merge → dispatch`。
- **绝不阻塞式等待**：`wait_agent` 单次超时上限 120s（不要填几分钟/几十分钟）；等不到就查状态、给子代理发消息、或结束回合让通知自己回来。
- 子代理超过 5 分钟没有任何输出：发状态询问或 stop/替换，并在黑板记录 stall；不要为了等它把主控挂死。
- 不 sleep、不忙轮询、不反复 list 子代理；主控任何时刻都要能回答"现在进展到哪"，做不到就说明编排坏了，立即收敛或降级为 C1；用户可见进度至少每 ~2 分钟一次（有实际状态变化才报）。
- C2 无收益（见 §7 采纳门）→ 回到 C1。

## 4. 拓扑（按需选择，不是全用）

- T0 单 agent：默认。0–1 个子目标。
- T1 多题并行：一题一 agent；用 resource 锁隔离 nc/浏览器/端口；主控只做路由与合并。
- T2 题内多分支：同一题 2–3 个独立假设；每个分支一个 Executor；`claim-activity` 去重（如 `decompile:chall`）。
- T3 控制-执行-监察：Controller 派 Executor 解题，另派独立 Supervisor 观察纪律（scope/凭据/flag 落点/重复提交/擅自改工具/进程干扰）；平台 Accepted 由 `checker-platform` 直接记 verified，不设常设验证者。

不做：同目标多 agent 竞速；固定角色大军；带 C2/外联的自动化。

## 5. 通信与合并

- 原生消息只用于解阻塞、改计划、冲突裁决；状态一律走黑板（board.db），不靠对话记忆。
- **Accepted 通知是一等事件**：执行层拿到 ACCEPTED 立即写 `ACCEPTED.txt`/`final/flag.txt`、黑板记 verified（actor `checker-platform`）、向主控发一行 `ACCEPTED <chal> <flag> <attempt>`，主控直接并入结果，不再等待验证。
- 合并只认 verified facts + artifacts（路径 + sha256）；verified 的两个来源等价：平台 Accepted（actor `verifier-platform`）或平台不可用时的独立复核复现。
- 冲突：两条相反结论 → 都标 `challenged`，以可复现证据裁决；无法裁决的记录死胡同与 `reopen if`。
- 子代理回传格式（≤1k tokens）：`claim / artifact / repro / evidence`；Accepted 时额外一行 flag 原文（展示用）；不通过时明确 `blocked` 与原因。

## 6. 资源与上下文

- spawn 的子代理只带任务需要的技能与 references（1 入口 + ≤2 references）；不用全量 catalog 复制。
- 主控压缩后必须回读黑板 verified 摘要（防事实漂移）。
- 子代理 token 预算单独计；超预算先降级（缩短探索）再回报 blocked。

## 7. 控制面指标与采纳门

用 `python ~/.agents/ctf-mode/bin/ctfboard.py log --event <name> --data '<json>'` 记录：
`dispatch`（派发时间戳/子任务数）、`settle`（结果时间戳）、`merge`、`c2_turn`、`handoff`（交接丢失/重复）。

指标：
- dispatch latency = settle − dispatch（按子任务）；
- controller busy ratio = C2 期间主控执行类工具调用 / C2 总步数（目标 <0.2）；
- subagent idle = 派发后等待合并的空转时长；
- handoff loss = 合并时缺失的 artifact/事实条数（目标 0）；
- duplicate work rate = 重复 activity 命中 / 总 activity（目标 <0.1）。

### 7.1 监察指标（行为纪律，由 `ctf-audit.py` 产出）

- `breach_count` / `warn_count`（按 code：PROVENANCE / GOVERNOR / IDEMPOTENCY / ACCEPTANCE /
  FLAG_HYGIENE / CREDENTIAL_HYGIENE / TOOLING_INTEGRITY / CONDUCT）；
- scope 违规数（越出题目授权目标）、探测式提交数（目标 0）；
- 擅自改模式工具的会话数（目标 0）、干扰他人进程（目标 0）；
- 虚假成功声明数（无平台 verdict 却声称已解，目标 0）；
- 失败追责：每个失败题出 1 份 `audit.md`，注明是"能力失败"还是"纪律失败"及证据。

采纳门：C2 相对 C1 solve 不下降，且（时间或 token 更优，或监察拦截显著增加）；否则保持按需单 agent。

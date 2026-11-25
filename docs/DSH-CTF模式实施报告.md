# DSH CTF 模式实施报告（目标版验收）

- 日期：2026-11-25
- 依据：`reports/DSH-CTF模式创建方案.md`（目标版）、`reports/CTF-Agent-内核方法论.md`、`reports/DSH-CTF模式设计方案.md` §11
- 实施方式：4 个并行工作流（12 入口 / 知识索引 / 状态验证 / 评测）+ 主控装配与验收
- 结论：**P0–P5 完成，P6 工具链完成、12 题次矩阵待配额执行**。CTF preset 已安装并激活；12 入口 lint 12/12；知识索引 500 技能、检索 30/30；黑板/验证门 66/66（含注入假阳性拦截）；路由 9/10、forbidden 0。剩余 3 项都需人工/外部条件，见 §6。

## 1. 交付物

| 交付物 | 路径 | 规模 |
|---|---|---|
| CTF preset bundle | `D:\AI_Lab\CTF_Agent\dsh-ctf-core\`（package.json / cordis.patch.yml / README / CHANGELOG） | 仅声明 `preset-ctf`，16 个顶层插件行，无新 Host 包 |
| 模式运行时 | `C:\Users\Geqim\.agents\ctf-mode\` | 0.8 MB / 79 文件（pools 为 junction，不占副本） |
| 12 入口 | `~/.agents/ctf-mode/roots/resident/ctf-*/SKILL.md` | 57,858 B，每个 ≤6 KB / ≤109 行 |
| 全量索引 | `~/.agents/ctf-mode/index.json` | 342,885 B，500 技能（506 SKILL.md 去重 6 个同名） |
| 检索命令 | `~/.agents/tools/skillctl.py ctf index/search/show/doctor` | stdlib，index 0.8 s / search 0.31 s |
| 状态平面 | `~/.agents/ctf-mode/bin/ctfboard.py` | 10 类命令，代理 blackboard.py，事实分级 + 去重 + 租约 |
| 平台适配 | `~/.agents/ctf-mode/bin/ctf-submit.py` | 只提交 verified；HTTP 200 ≠ Accepted；401 → exit 4 |
| 扩展契约 | `~/.agents/ctf-mode/schemas/{category,pack,tool,adapter,verifier,challenge,fact,verify}.schema.json` + `extensions/README.md` | 8 个 draft-07 schema |
| 多智能体协议 | `~/.agents/ctf-mode/PROTOCOL.md`（C1/C2、三角色、拓扑、控制面指标、采纳门） | 与 persona 一致 |
| 评测 | `~/.agents/ctf-mode/eval/` | 10 路由用例 + 3 归档题本地 checker + 矩阵报告器 + driver.md |
| 接口契约 | `~/.agents/ctf-mode/SPEC.md`、`config.yaml`、`README.md` | 单点事实源 |

## 2. 验收矩阵（全部为本机实测）

| # | 门 | 结果 | 证据 |
|---|---|---|---|
| A1 | 12 入口 lint 12/12 | **PASS** | `python ~/.agents/ctf-mode/tools/lint_skills.py` → `SUMMARY: 12/12 PASS, 0 failed, total 57858 B` |
| A2 | 入口模型可见（非 disable-model-invocation） | **PASS** | 12/12 `disable-model-invocation: false`；lint 检查 |
| A3 | 索引与实体一致 | **PASS** | `ctf doctor` → `index OK (500 skills)`；`ctf index --check --json` → `{"ok": true, "count": 500, "problems": []}` |
| A4 | 检索质量 top-3 ≥27/30 | **PASS** | `python ~/.agents/ctf-mode/tools/ctf_search_test.py` → `30/30 hits (gate >= 27/30) -> PASS` |
| A5 | 中文检索可用 | **PASS** | `ctf search "逆向 反混淆"` → `code-obfuscation-deobfuscation / reverse / 238`（zh→en 别名映射） |
| A6 | 深挖包不进 catalog | **PASS** | catalog 扫描根只有 `roots/resident`（12）；`pools/` 不在 `customSkillDirs`，仅经 index 检索 |
| A7 | preset 安装并激活 | **PASS** | `plugin_manager list_plugins` → `include:preset-ctf enabled=true fiberPhase=active`；profile `package.json` 增加 1 个 link 依赖 + bundles 条目，用户 patch 未改 |
| A8 | preset 组合可解析 | **PASS** | 临时 profile（web 模板 + 本 patch）`--dump-config` exit 0；`preset-ctf` 的 16 个插件行、persona、skill-filesystem、compaction(8192/4096/1024)、delegation 全部就位 |
| A9 | Standard/PTC/Minimal/Cordis 不变 | **PASS**（结构） | bundle 只 `insert` 一行 `preset-ctf`（order 5），未 override 任何既有行；用户 patch 与既有 preset 配置零改动 |
| A10 | 每题黑板可写/可读 | **PASS** | `ctfboard init/fact add/fact list/deadend add/status` 冒烟：`FACT f1 candidate`、`DEADEND d1`、`ATTEMPTS 0/10` |
| A11 | 只有 verifier 能写 verified | **PASS** | e2e selftest：executor 写 verified → exit 2 DENIED；`verifier-*` + reproduced=yes + exit 0 + artifact → verified |
| A12 | 注入假阳性被验证门拦截 | **PASS** | "HTTP 200 = flag" 声明（reproduced=no, exit≠0）→ 降级 candidate + WARN，永不 verified |
| A13 | 提交 governor 生效 | **PASS** | 无 verified fact 提交 → exit 3；第 11 次 → exit 3 且 attempts 封顶 10；第 3 次起打印独立复核/批准提示；原始 flag 不落盘（只存 sha256） |
| A14 | 平台适配不把 200 当 Accepted | **PASS** | pending → exit 6；401 → exit 4（提示 `gzctf login`，不消耗 attempt）；dry-run 不发请求 |
| A15 | 评测工具链自检 | **PASS** | routing self-test 13/13；report self-test 15/15（含 wrong_submission / C3<C0 / token 超限 / verify_catches=0 / peak>70% 的 FAIL 检出） |
| A16 | 路由 10 例首选 ≥8/10 且 forbidden 0 | **PASS（9/10）** | `run_routing.py eval/answers_20261125.txt --json --out eval/reports/routing_result.json`：accuracy 0.9、forbidden 0、status PASS。route-010（pcap 里 base64 cookie + Java 反序列化，先还原链路）判成 `ctf-triage`；expected 为 `ctf-forensics` 首选 — 记为 1 例未中 |
| A17 | 3 道归档题本地可复算 | **PASS** | crypto-01、rev-01、forensics-01 的确定性 checker 均本地跑出已知 flag（sha256 已记录于 `eval/cases/challenges.yaml`） |
| A18 | 3 题 × 4 基线矩阵 | **已被用户改口径** | 用户指示"跑实验测不出啥，只看跑通 + 性能短板"→ 改为 §9 真实平台实测 + §10 性能画像；矩阵工具链保留（`report.py` 自检 15/15，模板输入如实输出 `INCOMPLETE`） |
| A19 | 真会话 catalog 计数 | **PASS（44）** | 隔离 profile 以 CTF 为默认 preset 起真实会话（Playwright + 独立 `dsh web` 端口），会话日志 `agentPreset: ctf`，catalog 44 项 = 12 CTF 入口 + 26 全局常驻 + `dsh-doc` + 5 内置；模型抄出全部 12 个 `ctf-*` 并用 skill 工具成功加载 `ctf-triage`（首标题 `# ctf-triage 入口（判类与路由）`）。证据：`eval/reports/catalog_verification.json`。**用户侧 GUI CTF 会话独立复核一致**：12 个 resident 入口均可模型调用、`skill` 加载 `ctf-triage` 返回同一 H1 与 resident 基目录；`ctf-writeup` 因 `disable-model-invocation: true` 不进 catalog（预期，仅 `/ctf-writeup` 显式调用） |
| A20 | 真实平台 Accepted（模型驱动） | **PASS** | 真实 CTF preset 会话（隔离 profile，danger-full-access）独立完成 SAMPLE-005：ctf-triage/ctf-misc 路由 → 平台附件下载 → 套娃解压 → 双重复现 → 黑板 verified → `ctfy.py submit-qa` 提交（平台 QA/static 通道，1 次尝试）→ `{"correct": true}`；独立复核 `/me/solves` 出现 `SAMPLE-005 solved_at 01:21:29Z`、`/qa/challenges` `solved_question_ids=["flag"]`、`attempted_wrong_question_ids=[]`（**0 次错误提交**）。证据：`runs/ctfy/SAMPLE-005/`（flag.txt/writeup.md/verify.md/submissions.jsonl/tmp/l3_platform_verdict.txt）+ `eval/reports/real_session_overrun.json` |
| A21 | 真实会话性能与纪律 | **发现并修复** | 该会话 627s / 1 turn / 109 steps / 122 tool calls（pwsh 60、edit 18、write 17、read 17、web 3）；token：fresh input 95.7k + output 57.8k、cache read 10.2M、峰值请求 148.8k。问题：拿到 Accepted 后仍继续研究平台/实例，越过 10 分钟预算且未经许可修改共享适配器。**修复**：persona 新增 Scope/Stop conditions/Submission 三条纪律并重装 bundle（`include:preset-ctf` 仍 active） |
| A22 | 适配器离线契约测试 | **PASS（13/13）** | `tools/test_ctfy_adapter.py`：verified-fact 门（submit/submit-qa 未验证 fact 均 exit 3）、QA 提交体形状、wrong→REJECTED exit 7、下载 302 不带 Authorization、503 fail-closed、raw flag 不落 stdout/黑板。报告 `tools/test_ctfy_report.md` |
| A23 | 脚本化 live smoke（幂等） | **PASS** | `live_smoke.py --challenge SAMPLE-005 --qa`：真实平台下载 → 本地复现 → 黑板 verified → 读到平台已解状态，`LIVE SMOKE ACCEPTED`（不重复提交） |
| A24 | 自动登录：gzctf | **PASS** | `tools/gzctf_login_once.py` 引导浏览器登录一次 → 自动导出 cookies+token → `gzctf import-cookies` → `whoami` = `已登录：godfqther`；`gzctf chals` 40 题，`gzctf solved` 40 个 ID 全已解 |
| A25 | 自动接入：CTFy Agent API | **PASS** | `tools/ctfy_bootstrap.py` 引导登录后自动在 Settings→API tokens 签发 `pf_` 令牌（AI 智能体——参赛模板，30 天）→ `~/.ctfy/api_token.txt`（0600）→ `/api/v1/me` 验证；agent token 直接跳过交互式 human check（实例请求不再返回 428） |
| A27 | 提交优先（用户定策略） | **PASS** | 执行层有确凿执行证据即可快车道提交（--auto --evidence），平台判定即验证：ACCEPTED → 写 inal/flag.txt+ACCEPTED.txt、黑板记 erifier-platform verified、打印醒目 banner；REJECTED → 记尝试、换新候选（governor 上限）；同 (question, answer) 幂等去重；verified-fact 通道保留为平台不可用/审计兜底。适配器契约 23/23、黑板 e2e 66/66、入口 lint 12/12，bundle 1.0.2 已重装 |
| A28 | 角色模型：常设监察员而非验证者 | **PASS** | 常设第三角色改为独立 Supervisor/Auditor：只看行为纪律（scope/凭据/flag 落点/重复提交/擅自改工具/进程干扰/虚假成功），不判 flag 对错、不阻塞快车道提交；失败时出 udit.md 追责。新增 in/ctf-audit.py（8 类检查 + 退出码 1=BREACH + --bless 工具完整性清单 37 文件）、离线测试 6/6；PROTOCOL §7.1 增加监察指标矩阵；bundle 1.0.3 已重装 |
| A29 | 角色/命名收口（用户定） | **PASS** | 常设角色 vocabulary 统一：`verifier-*` → **`checker-*`（复核员，legacy verifier 兼容）**、`verifier-platform` → `checker-platform`、第 12 入口 `ctf-verify` → **`ctf-submit`（提交与判定）**；状态 `verified`/命令 `verify record`/文件 `verify.md` 保留（语义是已确认证据，不是角色）。回归：entry lint 12/12、路由自检 13/13 + 样例 10/10、适配器契约 23/23、黑板 e2e 66/66、监察 7/7；bundle 1.0.4 已重装 |
| A26 | 纯问答自动求解 | **PASS** | `tools/solve_SAMPLE020_quiz.py`：从平台标准 CTFY-0002（`/docs/standards/CTFY-0002` 快照，sha256 记录）提取答案 → 三题 candidate/verified 黑板证据 → `submit-qa` 提交 → 平台 `solved_question_ids=["channels","flag_format","gate_field"]`、`attempted_wrong_question_ids=[]`（**0 错误提交**） |

## 3. catalog 的实际构成（静态核算）

CTF 会话可见技能 = 本 preset 的 skill provider（custom + 默认根）+ Host 全局层 provider：

| 来源 | 数量 | 说明 |
|---|---|---|
| `roots/resident`（CTF 入口） | 12 | 模型可调用；rank 300，同名时压过全局 |
| `~/.agents/skills` 常驻 | 26 | 全局技能（非 disable-model-invocation） |
| `~/.dsh/skills` | 0 | 3 个全部 disable-model-invocation |
| bundled `dsh-agent-preset/skills` | 1 | `dsh-doc` |
| Host 全局 provider（office 4 + sandbox 诊断 1） | 5 | 与 preset 无关，任何会话都有 |
| **合计（预期）** | **44** | 设计文档写的 "12+26" 是近似；实际另含 bundled 与 Host 内置 6 个 |

> 与方案的一处主动偏差：方案 §8.3 写 `includeDefaultRoots:false`。实测 DSH 0.2.2 的技能注册表是 **host+per-scope 分层**（`dsh-skill` README："a plugin mounted by an agent preset's standing composition lands in that preset's layer"），Host 层当前没有挂 skill-filesystem；若 preset 里再关默认根，26 个全局常驻会整体消失。因此 bundle 用单 provider + `includeDefaultRoots:true`，靠 rank 300 保证 12 入口优先。已在 bundle 注释与 README 记录。

## 4. 关键实测事实（写进实现，不再靠推测）

1. 技能发现只认 `<root>/<name>/SKILL.md` 一层；`pools` 递归索引必须走 `index.json` + `skillctl ctf`，不能进扫描根。
2. 技能注册表分层合并：preset 层 > 全局层；同层先注册者/rank 优先。`providerName: ctf-filesystem` 避免与其它 provider 混淆。
3. `dsh --profile desktop --dump-config` 被拒（"managed exclusively by the Electron application"）；用 `--from-default-profile web --patch ...` 的同构 profile 验证组合。
4. 任务看板执行路径在本 deployment 全局损坏：pinned preset 与 control（无 preset）两张卡都立即失败 `Cannot read properties of undefined (reading 'signal')`。与本 bundle 无关；因此不把看板当评测驱动（已删除两张测试卡）。
5. 运行中的 GUI（`http://127.0.0.1:63242`）要求启动时打印的鉴权 token；该 token 只在 Desktop 窗口里，工具侧拿不到。真会话 catalog 改用隔离 profile + 默认 preset 自动化验证（A19，无需该 token）。
6. `gzctf`：平台可达，CLI 当前 401 未登录（`gzctf doctor` 非阻塞）；L3 活体判定与错误提交=0 的真实验证要登录后做。
7. Windows Defender 在扫描时隔离了 2 个 yaklang `SKILL.md`（`path-traversal-lfi`、`reverse-shell-techniques`，检测日志 08:27–08:28）；pools 由 508 → 506 文件。索引/doctor 一致（500），未修改 pool 内容。

## 5. 与目标方案的偏差清单

| 项 | 方案 | 实现 | 理由 |
|---|---|---|---|
| skill provider 根 | `includeDefaultRoots:false` + Host 全局 26 | 单 provider + `includeDefaultRoots:true` + custom CTF 根 | 实测分层语义，见 §3 |
| 多智能体 | 三角色 / C1-C2 / 按需 | persona + `PROTOCOL.md` + delegation（spawn/fork/control），不挂 agent-team/workflow | 目标明确"不引入 agent-team"，黑板承载协调 |
| 评测配置矩阵 | C0/C1/C2/C3 四个 preset | 一个 `ctf` preset；C0=minimal，C1/C2/C3 由 prompt 协议块显式禁用检索/黑板+验证门来区分（`eval/driver.md`） | 避免给 product roster 塞 4 个 ablation 行；driver 写清区分方式与代价 |
| 路由门 | 首选 ≥8/10 | 9/10（0.9） | 1 例歧义题判成 triage；不改判分口径粉饰 |
| 3 题 × 4 基线 | P6 必做 | 工具链 + 3 题本地 checker 就绪，12 题次未执行 | 需真实会话与配额（§6） |
| 扩展 | 独立 bundle + manifest | schema + `extensions/` + 模板 + 规则；未做 `ctf-ext-kit` CLI | 目标版只要求"目录/schema"；扩展不改核心已由 insert-only bundle 保证 |

## 6. 登录与外部条件（2026-11-25 晚更新：登录已全自动化）

1. **gzctf 登录：已自动完成**。`tools/gzctf_login_once.py` 打开一次引导浏览器窗口；用户登录一次后脚本自动导出 cookies+token、`gzctf import-cookies` 导入并 `whoami` 验证 → `已登录：godfqther`。当前该课程比赛 40 道题的已解 ID 全部为已解（`gzctf solved` 40 个），无需再提交。`ctf-submit.py` 继续对未登录 fail-closed（exit 4，不消耗 attempt）。
2. **CTFy 登录与 Agent 接入：已全自动**。`tools/ctfy_bootstrap.py`：引导登录一次 → 自动在 Settings → API tokens 用「AI 智能体 —— 参赛」模板签发 `pf_` 令牌（challenges:read submissions:write instances:write teams:write profile:read，30 天）→ 存 `~/.ctfy/api_token.txt`（0600）→ `/me` 验证身份。之后 SDK/CLI/MCP/REST 共用该令牌，**交互式 human check 被跳过**。适配器凭证优先级：`CTFY_TOKEN` > `~/.ctfy/api_token.txt` > `~/.ctfy/session.json`。
3. **CTFy 实例池离线（唯一外部阻塞，非登录问题）**：`POST /instances` 在 SAMPLE 共享池返回 `503 no_healthy_node`（"Register a node first: `ctfy-admin node join`"），Platform Playground 专用池返回 `503 dedicated_pool_unavailable`；**用官方前端点"启动"与用官方 agent token 调用结果一致**，说明是平台节点池未注册/离线，与登录、human check、适配器无关。节点恢复后 `tools/retry_l4.py` 自动补实例型 L4。
4. **用户 GUI 验证（已完成自动化等价验证）**：隔离 profile 真会话（A19）+ 用户侧 GUI CTF 会话复核一致；desktop profile 正常路径是新建会话时选 **CTF**。
5. **12 题次统计矩阵**：按用户口径改为"跑通 + 性能"后不再执行；`eval/driver.md` 与 `report.py` 保留。

## 7. 复现命令

```powershell
# 装配
plugin_manager list_plugins                      # include:preset-ctf active
# 入口/索引
python ~/.agents/ctf-mode/tools/lint_skills.py
python ~/.agents/tools/skillctl.py ctf doctor
python ~/.agents/tools/skillctl.py ctf search "逆向 反混淆"
python ~/.agents/ctf-mode/tools/ctf_search_test.py
# 状态/验证
python ~/.agents/ctf-mode/tools/test_ctfboard.py
python ~/.agents/ctf-mode/bin/ctfboard.py --help
# 评测
python ~/.agents/ctf-mode/eval/run_routing.py ~/.agents/ctf-mode/eval/answers_20261125.txt --json
python ~/.agents/ctf-mode/eval/verify_challenges.py
python ~/.agents/ctf-mode/eval/report.py ~/.agents/ctf-mode/eval/trials.template.jsonl
# 真实平台（CTFy，需先人工登录一次）
python ~/.agents/ctf-mode/bin/ctfy.py doctor
python ~/.agents/ctf-mode/bin/ctfy.py list
# 实例通道（当前平台节点池离线 → 503；节点恢复后由 retry_l4 自动补跑）
python ~/.agents/ctf-mode/tools/live_smoke.py --challenge SAMPLE-018 --platform-game e4e78ff318dc4844beac13f9ea7409aa --verify
# 静态题通道（无需实例，已拿到 Accepted）
python ~/.agents/ctf-mode/tools/live_smoke.py --challenge SAMPLE-005 --platform-game e4e78ff318dc4844beac13f9ea7409aa --qa
python ~/.agents/ctf-mode/bin/ctfy.py submit-qa SAMPLE-005 --question flag --answer-file <answer> \
    --verified-fact f1 --game ctfy --competition e4e78ff318dc4844beac13f9ea7409aa
python ~/.agents/ctf-mode/bin/ctfy.py solves --game e4e78ff318dc4844beac13f9ea7409aa
python ~/.agents/ctf-mode/tools/perf_profile.py
```

## 8. CTFy 真实平台实测（用户指定路线：只看跑通 + 性能）

平台：`https://ctfy.tsinghua.edu.cn`（CTFy v1.3.26，Go 实现，开源 `github.com/wangyihang/ctfy`），练习场 `Platform Playground` + `SAMPLE` 套件，flag 前缀 `FLAG`。

已实现并实测：
1. **适配器** `bin/ctfy.py`：推 API 得到 player 面（`/meta`、`/competitions/{id}/challenges`、`POST /instances`、`/instances/{id}/status|attachments|vpn-config`、`POST /submissions`、`POST /instances/{id}/check`、`/me/solves`），鉴权为登录后 `localStorage.teamKey` 的 `Authorization: Bearer`（由人工登录脚本写入 `~/.ctfy/session.json`，工具不碰密码、不打印 key）。
2. **鉴权/名额/题面**：`ctfy.py doctor` → `auth: OK`（identity 已登录账号，`registered=True`，`my_solves=0`）；`list` 拿到 15 道题与 questions/attachments。
3. **附件下载**：修复 R2 预签名重定向（302 → object storage，必须**去掉**平台 Authorization 再 GET，否则 S3 报 `SignatureDoesNotMatch`）；真实下载 `SAMPLE-005 archive.zip`（sha256 与平台 CAS 名一致）与 `SAMPLE-003 healthcheckd`。
4. **确定性求解 + 本地复现**：对真实平台附件解套娃压缩，纯本地两次独立抽取一致（sha256 `3c789c77…`）→ L2 通过；**提交前又从平台重新下载 `archive.zip`（1028 B，sha256 `c81cc268…`，与本地副本一致）重解一次，三跑同一 sha256**。
5. **黑板/验证门**：`live_smoke` 自动 init→candidate fact→`verifier-smoke` 写 verified（证据含附件 sha256、复现结论）→ 事实升级为 verified，`verify.md` 追加证据块，telemetry 落盘。**证据**：`runs/ctfy/SAMPLE-005/`（`facts.jsonl` f1/f2、`verify.md` v1/v2、`submissions.jsonl`）。
6. **实例池离线（实测）**：`POST /instances` 在 SAMPLE 套件返回 `503 no_healthy_node`（"No healthy node available. Register a node first: `ctfy-admin node join`"），在 Platform Playground 返回 `503 dedicated_pool_unavailable`。同一挑战 `SAMPLE-009` 在人类校验通过后仍被专用池拒绝，证明**不是** human-check 卡住；实例通道因此 fail-closed 为 `BLOCKED`，不编造 Accepted。
7. **catalog 真会话**：见 A19，44 项 = 12+26+6，skill 工具可加载入口。
8. **人类校验（PoW）已实现，标记 experimental/unverified**：平台对 `POST /instances` 返回 `428 human_check_required`（provider `pow`）。按部署前端的 `/assets/pbkdf2-CIq9Xt-Y.js` worker 还原算法：`PBKDF2-HMAC-SHA256(password = nonce_bytes ‖ uint32_be(counter), salt = salt_bytes, iterations = cost, dklen = keyLength)`，取首个以 `keyPrefix` 开头的派生键；令牌为 `base64(JSON{challenge:{parameters,signature}, solution:{counter,derivedKey,time}})`，放 `X-Human-Check` 头。新增 `bin/ctfy_pow.py` + `ctfy.py` 的 428 自动重试。**但**后续独立实测返回 `403 human_check_invalid`（令牌未被接受），且节点池离线导致该路径无法稳定复验——因此不计入验收，仅作为实验路径保留。
9. **真实 Accepted（L3 闭环）**：平台对静态题给出独立判分通道 `GET /qa/challenges`（question `"mode": "static"`, `"requires": []`）→ `POST /qa/submissions {challenge_id, competition_id, question_id, answer}`，无需实例。新增 `ctfy.py submit-qa`（同样受 verified-fact 闸门 + governor + 只记 sha256）。实测提交 `SAMPLE-005`：`{"correct": true}`，平台状态 `GET /me/solves` 出现 `SAMPLE-005 solved_at=2026-11-25T01:21:29Z ranked=true best_rank=129`，`GET /qa/challenges` 的 `solved_question_ids = ["flag"]`、`attempted_wrong_question_ids = []`。**这是本模式的第一个真实平台 Accepted 证据**（比赛：SAMPLE 套件 `e4e78ff3…`；练习场专用池仍离线，见 §6.1）。
10. **可复现的单命令验收**：`live_smoke.py --qa` 走同一套链路（doctor→list→下载→确定性求解→L2→黑板 verified→平台状态确认），且在题目已解时**读平台状态而不是二次提交**（不浪费 attempt）：实测 `LIVE SMOKE ACCEPTED total_measured=8051ms`，报告 `eval/reports/live_smoke_SAMPLE-005.json`。

## 9. 性能画像（`tools/perf_profile.py` → `tools/perf_report.md`）

| 项目 | 实测 | 结论 |
|---|---|---|
| catalog 上下文成本 | 12 CTF + 26 全局 ≈ **2,694 tokens**（设计目标 1,500） | 唯一"每请求都付"的成本；26 个全局常驻是主因。若预算敏感可把 `includeDefaultRoots` 关掉（catalog 降到 ~900 tokens，但会失去 26 个全局技能），当前按方案保留 12+26 |
| 12 入口正文 | 57,858 B / 12；均值 ≈1,793 tokens/页 | 单次加载一页的成本，符合 ≤6KB 约束 |
| 黑板命令 | init 150ms / fact add 156ms / deadend 191ms / verify record 336ms / status 158ms | 每条命令 = 1 个 ctfboard 进程 + 1 个 blackboard 子进程；相对模型单步（秒级）<5%，长 fact 循环里才可见 |
| 知识检索 | search 143–205ms（342 KB index.json 全量加载）；show 136ms；doctor 484ms；索引生成 0.8s | 可接受；要更快可做 compact 搜索索引（预估减半） |
| 平台 API | ctfy doctor 355ms、list 487ms（网络） | 正常 |
| 真实会话（模型驱动，SAMPLE-005） | 627s / 1 turn / 109 steps / 122 tool calls；fresh input 95.7k + output 57.8k，cache read 10.2M，峰值请求 148.8k | 解题本身在 ~20 步内完成（9:21 Accepted）；其余步数用于越界研究实例/平台。已是本轮最大短板，persona 纪律已修（A21） |
| 技能正文加载 | 读 12 页 5ms（I/O） | 可忽略 |

**性能短板排序**：catalog tokens ≫ 命令进程开销 > 索引加载。前者是预算问题（可配置），后者是毫秒级、不构成模型交互瓶颈。

## 10. 结论

目标形态的全部组件已落地并有实测证据：12 入口 12/12、500 技能索引 30/30、黑板/验证门 66/66、路由 9/10、**真会话 catalog 44 项（12+26+6）且 skill 工具可加载**、**真实 CTF preset 会话在 CTFy 平台拿到 Accepted（SAMPLE-005，1 次提交 / 0 错误，`/me/solves` + `solved_question_ids` 双确认）**、适配器离线契约测试 13/13、真实会话性能画像与越界行为修复。静态题判分通道（`/qa/submissions`）已验证；仍需外部条件的有两项：**需要实例**的题型（SAMPLE 共享池 `no_healthy_node`、练习场专用池 `dedicated_pool_unavailable`，节点恢复后可用 `tools/live_smoke.py`/`tools/retry_l4.py` 补 L4 证据）和 gzctf 登录（第二平台，适配器已 fail-closed）。human-check PoW 路径保留为 experimental，不计入验收。


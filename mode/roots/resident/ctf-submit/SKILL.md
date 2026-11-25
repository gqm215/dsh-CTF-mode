---
name: ctf-submit
description: Use when a candidate flag has execution evidence and should be submitted fast, or when a verdict must be recorded; do not use when nothing has been produced yet or the task is pure exploration.
domain: verification
type: protocol
tools: [bash, python, gzctf, ctfy, sha256sum]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-submit 入口（提交优先 · 平台判定即验证）

## When it applies

- 触发：执行层已产出有执行证据的候选 flag → 走**快车道提交**；或平台判定回来后要记账。
- 前置：候选有来源（命令/文件/offset）；平台凭据已就绪（gzctf: `~/.gzctf/session.json`；ctfy: `~/.ctfy/api_token.txt`，绝不写进 notes/报告/任务书）。
- 不适用：还没有任何候选 → 回类别入口；纯探索阶段不收尾。

## 5 分钟检查表

- [ ] 已保存执行证据文件：命令 + 完整输出 + exit + sha256（`tmp/<chal>/evidence_<q>.txt`）。
- [ ] `ctfboard.py governor --game G --chal C` 查过 attempts 与上限；平台未解（已解不重提）。
- [ ] 确认 flag 是程序/文件真实输出，未擅自加 `flag{}`、未假定同前缀。
- [ ] 平台的提交通道已确认可用（实例型需实例 running；静态题可走 QA 通道）。

## 子技术决策树

```
执行证据确凿（命令/文件/脚本输出直接得到 flag）
    → 立即提交（快车道 --auto --evidence），不等待独立验证回合
平台 ACCEPTED
    → 写 final/flag.txt + ACCEPTED.txt；黑板记 verified（actor checker-platform）；
      通知主控；该问停止验证（平台判定即验证）
平台 REJECTED
    → 尝试已记账；换新候选继续（受 governor 上限约束）；不要重发同一答案
平台通道不可用 / 需要独立审计
    → 才走本地 L1/L2 + verify record（checker-*）；通道恢复后再提交
同一 (question, answer)   → 只发一次（适配器幂等去重；重复会被 exit 3 拒绝）
HTTP 200 / 页面刷新       → 不算 Accepted；以平台终态/已解 ID 为准
```

## Method（首步协议）

1. 证据：把"产生 flag 的确切命令 + 输出 + exit + sha256"写进 `tmp/<chal>/evidence_<q>.txt`。
2. 预检：`python ~/.agents/ctf-mode/bin/ctfboard.py governor --game G --chal C` → 期望 attempts 未耗尽；查平台状态确认未解。
3. 快车道提交：
   - CTFy QA/静态题：`python ~/.agents/ctf-mode/bin/ctfy.py submit-qa <CHAL> --question <q> --answer-file final/flag.txt --auto --evidence tmp/<chal>/evidence_<q>.txt --game <game> --competition <comp>`
   - CTFy 实例型：`... ctfy.py submit <instance> --question <q> --answer-file ... --auto --evidence ... --game <game> --chal <chal>`
   - gzctf：`python ~/.agents/ctf-mode/bin/ctf-submit.py submit --game G --chal C --cid <cid> --flag-file final/flag.txt --auto --evidence tmp/<chal>/evidence_<q>.txt`
   → 期望：ACCEPTED banner（flag + attempt）或 REJECTED；HTTP 200 单独出现不算。
4. ACCEPTED：适配器已写 `final/flag.txt`、`ACCEPTED.txt` 并记 verified fact；你只需补 `final/writeup.md`（含 flag 与来源），并在黑板补一条任务流 fact、向主控/父会话报告一行结果。
5. REJECTED：记账完成；读平台状态/报错判断是否 flag 格式或题型误判，换新候选；3 次后按治理复核，`max_attempts` 由 config 决定。
6. 平台不可用时：才用 `ctfboard.py verify record --verdict verified --actor checker-*` 保留本地证据链，等通道恢复后再快车道提交。

### verify.md 证据块模板（平台判定时由适配器自动写）

```markdown
## Claim
<一句话结论>

## Evidence
- command: `<exact command>`
- output: `<full output or path>`
- exit: 0
- artifact: `<path>` sha256: <hash>
- reproduced: yes (local) / yes (WSL) / no
- timestamp: 2026-11-24T...

## Verdict
verified | candidate | rejected
```

### 提交与治理

- 提交基据二选一：**执行证据**（快车道，默认）或 verified fact（平台不可用时的兜底）。
- 同一 `(question, answer)` 只发送一次；错误答案可以换新候选继续提交。
- ≤3 次：按治理要求复核/批准；`max_attempts: 10`（config 可调）。
- 不提交假 flag 探测接口；不擅自加 `flag{}`，不假定整批同前缀。
- 完成 = 逐题平台终态 `Accepted` + 已解 ID 覆盖；总分/解出人数不算。

## Output contract

- `tmp/<chal>/`：求解脚本、执行证据、hash 清单、提交记录副本。
- `draft/notes.md`：候选/死胡同/复核意见/下一步。
- `final/flag.txt`：flag 原文 + 来源（平台/命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤 + flag 原文与来源（writeup 必须含 flag）。
- `ACCEPTED.txt`：平台 ACCEPTED 记录（flag、平台、attempt、时间）。
- `verify.md`：平台判定与证据块；仅平台不可用时才有本地复核证据。
- 规则：candidate ≠ verified；verified 只由 `checker-*` actor（含 `checker-platform`）写。

## Verify success（可观察）

- 成功：平台终态 `Accepted`/`correct:true`，且已解 ID 覆盖该题；QA 通道看 `solved_question_ids`。
- 失败：HTTP 200、页面刷新、他人转述都不算；未拿到终态的一律标 `(unverified)`。

## References

- 验证契约：[VERIFY_CONTRACT.md](../../../templates/VERIFY_CONTRACT.md)
- 状态模型：[STATE_SCHEMA.md](../../../templates/STATE_SCHEMA.md)
- 接口契约：[SPEC.md](../../../SPEC.md) §5
- 平台策略：[STRATEGY.md](../../../../../.gzctf/STRATEGY.md)
- 纪律审计：[ctf-audit.py](../../../bin/ctf-audit.py)（监察员：只看行为纪律，不判 flag 对错）
- 相邻：[ctf-blackboard](../ctf-blackboard/SKILL.md)、[ctf-triage](../ctf-triage/SKILL.md)

## Anti-patterns

- 不要把 HTTP 200/页面刷新/总分当成 Accepted。
- 不要为"等验证"而延迟提交：平台判定就是验证，快车道优先。
- 不要把凭据写进 notes/报告/任务书；flag 只进 final/ 与 writeup。

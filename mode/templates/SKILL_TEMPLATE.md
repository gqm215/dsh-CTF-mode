---
name: ctf-<category>
description: Use when <具体触发：文件类型/服务行为/题面关键词/工具输出>; do not use when <相邻类别或已明确技能可直接调用>. This is the <category> entry, not the deepest reference.
domain: <category>
type: technique
stability: learning
tools: [bash, python3]
schema_version: 1
license: MIT
disable-model-invocation: false   # 常驻入口必须 false；深挖包设为 true
user-invocable: true
---

# <Category> 入口

## When it applies

- 触发条件（可观察）：<文件后缀、端口、协议、报错串、题面词>
- 前置：<工具/权限/服务可达性>
- 不适用：<明确列出相邻类别，并指向正确入口>

## Why it works

2–3 句机制说明。写"为什么这类题会留下什么信号"，不写 payload，不写流程总结。

## 5 分钟检查表

- [ ] 文件类型/服务指纹已确认（`file`、`checksec`、`curl -I`、`nmap -sV`）
- [ ] 题面/附件/远程服务三处信息都已读
- [ ] 至少一个可验证 primitive（输入→输出/崩溃/回显）已建立
- [ ] 已确定下一步要读的 references

## 子技术决策树

```
如果 <信号 A> → 读 references/a.md
如果 <信号 B> → 读 references/b.md
如果 <信号 C> 且 <条件> → 先做 <最小验证>，再决定
否则 → 回 ctf-triage / 换类别
```

## Method（首步协议）

1. <命令> → 期望输出：<...>
2. <命令> → 期望输出：<...>
3. 把观察写成 candidate fact（见 STATE_SCHEMA），不要直接下结论。

## Tool protocol

| 工具 | 用途 | 关键参数/注意 |
|---|---|---|
| <tool> | <...> | <超时/输出截断/权限> |

## Gotchas

- <失败模式>：如何区分"没成功"与"不存在"。
- <常见误判>：<例：无回显 ≠ 无漏洞>。

## Verify success（可观察）

- 成功信号：<uid=0 / 返回角色 / 规则触发 / hash 一致 / 平台 Accepted>
- 失败/未验证：必须标 `(unverified)`，不得写入 verified facts。

## Output contract

- `tmp/<chal>/`：脚本、payload、抓包
- `draft/notes.md`：candidate facts 与死胡同
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）
- `final/writeup.md`：可复现步骤

## References

- 外部：<权威文档/CVE/论文>
- 相邻技能：`/<other-skill>`（何时转过去）
- 深挖：`references/<file>.md#<anchor>`

## Anti-patterns

- 不要在没建立 primitive 前深挖。
- 不要把猜测写成 fact。
- 不要重复已记录的死胡同（除非满足 reopen 条件）。

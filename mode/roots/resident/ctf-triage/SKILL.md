---
name: ctf-triage
description: Use when a CTF challenge arrives with unknown or mixed surface and the category is not yet chosen; do not use when one category is already clearly indicated, go straight to that entry.
domain: triage
type: router
tools: [bash, python, file, curl]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-triage 入口（判类与路由）

## When it applies

- 触发：新题目到手、题面信息不足、或从某类别 REROUTE 回来。
- 前置：题面/附件/远程地址至少读到一项；附件已落到 `tmp/<chal>/`。
- 不适用：类别信号已明确（如 64 位 ELF + nc → 直接 [ctf-pwn](../ctf-pwn/SKILL.md)），不要在此空转。

## 5 分钟检查表

- [ ] 题面/附件/远程地址三处信息都已读，摘要写进 `draft/notes.md`。
- [ ] `file <附件>`、`ls -la`、`curl -sI <url>` 至少做过一项，得到可观察指纹。
- [ ] 已按“目标表面”给出 1 个首选类别 + 1 个备选，并写置信度。
- [ ] 已估算预算：单题 150k tokens / 45 分钟，超出即止损。
- [ ] 已执行或计划首个可验证 primitive（输入→输出/崩溃/回显）。

## 子技术决策树

### 四列 triage 表（按目标表面判类，不按关键词堆砌）

| 类别 | 首步探针（可观察） | 一句话覆盖 | 参考入口 |
|---|---|---|---|
| web | URL/源码；`curl -I` 有响应 | 认证/注入/SSRF/上传/反序列化/竞态 | [ctf-web](../ctf-web/SKILL.md) |
| pwn | ELF + 远程服务；`checksec` 有保护信息 | 栈/堆/格式化串/ROP/沙箱 | [ctf-pwn](../ctf-pwn/SKILL.md) |
| reverse | 二进制/字节码/APK/固件；`file` 非常规文档 | 静态/动态/反混淆/VM | [ctf-reverse](../ctf-reverse/SKILL.md) |
| crypto | 数学/密钥/协议；题面给参数或密文 | RSA/ECC/格/AES/PRNG | [ctf-crypto](../ctf-crypto/SKILL.md) |
| forensics | 磁盘/内存/流量/日志/图片 | 雕复/PCAP/内存/时间线 | [ctf-forensics](../ctf-forensics/SKILL.md) |
| misc | 编码/沙箱/游戏；以上都不像 | 编码/pyjail/交互 | [ctf-misc](../ctf-misc/SKILL.md) |
| ai-ml | 权重/prompt/对抗样本 | 权重扰动/注入/窃取 | [ctf-ai-ml](../ctf-ai-ml/SKILL.md) |
| malware | 可疑样本/家族/beacon | 静态/动态/YARA（不运行） | [ctf-malware](../ctf-malware/SKILL.md) |
| osint | 人/组织/域名/公开信息 | 搜索/关联/元数据 | [ctf-osint](../ctf-osint/SKILL.md) |

### 目标表面决策树

```
远程服务 + 崩溃/内存行为 → pwn
远程服务 + HTTP 语义     → web
附件 + 二进制/字节码      → reverse（先 triage，再决定是否 pwn）
附件 + 密文/参数/数学     → crypto
附件 + 镜像/PCAP/日志     → forensics
权重/prompt/模型文件      → ai-ml
样本/可疑脚本             → malware（只分析，不执行）
人/组织/域名              → osint
都不匹配                  → misc（fallback，不是默认起点）
```

### 止损与重路由

- 2 次同类失败 → 换工具/换子目标，不要重复同一命令。
- 3 次无进展 → REROUTE：回本页重判类别，给新候选与置信度。
- 仍无 → PARK：写 dead end（scope/tests/invariant/reopen_if），转向下一题。
- 升级/交接前把状态压成 ≤1,000 token 的 case file。

## Method（首步协议）

1. `mkdir -p tmp/<chal> draft final` 并把附件复制进 `tmp/<chal>/` → 期望：目录树 + 题面摘要。
2. `file <附件>`；有 URL 则 `curl -sI <url>`；有端口则 `nc -vz <host> <port>` → 期望：类型/状态码/端口结论。
3. 按四列表写 `首选 <category>(置信度 0.x) / 备选 <category>` 到 `draft/notes.md`。
4. 读所选入口的 Method 首步，把 triage 结论写成 candidate fact（`ctfboard.py fact add`）。
5. 只有首个 primitive 明确后才深挖；否则继续 triage 或换候选。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：附件、探针输出、脚本；不覆盖题目源文件。
- `draft/notes.md`：题面摘要、首选/备选类别与置信度、下一步指针。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：判类结论有可复现探针支撑（命令+输出），首选类别入口的 Method 能直接接续执行。
- 失败：只能说出类别名、没有探针证据的，标 `(unverified)` 并继续 triage。

## References

- 路由模板：[ROUTER_TABLE.md](../../../templates/ROUTER_TABLE.md)
- 入口契约：[SPEC.md](../../../SPEC.md)
- 相邻：上表全部 9 个类别入口；无类别命中时转 [ctf-misc](../ctf-misc/SKILL.md)
- 外部：[CTF Wiki](https://ctf-wiki.org/)

## Anti-patterns

- 不要按题面关键词堆砌判类；要看目标表面与首步探针输出。
- 不要在没有 primitive 时反复换类别空转；先建立可观察信号。
- 不要把猜测写成 fact；candidate 必须带 evidence 与来源。
- 不要重复已记录死胡同（除非满足 reopen_if）。

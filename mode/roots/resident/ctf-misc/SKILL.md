---
name: ctf-misc
description: Use when a challenge fits no other category and the surface is encodings, a jail, audio, a game or a puzzle; do not use when a stronger category signal exists; misc is a fallback, not a default.
domain: misc
type: technique
tools: [bash, python, z3, file]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-misc 入口（杂项兜底）

## When it applies

- 触发：附件是编码串/二维码/音频/小游戏/沙箱脚本/pyjail；或跑完 triage 表后没有更强类别信号。
- 前置：`file`/`xxd` 已看；交互式题目能连上；Python 可跑。
- 不适用：类别信号明确时不要停在这里 —— web→[ctf-web](../ctf-web/SKILL.md)、pwn→[ctf-pwn](../ctf-pwn/SKILL.md)、crypto→[ctf-crypto](../ctf-crypto/SKILL.md)、forensics→[ctf-forensics](../ctf-forensics/SKILL.md)、reverse→[ctf-reverse](../ctf-reverse/SKILL.md)。

## 5 分钟检查表

- [ ] `file <f>` 与 `xxd <f> | head -5` 看头尾魔数与可见结构。
- [ ] 常见编码已试：base64/base32/hex/ROT/URL encode。
- [ ] 若是图片/音频，已跑 `zbarimg`/`binwalk`/`steghide` 或频谱检查。
- [ ] 若是交互题，已 `nc` 连上并记录提示语与输入格式。
- [ ] 已确认不是其他 8 类的强信号，或已记录为何排除。

## 子技术决策树

```
编码/多层解码/QR/杂码        → ../../../pools/ctf-skills/ctf-misc/encodings.md
Python jail / sandbox       → ../../../pools/ctf-skills/ctf-misc/pyjails.md
bash/sh jail 逃逸           → ../../../pools/ctf-skills/ctf-misc/bashjails.md
音频/频谱/DTMF              → ../../../pools/ctf-skills/ctf-misc/audio.md
小游戏/自定义 VM/交互       → ../../../pools/ctf-skills/ctf-misc/games-and-vms.md
z3/约束求解/约束推导        → ../../../pools/ctf-skills/ctf-misc/SKILL.md
Linux 提权/SUID             → ../../../pools/ctf-skills/ctf-misc/linux-privesc.md
DNS 隧道/编码               → ../../../pools/ctf-skills/ctf-misc/dns.md
都不匹配                    → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `file <f>` + `xxd <f> | head -5` → 期望：真实类型与头部魔数（错配即为线索）。
2. 逐层解码：`base64 -d` / `xxd -r -p` / `python` 脚本 → 期望：每层输出可读性提升，记录层数与偏移。
3. 交互题：`nc <host> <port>` 记录 banner/输入格式 → 期望：明确 oracle（长度/比较/回显）。
4. 建最小 oracle：一次只改一个输入变量，观察响应差异；必要时用 z3 建模。
5. 写解题脚本放 `tmp/<chal>/`，把关键观察写成 candidate fact。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：解码脚本、提取文件、payload；不覆盖题目源文件。
- `draft/notes.md`：编码层数、oracle 行为、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：解码链可重放且输出稳定；jail 里执行 `id`/读 flag 命令有回显。
- 失败：肉眼像 flag 但不可复现的，标 `(unverified)`。

## References

- 深挖：[pyjails.md](../../../pools/ctf-skills/ctf-misc/pyjails.md)、[encodings.md](../../../pools/ctf-skills/ctf-misc/encodings.md)、[audio.md](../../../pools/ctf-skills/ctf-misc/audio.md)、[games-and-vms.md](../../../pools/ctf-skills/ctf-misc/games-and-vms.md)
- 相邻：[ctf-triage](../ctf-triage/SKILL.md)（重新判类）、[ctf-forensics](../ctf-forensics/SKILL.md)（隐藏数据）
- 外部：[CyberChef](https://gchq.github.io/CyberChef/)、[dCode](https://www.dcode.fr/)

## Anti-patterns

- 不要把 misc 当默认起点；先按目标表面判类。
- 不要在宿主机直接运行未知二进制；用 WSL/容器。
- 不要猜 flag 格式或擅自补 `flag{}`。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

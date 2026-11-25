---
name: ctf-pwn
description: Use when a challenge ships an ELF or PE binary with a remote nc or local program and memory corruption, ROP or sandbox escape is the hard part; do not use when the task is web logic or reverse.
domain: pwn
type: technique
tools: [bash, python, pwntools, gdb, checksec]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-pwn 入口（二进制利用）

## When it applies

- 触发：附件是可执行 ELF/PE + 远程 `nc host port` 或本地可运行；`checksec --file=<bin>` 输出保护信息。
- 前置：pwntools 可用；能本地复现程序行为；libc 版本尽量获取。
- 不适用：未理解程序逻辑 → 先 [ctf-reverse](../ctf-reverse/SKILL.md)；纯 HTTP 语义 → [ctf-web](../ctf-web/SKILL.md)；受限 shell/pyjail → [ctf-misc](../ctf-misc/SKILL.md)。

## 5 分钟检查表

- [ ] `file <bin>`、`readelf -h <bin>` 与 `checksec --file=<bin>`：架构、入口、PIE/RELRO/NX/Canary。
- [ ] 本地运行程序并喂测试输入，观察崩溃/回显/菜单。
- [ ] `nc -v <host> <port>` 确认远程服务与本地行为一致。
- [ ] 已确定一个可重复的崩溃点（`cyclic` + core/gdb 或 ASAN）。
- [ ] 有 seccomp 就跑 `seccomp-tools dump ./<bin>` 记录允许的 syscall。

## 子技术决策树

```
无 Canary + 无 PIE + Partial RELRO → ../../../pools/ctf-skills/ctf-pwn/overflow-basics.md
Canary/PIE 需要泄漏               → ../../../pools/ctf-skills/ctf-pwn/rop-and-shellcode.md
printf 输入回显/任意读写           → ../../../pools/ctf-skills/ctf-pwn/format-string.md
菜单式 malloc/free              → ../../../pools/ctf-skills/ctf-pwn/heap-techniques.md
有 seccomp/open 限制             → ../../../pools/ctf-skills/ctf-pwn/sandbox-escape.md
kernel/module 题                → ../../../pools/ctf-skills/ctf-pwn/kernel.md
线程/sleep/全局态竞态            → ../../../pools/ctf-skills/ctf-pwn/advanced.md
未命中                          → 回 [../ctf-triage/SKILL.md](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `file <bin>; checksec --file=<bin>` → 期望：架构 + PIE/NX/Canary/RELRO 表。
2. `./<bin>` 喂 `AAAA`，`dmesg`/gdb 看崩溃 → 期望：EIP/RIP 可控或明确的崩溃模式。
3. `python -c "from pwn import *; print(cyclic(256))"` 求偏移，`cyclic_find(<crash value>)` → 期望：精确 offset。
4. 建最小 primitive：泄漏 libc/栈地址或直接 ret2win；先拿本地 shell/读本地 flag。
5. 同 payload 打远程 `nc`，把每步输出写成 candidate fact。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：exploit.py、payload、core、附件；不覆盖题目源文件。
- `draft/notes.md`：checksec 表、offset、libc 版本、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功信号：本地拿到 shell（`uid=0` 或读到本地 flag 文件），远程同 payload 同样成功；脚本 exit 0。
- 失败：只有崩溃/无回显不算成功；未在远程复现的标 `(unverified)`。

## References

- 深挖：[overflow-basics.md](../../../pools/ctf-skills/ctf-pwn/overflow-basics.md)、[rop-and-shellcode.md](../../../pools/ctf-skills/ctf-pwn/rop-and-shellcode.md)、[heap-techniques.md](../../../pools/ctf-skills/ctf-pwn/heap-techniques.md)
- 相邻：[ctf-reverse](../ctf-reverse/SKILL.md)（先懂逻辑）、[ctf-triage](../ctf-triage/SKILL.md)
- 外部：[how2heap](https://github.com/shellphish/how2heap)、[ROPgadget](https://github.com/JonathanSalwan/ROPgadget)
- 逆向工具链：`GZ_CTF\ai-toolchain\README.md`（angr/Ghidra 无头入口 `ctf.ps1 doctor`）。

## Anti-patterns

- 不要在 checksec 与崩溃 primitive 之前写完整 exploit。
- 不要假设远程 libc 与本地一致；先泄漏再选 libc。
- 不要忽略 seccomp/NX 就套 ret2shellcode。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

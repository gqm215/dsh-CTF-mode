---
name: ctf-reverse
description: Use when a challenge ships a binary, bytecode, APK or firmware and the goal is understanding its logic; do not use when the hard part is memory corruption or web behaviour.
domain: reverse
type: technique
tools: [bash, python, objdump, ghidra, strings]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-reverse 入口（逆向）

## When it applies

- 触发：附件是二进制/字节码/APK/固件/自定义 VM；`file` 输出非常规文档；题面要求还原校验或算法。
- 前置：可执行或可反编译；有测试输入能观察通过/失败。
- 不适用：已知漏洞要打远程 → [ctf-pwn](../ctf-pwn/SKILL.md)；web 客户端脚本只是小辅助 → [ctf-web](../ctf-web/SKILL.md)；核心是密码学算法 → [ctf-crypto](../ctf-crypto/SKILL.md)；真实恶意样本 → [ctf-malware](../ctf-malware/SKILL.md)。

## 5 分钟检查表

- [ ] `file <bin>` 与架构；可执行则 `chmod +x` 跑一次。
- [ ] `strings <bin> | grep -inE "flag|ctf\{|correct|wrong"` 先找明文字符串。
- [ ] `ltrace`/`strace` 跑一遍，看是否直接吐出比较目标。
- [ ] `objdump -d --disassemble=main <bin>` 或 r2 `pdf @ main` 看主逻辑。
- [ ] 找到校验函数/关键比较点，写进 `draft/notes.md`。

## 子技术决策树

```
明文字符串直接含 flag        → ../../../pools/ctf-skills/ctf-reverse/patterns.md
flag checker/约束校验        → ../../../pools/ctf-skills/ctf-reverse/unicorn-emulation.md
加壳/反调/花指令/时间检测     → ../../../pools/ctf-skills/ctf-reverse/anti-analysis.md
自定义 VM/opcode             → ../../../pools/ctf-skills/ctf-reverse/patterns.md
.NET/Java/APK/Python 打包    → ../../../pools/ctf-skills/ctf-reverse/languages.md
固件/硬件/外设协议            → ../../../pools/ctf-skills/ctf-reverse/platforms.md
动态跟踪看真实比较值          → ../../../pools/ctf-skills/ctf-reverse/tools-dynamic.md
未命中                       → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `strings <bin> | grep -inE "flag|ctf\{|congrat|correct|wrong"` → 期望：命中或明确无明文，**不要用 head 截断**。
2. `file <bin>` + `./<bin>` 喂测试输入 → 期望：通过/失败行为与输入形态。
3. `objdump -d --disassemble=main <bin>`（或 Ghidra `ctf.ps1`）→ 期望：主流程与校验调用点。
4. 在比较点取真实期望值：gdb 断 `strcmp`/`memcmp`，或 angr/unicorn 符号执行 → 期望：恢复出 pass 条件。
5. 写 solver 复算并重放输入 → 期望：solver 输出与程序判定一致。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：反编译工程、脚本、dump、输入样本；不覆盖题目源文件。
- `draft/notes.md`：关键函数地址、比较点、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：solver 输入让程序输出 success，或恢复的 key 能解出明文；同一输入重跑结果一致。
- 失败：仅“看起来像 flag”的字符串不算；decoy flag 未验证的标 `(unverified)`。

## References

- 深挖：[patterns.md](../../../pools/ctf-skills/ctf-reverse/patterns.md)、[anti-analysis.md](../../../pools/ctf-skills/ctf-reverse/anti-analysis.md)、[tools-dynamic.md](../../../pools/ctf-skills/ctf-reverse/tools-dynamic.md)、[unicorn-emulation.md](../../../pools/ctf-skills/ctf-reverse/unicorn-emulation.md)
- 相邻：[ctf-pwn](../ctf-pwn/SKILL.md)（要利用时）、[ctf-triage](../ctf-triage/SKILL.md)
- 外部：[dogbolt.org](https://dogbolt.org/) 多反编译器对照
- 本机工具链：`GZ_CTF\ai-toolchain\README.md`（angr 9.3.4 + Ghidra 12.1.3 无头，入口 `ctf.ps1 doctor`）。

## Anti-patterns

- 不要用 `head` 截断 triage 输出后下“没有 flag”的结论；改用 grep 过滤。
- 不要只信一个反编译器的伪代码；关键分支用 gdb 实证。
- 不要把 decoy flag 当答案；要在最终比较点验证。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

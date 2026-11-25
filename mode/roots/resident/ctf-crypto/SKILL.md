---
name: ctf-crypto
description: Use when a challenge gives ciphertext, keys, parameters, hashes or protocol and recovery needs number theory, lattice or PRNG reasoning; do not use when the core is a binary, jail or encoding puzzle.
domain: crypto
type: technique
tools: [bash, python, sage, z3]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-crypto 入口（密码学）

## When it applies

- 触发：题面给 `n/e/c`、密钥、密文、hash、椭圆曲线参数、PRNG 输出或协议流量；要求恢复明文/key。
- 前置：能本地跑 Python（pycryptodome/gmpy2/sympy）与 Sage（可选）；参数已完整记录。
- 不适用：二进制里藏算法 → [ctf-reverse](../ctf-reverse/SKILL.md)；先要取证/解包 → [ctf-forensics](../ctf-forensics/SKILL.md)；纯编码/替换谜题 → [ctf-misc](../ctf-misc/SKILL.md)。

## 5 分钟检查表

- [ ] 记录完整参数：模数位长、指数、密文长度、密钥/IV、hash 类型。
- [ ] 判断原语类别：RSA / AES / ECC / DH / Lattice / PRNG / classic。
- [ ] 小因子/共用模数/小指数等快速检查已做（`factorint`）。
- [ ] 已找到可验证判据：解出的明文格式或 MAC 校验。
- [ ] 已从决策树选定 1 个 pool 深挖文件。

## 子技术决策树

```
RSA 参数/小 e/共模/共模数       → ../../../pools/ctf-skills/ctf-crypto/rsa-attacks.md
AES 分组模式/填充 oracle/CBC    → ../../../pools/ctf-skills/ctf-crypto/modern-ciphers.md
ECC 曲线/小子群/无效曲线        → ../../../pools/ctf-skills/ctf-crypto/ecc-attacks.md
格/LWE/背包/近似             → ../../../pools/ctf-skills/ctf-crypto/lattice-and-lwe.md
MT/LCG/xorshift 输出预测      → ../../../pools/ctf-skills/ctf-crypto/prng-attacks.md
古典替换/维吉尼亚/XOR          → ../../../pools/ctf-skills/ctf-crypto/classic-ciphers.md
DH/离散对数                 → ../../../pools/ctf-skills/ctf-crypto/dh-attacks.md
未命中                       → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. 把题面参数抄成 `draft/notes.md` 的 Python 变量（`n,e,c,p,q,ct,iv`），漏参数就是漏答案。
2. `python -c "from sympy import factorint; print(factorint(n))"` 或 RSA 工具 → 期望：小因子/无因子结论。
3. `pip install pycryptodome z3-solver gmpy2` 后按原语写最小 solver；RSA 可先跑 `RsaCtfTool.py -n <n> -e <e> --uncipher <c>`。
4. solver 输出 → 用判据验证（可打印明文、PKCS 填充、MAC/签名通过）后再当候选。
5. 把“参数→结论”写成 candidate fact，注明来源命令。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：solver 脚本、参数文件、抓包；不覆盖题目源文件。
- `draft/notes.md`：参数、假设、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：solver 可重放输出确定明文；签名/MAC/填充校验通过；明文符合题面格式。
- 失败：只解出看似可读的字节串不算；无法验证的标 `(unverified)`。

## References

- 深挖：[rsa-attacks.md](../../../pools/ctf-skills/ctf-crypto/rsa-attacks.md)、[modern-ciphers.md](../../../pools/ctf-skills/ctf-crypto/modern-ciphers.md)、[ecc-attacks.md](../../../pools/ctf-skills/ctf-crypto/ecc-attacks.md)、[lattice-and-lwe.md](../../../pools/ctf-skills/ctf-crypto/lattice-and-lwe.md)
- 相邻：[ctf-forensics](../ctf-forensics/SKILL.md)（先取证再解密）、[ctf-misc](../ctf-misc/SKILL.md)（编码谜题）
- 外部：[RsaCtfTool](https://github.com/RsaCtfTool/RsaCtfTool)、[CryptoHack](https://cryptohack.org/)

## Anti-patterns

- 不要没看参数就套脚本；先确认原语与已知弱点。
- 不要擅自加 `flag{}` 或假设整批题同前缀。
- 不要把明文里的诱饵当答案；先过校验。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

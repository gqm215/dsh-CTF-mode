---
name: ctf-forensics
description: Use when a challenge ships a disk image, memory dump, pcap, log, photo or document and the answer hides in artifacts; do not use when the core is cryptanalysis, exploitation or an encoding puzzle.
domain: forensics
type: technique
tools: [bash, python, tshark, binwalk, volatility3]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-forensics 入口（取证）

## When it applies

- 触发：附件是磁盘镜像、内存 dump、pcap、日志、图片、文档、录音；要求恢复隐藏文件/流量/时间线。
- 前置：可安装 binwalk/tshark/volatility3/sleuthkit；样本在 `tmp/<chal>/`，原始件只读。
- 不适用：解出加密块后做数学 → [ctf-crypto](../ctf-crypto/SKILL.md)；恶意样本行为分析 → [ctf-malware](../ctf-malware/SKILL.md)；纯编码谜题 → [ctf-misc](../ctf-misc/SKILL.md)；需要逆向二进制 → [ctf-reverse](../ctf-reverse/SKILL.md)。

## 5 分钟检查表

- [ ] `file <evidence>`、`exiftool <evidence>`、`binwalk <evidence>` 三连已做。
- [ ] pcap 已跑 `tshark -r <pcap> -q -z io,phs` 看协议分层。
- [ ] `strings -n 8 <evidence> | grep -iE "flag|ctf\{"` 过一遍。
- [ ] 已确认是磁盘/内存/流量/图片/音频中的哪一类，并选好工具。
- [ ] 原始件 hash 已记录，产物写 `tmp/<chal>/`。

## 子技术决策树

```
pcap/流量                 → ../../../pools/ctf-skills/ctf-forensics/network.md
图片/隐写/音频            → ../../../pools/ctf-skills/ctf-forensics/steganography.md
磁盘镜像/分区/雕复/内存    → ../../../pools/ctf-skills/ctf-forensics/disk-and-memory.md
Windows 注册表/EVTX/浏览器 → ../../../pools/ctf-skills/ctf-forensics/windows.md
Linux 主机痕迹            → ../../../pools/ctf-skills/ctf-forensics/linux-forensics.md
RF/SDR/USB 外设/硬件信号   → ../../../pools/ctf-skills/ctf-forensics/signals-and-hardware.md
解出密文但缺密钥           → [ctf-crypto](../ctf-crypto/SKILL.md)
未命中                    → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `file <evidence>` + `exiftool <evidence>` → 期望：真实类型、元数据字段（可能直接藏 flag）。
2. `binwalk <evidence>`（或 `binwalk -e`）→ 期望：内嵌镜像/压缩包/文件系统偏移。
3. pcap：`tshark -r <pcap> -q -z io,phs` 与 `tshark -r <pcap> -Y "http.request" -T fields -e http.host -e http.request.uri` → 期望：协议与可疑请求清单。
4. 磁盘：`mmls`/`fls -r`/`photorec`；内存：`vol -f <dump> windows.info` → 期望：分区表/文件列表/系统版本。
5. 把“偏移/时间/来源”写成 candidate fact，并在 `draft/notes.md` 记录未命中的死胡同。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：解包产物、carve 文件、导出流量；不覆盖原始证据。
- `draft/notes.md`：偏移、时间线、脚本、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：flag 来自可定位的 artifact（文件/offset/包序号/时间戳），抽取命令可重放。
- 失败：只在 strings 里瞥见过、无法定位来源的，标 `(unverified)`。

## References

- 深挖：[steganography.md](../../../pools/ctf-skills/ctf-forensics/steganography.md)、[network.md](../../../pools/ctf-skills/ctf-forensics/network.md)、[disk-and-memory.md](../../../pools/ctf-skills/ctf-forensics/disk-and-memory.md)、[windows.md](../../../pools/ctf-skills/ctf-forensics/windows.md)
- 相邻：[ctf-crypto](../ctf-crypto/SKILL.md)、[ctf-malware](../ctf-malware/SKILL.md)、[ctf-triage](../ctf-triage/SKILL.md)
- 外部：[Volatility 3 docs](https://volatility3.readthedocs.io/)、[Wireshark display filters](https://www.wireshark.org/docs/dfref/)

## Anti-patterns

- 不要 `hexdump`/`cat` 整个大文件刷屏；按结构或 grep 定位。
- 不要在宿主机运行可疑样本；样本只在隔离环境分析。
- 不要停在第一个 `flag` 字样的诱饵上；要能定位来源并验证。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

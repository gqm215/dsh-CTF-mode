# 路由表与 triage 协议（模板）

## 入口约束

- 模型可见入口 ≤14 个；catalog 只放入口，不放深挖包。
- 每个入口 description：`Use when …; do not use when …`；禁止写流程。
- 深挖包 `disable-model-invocation: true`，只给 `/名称` 或 V2 搜索工具。

## triage 四列表

| 类别 | 首步探针（可观察） | 一句话覆盖 | 参考入口 |
|---|---|---|---|
| web | HTTP/URL/源码；`curl -I` 有响应 | 认证/注入/SSRF/上传/反序列化/竞态 | `/ctf-web` |
| pwn | ELF + 远程服务；`checksec` 有保护信息 | 栈/堆/格式化串/ROP/沙箱 | `/ctf-pwn` |
| reverse | 二进制/字节码/APK/固件；`file` 非常规文档 | 静态/动态/反混淆/VM | `/ctf-reverse` |
| crypto | 数学/密钥/协议；题面给参数/密文 | RSA/ECC/格/AES/PRNG | `/ctf-crypto` |
| forensics | 磁盘/内存/流量/日志/图片 | 雕复/PCAP/内存/时间线 | `/ctf-forensics` |
| misc | 编码/沙箱/游戏/杂项；以上都不像 | 编码/pyjail/交互 | `/ctf-misc` |
| ai-ml | 权重/prompt/对抗样本 | 权重扰动/注入/窃取 | `/ctf-ai-ml` |
| malware | 可疑样本/家族 | 静态/动态/YARA（不运行） | `/ctf-malware` |
| osint | 人/组织/域名/公开信息 | 搜索/关联/元数据 | `/ctf-osint` |

> 按"目标表面"判类，不按关键词堆砌；一条题可有多候选，给置信度与首选/备选。

## 目标表面决策树

```
远程服务 + 崩溃/内存行为 → pwn
远程服务 + HTTP 语义     → web
附件 + 二进制/字节码      → reverse（先 triage，再决定是否 pwn）
附件 + 密文/参数/数学     → crypto
附件 + 镜像/PCAP/日志     → forensics
权重/prompt/模型文件      → ai-ml
样本/可疑脚本             → malware（只分析）
人/组织/域名              → osint
都不匹配                  → misc（fallback，不是默认起点）
```

## 止损与重路由

- 2 次同类失败 → 换工具/换子目标。
- 3 次无进展 → REROUTE：回 triage，换类别候选。
- 仍无 → PARK：写 dead end（scope/tests/invariant/reopen if），转向下一题。
- 升级前把当前状态压成 ≤1,000 token case file。

## 路由评测（expected/forbidden）

```
case: "给了 64 位 ELF 和远程 nc，程序有栈溢出"
expected: /ctf-pwn
forbidden: /ctf-web, /ctf-forensics

case: "给了 pcap，里面是加密流量"
expected: /ctf-forensics
forbidden: /ctf-crypto（先取证再 crypto）
```

目标：10 条题面首选 ≥8/10；forbidden 命中 0。

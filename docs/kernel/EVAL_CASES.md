# 评测用例与指标（模板）

## 1. 路由评测（expected/forbidden）

```yaml
- id: route-001
  prompt: "给了 64 位 ELF + 远程 nc，程序有栈溢出"
  expected: [ctf-pwn]
  forbidden: [ctf-web, ctf-forensics]
- id: route-002
  prompt: "给了 pcap，流量里有一段加密 payload"
  expected: [ctf-forensics]
  forbidden: [ctf-crypto]
- id: route-003
  prompt: "给了 safetensors 权重和一段 prompt"
  expected: [ctf-ai-ml]
  forbidden: [ctf-reverse]
```

指标：首选命中率 ≥90%；forbidden 命中 = 0；不确定时允许给 2 候选（算部分分）。

## 2. 技能质量 lint

- frontmatter：name 与目录一致、description 含 Use when/do not use、license。
- 长度：正文 ≤200 行 / ≤6KB；references 链接存在。
- 负触发：每个入口 ≥1 条；fallback 声明"不是默认起点"。
- 验证段：必须有可观察的 Verify success；不得只有"完成分析"。

## 3. 四配置对照

| 配置 | 内容 |
|---|---|
| C0 | 裸 agent（无技能、无状态、无验证门） |
| C1 | + 常驻入口（路由） |
| C2 | + 路由 + references/搜索 |
| C3 | + 路由 + references + 验证门 + 状态平面 |

同题集 ≥3 次，记录：

| 指标 | 说明 |
|---|---|
| solve rate | 已解/总数 |
| first-solve time | 首次 Accepted 用时 |
| tokens / cost | 每题 input+output+cache |
| turns | 模型轮次 |
| wrong submissions | 错误提交数（目标 0） |
| context events | 压缩次数、峰值、事实保留率、漂移/重复尝试 |
| route accuracy | expected/forbidden 命中 |
| verify catches | 验证门拦截的假阳性数 |

## 4. 验收门

- C3 solve ≥ C0（不能变差）；错误提交 0。
- C3 token/题 ≤ 预算；压缩后早期 fact 可检索（抽查 5 条）。
- 路由 ≥8/10；lint 全过；至少 1 个技能改动回归通过。
- 负结果照实记录（技能没提升也要写）。

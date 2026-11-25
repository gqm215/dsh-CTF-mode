---
name: ctf-osint
description: Use when a challenge asks to identify a person, place, domain, account or image from public sources and metadata; do not use when local artifacts alone suffice or active exploitation is needed.
domain: osint
type: technique
tools: [bash, curl, exiftool, dig, python]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-osint 入口（公开情报）

## When it applies

- 触发：题面要求定位人/地点/账号/域名/组织，附件是图片/截图/昵称/hash/坐标；答案在公开来源。
- 前置：有网络访问；允许搜索公开信息；只在题目授权范围内调查。
- 不适用：本地文件/流量即可解 → [ctf-forensics](../ctf-forensics/SKILL.md)；需要打 HTTP 服务 → [ctf-web](../ctf-web/SKILL.md)；发现恶意样本 → [ctf-malware](../ctf-malware/SKILL.md)。

## 5 分钟检查表

- [ ] 明确要找什么：人/地点/域名/账号/时间，写成可验证问题。
- [ ] 图片先 `exiftool`/`identify -verbose`；文件先识别 32/40/64 hex 类型。
- [ ] 域名先 `dig +short -t txt|cname|mx` 与 `whois`。
- [ ] 至少做过一次反向图搜/用户名枚举/Wayback 查询。
- [ ] 每个结论都记来源 URL + 抓取时间。

## 子技术决策树

```
图片/地点/EXIF/街景/坐标   → ../../../pools/ctf-skills/ctf-osint/geolocation-and-media.md
社交账号/用户名/帖子/时间线 → ../../../pools/ctf-skills/ctf-osint/social-media.md
DNS/WHOIS/GitHub/Wayback   → ../../../pools/ctf-skills/ctf-osint/web-and-dns.md
需要浏览器渲染/截图交互     → ../../../pools/ctf-skills/ctf-osint/tools-mcp.md
拿到样本/beacon 要分析      → [ctf-malware](../ctf-malware/SKILL.md)
未命中                     → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `exiftool <img>` / `identify -verbose <img> | head -40` → 期望：GPS/相机/软件/时间等元数据。
2. `dig +short -t txt <domain>`、`dig +short -t cname <domain>`、`whois <domain>` → 期望：TXT/CNAME/注册信息线索。
3. 反向图搜（Google Lens/TinEye/Yandex）或用户名枚举（whatsmyname）→ 期望：候选地点/账号。
4. 每个候选再用第二个独立来源交叉验证（Wayback/官网/地图/社交原帖）→ 期望：一致证据。
5. 结论写成 candidate fact，附 URL、抓取时间与置信度；不确定就标 `(unverified)`。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：截图、下载页面、元数据导出、脚本；不覆盖题目源文件。
- `draft/notes.md`：检索式、候选答案、来源 URL + 时间、candidate facts。
- `final/flag.txt`：verified 候选 + 来源（URL/文件/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：≥2 个独立公开来源互相印证同一结论，URL 与抓取时间可复查。
- 失败：单一来源/缓存页面/“看起来像”的，标 `(unverified)`。

## References

- 深挖：[geolocation-and-media.md](../../../pools/ctf-skills/ctf-osint/geolocation-and-media.md)、[social-media.md](../../../pools/ctf-skills/ctf-osint/social-media.md)、[web-and-dns.md](../../../pools/ctf-skills/ctf-osint/web-and-dns.md)
- 相邻：[ctf-forensics](../ctf-forensics/SKILL.md)、[ctf-web](../ctf-web/SKILL.md)、[ctf-triage](../ctf-triage/SKILL.md)
- 外部：[Wayback Machine](https://web.archive.org/)、[whatsmyname](https://whatsmyname.app/)、[Shodan](https://www.shodan.io/)

## Anti-patterns

- 不要编造来源或把推测写成人/地点结论；必须附 URL。
- 不要只靠单一来源；要交叉验证并记录时间。
- 不要把调查扩展到题目授权范围之外（不碰真实个人隐私）。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

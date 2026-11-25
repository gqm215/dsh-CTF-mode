---
name: ctf-web
description: Use when a challenge gives a URL, HTTP service or web source with request, session, upload or client-side surface; do not use when the core is memory corruption, packet carving or cryptanalysis.
domain: web
type: technique
tools: [bash, python, curl, ffuf, sqlmap]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-web 入口

## When it applies

- 触发（可观察）：题面给 URL/域名/端口且 `curl -I` 有响应；或给 web 源码/备份，行为是 HTTP 语义。
- 前置：容器已启动、目标可达；只在题目给定范围内请求。
- 不适用：二进制内存破坏 → `/ctf-pwn`；pcap/磁盘/日志 → `/ctf-forensics`；JWT 数学/自定义 MAC → `/ctf-crypto`；公开情报 → `/ctf-osint`。

## 5 分钟检查表

- [ ] `curl -sI <url>` 记下状态码、Server、Set-Cookie、重定向链。
- [ ] 读 `/robots.txt`、`/sitemap.xml`、`/.git/`、`/.env` 与 JS bundle 里的路由/API。
- [ ] 每个功能点抓一组正常请求/响应，再变异动词、Content-Type、参数。
- [ ] 至少一个 primitive（报错回显/302 绕过/文件读/注入回显）可重复触发。
- [ ] 已从本页决策树选定 1–2 个 pool 深挖文件。

## 子技术决策树

```
SQL 报错/过滤/状态依赖   → ../../../pools/ctf-skills/ctf-web/sql-injection.md
模板/文件读/SSRF/命令执行 → ../../../pools/ctf-skills/ctf-web/server-side-exec.md
XSS/CSP/admin bot/前端    → ../../../pools/ctf-skills/ctf-web/client-side.md
会话/JWT/OAuth/越权       → ../../../pools/ctf-skills/ctf-web/auth-jwt.md
Node 原型链/VM 沙箱       → ../../../pools/ctf-skills/ctf-web/node-and-prototype.md
未命中                    → 回 `/ctf-triage` 换类别候选
```

## Method（首步协议）

1. `curl -sI <url>` 与 `curl -s <url>/robots.txt` → 期望：状态码、Server、Cookie、Disallow 路径。
2. `curl -s <url> | grep -oE '(src|href)="[^"]+"|/api/[A-Za-z0-9_/-]+' | sort -u` → 期望：JS/API 清单。
3. 对每个 API 用 `curl -v -X POST -H 'Content-Type: application/json' -d '{}'` 变异 → 期望：状态/报错差异，建立输入→输出 primitive。
4. 观察写成 candidate fact（`python ~/.agents/ctf-mode/bin/ctfboard.py fact add ...`），不要直接下结论。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：请求脚本、payload、抓包、下载附件；不覆盖题目源文件。
- `draft/notes.md`：candidate facts、死胡同、下一步指针。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：同一请求重放两次都返回 flag 或同一关键响应；来源可定位（响应体/文件/DB）。
- 失败：HTTP 200、页面刷新、报错消失都不算；未复现的标 `(unverified)`。

## References

- 深挖：[sql-injection.md](../../../pools/ctf-skills/ctf-web/sql-injection.md)、[server-side-exec.md](../../../pools/ctf-skills/ctf-web/server-side-exec.md)、[auth-and-access.md](../../../pools/ctf-skills/ctf-web/auth-and-access.md)
- 相邻：[ctf-pwn](../ctf-pwn/SKILL.md)（拿到 RCE 后做内存利用）、[ctf-triage](../ctf-triage/SKILL.md)（类别再路由）
- 外部：[PortSwigger Web Security Academy](https://portswigger.net/web-security)
- 登录爆破硬规则（用户名固定 admin、密码只用现成 Kali 字典）见 [auth-and-access.md](../../../pools/ctf-skills/ctf-web/auth-and-access.md)，不要自造字典或爆破脚本。

## Anti-patterns

- 不要没建立 primitive 就全站 fuzz；先抓正常请求做对照。
- 不要把工具报错或猜测写成 fact；candidate 必须带 evidence。
- 不要重复已记录死胡同（除非 reopen_if 成立）；3 次无进展回 `/ctf-triage`。

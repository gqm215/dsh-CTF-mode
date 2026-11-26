# Burp MCP 接线（需一次 GUI 操作）

Burp 本体已装好，扩展 jar 已备，但**最后一步是 UI 开关**，Agent 无法替代。

## 现状
| 项 | 值 |
|---|---|
| Burp | `C:\Users\Geqim\AppData\Local\Programs\BurpSuiteCommunity\BurpSuiteCommunity.exe`（2026.3.1） |
| 启动入口 | `D:\CTF\Toolchain\bin\burp.cmd` |
| MCP 扩展 jar | `D:\SecTools\GUI\burp-mcp-all.jar`（官方 BApp，MCP Server 1.4.0 / SerialVersion 12） |
| 已下载原始 BApp | `D:\SecTools\GUI\burp_mcp_server.bapp` |
| 预期端点 | `http://127.0.0.1:9876`（SSE） |

## 三步启用
1. 启动 Burp：`burp`（或双击开始菜单）。
2. `Extensions → Installed` 里若没有 `MCP Server`：`Add → Java →` 选 `D:\SecTools\GUI\burp-mcp-all.jar`。
3. 打开顶部 `MCP` 标签页 → 勾选启用服务 → 记下端口与 token（若界面上有）。

启用后 9876 会监听，回来告诉我，我把 MCP 客户端配置（stdio 代理或 HTTP/SSE）接上并写进 registry。

## 为什么不能全自动
- 扩展加载配置（`--config-file` / `--user-config-file` 的 `extender.extensions`）试过两种写法，Burp 静默忽略，没有日志可查；
- MCP 服务默认关闭，必须在 UI 里点开；
- Burp 是 Swing GUI，没有可用的事件循环接口供脚本注入。

## 备选（如果你不想点）
- 我可以改用 Burp 内置的 REST API（`misc.api`，默认关闭且 Community 限制多），能力远小于 MCP 扩展；
- 或者 Web 方向先用 `sqlmap + ffuf + mitmproxy + curl` 组合，Burp 仅作手动工具。

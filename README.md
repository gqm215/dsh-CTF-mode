# DSH CTF Mode

DeepSeek Harness（DSH）的 CTF 解题模式：**预设插件 + 12 入口技能 + 按题黑板 + 快车道提交 + 独立监察审计**。

本仓库是实验产物的整理版，不含任何账号凭据、flag、浏览器 profile 与平台运行记录。

## 组成

| 目录 | 内容 |
|---|---|
| `bundle/dsh-ctf-core/` | DSH bundle（agent preset `ctf`）：人格、技能提供器、黑板/工具/入口注册 |
| `mode/` | 模式运行时：SPEC / PROTOCOL / 12 入口技能 / 平台适配器（gzctf、CTFy、DataCon）/ 黑板 / 监察审计 / 预算 / 知识检索 / 路由评测 |
| `docs/` | 设计与实施报告、内核方法论、验收记录、内核模板 |
| `examples/` | 实验任务提示词示例（自然指令版） |

## 安装（概要）

1. 在 DSH 中安装 `bundle/dsh-ctf-core`（本地路径 bundle 安装，插件管理里启用）。
2. 把 `mode/` 内容部署到 `~/.agents/ctf-mode/`，复制 `config.example.yaml` 为 `config.yaml` 并按需修改。
3. 平台适配器按需准备只读凭据文件（仓库不含凭据）：
   - gzctf：`~/.gzctf/session.json`（`gzctf` CLI 登录产生）
   - CTFy：`~/.ctfy/api_token.txt`
   - DataCon：`~/.datacon/session.json`（`tools/datacon_login.py` 一次性浏览器登录导出）
4. 新建会话选择 `ctf` 预设。

## 验证（本机 2026-11-25 验收，非平台承诺）

- 入口技能 lint **12/12**；路由评测 10 例，accuracy 9/10、forbidden 0；
- 黑板 e2e **66/66**；CTFy 适配器契约 **23/23**；监察审计 **7/7**；
- 真实平台用例：CTFy SAMPLE-005 附件题 Accepted（1 次提交 0 错误）、SAMPLE-020 三问全对；DataCon 训练营 CTF 142 / 22 两题 Accepted。

## 实测得到的平台注意事项

- DataCon 训练营有并发/速率限制：客户端应**单飞**（同时 1 个请求）、间隔 0.5–1s、5xx 指数退避；
  `500 获取附件失败` / `提交flag失败,操作异常` 多为限流外壳，单发可复现才算真实错误。
- CTFy 实践区实例节点可能不可用；模式提供 `tools/preflight.py` 与 `tools/qa_runner.py` 等辅助。
- gzctf 与 CTFy 的登录态/Token 需要定期刷新，凭据只存本机指定文件。

## 安全边界

- 仓库不含凭据、flag、cookie、session、浏览器 profile、平台运行目录（`runs/`、`traces/`、`pools/` 均已被忽略）。
- 适配器只读取本机凭据文件；日志与黑板只存 flag 的 sha256（flag 只写入运行目录的 `final/`）。
- 平台交互须遵守目标平台规则；监察审计（`bin/ctf-audit.py`）用于行为纪律复核，不判 flag 对错。

## 状态

实验性研究项目；接口与实现可能变化。提交平台包括 DSH agent preset、SSE/REST 适配器、黑板与审计工具。

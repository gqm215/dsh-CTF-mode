# DSH CTF Mode

DeepSeek Harness（DSH）的 CTF 解题模式：**可安装的 DSH bundle（agent preset `ctf`）** + 模式运行时（12 入口技能 / 按题黑板 / 快车道提交 / 独立监察审计 / 知识检索）+ 设计文档与评测资产。

本仓库不含任何账号凭据、flag、浏览器 profile 与平台运行记录。

## 安装（DSH 插件管理 → 添加插件 → GitHub 地址）

本仓库根目录就是可安装的 bundle 包（`package.json` 的 `dsh.bundle.patch` 指向 `cordis.patch.yml`）。

**方式 A：跟随 main（每次更新后重装即生效）**

```text
github:gqm215/dsh-CTF-mode
```

**方式 B：钉住完整 commit（插件管理里可显示/执行 git 更新）**

```text
github:gqm215/dsh-CTF-mode#77760111b2365c171e2a3aba4d8448117478b943
```

**方式 C：本地目录**（开发时用）：把仓库根目录绝对路径填进“添加插件”。

- 兼容性：`engines.dsh = "0.2.2-rc.5"`，即只承诺与本机当前 DSH 版本兼容；DSH 升级后需要重测并更新该字段。
- 可选：发布到 npm 后可直接输包名 `dsh-ctf-mode` 安装；当前 GitHub 来源方式不依赖 npm。
- 已用 pnpm 11.24 从 GitHub 实测该 spec 可安装为 `dsh-ctf-mode@1.0.5`（manifest、patch、locale、icon、mode 均随包拉取）。

安装后新建会话选择 **CTF** 预设。bundle 只安装预设；模式运行时仍需部署到 `~/.agents/ctf-mode/`：

```text
mkdir %USERPROFILE%\.agents\ctf-mode
copy mode\* 到 %USERPROFILE%\.agents\ctf-mode\
copy mode\config.example.yaml 为 config.yaml
```

## 组成

| 目录 | 内容 |
|---|---|
| `package.json` / `cordis.patch.yml` | 可安装 bundle：声明 agent preset `ctf` 及其 16 个插件行 |
| `locale/`、`icon.svg`、`docs/DETAIL.md` | 插件管理里的标题/描述/详情页/图标 |
| `mode/` | 模式运行时：SPEC / PROTOCOL / 12 入口技能 / 平台适配器 / 黑板 / 监察审计 / 预算 / 路由评测 / config.example.yaml |
| `docs/` | 设计与实施报告、内核方法论、验收记录、内核模板 |
| `examples/` | 自然指令版实验提示词 |

## 验证（本机 2026-11-25 验收，非平台承诺）

- 入口技能 lint **12/12**；路由评测 10 例，accuracy 9/10、forbidden 0；
- 黑板 e2e **66/66**；CTFy 适配器契约 **23/23**；监察审计 **7/7**；
- 真实平台用例：CTFy SAMPLE-005 Accepted（1 次提交 0 错误）、SAMPLE-020 三问全对；DataCon 训练营 CTF 142 / 22 两题 Accepted。

## 平台注意事项（实测）

- DataCon 训练营有并发/速率限制：客户端应单飞（同时 1 个请求）、间隔 0.5–1s、5xx 指数退避；
  `500 获取附件失败` / `提交flag失败,操作异常` 多为限流外壳，单发可复现才算真实错误。
- gzctf / CTFy / DataCon 的登录态或 Token 需定期刷新；凭据只存本机指定文件，不出仓库。

## 安全边界

- 仓库不包含凭据、flag、cookie、session、浏览器 profile 与 `runs/`、`traces/`、`pools/`。
- 适配器只读本机凭据；日志与黑板只存 flag 的 sha256（flag 只写入运行目录的 `final/`）。
- 监察审计（`mode/bin/ctf-audit.py`）只做行为纪律复核，不判定 flag 对错。

## 状态

实验性研究项目；接口与实现可能变化。

# DSH CTF Mode

安装本 bundle 后，DSH 会新增一个 **CTF** agent 预设：12 个模型可调用的入口技能（triage、web、pwn、reverse、crypto、forensics、misc、ai-ml、malware、osint、blackboard、submit）+ 按题黑板状态 + 快车道提交（平台判定即验证）+ 独立监察审计。

## 它做什么

- 入口路由与知识检索：只常驻 12 个入口，500+ 深层技能通过 `skillctl ctf search` 按需读取，控制上下文成本。
- 按题黑板：`ctfboard.py` 记录 candidate / verified / dead-end / 提交账，支持多 agent 共享状态。
- 快车道提交：`ctfy.py`、`ctf-submit.py`、`datacon.py` 适配器把"执行证据 → 提交 → 平台判定"打通，Accepted 自动落产物并打印醒目 banner。
- 监察审计：`ctf-audit.py` 检查 provenance、governor、幂等、flag 落点、凭据外泄、工具完整性、会话行为；不判 flag 对错。

## 安装后还需要什么

bundle 只安装预设。模式运行时（12 个入口技能、工具脚本、模板）需要放到 `~/.agents/ctf-mode/`，并把 `mode/config.example.yaml` 复制为 `config.yaml`。

## 兼容性与安全

- `engines.dsh = "0.2.2-rc.5"`：只承诺与当前 DSH 版本兼容。
- 仓库不含任何凭据或 flag；平台凭据由本机对应工具单独产生，适配器只读不写。
- 平台交互遵守目标平台规则与限流。

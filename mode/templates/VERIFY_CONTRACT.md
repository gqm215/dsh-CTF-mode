# 验证契约（模板）

## 铁律

**没有 fresh evidence，不得声称完成/正确/已解。**
"should work"、"agent 说成功"、HTTP 200、平台页面刷新了——都不算。

## 三层验证

### L1 语法/自检
- 脚本 `--help`/`-T`/lint/schema 通过；输入输出格式符合题面。
- 例：`suricata -T`、`python -m py_compile`、`jq .`、`checksec`。

### L2 本地复现
- 重跑 exploit/脚本，同输入同输出；独立环境（WSL/Docker）再跑一次。
- 产物 hash 前后一致；候选 flag 来源可定位（文件/offset/命令输出）。
- 记录：命令、完整输出（或路径）、exit code、hash、时间。

### L3 平台判定
- `submit` 只用 verified 候选；轮询最终状态/已解 ID。
- 不把 HTTP 200 当 Accepted；不提交假 flag 探测接口。

## 证据记录模板

```markdown
## Claim
<一句话结论>

## Evidence
- command: `<exact command>`
- output: `<full output or path>`
- exit: 0
- artifact: `<path>` sha256: <hash>
- reproduced: yes (local) / yes (WSL) / no
- timestamp: 2026-11-24T... 

## Verdict
verified | candidate | rejected
```

## 提交 governor

- 只提交 verified；每题一个提交负责人。
- ≤3 次尝试：需用户批准；≤10 次：需独立复核。
- 格式：保留程序实际输出/题面要求，不擅自加 `flag{}`，不假定同前缀。
- 完成后逐题 `Accepted` + 已解 ID；总分/解出人数不作数。

## 验证衰减

- 验证结果带时间戳；工具/规则/版本变更后旧验证失效。
- 未验证结论必须标 `(unverified)`；不能混入 verified facts。
- 对"元技能"（检测规则、exploit 脚本）也适用：先双向测试（触发/不触发），再发布。

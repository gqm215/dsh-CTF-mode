# CTF Agent 内核模板（Kernel v0.1）

这套模板是 `reports/CTF-Agent-内核方法论.md` 的可复制版本，用于创建 DSH-CTF 模式时直接取用。

| 文件 | 用途 |
|---|---|
| `SKILL_TEMPLATE.md` | 单个入口/深挖技能的解剖模板（frontmatter + 六段 + 输出契约） |
| `ROUTER_TABLE.md` | triage 路由表、目标表面决策树、reroute/止损规则 |
| `STATE_SCHEMA.md` | 状态平面 schema（Fact/DeadEnd/Intent/Activity/Resource/Review），黑板或文件式 |
| `VERIFY_CONTRACT.md` | 三层验证、证据记录、提交 governor、验证衰减 |
| `EVAL_CASES.md` | expected/forbidden 路由用例 + 四配置评测指标 |
| `category.yaml.template` | 类别入口扩展清单 |
| `pack.yaml.template` | 深挖包扩展清单 |

使用原则：**内核只保留不变量；知识写进技能正文与 references，随题丢弃。**

```powershell
# 新建一个类别入口的骨架（V1 手工；V2 交给 skillctl ctf new-category）
mkdir %USERPROFILE%\.agents\ctf-mode\roots\resident\ctf-<category>
copy kernel\SKILL_TEMPLATE.md %USERPROFILE%\.agents\ctf-mode\roots\resident\ctf-<category>\SKILL.md
```

命名约定：`ctf-<category>`（入口）、`<category>-<technique>`（深挖包）、`ext-<kind>-<id>`（扩展）。

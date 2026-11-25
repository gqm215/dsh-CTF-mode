# extensions/ — 扩展注册区（不改核心）

内核只认清单；新增能力只加目录 + manifest，然后 `python ~/.agents/tools/skillctl.py ctf index` 重生成索引。
扩展失败只标记 `degraded`，核心 triage/执行仍可用。

| 扩展类型 | 放置 | 清单 schema | 加载 |
|---|---|---|---|
| 新类别入口 | `roots/resident/ctf-<id>/` + `extensions/categories/` | `schemas/category.schema.json` | 进 resident root + index + triage 表 |
| 新深挖包 | `roots/packs/<cat>/<id>/` + `extensions/packs/` | `schemas/pack.schema.json` | index + 搜索；默认 `user-only`，不进 catalog |
| 新工具 | 独立 bundle `dsh-ctf-ext-<id>/` | `schemas/tool.schema.json` | 独立安装的 profile patch |
| 新平台适配 | 独立 bundle `dsh-ctf-ext-platform-<id>/` | `schemas/adapter.schema.json` | 独立 bundle |
| 新验证后端 | `extensions/verifiers/` | `schemas/verifier.schema.json` | 核心验证链按序追加 |

模板在 `templates/category.yaml.template`、`templates/pack.yaml.template`；命名约定：
`ctf-<category>`（入口）、`<category>-<technique>`（深挖包）、`ext-<kind>-<id>`（扩展）。

硬规则：

- 深挖包默认 `disable-model-invocation: true`，只经 `skillctl ctf show` 或 `/名称` 访问；
- 红/蓝/AI 包默认 user-only，C2/凭据攻击类不进默认扩展集；
- 清单必须带 `provenance`（source/license/hash）与 `permissions`（工具/网络/凭据）；
- 卸载任一扩展后核心回归必须通过，Standard preset 行为不变；
- 不在技能包里存 API key / cookie，不把 flag/token 写进 trace。

当前无已注册扩展（空目录合法）。新增类别的最小步骤见 `SPEC.md` §2。

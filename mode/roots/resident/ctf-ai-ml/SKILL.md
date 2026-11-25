---
name: ctf-ai-ml
description: Use when a challenge ships model weights, an inference API, prompts or adversarial examples targeting an ML system; do not use when the model is only a binary to reverse or the math is plain crypto.
domain: ai-ml
type: technique
tools: [bash, python, torch, transformers]
license: MIT
stability: learning
schema_version: 1
disable-model-invocation: false
user-invocable: true
---

# ctf-ai-ml 入口（AI/ML）

## When it applies

- 触发：附件是 `.pt/.pth/.onnx/.safetensors/.h5` 或 HuggingFace 目录；题面给 LLM API/chat 端点、prompt、对抗样本提交入口。
- 前置：Python + torch/transformers/safetensors 可装；有权读权重或调用推理接口。
- 不适用：ONNX/自定义推理二进制需要反编译 → [ctf-reverse](../ctf-reverse/SKILL.md)；纯数论/格 → [ctf-crypto](../ctf-crypto/SKILL.md)；只是用 ML 包装的 jail/编码 → [ctf-misc](../ctf-misc/SKILL.md)。

## 5 分钟检查表

- [ ] `file model.*` 与目录结构（config.json/tokenizer/权重分片）已看。
- [ ] 已列出模型 key/shape：`torch.load` 或 `safe_open` 打印 keys。
- [ ] 已确认任务类型：权重分析 / 对抗样本 / LLM 注入 / 模型窃取。
- [ ] 本地能前向推理并得到可比对的输出。
- [ ] 已从决策树选 1 个 pool 深挖文件。

## 子技术决策树

```
权重被微调/扰动、行为被抑制 → ../../../pools/ctf-skills/ctf-ai-ml/model-attacks.md
需要误分类/对抗补丁/投毒     → ../../../pools/ctf-skills/ctf-ai-ml/adversarial-ml.md
prompt 注入/jailbreak/工具滥用 → ../../../pools/ctf-skills/ctf-ai-ml/llm-attacks.md
要偷参数/成员推断/查询重建    → ../../../pools/ctf-skills/ctf-ai-ml/model-attacks.md
加载器是二进制/自定义格式     → [ctf-reverse](../ctf-reverse/SKILL.md)
未命中                       → 回 [ctf-triage](../ctf-triage/SKILL.md)
```

## Method（首步协议）

1. `file model.*` 并 `python -c "import torch; m=torch.load('model.pt',map_location='cpu'); print(type(m)); print(list(m))"` → 期望：state_dict 结构/键名。
2. safetensors：`python -c "from safetensors import safe_open; f=safe_open('x.safetensors','pt'); print({k:f.get_tensor(k).shape for k in f.keys()})"` → 期望：shape 清单。
3. 跑一次基准推理，记录正常输入输出 → 期望：可复现 logits/文本。
4. 按任务改一个变量：权重对比（`(a-b).abs().max()`）、对抗优化（FGSM/PGD）或 prompt 注入 → 期望：输出朝目标移动。
5. 把“输入→输出变化”写成 candidate fact；需要提交的对抗样本/flag 先本地判定。

```
需要入口页未覆盖的技法时：
1) python ~/.agents/tools/skillctl.py ctf search "<技术词/工具输出/报错串>"
2) read <返回的 SKILL.md 路径>      # 只读命中项，不要整库加载
3) 按该包的 Method/Verify 执行；把新 fact 写黑板
4) 无结果 → 回本页决策树，不要空转
```

## Output contract

- `tmp/<chal>/`：模型副本、推理脚本、对抗样本、日志；不覆盖原始权重。
- `draft/notes.md`：结构/shape、超参、candidate facts、死胡同。
- `final/flag.txt`：verified 候选 + 来源（命令/文件/offset/hash）。
- `final/writeup.md`：可复现步骤；未验证结论标 `(unverified)`。
- `verify.md`：claim/command/output/exit/artifact hash/reproduced/verdict。
- 规则：candidate ≠ verified；只有 `checker-*` 写 verified；无 fresh evidence 不声称已解。

## Verify success（可观察）

- 成功：固定的 seed/输入下重跑得到同一输出；目标行为（误分类/泄露/注入成功）可稳定复现。
- 失败：远程 API 返回一句“flag”不算；未经本地/回放验证的标 `(unverified)`。

## References

- 深挖：[model-attacks.md](../../../pools/ctf-skills/ctf-ai-ml/model-attacks.md)、[adversarial-ml.md](../../../pools/ctf-skills/ctf-ai-ml/adversarial-ml.md)、[llm-attacks.md](../../../pools/ctf-skills/ctf-ai-ml/llm-attacks.md)
- 相邻：[ctf-reverse](../ctf-reverse/SKILL.md)、[ctf-crypto](../ctf-crypto/SKILL.md)、[ctf-triage](../ctf-triage/SKILL.md)
- 外部：[PyTorch docs](https://pytorch.org/docs/stable/index.html)、[HuggingFace Transformers](https://huggingface.co/docs/transformers)

## Anti-patterns

- 不要为了跑模型盲目装一堆重依赖；先 `file`/metadata 判断格式。
- 不要相信“模型说 flag 是 …”的记录；要能重放。
- 不要忘了固定 seed 与输入 hash，否则结论不可复现。
- 不要重复已记录死胡同（除非 reopen_if 成立）。

# CTF mode — routing eval batch prompt

把下面整段作为**一条** prompt 发给 CTF preset agent（fresh session，不要给附件内容，不要提供额外背景）。
该 prompt 只考路由判断，不考解题；agent 只需输出 10 行 `id: skill`。

---

你是 CTF 路由判定器。下面是 10 道题的题面摘要（已做模糊处理，只保留目标表面与症状）。
请为每题从 12 个入口技能中选出**一个**最合适的入口。共 10 行输出，每行严格为 `route-00X: <skill-name>`，
不要解释、不要 Markdown 代码围栏、不要多余文字、不要重复 id。若某题有两个候选，只写第一选择。

可用入口（只能使用这 12 个名字）：
ctf-triage, ctf-web, ctf-pwn, ctf-reverse, ctf-crypto, ctf-forensics, ctf-misc, ctf-ai-ml, ctf-malware, ctf-osint, ctf-blackboard, ctf-submit

题目：

route-001：给了 Flask 站点源码包（app.py + templates/），远程 8081 端口能访问登录页；login 把用户名直接拼进 SQL，且 /admin 只校验 cookie 里的 role 字段。

route-002：附件是 64 位 Linux ELF chall（checksec: NX 开、Canary 关、PIE 关），另给 nc 10.10.4.2 31337；程序用 read 读 0x200 字节到 0x40 的栈缓冲区。

route-003：附件 license_check 是 63KB 的 x86-64 ELF，无远程服务；运行后提示输入序列号，错误时打印 invalid key。要求找回能通过校验的字符串。

route-004：题面给出 n、e=3、c 三个十进制大整数（params.json），没有服务器；提示 m^e < n。要求恢复明文 flag。

route-005：附件是两个 7z 压缩的 RAID5 磁盘镜像 disk.img0.7z / disk.img1.7z，要求从镜像里恢复被删除的 flag 文件。

route-006：远程服务 nc 10.10.4.2 9001 连上是一个 Python 3 交互 REPL，会拦截 import、open、eval 等关键字，要求读出 /flag。

route-007：附件是 model.safetensors 权重、tokenizer 配置和一个 playground.py；题面要求在 system prompt 里注入指令，让本地模型输出隐藏的 secret。

route-008：附件 sample.bin 是 Windows PE（.exe）；题面要求不运行样本，从样本里提取 C2 域名与加密配置，并给出 YARA 规则。

route-009：题面只给一条微博截图和一句话『这张照片摄于某年秋天的大学校园』，要求定位照片中的建筑，并找出照片里人物的公开社交账号。

route-010：附件 capture.pcap 里有一段 HTTP 流量：Cookie 是 base64，POST body 是 Java 序列化的十六进制串；既像取证还原，又像 web 反序列化利用；要求先还原链路再判断是否需要打服务。

输出（只允许这 10 行）：

route-001: <skill-name>
route-002: <skill-name>
route-003: <skill-name>
route-004: <skill-name>
route-005: <skill-name>
route-006: <skill-name>
route-007: <skill-name>
route-008: <skill-name>
route-009: <skill-name>
route-010: <skill-name>

---

## How to grade

Save the agent output verbatim to `eval/answers_<date>.txt`, then:

```powershell
python C:\Users\Geqim\.agents\ctf-mode\eval\run_routing.py C:\Users\Geqim\.agents\ctf-mode\eval\answers_<date>.txt --json --out C:\Users\Geqim\.agents\ctf-mode\eval\reports\routing_result.json
```

Gate: first-choice accuracy ≥ 0.8 **and** forbidden hits == 0. The same file is read by
`report.py` as gate G5 (absent → G5 NOT RUN).

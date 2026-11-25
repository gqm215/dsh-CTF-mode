# dsh-ctf-core

DSH CTF mode bundle. It declares one agent preset, **CTF** (`id: ctf`), for
Jeopardy-format CTF solving. The preset is declaration-only: every plugin it
mounts ships with DeepSeek Harness, and nothing in it changes the behavior of
Standard / PTC / Minimal / Cordis.

## What the preset gives a session

| Layer | Content |
|---|---|
| L1 preset | CTF persona (kernel protocol, C1/C2 discipline), agent instructions, time context, shell/fs/jobs/web tools, compaction (8192/4096/1024), subagent delegation (spawn/fork/control), skill tool |
| L2 entries | 12 model-invocable skills from `~/.agents/ctf-mode/roots/resident/`: `ctf-triage`, `ctf-web`, `ctf-pwn`, `ctf-reverse`, `ctf-crypto`, `ctf-forensics`, `ctf-misc`, `ctf-ai-ml`, `ctf-malware`, `ctf-osint`, `ctf-blackboard`, `ctf-verify` |
| L3 knowledge | 500+ deep packs under `~/.agents/ctf-mode/pools/`, never in the scan root; reached through `skillctl ctf search/show` + `index.json` |
| L4 state/verify | `~/.agents/ctf-mode/runs/<game>/<chal>/` blackboard DB, `verify.md`, telemetry |
| L5 governance | scope allow-list, credentials only in `~/.gzctf/`, 0 wrong submissions |

The skill provider is configured with `includeDefaultRoots: true`, so the CTF
session catalog is the 26 global resident skills **plus** the 12 CTF entries
(the CTF root ranks 300, so its names win same-name ties). No deep pack is ever
in a scan root — discovery stays inside the measured safe budget.

## Install

```
plugin_manager install_bundle  target = D:\AI_Lab\CTF_Agent\dsh-ctf-core
```

Then verify:

```
plugin_manager list_plugins            # include:preset-ctf -> active
dsh --profile desktop --dump-config    # contains preset-ctf with the plugin list
```

Open a new session and choose **CTF** in the preset selector. The catalog should
show the 12 `ctf-*` entries; `python ~/.agents/tools/skillctl.py ctf doctor` must
report `index OK`.

## Uninstall

```
plugin_manager remove_bundle  target = @local/dsh-ctf-core
```

## Verified (2026-11-25, DSH 0.2.2-rc.5, desktop profile)

| Check | Result |
|---|---|
| `plugin_manager list_plugins` | `include:preset-ctf` enabled, fiberPhase `active` |
| Profile change surface | `package.json`: one `link:` dependency + one bundles entry; `cordis.patch.yml` (user patch) untouched; no override of existing rows |
| Composition | temp profile (shipped web template + this patch) `--dump-config` exit 0; all 16 plugin rows of `preset-ctf` compose, persona and skill root resolve |
| 12 entries | lint 12/12 PASS (57,858 B total, each <=6 KB) |
| Knowledge index | 500 skills from 506 SKILL.md; `skillctl ctf doctor` -> `index OK`; 30/30 retrieval test |
| State / verify gate | 66/66 end-to-end checks incl. injected false positive rejected |
| Real CTF-preset session | catalog = 44 skills (`agentPreset: ctf`); model loaded `ctf-triage`, solved CTFy SAMPLE-005, submitted once -> platform `{"correct":true}`, `/me/solves` + `solved_question_ids` confirm Accepted, `attempted_wrong_question_ids=[]` |
| Platform adapter contract | `tools/test_ctfy_adapter.py` 13/13 offline checks (verified-fact gate, QA/static channel, presigned download without Authorization, 503 fail-closed, no raw flag in logs) |
| Machinery profile | catalog ~2.7k tokens/request; board commands 150-336 ms; search 143-205 ms (`tools/perf_report.md`) |

## Files

- `package.json` — bundle manifest (`dsh.bundle.patch`)
- `cordis.patch.yml` — the `preset-ctf` declaration (only content)
- `README.md`, `CHANGELOG.md`

The mode's runtime assets live outside this package under `~/.agents/ctf-mode/`
(config.yaml, index.json, roots/, pools/, bin/, schemas/, eval/). See
`~/.agents/ctf-mode/SPEC.md` for the interface contract.

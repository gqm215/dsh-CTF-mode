# CTF mode — eval harness

Offline, deterministic evaluation assets for the DSH CTF mode (SPEC §6). Nothing here calls a
model or the network; model trials are a separate, quota-gated procedure (`driver.md`).

| path | purpose |
|---|---|
| `cases/routing.yaml` | 10 labeled routing cases (web/pwn/reverse/crypto/forensics/misc/ai-ml/malware/osint + 1 ambiguous) |
| `routing_prompt.md` | single batch prompt for the routing eval (10 blurred blurbs + the 12 entry skill names) |
| `run_routing.py` | grader: first-choice accuracy, forbidden hits; gate ≥0.8 and forbidden == 0 |
| `sample_answers_10of10.txt` | fixture: correct answers (gate PASS) |
| `sample_answers_partial.txt` | fixture: 7/10 + 1 forbidden (gate FAIL) |
| `cases/challenges.yaml` | 3 archived challenges (crypto-01, rev-01, forensics-01) with known flags + deterministic checks |
| `checkers/<id>_check.py` | stdlib-only repro scripts that recompute each known flag from the attachment |
| `verify_challenges.py` | re-hashes attachments/checkers/flags and runs every `check_cmd` |
| `judge.py` | hash-only local L3 judge used by the 12 model trials (never stores the flag) |
| `report.py` | matrix + gates G1–G6 from `trials.jsonl` |
| `trials.template.jsonl` | 12-row template (C0..C3 × 3 challenges) to fill after model runs |
| `driver.md` | exact DSH task-board procedure for the 12 trials, quota warning, metric definitions |
| `reports/` | generated reports (write via `--out`; empty until a real run happens) |

## Acceptance commands (all offline)

```powershell
$EVAL = "C:\Users\Geqim\.agents\ctf-mode\eval"
python "$EVAL\run_routing.py" "$EVAL\sample_answers_10of10.txt"   # PASS, exit 0
python "$EVAL\run_routing.py" --self-test                          # SELF-TEST: PASS
python "$EVAL\report.py" --self-test                               # SELF-TEST: PASS
python "$EVAL\verify_challenges.py"                                # 3/3 verified locally
python -c "import yaml; yaml.safe_load(open(r'$EVAL\cases\routing.yaml', encoding='utf-8')); yaml.safe_load(open(r'$EVAL\cases\challenges.yaml', encoding='utf-8')); print('yaml ok')"
```

Expected rejection: `python run_routing.py sample_answers_partial.txt` → FAIL, exit 1.

## Notes

- Routing gate result for `report.py` G5 must be produced by a **real** agent run
  (`run_routing.py <answers> --json --out eval/reports/routing_result.json`). The sample fixtures
  are tests, not evidence; no `routing_result.json` is shipped.
- Challenges are referenced in place under `D:\AI_Lab\CTF_Agent\experiments\trackA\challenges\`;
  no attachments or binaries are copied into this tree.
- Do not edit flags/checkers after model trials start (`driver.md` §8).

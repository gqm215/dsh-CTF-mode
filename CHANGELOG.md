# Changelog

## 1.0.8 — 2026-11-26

- **Scope correction (user):** only waiting on a subagent is forbidden. A blocking wait that a
  command itself requires (build, download, request) is normal and must not be discouraged.
  Reworded the C2 persona and PROTOCOL bullet so "no waiting" reads as "do not wait on
  subagents", not as "never block on a command".


## 1.0.7 — 2026-11-26

- Controller discipline simplified to the event-driven rule (user-corrected): the controller
  does not wait or sleep; it dispatches, ends its turn, and acts on proactive child reports and
  completion notices. Children must report at start, at milestones, immediately on a blocker,
  and once at completion. Removed the invented `wait_agent` time caps, "silent for 5 minutes"
  numbers and the "downgrade to C1" escape: none of those were grounded rules, and downgrading
  does not fix a stuck controller (cancelling/re-dispatching does).


## 1.0.6 — 2026-11-25

- **Controller must never block (user-directed).** C2 persona and PROTOCOL now forbid
  `wait_agent` timeouts above 120s and any silent multi-minute wait: after dispatch, end the
  turn and let completion notices arrive; if a wait is unavoidable, cap it at 60–120s, then
  check status/message the child/finish the turn. A child silent for 5+ minutes must be
  status-probed or stopped/replaced and recorded as a stall. The controller must always be
  able to state current progress; never let the user hang for 30+ minutes.


## 1.0.4 — 2026-11-25

- **Role/vocabulary rename (user-directed).** The leftover "Verifier" wording no longer
  matches the model: flag correctness comes from the platform verdict, the standing third
  role is the Supervisor/Auditor (监察员), and the old Verifier survives only as an optional
  fallback. Renamed:
  - canonical evidence-writer actor prefix `verifier-*` -> **`checker-*`** (role: 复核员 /
    Re-checker); legacy `verifier-*` actors are still accepted so existing facts/logs work;
  - platform adapter actors `verifier-platform` -> `checker-platform`;
  - 12th entry `ctf-verify` -> **`ctf-submit`**（提交与判定）with all cross-references,
    routing cases, prompts, eval lists, README/SPEC/PROTOCOL updated;
  - config `state.verified_writer: checker`; `verified` status, `verify record`, `verify.md`
    keep their names (they mean evidence/confirmation, not a role).
- Regression after rename: entry lint 12/12, routing self-test 13/13 + sample 10/10,
  adapter contract 23/23, board e2e 66/66, auditor 7/7; integrity manifest re-blessed.

## 1.0.3 — 2026-11-25

- **Role model refined (user-directed):** in a time-critical CTF the standing third role is an
  independent **Supervisor / Auditor (监察员)**, not a Verifier: flag correctness comes from the
  platform verdict; the supervisor watches behavior discipline while the run is live and does a
  post-mortem accountability review on failure. Verifier stays only as an optional fallback when
  the platform channel is unavailable.
- New `bin/ctf-audit.py`: audits provenance basis, governor counter, submission idempotency,
  acceptance consistency (no claimed success without a verdict), flag placement, credential
  hygiene, tooling integrity (mode files untouched during a solve; optional blessed manifest) and
  session conduct (process interference, out-of-adapter submissions). Exit 1 = BREACH. It never
  judges flag correctness and never blocks a submission.
- `PROTOCOL.md` roles/topology/metrics updated (T3 = Controller-Executor-Supervisor, behavioral
  metrics §7.1); persona supervision bullet added; `--bless` integrity manifest shipped.
- Tests: auditor offline suite 6/6; adapter contract 23/23; board e2e 66/66; entry lint 12/12.

## 1.0.2 — 2026-11-25

- **Submit-first policy (user-directed)**: the platform verdict IS the verification.
  A conclusive execution result may be submitted immediately
  (`ctfy.py submit|submit-qa --auto --evidence <file>`, `ctf-submit.py --auto
  --evidence <file>`) without a separate verifier round; the fast path exists for
  first-to-solve speed. `ACCEPTED` writes `final/flag.txt` + `ACCEPTED.txt`, records
  a `verifier-platform` verified fact and prints a loud banner; `REJECTED` records
  the attempt and the next candidate may be submitted (governor-bounded).
  The verified-fact gate remains as the fallback when the platform channel is
  unavailable or an independent audit is wanted. Same (question, answer) pairs are
  never sent twice (idempotency); guesses/probes remain forbidden.
- Cleared over-broad rules: flags are deliverables (`final/flag.txt`,
  `writeup.md`); only telemetry/submission logs keep sha256; credentials stay in
  their designated files. Removed unverified numeric heuristics (step counts,
  percentage thresholds) from the persona.

## 1.0.1 — 2026-11-25

- Persona discipline after the first real-session run: explicit `Scope` (do not
  modify mode tooling / other agents' processes while solving), `Stop conditions`
  (platform outage, missing credentials, no new verified fact after ~20 tool
  calls -> record blocker and stop; enforce the 70% budget), and `Submission`
  rules (one verified submit owner, never resubmit an already-solved challenge,
  a blocked platform channel is reported not bypassed).
- Verified on a real CTF-preset session: CTFy SAMPLE-005 solved and Accepted with
  1 submission and 0 wrong attempts (platform state double-checked).

## 1.0.0 — 2026-11-25

- First target-form release of the DSH CTF mode.
- Declares the `ctf` agent preset (order 5) as a declaration-only bundle:
  CTF persona + 12 entry skill root + 26 global resident skills + compaction +
  subagent delegation + shell/fs/jobs/web/ask/todo/present tools.
- No workflow engine and no agent-team DAG: coordination goes through the
  per-challenge blackboard, per the kernel methodology.
- Installed and verified against DSH 0.2.2-rc.5 (desktop profile).

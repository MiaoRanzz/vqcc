# Command quick reference

Run every command with the resolved interpreter:
`conda run --no-capture-output -n vqcc <python_executable> automation/<script> --config <config> ...`.
Runner context already contains the full `search_plan_command`,
`search_brief_command`, `search_report_command` and `queue_validate_command`.
All commands print JSON (except `report`, which prints Markdown).

## Startup and handoff (`automation/search.py`)

| Command | Effect |
|---|---|
| `plan [--task T]` | Resume/pin Top-3 cycles, preempt when a leader beats all roots by `top3_preempt_fraction`; writes `research/top3.json`. |
| `brief` | Read-only startup view: best costs, cycles/steps, handoff, agent-queued validations (last 2 days), ranked hypotheses, `allocation` with `share`, `due` research (daily scan, two-day `review` period, paper-library counts), reminders. |
| `rank [--limit N]` | Open hypotheses: resumable first, then `expected_log_combined_gain_prior × p_success / effort_hours`; lists `missing` estimate fields. |
| `handoff` / `handoff T --next TEXT [--step S] [--candidate ID]... [--command CMD]... [--notes N] [--run-id R]` | Show, or save the per-task note for the next run (`research/handoff.json`, last 20 kept). |
| `record T STEP --cycle C --candidate ID [--candidate ID ...]` | Complete a step with officially checked results (PASS or conclusive FAIL). |
| `record T STEP --cycle C --evidence FILE` | Complete with measured `infeasible`/`no_change` evidence (schema in top3.md). |
| `record T combined --cycle C --auto-no-change` | Combined step when at most one branch improved its root; writes the evidence. |
| `frontier [T --cost X --source REF --basis claimed\|local_official]` | Record a public per-task cost / show allocation. |
| `report` | Chinese run-report skeleton from the ledgers. |

## Candidates (`automation/pipeline.py`)

| Command | Effect |
|---|---|
| `create T --hypothesis H --source S --license L --parent P [--recipe-from P]` | New isolated candidate; returns `output`/`code` paths. `--recipe-from` copies the parent's recorded recipe into `code/parent_recipes/` and prints a summary. |
| `create T ... --parents P1 P2 P3 [--recipe-from P1 P2 P3]` | Combined candidate with all contributing parents. |
| `validate ID [--robustness]` | Full official verifier in the foreground (bounded by `validation_parallelism`). |
| `top T` | Inspect the ranking without advancing a cycle. |
| `promote ID` | Promote a lower official cost with matching provenance. |
| `status` | Ledger: `best`, submissions, `last_submitted_costs`. |
| `prepare` / `reserve` / `record` / `reconcile` / `resolve-unsubmitted` | Submission ledger; see submission.md. |

## Long validations (`automation/runner.py`)

| Command | Effect |
|---|---|
| `queue-validate --candidate ID [--robustness] [--seconds N] [--run-id R]` | Enqueue a `local_validate` job (origin `agent`) for the daemon; returns immediately. Deduplicated per candidate; at most `agent_validation_queue_limit` (default 3) waiting; default time limit `validation_job_seconds` (7200). Blocked jobs wait outside protected windows. |

## Generators

`generators/generate.py TASK --output-dir <candidate output> --params <params.json>`
plus `--source-npz` (chemistry) or `--upstream` (DQI) as the recipe requires.
Family-specific entry points and screens are listed in tasks.md.

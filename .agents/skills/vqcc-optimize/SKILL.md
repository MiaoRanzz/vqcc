---
name: vqcc-optimize
description: Research, optimize, verify, version, and submit this repository's DQI, InvSqrt, and DFTHC-SOS entries for the Google Verifiable Quantum Circuit Compilation competition. Use for its daily competition workflow, public notebook comparisons, weekly workflow improvement, experiment review, submission reconciliation, and reproducibility packages.
---

# VQCC optimization workflow

Improve the official combined score toward the final overall championship while
preparing reviewable milestone-award materials. Follow project `AGENTS.md` and
`automation/config.json`. Treat this as sustained empirical research: produce
reproducible code changes and measured experiments, not only literature summaries.

## Start from recorded state

1. Read the runner's assigned mode and remaining time/resource budget. Run the
   local pipeline's `--help` and `status` when its CLI or state is not already
   known. Resolve the configured Conda prefix and absolute interpreter before
   the first Python command in a new environment.
2. Read the current task incumbents, unresolved submission attempts, recent
   experiments, and last research cursor from the artifact store. Reuse the
   immutable 2026-10-29 baseline; never regenerate into that historical directory.
   Start new research from the current verified per-task best, including promoted
   public reproductions; the historical baseline is not a ceiling or a reset target.
3. Read [task contracts](references/tasks.md) for the task being changed. Consult
   current official pages when rules, deadlines, metric code, or dependencies
   may have changed. Preserve old verifier versions and invalidate affected
   comparisons if the official contract changes; do not silently update it.

## Daily and weekly checkpoints

The user authorized daily public-code comparison and weekly improvement of this
workflow and skill. Run both inside existing optimization jobs, sharing their
resource, time and model-task budgets; do not start another scheduler.

- On the first available optimization run each **Asia/Shanghai date**, perform
  the [high-scoring public-code review](references/public-code.md). Continue an
  unfinished scan in a later run; unchanged source and valid evidence are reused.
  Promote a reproduced, verified per-task improvement as the next working
  baseline, then optimize from it. Listing order or a notebook title alone is
  not evidence of better circuits.
- Once per week, at the first available run from **Monday 00:00 Asia/Shanghai**,
  review the previous completed ISO week using the
  [weekly retrospective](references/weekly-review.md). Summarize measured
  results and implement justified local workflow/skill improvements, with
  relevant checks, a Git checkpoint and next-week success criteria. Resume
  incomplete work instead of marking it complete or applying a change twice.
- Read each checkpoint's durable status before repeating it. Pauses, unavailable
  tools or insufficient budget produce an explicit partial/deferred result;
  they do not count as completed scans or completed retrospectives. These local
  calendar dates do not change the UTC submission quota or pending-submit priority.

## Research and optimize

- Fetch recent Kaggle discussions **including newly active old threads** through
  Kaggle MCP. Read the actual messages behind promising titles. Track topic ID,
  message/update time, link, claim, and whether it has been reproduced. Use web
  access if the connected tools lack the needed page, and record inaccessible
  sources rather than guessing their contents.
- Search original papers and official repositories for the active hypothesis.
  Keep useful older methods as well as recent work. Initial leads and outstanding
  questions are in [the research starting point](../../../docs/research.md); a source's recency is not evidence of gain.
- Before copying code, capture the exact upstream revision, license, and derived
  source chain. Public visibility or a downstream license label alone does not
  resolve missing upstream permission. Use a clearly licensed alternative or
  an independently derived method while a reuse question remains unresolved.
- Maintain a short ranked hypothesis queue. Rank by estimated change in log
  combined score, chance of working, and build/verification cost. Review all
  three tasks over successive runs; avoid indefinitely polishing only DQI.
  Delegate independent research or implementations when useful, within the
  **aggregate** resource budget and with distinct candidate directories.
- Select a concrete hypothesis and implement it in candidate generator source.
  Give each experiment a unique ID, parent candidate, hypothesis, parameters,
  source references/license evidence, source commit or fingerprint, and budget.
  Build into that candidate's directory. A candidate should isolate an explainable
  change; larger algorithm replacements are allowed when the expected benefit
  justifies them.
- Keep multiple promising resource tradeoffs and algorithm families. For DQI
  consider qubits, Toffolis, and failure probability together; for chemistry
  consider the whole block encoding. Preserve measured negative results with
  their tested scope, so a conditional failure is not turned into a universal
  claim. Stop spending on an idea after its specific claim is refuted.

## Validate and promote

Use `automation/pipeline.py` to register, validate, and promote candidates, after
checking its subcommand help. Its reports bind artifacts to validation evidence.
Do not hand-edit an incumbent or synthesize a PASS report.

The initial generator interface is `generators/generate.py TASK --output-dir
<returned-candidate-output-dir> [--params <JSON>]`, run with the resolved vqcc
interpreter. Register the candidate first with `pipeline.py create TASK
--hypothesis TEXT --source TEXT --license TEXT [--parent ID]`. The generator
writes a separate `generation.json` provenance report. See the task reference
for supported parameter families; implement additional algorithms in generator
source rather than mutating a generated circuit without a reproducible recipe.

- Use inexpensive analytical checks, resource estimates, reduced experiments,
  and tests of changed interfaces to screen candidates before expensive runs.
  Label all reduced checks as screening, not official validation.
- A new submitted component must pass the unchanged official full verifier at
  the official problem size, tolerance, and sample count. Use the default
  official run for the comparable cost. Log the exact command, hashes, time,
  environment, and raw result.
- Independently retest a **finalist** when stochastic selection or a marginal
  improvement could be sampling noise, especially DQI. Choose the additional
  seed before observing its result; preserve every such result. Never repeatedly
  sample until a candidate passes or choose a circuit encoding to improve its
  hash-derived draw. Keep robustness scores separate from the official cost.
  The current pipeline requires separate full-size DQI robustness evidence for
  an official cost reduction below `dqi_small_gain_fraction` (default 0.02).
  Every retained matching robustness result must also beat the incumbent cost.
  This tunable search heuristic is not an official acceptance rule or a proof;
  it does not impose extra checks on every task or a zero-error requirement.
- Design boundary checks for the changed implementation: for example finite-field
  basis conversion, phase indexing, register restoration, or arithmetic segment
  transitions. DQI's legitimate small failure probability is not replaced by a
  blanket zero-error requirement. InvSqrt's full verifier already visits every
  legal input; do not add redundant full-domain random-input runs by default.
- Promote only lower-cost, valid evidence. If stochastic evidence is inconclusive,
  retain the candidate for more work rather than claiming a gain. Build the
  combined submission from independently validated per-task incumbents, and
  reuse unchanged component evidence with matching provenance.

## Submit or reconcile

Read [the submission procedure](references/submission.md) for either external
mode. Daily optimization does not itself upload. The submission runner owns the
20:00 Asia/Shanghai window, the one-attempt daily limit, and serialization.

Skip when no qualifying improvement exists. Record the reason in the daily report
and continue research at the next scheduled optimization run. Stop submissions
at the competition deadline. Plan final reproducibility and candidate-selection
materials early enough to allow full verification before that deadline.

## Finish each run

- Record experiments including failures, current best costs, relative combined
  improvement, resource usage, and the next highest-value hypothesis. Report
  platform score/rank only when actually returned by an authoritative source.
- Include the daily public-code scan/comparison and any due weekly retrospective
  in the run report: coverage, evidence, adopted baseline or skip reason,
  workflow changes/checks, record paths and unfinished follow-up.
- Commit reproducible source and relevant documentation with an explanatory
  message. Keep generated artifacts in configured storage, linked by hashes;
  do not include credentials or temporary signed URLs in source or reports.
- Write a concise Chinese run report: change, evidence, submission state,
  unresolved issue, and next action. A no-improvement day is a valid result.
- If a public milestone is competitive, prepare a notebook, dependency snapshot,
  data manifest, attribution, and reproducible commands for user review. Do not
  publish or message other competitors automatically. Prepare at most two final
  submission recommendations with their evidence for the user's selection.

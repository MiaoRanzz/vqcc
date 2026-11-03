# VQCC project instructions

This project competes in `google-verifiable-quantum-circuit-compilation` with
`dqi`, `invsqrt`, and `dfthcsos`. Use the repository skill
[`.agents/skills/vqcc-optimize/SKILL.md`](.agents/skills/vqcc-optimize/SKILL.md)
for research, optimization, validation, submission, and competition reporting.

## Environment and resources

- Use the existing Conda environment `vqcc`. Resolve its prefix with `conda env
  list`; before Python work, confirm `sys.executable` and `sys.prefix`. Invoke
  Python with `conda run -n vqcc <absolute-environment-python> ...`. The supplied
  `kickmix` binary requires Python 3.13. Never silently fall back to `base`.
- `automation/config.json` defines the deployment. The approved aggregate ceiling
  is 20 CPU cores, 180 GiB host RAM, and GPUs 0 and 1, available all day. Limits
  cover all concurrent agents, generators, and validators together. No new paid
  services, subscriptions, or compute purchases are authorized.
- Store experiments and large artifacts under the configured storage root
  (this deployment: `/mnt/data2/vqcc`), exposed through the project's `artifacts`
  link. Keep source, instructions, and deployment configuration in Git; keep
  credentials, large binaries, transient logs, and signed URLs out of Git.
- Use the configured runner for unattended work and honor its shared lock,
  deadline, and resource controls. Do not start a competing background loop.
- On 2026-11-03 the user approved continuous optimization: hourly relay slots
  across the whole day outside the submission protection and reconciliation,
  with a daily model-task budget of 30. Automatic optimization runs may use
  per-task subagents within the same aggregate limits; `validation_parallelism`
  bounds concurrent official verifiers.

## Scientific and version invariants

- Preserve `sample_submission/`, `verifiers/`, `kickmix/`, and the historical
  `submission/2026-10-29/` snapshot. Develop generators in new source paths and
  write each candidate into a distinct experiment directory.
- Optimize the official per-task cost and combined geometric-mean improvement.
  A paper's resource metric or a forum result is not a measured competition score.
- Use a per-task Top-3 search cycle: rank distinct candidates by valid full
  official cost, optimize each of the three parents independently, then combine
  compatible improvements from all three branches within that task. Every
  independent result and every combined result needs its own full official
  validation bound to its exact artifacts; branch PASS does not validate a merge.
  Use `automation/search.py plan` and `record` to pin parents and persist phase
  progress across runs. Finish the independent branches before the combined
  phase; do not replace unfinished branches when a new best appears, except that
  `plan` refreshes a task whose verified leader beats every pinned root by at
  least `top3_preempt_fraction`. Close relatives within `top3_min_relative_gap`
  of a selected root do not occupy another slot. Retain all
  contributing parents for a combined candidate. Fewer than three eligible
  distinct candidates is a recorded shortfall, not a reason to duplicate one.
  Submission still uses the single promoted best per task and its existing gates.
- A candidate's validation belongs to its exact artifact, source, environment,
  and verifier hashes. Changing any relevant input invalidates that evidence.
  Reuse valid completed checks; do not rerun unchanged expensive tests routinely.
- Every feasible optimization must undergo full official verification through
  `automation/pipeline.py validate`, including public-code adaptations and each
  feasible variant in a parameter sweep. Screening may establish a concrete
  correctness/resource violation; estimated cost, small expected gain or an
  uncertain benefit cannot exempt a feasible candidate from official validation.
  Build complete artifacts for feasible proposals; until then they remain
  pending, not officially rejected. Carry unfinished generation/validation in
  the existing hypothesis queue with candidate IDs, remaining work and reasons;
  resume it before new experiments within the runner's limits. Reuse matching
  completed evidence rather than repeating unchanged checks.
- Full official verification is also the submission gate. Additional independent
  randomness is targeted at stochastic finalists whose improvement is uncertain;
  boundary tests target actual changes. InvSqrt already covers every legal input.
  DQI's allowed nonzero failure rate must remain judged by the official contract.
- Preserve source provenance and licenses, parameters, parent candidates, failed
  hypotheses, validation reports, and submission receipts. Record what was
  measured and what is only proposed. Never select candidates by hash/seed luck.

## Authorized external actions

- On 2026-11-03 the user changed unattended Kaggle uploads to one daily window
  at 23:40 UTC (07:40 Asia/Shanghai), lasting 20 minutes so it ends at the UTC
  quota reset, allowing at most one attempt and at most one successful submission
  per UTC day. This supersedes the 2026-10-30 08:00/20:00 windows and the earlier
  three-success limit. Success means a valid positive Kaggle submission ID,
  regardless of grading status; count each ID once. Failed uploads without an
  ID retain their attempt records but do not consume this daily success limit.
  Separately respect the official maximum of five submissions per UTC day and
  check current remote team history before uploading. Retain the configured
  model-task budget. Submit only fully verified improvements over the recorded
  submitted incumbent; skip unchanged, unverified or already-attempted combinations.
  Do not ask for routine submission approval.
- Carry unsubmitted verified improvements into the next day's window.
  Prioritize the pending best
  at that window; no new optimization is required to trigger it. Reuse the
  existing queue and prepare the current verified best at execution.
- Use `automation/pipeline.py` for preparation and the submission ledger. Reserve
  the attempt before any upload/submit call. An uncertain network outcome must
  be reconciled before another submission; missing status/score is unknown.
- After each failed or uncertain upload without a submission ID, the existing
  queue schedules one automatic reconciliation for that upload token. Persist
  deduplication across restarts, honor the model budget and pause/deadline controls,
  and do not automatically re-upload or recursively retry reconciliation.
- A proven failure before `create_submission` may be closed as `not_submitted`
  only through the pipeline's evidence-checked resolution command, after the
  upload run has ended and fresh complete platform history confirms no match.
  Preserve the attempt history and same-combination deduplication, without
  consuming the daily success quota; this does not
  claim that the storage service rejected or never received the ZIP bytes.
- Existing submission `57763974` on 2026-10-29 is the starting submitted baseline.
  Its stored metadata does not establish a platform score or successful grading.
- Public notebooks, datasets, forum posts, code sharing, team changes, and final
  submission selection require a concrete user-reviewed proposal. Preparing
  local drafts and reproducibility packages is authorized. Automatic ZIP
  submission does not authorize those other actions.
- Stop competition submissions at the configured deadline; verify current
  official rules before changing the schedule or limits. Retain milestone and
  final-selection reminders in the run report.

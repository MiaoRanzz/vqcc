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

## Scientific and version invariants

- Preserve `sample_submission/`, `verifiers/`, `kickmix/`, and the historical
  `submission/2026-10-29/` snapshot. Develop generators in new source paths and
  write each candidate into a distinct experiment directory.
- Optimize the official per-task cost and combined geometric-mean improvement.
  A paper's resource metric or a forum result is not a measured competition score.
- A candidate's validation belongs to its exact artifact, source, environment,
  and verifier hashes. Changing any relevant input invalidates that evidence.
  Reuse valid completed checks; do not rerun unchanged expensive tests routinely.
- Full official verification is the submission gate. Additional independent
  randomness is targeted at stochastic finalists whose improvement is uncertain;
  boundary tests target actual changes. InvSqrt already covers every legal input.
  DQI's allowed nonzero failure rate must remain judged by the official contract.
- Preserve source provenance and licenses, parameters, parent candidates, failed
  hypotheses, validation reports, and submission receipts. Record what was
  measured and what is only proposed. Never select candidates by hash/seed luck.

## Authorized external actions

- The user authorized unattended Kaggle submission for this competition, at
  most once per Asia/Shanghai day at the 20:00 submission window, only for a
  fully verified improvement over the recorded submitted incumbent. Unchanged
  or unverified results are skipped. Do not ask for routine submission approval.
- Use `automation/pipeline.py` for preparation and the submission ledger. Reserve
  the attempt before any upload/submit call. An uncertain network outcome must
  be reconciled before another submission; missing status/score is unknown.
- Existing submission `57763974` on 2026-10-29 is the starting submitted baseline.
  Its stored metadata does not establish a platform score or successful grading.
- Public notebooks, datasets, forum posts, code sharing, team changes, and final
  submission selection require a concrete user-reviewed proposal. Preparing
  local drafts and reproducibility packages is authorized. Automatic daily ZIP
  submission does not authorize those other actions.
- Stop competition submissions at the configured deadline; verify current
  official rules before changing the schedule or limits. Retain milestone and
  final-selection reminders in the run report.

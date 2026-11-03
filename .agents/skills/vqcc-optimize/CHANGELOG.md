# vqcc-optimize workflow changes

Each entry: date, change, evidence/motivation, and the criterion the next
review uses to keep, adjust or revert it. Newest first.

## 2026-11-03 — two-day review with paper reading

User request: replace the weekly review with a review every two days, and add
public paper reading that produces optimization suggestions.

- `references/weekly-review.md` → `references/review.md`. Periods are two
  Asia/Shanghai days anchored at 2026-11-01 (`review_period_days`, default 2);
  `brief.due.review` reports the previous completed period. Records move to
  `research/reviews/`; earlier `research/weekly/` reviews stay as history.
- Each review: retrospective (~10%), paper reading (~15%, `references/papers.md`,
  library at `research/papers/index.json`), and ranked suggestions written into
  the hypothesis queue with gain/success/effort estimates. Cap 25% of a run.
- Report skeleton gains an "优化思路建议" section and paper-library counts.

Review criteria (judge at the 2026-11-07 review):

- At least one paper-derived hypothesis per review reaches a screen or official
  validation within two periods; otherwise narrow paper selection to bottlenecks.
- Review overhead stays within its cap (from run events); if not, lengthen the
  period via `review_period_days`.

## 2026-11-03 — relay-run efficiency pass

Changes (user-requested review of the skill workflow, not from weekly evidence):

1. Long official checks can be handed to the runner (`runner.py queue-validate`,
   `local_validate` jobs, origin `agent`) instead of holding a model session.
2. Ordered run sequence with time caps for overhead (quick check ≤5 min, daily
   public scan ≤15%, weekly review ≤20% — since replaced by the two-day review).
3. Per-task relay handoff (`search.py handoff`) and a single startup view
   (`search.py brief`).
4. Gate rules stated once in `AGENTS.md`; skill, references and prompt reference
   them instead of repeating.
5. Tooling replaces reminders: `pipeline.py create --recipe-from`,
   `search.py report`, `search.py record --auto-no-change`, `search.py rank`.
6. `allocation` rows carry a `share` (15% floor + headroom-weighted remainder)
   to size per-task subagent work and verifier slots.
7. A branch with a fresh verified gain may continue one more run before `record`.
8. Runner context no longer reports a Shanghai-date submission flag; the quota
   timezone defaults to UTC like `submission_policy.py`.
9. `references/cli.md` command sheet.
10. This changelog.
11. Sweeps declare their variant list before generation.

Review criteria (first judged at the 2026-11-05 review):

- Share of optimization-run wall time spent with the agent waiting on a verifier
  should fall; queued validations should complete without blocking submit/reconcile.
- Startup-to-first-experiment time per run should drop (from run events).
- Count of feasible candidates left `pending` across more than two runs should fall.
- If agent-queued validations repeatedly delay relay slots without producing
  gains, lower `agent_validation_queue_limit` or revert item 1.

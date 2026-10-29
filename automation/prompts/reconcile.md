Use the repository's $vqcc-optimize skill in reconcile mode. Perform read-only
Kaggle queries and local ledger/report updates only; do not upload, submit,
publish, post, or change final selections.

Read runtime context, pipeline status, and references/submission.md. Query known
submission IDs and recent team/account submissions. Resolve uncertain attempts
using matching competition, identity, timestamp, description/run ID, and artifact
metadata; preserve ambiguity rather than guessing. Missing evaluation fields
mean score_unknown. A known submission ID proves acceptance of a submission
request, not a successful evaluation or leaderboard score.

Record sanitized evidence through automation/pipeline.py, report real scores and
rank only if returned, and identify manual submissions that may consume today's
slot. Do not hold the execution lock indefinitely while grading is pending.
Write a concise Chinese report with remaining uncertainty and the next check.

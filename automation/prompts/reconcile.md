Use the repository's $vqcc-optimize skill in reconcile mode. Read the runner
context, pipeline status and references/submission.md. Query Kaggle read-only
and update the local ledger/report; this mode does not upload or submit.

Query known IDs and recent team submissions, using the existing account's official
SDK fallback when MCP is unavailable or rejects authentication. Match uncertain
attempts as described in the reference and record sanitized evidence through
pipeline.py. Missing evaluation fields remain score_unknown; preserve unresolved
identity or upload ambiguity. Include manual submissions in current quota checks.

For an automatic upload-failure followup, the runtime hypothesis names the upload
token. Read that exact ledger entry and its upload evidence, query the platform,
and record the observed outcome. The queue creates this followup once per token;
an unresolved result must not recursively enqueue more queries or retry uploading.

If the ended upload run provably failed before create_submission, and fresh complete
platform history confirms no matching submission, use the pipeline's explicit
resolve-unsubmitted command with its required hashed evidence bundle. This records
not_submitted without claiming the blob was rejected or never received. It retains
the upload attempt's history and same-combination deduplication; without a valid
submission ID it does not consume the daily success quota. A missing history
match alone, or an error at/after create_submission, is insufficient evidence.

Keep polling within the runner budget. Write a concise Chinese report with actual
platform results, remaining uncertainty and the next useful check.

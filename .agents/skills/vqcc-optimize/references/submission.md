# Submit verified improvements and reconcile results

Use this reference in submit or reconcile mode. Authorization and external
publication boundaries are in `AGENTS.md`; execution uses the existing runner,
model budget, deadline and `automation/pipeline.py` ledger.

## Policy and access

The current `daily_windows` policy checks for a fully verified improvement at
08:00 and 20:00 Asia/Shanghai. Each window lasts 45 minutes and permits at most
one upload attempt. On 2026-11-03 the user changed the local daily limit to three
successful submissions per UTC day: count distinct valid positive Kaggle IDs,
regardless of grading status. Failed uploads without an ID retain their attempt
history but do not consume the daily success limit. The windows established on
2026-10-30 still supersede immediate submission after optimization.
Separately check the official limit of five
submissions per UTC day, including manual/team submissions.

Carry unsubmitted gains to the next scheduled window, including across the
08:00 Asia/Shanghai quota reset. No new optimization is required. Prepare the
**current** best at execution, including improvements made while waiting; retain
the existing pause, deadline and model-budget controls. Skip windows with no
eligible improvement rather than uploading an unchanged combination.

Discover the installed Kaggle MCP interfaces. If unavailable or unauthenticated,
use the installed official `kagglesdk` for the same account and competition:
`KaggleClient().competitions.competition_api_client`. The runner supplies
`KAGGLE_API_TOKEN` from the existing credential; outside it, use the existing
`~/.kaggle/access_token` without exposing its value. Inspect the installed request
types and upload protocol. Authentication diagnosis should reflect current
responses, not a past incident. Keep credentials and signed URLs out of logs,
reports and Git.

## Submit

1. Read pipeline status and the full current UTC day's remote team submission
   history. Confirm quota, deadline and identity; an incomplete history cannot
   establish an available slot. Check current official rules if they may have
   changed. Resolve an uncertain upload/submit outcome without a known ID first.
2. Run `prepare` to select the current verified best, check its evidence and ZIP,
   and skip unchanged, already-attempted or ineligible combinations. Record the
   selected candidate IDs and archive hash.
3. Run `reserve TOKEN` immediately before any upload request. It records the
   durable attempt and `upload_started` status. Upload the exact reserved bytes
   using the live tool/SDK protocol (`start_submission_upload` in the SDK), then
   create the submission with the returned handles. Keep signed URLs in memory
   or a temporary file outside source control.
4. Immediately `record` the returned submission ID and sanitized receipt. An
   upload acknowledgement can also be recorded without inventing a final status.
   A timeout with an uncertain outcome goes to reconciliation before retrying.
5. Fetch evaluation status. A known accepted ID without a score is
   `score_unknown`: it consumes quota but allows a different verified improvement
   while slots remain. Only an actual platform result establishes score/rank.

## Reconcile

Use read-only Kaggle queries for known IDs and recent submissions. Match by
competition, account/team, timestamp, description/run ID and available artifact
metadata; retain ambiguity when those cannot resolve the attempt. Save sanitized
receipts through the pipeline. Uncertain attempts without an ID block another
upload; a known ID with pending grading does not.

Bound polling by the run budget and leave pending grading to a later reconcile
run. Record an observed rejection; the same rejected combination is not retried
automatically. Report selected components, local costs, archive hash, submission
ID, observed platform result and any skip or unresolved outcome in Chinese.

## CLI

Run with the resolved vqcc interpreter; consult subcommand help as needed:

```text
automation/pipeline.py [--config PATH] status
automation/pipeline.py [--config PATH] prepare
automation/pipeline.py [--config PATH] reserve TOKEN
automation/pipeline.py [--config PATH] record TOKEN --receipt FILE --submission-id ID --status score_unknown
automation/pipeline.py [--config PATH] reconcile TOKEN --receipt FILE --status scored --score SCORE
```

Use the status and score evidenced by the receipt; the last two lines illustrate
possible outcomes. Public releases, messages, team changes and final selections
still require the concrete user review described in `AGENTS.md`.

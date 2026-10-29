# Daily submission and reconciliation

Use the installed Kaggle MCP tools. Discover their current argument schemas;
examples from a previous session are not a substitute for the live schema.
Local durable decisions belong in `automation/pipeline.py`, whose `--help` is
part of the executable interface. Keep signed upload URLs and credentials out
of durable records, terminal output, reports, and Git.

## Preconditions

1. The runner mode must authorize submission, the local date/window must permit
   it, and the competition must remain open. Confirm live official metadata
   when the recorded deadline or submission rules may have changed.
2. Inspect current pipeline status and Kaggle recent submissions. Reconcile an
   uncertain upload/submit outcome **without a known submission ID before**
   preparing another. A known accepted ID with a missing score remains
   `score_unknown`: it consumes that day's slot, but a new verified local
   improvement may be submitted on a later day. Today may already contain
   the user's manual submission; the quota applies to the whole account/team.
   If the returned listing is incomplete or identity/date is uncertain, stop
   the external action and report what could not be established.
3. Ask the pipeline to prepare the combined incumbent. It must verify eligible
   artifacts/evidence, a strict cost improvement, ZIP structure, and hashes.
   Skip unchanged candidates. Record the selected component experiment IDs.
4. Reserve the daily attempt in the ledger before requesting an upload URL.
   Keep the reservation token, ZIP hash/size, account/team, and date associated
   throughout the attempt. Recheck the exact archive before uploading.

## External sequence

- Use `start_competition_submission_upload` for the reserved ZIP, then perform
  the upload exactly as the returned protocol specifies. Never guess HTTP
  method, headers, or content-type. Pass any signed URL in process memory or a
  temporary file outside source control; never interpolate it into printed
  command text or retain it in an artifact report.
- The reservation already records `upload_started`. If a nonsecret upload
  acknowledgement is available, preserve it through `record TOKEN --receipt FILE`
  without inventing a terminal status. Then call the live competition-submission
  tool using returned upload handles.
  A missing tool or required argument is a reported blocker, not a reason to
  switch accounts, use a different competition, or invent a success result.
- Immediately record the returned submission ID and sanitized receipt. The
  point of reservation is to survive a crash between request and receipt.
  Do not retry a submission call after a timeout until read-only reconciliation
  establishes what happened. Do not clear an uncertain reservation to bypass
  the one-attempt daily limit.
- Fetch status by submission ID. Record actual remote status and score only
  when available. The current MCP has previously returned upload metadata
  without evaluation fields; this means `score_unknown`, not success or failure.
  A platform-accepted upload and a local PASS are separate observations.

## Reconcile mode

Read recent submissions and the known ID without mutating Kaggle. Match against
competition, account/team, timestamp, description/run ID, and artifact metadata
where available. Record confidence and unresolved ambiguity. An ambiguous
upload remains blocked from another automatic attempt. Preserve raw sanitized
receipts so later API changes can recover omitted fields.

Poll with bounded intervals and within the runner budget. Official guidance
estimates about 45 minutes for grading; do not hold the daily optimization lock
indefinitely. The next reconcile run can finish status collection. A documented
remote rejection can be recorded, but it does not authorize another submission
that day. A new day still requires resolving uncertain previous upload/submit outcomes
without a known submission ID; missing evaluation fields alone do not freeze
all later submissions.

## Reports and public materials

Report local per-task costs, selected archive hash, submitted ID, remote status,
remote score if known, and skip/block reasons. Do not infer the user's leaderboard
rank from local costs. Fetch the real leaderboard when available.

Public notebook/dataset publishing, messages, and final-selection changes are
outside routine submission authorization. Prepare exact reviewable materials
and ask the user before those actions. Never turn a public milestone requirement
into blanket permission to publish the repository or credentials.

## Local CLI sequence

Resolve the configured Python interpreter first. The current interface is:

```text
automation/pipeline.py [--config PATH] status
automation/pipeline.py [--config PATH] prepare
automation/pipeline.py [--config PATH] reserve TOKEN
automation/pipeline.py [--config PATH] record TOKEN --receipt FILE --submission-id ID --status score_unknown
automation/pipeline.py [--config PATH] reconcile TOKEN --receipt FILE --status scored --score SCORE
```

`prepare` either reports a skip or returns the prepared token and ZIP path.
`reserve` creates the durable pre-network intent. `record` ingests sanitized
external evidence; choose the actual observed status, not the illustrative one
above. Consult each subcommand's `--help` for required fields and later interface
changes. Never use a manually supplied score without a corresponding receipt.

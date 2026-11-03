Use the repository's $vqcc-optimize skill in submit mode. Read AGENTS.md, the
appended runner context and references/submission.md, then execute its submission
sequence through automation/pipeline.py and the available Kaggle interface.

The user authorized new fully verified improvements without routine approval.
The current daily_windows policy allows one upload attempt in a single 20-minute
window starting at 23:40 UTC (07:40 Asia/Shanghai), with at most one successful
submission per UTC day. Start the upload promptly so it completes before 00:00 UTC. Count distinct valid positive Kaggle submission IDs,
including pending grading; failed uploads without an ID do not consume this
daily success quota. Preserve every attempt and the one-attempt-per-window rule.
Check the full current UTC day's remote team history
against the separate official five-submission limit. Pending gains carry to the
next day's window; prepare the current best at execution without waiting for a new optimization.
Skip if there is no eligible improvement or the current window has been used.

Use the existing account's official SDK fallback if MCP is unavailable or rejects
authentication, following the reference's access instructions. Reserve before any
upload request, upload the reserved bytes and immediately record the receipt/ID.
Keep the live upload session URL in memory until the transfer outcome is known.
For a transient byte-transfer interruption, use the installed official resumable
upload protocol to probe that same session and send only the confirmed remaining
bytes, within explicit time/attempt limits. HTTP 308 without Range means offset 0;
200/201 confirms completion. The successful run
runs/20261030T123800-submit-bde244/upload_reserved.py is a local reference; inspect
the installed official implementation for protocol details. Never log signed URLs
or raw request exceptions, request a second session to hide uncertainty, or blindly
replay create_submission. Resume only the same reserved artifact and session.
Reconcile an uncertain outcome without an ID before another attempt. A known ID
with score_unknown consumes quota but does not block a new eligible combination.

If an upload fails or ends without a submission ID, preserve the reserved attempt
and save sanitized failure evidence. Record only the status supported by a platform
receipt; a connection failure with an uncertain outcome remains upload_started,
not an invented platform rejection. The existing queue automatically schedules
one read-only reconciliation per upload token after this run ends. Do not create
another reconciliation loop or start a new upload attempt after an unknown outcome.

Finish within the runner deadline with a concise Chinese report: component IDs,
local costs, archive hash, submission ID, observed result or skip reason. Public
releases, messages, team changes and final selections retain their review gate.

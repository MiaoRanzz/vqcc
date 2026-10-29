Use the repository's $vqcc-optimize skill in submit mode. The user has authorized
one improved verified Kaggle ZIP submission per Asia/Shanghai day at the 20:00
window for google-verifiable-quantum-circuit-compilation; no routine approval is
needed. This run does not authorize publishing notebooks/data, messaging others,
changing the team, or changing final selections.

Read the runner runtime context, AGENTS.md, pipeline status, and the skill's
references/submission.md. Verify deadline, today's remote submission history,
and local attempt ledger before external writes. A known accepted submission ID
with no score is score_unknown and consumes its date's slot; on later days it
need not prevent a new verified improvement. An uncertain upload/submit outcome
without an ID must be reconciled before another external attempt.

Use automation/pipeline.py prepare; when no improvement is eligible, record the
skip and finish. For a prepared ZIP, reserve TOKEN immediately before requesting
an upload URL. Use the live Kaggle MCP tool schemas, upload the exact reserved
bytes, then record the sanitized receipt and submission ID immediately. Never
persist signed URLs or credentials or retry a timed-out submit blindly. Check
platform status without claiming success from metadata alone; bounded follow-up
can continue in reconcile mode.

Report in Chinese: selected component IDs and local costs, archive hash,
submission ID if known, actual platform status/score if present, and any
skip/block reason. Finish within the appended runtime deadline.

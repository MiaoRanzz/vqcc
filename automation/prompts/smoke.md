Perform a read-only readiness check for this project's scheduled VQCC workflow.
Read AGENTS.md and the vqcc-optimize skill, but do not run optimization, create a
candidate, modify source, upload/submit, publish, or change schedules.

1. Use one actual shell tool call to read automation/config.json and confirm the
   project/storage paths are accessible. If the workspace sandbox cannot start,
   request the automatic approval review for the same narrow read-only command;
   do not disable approvals or sandboxing.
2. Call Kaggle MCP get_competition for
   google-verifiable-quantum-circuit-compilation and
   get_competition_submission for ID 57763974. Inspect their live schemas first.
3. Report readiness as a JSON object with keys shell_read, storage_read,
   kaggle_metadata, kaggle_submission_read, issues. Each readiness value is
   pass/fail/unknown, and issues is a string array. Do not include credentials,
   authorization headers, signed URLs, raw tool payloads, or a fabricated score.

The final report file is written by the runner; the check itself is read-only.

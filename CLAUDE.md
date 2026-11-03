# VQCC — Claude Code entry

@AGENTS.md

## Claude Code notes

- `AGENTS.md` (imported above) is the single source of standing constraints and
  authorizations; this file only maps them onto Claude Code. Edit `AGENTS.md`,
  not this file, when a rule changes.
- The `vqcc-optimize` skill is `.claude/skills/vqcc-optimize`, a symlink to
  `.agents/skills/vqcc-optimize`. Invoke it as `/vqcc-optimize` (Codex: `$vqcc-optimize`)
  and edit the files under `.agents/` only.
- `.claude/settings.json` denies edits to the read-only competition inputs
  (`verifiers/`, `sample_submission/`, `kickmix/`, `submission/2026-10-29/`) and
  reads of credentials. Do not work around these rules.
- Unattended runs use `automation/runner.py`; `agent_backend` in
  `automation/config.json` selects `codex` or `claude` (`claude -p`, stream-json).
  Do not start `claude` or `codex` loops of your own beside the configured runner.
- Respect `allow_subagents` and `stop_by` from the runner's runtime context.

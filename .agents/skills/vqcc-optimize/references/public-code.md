# Public-code comparison

Public methods produced most measured gains so far (W44: 6.05x of 10.9x). Check
them in two depths:

- **Every optimization run (≤5 min):** a quick incremental check. From the saved
  cursor, list Code-page entries new or re-versioned since the last check
  (score-descending, first pages). Record the cursor and any newly observed public
  per-task cost with `search.py frontier TASK --cost C --source REF --basis
  claimed|local_official` (`local_official` after our own full verification).
  Queue promising sources for reproduction ahead of local micro-tuning.
- **When `brief.due.daily_public_scan` (≤15% of the run):** the full comparison
  below. Past the cap, save the cursor and remaining scope and continue next run.
  The aim is a better starting point or a useful next experiment.

## Find promising methods

Read current `state.best`, the hypothesis queue and prior source comparisons.
Use the [competition Code page](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/code)
in score-descending order through Kaggle MCP, inspecting its live schema. Use
the official SDK or public source access when MCP cannot retrieve the material.
Prioritize changed versions with plausible gains; extend pagination according
to task coverage and remaining experiment time. Record the planned scope and
where the scan stopped.

Sorting, title claims and team leaderboard scores are leads. Associate a score
with a notebook version only when the source establishes that link. Compare
local per-task costs even when no numeric notebook score is available.

For a promising source, save its ref/URL, observed version, retrieval time and
source hash, plus the relevant upstream revisions, data hashes and licenses.
Use supported version retrieval; otherwise retain the returned source and note
the pinning limit. Unclear upstream reuse stays pending while another eligible
route proceeds. Inspect and extract the generation path before running public
code; exclude its upload, credential and verifier-changing steps.

## Compare, reproduce, improve

1. Compare the method with the current verified best: algorithm, precision,
   data/factorization and Q/Toffoli/T/error tradeoffs. For chemistry, compare the
   whole block encoding and keep the NPZ and ANGLE family together.
2. Estimate the possible relative cost reduction and the cheapest useful screen.
   Prioritize sources that can change our next experiment or beat an incumbent.
   Reuse matching evidence for unchanged source, inputs and artifacts.
3. Register a distinct candidate recording the comparison incumbent and the
   actual upstream recipe, inputs, parameters and adaptation.
4. Screen for concrete violations, then build and validate each feasible
   adaptation and variant under the `AGENTS.md` gates (long checks via
   `queue-validate`). Carry unfinished work in the hypothesis queue.
5. Adopt eligible per-task gains through `promote`, keeping stronger local
   components from other sources. New eligible recipes enter the next Top-3
   ranking without discarding the active cycle's remaining steps. Retain useful
   alternatives and scoped negatives.

State what was reproduced: verified imported artifacts, a rerunnable generator,
or both. Missing upstream generation source can remain a recovery task while
a reproducible transformation improves the pinned artifacts or fixed inputs.
Recover more source when the chosen algorithm needs it. Record this distinction
for final reproducibility materials; it adds no submission gate.

Any resulting submission is handled by the existing queue after optimization,
with its quota, reconciliation and next-day carryover rules.

## Save enough to continue

Use the existing files under the configured storage root:

- `research/public-code/index.json`: latest attempt, successful scan day,
  incremental cursor, source/version history and unfinished work.
- `research/frontier.json` (via `search.py frontier`): best known public cost per
  task with source, basis and history; feeds `plan`'s `allocation`.
- `research/public-code/scans/<YYYY-MM-DD>/<run_id>.json`: scope, sources,
  comparison decisions and next actions.
- Candidate code/source records: exact recipe, dependencies, adaptations and
  linked validation evidence.

Reuse their current format and save atomically before `stop_by`. Leave forum
`research/cursors.json` separate. Record candidate IDs, measured costs, source
and license gaps, and why each promising route was adopted, deferred or rejected.

Advance `last_successful_scan_day` when the planned discovery scope and decisions
are recorded without unresolved retrieval gaps; expensive reproductions may
remain queued.
Budget-truncated or failed retrievals stay partial, with the remaining items
saved for a later run. Keep the original scope and describe pagination limits.
Avoid repeatedly spending the experiment budget on the same unavailable source;
retain the gap and continue other useful comparisons.

In the Chinese run report, summarize coverage, adopted improvements and the
highest-value next reproduction or optimization.

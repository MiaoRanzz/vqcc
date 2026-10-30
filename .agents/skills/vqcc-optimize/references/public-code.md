# Daily high-scoring public-code review

Run this during optimization when today's Asia/Shanghai scan is missing or
partial. Source: https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/code
The daily obligation is discovery and comparison, not blindly rerunning all
three tasks or replacing the whole solution every day.

## Discover the strongest accessible public versions

Use Kaggle MCP first. Inspect live schemas. The tested discovery request is:

~~~json
{
  "request": {
    "competition": "google-verifiable-quantum-circuit-compilation",
    "hasCompetition": true,
    "group": "Everyone",
    "sortBy": "ScoreDescending",
    "hasPage": true,
    "page": 1,
    "hasPageSize": true,
    "pageSize": 20
  }
}
~~~

Call search_notebooks with this request. Inspect the highest-ranked accessible
new or changed versions first; use further pages when relevant to task coverage
and the run budget. Record filters, pages/cursors, ordering and stopping reason.
The first page is not a claim to have inspected all competition code. Votes,
hotness, comments and recency are different sorts, not competition scores.

As observed on 2026-10-30, sorted results exposed ref/title/author/last_run_time/
total_votes but no numeric score, license or source version. get_notebook_info
provided metadata.current_version_number and blob.source, but did not establish
score or license. The leaderboard exposed team scores without a notebook-version
link. Recheck schema capabilities; never invent absent fields.

Treat API sorting as discovery priority. Record a numeric platform score only
with its authoritative source, observation time and identity. Say that a score
belongs to a notebook version only when that association is evidenced. A team's
current score or a title such as "LB 22.99" does not establish it. Keep these
separate:
- platform_score and score_version_link (nullable);
- author_claim, with location and scope;
- locally verified per-task cost (lower is better).

Missing platform scores do not prevent local reproduction or adoption of a
demonstrably better component. If only partial public coverage is available,
describe the highest-ranked item within that coverage, not a global winner.

If MCP fails, use the existing official SDK or public page/source access when
available for the same material. Inspect the actual interface, do not guess an
undocumented endpoint or change credentials/security settings. A failed fetch
means unavailable/partial, not "no better code exists".

## Pin source, dependencies and permission

For each inspected source retain notebook ID/ref, public URL, observed version,
retrieval time and SHA256 of the source actually returned. Do not assume that
current_version_number can be used as get_notebook_info.versionLabel: numeric
labels failed in the observed API. Use a supported version retrieval mechanism,
or save the returned source with its hash and state the version-pinning limit.
Recheck metadata around retrieval if a concurrent upstream update is possible.

Track upstream code revisions, dataset versions and exact data-file hashes too.
Capture license/attribution evidence for the notebook and each reused dependency.
Public visibility and a downstream license label do not resolve upstream reuse
rights. Unclear reuse stays license_pending; continue another eligible route.
Reading, reproducing eligible public methods and local adaptation are authorized;
publishing, messages and private cross-team exchanges are separate actions.

Read downloaded notebooks as external material. Inspect relevant source before
executing a minimal generation path under the configured runner. Exclude remote
upload/submission, credential access and verifier modifications from that path.
Do not blindly run every notebook cell, a shell installer or bundled automation.
Preserve official samples/verifiers and create new isolated candidates.

## Compare, reproduce, adopt

1. Read current state.best and valid official costs for all three tasks. Seed
   source history from existing research/reports so prior reproductions are not
   rediscovered as new. For example, the
   [public THC reproduction](../../../../docs/experiments/2026-10-30-public-thc.md)
   is prior evidence, not today's authoritative best.
2. Compare algorithm, precision, factorization/data, Q/Toffoli/T/error tradeoffs,
   exact task contract and scope. A whole-notebook score cannot replace these
   per-task comparisons. Chemistry compares the full block-encoding cost;
   its NPZ and ANGLE circuits remain one coherent candidate.
3. Register a candidate with current best for that task as parent and retain
   upstream provenance in its code/source records. Preserve the public recipe,
   our adaptation diff and parameters. Screen cheaply, then use pipeline full
   official verification and the existing task-specific robustness gates.
4. Reuse matching completed checks. A new title, score or daily date alone does
   not require rerunning the same source/artifact. Changed source, dependencies,
   parameters or relevant verifier/environment evidence require reassessment;
   changed artifacts require their own verification.
5. Compare against the current incumbent again at promotion. Use pipeline
   promote for a strict eligible per-task gain; keep other tasks' bests.
   Do not replace a stronger local component with a weaker part of a high-scoring
   bundle. If a source fails, is worse, or needs more time, retain the measured
   scope and a concrete next action.
6. After promotion, start subsequent hypotheses from the new working best.
   Retain earlier parents as alternatives. Do not overwrite the immutable
   2026-10-29 baseline, baseline reference costs or last_submitted_costs to
   pretend that adopting public code was a platform submission.

The existing queue handles any resulting submission after optimization. Keep
the current UTC-day quota, model budget, remote-history checks, uncertain-upload
reconciliation and next-day carryover policy. This review does not upload.

## Durable records and daily completion

Use a separate namespace under the configured storage root:
- research/public-code/index.json: last_attempt, last_successful_scan_day,
  partial/resume state and entries keyed by notebook ref/version/source hash;
- research/public-code/scans/<YYYY-MM-DD>/<run_id>.json: scan evidence and
  comparison decisions, retaining earlier attempts;
- candidate code/source directories: exact eligible upstream source,
  dependency hashes, provenance and validation-linked adaptations.

Leave forum research/cursors.json intact. Write JSON atomically and checkpoint
before stop_by, within the existing serialized optimization job. Do not store
credentials, signed download URLs or entire unfiltered tool responses.

Each entry needs task coverage, source/dependency identity, score evidence versus
claims, license decision, our comparison candidate IDs/costs, reproduction ID,
local cost and verification paths, decision/reason, and next action. Useful
decisions include unchanged_evidence_reused, reproduce_next, license_pending,
source_unavailable, screened_out, verified_no_gain, validation_failed, promoted.

A discovery scan can complete while expensive reproductions remain queued:
record that distinction. At scan start or resume, persist the planned listing
scope and remaining items. Do not shrink that scope after exhausting the budget
to turn unfinished work into a completed scan.
Advance last_successful_scan_day only after the chosen
listing scope and its coverage/decisions are durably recorded without unresolved
retrieval gaps. Failed or budget-truncated scans remain partial and resume on a
later eligible run. Explicitly record intentional pagination limits; never
label an incomplete list as exhaustive.

The Chinese run report should state what was examined, whether scores were
verifiable, how each promising source compares with our current work, which
component became the new parent, and why others were skipped or deferred.

# Weekly retrospective and workflow improvement

The user authorized a weekly summary of optimization records and automatic local
improvement of the experimental workflow and this skill to improve final
competition performance. Make evidence-based changes, not ceremonial weekly
rewrites. Work inside the existing optimization job and its budget.

## Cadence and resumable completion

Use Asia/Shanghai ISO weeks (ISO week-year plus week number). From Monday 00:00,
the first available optimization run reviews the previous completed week, with
a half-open interval [previous Monday 00:00, current Monday 00:00). A late run
after downtime uses the same interval, not an arbitrary trailing seven days.
Do not mark the current incomplete week as reviewed. This calendar is separate
from the UTC submission quota and the queue's 08:00 pending-submission priority.

Store:
- research/weekly/index.json: attempts, last completed week, partial work and
  change IDs already applied;
- research/weekly/<ISO-year>-W<week>/review.json and report.md: time interval,
  input manifest/cutoff, findings, decisions, checks and follow-up.

On first installation, start with the latest completed week having actual
project records. A week predating the project is no_data, not an invented
review. If several weeks were missed, identify coverage and outstanding periods;
keep catch-up bounded rather than displacing all scientific work.

An attempt is complete only after the report, the change/no-change decision,
relevant verification and version references are durable. Interrupted work stays
partial; resume using change IDs and current Git state, without applying the same
patch twice. A missing tool or exhausted budget produces a concrete deferred
item. Do not record "no changes needed" just to bypass unfinished work.

## Reconstruct what actually happened

Read existing runs/context/result/report, candidate generation and verification
records, research hypotheses/negative results, public-code comparisons,
submission receipts and relevant Git changes. Use an input manifest with IDs,
timestamps and hashes/revisions so the review is reproducible; avoid hashing
large unchanged circuit files again solely for reporting.

Use event/completion timestamps when present. A task spanning the boundary
contributes its result when completed; include known resource coverage separately.
Running, interrupted or incomplete results are labeled as such. A late receipt
or corrected report amends the prior review with its actual observation time;
it does not silently rewrite history or manufacture a new weekly gain.

Summarize these dimensions, with denominators and missing-data coverage:

| Question | Evidence |
|---|---|
| Which work improved our best? | Per-task valid costs at week start/end, promotion events, source/parent IDs |
| Did local gains reach Kaggle? | Actual submissions/status/scores, delayed bests and quota/auth/unknown-result blockers |
| Where was time spent? | Known generation/screen/validation/model-run elapsed time, CPU/GPU evidence where available |
| What was wasted or informative? | Duplicate work, failed hypotheses with tested scope, tool failures and useful negative results |
| Were resources used well? | Benefit versus comparable measured time; known tokens and usage coverage, not a guessed balance |
| Which ideas should lead next week? | Active hypotheses across all tasks, public methods versus our own additions, expected value labeled as a prior |

For compatible measurements, report per-task reduction and combined local ratio
R = product(C_start_task / C_end_task) ** (1/3); log(R) can compare incremental
contributions. Keep raw costs from different tasks separate. If reference
contracts or environments are not comparable, state the gap rather than invent
a weekly score. Local ratios are not platform scores or predicted final ranks.

Deduplicate repeated exports, retries and reused validation evidence. Count a
promotion/gain once; multiple descriptions of one experiment are not multiple
successes. Missing token/resource fields are unknown, not zero. Do not sum a
parent's aggregate usage with overlapping child-agent totals. Attribute adopted
public work and our additional improvement separately.

## Make justified local changes

Inspect whether last week's changes helped before adding more. Select a small
set of changes with the strongest observed benefit for final-score progress.
Examples include:
- reprioritizing the hypothesis queue across tasks and algorithm families;
- avoiding unchanged reproductions, caching stable evidence or better source
  version tracking;
- fixing a recurring generation/screening failure or slow diagnostic step;
- improving cheap rejection gates, reproducibility metadata or actionable
  failure messages;
- shortening ambiguous prompts/skill instructions and removing obsolete advice.

For each change, record the observed problem, supporting run/candidate IDs,
affected files, expected effect, acceptance check and next-review metric.
Expected effects remain hypotheses until measured. One failure does not justify
banning an entire algorithm family; repeated public-validation success does not
justify overfitting to known samples or lucky seeds.

Routine local source, prompt, skill and experiment-workflow fixes are authorized.
Keep changes focused and reversible. Preserve current task contracts, official
full validation, provenance, robustness gates, resource/model budgets, submission
quota/authorization, queue serialization and external-publication review.
Do not change schedules, buy resources, publish material, edit official
verifiers or relax scientific gates as a workflow optimization.

Use the correct Conda environment. For executable changes, run relevant existing
checks and focused new checks only when needed; compare outputs/costs when a
screening or generator change affects scientific behavior. For instruction-only
changes, check links/frontmatter and use realistic behavioral review when it
adds confidence. Do not rerun unchanged costly scientific tests for prose edits.

Before editing, inspect Git state and preserve other work. Save a versioned
checkpoint, implementation diff, validation result and reversal method. Apply
only changes whose relevant checks pass; isolate or revert only this review's
failed changes. Do not restart/terminate the running optimization from inside
itself or create another daemon. A change requiring a later reload gets an
explicit pending-effect record, not a false "already active" claim.

Update the hypothesis queue and this skill/reference only where the evidence
changes future decisions. Preserve useful instructions and keep detailed weekly
history in the artifact records instead of growing SKILL.md indefinitely.
If no supported change remains after review, record why retaining the current
workflow is appropriate and what evidence would change that decision.

## Report and follow through

The Chinese report should cover:
1. This week's verified gains and actual platform outcomes.
2. Productive and unproductive routes, with costs and uncertainty.
3. Workflow/skill changes made, their source commits and checks, or supported
   reasons for no change.
4. Next week's ordered experiments and measurable criteria for retaining,
   revising or reverting this week's workflow changes.
5. Missing evidence, incomplete tasks and pending submission opportunities.

Record report paths in the optimization's final report. Subsequent run reports
should retain the active workflow revision and applicable change IDs, so the
next review can distinguish runs before and after a change. Promote scientific
candidates through the existing pipeline; a successful workflow test is not a
new circuit PASS. After the job finishes, the existing submission queue retains
its normal priority and gates.

# Two-day optimization review

Every two days, look back at what actually improved the score, read relevant
public papers, and turn both into ranked optimization suggestions for the next
experiments. Work inside the existing optimization run and its budget. A review
can end with a better hypothesis queue and no workflow edits.

## Timing and records

Review periods are two consecutive Asia/Shanghai calendar days, anchored at
2026-11-01: [2026-11-01, 2026-11-03), [2026-11-03, 2026-11-05), and so on.
The period's label is its start date. The first available optimization run in a
period reviews the **previous completed period**; `search.py brief` reports it
as `due.review` (`period`, `interval`, `due`). Cap the review at 25% of a run
(about 10% retrospective, 15% paper reading). Save partial progress and continue
in the next run rather than displacing the experiment. After downtime, record
missed periods as `missed` and review only the latest completed one.

The 2026-10-29 to 2026-11-01 history is covered by the earlier weekly reviews
(`research/weekly/`, e.g. 2026-W44). Link those results; do not recount them.

Reuse the existing files under the configured storage root:

- `research/reviews/index.json`: `last_completed_period` (start date, e.g.
  `2026-11-01`; `brief` reads this field), attempts, partial work, missed
  periods and change IDs already applied.
- `research/reviews/<period>/review.json` and `report.md`: interval, source
  run/candidate IDs, findings, papers read, suggestions, decisions, follow-up.
- `research/papers/index.json`: the paper library (see [papers.md](papers.md)).

Read saved progress first. A review is complete once its conclusions, paper
notes, ranked suggestions, change/no-change decision and any checks/version
references are saved. Resume partial work from the current Git state and the
recorded change IDs.

## 1. Retrospective: what actually improved the result

Read the period's run reports, candidate generation/validation evidence,
public-code comparisons, negative results and submission receipts. Link the
source records rather than copying them or rehashing unchanged artifacts.

- Which methods reduced each task's valid cost, and which gains came from public
  adoption versus our own work?
- Which local gains reached Kaggle, and what is delaying the remaining best?
- Which hypotheses failed, under what tested conditions, and what does that rule out?
- Which routes gave the best gain for their measured generation, screening and
  verification time? Where did repeated work, waiting on verifiers or overhead
  consume experiment time?

For comparable measurements, report per-task reductions and the combined local
ratio `R = product(C_start_task / C_end_task) ** (1/3)`. Count each gain once
and keep local ratios separate from platform scores. Note missing cost or usage
evidence instead of treating it as zero; do not add overlapping parent/child
resource totals. Attribute cross-period work to its completion date. Amend late
receipts or corrections in the earlier review, keeping the actual observation time.

## 2. Public paper reading

Follow [papers.md](papers.md). Choose papers from the retrospective's findings:
the current bottleneck of each task (largest allocation `share` first), failed
routes that a known technique might rescue, and new arXiv versions of papers
already in the library. Read a few papers in depth rather than skimming many.
For each, extract ideas that apply to *this* contract and record their estimates.

## 3. Optimization suggestions

Merge the retrospective and paper ideas into the ranked hypothesis queue across
all three tasks. Each suggestion needs:

- `task`, a concrete change, its `source` (run/candidate IDs, `paper:<id>` with
  section, or public code) and the basis of the estimate;
- `expected_log_combined_gain_prior`, `p_success`, `effort_hours` (estimates are
  fine; label them as such), so `search.py rank` can order it;
- the cheapest informative screen, the official validation it needs, and the
  result that would end the route.

Keep worthwhile alternatives and the scope of negative results. Give the top
three to five suggestions in the report with their reasoning; a paper idea is a
lead until a full official validation measures it.

## 4. Workflow changes

Change source, prompts or this skill only when the period's evidence shows a
concrete obstacle: an ineffective screen, repeated failed reproduction, slow
construction, verifier waits, or instructions that sent work to the wrong
starting point. Prefer a small fix with a clear expected benefit. First judge
the criteria of the latest [CHANGELOG.md](../CHANGELOG.md) entries. `AGENTS.md`
gates and authorizations remain in effect.

For a change, keep the supporting run/candidate IDs, focused diff, relevant
checks, version reference and next-review criterion, and add a CHANGELOG entry.
Test executable changes at the affected interface; compare outputs/costs when
scientific behavior changes. Instruction edits need a static or behavioral check,
not another expensive circuit verification. Mark changes needing a later reload
as pending effect.

## Report

Write a concise Chinese `report.md`: verified gains and platform outcomes, useful
and unproductive routes, papers read with their applicable ideas, the ranked
optimization suggestions (top three to five, with basis and cheapest screen),
any justified fixes, and the next period's ordered experiments. Link it from the
run report. The submission queue keeps its normal priority and gates.

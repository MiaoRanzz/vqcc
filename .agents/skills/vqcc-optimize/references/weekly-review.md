# Weekly optimization review

Use the weekly review to decide which experiments should lead next and which
recurring obstacles are worth fixing. Work inside the existing optimization job
and its budget; a week can end with a better research plan and no workflow edits.

## Timing and records

From Monday 00:00 Asia/Shanghai, the first available optimization run reviews
the previous completed ISO week: [previous Monday 00:00, current Monday 00:00).
Use the ISO week-year and week number. On first installation, start with the
latest completed week having project records; earlier weeks are `no_data`.
After downtime, record missed coverage and keep catch-up small enough to leave
time for experiments. The UTC submission quota and pending-submit priority are
unchanged.

Reuse the existing files under the configured storage root:

- `research/weekly/index.json`: attempts, last completed week, partial work and
  change IDs already applied.
- `research/weekly/<ISO-year>-W<week>/review.json` and `report.md`: interval,
  source run/candidate IDs, findings, decisions and follow-up.

Read the saved progress first. Complete the review after its conclusions,
change/no-change decision and any applicable checks/version references are
saved. Resume partial work from the current Git state and recorded change IDs.

## Find what actually improved the result

Read relevant run reports, candidate generation/validation evidence, public-code
comparisons, negative results and submission receipts. Use completed results
within the interval and identify important pending work. Link the source
records rather than duplicating their contents or rehashing unchanged artifacts.

Focus on these questions:

- Which methods reduced each task's valid cost, and which gains came from public
  adoption versus our own improvements?
- Which local gains reached Kaggle, and what is delaying the remaining best?
- Which hypotheses failed, under what tested conditions, and what did that rule out?
- Which routes offered the best gains for their measured generation, screening
  and verification time? Where did repeated work consume useful experiment time?
- Given the current bests, which concrete hypotheses now have the highest
  expected combined-score gain per unit effort?

For comparable measurements, report per-task reductions and the combined local
ratio `R = product(C_start_task / C_end_task) ** (1/3)`. Count each gain once and
keep local ratios separate from returned platform scores. Note missing cost or
usage evidence rather than estimating it as zero; avoid adding overlapping
parent/child resource totals. Attribute cross-week work to its completion date.
Amend late receipts or corrections in the earlier review, retaining their actual
observation time.

## Improve the next experiments

Update the ranked hypothesis queue across the three tasks. For leading ideas,
keep the expected gain and its basis, the cheapest informative experiment,
approximate build/verification effort and what result would end that route.
Preserve worthwhile algorithm alternatives and the scope of negative results.

Change source, prompts or this skill when the week's evidence identifies a
concrete obstacle: an ineffective screen, repeated failed reproduction, slow
construction or instructions that sent work toward the wrong starting point.
Prefer a small fix with a clear expected benefit. Check whether the previous
week's changes helped before adding more process. Existing authorization and
scientific gates in `AGENTS.md` remain in effect.

For a change, retain the supporting run/candidate IDs, focused diff, relevant
checks, version reference and next-review criterion. Preserve unrelated work.
Test executable changes at the affected interface; compare outputs/costs when
scientific behavior changes. Instruction edits need an appropriate static or
behavioral check, not another expensive circuit verification. Mark changes
requiring a later reload as pending effect and keep detailed history in the
weekly records.

Write a concise Chinese report: verified gains and platform outcomes, useful and
unproductive routes, any justified fixes, and next week's ordered experiments.
Link it from the run report. The existing submission queue continues to handle
verified improvements with its normal priority and gates.

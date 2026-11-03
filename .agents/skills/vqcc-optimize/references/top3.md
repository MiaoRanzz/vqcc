# Per-task Top-3 optimization

The cycle rules (three independent branches, then a combined step, each result
separately and fully validated) are in `AGENTS.md`. This file covers the ledger
mechanics. It changes search ancestry, not the submission schedule or budget.

## Select and pin a round

Run the runner's `search_plan_command` (outside a run: `automation/search.py
--config automation/config.json plan`). It ranks each task's distinct artifact
families by official cost, rechecks the selected candidates' evidence integrity
(no scientific rerun) and writes `research/top3.json`.

- Identical artifact copies occupy one slot and use the earliest valid
  attestation, never a favorable-seed report. Officially checked nonwinning
  candidates can be roots.
- With `top3_min_relative_gap`, a candidate within that gap of a selected root
  that is its ancestor, descendant or sibling is excluded as `near_duplicate_of`;
  unrelated near-ties (e.g. imported public artifacts) stay.
- Fewer than three distinct roots is a reported `shortfall`; never pad.
- `plan` resumes active cycles. Exception: a verified leader beating every root
  by `top3_preempt_fraction` archives the cycle as `preempted` and starts a new
  one (`replaces` names it). Move the old cycle's unfinished feasible work into
  the hypothesis queue; `record` against the old cycle ID is refused.
- A general run finishes the round across all three tasks before refreshing
  completed cycles; `plan --task T` scopes a single task. Completed cycles are
  archived in `research/top3-history/`. `pipeline.py top T` inspects without
  advancing.

`plan` and `brief` also return `allocation` (headroom and `share`); see SKILL.md.

## Independent branches top1, top2, top3

Work from each pending step's own `parents` and that parent's actual recipe
(`pipeline.py create ... --parent P --recipe-from P`), not from `state.best`.
Branches may run sequentially and span several runs. Give every pinned branch a
turn before repeating one; a branch whose latest result was a verified gain may
continue one more run before it is recorded.

Each feasible output: `create` → build complete artifacts → `validate` (in-run)
or `queue-validate` (long check). Record all results of the step, including
official FAIL outcomes:

```text
automation/search.py record TASK top1 --cycle CYCLE_ID --candidate CHILD_ID [--candidate ...]
```

A queued/unfinished check, an estimate or a DQI robustness run alone cannot
complete a step. `promote` eligible improvements; promotion does not replace the
cycle's remaining roots.

## Combined step

It unlocks once every independent step is complete. Its `parents` are the
lowest-cost valid result per branch (the original root when its children failed
or got worse).

- **At most one branch improved its root:** there is nothing to merge (the
  combination is the roots themselves or one already verified result). Close it:
  `search.py record TASK combined --cycle CYCLE_ID --auto-no-change`. The command
  refuses when two or more branches improved.
- **Two or more improved:** read all recipes, check parameter, precision,
  ancilla, phase and input compatibility, and build one coherent same-task
  candidate. Keep chemistry's NPZ and complete ANGLE family consistent. Never
  concatenate whole circuits or mix tasks.

```text
automation/pipeline.py create TASK --hypothesis TEXT --source TEXT --license TEXT --parents P1 P2 P3 --recipe-from P1 P2 P3
automation/pipeline.py validate COMBINED_ID      # or runner.py queue-validate --candidate COMBINED_ID
automation/search.py record TASK combined --cycle CYCLE_ID --candidate COMBINED_ID
```

Pairwise intermediates are allowed, need their own validation, and do not
complete the step; register the final integration with all assigned parents.
A combined FAIL is a completed experiment and does not displace the incumbent.

## Completion, infeasibility and continuation

`record` checks evidence, exact ancestry and phase order; the cycle ID stops an
old run from updating a new cycle. If time runs out, leave the step pending and
write `search.py handoff` plus the hypothesis-queue entry (candidate IDs,
remaining commands, reason). A timeout or low expected gain is not infeasibility.

When a concrete check proves the chosen change infeasible or exactly unchanged,
save JSON evidence under the storage root and pass `record ... --evidence FILE`:

```json
{
  "task": "invsqrt",
  "cycle_id": "the-current-cycle-id",
  "step": "top2",
  "parents": ["the-assigned-parent-id"],
  "conclusion": "infeasible",
  "reason": "The concrete correctness/resource violation or exact identity",
  "measurements": {"report": "path/to/check", "observed": "measured result"}
}
```

`conclusion` is `infeasible` or `no_change`. Combined infeasibility must cover
all assigned sources with measured incompatibilities. Existing feasible outputs
still need their own official checks before closing a step.

After the round completes, `plan` refreshes Top-3 from valid official results.
`state.best` holds only the promoted winner used by the submission pipeline. The
report skeleton (`search.py report`) already lists cycle IDs, roots, step results
and the combined outcome.

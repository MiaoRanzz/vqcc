# Per-task Top-3 optimization

Use the configured Conda interpreter, shared runner, resource limits and deadline.
This changes search ancestry, not the submission schedule or model-task budget.

## Select and pin a round

Run the runner's `search_plan_command`. Outside a run, the equivalent is:

```text
automation/search.py --config automation/config.json plan
```

The command ranks each task's distinct artifact families by ascending official
cost, checks the selected candidates' artifact/source/report/environment/verifier
evidence and writes `research/top3.json`. This rechecks evidence integrity; it
does not rerun scientific verification. Identical artifact copies occupy one
slot and use the earliest valid attestation, never a favorable-seed report.
Officially checked nonwinning candidates can be search parents. DQI promotion
still requires the existing independent robustness evidence where applicable.

With `top3_min_relative_gap` set, a candidate whose cost is within that relative
gap of an already selected root and is its ancestor, descendant or sibling (shares
a direct parent) is excluded as `near_duplicate_of` that root; the next distinct
family takes the slot. Unrelated near-ties, such as imported public artifacts, stay.

Each task freezes up to three roots for a cycle. If fewer than three qualify,
report the shortfall and use the available distinct roots. Do not pad with copies
or unverified estimates. `plan` resumes an active cycle without replacing its
roots, with one exception: when the task's verified leader beats every pinned root
by at least `top3_preempt_fraction`, `plan` archives the cycle as `preempted` and
starts a new one led by that candidate (`replaces` names the old cycle). Save the
preempted cycle's unfinished feasible work in the hypothesis queue; a `record`
against the old cycle ID is refused. General runs finish the current round across all three tasks before
refreshing completed cycles; a task-scoped invocation may use `plan --task TASK`.
Completed cycles are archived in `research/top3-history/` before replacement.
For an inspection without advancing a cycle, use `pipeline.py top TASK`.

`plan` also returns `allocation`: tasks ordered by `log(our_best / public_best) / 3`,
the combined log-score headroom to the best known public cost recorded with
`search.py frontier`. Spend the run's time on the largest headroom first; tasks
with an unknown frontier need a public scan; `leading` tasks get local work.

## Independently optimize top1, top2, top3

Use each pending step's own `parents` and actual recipe, inputs and parameters.
Rank research hypotheses within these branches; do not route all work back to
`state.best`. Each branch should test a concrete optimization. Branches may run
sequentially and span multiple scheduled runs. Resume unfinished feasible work
first and give every pinned branch a turn before repeating a completed branch.

Create a new candidate with `pipeline.py create TASK ... --parent PARENT_ID`.
Generate its complete artifacts and run `pipeline.py validate CANDIDATE_ID`.
Every feasible result in the branch must have its own full official result;
retain failures and no-gain results alongside successes. Only matching completed
evidence for that exact artifact can be reused. Record all results of the step:

```text
automation/search.py record TASK top1 --cycle CYCLE_ID --candidate CHILD_ID
```

Repeat `--candidate` for additional results, including official FAIL outcomes.
An unfinished verification, an analysis estimate or a DQI robustness run alone
cannot complete a step. Use `pipeline.py promote` for eligible improvements;
promotion does not replace the remaining roots of this cycle.

## Combine the three branches, then verify again

The `combined` step unlocks only after every available independent step is
complete. Its `parents` select the lowest-cost valid result from each branch,
retaining the original root when its children fail or get worse. Read all three
recipes, compare their effective changes and construct a coherent same-task
combination. Check parameter, precision, ancilla, phase and input compatibility.
Keep chemistry's NPZ and complete ANGLE family consistent. Do not concatenate
whole circuits or treat the three different competition tasks as interchangeable.

Use all assigned contributing parents when registering each combined result:

```text
automation/pipeline.py create TASK --hypothesis TEXT --source TEXT --license TEXT --parents P1 P2 P3
automation/pipeline.py validate COMBINED_ID
automation/search.py record TASK combined --cycle CYCLE_ID --candidate COMBINED_ID
```

Build an integrated candidate from all three branches' compatible contributions.
Intermediate pairwise experiments are allowed and also need separate official
verification, but do not complete the combined step by themselves. Retain their
actual parent lists; register the final integration with all three assigned
sources. If fewer than three roots exist, use the actual assigned list.

The three branch reports never validate the combined artifact. The combined
candidate needs its own full official PASS/FAIL bound to its exact artifact and
source, even if all parents passed. Only separately verified improvements may
be promoted. A combined failure still records a useful completed experiment;
it does not displace the promoted incumbent.

## Completion, infeasibility and continuation

`record` checks current evidence, exact ancestry and phase order before saving
completion. The cycle ID prevents an old run from updating a new cycle. If the
run budget ends, leave the step pending and save the exact remaining commands,
candidate IDs and reason in the existing hypothesis queue. Do not record a
timeout or expected low gain as infeasibility.

When a concrete check proves the chosen change infeasible or exactly unchanged,
there is no new feasible output to validate. Preserve a JSON evidence file under
the storage root with these fields, then pass it as `record ... --evidence FILE`:

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

`conclusion` is `infeasible` or `no_change`. For combined infeasibility, cover all
assigned sources and explain the incompatible changes with measured evidence;
do not invent parent contributions or substitute a pairwise candidate silently.
Existing feasible outputs still require their own official checks before closing
the step. Store each report's recipe and source provenance in its candidate.

The Chinese run report lists each task's Top-3 IDs, cycle ID, independent results,
separate combined result and remaining work. After completing the round, `plan`
refreshes Top-3 from valid official results for the next round. `state.best`
continues to contain only the promoted winner used by the submission pipeline.

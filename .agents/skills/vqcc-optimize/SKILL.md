---
name: vqcc-optimize
description: Improve this repository's DQI, InvSqrt, and DFTHC-SOS competition circuits through research, public-code comparison, reproducible experiments, and official verification. Also use for experiment review, submission/reconciliation, and reproducibility materials.
---

# VQCC optimization

Maximize the official combined score. Focus effort on promising algorithms,
circuit implementations and measured experiments. Project `AGENTS.md` owns the
standing constraints and authorizations; `automation/config.json` and runner
context supply the environment, resources and time budget.

## Match the request

| Request or runner mode | Work to perform |
|---|---|
| Optimize or reproduce a method | Follow the optimization loop below; read the relevant [task contract and method entries](references/tasks.md). |
| Review experiments or the workflow | Inspect the requested evidence and give findings; make changes when requested. |
| Submit or reconcile | Use [submission.md](references/submission.md); reconciliation queries Kaggle and updates local records only. |
| Prepare reproducibility materials | Assemble the requested source, inputs and commands; identify any missing generation recipe. |

Use the user's request when no runner mode is supplied. Load references as needed.
Optimization runs leave uploading to the existing submission queue.

## Start from each task's Top-3

Read pipeline `status`, the three current verified bests, recent failed ideas,
and `artifacts/research/hypotheses.json`. Consult CLI help when the interface is
unfamiliar. Resolve and confirm the configured Conda interpreter per `AGENTS.md`
before Python work.

Follow the [Top-3 search cycle](references/top3.md). Run the runner's
`search_plan_command` (or `automation/search.py plan`) and resume its pinned
per-task branches. Each task independently optimizes all three ranked parents,
then combines their compatible improvements. Current best remains the promotion
benchmark; it is not the only search parent. Each branch result and combined
result must separately pass through `pipeline.py validate` before being recorded.

Before choosing work, run the quick public check in
[public-code.md](references/public-code.md) and read `plan`'s `allocation`: give
most time to the task with the largest public headroom, and adopt or reproduce a
better public method before local micro-tuning. When the runner allows subagents,
work on the three tasks in parallel with one subagent per task; official
verifications may overlap up to `validation_parallelism`.

First resume feasible proposals/candidates awaiting generation or full official
verification from the hypothesis queue and recent experiment records. Use the
existing runner and its limits; do not lose unfinished checks between runs.

For each selected branch, inspect its assigned parent's `generation.json`, candidate
source/code snapshot, inputs and parameters. **`--parent` records ancestry; it
does not make the generator inherit that recipe.** Select the actual generator
and pass its inputs explicitly. The generic generator defaults can still point
to historical source or sample data.

If only verified artifacts are available, record that generator reproduction is
still missing. A reproducible transformation of the pinned artifact or its
fixed inputs can still be a useful optimization route. Recover the full recipe
when needed, or use a reproducible alternative with its actual parent recorded.
Always compare against the current best; the historical baseline is a reference.

## Choose and test a valuable hypothesis

- Rank the short hypothesis queue by expected relative cost reduction, chance of
  success and total implementation/generation/verification effort. This orders
  work; it does not exempt feasible optimizations from official verification.
  A task cost reduction contributes `log(C_before / C_after) / 3` to log combined gain.
  Use measured bottlenecks and rough estimates; keep all three tasks in view.
- Seek algorithm changes, resource tradeoffs and better public methods as well
  as parameter tuning. Keep promising alternatives; abandon a specific route
  after its infeasibility is established or official results remove the benefit.
- Read relevant Kaggle discussions, including new activity in old threads, and
  primary papers/source for the active idea. Reuse saved cursors and evidence.
  [Research notes](../../../docs/research.md) supply leads, not current bests.
- State the proposed change, expected gain and cheapest useful test. Screen with
  analysis, resource counts or a numerical model before building an expensive
  circuit. Screening can rule out a concrete correctness/resource violation;
  estimated cost, small gains or uncertain benefit cannot rule out official
  validation of a feasible optimization. Feasible proposals without complete
  artifacts stay pending generation. Where feasible, each optimization run
  should test a concrete hypothesis.
- Implement the change in a reproducible generator or transformation. Record
  its actual parent, parameters and source revision/license; use a distinct
  candidate directory. Delegate independent hypotheses within the shared budget.
  Reserve enough time to finish the selected check and save its result.

Register with `automation/pipeline.py create TASK --hypothesis TEXT --source TEXT
--license TEXT --parent ID`. Use the returned candidate paths. When the generic
generator matches the selected recipe, its interface is:

```text
generators/generate.py TASK --output-dir <candidate-output> --params <params.json>
```

`params.json` is a file containing task parameters. Supply `--source-npz` for the
chosen chemistry input or `--upstream` for the chosen DQI source as appropriate.
For other families use their own entrypoints in the task reference. Retain the
exact recipe with the candidate; no new reporting framework is needed.

## Verify gains and continue from them

Use `pipeline.py validate` for **every feasible optimization**, including
public-code adaptations and every feasible parameter-sweep variant, not just
the predicted winner. Build its complete official artifacts and run the unchanged
full verifier even when the screen predicts no gain. Only a concrete, recorded
correctness/resource violation can close a route before official verification.
Use `promote` only for a lower official cost, with matching
artifact/source/environment provenance. Reuse valid completed checks for
unchanged components; retain official failures and no-gain results as well.

Budget generation plus full verification before starting an experiment. When
time/resources prevent completion, keep the optimization pending in the existing
`research/hypotheses.json` with candidate IDs (when created), exact recipe,
remaining commands and deferral reason. Resume pending work before new
experiments. A timeout, interruption or missing artifact is not an official
rejection or PASS; do not bypass runner limits or launch detached validators.

Target additional checks at the actual change or uncertain stochastic finalists.
DQI small gains below `dqi_small_gain_fraction` require the pipeline's independent
full-size robustness evidence; all matching retained results must also beat the
incumbent. Choose extra seeds before seeing results and retain them; hash/seed
luck is not an optimization. This local heuristic does not replace DQI's allowed
failure rate. InvSqrt full validation already covers every legal input.

After promotion, keep the remaining Top-3 branches pinned. Once all independent
branches are complete, combine the best valid result from each branch (falling
back to that branch's original parent when needed), build a distinct candidate
and validate it independently. Record phase completion with `search.py record`.
Refresh the ranked parents for the next cycle only after the current round's
independent and combined work is finished. Preserve failed ideas' tested scope.

## Keep research useful across runs

During optimization, check the existing daily and weekly records before repeating:

- Once per **Asia/Shanghai day**, compare promising public code using
  [public-code.md](references/public-code.md). Adopt verified improvements per
  task; eligible artifacts enter the next Top-3 ranking without dropping active branches.
- From **Monday 00:00 Asia/Shanghai**, review the previous completed ISO week using
  [weekly-review.md](references/weekly-review.md). Prioritize better experiments;
  change the workflow only where evidence shows it obstructs progress.

Keep discovery and retrospective work within the current run budget. Save partial
progress for a later run. Use existing research records and the existing runner.

## Finish an optimization run

Save the measured result, current best costs, local combined improvement and next
hypothesis in a concise Chinese report. Include due research coverage, submission
state and milestone/final-selection reminders. Account for every feasible
candidate: completed official result, matching evidence reused, or pending work
and the next command. Include each task's cycle ID, three parent IDs, independent
branch results and separate combined-result validation. Platform scores come from actual platform responses.
A no-gain result is valid.

Keep source changes versioned with focused commits that preserve other work;
large artifacts and detailed evidence stay in configured storage. Prepare useful
reproducibility or milestone materials for user review when warranted. Submission,
publication and final selection follow the existing `AGENTS.md` authorization.

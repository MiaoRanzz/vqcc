---
name: vqcc-optimize
description: Improve this repository's DQI, InvSqrt, and DFTHC-SOS competition circuits through research, public-code comparison, reproducible experiments, and official verification. Also use for experiment review, submission/reconciliation, and reproducibility materials.
---

# VQCC optimization

Maximize the official combined score with measured experiments. Project
`AGENTS.md` is the single source of the scientific gates (every feasible
optimization gets full official validation, Top-3 cycle rules, evidence binding,
no seed selection) and of all authorizations. This skill says how to work inside
those rules; it does not restate them. Runner context supplies the interpreter,
resources, `stop_by` and the ready-made commands named below.

## Match the request

| Request or runner mode | Work to perform |
|---|---|
| Optimize or reproduce a method | Follow the run sequence below; read the [task contract and routes](references/tasks.md). |
| Review experiments or the workflow | Inspect the requested evidence and give findings; make changes when requested. |
| Submit or reconcile | Use [submission.md](references/submission.md); reconciliation is read-only on Kaggle. |
| Prepare reproducibility materials | Assemble source, inputs and commands; name any missing generation recipe. |

Use the user's request when no runner mode is supplied. Commands and flags are in
[cli.md](references/cli.md); do not rediscover them with `--help` every run.

## Optimization run sequence

Runs relay hourly. Do these steps in order; the caps keep overhead from eating
the experiment. Times are fractions of the time until `stop_by`.

1. **Environment (≤2 min).** Confirm the configured Conda interpreter per `AGENTS.md`.
2. **Advance and read state (≤5 min).** Run `search_plan_command`, then
   `search_brief_command`. `brief` is the one startup view: cycles and steps,
   per-task handoff notes from the previous run, agent-queued validations and
   their results, the ranked hypothesis queue, allocation shares, due research
   and reminders. Read further files only for the branch you pick.
3. **Collect finished work (≤10%).** For each agent-queued validation that
   finished, `promote` an eligible gain and `search.py record` the step result.
   Then resume the `brief.hypotheses` items marked for resumption (candidate IDs
   with remaining commands) before new ideas.
4. **Due research, capped.** Always the quick public check (≤5 min,
   [public-code.md](references/public-code.md)). If `due.daily_public_scan`,
   the full comparison (≤15%). If `due.review`, the two-day
   [review](references/review.md) (≤25%): retrospective, public
   [paper reading](references/papers.md) and ranked optimization suggestions.
   Past a cap, save partial progress and continue next run; never skip the
   experiment for them.
5. **Experiment (most of the run).** Pick a pending Top-3 step per
   [top3.md](references/top3.md) and the allocation `share` (below), then test
   one concrete hypothesis as described in the next section.
6. **Checkpoint (last ≥10 min).** Queue unfinished long validations, write each
   touched task's `handoff`, update the hypothesis queue, generate the report
   skeleton, commit source changes. Leave no unmanaged process.

## Allocate across tasks

`plan`/`brief` return `allocation` rows with `log_score_headroom` to the best
known public cost and a suggested `share` (each task keeps a 15% floor; the rest
follows headroom). Use `share` to split run time, the `validation_parallelism`
verifier slots and subagent effort. With subagents allowed, run one per task but
size each one's work and verifier use by `share` rather than equally. `leading`
tasks get cheap local work; `unknown_frontier` tasks need a public scan first.
Adopt or reproduce a better public method before local micro-tuning.

## Choose and test a hypothesis

- `search.py rank` orders open hypotheses: resumable work first, then
  `expected_log_combined_gain_prior × p_success / effort_hours`. Keep those three
  fields on every queue entry (estimates are fine; say so). A task cost reduction
  adds `log(C_before / C_after) / 3` to log combined gain. Items listed under
  `missing` need estimates before they can compete.
- Seek algorithm changes, resource tradeoffs and better public methods as well as
  parameter tuning. Read relevant Kaggle threads and the primary papers for the
  active idea ([papers.md](references/papers.md)), reusing saved cursors and the
  paper library. [Research notes](../../../docs/research.md) and paper ideas are
  leads, not measured gains.
- State the change, expected gain and cheapest useful screen. Screen with
  analysis, resource counts or a numerical model before an expensive build. A
  screen can close a route only by a concrete correctness/resource violation.
- **Sweeps:** before generating, write the full variant list (parameters and
  count) into the hypothesis entry as `sweep`. That fixes validation cost up
  front and rules out choosing variants after seeing results. Each feasible
  variant still gets its own official validation.
- Register with `pipeline.py create TASK ... --parent ID --recipe-from ID`.
  `--recipe-from` copies the parent's `generation.json`, parameters and code into
  `code/parent_recipes/` and prints the recorded generator/inputs. It does not
  run anything: still select the generator and pass inputs explicitly (generic
  generator defaults point at historical sample data). If the parent has no
  `generation.json`, record that its generator reproduction is missing; a
  reproducible transformation of the pinned artifact remains a valid route.
- Implement in a reproducible generator or transformation with source revision
  and license recorded. Delegate independent hypotheses within the shared budget.

## Validate without holding the model

Estimate verification time before starting. Run a validation inside the run
only when it will finish well before the checkpoint; run independent ones
concurrently up to `validation_parallelism`. Otherwise, as soon as the artifact
is complete, hand it to the runner with `queue_validate_command`
(`runner.py queue-validate --candidate ID`): the existing daemon runs it as a
`local_validate` job between model runs (ahead of the next relay slot, outside
protected submission/reconciliation windows), with no model session. At most
`agent_validation_queue_limit` agent-queued checks may wait; keep the rest
pending in the hypothesis queue with candidate IDs and the exact command. The
next run collects results in step 3. A queued, interrupted or timed-out check is
neither PASS nor rejection.

`promote` only a lower official cost with matching provenance. DQI gains below
`dqi_small_gain_fraction` also need the pipeline's independent robustness
evidence (`queue-validate --robustness` for the long DQI replication); choose
extra seeds before seeing results. InvSqrt full validation already covers every
legal input.

## Top-3 cycle mechanics

Follow [top3.md](references/top3.md). Two practical rules:

- A branch whose latest result was a verified gain may continue for one more run
  before you `record` it; otherwise record and give an untouched branch its turn.
- When at most one branch improved its root, the combined step has nothing to
  merge: close it with `search.py record TASK combined --cycle ID --auto-no-change`,
  which writes the identity evidence itself. Two or more improved branches need a
  real combined candidate and its own validation.

## Finish a run

1. `search.py handoff TASK --next "..." --step STEP --candidate ID --command "..."`
   for every task you touched: the next run reads it first.
2. `search_report_command` prints the Chinese report skeleton (best costs, local
   ratio vs last submission, cycles and step results, allocation, queued
   validations, due research, submission state, milestone/final-selection
   reminders). Save it to the run directory and fill only the two marked sections:
   this run's experiments with every feasible candidate's disposition (official
   result, reused matching evidence, or pending/queued with its next command),
   and the next hypothesis. Platform scores come only from platform responses.
   A no-gain result is a valid outcome.
3. Commit focused source changes; large artifacts and evidence stay in storage.
   Optimization runs never upload; the existing submission queue does.

## Change this skill

Review-driven edits go in [CHANGELOG.md](CHANGELOG.md) with the supporting
run/candidate IDs and the criterion the next review uses to judge the change.

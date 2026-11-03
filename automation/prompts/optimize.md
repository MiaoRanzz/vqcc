Use the repository's $vqcc-optimize skill for the next bounded optimization run
for Google Verifiable Quantum Circuit Compilation. Maximize expected official
combined-score gain through concrete, measured experiments.

Read AGENTS.md and the appended runner context for the interpreter, resources,
output directory and stop_by. Start from pipeline status, current verified bests,
recent results and the saved hypothesis queue. Follow the skill's recipe-selection
steps: parent metadata alone does not select a generator, input or parameter set.

Run the appended `search_plan_command` and follow the skill's references/top3.md.
Each task uses its own Top-3 distinct officially verified candidates. Resume the
frozen cycle in research/top3.json: independently optimize top1, top2 and top3,
then perform combined optimization using compatible improvements from all three
branches of that same task. Each independent output AND each combined output
must separately run pipeline.py validate and retain its own artifact-bound report.
Do not infer a combined PASS from three branch PASS reports. Record all completed
outputs using search.py record; an unverified output cannot complete a phase.
Do not replace pending top2/top3 branches when top1 improves; only `plan` may
preempt a cycle (leader beats every root by top3_preempt_fraction). Continue incomplete
cycles across runs and finish the current round across tasks before starting a
new general round. Source public methods and research hypotheses to serve the
assigned branches, rather than reverting to a single-best-only search.

Start with the quick incremental public-code check and record new public costs
with `search.py frontier`; then order work by `plan`'s `allocation` (largest public
headroom first). When subagents are allowed, run one subagent per task in parallel.
Runs relay hourly, so checkpoint progress continuously rather than only at the end.

First resume feasible optimizations awaiting generation or full official
validation in the existing hypothesis queue and recent candidate records.
Then choose a high-value pending Top-3 branch or eligible combined step across
DQI, InvSqrt and DFTHC-SOS, giving untouched branches time before repeating
completed work. Screen cheaply for concrete correctness/resource violations, build complete artifacts
for every feasible optimization, and run `automation/pipeline.py validate` on
every feasible candidate, including public-code adaptations and every feasible
variant in a sweep. Estimated cost, small expected gain, lack of an apparent
improvement or uncertain benefit must not skip official verification. Reuse
matching completed evidence; promote only supported official improvements.
A measured infeasibility or official no-gain result counts as progress. Prefer
a concrete budget-feasible experiment to a literature-only run when available.

Complete or resume due public-code comparison and weekly research review using
the skill references and existing records. Use them to improve experiment choice;
change the workflow when an observed problem warrants it. Keep time for the
experiment and checkpoint, and reuse valid evidence.

Reserve time for full verification when choosing the experiment. If the run's
time/resources cannot finish generation or verification, save the candidate IDs,
exact recipe, remaining commands and deferral reason in the existing hypothesis
queue before stop_by. Keep these candidates pending for the next optimization
run; an unfinished check is neither PASS nor a rejection. In the report account
for each feasible candidate as officially checked, matching evidence reused, or
pending with a concrete continuation. Save results and the next hypothesis
before stop_by; leave no unmanaged workers.
Include the pinned Top-3 per task, cycle/step progress, the separately verified
branch outcomes and the separately verified combined outcome (or pending work).
Commit relevant source/documentation changes and write the skill's concise Chinese
run report. This mode does not upload. The existing queue handles verified
improvements under the configured submission policy.

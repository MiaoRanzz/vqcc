Use the repository's $vqcc-optimize skill for the next bounded optimization run
for Google Verifiable Quantum Circuit Compilation. Maximize expected official
combined-score gain through concrete, measured experiments.

`AGENTS.md` holds the gates (every feasible optimization and every combined
result gets its own full official validation; no seed selection; evidence bound
to exact artifacts) and the authorizations. The appended runner context gives the
interpreter, resources, `stop_by` and ready-made commands.

Follow the skill's "Optimization run sequence" in order:

1. Confirm the interpreter.
2. Run `search_plan_command`, then `search_brief_command`; start from the
   brief (previous handoff, finished agent-queued validations, ranked queue,
   allocation shares, due research).
3. Collect finished validations (`promote`, `search.py record`) and resume
   pending candidates before new ideas.
4. Do due research within its caps (quick public check ≤5 min; daily scan ≤15%;
   two-day review ≤25%, which includes public paper reading and ranked
   optimization suggestions written into the hypothesis queue).
5. Spend most of the run on one or more concrete Top-3 experiments, sized by
   allocation `share`. When subagents are allowed, run one per task, sized by share.
6. Checkpoint before `stop_by`: hand long checks to `queue_validate_command`
   instead of waiting on them, write `search.py handoff` for each touched task,
   update the hypothesis queue, save the `search_report_command` skeleton filled
   with this run's results to the run directory, and commit source changes.

Runs relay hourly, so checkpoint continuously. A measured infeasibility or an
official no-gain result is progress. This mode does not upload; the existing
queue handles verified improvements under the submission policy.

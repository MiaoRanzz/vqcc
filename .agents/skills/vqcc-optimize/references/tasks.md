# Task contracts and optimization methods

Contract snapshot: 2026-10-29. Local `verifiers/` and official competition pages
are authoritative; check for official changes when relevant to an experiment.

Maximize the combined score:

`S = ((cost_ref_dqi / cost_dqi) * (cost_ref_invsqrt / cost_invsqrt) * (cost_ref_dfthcsos / cost_dfthcsos)) ** (1/3)`.

Compare expected relative gains per unit effort: halving one task's cost improves
S by `2 ** (1/3)`. Local improvement ratios and platform scores are separate.
Start from the current verified per-task best and its recorded generation recipe.
The implementations below are available routes, not a claim about which is best.

## DQI

- RS(4095,4025), GF(2^12), 70 syndrome registers and 4,095 input phase-mask values.
- Cost: `R(epsilon_plus) * Q**2 * Toffoli`, where
  `R(e) = ln(2) / -ln(1/2 + 2*sqrt(e))`. The sampled error upper bound must be
  below `1/16`; full verification uses 102,400 shots and `log2_delta=-128`.
- Optimize qubit lifetime/recomputation, decoder algorithms, GF arithmetic,
  reversible polynomial operations and root scanning. Compare Q, Toffolis and
  failure probability together; Q enters quadratically. Generation and simulator
  time affect how many hypotheses can be tested.
- The historical Gu adaptation uses a different field representation and phase
  mask. When modifying that family, read `submission/2026-10-29/ADAPTATION.md`
  for finite-field conversion, root order, phase controls and HMR addressing.
- Circuit hash and salt determine sampling. Assess uncertain finalists with the
  existing robustness procedure; hash/seed selection is not circuit optimization.
  Zero/single-error checks are useful diagnostics, not the official distribution.

## InvSqrt

- Cost: `Q * (Toffoli + T/4)`.
- 22-bit input `x`, all integers `1..3,133,452`; phase tolerance is
  `2**-24 / sqrt(x)` turns. Full verification runs each input 64 times and
  checks register restoration and random measurement behavior.
- Optimize approximation family/segmentation, coefficient precision, truncated
  multiplication, workspace reuse and phase synthesis together. An arithmetic
  change can save gates while consuming the margin available for phase synthesis;
  screen the resulting total cost before committing to a full verifier run.
- Use a fixed-point model and relevant segment boundaries for early screening.
  The full official verifier already covers every legal input, so routine extra
  random-input coverage adds little. The paper's Coulomb benchmark is a different
  problem, not a substitute for this contract.

## DFTHC-SOS

- Fixed FeMoCo76o113e instance. Cost:
  `sqrt(E_gap * (2*Lambda - E_gap)) * T_total * Q_total` for the **whole** block
  encoding, including outer/inner PREPARE costs.
- Each ANGLE circuit uses at most 128 qubits. Hamiltonian residual gates must
  pass (20 mHa threshold); `Lambda > 49.0` and `E_gap > 3.914898` are strict.
  See `verifiers/dfthcsos/SCORING_README.md` for residual definitions.
- Factorization and Givens tree must match the words loaded by the ANGLE circuits.
  Indices start at zero without gaps. NPZ fields include `U`, `W`, `H2_I`, `H1_I`,
  `Hsym_lower`, and `tree_edges`; fixed shifts make submitted `H1_I`/`Hsym_lower`
  ineffective optimization knobs.
- Jointly tune factorization dimensions/weights, Givens tree, angle precision and
  lookup structure/batches. Rank by complete block-encoding cost; lowering Lambda
  or ANGLE gate count alone may have little benefit. Requantization needs numerical
  feasibility screening before circuit verification.
- Full verification covers all relevant addresses and randomized measurements.
  Additional seeds are useful for changed measurement-dependent behavior or
  observed instability, rather than as a routine extra pass.

## Available implementation routes

Paths below are relative to the repository root. Select the route matching the
parent's source, inputs and arithmetic family; consult its source/`--help` for
accepted parameters. The common generator takes `--params <params.json>`.
Its default data/source paths are historical examples, so pass the intended
`--source-npz` or `--upstream` explicitly when using a different parent.

| Route | Entry points and useful controls |
|---|---|
| DQI adapted decoder | `generators/generate.py dqi`: `stack_cap`, `sweep_mode=product/phase`, `--upstream`; `generators/profile_dqi.py` profiles lifetimes, `generators/check_dqi_phase.py` checks the phase implementation. |
| InvSqrt Newton arithmetic | `generators/generate.py invsqrt`: arithmetic bit widths and `coefficient_table`; `generators/search_invsqrt_precision.py` and `generators/search_invsqrt_coefficients.py` screen precision/coefficient choices; `generators/screen_invsqrt_tradeoffs.py` includes phase-synthesis cost. |
| InvSqrt piecewise arithmetic | `generators/invsqrt_piecewise.py`: recorded coefficients via `--fit-from`, carry tradeoffs via `--qcap`, and nested-window choice. |
| DFTHC lookup and angle precision | `generators/generate.py dfthcsos`: `--source-npz`, `brot`/`source_brot`, `batch_size`, `prefix_bits`, `lookup_family=reference/prefix/anf`; `generators/screen_dfthcsos_layout.py`, `generators/screen_dfthcsos_anf.py` and `generators/screen_dfthcsos_quantization.py` provide screening routes. |
| DFTHC coefficient gauges | Common generator's `column_gauge_sweeps`; `generators/dfthcsos_gauge_breakpoints.py` screens exact pair-coordinate rotations from `--parent-output`. |
| DFTHC native plan reduction | `generators/dfthcsos_plan_reduce.py`: matching `--source-bank` and `--parent-output`; removes products using exact legal-address relations within the native plan's sign-borrowing contract. |
| Public components | `generators/import_public_bundle.py` imports pinned components; `generators/dfthcsos_public_parts.py` assembles a pinned chemistry recipe with matching parent words/tree. An imported artifact may still lack its full generating source. |

Screening reports guide selection; only the pipeline's full official verification
establishes an eligible improvement. Keep useful alternatives when they offer
better error margin, generation speed or a promising next algorithmic step.

## Competition timing and artifacts

- Submission policy and UTC quota/carryover procedure: [submission.md](submission.md).
  The recorded limits are five submissions per UTC day and up to two final selections.
- Final deadline: 2027-01-21 07:59 Asia/Shanghai (2027-01-20 23:59 UTC).
- Milestones observed: 2026-11-21 07:59 and 2027-01-05 07:59 Asia/Shanghai.
  Check award conditions on the prizes page when preparing milestone materials.
- ZIP root: `dqi.kmb` or `.kmx`, `invsqrt.kmb` or `.kmx`, and
  `dfthcsos/angle_k_0...` plus `dfthcsos/submission.npz`.
- Official sources: [evaluation](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/overview/evaluation),
  [data](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/data),
  [rules](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/rules),
  [prizes](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/overview/prizes).

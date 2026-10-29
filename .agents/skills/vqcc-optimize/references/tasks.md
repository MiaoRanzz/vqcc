# Task contracts and optimization targets

Verified on 2026-10-29. Recheck official changes; local `verifiers/` and official
competition pages are authoritative, and forum claims are research leads.

The combined score is maximized:

`S = ((cost_ref_dqi / cost_dqi) * (cost_ref_invsqrt / cost_invsqrt) * (cost_ref_dfthcsos / cost_dfthcsos)) ** (1/3)`.

Per-task costs are minimized. A 2x gain on one task alone multiplies the combined
score by `2 ** (1/3)`, so compare expected relative gains per unit effort rather
than raw numerical cost magnitudes. Never invent reference costs or equate a
local relative-improvement ratio with a platform leaderboard score.

## DQI

- RS(4095,4025), GF(2^12), 70 syndrome registers and 4,095 input phase-mask values.
- Official cost: `R(epsilon_plus) * Q**2 * Toffoli`, with
  `R(e) = ln(2) / -ln(1/2 + 2*sqrt(e))`. The sampled error upper bound must be
  below `1/16`; the default full verifier uses 102,400 shots and `log2_delta=-128`.
- The circuit hash and salt determine random input and measurement draws.
  Independent sampling is useful to assess uncertain finalists; do not turn
  hash changes or repeated seed selection into an optimization strategy.
- The current baseline adapts Gu et al. from a different field representation
  and fixed phase mask. Read `submission/2026-10-29/ADAPTATION.md` before changing
  finite-field conversion, root order, phase controls, or HMR addressing.
- Directions: decoder algorithm families, qubit lifetime and uncomputation,
  GF arithmetic, reversible polynomial operations, root scanning, and justified
  truncation/failure tradeoffs. Total operation count and simulator time also
  matter to search throughput, even when not in the objective.
- The initial portable generator exposes `stack_cap` (default 1, range 1..35)
  and an optional upstream source path. Other approximations remain unchanged;
  do not describe a stack-cap change as a wholly new decoder.
- Extra zero/single-error tests are diagnostic. Their distribution and score do
  not substitute for the official random distribution.

## InvSqrt

- Official cost: `Q * (Toffoli + T/4)`.
- 22-bit input `x`, all integers `1..3,133,452`; required phase tolerance
  `2**-24 / sqrt(x)` turns. The default verifier runs each input 64 times and
  tests register restoration and random measurement behavior.
- Full validation already covers every legal numerical input. Boundary/segment
  checks are useful for early screening or debugging; redundant random-input
  coverage is not a default extra gate.
- Start from `verifiers/invsqrt/nr_reference_circuit.py`. Precision parameters
  include delta, coefficient, square, product, and result bits. Screen an
  arithmetic change with its fixed-point model before generating the circuit.
- The portable generator accepts `delta_bits`, `coef_bits`, `square_bits`,
  `product_bits`, and `result_bits`; starting values are 14, 17, 28, 28, 29. It
  performs an all-input fixed-point screening check before building. That cheap
  arithmetic check does not replace the official circuit/phase verifier.
- Directions: approximation families and segmentation, coefficient precision,
  truncated multiplication, workspace recycling, phase synthesis, and resource
  scheduling. The paper's Coulomb benchmark is not this contract.

## DFTHC-SOS

- Fixed FeMoCo76o113e chemistry instance. Cost is
  `sqrt(E_gap * (2*Lambda - E_gap)) * T_total * Q_total` for the **whole** block
  encoding, including the outer/inner PREPARE cost model.
- Each ANGLE circuit must use at most 128 qubits. Hamiltonian residual gates
  must pass (20 mHa threshold); `Lambda > 49.0` and `E_gap > 3.914898` are strict.
  Consult `verifiers/dfthcsos/SCORING_README.md` for precise residual definitions.
- Factorization and Givens tree must agree with the words actually loaded by
  the ANGLE circuits. ANGLE indices start at zero without gaps. The NPZ includes
  `U`, `W`, `H2_I`, `H1_I`, `Hsym_lower`, and `tree_edges`; fixed shifts make the
  submitted `H1_I`/`Hsym_lower` ineffective optimization knobs.
- Directions: jointly tune decomposition dimensions/weights, Givens tree,
  quantization and QROM batches, while counting complete `T_total * Q_total`.
  Lowering lambda alone may provide little gain; verify any claimed lower bound.
- The portable generator starts with `brot=12`, `source_brot=12`, and
  `batch_size=8`, optionally taking a different source NPZ. Changing `brot`
  requantizes angle words while preserving factorization arrays; numerical
  feasibility must be verified afterward.
- Full verification recovers all relevant addresses and checks randomized
  measurements. Add extra seeds only when a changed measurement-dependent
  implementation or observed instability justifies them.

## Competition timing and artifacts

- User policy: one improved daily submission at 20:00 Asia/Shanghai, otherwise
  skip. Official maximum observed: five daily submissions, up to two final
  selections. Do not consume the unused quota automatically.
- Final deadline: 2027-01-21 07:59 Asia/Shanghai (2027-01-20 23:59 UTC).
- Milestone dates observed: 2026-11-21 07:59 and 2027-01-05 07:59 Asia/Shanghai.
  Check exact award conditions on the prizes page before preparing a release.
- ZIP root contains `dqi.kmb` or `.kmx`, `invsqrt.kmb` or `.kmx`, and
  `dfthcsos/angle_k_0...` plus `dfthcsos/submission.npz`. No extra enclosing folder.
- Sources: [evaluation](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/overview/evaluation),
  [data](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/data),
  [rules](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/rules),
  [prizes](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/overview/prizes).

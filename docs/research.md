# VQCC research starting point

Snapshot: 2026-10-29, Asia/Shanghai. This is a starting hypothesis map, not a claim
that the cited circuits or performance numbers have been reproduced here.
Maintain subsequent experiments, negative results, source snapshots, and topic
cursors in the configured artifact store; commit substantive source adaptations.

## Current measured starting point

The historical `submission/2026-10-29/` contains an adapted Gu et al. DQI circuit
and unchanged official InvSqrt/DFTHC-SOS samples. The saved full local verifier
reports passed. DQI has 1,842 qubits and 566,880 Toffolis; its official local cost
is approximately `2.34627e12`. InvSqrt cost is `2.07677e6`; DFTHC-SOS cost is
`3.35560e9`. These are per-task costs to minimize, not leaderboard scores.

Submission #57763974 is recorded, but the MCP response available at this snapshot
omits evaluation status and score. Track those fields as unknown until evidence
arrives. Read the archived ADAPTATION.md for actual contract differences.

## Initial priority queue

| Route | Why test it | First useful evidence |
| --- | --- | --- |
| InvSqrt precision and arithmetic family | It remains the official sample; existing fixed-point model enables cheap all-input screening | Worst-case phase error, circuit Q/Toffoli/T, full verifier report |
| DQI qubit lifetime and decoder architecture | Q is squared in this task's objective; public lower-qubit claims warrant inspection | Adaptation/permission evidence, Q/Toffoli/error tradeoff under official contract |
| DFTHC-SOS joint word/QROM/tree optimization | Whole block-encoding cost matters; isolated lambda or ANGLE gains can mislead | Total cost, residual margins, per-ANGLE width, factorization/circuit agreement |
| Search throughput | Faster valid screening can increase the number of useful experiments | Agreement with official outputs and measured wall time on this machine |

Do not assume GPUs help every route. Arithmetic/circuit generation and official
simulators can be CPU-bound; prioritize actual bottlenecks before parallelizing.

## Primary research

- [Competition paper: Leveraging verifiable structure in quantum circuits to find more efficient compilations with agentic AI](https://arxiv.org/abs/2610.23832), first posted 2026-10-16, v2 2026-10-21.
  Start with the exact benchmark contracts and verifier assumptions.
- [Gu et al., Discovering state-of-the-art quantum circuits with large language models](https://arxiv.org/abs/2610.22367), 2026-10-15;
  [source repository](https://github.com/andigu/uncompute). Existing adaptation
  pins `64b5a13aa249f1360846657392e6c66817b26d0f` and retains Apache-2.0 evidence.
  The search design supports multiple algorithm families, parent-child lineage,
  negative feedback, and a resource-tradeoff archive. Replace its metric with
  each competition task's actual objective. Its Coulomb and FeS benchmarks are
  not drop-in solutions for this competition's InvSqrt and FeMoCo tasks.
- [Verifiable Quantum Advantage via Optimized DQI Circuits](https://arxiv.org/abs/2510.10967), 2025-10-13.
  Compare reversible RS decoding, Euclidean/Bézout methods, and workspace use.
- [Fast quantum simulation of electronic structure by spectrum amplification](https://arxiv.org/abs/2502.15882), 2025-02-21, later PRX 15, 041016.
  Map DFTHC-SOS ideas to the fixed FeMoCo instance and complete cost model.
- [Optimizing Quantum Circuits for Arithmetic](https://arxiv.org/abs/1805.12445), 2018-05-31.
  Foundational arithmetic and inverse-square-root ideas; an older reference,
  included for relevance rather than represented as a recent paper.

## Discussion leads to revisit through Kaggle MCP

Use [recently commented discussions](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion?sort=recent-comments)
and fetch the actual topic messages. Keep retrieval dates and distinguish claims
from reproductions.

- [Two-stage search loop](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753741), 2026-10-29:
  qubit lifetimes/uncomputation before local rewriting; a proposal to test.
- [Measured negative results](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753185), 2026-10-27 with later replies:
  avoid repeating the same tested parameter regions, while preserving the
  conditions under which each failure was observed.
- [Chemistry lambda discussion](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753633), 2026-10-28:
  inspect claimed improvement limits before spending a large budget on lambda
  alone. Numerical bounds are not independently established here.
- [kickmix-engine and cross-checking](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753642), 2026-10-28:
  optional screening backend; first measure correctness agreement and throughput.
  The official verifier remains the submission gate.
- [InvSqrt circuit viewer](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753403), 2026-10-28:
  inspect the reported 63-qubit, 1,348-Toffoli construction and its provenance.
  A visualization or an observed zero register does not prove safe reuse.
- [DQI source-license question](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753740)
  and [permission request](https://www.kaggle.com/competitions/google-verifiable-quantum-circuit-compilation/discussion/753660), 2026-10-29:
  check the full source chain and any organizer response before incorporating
  affected QuantumAI-derived code. Do not infer a legal conclusion from a title
  or consider a downstream notebook label sufficient evidence.

## What to record for each research decision

Record source URL/version, claim, task-contract differences, license evidence,
proposed change, expected official-cost effect, experiment ID and parent,
measured outcome, counterexample/failure reason, and next action. Record a
negative result's tested scope so it remains useful without forbidding unrelated
variants. Revisit stale negative results when the algorithm or contract changes.

## First bounded optimization update — 2026-10-29

The completed run `20261029T164657-optimize-deee74` promoted two officially verified
improvements: InvSqrt `1,941,280.5598621224` (256 qubits, 7,327 Toffolis) and
DFTHC-SOS `3,247,752,448.668952` (742 whole-block qubits, 88,781 Toffolis).
DQI remains `2,346,266,562,950.239`. Combined local improvement over the submitted
baseline is `1.0339417327`; platform score remains unknown. No upload occurred.

See [experiment and reproduction details](experiments/2026-10-29-bounded.md).
All precision failures and retained margin/resource tradeoffs are in the experiment
store. Topic cursors and the ranked next-run queue now live under
`artifacts/research/`; review these before repeating initial leads. The next
priority is a measured lifetime/recomputation analysis of the pinned, licensed
DQI family; chemistry lookup families and InvSqrt coefficient/precision co-tuning
remain active routes. Imported public frontier claims are still unreplicated.

## Second bounded update — 2026-10-29

Run `20261029T181000-optimize-1095d3` promoted the direct runtime-mask DQI
product phase: cost `1847158218915.0073`, 1842 qubits, 444030 Toffolis.
Official full verification passed (102400 shots; 0 value errors, 9 phase errors);
all source and artifact evidence is preserved. Combined local improvement over
the submitted baseline is `1.1197484843`. No upload occurred; platform score
remains unknown. See [experiment and reproduction details](experiments/2026-10-29-dqi-phase.md).

The measured lifetime profile did not reduce qubits: sweep peaks at 1842 and
Euclid at 1837, with 444 long-lived BM B-bank bits. Next-run queue now rotates
to chemistry Boolean lookup decomposition, then InvSqrt coefficient co-tuning;
a larger DQI state-recomputation route remains active. Original and corrected
profiling diagnostics and typed-control harness failures are retained.

## Third bounded update — 2026-10-30 (Asia/Shanghai)

Run `20261030T001000-optimize-565f4a` promoted exact-word ANF lookup candidate
`20261030T002957-dfthcsos-8907aa`: DFTHC-SOS cost `3143055863.722955`,
85,919 whole-block Toffolis and 742 qubits. Official full verification and the
precommitted arbitrary-target cleanup check passed. Combined local improvement
over the submitted baseline is `1.1320460391`; no upload occurred.
See [evidence and reproduction](experiments/2026-10-30-dfthcsos-anf.md).

Nine resource combinations retain cap failures and lower-ANGLE-width tradeoffs;
the initial screening API counting error is explicitly invalidated and archived.
Kaggle was inaccessible this run, so the successful message cursor did not advance.
The queue now prioritizes InvSqrt coefficient co-tuning, followed by DQI state
recomputation and chemistry quantization screening.

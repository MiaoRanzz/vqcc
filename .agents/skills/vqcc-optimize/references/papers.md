# Public paper reading

Papers supply techniques; only full official validation measures a gain. Read
them for this competition's exact contracts in [tasks.md](tasks.md): costs are
`R(ε)·Q²·Toffoli` (DQI), `Q·(Toffoli + T/4)` (InvSqrt) and the whole
block-encoding `sqrt(E_gap(2Λ−E_gap))·T·Q` (DFTHC-SOS). A paper's own resource
metric, benchmark instance or asymptotic claim is not our cost.

## When

- **Every two-day review** (≤15% of a run): targeted reading chosen from the
  retrospective (see [review.md](review.md)).
- **During an experiment**, as needed: the primary source for the active idea.
  Reuse the library entry rather than re-reading.

## Finding papers

Start from the task's measured bottleneck, then search arXiv (listing/abstract
pages and full text), references and citations of papers already in the library,
and papers cited by public notebooks and Kaggle threads. Check for new versions
of library papers. Prefer primary sources and full text over summaries.

Starting topics (leads to confirm on retrieval, not established results):

| Task | Topics and known starting points |
|---|---|
| DQI | Decoded quantum interferometry (Jordan et al., arXiv:2408.08292); reversible/quantum Reed–Solomon and BCH syndrome decoding (Berlekamp–Massey, extended Euclid, Chien search); GF(2^m) multiplication and inversion circuits (basis choice, Karatsuba, Itoh–Tsujii); measurement-based uncomputation and temporary logical-AND (Gidney, arXiv:1709.06648); conditionally clean ancillae (Khattar & Gidney, arXiv:2407.17966); qubit-recycling and pebbling schedules. Q enters squared, so width reductions weigh most. |
| InvSqrt | Quantum fixed-point arithmetic and piecewise polynomial evaluation (Häner, Roetteler & Svore, arXiv:1805.12445); Newton–Raphson inverse square root; windowed arithmetic and lookup (Gidney, arXiv:1905.07682); adder cost (arXiv:1709.06648); truncated/approximate multiplication error analysis; phase-gradient rotations and single-qubit synthesis cost (Ross & Selinger, arXiv:1403.2975). |
| DFTHC-SOS | Double factorization and QROAM (Berry et al., arXiv:1902.02134; von Burg et al., arXiv:2007.14460); tensor hypercontraction block encodings (Lee et al., arXiv:2011.03494); unary iteration and QROM (Babbush et al., arXiv:1805.03662); dirty-qubit lookup tradeoffs (Low, Kliuchnikov & Schaeffer, arXiv:1812.00954); state preparation without arithmetic (Sanders et al., arXiv:1807.03206); Givens-rotation compression and angle precision; spectrum-amplified or regularized factorizations that lower Λ at fixed residual. |
| Contract | The competition paper (arXiv:2610.23832) and Gu et al. (arXiv:2610.22367); see `docs/research.md`. |

## Reading a paper

1. Record the identifier, version and retrieval time before reading. Note the
   license only if code or data from it will be reused.
2. Read the sections that define the technique and its resource accounting.
   Translate the claimed savings into our cost formula: which of Q, Toffoli, T,
   Λ, E_gap or failure rate changes, by how much, and what it costs elsewhere
   (extra ancillas, precision margin, measurement-dependent behavior, error budget).
3. Check compatibility with the current best recipe: field representation,
   phase-mask convention, input domain, ANGLE 128-qubit cap, NPZ/word agreement,
   verifier assumptions.
4. Write ideas only when they map to a concrete change in one of our generators
   or a new route. "Not applicable because …" is a useful outcome; record it.

## Records

`research/papers/index.json` (create it on first use; keep the format stable):

```json
{
  "papers": {
    "arXiv:1805.12445": {
      "title": "...", "version": "v2", "retrieved_at": "2026-11-03T10:00:00+08:00",
      "tasks": ["invsqrt"], "depth": "full|sections|abstract",
      "sections_read": ["3", "4.2"],
      "summary": "Technique and its resource accounting in two or three sentences",
      "applicability": "How it maps onto our cost and current recipe, or why not",
      "ideas": ["hypothesis id in research/hypotheses.json"],
      "status": "read|partial|queued|not_applicable",
      "review_period": "2026-11-01"
    }
  },
  "queue": [{"id": "arXiv:...", "task": "dqi", "reason": "why it is worth reading next"}],
  "updated_at": "..."
}
```

Each idea goes into `research/hypotheses.json` with `source: "paper:<id> §<section>"`
and the estimate fields required by [review.md](review.md) section 3. Record
reading that runs out of budget as `partial` with the sections left.

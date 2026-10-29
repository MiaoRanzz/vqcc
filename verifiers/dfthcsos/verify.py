"""Score a DFTHC-SOS submission: ANGLE_k kickmix circuits plus the factorization.

``verify(circuits, factorization) -> dict`` scores a FeMoCo76o113e submission:
``score = lambda_eff * T_total * Q_total`` (lower is better) with a summary of
the costs and metrics, or raises if it is rejected. Everything the score
needs is in this package; this module builds on ``dfthcsos.scoreinfra``: the
reference integrals (``scoreinfra.reference``), the circuit simulation
(``scoreinfra.circuits``), the DF-THC metrics (``scoreinfra.dfthc_math``) and
the state-preparation cost model (``scoreinfra.costs_prepare``).

Usage::

    from dfthcsos.verify import verify

    verify("run_dir/")
    verify("run_dir/", "run_dir/submission.npz")
    verify(["a.kmx", "b.kmx"], "factorization.npz", tree_edges=edges)

    python dfthcsos/verify.py run_dir/ [--salt STR] [--seed N]
    python dfthcsos/verify.py run_dir/submission.npz run_dir/
    python dfthcsos/verify.py factorization.npz a.kmx b.kmx --tree-edges edges.npy

Inputs
------
* ``circuits``: a directory with ``angle_k_0.kmx``, ``angle_k_1.kmx``, ... (or
  ``.kmb``), or the circuit files in order. They must follow the register rules in
  ``dfthcsos/scoreinfra/circuits.py``; ``brot`` and ``J`` are read from the
  circuits.
* ``factorization``: an ``.npz`` with the trainer's ``U``, ``W``, ``H2_I``,
  ``H1_I`` and ``Hsym_lower`` (``dfthcsos/scoreinfra/reference.py``). It
  supplies the weights; the circuits only load the angle words. The symmetry
  shift ``(S, beta_1)`` is fixed to the provided baseline's: the submitted
  ``H1_I`` and ``Hsym_lower`` are ignored. Optional when
  ``circuits`` is a directory containing ``submission.npz``. Pickles are not accepted:
  save the arrays with ``numpy.savez``. The starter trainer writes NPZ
  directly, and the
  ``submission.npz`` written by its ``build_circuits.py`` also holds them.
* ``tree_edges``: the ``(N - 1, 2)`` Givens tree the words are defined on, as
  an array or a ``.npy``/``.npz`` file. Optional if the circuits directory
  contains ``submission.npz`` with ``tree_edges``.

The reference integrals are not an input: the score always uses the
FeMoCo76o113e FCIDUMP packaged with ``dfthcsos``, after checking its SHA-256.
Measurement outcomes (``HMR`` and ``R``) are seeded with
``initial_seed(submission_sha256(...), salt)``: the SHA-256 of the whole
submission (circuits, factorization and tree), merged with ``--salt`` when
given, or overridden by ``--seed``.

Score
-----
::

    score      = lambda_eff * T_total * Q_total
    lambda_eff = sqrt(E_gap * (2 Lambda - E_gap))       of the words the circuits load
    T_total    = ANGLES Toffolis                        mean per shot in kickmix, U_T and U_T^dagger
               + outer_state_prep + inner_state_prep    Toffolis, SpinFreeData_V1 (incl. _dag)
               + 2 * (N - 1) * (2 * brot - 1)           Toffolis, Givens rotations (U_T and U_T^dagger)
    Q_total    = outer_persistent + inner_persistent    persistent state-prep qubits, SpinFreeData_V1
               + J * brot                               persistent angle-word registers
               + max(outer_temp, inner_temp, ang_temp)  shared temporary workspace

The ANGLE_k circuits run sequentially and share their workspace with the outer
and inner state preparations, so temporary workspace is the maximum across
stages, not the sum. ``SpinFreeData_V1`` uses ``R, B, C, N``,
``chi = KEEP_BITS`` and ``beta = brot``. The metrics behind ``lambda_eff``
are defined in ``evaluate_words``.

Rejected (``verify`` raises ``AssertionError`` or ``InvalidCircuits``; the
command line prints ``{"status": "FAIL", "error": ...}`` and exits 1) if
* ``error_1`` or ``error_2`` of the words the circuits load exceeds 20 mHa;
* the SOS gap is outside ``(0, 2 * Lambda)``;
* raw ``Lambda <= 49.0`` or ``E_gap <= 3.914898`` Ha;
* any ANGLE_k circuit uses more than 128 qubits;
* the circuits break the register contract or do not load consistent words
  (``dfthcsos.scoreinfra.circuits.InvalidCircuits``).
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import numpy.typing as npt

# Development shim: allow `python dfthcsos/verify.py` without installing.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

# The verifier is self-contained: it imports nothing from dfthc and needs only
# numpy, scipy and kickmix.
from dfthcsos.scoreinfra.circuits import (  # noqa: E402
    FORMATS,
    SHOTS_PER_ADDRESS,
    InvalidCircuits,
    initial_seed,
    load_circuits,
    recover_words_from_circuits,
    register_layout,
    submission_sha256,
)
from dfthcsos.scoreinfra.costs_prepare import SpinFreeData_V1  # noqa: E402
from dfthcsos.scoreinfra.dfthc_math import evaluate_dfthc_angle_words, symmetric_from_lower  # noqa: E402
from dfthcsos.scoreinfra.reference import (  # noqa: E402
    ORBITALS,
    SYSTEM,
    UPPER_ENERGY,
    check_fcidump,
    load_factorization,
    load_fixed_shifts,
    load_reference,
)

# Qaggle Eq. (48): 20 mHa Frobenius-norm bound on the two-body residual. The
# same bound is applied to the one-body residual after quantization.
ERROR_2_THRESHOLD = 0.020
ERROR_1_THRESHOLD = 0.020

# Strict floors on the raw LCU normalization Lambda and the SOS gap.
# Equality fails; computed values are never clamped. lambda_eff remains the
# score factor and has no separate acceptance floor. E_GAP_FLOOR is the
# difference between the supplied active-space DMRG and SOS-SDP energies.
LAMBDA_FLOOR = 49.0
E_GAP_FLOOR = 3.914898  # Hartree

# Hard limit on the ANGLE_k circuit width: if any ANGLE_k circuit uses more
# qubits than this, the score is inf.
QUBIT_CAP = 128

# Keep-value bits (chi) of the outer and inner alias-sampling state
# preparations in the heuristic cost model. Fixed by the competition: it is
# not a verifier option, since a smaller value would lower every score.
KEEP_BITS = 10

# The file next to a family's .kmx files that build_circuits.py writes; the
# verifier reads tree_edges from it when none are given.
SUBMISSION_FILE = "submission.npz"


# ---------------------------------------------------------------------------
# Inputs: the factorization and the reference integrals
# ---------------------------------------------------------------------------


def native_inputs(
    params: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Convert optimizer coordinates to the native Qaggle (w, W, S, beta_1).

    The factorization stores lowercase w as ``W``, ``w_B = W + sum_b w`` as
    ``H2_I``, ``S`` through its lower triangle ``Hsym_lower``, and
    ``beta_1 + Tr(S)/2`` as ``H1_I``. ``S`` is rounded to float32 first, as
    the trainer's ``H1_from_lower`` does.
    """
    w = np.asarray(params["W"], dtype=np.float64)
    W = np.asarray(params["H2_I"], dtype=np.float64) - np.sum(w, axis=1)
    S = np.asarray(
        symmetric_from_lower(params["Hsym_lower"], np.shape(params["U"])[-1]),
        dtype=np.float64,
    )
    beta_1 = float(params["H1_I"]) - 0.5 * float(np.trace(S))
    return w, W, S, beta_1


@dataclass(frozen=True)
class SubmissionInputs:
    """A factorization together with the FeMoCo76o113e reference data.

    ``ref`` is ``dfthcsos.scoreinfra.reference.load_reference`` of the FCIDUMP:
    ``{orbitals, electrons, ecore, oei, tei, h1_thc}``. ``factorization_file``
    is the ``.npz`` the arrays came from, or ``None`` for in-memory arrays.
    """

    factorization_file: Path | None
    params: dict[str, np.ndarray]
    ref: dict[str, Any]
    w: np.ndarray
    W: np.ndarray
    S: np.ndarray
    beta_1: float
    energy_upper: float

    @property
    def num_orbitals(self) -> int:
        return int(self.ref["orbitals"])

    @property
    def num_vectors(self) -> int:
        """``N + R*B``: the one-body rows followed by the two-body rows."""
        rank_r, bases_b, _ = self.w.shape
        return self.num_orbitals + rank_r * bases_b


def load_inputs(
    factorization: str | Path | Mapping[str, npt.ArrayLike],
) -> SubmissionInputs:
    """Load a factorization and the FeMoCo76o113e FCIDUMP and E_upper.

    ``factorization`` is an ``.npz`` path or a mapping of arrays
    (``dfthcsos.scoreinfra.reference.load_factorization``). The integrals are
    always the packaged reference FCIDUMP; ``check_fcidump`` confirms its size
    and SHA-256 before it is read, and raises if the file was modified. The
    symmetry shift is always the baseline's (``load_fixed_shifts``): the
    submitted ``H1_I`` and ``Hsym_lower`` are replaced before ``S`` and
    ``beta_1`` are derived.
    """
    params = load_factorization(factorization)
    if np.shape(params["U"])[-1] != ORBITALS:
        raise ValueError(
            f"factorization has {np.shape(params['U'])[-1]} orbitals, {SYSTEM} has {ORBITALS}"
        )
    params.update(load_fixed_shifts())
    ref = load_reference(check_fcidump())
    w, W, S, beta_1 = native_inputs(params)
    return SubmissionInputs(
        factorization_file=None if isinstance(factorization, Mapping) else Path(factorization),
        params=params,
        ref=ref,
        w=w,
        W=W,
        S=S,
        beta_1=beta_1,
        energy_upper=UPPER_ENERGY,
    )


def load_tree_edges(
    tree_edges: npt.ArrayLike | str | Path | None, circuits: Any
) -> np.ndarray:
    """Resolve ``tree_edges``: an array, a ``.npy``/``.npz`` path, or ``None``.

    With ``None`` the edges are read from ``submission.npz`` next to the
    circuits, which requires ``circuits`` to be a directory.
    """
    if tree_edges is None:
        if not (isinstance(circuits, (str, Path)) and Path(circuits).is_dir()):
            raise ValueError(
                "tree_edges is required unless circuits is a directory with "
                f"{SUBMISSION_FILE}"
            )
        tree_edges = Path(circuits) / SUBMISSION_FILE
        if not tree_edges.is_file():
            raise FileNotFoundError(
                f"no {SUBMISSION_FILE} in {circuits}; pass tree_edges explicitly"
            )
    if isinstance(tree_edges, (str, Path)):
        loaded = np.load(tree_edges, allow_pickle=False)
        if isinstance(loaded, np.ndarray):
            tree_edges = loaded
        else:
            with loaded as data:
                tree_edges = np.array(data["tree_edges"])
    edges = np.asarray(tree_edges)
    if edges.ndim != 2 or edges.shape[1] != 2 or not np.issubdtype(edges.dtype, np.integer):
        raise ValueError(f"tree_edges must be an (N - 1, 2) integer array, got {edges.shape}")
    return edges.astype(np.int64)


# ---------------------------------------------------------------------------
# Metrics of the words the circuits load
# ---------------------------------------------------------------------------


def evaluate_words(
    inputs: SubmissionInputs,
    angle_words: npt.ArrayLike,
    tree_edges: npt.ArrayLike,
    brot: int,
) -> dict[str, float | bool]:
    """The DF-THC metrics of an angle-word table.

    What is evaluated
    -----------------
    Each row of the ``(N + R*B, N - 1)`` integer table is decoded on the
    Givens tree ``tree_edges``, with ``theta / pi = word / 2**(brot - 1)``,
    into a unit vector of length ``N``:

    * rows ``0 .. N-1``: the one-body vectors, meant to be the eigenvectors of
      ``h1_prime`` (below);
    * rows ``N .. N+R*B-1``: the two-body vectors ``u_b^(rho)`` in
      ``(rho, b)`` order.

    The verifier (``dfthcsos.scoreinfra.dfthc_math.evaluate_dfthc_vectors``) combines
    them with the scalars and tensors ``w`` (R, B, C), ``W`` (R, C), ``S``
    (N, N) and ``beta_1`` from the factorization (see ``native_inputs``) and
    the original FCIDUMP integrals ``oei = h^(1)`` and ``tei = (pq|rs)``.

    Intermediate quantities (from the decoded two-body vectors)
    -----------------------------------------------------------
    ::

        X^(rho c)_pq = sum_b w_b^(rho c) u_b^(rho)_p u_b^(rho)_q
                       (symmetrized from the lower triangle)
        H1_THC       = oei_pq - 1/2 sum_r (pr|rq)
        h1_prime     = H1_THC - (eta/2) S + beta_1 I - sum_(rho c) W^(rho c) X^(rho c)
                       (qaggle.tex Eq. exact-one-body-absorption)
        lambda_j     = eigenvalues of h1_prime

    ``h1_prime`` is always built from the *decoded* ``X``, so rounding the
    two-body angles changes ``h1_prime`` (and hence ``lambda_j``) consistently.
    It never shows up as a one-body error.

    Returned metrics (all energies in Hartree)
    ------------------------------------------
    ``error_1``
        One-body residual, ``||H1_THC(submitted) - H1_THC||_F``. The verifier
        pairs each submitted one-body row ``v_j`` with an exact eigenvector of
        ``h1_prime`` (a one-to-one assignment on ``|overlap|``, so row order and
        signs do not matter). It gives that row the matching eigenvalue
        ``lambda_j`` and rebuilds ``sum_j lambda_j v_j v_j^T``. Undoing the
        shifts gives ``H1_THC(submitted)``. The shifts cancel, so this equals
        ``||sum_j lambda_j v_j v_j^T - h1_prime||_F``: how well the one-body
        rows encode ``h1_prime``. It shrinks with ``brot`` and is compared
        with the 20 mHa bound (``ERROR_1_THRESHOLD``). This is the "residual
        of the 1-electron component" in qaggle.tex.
    ``error_2``
        Two-body residual ``epsilon_fro``, the Frobenius norm over all ``N**4``
        chemist-order entries::

            || sum_(rho c) X^(rho c) (x) X^(rho c) - (S (x) I + I (x) S)/2 - (pq|rs) ||_F

        This is compared with the 20 mHa bound (``ERROR_2_THRESHOLD``). It
        includes the rounding error of the two-body rows.
    ``Lambda``
        LCU one-norm (qaggle.tex Eq. dfthc-normalization)::

            sum_j |lambda_j| + 1/4 sum_(rho c) (|w_B^(rho c)| + sum_b |w_b^(rho c)|)**2,
            w_B^(rho c) = W^(rho c) + sum_b w_b^(rho c)
    ``E_SOS``
        Sum-of-squares lower bound on the DFTHC Hamiltonian's energy,
        including the FCIDUMP core energy::

            ecore - eta beta_1 - (sum_j |lambda_j| - sum_j lambda_j) - 1/2 sum_(rho c) W^(rho c)**2
    ``E_gap``
        ``E_upper - E_SOS``, where ``E_upper`` is the reference energy
        ``dfthcsos.scoreinfra.reference.UPPER_ENERGY``. It stands in for the ground-state
        energy, so this is an estimate; the many-body Hamiltonian is not
        diagonalized.
    ``gap_in_domain``
        ``0 < E_gap < 2 * Lambda``, including the high-precision radicand check.
    ``lambda_eff``
        Spectrum-amplified one-norm ``sqrt(E_gap * (2 Lambda - E_gap))``
        (qaggle.tex Eq. effective-normalization). It is ``nan`` when the gap is
        out of domain. It is the first factor of the score.

    ``score_from_metrics`` turns these into the score: ``inf`` if
    ``error_1`` or ``error_2`` exceeds 20 mHa, the gap is out of domain,
    ``Lambda <= LAMBDA_FLOOR`` or ``E_gap <= E_GAP_FLOOR``, otherwise
    ``lambda_eff`` times the Toffoli and qubit counts (see ``resource_costs``).
    """
    return evaluate_dfthc_angle_words(
        angle_words, inputs.w, inputs.W, inputs.S, inputs.beta_1, inputs.ref,
        brot=brot, tree_edges=tree_edges, energy_upper=inputs.energy_upper,
    )


def _floor_rejection_reasons(metrics: Mapping[str, Any]) -> list[str]:
    """Reject missing/nonfinite values and equality at either strict floor."""
    reasons = []
    for name, floor in (("Lambda", LAMBDA_FLOOR), ("E_gap", E_GAP_FLOOR)):
        value = float(metrics.get(name, np.nan))
        if not np.isfinite(value) or value <= floor:
            reasons.append(f"{name} = {value:.17g} must be finite and > {floor} (strict floor)")
    return reasons


def passes_accuracy(metrics: Mapping[str, Any]) -> bool:
    """Check both 20 mHa limits, the valid domain, and strict Lambda/gap floors."""
    return bool(
        metrics["error_1"] <= ERROR_1_THRESHOLD
        and metrics["error_2"] <= ERROR_2_THRESHOLD
        and metrics["gap_in_domain"]
        and np.isfinite(metrics["lambda_eff"])
        and not _floor_rejection_reasons(metrics)
    )


# ---------------------------------------------------------------------------
# Costs: T_total and Q_total
# ---------------------------------------------------------------------------


def angles_costs(circuits: Iterable[Any], toffoli: float) -> dict[str, int | float]:
    """Toffoli and qubit counts of an ANGLE_k family of kickmix circuits.

    ``toffoli`` is the simulator's count from ``recover_words_from_circuits``:
    the mean number of Toffoli-like gates executed per shot over the forward
    (``U_T``) and reverse (``U_T^dagger``) pass; ``toffoli_per_pass`` is half of
    it. ``qubits`` is the maximum over k of ``Circuit.num_qubits`` (workspace
    included). In the block encoding, ``selection`` is the address register from
    the state preparations, the ``J`` word registers (``J * brot`` qubits) stay
    live across the Givens rotations (``persistent_qubits``), and the remaining
    workspace qubits return to ``|0>`` after each circuit (``temporary_qubits``).
    """
    circuits = tuple(circuits)
    if not circuits:
        raise ValueError("circuits must be nonempty")
    layout = register_layout(circuits)
    qubits = max(int(circuit.num_qubits) for circuit in circuits)
    selection_qubits = len(layout.selection)
    persistent_qubits = layout.batch_size * layout.brot
    temporary_qubits = qubits - selection_qubits - persistent_qubits
    return {
        "toffoli_per_pass": toffoli / 2,
        "toffoli": toffoli,
        "qubits": qubits,
        "selection_qubits": selection_qubits,
        "persistent_qubits": persistent_qubits,
        "temporary_qubits": temporary_qubits,
    }


def heuristic_costs(
    num_orbitals: int,
    rank_r: int,
    bases_b: int,
    ensemble_c: int,
    brot: int,
) -> dict[str, int]:
    """State-preparation and Givens-rotation costs from ``SpinFreeData_V1``.

    Toffoli counts are ``outer_state_prep()``, ``inner_state_prep()`` and
    ``givens_rotations()`` (one block-encoding pass ``O_x``: each state prep
    already includes its uncomputation, and the ``N - 1`` Givens rotations run
    in ``U_T`` and ``U_T^dagger``). Qubit counts share temporary workspace
    between the sequential outer and inner state preparations:
    ``persistent_qubits + max(outer_temporary, inner_temporary)``. ``chi = KEEP_BITS``
    (fixed) and ``beta = brot``.
    """
    model = SpinFreeData_V1(
        R=int(rank_r),
        B=int(bases_b),
        C=int(ensemble_c),
        N=int(num_orbitals),
        chi=KEEP_BITS,
        beta=int(brot),
    )
    outer_qubits = model.outer_state_prep_qubit_cost()
    inner_qubits = model.inner_state_prep_qubit_cost()
    outer_persistent = int(outer_qubits["persistent"])
    outer_temporary = int(outer_qubits["temporary"])
    inner_persistent = int(inner_qubits["persistent"])
    inner_temporary = int(inner_qubits["temporary"])
    costs = {
        "outer_state_prep_toffoli": int(model.outer_state_prep()),
        "inner_state_prep_toffoli": int(model.inner_state_prep()),
        "givens_rotations_toffoli": int(model.givens_rotations()),
        "outer_state_prep_persistent_qubits": outer_persistent,
        "outer_state_prep_temporary_qubits": outer_temporary,
        "outer_state_prep_qubits": outer_persistent + outer_temporary,
        "inner_state_prep_persistent_qubits": inner_persistent,
        "inner_state_prep_temporary_qubits": inner_temporary,
        "inner_state_prep_qubits": inner_persistent + inner_temporary,
    }
    costs["persistent_qubits"] = outer_persistent + inner_persistent
    costs["temporary_qubits"] = max(outer_temporary, inner_temporary)
    costs["toffoli"] = (
        costs["outer_state_prep_toffoli"]
        + costs["inner_state_prep_toffoli"]
        + costs["givens_rotations_toffoli"]
    )
    costs["qubits"] = costs["persistent_qubits"] + costs["temporary_qubits"]
    return costs


def resource_costs(
    inputs: SubmissionInputs,
    circuits: Iterable[Any],
    brot: int,
    angles_toffoli: float,
) -> dict[str, int | float | bool]:
    """``T_total`` and ``Q_total`` of the score (see the module docstring).

    ``angles_toffoli`` is the simulator's Toffoli count of the ANGLES family
    (``recover_words_from_circuits``).

    Returns the ANGLES and heuristic parts, the shared-workspace qubit breakdown
    (``persistent_qubits`` and ``temporary_qubits``), their totals ``toffoli``
    and ``qubits``, and ``angles_within_cap`` (``angles_qubits <= QUBIT_CAP``).
    """
    rank_r, bases_b, ensemble_c = inputs.w.shape
    angles = angles_costs(circuits, angles_toffoli)
    heuristic = heuristic_costs(inputs.num_orbitals, rank_r, bases_b, ensemble_c, brot)
    toffoli = angles["toffoli"] + heuristic["toffoli"]
    persistent_qubits = heuristic["persistent_qubits"] + angles["persistent_qubits"]
    temporary_qubits = max(heuristic["temporary_qubits"], angles["temporary_qubits"])
    qubits = persistent_qubits + temporary_qubits
    return {
        "brot": int(brot),
        "keep_bits": KEEP_BITS,
        "angles_toffoli_per_pass": angles["toffoli_per_pass"],
        "angles_toffoli": angles["toffoli"],
        "angles_qubits": angles["qubits"],
        "angles_selection_qubits": angles["selection_qubits"],
        "angles_persistent_qubits": angles["persistent_qubits"],
        "angles_temporary_qubits": angles["temporary_qubits"],
        **{
            name: value
            for name, value in heuristic.items()
            if name.startswith(("outer", "inner", "givens"))
        },
        "heuristic_persistent_qubits": heuristic["persistent_qubits"],
        "heuristic_temporary_qubits": heuristic["temporary_qubits"],
        "heuristic_toffoli": heuristic["toffoli"],
        "heuristic_qubits": heuristic["qubits"],
        "persistent_qubits": persistent_qubits,
        "temporary_qubits": temporary_qubits,
        "toffoli": toffoli,
        "qubits": qubits,
        "angles_within_cap": angles["qubits"] <= QUBIT_CAP,
    }


# ---------------------------------------------------------------------------
# The score
# ---------------------------------------------------------------------------


def rejection_reason(metrics: Mapping[str, Any], resources: Mapping[str, Any]) -> str | None:
    """Why ``score_from_metrics`` returns ``inf``, or ``None`` if it does not."""
    reasons = []
    if not metrics["error_1"] <= ERROR_1_THRESHOLD:
        reasons.append(
            f"error_1 = {1e3 * metrics['error_1']:.4f} mHa > {1e3 * ERROR_1_THRESHOLD:g} mHa"
        )
    if not metrics["error_2"] <= ERROR_2_THRESHOLD:
        reasons.append(
            f"error_2 = {1e3 * metrics['error_2']:.4f} mHa > {1e3 * ERROR_2_THRESHOLD:g} mHa"
        )
    if not metrics["gap_in_domain"] or not np.isfinite(metrics["lambda_eff"]):
        reasons.append("the SOS gap E_gap lies outside (0, 2 * Lambda) or its calculation is invalid")
    reasons.extend(_floor_rejection_reasons(metrics))
    if int(resources["angles_qubits"]) > QUBIT_CAP:
        reasons.append(
            f"an ANGLE_k circuit uses {resources['angles_qubits']} qubits > {QUBIT_CAP}"
        )
    return "; ".join(reasons) or None


def score_from_metrics(metrics: Mapping[str, Any], resources: Mapping[str, Any]) -> float:
    """``inf`` if rejected, else ``lambda_eff * toffoli * qubits``.

    Rejected means: an accuracy gate fails (``passes_accuracy``), or the
    ANGLES circuits use more than ``QUBIT_CAP`` qubits. ``rejection_reason``
    says why a result is ``inf``.
    """
    if not passes_accuracy(metrics) or int(resources["angles_qubits"]) > QUBIT_CAP:
        return np.inf
    return float(metrics["lambda_eff"]) * float(resources["toffoli"]) * int(resources["qubits"])


def evaluate_circuits(
    inputs: SubmissionInputs,
    circuits: Any,
    tree_edges: npt.ArrayLike,
    *,
    format: str = "auto",
    shots_per_address: int = SHOTS_PER_ADDRESS,
    seed: int | None = None,
    salt: str = "",
) -> dict[str, Any]:
    """Simulate an ANGLE_k family, evaluate the words it loads and score it.

    ``circuits`` is anything ``dfthcsos.scoreinfra.circuits.load_circuits`` accepts: a
    directory holding ``angle_k_0.kmx``, ``angle_k_1.kmx``, ... (or ``.kmb``), a
    single circuit file, or an ordered sequence of circuit paths or
    ``kickmix.Circuit`` objects. ``recover_words_from_circuits`` checks the
    register contract and recovers the words; ``brot`` and ``J`` are the width
    and the number of the ``word_j`` registers. Raises
    ``dfthcsos.scoreinfra.circuits.InvalidCircuits`` if the circuits break the contract.
    The simulator seed is ``seed``, or ``initial_seed(submission_sha256(...), salt)``.

    Returns ``angle_words``, ``brot``, ``batch_size``, ``metrics``,
    ``resources``, ``score``, ``submission_sha256`` and ``verified_shots``.
    """
    circuits = load_circuits(circuits, format=format)
    digest = submission_sha256(circuits, inputs.factorization_file or inputs.params, tree_edges)
    words, layout, toffoli = recover_words_from_circuits(
        circuits,
        num_vectors=inputs.num_vectors,
        num_angles=inputs.num_orbitals - 1,
        shots_per_address=shots_per_address,
        seed=initial_seed(digest, salt) if seed is None else seed,
    )
    brot = layout.brot
    metrics = evaluate_words(inputs, words, tree_edges, brot)
    resources = resource_costs(inputs, circuits, brot, toffoli)
    return {
        "angle_words": words,
        "brot": brot,
        "batch_size": layout.batch_size,
        "metrics": metrics,
        "resources": resources,
        "score": score_from_metrics(metrics, resources),
        "submission_sha256": digest,
        "verified_shots": inputs.num_vectors * shots_per_address,
    }


def verify(
    circuits: Any,
    factorization: str | Path | Mapping[str, npt.ArrayLike] | None = None,
    tree_edges: npt.ArrayLike | str | Path | None = None,
    *,
    format: str = "auto",
    shots_per_address: int = SHOTS_PER_ADDRESS,
    seed: int | None = None,
    salt: str = "",
) -> dict[str, Any]:
    """Verify and score a submission; return a summary dict or raise if rejected.

    Args:
        circuits: the Task 3 output: a directory with ``angle_k_*.kmx`` (or
            ``.kmb``), or the circuit files (or ``kickmix.Circuit`` objects)
            in order.
        factorization: the Task 1 output as an ``.npz`` with ``U``, ``W``,
            ``H2_I``, ``H1_I`` and ``Hsym_lower`` (or a mapping of those arrays).
            ``H1_I`` and ``Hsym_lower`` are ignored: the shift is the baseline's.
            Optional if the circuits directory has ``submission.npz``.
            Pickles are not accepted.
        tree_edges: the Task 2 Givens tree (array or ``.npy``/``.npz``).
            Optional if the circuits directory has ``submission.npz``.
        format: ``'auto'`` (default), ``'kmb'`` or ``'kmx'``.
        shots_per_address: shots simulated per address (default 64).
        seed: explicit simulator seed, overriding ``submission_sha256`` and ``salt``.
        salt: merged with ``submission_sha256`` to derive the simulator seed.

    The reference integrals are always the packaged FeMoCo76o113e FCIDUMP.

    Returns:
        A JSON-serializable dict: ``status`` (``"PASS"``), ``score``,
        ``lambda_eff``, ``toffoli_count``, ``num_qubits``, ``brot``,
        ``batch_size``, ``num_circuits``, ``reaction_depth``, ``num_ops``,
        ``verified_shots``, ``submission_sha256``, and the ``resources`` and
        ``metrics`` breakdowns.

    Raises:
        InvalidCircuits: the circuits break the register contract or do not
            load consistent words.
        AssertionError: an accuracy, gap, floor or 128-qubit gate fails.
    """
    if factorization is None:
        if not (isinstance(circuits, (str, Path)) and Path(circuits).is_dir()):
            raise ValueError(f"factorization is required unless circuits is a directory with {SUBMISSION_FILE}")
        factorization = Path(circuits) / SUBMISSION_FILE
    edges = load_tree_edges(tree_edges, circuits)
    inputs = load_inputs(factorization)
    family = load_circuits(circuits, format=format)
    result = evaluate_circuits(
        inputs, family, edges, shots_per_address=shots_per_address, seed=seed, salt=salt
    )
    reason = rejection_reason(result["metrics"], result["resources"])
    if reason is not None:
        raise AssertionError(reason)
    return {
        "status": "PASS",
        "score": float(result["score"]),
        "lambda_eff": result["metrics"]["lambda_eff"],
        "toffoli_count": result["resources"]["toffoli"],
        "num_qubits": result["resources"]["qubits"],
        "brot": result["brot"],
        "batch_size": result["batch_size"],
        "num_circuits": len(family),
        "reaction_depth": sum(c.reaction_depth() for c in family),
        "num_ops": sum(len(c) for c in family),
        "verified_shots": result["verified_shots"],
        "submission_sha256": result["submission_sha256"],
        "resources": result["resources"],
        "metrics": result["metrics"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Verify {SYSTEM} ANGLE_k kickmix circuits and print the competition score as JSON."
    )
    parser.add_argument(
        "inputs", nargs="+", type=Path,
        help="a submission directory (submission.npz and angle_k_*), or a factorization .npz "
        "followed by a directory with angle_k_*.kmb/.kmx or the circuit files in order",
    )
    parser.add_argument(
        "--tree-edges", type=Path,
        help=f".npy or .npz with the Givens tree (default: {SUBMISSION_FILE} in the directory)",
    )
    parser.add_argument("--format", choices=FORMATS, default="auto",
                        help="circuit file format (default: auto-detect .kmb or .kmx)")
    parser.add_argument("--shots-per-address", type=int, default=SHOTS_PER_ADDRESS,
                        help=f"shots simulated per address (default: {SHOTS_PER_ADDRESS})")
    parser.add_argument("--salt", type=str, default="",
                        help="optional salt merged with submission_sha256 to derive the seed (default: empty)")
    parser.add_argument("--seed", type=int, default=None,
                        help="explicit simulator seed overriding submission_sha256 and --salt")
    args = parser.parse_args()
    if len(args.inputs) == 1:
        factorization, circuits = None, args.inputs[0]
    else:
        factorization, *circuits = args.inputs
        circuits = circuits[0] if len(circuits) == 1 else circuits
    try:
        summary = verify(
            circuits, factorization, args.tree_edges, format=args.format,
            shots_per_address=args.shots_per_address, seed=args.seed, salt=args.salt,
        )
    except (AssertionError, ValueError, RuntimeError, OSError, KeyError) as ex:
        print(json.dumps({"status": "FAIL", "error": str(ex)}, indent=2))
        sys.exit(1)
    print(json.dumps(summary, indent=2))


__all__ = [
    "ERROR_1_THRESHOLD",
    "ERROR_2_THRESHOLD",
    "E_GAP_FLOOR",
    "InvalidCircuits",
    "KEEP_BITS",
    "LAMBDA_FLOOR",
    "QUBIT_CAP",
    "SUBMISSION_FILE",
    "SubmissionInputs",
    "angles_costs",
    "evaluate_circuits",
    "evaluate_words",
    "heuristic_costs",
    "load_inputs",
    "load_tree_edges",
    "main",
    "native_inputs",
    "passes_accuracy",
    "rejection_reason",
    "resource_costs",
    "score_from_metrics",
    "verify",
]


if __name__ == "__main__":
    main()

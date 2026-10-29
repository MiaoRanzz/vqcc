"""DFTHC verifier metrics in plain numpy: error_1, error_2, Lambda, E_SOS, lambda_eff.

Copied from ``dfthc/verify_dfthc.py`` and the parts of ``dfthc/verify_angle_k.py``
and ``dfthc/df_thc_sga.py`` they use, so that the verifier does not import
``dfthc`` (and through it JAX, Optax, Qualtran or OpenFermion). Function names
and signatures are kept; the three JAX kernels are rewritten in numpy:

* ``reconstruct_x``: ``df_thc_sga.Compute_H2_sqrt`` (float64 here; the
  original is float64 only while ``jax_enable_x64`` is on).
* ``lambda_h2``: ``df_thc_sga.Compute_df_thc_sga_lambda_H2``.
* ``symmetric_from_lower``: ``df_thc_sga.H1_from_lower``. It rounds to float32
  like the original; the score depends on that rounding, so keep it.

Parameters follow Qaggle Eq. (36)::

    w_b_rho_c[rho, b, c] : lowercase weights, shape (R, B, C)
    W_rho_c[rho, c]      : identity offsets, shape (R, C)
    S[p, q]              : symmetric particle-number shift, shape (N, N)
    beta_1               : scalar particle-number shift

``ref`` holds the original FCIDUMP inputs (``dfthcsos.scoreinfra.reference.load_reference``)::

    ref = {"oei": oei, "tei": tei, "electrons": num_electrons, "ecore": ecore, ...}

``oei`` has shape (N, N); ``tei`` has shape (N, N, N, N) in chemist order,
``tei[p, q, r, s] = (pq|rs)``. The one-body coefficient of ``E_pq`` is built
here::

    H1_THC[p, q] = oei[p, q] - 0.5 * sum_r tei[p, r, r, q].

The vector table has shape (N + R*B, N): N one-body rows, then the R*B
two-body rows in (rho, b) order. Each row is normalized independently. The
integer table has shape (N + R*B, N - 1): raw angle words, ``theta / pi`` with
one integer bit and ``brot - 1`` fractional bits.

Both entry points return error_1, error_2, Lambda, E_SOS, E_gap, lambda_eff
and gap_in_domain. Outside ``0 < E_gap < 2 * Lambda`` the errors are kept
but ``lambda_eff`` is NaN.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext
import math
from operator import index
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import linear_sum_assignment

FloatArray = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------
# Kernels (numpy versions of dfthc.df_thc_sga)
# ---------------------------------------------------------------------------


def symmetric_from_lower(lower: npt.ArrayLike, num_orbitals: int) -> npt.NDArray[np.float32]:
    """Symmetric ``(N, N)`` matrix from its row-major packed lower triangle.

    Same as ``df_thc_sga.H1_from_lower``, including its float32 rounding.
    """
    n = int(num_orbitals)
    lower = np.asarray(lower)
    if lower.shape != (n * (n + 1) // 2,):
        raise ValueError(f"packed lower triangle must have shape ({n * (n + 1) // 2},)")
    matrix = np.zeros((n, n), dtype=np.float32)
    rows, cols = np.tril_indices(n)
    matrix[rows, cols] = lower.astype(np.float32)
    return matrix + matrix.T - np.diag(np.diag(matrix))


def reconstruct_x(u_b_rho: npt.ArrayLike, w_b_rho_c: npt.ArrayLike) -> FloatArray:
    """``X^(rho c) = sum_b w_b^(rho c) u_b^(rho) u_b^(rho)^T``, shape (R, C, N, N).

    The ``u_b^(rho)`` rows are normalized first, as in
    ``df_thc_sga.Compute_H2_sqrt``.
    """
    u = np.asarray(u_b_rho, dtype=np.float64)
    w = np.asarray(w_b_rho_c, dtype=np.float64)
    u = u / np.linalg.norm(u, ord=2, axis=2)[:, :, None]
    return np.einsum("tjp,tjq,tjl->tlpq", u, u, w, optimize=True)


def lambda_h2(w_b_rho_c: npt.ArrayLike, W_rho_c: npt.ArrayLike) -> float:
    """Two-body LCU one-norm ``1/4 sum_(rho c) (|w_B| + sum_b |w_b|)**2``.

    ``w_B^(rho c) = W^(rho c) + sum_b w_b^(rho c)``
    (``df_thc_sga.Compute_df_thc_sga_lambda_H2``).
    """
    w = np.asarray(w_b_rho_c, dtype=np.float64)
    w_B = np.asarray(W_rho_c, dtype=np.float64) + np.sum(w, axis=1)
    return float(0.25 * np.sum(np.square(np.linalg.norm(w, ord=1, axis=1) + np.abs(w_B))))


# ---------------------------------------------------------------------------
# Vectors, X and h1_prime (from dfthc.verify_angle_k)
# ---------------------------------------------------------------------------


def reconstruct_u_vectors(
    theta_over_pi: npt.ArrayLike,
    tree_edges: npt.ArrayLike,
) -> FloatArray:
    """Apply the ordered Givens-tree rotations to e_0 for every vector."""
    angles = np.asarray(theta_over_pi, dtype=np.float64)
    edges = np.asarray(tree_edges, dtype=np.int64)
    num_vectors, num_angles = angles.shape
    if edges.shape != (num_angles, 2):
        raise ValueError("tree_edges must have shape (N - 1, 2)")

    vectors = np.zeros((num_vectors, num_angles + 1), dtype=np.float64)
    vectors[:, 0] = 1.0
    for angle_index, (parent, child) in enumerate(edges):
        parent_value = vectors[:, parent].copy()
        child_value = vectors[:, child].copy()
        theta = np.pi * angles[:, angle_index]
        cosine = np.cos(theta)
        sine = np.sin(theta)
        vectors[:, parent] = cosine * parent_value - sine * child_value
        vectors[:, child] = sine * parent_value + cosine * child_value
    return vectors


def split_u_vectors(
    u_all: npt.ArrayLike,
    w_b_rho_c: npt.ArrayLike,
) -> tuple[FloatArray, FloatArray]:
    """Split the N one-body rows from the following R*B two-body rows."""
    vectors = np.asarray(u_all, dtype=np.float64)
    w_b_rho_c = np.asarray(w_b_rho_c, dtype=np.float64)
    num_vectors, num_orbitals = vectors.shape
    rank_r, bases_b, _ = w_b_rho_c.shape
    expected_num_vectors = num_orbitals + rank_r * bases_b
    if num_vectors != expected_num_vectors:
        raise ValueError(
            f"expected A=N+R*B={expected_num_vectors} vectors, got A={num_vectors}"
        )
    return (
        vectors[:num_orbitals],
        vectors[num_orbitals:].reshape(rank_r, bases_b, num_orbitals),
    )


def build_h1_prime(
    h1_thc: npt.ArrayLike,
    S: npt.ArrayLike,
    beta_1: float,
    num_electrons: int,
    W_rho_c: npt.ArrayLike,
    X_rho_c: npt.ArrayLike,
) -> FloatArray:
    """``h1_prime = H1_THC - (eta/2) S + beta_1 I - sum_(rho c) W X`` (Eq. (38))."""
    h1_thc = np.asarray(h1_thc, dtype=np.float64)
    return (
        h1_thc
        - 0.5 * num_electrons * np.asarray(S, dtype=np.float64)
        + beta_1 * np.eye(h1_thc.shape[0])
        - np.einsum("rc,rcpq->pq", W_rho_c, X_rho_c, optimize=True)
    )


def reconstruct_h1_thc(
    qrom_h1_prime_eigenvectors: npt.ArrayLike,
    h1_thc: npt.ArrayLike,
    S: npt.ArrayLike,
    beta_1: float,
    num_electrons: int,
    W_rho_c: npt.ArrayLike,
    X_rho_c: npt.ArrayLike,
) -> FloatArray:
    """H1_THC rebuilt from the submitted one-body rows and the exact eigenvalues.

    The rows may be permuted or sign-flipped: each is paired with an exact
    eigenvector of ``h1_prime`` by a one-to-one assignment on ``|overlap|``
    and gets that eigenvector's eigenvalue.
    """
    qrom_eigenvectors = np.asarray(qrom_h1_prime_eigenvectors, dtype=np.float64)
    ideal_h1_prime = build_h1_prime(h1_thc, S, beta_1, num_electrons, W_rho_c, X_rho_c)
    ideal_eigenvalues, ideal_eigenvector_columns = np.linalg.eigh(ideal_h1_prime)

    overlaps = np.abs(qrom_eigenvectors @ ideal_eigenvector_columns)
    qrom_indices, ideal_indices = linear_sum_assignment(-overlaps)
    matched_eigenvalues = np.empty_like(ideal_eigenvalues)
    matched_eigenvalues[qrom_indices] = ideal_eigenvalues[ideal_indices]

    h1_prime_qrom = np.einsum(
        "j,jp,jq->pq",
        matched_eigenvalues,
        qrom_eigenvectors,
        qrom_eigenvectors,
        optimize=True,
    )

    # Invert h1_prime = H1_THC - eta*S/2 + beta_1*I - sum_(rho,c) W*X.
    return (
        h1_prime_qrom
        + 0.5 * num_electrons * np.asarray(S, dtype=np.float64)
        - beta_1 * np.eye(ideal_h1_prime.shape[0])
        + np.einsum("rc,rcpq->pq", W_rho_c, X_rho_c, optimize=True)
    )


def h1_thc_reconstruction_error(
    qrom_h1_prime_eigenvectors: npt.ArrayLike,
    h1_thc: npt.ArrayLike,
    S: npt.ArrayLike,
    beta_1: float,
    num_electrons: int,
    W_rho_c: npt.ArrayLike,
    X_rho_c: npt.ArrayLike,
) -> float:
    """``error_1 = ||H1_THC(submitted) - H1_THC||_F``."""
    reconstructed = reconstruct_h1_thc(
        qrom_h1_prime_eigenvectors, h1_thc, S, beta_1, num_electrons, W_rho_c, X_rho_c
    )
    return float(np.linalg.norm(reconstructed - np.asarray(h1_thc)))


def reconstruct_h2(X_rho_c: npt.ArrayLike) -> FloatArray:
    """The Gram tensor ``sum_(rho c) X (x) X``, before the S shift is undone."""
    factors = np.asarray(X_rho_c, dtype=np.float64)
    return np.einsum("rcpq,rcst->pqst", factors, factors, optimize=True)


# ---------------------------------------------------------------------------
# Evaluation (from dfthc.verify_dfthc)
# ---------------------------------------------------------------------------


def _exact_lambda_eff(
    eigenvalues: np.ndarray,
    w_b_rho_c: np.ndarray,
    W_rho_c: np.ndarray,
    beta_1: float,
    ecore: float,
    electrons: int,
    energy_upper: float,
) -> float | None:
    """High-precision ``Decimal`` check for ``lambda_eff`` to detect cancellation."""
    dec = Decimal.from_float
    rank_r, _, copies_c = w_b_rho_c.shape
    with localcontext() as ctx:
        ctx.prec = 100
        lam_h1 = sum((abs(dec(float(ev))) for ev in eigenvalues), Decimal(0))
        tr_h1 = sum((dec(float(ev)) for ev in eigenvalues), Decimal(0))
        lam_h2 = Decimal("0.25") * sum(
            (
                (
                    sum((abs(dec(float(x))) for x in w_b_rho_c[r, :, c]), Decimal(0))
                    + abs(
                        dec(float(W_rho_c[r, c]))
                        + sum((dec(float(x)) for x in w_b_rho_c[r, :, c]), Decimal(0))
                    )
                )
                ** 2
                for r in range(rank_r)
                for c in range(copies_c)
            ),
            Decimal(0),
        )
        Lambda_d = lam_h1 + lam_h2
        w2_sum = sum((dec(float(x)) ** 2 for x in W_rho_c.ravel()), Decimal(0))
        e_sos = (
            dec(float(ecore))
            - Decimal(int(electrons)) * dec(float(beta_1))
            - (lam_h1 - tr_h1)
            - Decimal("0.5") * w2_sum
        )
        e_gap = dec(float(energy_upper)) - e_sos
        rad = e_gap * (Decimal(2) * Lambda_d - e_gap)
        if e_gap <= 0 or rad <= 0:
            return None
        return float(rad.sqrt())


def evaluate_dfthc_vectors(
    u_all: npt.ArrayLike,
    w_b_rho_c: npt.ArrayLike,
    W_rho_c: npt.ArrayLike,
    S: npt.ArrayLike,
    beta_1: float,
    ref: Mapping[str, Any],
    *,
    energy_upper: float,
) -> dict[str, float | bool]:
    """Evaluate all N+RB submitted vector rows, without angle quantization.

    Eigenvalues are derived from the target h1_prime and matched internally
    to the submitted one-body rows.
    """
    vectors = np.asarray(u_all, dtype=np.float64)
    w_b_rho_c = np.asarray(w_b_rho_c, dtype=np.float64)
    W_rho_c = np.asarray(W_rho_c, dtype=np.float64)
    S = np.asarray(S, dtype=np.float64)
    oei = np.asarray(ref["oei"], dtype=np.float64)
    tei = np.asarray(ref["tei"], dtype=np.float64)
    if oei.ndim != 2 or oei.shape[0] != oei.shape[1]:
        raise ValueError("ref['oei'] must have shape (N, N)")
    num_orbitals = oei.shape[0]
    if tei.shape != (num_orbitals,) * 4:
        raise ValueError("ref['tei'] must have shape (N, N, N, N) in chemist order")
    if w_b_rho_c.ndim != 3 or min(w_b_rho_c.shape) < 1:
        raise ValueError("w_b_rho_c must have shape (R, B, C) with positive sizes")
    rank_r, bases_b, copies_c = w_b_rho_c.shape
    if vectors.shape != (num_orbitals + rank_r * bases_b, num_orbitals):
        raise ValueError("u_all must have shape (N + R*B, N)")
    if W_rho_c.shape != (rank_r, copies_c):
        raise ValueError("W_rho_c must have shape (R, C)")
    if S.shape != (num_orbitals, num_orbitals) or not np.allclose(S, S.T):
        raise ValueError("S must be a symmetric (N, N) matrix")
    if not all(np.all(np.isfinite(a)) for a in (vectors, w_b_rho_c, W_rho_c, S)):
        raise ValueError("vectors, w, W, and S must contain finite values")
    if not np.isfinite(beta_1) or not np.isfinite(energy_upper):
        raise ValueError("beta_1 and energy_upper must be finite scalars")
    row_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(row_norms == 0.0) or not np.all(np.isfinite(row_norms)):
        raise ValueError("submitted vector rows must have finite, nonzero norms")
    one_body_vectors, u_b_rho = split_u_vectors(vectors / row_norms, w_b_rho_c)

    X_rho_c = reconstruct_x(u_b_rho, w_b_rho_c)
    # Symmetrize from the lower triangle, and use this same X in the target and
    # both error checks.
    X_rho_c = np.tril(X_rho_c) + np.swapaxes(np.tril(X_rho_c, k=-1), -1, -2)
    # Converting the raw FCIDUMP Hamiltonian to E_pq E_rs contributes this
    # one-body contraction of the original, unshifted chemist ERIs.
    h1_thc = oei - 0.5 * np.einsum("prrq->pq", tei)
    h1_prime = build_h1_prime(h1_thc, S, beta_1, ref["electrons"], W_rho_c, X_rho_c)
    eigenvalues = np.linalg.eigvalsh(h1_prime)
    error_1 = h1_thc_reconstruction_error(
        one_body_vectors, h1_thc, S, beta_1, ref["electrons"], W_rho_c, X_rho_c
    )
    # error_2 = ||sum_rc X_rc tensor X_rc - (S tensor I + I tensor S)/2 - tei||_F.
    # Subtract the identity terms on their diagonal pairs without allocating
    # additional N^4 symmetry-shift tensors or modifying the input integrals.
    h2_delta = reconstruct_h2(X_rho_c)
    h2_delta -= tei
    diagonal = np.arange(num_orbitals)
    h2_delta[:, :, diagonal, diagonal] -= 0.5 * S[:, :, None]
    h2_delta[diagonal, diagonal, :, :] -= 0.5 * S[None, :, :]
    error_2 = float(np.linalg.norm(h2_delta.ravel()))

    # Qaggle Eq. (42): retain the signed generator weights even when the
    # submitted one-body rows are not orthogonal after finite-bit encoding.
    lambda_h1 = float(np.sum(np.abs(eigenvalues)))
    Lambda = lambda_h1 + lambda_h2(w_b_rho_c, W_rho_c)

    # Eq. (43): every submitted vector has unit norm, so Tr(h1_prime_decoded)
    # equals sum_j lambda_j even if the vectors are not mutually orthogonal.
    E_SOS = float(
        ref["ecore"]
        - ref["electrons"] * beta_1
        - (lambda_h1 - np.sum(eigenvalues))
        - 0.5 * np.sum(W_rho_c**2)
    )
    E_gap = float(energy_upper - E_SOS)
    gap_in_domain = 0.0 < E_gap <= 2.0 * Lambda
    lambda_eff = (
        float(np.sqrt(E_gap * (2.0 * Lambda - E_gap)))
        if gap_in_domain else float("nan")
    )
    if gap_in_domain:
        exact_lambda_eff = _exact_lambda_eff(
            eigenvalues, w_b_rho_c, W_rho_c, beta_1, ref["ecore"], ref["electrons"], energy_upper
        )
        if exact_lambda_eff is None or not math.isclose(
            lambda_eff, exact_lambda_eff, rel_tol=1e-6
        ):
            gap_in_domain = False
            lambda_eff = float("nan")
    return {
        "error_1": error_1,
        "error_2": error_2,
        "Lambda": Lambda,
        "E_SOS": E_SOS,
        "E_gap": E_gap,
        "lambda_eff": lambda_eff,
        "gap_in_domain": gap_in_domain,
    }


def evaluate_dfthc_angle_words(
    angle_words: npt.ArrayLike,
    w_b_rho_c: npt.ArrayLike,
    W_rho_c: npt.ArrayLike,
    S: npt.ArrayLike,
    beta_1: float,
    ref: Mapping[str, Any],
    *,
    brot: int,
    tree_edges: npt.ArrayLike,
    energy_upper: float,
) -> dict[str, float | bool]:
    """Decode recovered integer words on ``tree_edges`` and evaluate the vectors.

    ``angle_words`` has N+RB rows and N-1 columns; simulation and rounding
    happen before this call.
    """
    words = np.asarray(angle_words)
    oei = np.asarray(ref["oei"])
    if oei.ndim != 2 or oei.shape[0] != oei.shape[1]:
        raise ValueError("ref['oei'] must have shape (N, N)")
    num_orbitals = oei.shape[0]
    try:
        brot = index(brot)
    except TypeError as exc:
        raise ValueError("brot must be an integer between 1 and 63") from exc
    if not 1 <= brot <= 63:
        raise ValueError("brot must be an integer between 1 and 63")
    if words.ndim != 2 or words.shape[1] != num_orbitals - 1:
        raise ValueError("angle_words must have shape (N + R*B, N - 1)")
    if not np.issubdtype(words.dtype, np.integer):
        raise ValueError("angle_words must contain integers")
    if np.any(words < 0) or np.any(words >= 1 << brot):
        raise ValueError("angle_words must lie in [0, 2**brot)")
    edges = np.asarray(tree_edges)
    if edges.shape != (num_orbitals - 1, 2) or not np.issubdtype(edges.dtype, np.integer):
        raise ValueError("tree_edges must contain N-1 ordered integer vertex pairs")
    if np.any(edges < 0) or np.any(edges >= num_orbitals):
        raise ValueError("tree_edges vertices must lie in [0, N)")
    visited = {0}
    for parent, child in edges:
        if parent not in visited or child in visited:
            raise ValueError("tree_edges must form a tree rooted at 0 in parent-before-child order")
        visited.add(child)

    u_all = reconstruct_u_vectors(words / (1 << (brot - 1)), edges)
    return evaluate_dfthc_vectors(
        u_all, w_b_rho_c, W_rho_c, S, beta_1, ref, energy_upper=energy_upper
    )


__all__ = [
    "build_h1_prime",
    "evaluate_dfthc_angle_words",
    "evaluate_dfthc_vectors",
    "h1_thc_reconstruction_error",
    "lambda_h2",
    "reconstruct_h1_thc",
    "reconstruct_h2",
    "reconstruct_u_vectors",
    "reconstruct_x",
    "split_u_vectors",
    "symmetric_from_lower",
]

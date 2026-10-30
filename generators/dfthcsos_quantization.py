"""Deterministic tree encoding, with one-body refitting after quantization.

Independently derived inverse Givens elimination. Numerical chemistry interfaces
are the unchanged official Apache-2.0 verifier. No randomized rounding/search.
"""
from __future__ import annotations
import numpy as np
from dfthcsos.scoreinfra.dfthc_math import (
    reconstruct_u_vectors, reconstruct_x, build_h1_prime,
)


def encode_vectors(vectors, tree_edges, brot):
    """Encode normalized real rows on a parent-before-child spanning tree."""
    v = np.array(vectors, dtype=np.float64, copy=True)
    edges = np.asarray(tree_edges)
    if v.ndim != 2 or edges.shape != (v.shape[1] - 1, 2):
        raise ValueError('vector/tree shapes disagree')
    if not np.issubdtype(edges.dtype, np.integer) or not 1 <= brot <= 30:
        raise ValueError('invalid tree dtype or precision')
    seen = {0}
    for p, c in edges:
        if p not in seen or c in seen or not 0 <= c < v.shape[1]:
            raise ValueError('expected a parent-before-child spanning tree rooted at zero')
        seen.add(int(c))
    norms = np.linalg.norm(v, axis=1)
    if not np.isfinite(v).all() or np.any(norms == 0):
        raise ValueError('expected finite nonzero vectors')
    v /= norms[:, None]
    angles = np.empty((len(v), len(edges)))
    for i in range(len(edges) - 1, -1, -1):
        p, c = edges[i]
        angles[:, i] = np.arctan2(v[:, c], v[:, p])
        v[:, p] = np.hypot(v[:, p], v[:, c])
        v[:, c] = 0
    return np.rint(angles * ((1 << brot) / (2 * np.pi))).astype(np.int64) % (1 << brot)


def reencode_words(inputs, tree_edges, brot):
    """Quantize source U, then fit one-body eigenvectors to that decoded U."""
    u = np.asarray(inputs.params['U'], dtype=np.float64)
    two_words = encode_vectors(u.reshape(-1, inputs.num_orbitals), tree_edges, brot)
    decoded = reconstruct_u_vectors(two_words / (1 << (brot - 1)), tree_edges).reshape(u.shape)
    decoded /= np.linalg.norm(decoded, axis=-1, keepdims=True)
    x = reconstruct_x(decoded, inputs.w)
    x = np.tril(x) + np.swapaxes(np.tril(x, k=-1), -1, -2)
    h1 = build_h1_prime(inputs.ref['h1_thc'], inputs.S, inputs.beta_1,
                        inputs.ref['electrons'], inputs.W, x)
    _, eigenvectors = np.linalg.eigh(h1)
    one_words = encode_vectors(eigenvectors.T, tree_edges, brot)
    return np.concatenate((one_words, two_words))

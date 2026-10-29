"""QROM with prefix recomputation to reduce peak clean workspace.

Compute a high-address prefix into one flag, uncompute its intermediate ANDs,
and let the lower tree reuse those clean wires. Recompute the intermediates
to clear the flag after the subtree. Word loads remain XOR oracles.

Independently written scheduling; batch_deltas and register names come from
the unchanged Apache-2.0 official reference (verifiers/LICENSE.txt).
"""
from __future__ import annotations

from operator import index
import kickmix as km
import numpy as np

from dfthcsos.example_submission.angle_k_reference_circuit import batch_deltas
from dfthcsos.scoreinfra.circuits import SELECTION_REGISTER, word_register


def workspace_bits(address_bits: int, prefix_bits: int) -> int:
    if not 2 <= prefix_bits <= address_bits:
        raise ValueError("prefix_bits must be between 2 and the address width")
    return 1 + max(prefix_bits - 2, address_bits - prefix_bits)


def build_prefix_circuit(delta, brot: int, prefix_bits: int) -> km.Circuit:
    delta = np.asarray(delta)
    brot, prefix_bits = index(brot), index(prefix_bits)
    if delta.ndim != 2 or delta.shape[0] < 2 or not np.issubdtype(delta.dtype, np.integer):
        raise ValueError("delta must be a two-dimensional integer table with >=2 rows")
    if not 1 <= brot <= 30 or np.any(delta < 0) or np.any(delta >= 1 << brot):
        raise ValueError("word precision/range invalid")
    rows, batch_size = delta.shape
    n = (rows - 1).bit_length()
    work_count = workspace_bits(n, prefix_bits)
    builder = km.CircuitBuilder()
    selection = builder.create_quantum_register(n, SELECTION_REGISTER)
    words = [builder.create_quantum_register(brot, word_register(j)) for j in range(batch_size)]
    work = builder.alloc_qubits(work_count)
    flag, temp = work[-1], work[:-1]
    bits = list(reversed(selection))
    high, low = bits[:prefix_bits], bits[prefix_bits:]

    def load(row, control):
        for j in range(batch_size):
            for bit in range(brot):
                if (int(delta[row, j]) >> bit) & 1:
                    builder.cx(control, words[j][bit])

    def intermediate(inverse):
        steps = range(prefix_bits - 2)
        for i in reversed(steps) if inverse else steps:
            a, b = (high[0], high[1]) if i == 0 else (temp[i - 1], high[i + 1])
            if inverse:
                builder.del_and(a, b, temp[i])
            else:
                builder.init_and(a, b, temp[i])

    def node(control, level, lo, hi):
        if lo >= rows:
            return
        if hi <= rows and (hi - lo == 1 or np.all(delta[lo:hi] == delta[lo])):
            load(lo, control)
            return
        mid = (lo + hi) // 2
        if rows <= mid:
            node(control, level + 1, lo, mid)
            return
        bit, ancilla = low[level], temp[level]
        builder.x(bit)
        builder.init_and(control, bit, ancilla)
        builder.x(bit)
        node(ancilla, level + 1, lo, mid)
        builder.cx(control, ancilla)
        node(ancilla, level + 1, mid, hi)
        builder.del_and(control, bit, ancilla)

    block = 1 << len(low)
    for prefix in range((rows + block - 1) // block):
        zeros = [q for i, q in enumerate(high) if not ((prefix >> (prefix_bits - i - 1)) & 1)]
        for q in zeros:
            builder.x(q)
        intermediate(False)
        a, b = (high[0], high[1]) if prefix_bits == 2 else (temp[prefix_bits - 3], high[-1])
        builder.init_and(a, b, flag)
        intermediate(True)
        node(flag, 0, prefix * block, (prefix + 1) * block)
        intermediate(False)
        builder.del_and(a, b, flag)
        intermediate(True)
        for q in zeros:
            builder.x(q)
    builder.free(work)
    return builder.finish_circuit()


def build_prefix_family(words, brot: int, batch_size: int, prefix_bits: int):
    return tuple(build_prefix_circuit(delta, brot, prefix_bits)
                 for delta in batch_deltas(words, batch_size))

"""Exact XOR lookup via algebraic normal form and recomputed monomials.

Independent derivation; Apache-2.0 official batch_deltas and register names.
F(a) = XOR_{s subset a} coefficient[s]. For legal a < rows, every s <= a,
so coefficients >= rows can be omitted exactly. No sampled assumptions.
High-address monomials share recomputed scratch with low-address monomials.
"""
from __future__ import annotations
from operator import index
import kickmix as km
import numpy as np
from dfthcsos.example_submission.angle_k_reference_circuit import batch_deltas
from dfthcsos.scoreinfra.circuits import SELECTION_REGISTER, word_register
from dfthcsos_prefix import workspace_bits


def anf_coefficients(delta):
    delta = np.asarray(delta)
    if delta.ndim != 2 or delta.shape[0] < 2 or not np.issubdtype(delta.dtype, np.integer):
        raise ValueError("delta must be a two-dimensional integer table with >=2 rows")
    rows, width = delta.shape
    n = (rows - 1).bit_length()
    coefficients = np.zeros((1 << n, width), dtype=np.int64)
    coefficients[:rows] = delta
    for bit in range(n):
        stride = 1 << bit
        blocks = coefficients.reshape(-1, 2 * stride, width)
        blocks[:, stride:] ^= blocks[:, :stride]
    coefficients[rows:] = 0
    return coefficients


def build_anf_circuit(delta, brot: int, prefix_bits: int) -> km.Circuit:
    brot, prefix_bits = index(brot), index(prefix_bits)
    delta = np.asarray(delta)
    coefficients = anf_coefficients(delta)
    if not 1 <= brot <= 30 or np.any(delta < 0) or np.any(delta >= 1 << brot):
        raise ValueError("word precision/range invalid")
    rows, batch_size = delta.shape
    n = (rows - 1).bit_length()
    work_count = workspace_bits(n, prefix_bits)
    low_bits = n - prefix_bits
    builder = km.CircuitBuilder()
    selection = builder.create_quantum_register(n, SELECTION_REGISTER)
    words = [builder.create_quantum_register(brot, word_register(j)) for j in range(batch_size)]
    work = builder.alloc_qubits(work_count)
    flag, temp = work[-1], work[:-1]

    def load(values, control):
        for j, value in enumerate(values):
            for bit in range(brot):
                if (int(value) >> bit) & 1:
                    if control is None:
                        builder.x(words[j][bit])
                    else:
                        builder.cx(control, words[j][bit])

    for high_mask in range(1 << prefix_bits):
        table = coefficients[high_mask << low_bits:(high_mask + 1) << low_bits]
        active = np.any(table != 0, axis=1)
        if not active.any():
            continue
        # Trie ancestors: add low-address bits in ascending order.
        needed = active.copy()
        for mask in range(len(needed) - 1, 0, -1):
            if needed[mask]:
                needed[mask ^ (1 << (mask.bit_length() - 1))] = True
        high = [selection[low_bits + bit] for bit in range(prefix_bits)
                if (high_mask >> bit) & 1]

        def intermediates(inverse):
            steps = range(len(high) - 2)
            for i in reversed(steps) if inverse else steps:
                a, b = (high[0], high[1]) if i == 0 else (temp[i - 1], high[i + 1])
                if inverse:
                    builder.del_and(a, b, temp[i])
                else:
                    builder.init_and(a, b, temp[i])

        if len(high) >= 2:
            intermediates(False)
            a, b = (high[0], high[1]) if len(high) == 2 else (temp[len(high) - 3], high[-1])
            builder.init_and(a, b, flag)
            intermediates(True)
            control = flag
        else:
            control = high[0] if high else None

        def visit(mask, parent, start_bit, depth):
            if active[mask]:
                load(table[mask], parent)
            for bit in range(start_bit, low_bits):
                child = mask | (1 << bit)
                if not needed[child]:
                    continue
                if parent is None:
                    visit(child, selection[bit], bit + 1, depth)
                else:
                    target = temp[depth]
                    builder.init_and(parent, selection[bit], target)
                    visit(child, target, bit + 1, depth + 1)
                    builder.del_and(parent, selection[bit], target)

        visit(0, control, 0, 0)
        if len(high) >= 2:
            intermediates(False)
            builder.del_and(a, b, flag)
            intermediates(True)
    builder.free(work)
    return builder.finish_circuit()


def build_anf_family(words, brot: int, batch_size: int, prefix_bits: int):
    return tuple(build_anf_circuit(delta, brot, prefix_bits)
                 for delta in batch_deltas(words, batch_size))

"""Independent integer coefficient tuning around the Apache-2.0 reference model.

Only table loading changes: the reference model and circuit consume the same
immutable table. No verifier or reference module globals are modified.
"""
from __future__ import annotations

import numpy as np
from invsqrt.nr_reference_circuit import Precision


class TablePrecision(Precision):
    def __init__(self, *, coefficient_table, **widths):
        super().__init__(**widths)
        if len(coefficient_table) != 4 or any(len(row) != 4 for row in coefficient_table):
            raise ValueError("coefficient_table must be four rows of four integers")
        if any(type(v) is not int or not 0 <= v < 2**self.coef_bits
               for row in coefficient_table for v in row):
            raise ValueError("coefficients must be integers fitting coef_bits")
        object.__setattr__(self, "_table", tuple(tuple(row) for row in coefficient_table))

    def coefficient_table(self):
        return [list(row) for row in self._table]


def initial_guess(prec, case, normalized):
    """Exact Horner value on already-normalized 22-bit integers, for screening."""
    c0, c1, c2, c3 = prec.coefficient_table()[case]
    x = np.asarray(normalized, dtype=np.int64)
    delta = [((x >> 21) & (x >> 19) & 1, 1)]
    delta += [((x >> (20 - m)) & 1, m) for m in range(2, prec.delta_bits + 1)]
    value = np.full_like(x, c3)
    for coefficient in (c2, c1, c0):
        product = sum(control * (value >> m) for control, m in delta)
        value = coefficient - product
        if np.any(value <= 0) or np.any(value >= 2**prec.coef_bits):
            raise OverflowError("Horner intermediate outside reference bounds")
    return value


def segment_endpoints(delta_bits, case):
    """Both ends of every constant-Horner cell, including all four intervals.

    This is a superset of normalized legal inputs. Initial relative error is
    monotone within each cell. It does not bound final Newton truncation error.
    """
    bounds = [1 << 20, 3 << 19, 2 << 20, 3 << 20, 4 << 20]
    step = 1 << (20 - delta_bits)
    starts = np.arange(bounds[case], bounds[case + 1], step, dtype=np.int64)
    return np.sort(np.concatenate((starts, starts + step - 1)))


def tune_table(delta_bits, coef_bits):
    """Bounded deterministic integer coordinate descent; no random seed search."""
    widths = dict(delta_bits=delta_bits, coef_bits=coef_bits)
    table = Precision(**widths).coefficient_table()
    history = []
    for case in range(4):
        xs = segment_endpoints(delta_bits, case)
        roots = np.sqrt(xs / 2.0**20) / 2.0**coef_bits

        def objective(row):
            trial = [list(r) for r in table]
            trial[case] = row
            try:
                guess = initial_guess(TablePrecision(coefficient_table=trial, **widths), case, xs)
            except (ValueError, OverflowError):
                return float("inf")
            return float(np.max(np.abs(guess * roots - 1)))

        row = list(table[case])
        before = score = objective(row)
        evaluations = 1
        for step in (32, 16, 8, 4, 2, 1):
            for sweep in range(12):
                changed = False
                for j in range(4):
                    options = []
                    for sign in (-1, 1):
                        trial = list(row)
                        trial[j] += sign * step
                        options.append((objective(trial), trial))
                        evaluations += 1
                    best, trial = min(options, key=lambda item: item[0])
                    if best < score:
                        score, row, changed = best, trial, True
                if not changed:
                    break
        table[case] = row
        history.append(dict(case=case, endpoints=len(xs), before=before, after=score,
                            evaluations=evaluations, coefficients=row))
    return table, history

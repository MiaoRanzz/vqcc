"""Verifier for Benchmark II: DQI Reed-Solomon MBUC syndrome decoder (arXiv:2408.08292, arXiv:2510.10967).

For parameters `(m, n, b)` (`m` codeword positions, `n` syndromes correcting up to
`l = n // 2` errors over `GF(2^b)` using `km.GF2Field(b)` with primitive element
`alpha = km.GF2Field(b).primitive_element`):

Registers (little-endian, width `b`, pairwise disjoint, no other registers allowed):
    S0..S{n-1}  Quantum syndrome registers (`km.q`). Hold `S_i = sum_j e_j alpha^{(i+1) j}`.
    E0..E{m-1}  Classical MBUC outcome registers (`km.b`). Hold `M_0..M_{m-1}` on input.

Contract: on each shot, `S0..S{n-1}` must be restored, all other qubits must return to |0>,
and the global phase must be multiplied by `(-1) ** sum_j popcount(e_j & M_j)`. `Z_POW` gates
are not allowed. With `k = value_errors + phase_errors` failed shots out of `N = num_shots`,
the one-sided Clopper-Pearson upper bound `eps_plus` at confidence `1 - 2^log2_delta`
(default `log2_delta = -128`, i.e. `delta = 2^{-128}`) must satisfy `eps_plus < 1/16`,
and the score is `R(eps_plus) * Q^2 * T` where `R(eps) = ln(2) / -ln(1/2 + 2 * sqrt(eps))`.

Test distribution: each shot draws error weight `k in {0, ..., l}` with probability `w_k^2`,
where `w` is the principal eigenvector of the `(l + 1) x (l + 1)` DQI matrix `A` with
`A[k, k] = k (q - 2r) / sqrt(r (q - r))` and `A[k - 1, k] = sqrt(k (m - k + 1))` for `q = 2^b`
and `r = |F_i|` (`default_num_accepted_values(b)`), then picks `k` uniform positions in `0..m-1`
with uniform nonzero values in `GF(2^b)` and uniform independent `M_j in GF(2^b)`.

Shots are drawn `batch_size` at a time from `numpy.random.default_rng(seed)`, where `seed` is
derived from the SHA-256 of the circuit's `.kmb` binary representation (merged with `--salt` when
given) unless `--seed` is passed. The same `seed` also seeds `HMR` and `R` outcomes in
`km.Simulator`, so verification and per-shot operation counts (`T` = mean Toffoli-like gates per
shot) are deterministic. `num_shots` must be a multiple of `batch_size`.

Usage:
    python dqi/verify_submission_dqi.py submission.kmb [--m 4095] [--n 70] [--degree 12] [--r 2016] [--log2-delta -128] [--salt STR]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
import sys
from typing import Any, Sequence

import numpy as np

import kickmix as km

DEFAULT_M = 4095
DEFAULT_N = 70
DEFAULT_DEGREE = 12
DEFAULT_R = 2016  # Bent-function support size (2^12 - 2^6) // 2 for degree=12.
DEFAULT_NUM_SHOTS = 400 * 256  # 102,400 shots.
DEFAULT_BATCH_SIZE = 256
DEFAULT_LOG2_DELTA = -128.0  # log2(delta) for Clopper-Pearson confidence 1 - 2^log2_delta.
DEFAULT_MAX_WORKERS = 4


# Problem specification.


@dataclasses.dataclass(frozen=True)
class ProblemSpecDQI:
    """Specification of the Benchmark II problem instance."""
    m: int
    n: int
    degree: int
    r: int
    num_shots: int

    @property
    def max_errors(self) -> int:
        """Maximum number of correctable errors `l = n // 2`."""
        return self.n // 2

    @property
    def q(self) -> int:
        """Field size `q = 2^degree`."""
        return 1 << self.degree

    @classmethod
    def benchmark_instance(
        cls,
        *,
        m: int = DEFAULT_M,
        n: int = DEFAULT_N,
        degree: int = DEFAULT_DEGREE,
        r: int | None = None,
        num_shots: int = DEFAULT_NUM_SHOTS,
    ) -> ProblemSpecDQI:
        """Returns the default competition benchmark instance."""
        return cls(
            m=m,
            n=n,
            degree=degree,
            r=default_num_accepted_values(degree) if r is None else r,
            num_shots=num_shots,
        )


# Field and distribution helpers.


class FieldTables:
    """Precomputed log and antilog tables over `GF(2^b)`."""

    def __init__(self, field: km.GF2Field):
        self.degree = field.degree
        self.order = (1 << self.degree) - 1
        primitive = field.primitive_element
        self.antilog = np.array([field.pow(primitive, k) for k in range(self.order)], dtype=np.int64)
        if len(set(self.antilog.tolist())) != self.order:
            raise ValueError(
                f'Element {primitive} is not primitive in GF(2^{self.degree}) '
                f'(generated {len(set(self.antilog.tolist()))} of {self.order} nonzero elements).'
            )
        self.log = np.zeros(1 << self.degree, dtype=np.int64)
        self.log[self.antilog] = np.arange(self.order)


def default_num_accepted_values(degree: int) -> int:
    """Default `r = |F_i| = (2^b - isqrt(2^b)) // 2` (bent-function support size, 2016 for b=12)."""
    q = 1 << degree
    return max(1, (q - math.isqrt(q)) // 2)


def repetition_overhead(eps: float) -> float:
    """Repetition factor `R(eps) = ln(2) / -ln(1/2 + 2 * sqrt(eps))` for `0 <= eps < 1/16`."""
    if not 0.0 <= eps < 1 / 16:
        raise ValueError(f'Effective error rate eps must be in [0, 1/16), got {eps}.')
    if eps == 0.0:
        return 1.0
    return math.log(2.0) / -math.log(0.5 + 2.0 * math.sqrt(eps))


def clopper_pearson_upper_bound(
    k: int, n: int, log2_delta: float = DEFAULT_LOG2_DELTA
) -> float:
    """One-sided Clopper-Pearson upper bound `eps_plus` at confidence `1 - 2^log2_delta`."""
    if n <= 0 or not (0 <= k <= n) or not (math.isfinite(log2_delta) and log2_delta <= 0.0):
        raise ValueError(
            f'Expected 0 <= k <= n, n > 0, and finite log2_delta <= 0, '
            f'got k={k}, n={n}, log2_delta={log2_delta}.'
        )
    if k == n or log2_delta == 0.0:
        return 1.0 if k == n else k / n
    log_delta = log2_delta * math.log(2.0)
    if k == 0:
        return -math.expm1(log_delta / n)
    j = np.arange(k + 1, dtype=np.float64)
    log_comb = np.r_[0.0, np.cumsum(np.log(n - j[1:] + 1.0) - np.log(j[1:]))]

    def log_tail(p: float) -> float:
        terms = log_comb + j * math.log(p) + (n - j) * math.log1p(-p)
        m = float(terms.max())
        return m + math.log(float(np.exp(terms - m).sum()))

    lo = k / n if log_tail(k / n) >= log_delta else 0.0
    hi = 1.0
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if mid == lo or mid == hi:
            break
        if log_tail(mid) > log_delta:
            lo = mid
        else:
            hi = mid
    return hi


def optimal_dqi_weights(m: int, max_errors: int, degree: int, r: int) -> np.ndarray:
    """Principal unit eigenvector `w_0..w_l` of the DQI tridiagonal matrix (arXiv:2408.08292, Lemma 9.2)."""
    q = 1 << degree
    if not (0 <= max_errors <= m and 0 < r < q):
        raise ValueError(f'Invalid (max_errors={max_errors}, r={r}) for m={m}, q={q}.')
    k = np.arange(max_errors + 1, dtype=np.float64)
    off = np.sqrt(k[1:] * (m - k[1:] + 1))
    d = (q - 2 * r) / math.sqrt(r * (q - r))
    _, vecs = np.linalg.eigh(np.diag(k * d) + np.diag(off, 1) + np.diag(off, -1))
    w = np.abs(vecs[:, -1])
    return w / np.linalg.norm(w)


def sample_error(m: int, max_value: int, weight_probs: Sequence[float],
                 rng: np.random.Generator) -> dict[int, int]:
    """Samples an error word `position -> value` from the DQI error distribution."""
    k = int(rng.choice(len(weight_probs), p=weight_probs))
    positions = rng.choice(m, size=k, replace=False).tolist()
    values = rng.integers(1, max_value, size=k, endpoint=True).tolist()
    return dict(zip(positions, values))


def to_bits(values: np.ndarray, degree: int) -> np.ndarray:
    """Unpacks `(batch, num_regs)` field elements into `(num_regs * degree, batch)` booleans."""
    bits = (values[:, :, None] >> np.arange(degree)) & 1 == 1
    return bits.transpose(1, 2, 0).reshape(-1, len(values))


# Register validation.


def validate_registers(
    circuit: km.Circuit, spec: ProblemSpecDQI
) -> tuple[list[Any], list[Any], km.array]:
    """Validates register names, types, widths, and disjointness."""
    registers = circuit.register_data
    s_names = [f'S{i}' for i in range(spec.n)]
    e_names = [f'E{j}' for j in range(spec.m)]
    if len(registers) != circuit.num_registers or set(registers) != set(s_names) | set(e_names):
        raise ValueError('Registers must be exactly S0..S{n-1} and E0..E{m-1}.')

    def collect(names: list[str], kind: type, label: str) -> list:
        out = []
        for name in names:
            reg = list(registers[name])
            if len(reg) != spec.degree or not all(isinstance(x, kind) for x in reg):
                raise ValueError(f'Register {name!r} must be {spec.degree} {label}, got {len(reg)}.')
            out.extend(reg)
        if len(set(out)) != len(out):
            raise ValueError(f'{label} registers must not overlap.')
        return out

    syndrome_qubits = collect(s_names, km.q, 'qubits')
    mbuc_bits = collect(e_names, km.b, 'classical bits')
    syndrome_set = set(syndrome_qubits)
    ancilla_qubits = km.array([km.q(k) for k in range(circuit.num_qubits) if km.q(k) not in syndrome_set])
    return syndrome_qubits, mbuc_bits, ancilla_qubits


# Shot sampling.


def sample_shots(
    spec: ProblemSpecDQI,
    tables: FieldTables,
    rng: np.random.Generator,
    num_shots: int,
    weight_probs: Sequence[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns `(syndromes, mbuc, phases)` for `num_shots` DQI test cases drawn from `rng`."""
    if weight_probs is None:
        weight_probs = optimal_dqi_weights(spec.m, spec.max_errors, spec.degree, spec.r) ** 2
    max_value = (1 << tables.degree) - 1
    weights = rng.choice(len(weight_probs), size=num_shots, p=weight_probs)
    mbuc = rng.integers(0, max_value, size=(num_shots, spec.m), endpoint=True, dtype=np.int64)
    syndromes = np.zeros((num_shots, spec.n), dtype=np.int64)
    phases = np.zeros(num_shots, dtype=bool)
    rows = np.arange(1, spec.n + 1, dtype=np.int64)[:, None]

    for shot in np.flatnonzero(weights):
        k = int(weights[shot])
        pos = rng.choice(spec.m, size=k, replace=False)
        vals = rng.integers(1, max_value, size=k, endpoint=True, dtype=np.int64)
        exps = (tables.log[vals][None, :] + rows * pos[None, :]) % tables.order
        syndromes[shot] = np.bitwise_xor.reduce(tables.antilog[exps], axis=1)
        phases[shot] = sum(int(x).bit_count() for x in vals & mbuc[shot, pos]) & 1 == 1
    return syndromes, mbuc, phases


# Simulation and verification.


def _validate_inputs(
    spec: ProblemSpecDQI,
    batch_size: int,
    log2_delta: float,
    shots: tuple[np.ndarray, np.ndarray, np.ndarray] | None,
) -> int:
    """Validates `spec`, `batch_size`, `log2_delta`, and `shots`, returning the total `num_shots`."""
    if not (1 <= spec.degree and 2 <= spec.n < spec.m <= (1 << spec.degree) - 1):
        raise ValueError(
            f'Expected 1 <= degree and 2 <= n < m <= 2^degree - 1, '
            f'got m={spec.m}, n={spec.n}, degree={spec.degree}.'
        )
    if batch_size <= 0:
        raise ValueError(f'batch_size must be positive, got {batch_size}.')
    if not (math.isfinite(log2_delta) and log2_delta <= 0.0):
        raise ValueError(f'Expected finite log2_delta <= 0, got {log2_delta}.')
    num_shots = spec.num_shots if shots is None else len(shots[0])
    if num_shots <= 0 or num_shots % batch_size:
        raise ValueError(f'num_shots must be a positive multiple of batch_size={batch_size}, got {num_shots}.')
    if shots is not None and not (
            shots[0].shape == (num_shots, spec.n)
            and shots[1].shape == (num_shots, spec.m)
            and shots[2].shape == (num_shots,)):
        raise ValueError('shots must be (syndromes[N, n], mbuc[N, m], phases[N]).')
    return num_shots


def _circuit_sha256(circuit: km.Circuit) -> str:
    """Returns the SHA-256 hex digest of the canonical `.kmb` serialization of `circuit`."""
    buf = io.BytesIO()
    circuit.to_file(buf, format='kmb')
    return hashlib.sha256(buf.getvalue()).hexdigest()


def _initial_seed(circuit_hash: str, salt: str) -> int:
    """Computes the initial RNG seed from `circuit_hash` and optional `salt`."""
    if not salt:
        return int(circuit_hash, 16)
    return int(hashlib.sha256(f'{circuit_hash}{salt}'.encode('utf-8')).hexdigest(), 16)


_WORKER_FN = None


def _call_worker(task):
    return _WORKER_FN(task)


def _run_parallel(fn, tasks: list, max_workers: int | None) -> list:
    global _WORKER_FN
    if max_workers is not None and max_workers <= 0:
        raise ValueError(f'max_workers must be positive, got {max_workers}.')
    cpus = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    workers = min(len(tasks), min(cpus, DEFAULT_MAX_WORKERS) if max_workers is None else max_workers)
    if workers <= 1 or 'fork' not in mp.get_all_start_methods():
        return [fn(t) for t in tasks]
    _WORKER_FN = fn
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('fork')) as pool:
            try:
                return list(pool.map(_call_worker, tasks))
            except Exception:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
    finally:
        _WORKER_FN = None


def verify(
    circuit: km.Circuit,
    spec: ProblemSpecDQI,
    *,
    seed: int | None = None,
    salt: str = '',
    batch_size: int = DEFAULT_BATCH_SIZE,
    log2_delta: float = DEFAULT_LOG2_DELTA,
    max_workers: int | None = None,
    shots: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Verifies `circuit` on `spec.num_shots` DQI test cases (or pre-generated `shots`)."""
    num_shots = _validate_inputs(spec, batch_size, log2_delta, shots)

    circuit_stats = circuit.operation_statistics()
    if 'Z_POW' in circuit_stats:
        raise ValueError('Z_POW gates are not allowed in Benchmark II.')
    circuit_hash = _circuit_sha256(circuit)

    syndrome_qubits, mbuc_bits, ancilla_qubits = validate_registers(circuit, spec)
    syndrome_array, mbuc_array = km.array(syndrome_qubits), km.array(mbuc_bits)

    weight_probs = optimal_dqi_weights(spec.m, spec.max_errors, spec.degree, spec.r) ** 2
    tables = FieldTables(km.GF2Field(spec.degree))
    base_seed = _initial_seed(circuit_hash, salt) if seed is None else int(seed)

    def run_batch(task: tuple[int, int, int]) -> tuple[int, int, int, dict[str, int]]:
        start, rng_seed, sim_seed = task
        stop = start + batch_size
        if shots is None:
            rng = np.random.default_rng(rng_seed)
            syndromes, mbuc, phases = sample_shots(spec, tables, rng, batch_size, weight_probs)
        else:
            syndromes, mbuc, phases = (a[start:stop] for a in shots)

        sim = km.Simulator(
            batch_size=batch_size,
            debug_print=False,
            counting_operations=True,
            seed=sim_seed,
        )
        sim.use_same_registers_as(circuit)
        input_syndromes = to_bits(syndromes, spec.degree)
        sim.write_across_shots(syndrome_array, input_syndromes)
        sim.write_across_shots(mbuc_array, to_bits(mbuc, spec.degree))
        sim.do(circuit)

        phase_flipped = sim.read_phase_flipped_across_shots()
        reg_diff = sim.read_across_shots(syndrome_array) ^ input_syndromes
        junk = (
            sim.read_across_shots(ancilla_qubits)
            if len(ancilla_qubits)
            else np.zeros((0, batch_size), dtype=bool)
        )

        val_err = reg_diff.any(axis=0) | junk.any(axis=0)
        phase_err = (phase_flipped ^ phases) & ~val_err
        stats = sim.operation_statistics()
        return int(val_err.sum()), int(phase_err.sum()), int(stats.num_toffoli_like), dict(stats)

    starts = range(0, num_shots, batch_size)
    seeds = np.random.SeedSequence(base_seed, pool_size=8).generate_state(8 * len(starts), dtype=np.uint64).reshape(-1, 2, 4)
    tasks = [(s, int.from_bytes(seeds[i, 0], 'little'), int.from_bytes(seeds[i, 1], 'little')) for i, s in enumerate(starts)]
    results = _run_parallel(run_batch, tasks, max_workers)

    value_errors = sum(r[0] for r in results)
    phase_errors = sum(r[1] for r in results)
    shot_operation_counts: dict[str, int] = {}
    for _, _, _, op_counts in results:
        for op, count in op_counts.items():
            shot_operation_counts[op] = shot_operation_counts.get(op, 0) + count

    total_errors = value_errors + phase_errors
    eps_hat = total_errors / num_shots
    eps_plus = clopper_pearson_upper_bound(total_errors, num_shots, log2_delta=log2_delta)
    if eps_plus >= 1 / 16:
        raise AssertionError(
            f'Effective error rate {eps_plus:.4f} >= 1/16 at log2_delta={log2_delta} '
            f'(empirical={eps_hat:.4f}, value_errors={value_errors}/{num_shots}, '
            f'phase_errors={phase_errors}/{num_shots})'
        )
    rep_factor = repetition_overhead(eps_plus)
    toffolis = sum(r[2] for r in results) / num_shots
    num_qubits = circuit.num_qubits
    return {
        'status': 'PASS',
        'score': rep_factor * (num_qubits ** 2) * toffolis,
        'm': spec.m,
        'n': spec.n,
        'degree': spec.degree,
        'r': spec.r,
        'verified_shots': num_shots,
        'value_errors': value_errors,
        'phase_errors': phase_errors,
        'empirical_error_rate': eps_hat,
        'effective_error_rate': eps_plus,
        'log2_delta': log2_delta,
        'repetition_factor': rep_factor,
        'mean_error_weight': float(np.arange(len(weight_probs)) @ weight_probs),
        'toffoli_count': toffolis,
        'max_toffoli_count': circuit.operation_statistics().num_toffoli_like,
        'reaction_depth': circuit.reaction_depth(),
        'num_ops': len(circuit),
        'shot_operation_counts': shot_operation_counts,
        'num_qubits': num_qubits,
        'num_bits': circuit.num_bits,
        'circuit_sha256': circuit_hash,
    }


# CLI.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('circuit_file', help='Path to a submitted .kmb or .kmx circuit file.')
    parser.add_argument('--format', choices=('auto', 'kmb', 'kmx'), default='auto',
                        help="Input circuit file format (default: 'auto', auto-detects .kmb or .kmx).")
    parser.add_argument('--m', type=int, default=DEFAULT_M, help=f'Codeword length (default: {DEFAULT_M}).')
    parser.add_argument('--n', type=int, default=DEFAULT_N, help=f'Number of syndromes (default: {DEFAULT_N}).')
    parser.add_argument('--degree', type=int, default=DEFAULT_DEGREE,
                        help=f'Field degree b for GF(2^b) (default: {DEFAULT_DEGREE}).')
    parser.add_argument('--r', type=int, default=None,
                        help=f'Accepted values per constraint |F_i| (default: {DEFAULT_R}).')
    parser.add_argument('--num-shots', type=int, default=DEFAULT_NUM_SHOTS,
                        help=f'Number of verification shots; must be a multiple of --batch-size '
                             f'(default: {DEFAULT_NUM_SHOTS}).')
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                        help=f'Simulator batch size (default: {DEFAULT_BATCH_SIZE}).')
    parser.add_argument('--log2-delta', type=float, default=DEFAULT_LOG2_DELTA,
                        help=f'Base-2 log of Clopper-Pearson delta (confidence 1 - 2^log2_delta; '
                             f'default: {DEFAULT_LOG2_DELTA}).')
    parser.add_argument('--salt', type=str, default='',
                        help='Optional salt merged with circuit_sha256 to derive the initial seed (default: empty).')
    parser.add_argument('--seed', type=int, default=None,
                        help='Explicit RNG seed overriding circuit_sha256 and --salt.')
    parser.add_argument('--max-workers', type=int, default=DEFAULT_MAX_WORKERS,
                        help=f'Maximum worker processes (default: {DEFAULT_MAX_WORKERS}, matching 4-core / 30 GB '
                             f'Kaggle notebooks; each worker needs ~6 GB of RAM for the reference decoder).')
    args = parser.parse_args()

    r = default_num_accepted_values(args.degree) if args.r is None else args.r
    spec = ProblemSpecDQI(
        m=args.m,
        n=args.n,
        degree=args.degree,
        r=r,
        num_shots=args.num_shots,
    )
    try:
        summary = verify(
            km.Circuit.from_file(args.circuit_file, format=args.format),
            spec,
            seed=args.seed,
            salt=args.salt,
            batch_size=args.batch_size,
            log2_delta=args.log2_delta,
            max_workers=args.max_workers,
        )
    except (AssertionError, ValueError, RuntimeError, OSError) as ex:
        print(json.dumps({'status': 'FAIL', 'error': str(ex)}, indent=2))
        sys.exit(1)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

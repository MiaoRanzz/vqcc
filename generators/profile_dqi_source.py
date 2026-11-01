"""Rebuild an explicit DQI source entry and profile its Python workspace lifetimes.

The proxy forwards every operation and mark to the unchanged bundled builder.
It observes explicit alloc/free calls, not allocations internal to native helper
methods. Emitted artifact equality and final Q are checked independently.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import kickmix as km


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ProfileBuilder:
    def __init__(self, builder, source_root):
        self.builder = builder
        self.source_root = Path(source_root).resolve()
        self.owners = {}
        self.scopes = []
        self.high_allocations = Counter()
        self.peaks = []
        self.peak = 0
        self.allocations = 0

    def __getattr__(self, name):
        return getattr(self.builder, name)

    def alloc_qubits(self, count):
        wires = self.builder.alloc_qubits(count)
        frame = sys._getframe(1)
        filename = Path(frame.f_code.co_filename).resolve()
        try:
            filename = filename.relative_to(self.source_root)
        except ValueError:
            pass
        site = f'{filename}:{frame.f_lineno}:{frame.f_code.co_name}'
        for q in wires:
            self.owners[q] = site
        self.allocations += 1
        live = self.builder.num_allocated_qubits
        if live >= 895:
            self.high_allocations[(site, live, tuple(self.scopes))] += 1
        if live > self.peak:
            self.peak = live
            owners = Counter(self.owners.values())
            self.peaks.append(dict(live=live, tracked_live=len(self.owners), site=site,
                                   scopes=list(self.scopes), owners=dict(owners)))
        return wires

    def free(self, arg):
        try:
            wires = list(arg)
        except TypeError:
            wires = [arg]
        self.builder.free(arg)
        for q in wires:
            self.owners.pop(q, None)

    @contextmanager
    def mark(self, name):
        self.scopes.append(name)
        try:
            with self.builder.mark(name):
                yield
        finally:
            self.scopes.pop()

    def report(self):
        return dict(explicit_allocation_peak=self.peak, allocations=self.allocations,
                    tracked_at_end=len(self.owners), peaks=self.peaks[-12:],
                    high_allocations=[dict(site=k[0], live=k[1], scopes=list(k[2]), count=n)
                                      for k, n in self.high_allocations.most_common()],
                    scope='Python alloc/free only; native helper temporaries are not intercepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error('Output and report must be new')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    sys.modules['circ'] = km
    spec = importlib.util.spec_from_file_location('profiled_decoder', args.entry.resolve())
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    builder = ProfileBuilder(km.CircuitBuilder(), args.entry.resolve().parent)
    syndrome = [builder.alloc_qubits(12) for _ in range(70)]
    masks = [builder.alloc_bits(12) for _ in range(4095)]
    module.decode(builder, syndrome, masks)
    metadata = []
    for i in range(70):
        metadata.append(f'REGISTER r{i} "S{i}"')
        metadata.extend(f'APPEND_TO_REGISTER q{12*i+k} r{i}' for k in range(12))
    for j in range(4095):
        metadata.append(f'REGISTER r{70+j} "E{j}"')
        metadata.extend(f'APPEND_TO_REGISTER b{12*j+k} r{70+j}' for k in range(12))
    circuit = km.Circuit('\n'.join(metadata)) + builder.finish_circuit()
    circuit.to_file(str(args.output), format='kmb')
    sha = digest(args.output)
    result = dict(kind='explicit_source_rebuild_and_lifetime_profile', official_validation=False,
                  entry=str(args.entry.resolve()), entry_sha256=digest(args.entry),
                  profiler_sha256=digest(__file__), argv=sys.argv, python=sys.executable,
                  prefix=sys.prefix, sha256=sha, Q=circuit.num_qubits,
                  T_static=circuit.operation_statistics().num_toffoli_like,
                  num_ops=len(circuit), num_bits=circuit.num_bits,
                  elapsed_seconds=time.monotonic()-started, **builder.report())
    if args.expected_sha256:
        result['expected_sha256'] = args.expected_sha256
        result['byte_identical'] = sha == args.expected_sha256
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['sha256','Q','T_static','elapsed_seconds']}), flush=True)
    if args.expected_sha256 and sha != args.expected_sha256:
        raise SystemExit('Reproduction did not match the pinned artifact')


if __name__ == '__main__':
    main()

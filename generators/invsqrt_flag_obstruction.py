# SPDX-License-Identifier: Apache-2.0
"""Exact obstruction to reconstructing an idle flag from other wire values.

Enumerate the full legal InvSqrt domain through its deterministic value prefix.
If two inputs have identical remaining quantum wire values but different flag
values at the reconstruction point, no Boolean function of those remaining
values reconstructs the flag. This only rejects that specific spill strategy;
it says nothing about changed arithmetic, additional stored information, or
reconstruction using other resources. Phase/measurement instructions are kept.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import time
import numpy as np
from generate import ROOT, sha256
from invsqrt_reachable import analyze_prefix, unpack


def conflicting_inputs(codes, target):
    """Return an explicit colliding pair, never infer impossibility from rank."""
    _, first, inverse = np.unique(codes, return_index=True, return_inverse=True)
    bad = np.flatnonzero(target != target[first[inverse]])
    pair = None if not len(bad) else (int(first[inverse[bad[0]]]), int(bad[0]))
    return pair, len(first), len(bad)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact', type=Path, required=True)
    p.add_argument('--expected-sha256', required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--flag', type=int, default=23)
    p.add_argument('--gap-start', type=int, default=249)
    p.add_argument('--gap-end', type=int, default=15244)
    a = p.parse_args(); start = time.monotonic()
    if sha256(a.artifact) != a.expected_sha256:
        raise ValueError('Pinned artifact changed')
    sys.path.insert(0, str(ROOT/'kickmix')); import kickmix as km
    circuit = km.Circuit.from_file(a.artifact)
    if circuit.num_qubits > 64 or not 22 <= a.flag < circuit.num_qubits:
        raise ValueError('Unsupported width or flag')
    text = str(circuit); lines = text.splitlines()
    if not 0 <= a.gap_start < a.gap_end < len(lines):
        raise ValueError('Gap outside circuit')
    token = re.compile(r'\bq'+str(a.flag)+r'\b')
    if any(token.search(line) for line in lines[a.gap_start:a.gap_end]):
        raise ValueError('Flag is used inside the proposed gap')
    if not token.search(lines[a.gap_end]):
        raise ValueError('Gap end must be the next flag use')
    max_x = 3133452
    analysis = analyze_prefix(lines[:a.gap_end+1], snapshots=[a.gap_end])
    if a.gap_end not in analysis['snapshots']:
        raise ValueError('Reconstruction point exceeds the deterministic value prefix')
    state = analysis['snapshots'][a.gap_end]
    wires = [q for q in range(circuit.num_qubits) if q != a.flag]
    codes = np.zeros(max_x, dtype=np.uint64)
    for bit, q in enumerate(wires):
        codes |= unpack(state.get(q,0), max_x).astype(np.uint64) << bit
    target = unpack(state[a.flag],max_x)
    pair, unique, conflicts = conflicting_inputs(codes,target)
    witness = None
    if pair:
        i,j = pair
        assert codes[i] == codes[j] and target[i] != target[j]
        witness = dict(inputs=[i+1,j+1], flag_values=[int(target[i]),int(target[j])],
                       other_wire_order=wires, identical_other_values_hex=hex(int(codes[i])))
    report = dict(kind='exact_quantum_value_only_flag_reconstruction_obstruction',
                  official_validation=False, artifact=str(a.artifact.resolve()),
                  artifact_sha256=a.expected_sha256, argv=sys.argv,
                  python_executable=sys.executable, python_prefix=sys.prefix,
                  domain=[1,max_x], flag=a.flag, gap=[a.gap_start,a.gap_end],
                  next_use=lines[a.gap_end], distinct_remaining_patterns=unique,
                  conflicting_inputs_against_class_representative=conflicts, witness=witness,
                  decision='infeasible_quantum_value_only_reconstruction' if witness else 'no_obstruction_found',
                  scope='Same unmodified deterministic prefix, full legal domain, all other quantum wire values. No claim against altered arithmetic, retained extra information or other resources.',
                  source_hashes={name:sha256(Path(__file__).with_name(name)) for name in
                                 ['invsqrt_flag_obstruction.py','invsqrt_reachable.py']},
                  elapsed_seconds=time.monotonic()-start)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report))


if __name__ == '__main__':
    main()

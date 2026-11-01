"""Check q22 retained-trace identities, not full decoder acceptance.

The 144 GF(2) basis pairs prove the bilinear product identity for every pair
of 12-bit values. Exhaustion of the 4096 field values checks zero completion
and the coordinate inverse. Measurement/return behavior still needs the full
unchanged official DQI verifier.
"""
from __future__ import annotations
import argparse
import ast
import functools
import importlib.util
import json
from pathlib import Path
import sys
import kickmix as km
from profile_dqi_source import digest


def check(root):
    sys.modules['circ'] = km
    arithmetic = root/'playbook/kit/decoder/exp/arithmetic/field.py'
    spec = importlib.util.spec_from_file_location('trace_arithmetic', arithmetic)
    ar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ar)
    source = root/'exp/next/a05/single_trace_return.py'
    tree = ast.parse(source.read_text())
    scope = dict(field=ar.field, ar=ar, inverse_columns=ar.inverse_columns,
                 lru_cache=functools.lru_cache)
    # Read the actual recipe's definitions without importing the large decoder graph.
    for name in ['rank', 'layout']:
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    rows = []
    for k in [2, 3, 6]:
        plan = scope['layout'](k)
        field, subfield = ar.field(12), ar.field(k)
        for i in range(12):
            for j in range(12):
                a = ar.apply(plan['extension_to'], 1 << i)
                b = ar.apply(plan['dual'], 1 << j)
                value = 0
                for h in range(12//k):
                    value ^= subfield.mul((a >> (k*h)) & ((1 << k)-1),
                                          (b >> (k*h)) & ((1 << k)-1))
                if value != ar.apply(plan['trace'], field.mul(1 << i, 1 << j)):
                    raise AssertionError(f'Trace product failed for {k=}, {i=}, {j=}')
        for x in range(4096):
            if ar.apply(plan['trace'], x) != ar.apply(plan['trace'], x ^ 1):
                raise AssertionError('Trace changed under zero completion')
            if ar.apply(plan['back'], ar.apply(plan['to'], x)) != x:
                raise AssertionError('Coordinate maps were not inverse')
        rows.append(dict(trace_bits=k, retained_bits=12-k, bilinear_basis_cases=144,
                         zero_completion_cases=4096,
                         trace_rebuild_toffoli=(12//k)*len(ar.tensor(k))))
    return dict(official_validation=False, rows=rows, python=sys.executable,
                prefix=sys.prefix, source_root=str(root.resolve()),
                input_hashes={str(p.relative_to(root)): digest(p) for p in [source, arithmetic]},
                check_sha256=digest(__file__))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Report must be new')
    result = check(args.source_root)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['rows']))


if __name__ == '__main__':
    main()

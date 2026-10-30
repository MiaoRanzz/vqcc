"""Exact legal-address linear elimination in credited native ANGLE plans.

The emitter is Atakan Aldemir's retained Apache-2.0 source. This reduction is
independent: eliminate product truth tables only when an exact GF(2) relation
with already available monomials/products exists on *every* legal address.
The original redundant-sign borrowing contract is retained, not strengthened
into arbitrary-target XOR semantics. No simulator seed participates in search.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'kickmix'), str(ROOT / 'verifiers')]
import numpy as np
from dfthcsos.example_submission.angle_k_reference_circuit import batch_deltas
from generate import output_workspace, sha256

EMITTER = ROOT / 'generators/vendor/atakan_native/rebuild_native.py'


def set_bits(value):
    while value:
        bit = value & -value
        yield bit.bit_length() - 1
        value ^= bit


def pure_masks(rows):
    return [m for m in range(rows) if m < 16 or m % 16 == 0]


def truth_tables(rows):
    return {m: sum(1 << a for a in range(rows) if a & m == m)
            for m in pure_masks(rows)}


def form_truth(form, tables):
    value = 0
    for m in set_bits(int(form['low'])):
        value ^= tables[m]
    for h in set_bits(int(form['high'])):
        value ^= tables[h << 4]
    return value


def evaluate(plan, tables, rows):
    result = [0] * rows
    terms = [(tables[int(m)], fan) for m, fan in plan['pure'].items()]
    terms += [(form_truth(p['a'], tables) & form_truth(p['b'], tables), p['fanout'])
              for p in plan['products']]
    for truth, fan in terms:
        for address in set_bits(truth):
            result[address] ^= fan
    return result


def reduce_plan(plan, rows):
    tables = truth_tables(rows)
    masks = list(tables)
    basis = {}
    def add(value, coordinate):
        relation = coordinate
        while value:
            pivot = value.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = (value, relation)
                return None
            previous, combo = basis[pivot]
            value ^= previous
            relation ^= combo
        return relation
    for i, m in enumerate(masks):
        assert add(tables[m], 1 << i) is None
    products = json.loads(json.dumps(plan['products']))
    pure = {int(m): int(fan) for m, fan in plan['pure'].items()}
    retained, removed = [], []
    for i, product in enumerate(products):
        truth = form_truth(product['a'], tables) & form_truth(product['b'], tables)
        relation = add(truth, 1 << (len(masks) + i))
        if relation is None:
            retained.append(i)
            continue
        relation ^= 1 << (len(masks) + i)
        fan = product['fanout']
        for index in set_bits(relation):
            if index < len(masks):
                m = masks[index]
                pure[m] = pure.get(m, 0) ^ fan
            else:
                products[index - len(masks)]['fanout'] ^= fan
        removed.append({'product': i, 'relation': hex(relation)})
    result = {'products': [products[i] for i in retained if products[i]['fanout']],
              'pure': {str(m): fan for m, fan in pure.items() if fan}}
    before = evaluate(plan, tables, rows)
    assert before == evaluate(result, tables, rows)
    return result, {'original_products': len(products), 'remaining_products': len(result['products']),
                    'removed': removed, 'domain': [0, rows], 'exact_truth_table_match': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bank', type=Path, required=True)
    parser.add_argument('--parent-output', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    source = args.source_bank.resolve()
    manifest = json.loads((source / 'MANIFEST.json').read_text())
    with np.load(args.parent_output / 'submission.npz', allow_pickle=False) as data:
        words = np.array(data['angle_words'])
    with np.load(source / 'factorization.npz', allow_pickle=False) as data:
        assert np.array_equal(words, data['angle_words']), 'Source plans use different words'
    assert words.shape == (1220, 75)
    assert np.all((words >> 7) == ((words >> 6) & 1)), 'Sign borrowing premise fails'
    expected = batch_deltas(words, 5)
    spec = importlib.util.spec_from_file_location('reviewed_native', EMITTER)
    emitter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emitter)  # reviewed definitions only; main is not called
    reports = []
    code = args.output_dir.parent / 'code'
    code.mkdir(exist_ok=True)
    tables = truth_tables(len(words))
    with output_workspace(args.output_dir) as (output, stage):
        shutil.copyfile(args.parent_output / 'submission.npz', stage / 'submission.npz')
        for k in range(15):
            name = f'plans/batch_{k}.json'
            assert sha256(source / name) == manifest['files'][name]
            plan = json.loads((source / name).read_text())
            optimized, report = reduce_plan(plan, len(words))
            truth = evaluate(optimized, tables, len(words))
            target = [sum(int(v) << (8 * j) for j, v in enumerate(row)) for row in expected[k]]
            assert truth == target, 'Plan disagrees with unchanged factor words'
            c = emitter.emit_native(optimized['products'], {int(m): v for m, v in optimized['pure'].items()})
            dest = stage / f'angle_k_{k}.kmb'
            c.to_file(dest, format='kmb')
            report.update(batch=k, qubits=c.num_qubits, toffolis=int(c.operation_statistics().num_toffoli_like),
                          sha256=sha256(dest), parent_sha256=sha256(args.parent_output / dest.name))
            reports.append(report)
            (code / f'optimized_plan_{k}.json').write_text(json.dumps(optimized, indent=2) + '\n')
            shutil.copyfile(source / name, code / f'parent_plan_{k}.json')
            print(json.dumps(report), flush=True)
    for name in ['MANIFEST.json', 'LICENSE.md', 'CREDITS.md', 'SOURCE_MANIFEST.json']:
        shutil.copy2(source / name, code / name)
    report = {'kind': 'exact_native_plan_reduction', 'official_validation': False,
              'parent_output': str(args.parent_output.resolve()), 'source_bank': str(source),
              'source_manifest_sha256': sha256(source / 'MANIFEST.json'),
              'source_sha256': sha256(Path(__file__)), 'emitter_sha256': sha256(EMITTER),
              'python_executable': sys.executable, 'created_at': datetime.now(timezone.utc).isoformat(),
              'elapsed_seconds': time.monotonic() - start, 'rows': reports,
              'saved_products_per_pass': sum(r['original_products'] - r['remaining_products'] for r in reports),
              'all_parent_circuits_byte_identical': all(r['sha256'] == r['parent_sha256'] for r in reports),
              'scope': 'All legal addresses, exact words. Borrowed sign workspace retains original reachable-state contract.'}
    (output.parent / 'generation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}), flush=True)


if __name__ == '__main__':
    main()

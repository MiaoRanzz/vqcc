"""Build a per-slot minimum-loader recipe for dfthcsos_public_parts.py.

Keeps the parent's NPZ (factorization, words, tree) and, for every ANGLE slot,
selects the loader with the lowest static max_magic among the parent and the
given public families whose angle_words and tree_edges equal the parent's.
Ties keep the parent's own file. Writes recipe.json, provenance.json and a
parts directory with the selected bytes; no upstream code is executed.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'kickmix'), str(ROOT / 'verifiers'), str(ROOT / 'generators')]

from generate import sha256  # noqa: E402
import numpy as np  # noqa: E402
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs  # noqa: E402


def words_tree(directory):
    with np.load(directory / 'submission.npz', allow_pickle=False) as data:
        return np.array(data['angle_words']), np.array(data['tree_edges'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--parent-id', required=True)
    p.add_argument('--family', type=Path, action='append', default=[],
                   help='Directory holding a public family submission.npz and angle_k_*.kmb')
    p.add_argument('--manifest', type=Path, required=True,
                   help='Public manifest.csv with author/licence/notebook columns per family sha12')
    p.add_argument('--dataset', required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    meta = {r['sha12']: r for r in csv.DictReader(args.manifest.open())}
    parent_words, parent_tree = words_tree(args.parent_output)
    parent_costs = [s['max_magic'] for s in circuit_costs(load_circuits(args.parent_output))]
    best = [dict(cost=c, directory=args.parent_output, family=None) for c in parent_costs]
    screened = []
    for fam in args.family:
        words, tree = words_tree(fam)
        same = (words.shape == parent_words.shape and np.array_equal(words, parent_words)
                and tree.shape == parent_tree.shape and np.array_equal(tree, parent_tree))
        costs = [s['max_magic'] for s in circuit_costs(load_circuits(fam))] if same else None
        screened.append(dict(family=fam.name, same_words_and_tree=bool(same), max_magic=costs))
        if not same or len(costs) != len(best):
            continue
        for k, c in enumerate(costs):
            if c < best[k]['cost']:
                best[k] = dict(cost=c, directory=fam, family=fam.name)
    parts = args.out / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.parent_output / 'submission.npz', parts / 'submission.npz')
    slots = []
    for k, b in enumerate(best):
        name = f'angle_k_{k}.kmb'
        shutil.copyfile(b['directory'] / name, parts / name)
        row = meta.get(b['family'] or '', {})
        slots.append(dict(slot=k, file_sha256=sha256(parts / name), max_magic=b['cost'],
                          source_family=b['family'] or f'parent:{args.parent_id}',
                          author=row.get('author'), notebook=row.get('source_notebook_url'),
                          notebook_version=row.get('source_notebook_version'),
                          licence=row.get('licence') if b['family'] else 'parent candidate',
                          dataset_path=f"circuits/chemistry/{b['family']}/{name}" if b['family'] else None))
    recipe = dict(schema=1, task='dfthcsos', method='per-slot minimum static max_magic over identical words/tree',
                  dataset=args.dataset, manifest_sha256=sha256(args.manifest),
                  npz=dict(sha256=sha256(parts / 'submission.npz'), source=f'parent:{args.parent_id}'),
                  parent_max_magic_total=sum(parent_costs), max_magic_total=sum(b['cost'] for b in best),
                  screened=screened, slots=slots)
    (args.out / 'recipe.json').write_text(json.dumps(recipe, indent=2) + '\n')
    licences = {s['licence'] for s in slots if s['source_family'] != f'parent:{args.parent_id}'}
    provenance = dict(recipe_sha256=sha256(args.out / 'recipe.json'),
                      reuse_decision='eligible' if licences <= {'Apache-2.0'} else 'unresolved',
                      licences=sorted(licences), dataset=args.dataset)
    (args.out / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps(dict(parent_total=sum(parent_costs), total=recipe['max_magic_total'],
                          changed=[s['slot'] for s in slots if not s['source_family'].startswith('parent:')],
                          reuse_decision=provenance['reuse_decision']), indent=2))


if __name__ == '__main__':
    main()

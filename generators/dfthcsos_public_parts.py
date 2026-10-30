"""Assemble reviewed public chemistry parts and screen their numerical cost.

Independent implementation of the parts-assembly method documented by
manwithacat. Circuit and weight bytes remain attributed to their original
creators in the pinned recipe/provenance; no upstream notebook is executed.
The numerical screen does not prove loader compatibility: full official
verification of this exact combined family remains mandatory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

from generate import ROOT, output_workspace, sha256
import numpy as np
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs


def recipe_files(recipe):
    slots = recipe['slots']
    indices = [s['slot'] for s in slots]
    if indices != list(range(len(slots))) or not slots:
        raise ValueError('Recipe slots must be contiguous, ordered and unique')
    return [('submission.npz', recipe['npz']['sha256'])] + [
        (f"angle_k_{s['slot']}.kmb", s['file_sha256']) for s in slots]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe', type=Path, required=True)
    p.add_argument('--provenance', type=Path, required=True)
    p.add_argument('--parts-dir', type=Path, required=True)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    start = time.monotonic()
    recipe = json.loads(args.recipe.read_text())
    provenance = json.loads(args.provenance.read_text())
    if provenance['reuse_decision'] != 'eligible':
        raise ValueError('Source permission remains unresolved')
    if provenance['recipe_sha256'] != sha256(args.recipe):
        raise ValueError('Recipe differs from reviewed provenance')
    records = []
    with output_workspace(args.output_dir) as (output, stage):
        for name, digest in recipe_files(recipe):
            src = args.parts_dir / name
            if sha256(src) != digest:
                raise ValueError(f'Public part hash mismatch: {name}')
            shutil.copyfile(src, stage / name)
            records.append(dict(path=name, sha256=digest, bytes=src.stat().st_size,
                                parent_sha256=sha256(args.parent_output / name)))
        with np.load(stage / 'submission.npz', allow_pickle=False) as data:
            words, edges = np.array(data['angle_words']), np.array(data['tree_edges'])
        with np.load(args.parent_output / 'submission.npz', allow_pickle=False) as parent:
            same_words = np.array_equal(words, parent['angle_words'])
            same_tree = np.array_equal(edges, parent['tree_edges'])
        if not same_words or not same_tree:
            raise ValueError('This experiment requires unchanged parent words and tree')
        inputs = load_inputs(stage / 'submission.npz')
        metrics = evaluate_words(inputs, words, edges, 8)
        circuits = load_circuits(stage)
        stats = circuit_costs(circuits)
        resources = resource_costs(inputs, circuits, 8, 2 * sum(s['max_magic'] for s in stats))
        screen = dict(kind='numerical_and_static_resource_screen', official_validation=False,
                      parent_words_equal=same_words, parent_tree_equal=same_tree,
                      metrics=metrics, resources=resources,
                      passes_numerical_gates=passes_accuracy(metrics),
                      conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'])
        if not screen['passes_numerical_gates'] or not resources['angles_within_cap']:
            raise ValueError(f'Assembly failed cheap screen: {screen}')
    code = output.parent / 'code'
    code.mkdir(exist_ok=True)
    for f in (args.recipe, args.provenance):
        if f.resolve() != (code / f.name).resolve():
            shutil.copy2(f, code / f.name)
    report = dict(kind='pinned_public_parts_assembly', official_validation=False,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  python_executable=sys.executable, python_prefix=sys.prefix,
                  recipe_sha256=sha256(args.recipe), provenance_sha256=sha256(args.provenance),
                  generator_sha256=sha256(Path(__file__)), parent_output=str(args.parent_output.resolve()),
                  source_generator_available=False, artifacts=records, screen=screen,
                  elapsed_seconds=time.monotonic()-start)
    (output.parent / 'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

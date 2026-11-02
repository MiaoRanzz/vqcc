# SPDX-License-Identifier: Apache-2.0
"""Materialize a pinned manifold checkpoint for fresh official verification.

A saved w/d point is numerical evidence only. Reuse its parent's fixed words,
loaders and ancillary arrays, recompute all numerical gates and whole cost, and
write a distinct candidate without modifying the interrupted experiment.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from generate import sha256, output_workspace
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--expected-parent-sha256', required=True)
    p.add_argument('--expected-checkpoint-sha256', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--brot', type=int, required=True)
    args = p.parse_args()
    source = args.parent_output/'submission.npz'
    if sha256(source) != args.expected_parent_sha256 or sha256(args.checkpoint) != args.expected_checkpoint_sha256:
        raise ValueError('Pinned parent or checkpoint changed')
    arrays = dict(np.load(source, allow_pickle=False))
    with np.load(args.checkpoint, allow_pickle=False) as saved:
        w, d = saved['w'].copy(), saved['d'].copy()
    inputs = load_inputs(source)
    if w.shape != inputs.w.shape or d.shape != inputs.W.shape:
        raise ValueError('Checkpoint dimensions differ from parent')
    if not np.all(np.isfinite(w)) or not np.all(np.isfinite(d)):
        raise ValueError('Nonfinite checkpoint')
    if 'brot' in arrays and int(arrays['brot']) != args.brot:
        raise ValueError('Precision mismatch')
    arrays['brot'] = np.array(args.brot)
    arrays['W'], arrays['H2_I'] = w, d+w.sum(axis=1)
    if 'offset_W' in arrays:
        arrays['offset_W'] = d
    with output_workspace(args.output_dir) as (output, stage):
        np.savez(stage/'submission.npz', **arrays)
        for f in args.parent_output.glob('angle_k_*.kmb'):
            shutil.copy2(f, stage/f.name)
        final = load_inputs(stage/'submission.npz')
        metrics = evaluate_words(final, arrays['angle_words'], arrays['tree_edges'], args.brot)
        if not passes_accuracy(metrics):
            raise ValueError(f'Checkpoint fails numerical gates: {metrics}')
        circuits = load_circuits(stage)
        resources = resource_costs(final, circuits, args.brot,
            2*sum(s['max_magic'] for s in circuit_costs(circuits)))
    report = dict(kind='recovered_manifold_checkpoint', official_validation=False,
        parent_output=str(args.parent_output.resolve()), source_sha256=sha256(source),
        checkpoint=str(args.checkpoint.resolve()), checkpoint_sha256=sha256(args.checkpoint),
        generator_sha256=sha256(Path(__file__)), argv=sys.argv,
        python_executable=sys.executable, python_prefix=sys.prefix,
        metrics=metrics, resources=resources, passes_numerical_gates=True,
        conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],
        artifacts=[dict(path=f.name, sha256=sha256(f)) for f in sorted(output.iterdir())])
    code=output.parent/'code';code.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__),code/Path(__file__).name)
    screen=output.parent/'screen';screen.mkdir(exist_ok=True)
    shutil.copy2(args.checkpoint,screen/'recovered-point.npz')
    shutil.copy2(Path(__file__).with_name('generate.py'),code/'generate.py')
    (output.parent/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

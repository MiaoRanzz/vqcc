# SPDX-License-Identifier: Apache-2.0
"""Drop one physical rank direction, then attempt a bounded manifold refit.

The minimum-L1 Householder initialization preserves the same angle words/tree.
Initialization alone is not the experiment: the existing block-metric fitter
must recover the residual/gap constraints and beat the parent's whole cost.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import numpy as np
from generate import sha256
from dfthcsos.verify import load_inputs, evaluate_words, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs
from dfthcsos_fixed_words import from_inputs, near_identity_rank_drop


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--cache-parent-output', type=Path, required=True)
    p.add_argument('--brot', type=int, required=True)
    p.add_argument('--max-seconds', type=float, default=180)
    p.add_argument('--stop-by', required=True)
    args = p.parse_args(); started = time.monotonic()
    stop = datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None or not 0 < args.max_seconds <= 600:
        p.error('Timezone and a 0..600 second budget are required')
    if (stop-datetime.now(timezone.utc)).total_seconds() < args.max_seconds+30:
        p.error('Insufficient time for refit and checkpoint')
    candidate = args.output_dir.parent
    screen = candidate/'screen'; screen.mkdir(exist_ok=True)
    seed = screen/'rank-initial-output'; seed.mkdir()
    source = args.parent_output/'submission.npz'
    arrays = dict(np.load(source, allow_pickle=False))
    with np.load(args.cache_parent_output/'submission.npz', allow_pickle=False) as other:
        for key in ('angle_words', 'tree_edges'):
            if not np.array_equal(arrays[key], other[key]):
                raise ValueError('Cache words/tree mismatch')
    if 'brot' in arrays and int(arrays['brot']) != args.brot:
        raise ValueError('Precision mismatch')
    arrays['brot'] = np.array(args.brot)
    inputs = load_inputs(source)
    model = from_inputs(inputs, arrays, dict(np.load(args.cache, allow_pickle=False)))
    w, d, details, q = near_identity_rank_drop(inputs.w, inputs.W, model.ar)
    arrays['W'] = w; arrays['H2_I'] = d+w.sum(axis=1)
    if 'offset_W' in arrays:
        arrays['offset_W'] = d
    np.savez(seed/'submission.npz', **arrays)
    np.save(screen/'column-projection.npy', q)
    for path in args.parent_output.glob('angle_k_*.kmb'):
        shutil.copy2(path, seed/path.name)
    seed_inputs = load_inputs(seed/'submission.npz')
    metrics = evaluate_words(seed_inputs, arrays['angle_words'], arrays['tree_edges'], args.brot)
    circuits = load_circuits(seed); stats = circuit_costs(circuits)
    resources = resource_costs(seed_inputs, circuits, args.brot, 2*sum(row['max_magic'] for row in stats))
    report = dict(kind='rank_drop_with_bounded_block_refit', official_validation=False,
        parent_output=str(args.parent_output.resolve()), parent_sha256=sha256(source),
        seed_sha256=sha256(seed/'submission.npz'), cache_sha256=sha256(args.cache),
        initial_metrics=metrics, initial_resources=resources,
        initial_conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],
        initializer=details, rank_before=inputs.w.shape[-1], rank_after=w.shape[-1],
        projection_sha256=sha256(screen/'column-projection.npy'),
        argv=sys.argv, python=sys.executable, prefix=sys.prefix,
        generator_sha256=sha256(Path(__file__)),
        model_sha256=sha256(Path(__file__).with_name('dfthcsos_fixed_words.py')))
    (candidate/'rank-initialization.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(initial_metrics=metrics, conditional_cost=report['initial_conditional_cost'])), flush=True)
    command = ['conda', 'run', '--no-capture-output', '-n', 'vqcc', sys.executable,
        str(Path(__file__).with_name('dfthcsos_manifold.py')), '--parent-output', str(seed),
        '--output-dir', str(args.output_dir), '--cache', str(args.cache), '--brot', str(args.brot),
        '--freeze-below', '1e-5', '--error1-inequality', '--stall-window', '20',
        '--minimum-lambda-progress', '1e-8', '--block-residual-metric', '--max-seconds', str(args.max_seconds),
        '--iterations', '10000', '--stop-by', args.stop_by]
    log = candidate/'refit.log'
    with log.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=args.max_seconds+60)
    if result.returncode:
        if 'Initial constraint retraction failed' not in log.read_text():
            raise RuntimeError(f'Unexpected fitter failure; inspect {log}')
        final = dict(report, decision='rejected_initial_retraction_failed',
                     scope='This initialization and ten-step block-metric Newton retraction only; not rank39 infeasibility')
    else:
        final = json.loads((candidate/'generation.json').read_text())
        final['rank_initialization'] = report
    final['rank_refit_command'] = command
    final['rank_refit_elapsed_seconds'] = time.monotonic()-started
    (candidate/'generation.json').write_text(json.dumps(final, indent=2)+'\n')
    code = candidate/'code'; code.mkdir(exist_ok=True)
    for name in ('dfthcsos_rank_refit.py', 'dfthcsos_manifold.py', 'dfthcsos_fixed_words.py',
                 'dfthcsos_block_metric.py', 'dfthcsos_curvature.py', 'dfthcsos_orthant.py'):
        shutil.copy2(Path(__file__).with_name(name), code/name)
    print(json.dumps(dict(decision=final.get('decision', final.get('status')),
                         conditional_cost=final.get('conditional_cost'),
                         elapsed_seconds=final['rank_refit_elapsed_seconds'])), flush=True)


if __name__ == '__main__':
    main()

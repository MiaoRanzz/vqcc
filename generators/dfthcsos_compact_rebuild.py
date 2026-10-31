"""Replay Marculera's compact-factor tensor recipe with bounded checkpoints.

The original tensorqrom emitter and decomposition are imported from an explicitly
pinned source bank. Skip its full-cache search only when its allocated width is
statically above the official cap; each grouped decomposition starts from its
own batch seed, so skipping that search does not change the selected recipe.
Author/source notices remain with the source bank. No training is replayed.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sys
import time
from generate import ROOT, output_workspace, sha256
import numpy as np
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs


def full_cache_width(addresses, batch, brot, lowbits):
    """Exact allocations of the upstream non-borrowing full-cache branch."""
    high = math.ceil(addresses / 2**lowbits)
    high_singles = sum(m.bit_count() == 1 for m in range(1, high))
    low_ands = 2**lowbits - 1 - lowbits
    high_ands = high - 1 - high_singles
    return max(1, (addresses-1).bit_length()) + batch*brot + low_ands + high_ands


def source_module(bank):
    os.environ['DFTHC_DATA'] = str(ROOT)
    sys.path.insert(0, str(bank))
    return importlib.import_module('tensorqrom')


def solve_task(task):
    bank, screen, k, delta, nsel, brot, trials, perm, sizes, source_hash, deadline = task
    def expired(*_):
        raise TimeoutError('Bounded decomposition deadline reached')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(.01, deadline-time.time()))
    start = time.monotonic()
    tq = source_module(bank)
    params = dict(batch=k, delta_sha256=hashlib.sha256(delta.tobytes()).hexdigest(),
                  shape=list(delta.shape), brot=brot, lowbits=4, trials=trials,
                  seed=k, output_permutation=perm, output_groups=sizes,
                  source_sha256=source_hash)
    saved = screen / f'plan-{k}.json'
    reused = False
    if saved.exists():
        record = json.loads(saved.read_text())
        if record['parameters'] != params:
            raise ValueError(f'Checkpoint recipe mismatch for batch {k}')
        terms = record['terms']
        reused = True
    else:
        C = tq.anf_tensor(delta, brot, 4)
        Cp = C[:, :, perm] if perm is not None else C
        terms = tq.shared(Cp, sizes, trials=trials, seed=k, groups=tq.low_groups(4))
        if perm is not None:
            terms = [(a,b,c,d,sum(1 << perm[i] for i in tq._bits(s)))
                     for a,b,c,d,s in terms]
        record = dict(parameters=params, terms=terms)
        tmp = saved.with_suffix('.tmp')
        tmp.write_text(json.dumps(record)+'\n'); tmp.replace(saved)
    circuit = tq.build_circuit(delta, terms, nsel, brot, 4,
                               groups=tq.low_groups(4), scratch=True)
    path = screen / f'angle_k_{k}.kmb'
    circuit.to_file(path, format='kmb')
    result = dict(batch=k, products=len(terms), qubits=circuit.num_qubits,
                  toffolis=int(circuit.operation_statistics().num_toffoli_like),
                  sha256=sha256(path), elapsed_seconds=time.monotonic()-start,
                  reused_plan=reused, exact_mixed_tensor=True)
    (screen / f'batch-{k}.json').write_text(json.dumps(result, indent=2)+'\n')
    signal.setitimer(signal.ITIMER_REAL, 0)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-bank', type=Path, required=True)
    p.add_argument('--source-sha256', required=True, help='Reviewed tensorqrom.py digest')
    p.add_argument('--source-npz', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--trials', type=int, default=6)
    p.add_argument('--expected-family-sha256')
    p.add_argument('--stop-by', required=True)
    args = p.parse_args(); start = time.monotonic()
    stop = datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None or stop <= datetime.now(timezone.utc):
        raise ValueError('A future timezone-aware deadline is required')
    if not 1 <= args.jobs <= 19 or args.trials < 1:
        raise ValueError('Invalid worker or trial count')
    bank = args.source_bank.resolve()
    if sha256(bank / 'tensorqrom.py') != args.source_sha256:
        raise ValueError('Source module differs from reviewed pin')
    source_files = [dict(path=str(f.relative_to(bank)), sha256=sha256(f))
                    for f in sorted(bank.rglob('*.py'))]
    tq = source_module(bank)
    from fourqrom import batch_deltas
    with np.load(args.source_npz, allow_pickle=False) as z:
        arrays = {k:np.array(z[k]) for k in z.files}
    words = arrays['angle_words']; brot = int(arrays['brot'])
    if words.shape != (1363, 75) or brot != 8:
        raise ValueError('This reviewed route requires the 1363x75 compact 8-bit family')
    width = full_cache_width(len(words), 5, brot, 4)
    if width <= 128:
        raise ValueError('Full-cache branch is feasible; this shortcut does not apply')
    screen = args.output_dir.parent / 'screen'; screen.mkdir(exist_ok=True)
    coded, coded2 = (set(map(int, arrays.get(key, []))) for key in ('coded','coded2'))
    tasks = []
    for k, delta in enumerate(batch_deltas(words, 5)):
        cw = [i for i in range(5) if 5*k+i in coded and (k==0 or 5*(k-1)+i in coded)]
        cw2 = [i for i in range(5) if 5*k+i in coded2 and (k==0 or 5*(k-1)+i in coded2)]
        perm, sizes = tq.coded_layout(cw, 5, brot, cw2)
        if cw:delta = tq.pad_affine(delta, cw, cw2)
        tasks.append((bank,screen,k,delta,11,brot,args.trials,perm,sizes,args.source_sha256,stop.timestamp()))
    rows = []
    with ProcessPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(solve_task, task) for task in tasks]
        for future in as_completed(futures):
            row = future.result(); rows.append(row); print(json.dumps(row), flush=True)
    rows.sort(key=lambda a:a['batch'])
    with output_workspace(args.output_dir) as (output, stage):
        np.savez(stage / 'submission.npz', **{k:arrays[k] for k in
                 ('U','W','H2_I','H1_I','Hsym_lower','tree_edges','angle_words')})
        for k in range(15):shutil.copy2(screen / f'angle_k_{k}.kmb', stage / f'angle_k_{k}.kmb')
        family_hash = hashlib.sha256(''.join(f'{f.name}\t{sha256(f)}\n'
                         for f in sorted(stage.iterdir())).encode()).hexdigest()
        if args.expected_family_sha256 and family_hash != args.expected_family_sha256:
            raise ValueError(f'Family hash mismatch: {family_hash}')
        inputs = load_inputs(stage / 'submission.npz')
        metrics = evaluate_words(inputs, words, arrays['tree_edges'], brot)
        circuits = load_circuits(stage); stats = circuit_costs(circuits)
        resources = resource_costs(inputs,circuits,brot,2*sum(s['max_magic'] for s in stats))
        result = dict(metrics=metrics,resources=resources,
                      passes_numerical_gates=passes_accuracy(metrics),
                      conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'])
    if source_files != [dict(path=str(f.relative_to(bank)),sha256=sha256(f)) for f in sorted(bank.rglob('*.py'))]:
        raise ValueError('Source bank changed during replay')
    code = output.parent / 'code'
    shutil.copytree(bank,code / 'source-bank',dirs_exist_ok=True)
    shutil.copy2(__file__,code / Path(__file__).name)
    report = dict(kind='compact_factor_grouped_source_replay',official_validation=False,
                  source_bank=str(bank),source_input=str(args.source_npz.resolve()),
                  input_sha256=sha256(args.source_npz),source_files=source_files,
                  generator_sha256=sha256(Path(__file__)),argv=sys.argv,
                  python_executable=sys.executable,python_prefix=sys.prefix,
                  omitted_branch=dict(full_cache_qubits=width,cap=128,reason='Static allocation exceeds cap; grouped RNG restarts from identical batch seed'),
                  rows=rows,screen=result,family_sha256=family_hash,
                  elapsed_seconds=time.monotonic()-start,
                  artifacts=[dict(path=f.name,sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent / 'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('FINAL '+json.dumps(result),flush=True)


if __name__ == '__main__':
    main()

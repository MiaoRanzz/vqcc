"""Reproduce a reviewed C43 source bank with explicit input and source pins.

This adapts Atakan Aldemir's source-only replay, retaining its exact emitter,
plans and Marculera factor lineage. No upstream orchestration is executed.
The unchanged full official pipeline remains the acceptance gate.
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
from generate import output_workspace, sha256
import numpy as np
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-bank', type=Path, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--brot', type=int, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    start = time.monotonic()
    bank = args.source_bank.resolve()
    manifest_path = bank / 'MANIFEST.json'
    if sha256(manifest_path) != args.manifest_sha256:
        raise ValueError('Source-bank manifest differs from reviewed pin')
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest['files'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or sha256(bank / rel) != digest:
            raise ValueError(f'Unpinned or unsafe source: {name}')
    # This emitter was inspected independently of the notebook entrypoint.
    spec = importlib.util.spec_from_file_location('reviewed_c43_emitter', bank / 'src/emitter.py')
    emitter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emitter)
    with np.load(bank / 'factorization.npz', allow_pickle=False) as z:
        words = z['angle_words'].copy()
        brot = args.brot
        edges = z['tree_edges'].copy()
    if words.shape != (1363, 75) or brot != 8:
        raise ValueError('This reviewed route requires the C43 1363x75 8-bit table')
    delta = words.reshape(len(words), 15, 5).copy()
    delta[:, 1:] ^= delta[:, :-1].copy()
    rows = []
    with output_workspace(args.output_dir) as (output, stage):
        shutil.copy2(bank / 'factorization.npz', stage / 'submission.npz')
        for k in range(15):
            plan = json.loads((bank / f'plans/batch_{k}.json').read_text())
            circuit, detail = emitter.emit_streamed(plan['products'], delta[:, k])
            name = f'angle_k_{k}.kmb'
            circuit.to_file(stage / name, format='kmb')
            digest = sha256(stage / name)
            if digest != manifest['expected_circuits'][name]:
                raise ValueError(f'Source replay did not match pinned circuit {name}')
            rows.append(dict(batch=k, qubits=circuit.num_qubits,
                             toffolis=int(circuit.operation_statistics().num_toffoli_like),
                             low_peak=detail['low_peak'], sha256=digest))
        inputs = load_inputs(stage / 'submission.npz')
        metrics = evaluate_words(inputs, words, edges, brot)
        circuits = load_circuits(stage)
        stats = circuit_costs(circuits)
        resources = resource_costs(inputs, circuits, brot, 2*sum(s['max_magic'] for s in stats))
        screen = dict(metrics=metrics, resources=resources,
                      passes_numerical_gates=passes_accuracy(metrics),
                      conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'])
    code = output.parent / 'code'
    shutil.copytree(bank, code / 'source-bank', dirs_exist_ok=True)
    shutil.copy2(Path(__file__), code / Path(__file__).name)
    report = dict(kind='pinned_c43_source_rebuild', official_validation=False,
                  source_bank=str(bank), source_manifest_sha256=args.manifest_sha256,
                  generator_sha256=sha256(Path(__file__)), argv=sys.argv,
                  python_executable=sys.executable, python_prefix=sys.prefix,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  reproduction='Exact source/plans to all fifteen loader hashes; fixed trained factor copied. Full training dependencies are not all portable.',
                  rows=rows, screen=screen, elapsed_seconds=time.monotonic()-start,
                  artifacts=[dict(path=f.name, sha256=sha256(f)) for f in sorted(output.iterdir())])
    (output.parent / 'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(screen=screen, elapsed_seconds=report['elapsed_seconds'])), flush=True)


if __name__ == '__main__':
    main()

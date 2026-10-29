"""Deterministic resource screening; no simulation or official PASS is claimed."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'kickmix'), str(ROOT / 'verifiers'), str(ROOT / 'generators')]
import numpy as np
from dfthcsos_anf import build_anf_family
from dfthcsos_prefix import workspace_bits
from dfthcsos.scoreinfra.circuits import circuit_costs
from dfthcsos.verify import resource_costs
from generate import check_destination, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-npz', type=Path, required=True)
    parser.add_argument('--incumbent-report', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = check_destination(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    incumbent = json.loads(args.incumbent_report.read_text())
    with np.load(args.source_npz, allow_pickle=False) as data:
        words = np.array(data['angle_words'])
        inputs = SimpleNamespace(w=np.array(data['W']), num_orbitals=data['U'].shape[-1])
    brot = int(incumbent['brot'])
    n = (len(words) - 1).bit_length()
    trials = []
    for batch, prefix in [(8, 2), (8, 3), (8, 4), (9, 4), (9, 5), (9, 6), (9, 7), (9, 8), (9, 9)]:
        params = dict(brot=brot, source_brot=brot, batch_size=batch, prefix_bits=prefix, lookup_family='anf')
        estimated_width = n + batch * brot + workspace_bits(n, prefix)
        record = dict(parameters=params, estimated_angle_qubits=estimated_width, official_validation=False)
        if estimated_width > 128:
            record.update(status='cap_rejected', reason='ANGLE qubits exceed 128')
        else:
            started = time.monotonic()
            circuits = build_anf_family(words, brot, batch, prefix)
            stats = circuit_costs(circuits)
            per_pass = sum(item['max_magic'] for item in stats)
            resources = resource_costs(inputs, circuits, brot, 2 * per_pass)
            estimate = incumbent['lambda_eff'] * resources['toffoli'] * resources['qubits']
            record.update(status='resource_screened', resources=resources, circuits=stats,
                          conditional_score_estimate=estimate,
                          relative_to_incumbent=estimate / incumbent['score'],
                          elapsed_seconds=time.monotonic() - started)
            del circuits
        trials.append(record)
        with (output / 'trials.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        print(json.dumps(record), flush=True)
    feasible = [t for t in trials if t['status'] == 'resource_screened']
    best = min(feasible, key=lambda t: t['conditional_score_estimate'])
    # Keep the lower-width ANGLE alternatives, even when full-block Q is fixed
    # by PREPARE. They can support future compositions under the hard cap.
    tradeoffs = [t for t in feasible if not any(
        u['conditional_score_estimate'] <= t['conditional_score_estimate'] and
        u['resources']['angles_qubits'] <= t['resources']['angles_qubits'] and
        (u['conditional_score_estimate'] < t['conditional_score_estimate'] or
         u['resources']['angles_qubits'] < t['resources']['angles_qubits']) for u in feasible)]
    summary = dict(kind='static_resource_screen', official_validation=False,
        note='Scores conditional on exact words and valid measurement cleanup; not official evidence.',
        created_at=datetime.now(timezone.utc).isoformat(), python_executable=sys.executable,
        source_npz=str(args.source_npz.resolve()), source_npz_sha256=sha256(args.source_npz),
        incumbent_report=str(args.incumbent_report.resolve()), incumbent_report_sha256=sha256(args.incumbent_report),
        source_hashes={p.name:sha256(p) for p in (Path(__file__), ROOT/'generators/dfthcsos_anf.py', ROOT/'generators/dfthcsos_prefix.py')},
        best=best, retained_tradeoffs=tradeoffs, trials=trials)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (output / 'recommended-params.json').write_text(json.dumps(best['parameters'], indent=2) + '\n')


if __name__ == '__main__':
    main()

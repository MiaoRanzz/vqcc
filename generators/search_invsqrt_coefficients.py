"""Bounded coefficient/precision search; all reports are screening, not validation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'kickmix'), str(ROOT / 'verifiers'), str(ROOT / 'generators')]
from generate import numeric_screen
from invsqrt.nr_reference_circuit import build_nr_circuit, relative_error
from invsqrt.verify_submission_invsqrt import N_P, ProblemSpecInvSqrt
from invsqrt_coefficients import TablePrecision, tune_table
from search_invsqrt_precision import boundary_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--stop-by', type=datetime.fromisoformat, required=True)
    parser.add_argument('--full-limit', type=int, default=12)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    xs = boundary_inputs(ProblemSpecInvSqrt.for_n_p(N_P).max_x)
    survivors, full, tables = [], [], []
    metadata = dict(official_validation=False, python_executable=sys.executable,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (Path(__file__), ROOT/'generators/invsqrt_coefficients.py',
                                  ROOT/'verifiers/invsqrt/nr_reference_circuit.py', ROOT/'verifiers/LICENSE.txt')},
                    grid=dict(delta_bits=[11,12,13,14], coef_bits=[14,15,16],
                              square_bits=[27,28,29], product_bits=[27,28,29], result_bits=[27,28,29]),
                    sample_inputs=len(xs), stop_by=args.stop_by.isoformat())
    (args.output_dir/'search.json').write_text(json.dumps(metadata, indent=2)+'\n')
    with (args.output_dir/'trials.jsonl').open('x', buffering=1) as stream:
        for coef, delta in itertools.product((14,15,16), (11,12,13,14)):
            if (args.stop_by-datetime.now(timezone.utc)).total_seconds() < 120:
                break
            table, history = tune_table(delta, coef)
            tables.append(dict(delta_bits=delta,coef_bits=coef,table=table,history=history))
            (args.output_dir/'tables.json').write_text(json.dumps(tables,indent=2)+'\n')
            print(json.dumps(tables[-1]),flush=True)
            for square, product, result in itertools.product((27,28,29), repeat=3):
                prec=TablePrecision(coefficient_table=table,delta_bits=delta,coef_bits=coef,
                                    square_bits=square,product_bits=product,result_bits=result)
                errors=relative_error(N_P,prec,xs)
                record=dict(parameters={**asdict(prec),'coefficient_table':table},
                            sample_worst_ratio=float(errors.max()*2**24),
                            sample_worst_x=int(xs[errors.argmax()]),official_validation=False)
                if record['sample_worst_ratio'] < 1:
                    circuit=build_nr_circuit(N_P,prec=prec)
                    record.update(qubits=circuit.num_qubits,
                                  toffolis=int(circuit.operation_statistics().num_toffoli_like))
                    record['cost_lower_bound']=record['qubits']*record['toffolis']
                    survivors.append(record)
                stream.write(json.dumps(record)+'\n')
        for record in sorted(survivors,key=lambda r:r['cost_lower_bound'])[:args.full_limit]:
            if (args.stop_by-datetime.now(timezone.utc)).total_seconds() < 60:
                break
            result={**record,'full_domain':numeric_screen(TablePrecision(**record['parameters']))}
            full.append(result)
            print(json.dumps(result),flush=True)
            (args.output_dir/'full-domain.json').write_text(json.dumps(full,indent=2)+'\n')
    passing=[r for r in full if r['full_domain']['passes_model_tolerance']]
    if passing:
        best=min(passing,key=lambda r:r['cost_lower_bound'])
        (args.output_dir/'best-params.json').write_text(json.dumps(best['parameters'],indent=2)+'\n')
    metadata.update(elapsed_seconds=time.monotonic()-started,survivors=len(survivors),full_evaluated=len(full),full_passed=len(passing))
    (args.output_dir/'search.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata),flush=True)


if __name__=='__main__':
    main()

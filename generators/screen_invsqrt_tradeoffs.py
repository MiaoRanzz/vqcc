"""Compare retained tables using exact model margin and static circuit resources.

This is screening only: it does not simulate register/phase restoration. The
official full verifier remains necessary even if the estimated cost agrees.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'kickmix'),str(ROOT/'verifiers'),str(ROOT/'generators')]
import numpy as np
from invsqrt.nr_reference_circuit import build_nr_circuit, fixed_point_model
from invsqrt.verify_submission_invsqrt import N_P, ProblemSpecInvSqrt, reference_values, rotation_t_count
from invsqrt_coefficients import TablePrecision


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-domain',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stop-by',type=datetime.fromisoformat,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    started=time.monotonic()
    spec=ProblemSpecInvSqrt.for_n_p(N_P)
    xs=np.arange(1,spec.max_x+1,dtype=np.uint64)
    target,tol=reference_values(spec,xs)
    rows=[]
    for record in json.loads(args.full_domain.read_text()):
        if not record['full_domain']['passes_model_tolerance']:
            continue
        if (args.stop_by-datetime.now(timezone.utc)).total_seconds()<60:
            break
        prec=TablePrecision(**record['parameters'])
        margin=1<<64
        for start in range(0,len(xs),65536):
            subset=xs[start:start+65536]
            value=fixed_point_model(N_P,prec,subset).astype(np.uint64)
            phase=value << np.uint64(64-prec.output_bits(N_P))
            used=np.abs((phase-target[start:start+len(subset)]).view(np.int64)).view(np.uint64)
            allowed=tol[start:start+len(subset)]
            if np.any(used>=allowed):
                raise ValueError('No positive model phase margin')
            margin=min(margin,int((allowed-used).min()))
        circuit=build_nr_circuit(N_P,prec=prec)
        stats=circuit.operation_statistics()
        rotations=int(stats.num_z_pow(min_clifford_hierarchy_level=4))
        t_base=int(stats.num_t_like)
        eps=math.pi*margin/2**64/rotations
        cost=circuit.num_qubits*(int(stats.num_toffoli_like)+(t_base+rotations*rotation_t_count(eps))/4)
        rows.append({**record,'model_min_margin_units_2neg64':margin,'estimated_rotation_eps':eps,
                     'estimated_cost_including_rotations':cost,'official_validation':False})
    rows.sort(key=lambda r:r['estimated_cost_including_rotations'])
    pareto=[r for r in rows if not any(
        s['estimated_cost_including_rotations']<=r['estimated_cost_including_rotations']
        and s['full_domain']['error_over_tolerance']<=r['full_domain']['error_over_tolerance']
        and (s['estimated_cost_including_rotations']<r['estimated_cost_including_rotations']
             or s['full_domain']['error_over_tolerance']<r['full_domain']['error_over_tolerance']) for s in rows)]
    result=dict(official_validation=False,elapsed_seconds=time.monotonic()-started,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                input_sha256=hashlib.sha256(args.full_domain.read_bytes()).hexdigest(),
                python_executable=sys.executable,ranked=rows,retained_pareto=pareto)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([{'parameters':r['parameters'],'cost':r['estimated_cost_including_rotations'],
                      'ratio':r['full_domain']['error_over_tolerance']} for r in rows],indent=2))


if __name__=='__main__':
    main()

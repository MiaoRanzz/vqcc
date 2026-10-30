"""Compare exact-word ANF layouts using the complete official resource model.

No circuit simulation is performed. Numerical gates must be screened separately.
"""
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
sys.path[:0] = [str(ROOT/'kickmix'), str(ROOT/'verifiers'), str(ROOT/'generators')]
import numpy as np
from dfthcsos_anf import build_anf_family
from dfthcsos_prefix import workspace_bits
from dfthcsos.scoreinfra.circuits import circuit_costs
from dfthcsos.verify import resource_costs, passes_accuracy
from generate import check_destination, sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-npz', type=Path, required=True)
    p.add_argument('--metrics-json', type=Path, required=True)
    p.add_argument('--brot', type=int, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--stop-by', type=datetime.fromisoformat, required=True)
    args=p.parse_args();out=check_destination(args.output_dir);out.mkdir(parents=True,exist_ok=False)
    numerical=json.loads(args.metrics_json.read_text())
    if numerical['source_sha256'] != sha256(args.source_npz):
        raise ValueError('Numerical screen does not match factorization')
    metrics=numerical['metrics']
    if not passes_accuracy(metrics):
        raise ValueError('Numerical gates failed')
    with np.load(args.source_npz,allow_pickle=False) as d:
        words=np.array(d['angle_words']);inputs=SimpleNamespace(w=np.array(d['W']),num_orbitals=d['U'].shape[-1])
    n=(len(words)-1).bit_length();trials=[]
    for batch in (8,9,10):
        for prefix in range(2,n+1):
            if (args.stop_by-datetime.now(timezone.utc)).total_seconds()<60:break
            params=dict(brot=args.brot,source_brot=args.brot,batch_size=batch,prefix_bits=prefix,lookup_family='anf')
            width=n+batch*args.brot+workspace_bits(n,prefix)
            record=dict(parameters=params,estimated_angle_qubits=width,official_validation=False)
            if width>128:record['status']='cap_rejected'
            else:
                t=time.monotonic();circuits=build_anf_family(words,args.brot,batch,prefix)
                stats=circuit_costs(circuits);resources=resource_costs(inputs,circuits,args.brot,2*sum(s['max_magic'] for s in stats))
                record.update(status='resource_screened',resources=resources,
                    conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'],elapsed_seconds=time.monotonic()-t)
                del circuits
            trials.append(record)
            with (out/'trials.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
            print(json.dumps(record),flush=True)
    valid=[t for t in trials if t['status']=='resource_screened']
    best=min(valid,key=lambda t:t['conditional_cost'])
    retained=[t for t in valid if not any(u['conditional_cost']<=t['conditional_cost'] and u['estimated_angle_qubits']<=t['estimated_angle_qubits'] and (u['conditional_cost']<t['conditional_cost'] or u['estimated_angle_qubits']<t['estimated_angle_qubits']) for u in valid)]
    report=dict(official_validation=False,source_npz=str(args.source_npz.resolve()),source_sha256=sha256(args.source_npz),metrics=metrics,
        python_executable=sys.executable,source_hashes={str(p.relative_to(ROOT)):sha256(p) for p in [Path(__file__),ROOT/'generators/dfthcsos_anf.py',ROOT/'generators/dfthcsos_prefix.py']},
        trials=trials,best=best,retained_tradeoffs=retained)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'recommended-params.json').write_text(json.dumps(best['parameters'],indent=2)+'\n')


if __name__=='__main__':main()

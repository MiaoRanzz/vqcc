"""Bounded exact output-basis search on a pinned compact C42 ANGLE recipe.

Apply deterministic invertible XOR shears before grouped tensor decomposition.
Undo their action on each product's fanout mask; the original emitter recomputes
pure Clifford corrections from the original delta. No output-register basis
change or extra workspace is needed. Preserve the signed-gauge borrowing contract.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import signal
import sys
import time
import numpy as np
from generate import ROOT, output_workspace, sha256
from dfthcsos_compact_rebuild import source_module
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy, resource_costs
from dfthcsos.scoreinfra.circuits import load_circuits, circuit_costs, register_layout
import kickmix as km

VARIANTS = ('adjacent_bits', 'adjacent_words', 'prefix_words', 'butterfly_words')


def shears(variant, words=5, bits=7):
    """(control, target) elementary output XORs; coded bit zero stays isolated."""
    if variant == 'adjacent_bits':
        return [(j*bits+b+1, j*bits+b) for j in range(words) for b in range(1,bits-1)]
    if variant == 'adjacent_words':
        return [((j-1)*bits+b,j*bits+b) for j in range(words-1,0,-1) for b in range(1,bits)]
    if variant == 'prefix_words':
        return [((j-1)*bits+b,j*bits+b) for j in range(1,words) for b in range(1,bits)]
    if variant == 'butterfly_words':
        return [(j*bits+b,(j+stride)*bits+b) for stride in (1,2,4)
                for j in range(0,words,2*stride) if j+stride<words for b in range(1,bits)]
    raise ValueError(variant)


def transform_tensor(tensor, operations):
    out=tensor.copy()
    for control,target in operations:out[...,target]^=out[...,control]
    return out


def inverse_mask(mask, operations):
    for control,target in reversed(operations):
        if mask >> control & 1:mask ^= 1 << target
    return mask


def signed_xor_check(circuit, delta, seed=20261101):
    """All legal addresses, arbitrary signed-gauge words, two passes and phases."""
    layout=register_layout([circuit]);n=len(delta)
    addresses=np.arange(n);rng=np.random.default_rng(seed)
    targets=rng.integers(0,128,(n,delta.shape[1]));targets|=(targets & 64)<<1
    bits=lambda v,w:((v[None,:]>>np.arange(w)[:,None])&1).astype(bool)
    sim=km.Simulator(batch_size=n,seed=seed);sim.use_same_registers_as(circuit)
    ab=bits(addresses,len(layout.selection));sim.write_across_shots(layout.selection,ab)
    for j,word in enumerate(layout.words):sim.write_across_shots(word,bits(targets[:,j],8))
    scratch=km.array([km.q(i) for i in range(circuit.num_qubits) if i not in layout.public_qubits])
    for expected in (targets ^ delta,targets):
        sim.do(circuit)
        np.testing.assert_array_equal(sim.read_across_shots(layout.selection),ab)
        for j,word in enumerate(layout.words):np.testing.assert_array_equal(sim.read_across_shots(word),bits(expected[:,j],8))
        if sim.read_across_shots(scratch).any():raise AssertionError('dirty scratch')
        if any(sim.read_shot_phase(i)%2 for i in range(n)):raise AssertionError('nonzero phase')
    return dict(addresses=n,applications=2*n,seed=seed,domain='arbitrary signed-gauge targets',status='PASS')


def worker(task):
    bank,screen,k,variant,delta,real_count,perm,sizes,trials,deadline=task
    def expire(*_):raise TimeoutError('output-basis deadline')
    signal.signal(signal.SIGALRM,expire)
    signal.setitimer(signal.ITIMER_REAL,max(.01,deadline-time.time()))
    start=time.monotonic();tq=source_module(bank);ops=shears(variant)
    C=tq.anf_tensor(delta,8,4);changed=transform_tensor(C,ops)
    np.testing.assert_array_equal(transform_tensor(changed,list(reversed(ops))),C)
    Cp=changed[:,:,perm] if perm is not None else changed
    saved=screen/f'batch{k}-{variant}-terms.json'
    reused=saved.exists()
    if reused:
        terms=json.loads(saved.read_text())
    else:
        terms=tq.shared(Cp,sizes,trials=trials,seed=k,groups=tq.low_groups(4))
        if perm is not None:terms=[(a,b,c,d,sum(1<<perm[i] for i in tq._bits(s))) for a,b,c,d,s in terms]
        terms=[(a,b,c,d,inverse_mask(s,ops)) for a,b,c,d,s in terms]
    np.testing.assert_array_equal(tq.mixed_of(terms,C.shape[0]-1,C.shape[1]-1,C.shape[2]),C[1:,1:])
    circuit=tq.build_circuit(delta,terms,11,8,4,groups=tq.low_groups(4),scratch=True)
    path=screen/f'batch{k}-{variant}.kmb';circuit.to_file(path,format='kmb')
    (screen/f'batch{k}-{variant}-terms.json').write_text(json.dumps(terms)+'\n')
    stats=dict(circuit.operation_statistics())
    check=signed_xor_check(circuit,delta[:real_count])
    row=dict(batch=k,variant=variant,reused_plan=reused,shears=ops,products=len(terms),qubits=circuit.num_qubits,
             toffolis=float(circuit.operation_statistics().num_toffoli_like),statistics=stats,sha256=sha256(path),
             circuit=str(path),exact_tensor=True,signed_target_check=check,
             elapsed_seconds=time.monotonic()-start)
    (screen/f'batch{k}-{variant}.json').write_text(json.dumps(row,indent=2)+'\n')
    signal.setitimer(signal.ITIMER_REAL,0)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--recipe-npz',type=Path,required=True)
    p.add_argument('--source-bank',type=Path,required=True)
    p.add_argument('--source-sha256',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--batches',type=int,nargs='+',default=[4])
    p.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    p.add_argument('--trials',type=int,default=6)
    p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--stop-by',required=True)
    args=p.parse_args();start=time.monotonic()
    stop=datetime.fromisoformat(args.stop_by)
    if stop.tzinfo is None or stop<=datetime.now(timezone.utc):raise ValueError('future aware deadline required')
    if not 1<=args.jobs<=19 or args.trials<1:raise ValueError('invalid resource bound')
    bank=args.source_bank.resolve()
    if sha256(bank/'tensorqrom.py')!=args.source_sha256:raise ValueError('source pin mismatch')
    source_files=[dict(path=str(f.relative_to(bank)),sha256=sha256(f)) for f in sorted(bank.rglob('*.py'))]
    tq=source_module(bank)
    from fourqrom import batch_deltas
    with np.load(args.recipe_npz,allow_pickle=False) as z:recipe={k:np.array(z[k]) for k in z.files}
    with np.load(args.parent_output/'submission.npz',allow_pickle=False) as z:words=np.array(z['angle_words'])
    np.testing.assert_array_equal(words,recipe['angle_words'])
    if words.shape!=(1363,75) or int(recipe['brot'])!=8:raise ValueError('requires reviewed C42 recipe')
    if any(k<0 or k>=15 for k in args.batches):raise ValueError('batch index')
    candidate=args.output_dir.parent;screen=candidate/'screen';screen.mkdir(exist_ok=True)
    coded,coded2=(set(map(int,recipe.get(key,[]))) for key in ('coded','coded2'))
    tasks=[];baselines={}
    for k,delta in enumerate(batch_deltas(words,5)):
        if k not in args.batches:continue
        cw=[i for i in range(5) if 5*k+i in coded and (k==0 or 5*(k-1)+i in coded)]
        cw2=[i for i in range(5) if 5*k+i in coded2 and (k==0 or 5*(k-1)+i in coded2)]
        if cw2:raise ValueError('bit-one coding requires a different preserved subspace')
        perm,sizes=tq.coded_layout(cw,5,8,cw2)
        if cw:delta=tq.pad_affine(delta,cw,cw2)
        circ=km.Circuit.from_file(args.parent_output/f'angle_k_{k}.kmb')
        baselines[k]=dict(qubits=circ.num_qubits,toffolis=float(circ.operation_statistics().num_toffoli_like),sha256=sha256(args.parent_output/f'angle_k_{k}.kmb'))
        tasks += [(bank,screen,k,v,delta,len(words),perm,sizes,args.trials,stop.timestamp()) for v in args.variants]
    plan=dict(batches=args.batches,variants=args.variants,trials=args.trials,seeds='batch index',jobs=args.jobs,
              baselines=baselines,stop_by=args.stop_by,
              source_files=source_files,recipe_sha256=sha256(args.recipe_npz),
              shears={v:shears(v) for v in args.variants})
    if (screen/'plan.json').exists():
        previous=json.loads((screen/'plan.json').read_text())
        for key in ('batches','variants','trials','seeds','baselines','source_files','recipe_sha256','shears'):
            if json.dumps(previous.get(key),sort_keys=True)!=json.dumps(plan[key],sort_keys=True):raise ValueError('saved recipe differs: '+key)
    (screen/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    rows=[]
    with ProcessPoolExecutor(args.jobs) as pool:
        for future in as_completed([pool.submit(worker,t) for t in tasks]):
            row=future.result();rows.append(row);print(json.dumps(row),flush=True)
    selected={}
    for k in args.batches:
        eligible=[r for r in rows if r['batch']==k and r['qubits']<=128 and r['toffolis']<baselines[k]['toffolis']]
        if eligible:selected[k]=min(eligible,key=lambda r:(r['toffolis'],r['variant']))
    result=None
    if selected:
        with output_workspace(args.output_dir) as (output,stage):
            for f in args.parent_output.iterdir():shutil.copy2(f,stage/f.name)
            for k,r in selected.items():shutil.copy2(r['circuit'],stage/f'angle_k_{k}.kmb')
            inputs=load_inputs(stage/'submission.npz');metrics=evaluate_words(inputs,words,recipe['tree_edges'],8)
            circuits=load_circuits(stage);stats=circuit_costs(circuits)
            resources=resource_costs(inputs,circuits,8,2*sum(s['max_magic'] for s in stats))
            result=dict(metrics=metrics,resources=resources,passes_numerical_gates=passes_accuracy(metrics),
                        conditional_cost=metrics['lambda_eff']*resources['toffoli']*resources['qubits'])
    if source_files != [dict(path=str(f.relative_to(bank)),sha256=sha256(f)) for f in sorted(bank.rglob('*.py'))]:raise ValueError('source changed')
    code=candidate/'code';shutil.copytree(bank,code/'source-bank',dirs_exist_ok=True)
    for f in [Path(__file__),Path(__file__).with_name('dfthcsos_compact_rebuild.py'),Path(__file__).with_name('generate.py')]:shutil.copy2(f,code/f.name)
    for f in bank.parent.glob('LICENSE*'):shutil.copy2(f,code/f.name)
    report=dict(kind='exact_output_basis_grouped_tensor',official_validation=False,argv=sys.argv,
                parameters=plan,parent_output=str(args.parent_output.resolve()),
                parent_npz_sha256=sha256(args.parent_output/'submission.npz'),recipe_npz=str(args.recipe_npz.resolve()),
                recipe_sha256=sha256(args.recipe_npz),source_files=source_files,generator_sha256=sha256(Path(__file__)),
                python_executable=sys.executable,python_prefix=sys.prefix,results=sorted(rows,key=lambda r:(r['batch'],r['variant'])),
                selected=selected,screen=result,elapsed_seconds=time.monotonic()-start,
                decision='plausible_gain_requires_full_verification' if selected else 'no_lower_toffoli_count',
                clifford_repair='inverse masks absorbed into product fanout; pure corrections recomputed from original delta')
    if selected:report['artifacts']=[dict(path=f.name,sha256=sha256(f)) for f in sorted(args.output_dir.iterdir())]
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print('FINAL '+json.dumps(report),flush=True)


if __name__=='__main__':main()

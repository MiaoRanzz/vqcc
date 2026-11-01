"""Exact legal-address product dependencies in a pinned compact ANGLE family.

Screen only: a dependency would still need a circuit emitter and full official
verification. All pure low/high monomials are admitted to the linear span, so
absence of dependencies also excludes elimination using any subset of them.
Changing the nonlinear product basis is outside this test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bits(value):
    while value:
        bit = value & -value
        yield bit.bit_length()-1
        value ^= bit


def screen(terms, rows):
    low = [sum(1 << a for a in range(rows) if a & m == m) for m in range(16)]
    high = [sum(1 << a for a in range(rows) if (a >> 4) & m == m)
            for m in range((rows+15)//16)]
    def form(value, tables):
        result = 0
        for k in bits(value): result ^= tables[k+1]
        return result
    basis = {}
    def add(value, identity):
        while value:
            pivot = value.bit_length()-1
            if pivot not in basis:
                basis[pivot] = value, identity
                return None
            previous, combo = basis[pivot]
            value ^= previous; identity ^= combo
        return identity
    pure = low+high[1:]
    for i, value in enumerate(pure):
        if add(value, 1 << i) is not None:
            raise ValueError('Dependent pure basis; unsupported address domain')
    relations = []
    for i, (a1,b1,a2,b2,fanout) in enumerate(terms):
        value = (form(a1,low)^form(b2,high)) & (form(a2,low)^form(b1,high))
        relation = add(value,1 << (len(pure)+i))
        if relation is not None:
            relations.append(dict(product=i,relation=hex(relation),fanout=fanout))
    return dict(products=len(terms),pure_dimension=len(pure),
                independent_products=len(basis)-len(pure),relations=relations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-candidate',type=Path,required=True)
    parser.add_argument('--parent-output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args(); start = time.monotonic()
    if args.report.exists(): parser.error('Report must be new')
    old = args.plan_candidate/'output'; parent = args.parent_output
    with np.load(old/'submission.npz',allow_pickle=False) as a, np.load(parent/'submission.npz',allow_pickle=False) as b:
        for name in ['angle_words','tree_edges']:
            if not np.array_equal(a[name],b[name]): raise ValueError('Plan family differs from parent')
        rows = len(b['angle_words'])
    generation = json.loads((args.plan_candidate/'generation.json').read_text())
    loaders = {f.name:sha(f) for f in old.glob('angle_k_*.kmb')}
    if len(loaders)!=15 or any(sha(parent/name)!=digest for name,digest in loaders.items()):
        raise ValueError('Recorded plan family does not reproduce these fifteen loaders')
    results = []
    for k in range(15):
        path = args.plan_candidate/'screen'/f'plan-{k}.json'
        plan = json.loads(path.read_text())
        if plan['parameters']['lowbits']!=4: raise ValueError('Only four low address bits supported')
        results.append(dict(batch=k,plan_sha256=sha(path),parameters=plan['parameters'],
                            **screen(plan['terms'],rows)))
    report = dict(kind='exact_compact_product_span_screen',official_validation=False,
        rows=rows,plan_candidate=str(args.plan_candidate.resolve()),parent_output=str(parent.resolve()),
        generator_sha256=sha(Path(__file__)),plan_generation_sha256=sha(args.plan_candidate/'generation.json'),
        plan_generation_recipe=generation['argv'],identical_loader_hashes=loaders,same_words=True,same_tree=True,
        batches=results,removed_opportunities=sum(len(x['relations']) for x in results),elapsed_seconds=time.monotonic()-start)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['batches','identical_loader_hashes','plan_generation_recipe']}))


if __name__=='__main__':main()

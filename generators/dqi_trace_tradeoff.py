"""Reproducible workspace/trace tradeoff on pinned SomeJoint q22 source.

Only exact arithmetic selection guards and the subfield trace dimension change.
The ordinary return stores 12-k norm coordinates and reconstructs the k-bit
trace using the supplied dual-basis product. k=2,3,6 are the source's supported
exact even-relative-degree traces, so trace(1)=0 preserves zero completion.
This experiment does not infer correctness or cost from a chosen circuit hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from profile_dqi_source import digest


PINNED_PARENT = '7dcb493e9de4bee7317b27772724ff778070f1d84d13408c853e2f0bab29dd56'
SOURCE_REL = Path('blocks/dqi/pro-q22-898/source')


def transform(root, ceiling, trace_bits):
    path = root / SOURCE_REL / 'exp/next/a13/decode_inv72_cap898.py'
    old = path.read_text()
    replacements = [
        ('dispatch.install(16,898)', f'dispatch.install(16,{ceiling})'),
        ("pairs=('first','second'),ceiling=898", f"pairs=('first','second'),ceiling={ceiling}"),
        ('b.num_allocated_qubits>=897', f'b.num_allocated_qubits>={ceiling-1}'),
        ('jet_reverse=make_jet_reverse(2)', f'jet_reverse=make_jet_reverse({trace_bits})'),
        ('install_ceiling(decode,898)', f'install_ceiling(decode,{ceiling})'),
    ]
    changes = []
    updated = old
    for before, after in replacements:
        if updated.count(before) != 1:
            raise ValueError(f'Unexpected source recipe: {before}')
        updated = updated.replace(before, after)
        changes.append(dict(path=str(path.relative_to(root)), before=before, after=after))
    path.write_text(updated)
    path = root / SOURCE_REL / 'exp/next/a07/log_source_cap898.py'
    old = path.read_text()
    before = 'b.num_allocated_qubits>=898'
    after = f'b.num_allocated_qubits>={ceiling}'
    if old.count(before) != 1:
        raise ValueError('Unexpected six-bit source guard')
    path.write_text(old.replace(before, after))
    changes.append(dict(path=str(path.relative_to(root)), before=before, after=after))
    return changes


def source_manifest(root):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--parent-artifact', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--ceiling', type=int, choices=range(894, 899), required=True)
    parser.add_argument('--trace-bits', type=int, choices=(2, 3, 6), required=True)
    args = parser.parse_args()
    if digest(args.parent_artifact) != PINNED_PARENT:
        parser.error('This transformation is pinned to the reproduced q22 parent')
    candidate = args.output_dir.resolve().parent
    source = candidate / 'code' / 'upstream'
    if source.exists() or (args.output_dir/'dqi.kmb').exists():
        parser.error('Candidate source and output must be new')
    original = source_manifest(args.source_root)
    shutil.copytree(args.source_root, source, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    changes = transform(source, args.ceiling, args.trace_bits)
    screen = candidate/'screen';screen.mkdir(exist_ok=True)
    for name in ('dqi_trace_tradeoff.py','profile_dqi_source.py'):
        shutil.copy2(Path(__file__).with_name(name), candidate/'code'/name)
    command = [sys.executable, str(candidate/'code/profile_dqi_source.py'),
               '--entry', str(source/SOURCE_REL/'decode_next_best.py'),
               '--output', str(args.output_dir/'dqi.kmb'),
               '--report', str(screen/'lifetime.json')]
    generation = dict(kind='pinned_source_trace_workspace_tradeoff', official_validation=False,
                      actual_source_root=str(args.source_root.resolve()),
                      parent_artifact=str(args.parent_artifact.resolve()),
                      parent_sha256=PINNED_PARENT, parameters=dict(ceiling=args.ceiling,trace_bits=args.trace_bits),
                      argv=sys.argv, build_command=command, python=sys.executable, prefix=sys.prefix,
                      input_source_hashes=original, transformed_source_hashes=source_manifest(source),
                      edits=changes, scientific_scope='Exact selector alternatives and retained trace dimension; full official evidence required')
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
    env=os.environ.copy();env['OPENBLAS_NUM_THREADS']='1';env['OMP_NUM_THREADS']='1'
    subprocess.run(command,env=env,check=True)
    generation['artifacts']=[dict(path='dqi.kmb',sha256=digest(args.output_dir/'dqi.kmb'))]
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')


if __name__ == '__main__':
    main()

# SPDX-License-Identifier: Apache-2.0
"""Apply the exact DQI cache proofs to pinned InvSqrt or chemistry circuits.

This is a shared circuit transformation, with no task-specific arithmetic or
input defaults. The entire parent manifest is pinned. Every circuit and the
chemistry NPZ are emitted, even when the scan finds no replacement.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from dqi_boolean_reduce import compile_scanner, read_proofs, rewrite
from dqi_interval_cache import rewrite_intervals
from generate import output_workspace, sha256


def manifest(directory):
    return [dict(path=p.name,bytes=p.stat().st_size,sha256=sha256(p)) for p in sorted(directory.iterdir()) if p.is_file()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',choices=['invsqrt','dfthcsos'],required=True)
    p.add_argument('--mode',choices=['existing','interval'],required=True)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--parent-manifest',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--term-cap',type=int,default=512)
    a=p.parse_args();started=time.monotonic()
    if not 1<=a.term_cap<=4096:p.error('Term cap outside bounded range')
    expected=json.loads(a.parent_manifest.read_text())
    if manifest(a.parent_output)!=expected:raise ValueError('Pinned parent manifest changed')
    names=[f['path'] for f in expected]
    if a.task=='invsqrt' and names!=['invsqrt.kmb']:raise ValueError('Wrong InvSqrt parent')
    if a.task=='dfthcsos' and ('submission.npz' not in names or not any(n.startswith('angle_k_') for n in names)):
        raise ValueError('Wrong chemistry parent')
    candidate=a.output_dir.parent;code=candidate/'code';screen=candidate/'screen'
    code.mkdir(exist_ok=True);screen.mkdir(exist_ok=True)
    sources=['boolean_cache_tasks.py','dqi_interval_cache.py','dqi_boolean_reduce.py','dqi_boolean_screen.cpp','generate.py']
    for name in sources:shutil.copy2(Path(__file__).with_name(name),code/name)
    shutil.copy2(a.parent_manifest,code/'parent-manifest.json')
    scanner=screen/'cache-scanner';_,compile_command=compile_scanner(scanner,code/'dqi_boolean_screen.cpp')
    rows=[]
    with output_workspace(a.output_dir) as (output,stage):
        for name in names:
            parent=a.parent_output/name
            if name=='submission.npz':shutil.copyfile(parent,stage/name);continue
            if not name.endswith('.kmb'):raise ValueError('Binary parent required')
            proofs_path=screen/(name+'.proofs.tsv');summary=screen/(name+'.summary.json')
            command=[str(scanner),str(parent),str(proofs_path),str(summary),str(a.term_cap),'0','0','0','1' if a.mode=='existing' else '2']
            with (screen/(name+'.log')).open('w') as log:
                subprocess.run(command,check=True,stdout=log,stderr=log,timeout=60)
            proofs=read_proofs(proofs_path)
            if a.mode=='interval':change=rewrite_intervals(parent,stage/name,proofs)
            elif proofs:change=rewrite(parent,stage/name,proofs)
            else:shutil.copyfile(parent,stage/name);change=dict(removed_toffolis=0,added_measurements=0)
            rows.append(dict(circuit=name,proofs=len(proofs),change=change,command=command,
                             proof_sha256=sha256(proofs_path),summary=json.loads(summary.read_text())))
            print(name,len(proofs),'sites',flush=True)
    if manifest(a.parent_output)!=expected:raise ValueError('Parent changed during generation')
    report=dict(kind='exact_boolean_cache_transfer',official_validation=False,task=a.task,mode=a.mode,
        argv=sys.argv,python_executable=sys.executable,python_prefix=sys.prefix,
        parent_output=str(a.parent_output.resolve()),parent_manifest=expected,term_cap=a.term_cap,
        source_generator_available=False,compile_command=compile_command,
        source_hashes={name:sha256(code/name) for name in sources},rows=rows,
        exact_sites=sum(r['proofs'] for r in rows),artifacts=manifest(output),elapsed_seconds=time.monotonic()-started)
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n');print('total sites',report['exact_sites'],flush=True)


if __name__=='__main__':main()

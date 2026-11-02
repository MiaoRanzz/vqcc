# SPDX-License-Identifier: Apache-2.0
"""Complete the previously screened live-891 GF64 logarithmic-source variant.

This builds the exact source-reproduced carry-q22 parent, not the newer compiled
HW09 incumbent. Lowering the n=6 source threshold is the same change whose
4096-case truth table and isolated source costs were saved by the prior run.
Its estimated extra Toffolis do not waive full official verification.
"""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
from generate import sha256

PIN='bdee18489fac2b38b86c2aab225b6469477c67a61ab8b2754f72c1f4a8f6ebe9'
REL=Path('blocks/dqi/carry-q22-892/source')


def manifest(root):
    return {str(f.relative_to(root)):sha256(f) for f in sorted(root.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True);p.add_argument('--parent-artifact',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--screen-evidence',type=Path,required=True)
    args=p.parse_args();started=time.monotonic()
    if sha256(args.parent_artifact)!=PIN:raise ValueError('Wrong actual source parent')
    candidate=args.output_dir.resolve().parent;source=candidate/'code/source'
    if source.exists() or list(args.output_dir.iterdir()):raise ValueError('Use a new candidate')
    original=manifest(args.source_root);shutil.copytree(args.source_root,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    f=source/REL/'exp/next/a07/log_source_cap898.py';old=f.read_text();before='b.num_allocated_qubits>=892';after='b.num_allocated_qubits>=891'
    if old.count(before)!=1:raise ValueError('Unexpected source threshold')
    f.write_text(old.replace(before,after))
    screen=candidate/'screen';screen.mkdir(exist_ok=True)
    for name in ['dqi_companion_log.py','profile_dqi_source.py']:shutil.copy2(Path(__file__).with_name(name),candidate/'code'/name)
    shutil.copy2(args.screen_evidence,candidate/'code/previous-screen.json')
    command=['conda','run','--no-capture-output','-n','vqcc',sys.executable,str(candidate/'code/profile_dqi_source.py'),'--entry',str(source/REL/'decode_carry.py'),'--output',str(args.output_dir/'dqi.kmb'),'--report',str(screen/'lifetime.json')]
    generation=dict(kind='live891_gf64_log_source',official_validation=False,argv=sys.argv,python=sys.executable,prefix=sys.prefix,parent_sha256=PIN,parent_artifact=str(args.parent_artifact.resolve()),actual_source_root=str(args.source_root.resolve()),edits=[dict(path=str(f.relative_to(source)),before=before,after=after)],input_source_hashes=original,transformed_source_hashes=manifest(source),build_command=command,screen_evidence=str(args.screen_evidence),screen_sha256=sha256(args.screen_evidence))
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
    subprocess.run(command,check=True)
    generation['artifacts']=[dict(path='dqi.kmb',sha256=sha256(args.output_dir/'dqi.kmb'))];generation['elapsed_seconds']=time.monotonic()-started
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
    print(json.dumps({'generated':str(args.output_dir/'dqi.kmb'),'elapsed_seconds':generation['elapsed_seconds']}),flush=True)


if __name__=='__main__':main()

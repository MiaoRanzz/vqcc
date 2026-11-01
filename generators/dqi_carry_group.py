"""Test one additional homogeneous group on the pinned 892-qubit carry decoder.

The public carry relation has an allowed nonzero failure rate; this transform
is not a proof that it holds on every input. Official validation and independent
full-size checks decide eligibility. No verifier seed or hash is selected.
"""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from profile_dqi_source import digest

PIN='bdee18489fac2b38b86c2aab225b6469477c67a61ab8b2754f72c1f4a8f6ebe9'
REL=Path('blocks/dqi/carry-q22-892/source')


def manifest(root):
    return {str(f.relative_to(root)):digest(f) for f in sorted(root.rglob('*'))
            if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--parent-artifact',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--first-group',type=int,choices=[4],required=True)
    args=p.parse_args()
    if digest(args.parent_artifact)!=PIN:p.error('Expected the exact reproduced 892-qubit parent')
    candidate=args.output_dir.resolve().parent;source=candidate/'code/source'
    if source.exists() or (args.output_dir/'dqi.kmb').exists():p.error('Use a new candidate')
    original=manifest(args.source_root)
    shutil.copytree(args.source_root,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    f=source/REL/'exp/next/carry/flag_carry.py';old=f.read_text()
    before='FIRST, LAST = 5, 16';after=f'FIRST, LAST = {args.first_group}, 16'
    if old.count(before)!=1:raise ValueError('Unexpected carry source')
    f.write_text(old.replace(before,after))
    screen=candidate/'screen';screen.mkdir(exist_ok=True)
    for name in ['dqi_carry_group.py','profile_dqi_source.py']:
        shutil.copy2(Path(__file__).with_name(name),candidate/'code'/name)
    command=[sys.executable,str(candidate/'code/profile_dqi_source.py'),'--entry',str(source/REL/'decode_carry.py'),'--output',str(args.output_dir/'dqi.kmb'),'--report',str(screen/'lifetime.json')]
    generation=dict(kind='pinned_carry_group_extension',official_validation=False,argv=sys.argv,python=sys.executable,prefix=sys.prefix,parent_sha256=PIN,parent_artifact=str(args.parent_artifact.resolve()),actual_source_root=str(args.source_root.resolve()),parameters=dict(first_group=args.first_group,last_group=16,arithmetic_cap=892),edits=[dict(path=str(f.relative_to(source)),before=before,after=after)],input_source_hashes=original,transformed_source_hashes=manifest(source),build_command=command)
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
    env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    subprocess.run(command,env=env,check=True)
    generation['artifacts']=[dict(path='dqi.kmb',sha256=digest(args.output_dir/'dqi.kmb'))]
    (candidate/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')


if __name__=='__main__':main()

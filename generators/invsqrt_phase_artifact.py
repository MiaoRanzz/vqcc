# SPDX-License-Identifier: Apache-2.0
"""Apply a pinned, fixed-point phase fit to a verified InvSqrt artifact.

Only explicitly listed Z_POW angles change. Quantum values, registers,
measurement bits and cleanup remain unchanged. An optional extra rotation is
inserted at a pinned operation, or on an input bit before value operations. Numerical fitting is separate
from official validation; the saved fit and every source script are retained.
"""
from __future__ import annotations
import argparse
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path
import shutil
import sys
from generate import ROOT, sha256, output_workspace


def decimal_angle(value):
    if value.denominator & (value.denominator-1):
        raise ValueError('Expected a dyadic angle')
    with localcontext() as ctx:
        ctx.prec = max(100, value.denominator.bit_length()+20)
        return format(Decimal(value.numerator)/Decimal(value.denominator),'f')


def apply_fit(lines, rows, delta_units, dropped=(), extra_input_bit=None, extra_feature=None):
    if extra_input_bit is not None and extra_feature is not None:raise ValueError("Choose one extra feature")
    expected = len(rows)+int(extra_input_bit is not None or extra_feature is not None)
    if len(delta_units)!=expected or len({r['index'] for r in rows})!=len(rows):
        raise ValueError('Fit dimensions or rotation indices disagree')
    if not set(dropped)<=set(range(len(rows))):raise ValueError('Invalid dropped rotation')
    if any(not isinstance(x,int) for x in delta_units):raise ValueError('Phase deltas must be integer turn units')
    result=list(lines);changes=[]
    for j,row in enumerate(rows):
        i=row['index']
        if not 0<=i<len(lines):raise ValueError('Rotation index out of range')
        original=lines[i]
        if original!=row['instruction']:raise ValueError('Pinned instruction changed')
        fields=original.split()
        if len(fields)!=3 or fields[0]!='Z_POW':raise ValueError('Only unconditional rotations are supported')
        angle=Fraction(fields[2])+Fraction(int(delta_units[j]),1<<63)
        if j in dropped:
            # Rounded fit deltas can differ by a unit; enforce the prescribed exact zero.
            angle=Fraction(0)
        result[i]='' if not angle else f'{fields[0]} {fields[1]} {decimal_angle(angle)}'
        changes.append(dict(index=i,before=original,after=result[i],delta_turn_units=int(delta_units[j])))
    if extra_input_bit is not None:
        if not 0<=extra_input_bit<22:raise ValueError('Input bit out of range')
        angle=Fraction(int(delta_units[-1]),1<<63)
        if angle:
            at=next(i for i,line in enumerate(result) if line and not line.startswith(('APPEND_TO_REGISTER ','REGISTER ')))
            instruction=f'Z_POW q{extra_input_bit} {decimal_angle(angle)}'
            result.insert(at,instruction);changes.append(dict(insert_before=at,after=instruction))
    if extra_feature is not None:
        at=int(extra_feature['before_index']);q=int(extra_feature['qubit'])
        if not 0<=at<len(lines):raise ValueError('Feature index out of range')
        if lines[at]!=extra_feature['before_instruction']:raise ValueError('Feature insertion context changed')
        if q<0:raise ValueError('Invalid feature qubit')
        angle=Fraction(int(delta_units[-1]),1<<63)
        if angle:
            instruction=f'Z_POW q{q} {decimal_angle(angle)}'
            result.insert(at,instruction);changes.append(dict(insert_before=at,after=instruction))
    return '\n'.join(line for line in result if line)+'\n',changes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--expected-parent-sha256',required=True)
    p.add_argument('--fit',type=Path,required=True)
    p.add_argument('--model-report',type=Path,required=True)
    p.add_argument('--source-script',type=Path,action='append',default=[])
    args=p.parse_args();parent=args.parent_output/'invsqrt.kmb'
    if sha256(parent)!=args.expected_parent_sha256:raise ValueError('Pinned artifact changed')
    fit=json.loads(args.fit.read_text());model=json.loads(args.model_report.read_text())
    sys.path.insert(0,str(ROOT/'kickmix'));import kickmix as km
    candidate=args.output_dir.parent;screen=candidate/'screen';screen.mkdir(exist_ok=True)
    km.Circuit.from_file(parent).to_file(screen/'parent.kmx',format='kmx')
    text,changes=apply_fit((screen/'parent.kmx').read_text().splitlines(),model['rotation_rows'],fit['delta_units'],fit.get('drop',()),fit.get('extra_input_bit'),fit.get('extra_feature'))
    (screen/'fitted.kmx').write_text(text)
    with output_workspace(args.output_dir) as (output,stage):
        km.Circuit.from_file(screen/'fitted.kmx').to_file(stage/'invsqrt.kmb',format='kmb')
    code=candidate/'code'
    for src in [Path(__file__),Path(__file__).with_name('generate.py'),args.fit,args.model_report,*args.source_script]:
        shutil.copy2(src,code/src.name)
    report=dict(kind='fixed_point_rotation_refit',official_validation=False,argv=sys.argv,
        python=sys.executable,prefix=sys.prefix,parent_output=str(args.parent_output.resolve()),parent_sha256=sha256(parent),
        source_generator_available=False,changes=changes,fit=fit,model_checks=model.get('checks'),
        model_scope=model.get('model'),source_hashes={f.name:sha256(f) for f in code.iterdir() if f.is_file()},
        artifacts=[dict(path='invsqrt.kmb',sha256=sha256(output/'invsqrt.kmb'))])
    (candidate/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(changed_rotations=len(changes),model_margin=fit['exact_margin_units'],artifact=report['artifacts'][0])))


if __name__=='__main__':main()

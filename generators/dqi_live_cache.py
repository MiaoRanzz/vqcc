# SPDX-License-Identifier: Apache-2.0
"""Reuse an exact product already held by another live DQI wire.

No cache is allocated. A conservative symbolic stream proves z=a*b immediately
before an unconditional CCX a b t, with z distinct from a,b,t. Replace it by
CX z t. Resets and every conditional or unconditional value mutation invalidate
cached expressions. Opaque atoms only lose opportunities; they never certify a
sampled identity. Complete artifacts are emitted even when no site qualifies.
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
from generate import output_workspace, sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent-output', type=Path, required=True)
    p.add_argument('--expected-parent-sha256', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--term-cap', type=int, default=512)
    p.add_argument('--timeout-seconds', type=int, default=240)
    a = p.parse_args()
    if not 1 <= a.term_cap <= 4096 or not 1 <= a.timeout_seconds <= 900:
        p.error('Invalid bounded proof budget')
    start = time.monotonic()
    parent = a.parent_output/'dqi.kmb'
    if sha256(parent) != a.expected_parent_sha256:
        raise ValueError('Pinned parent changed')
    candidate = a.output_dir.parent
    screen, code = candidate/'screen', candidate/'code'
    screen.mkdir(exist_ok=True); code.mkdir(exist_ok=True)
    names = ['dqi_live_cache.py', 'dqi_boolean_reduce.py', 'dqi_boolean_screen.cpp', 'generate.py']
    for name in names:
        shutil.copy2(Path(__file__).with_name(name), code/name)
    binary = screen/'live-cache-scanner'
    source, compile_command = compile_scanner(binary, code/'dqi_boolean_screen.cpp')
    proofs_path, summary_path = screen/'proofs.tsv', screen/'summary.json'
    command = [str(binary), str(parent), str(proofs_path), str(summary_path), str(a.term_cap), '0', '0', '0', '1']
    with (screen/'scanner.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log, timeout=a.timeout_seconds)
    proofs = read_proofs(proofs_path)
    if any(p['kind'] != 'cached_cx' for p in proofs):
        raise ValueError('Unexpected proof mode')
    with output_workspace(a.output_dir) as (output, stage):
        if proofs:
            change = rewrite(parent, stage/'dqi.kmb', proofs)
        else:
            shutil.copyfile(parent, stage/'dqi.kmb')
            change = dict(removed_toffolis=0, added_measurements=0)
    if sha256(parent) != a.expected_parent_sha256:
        raise ValueError('Parent changed during generation')
    report = dict(kind='exact_existing_live_product_reuse', official_validation=False,
                  argv=sys.argv, python_executable=sys.executable, python_prefix=sys.prefix,
                  parent_output=str(a.parent_output.resolve()), parent_sha256=a.expected_parent_sha256,
                  source_generator_available=False, parameters=dict(term_cap=a.term_cap, xor_cache_limit=0),
                  source_hashes={name:sha256(code/name) for name in names},
                  compile_command=compile_command, screen_command=command,
                  screen=json.loads(summary_path.read_text()), proof_sha256=sha256(proofs_path),
                  change=change, exact_sites=len(proofs),
                  artifacts=[dict(path='dqi.kmb', sha256=sha256(output/'dqi.kmb'))],
                  elapsed_seconds=time.monotonic()-start)
    (candidate/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

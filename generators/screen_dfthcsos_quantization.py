"""Screen fixed deterministic angle strategies using official numerical metrics.

This bypasses circuit simulation and NEVER constitutes official verification.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'kickmix'), str(ROOT/'verifiers'), str(ROOT/'generators')]
import numpy as np
from dfthcsos.verify import load_inputs, evaluate_words, passes_accuracy
from dfthcsos_quantization import reencode_words
from generate import check_destination, requantize_words, sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-npz', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--stop-by', type=datetime.fromisoformat, required=True)
    args = p.parse_args()
    out = check_destination(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    inputs = load_inputs(args.source_npz)
    with np.load(args.source_npz, allow_pickle=False) as data:
        words, edges = np.array(data['angle_words']), np.array(data['tree_edges'])
    trials = []
    for brot, strategy in [(11, 'requantize'), (11, 'reencode'), (12, 'reencode')]:
        if (args.stop_by - datetime.now(timezone.utc)).total_seconds() < 90:
            break
        t = time.monotonic()
        candidate = (requantize_words(words, 12, brot) if strategy == 'requantize'
                     else reencode_words(inputs, edges, brot))
        metrics = evaluate_words(inputs, candidate, edges, brot)
        record = dict(brot=brot, strategy=strategy, metrics=metrics,
                      passes_numerical_gates=passes_accuracy(metrics),
                      official_validation=False, elapsed_seconds=time.monotonic()-t)
        np.save(out / f'{strategy}-{brot}-words.npy', candidate)
        record['words_sha256'] = sha256(out / f'{strategy}-{brot}-words.npy')
        trials.append(record)
        with (out/'trials.jsonl').open('a') as f:
            f.write(json.dumps(record)+'\n')
        print(json.dumps(record), flush=True)
    report = dict(kind='deterministic_numerical_screen', official_validation=False,
        source_npz=str(args.source_npz.resolve()), source_npz_sha256=sha256(args.source_npz),
        source_hashes={str(p.relative_to(ROOT)):sha256(p) for p in [Path(__file__), ROOT/'generators/dfthcsos_quantization.py', ROOT/'generators/generate.py', ROOT/'verifiers/dfthcsos/verify.py', ROOT/'verifiers/dfthcsos/scoreinfra/dfthc_math.py']},
        python_executable=sys.executable, python_prefix=sys.prefix,
        elapsed_seconds=time.monotonic()-started, trials=trials)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()

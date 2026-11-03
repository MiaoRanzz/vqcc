# SPDX-License-Identifier: Apache-2.0
"""Combined-step input: convex mix of W and H2_I from two fixed-word branch results.

Usage: dfthcsos_mix_branches.py PARENT_A_OUTPUT PARENT_B_OUTPUT STAGING_DIR WEIGHT_A
Asserts identical U, words, tree and loader bytes; writes W, H2_I = w*A + (1-w)*B,
recomputes offset_W, copies the loaders, and records parent/mixed NPZ hashes in mix.json.
The staging dir then feeds dfthcsos_manifold.py --parent-output to restore constraints.
First used for candidate 20261103T185806-dfthcsos-97991d (w=0.5), whose code/mix_branches.py
has the same body without this docstring.
"""
import hashlib, json, shutil, sys
from pathlib import Path
import numpy as np
a_dir, b_dir, out = map(Path, sys.argv[1:4]); w = float(sys.argv[4])
a = dict(np.load(a_dir / 'submission.npz')); b = dict(np.load(b_dir / 'submission.npz'))
for k in ('U', 'H1_I', 'Hsym_lower', 'tree_edges', 'angle_words', 'brot'):
    assert np.array_equal(a[k], b[k]), k
for f in sorted(a_dir.glob('angle_k_*.kmb')):
    assert f.read_bytes() == (b_dir / f.name).read_bytes(), f.name
    shutil.copyfile(f, out / f.name)
m = dict(a)
m['W'] = w * a['W'] + (1 - w) * b['W']; m['H2_I'] = w * a['H2_I'] + (1 - w) * b['H2_I']
if 'offset_W' in m: m['offset_W'] = m['H2_I'] - m['W'].sum(axis=1)
np.savez(out / 'submission.npz', **m)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
json.dump(dict(parents=[str(a_dir), str(b_dir)], weight=w, parent_npz_sha256=[sha(a_dir / 'submission.npz'), sha(b_dir / 'submission.npz')],
               mixed_npz_sha256=sha(out / 'submission.npz')), open(out / 'mix.json', 'w'), indent=1)

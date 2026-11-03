# SPDX-License-Identifier: Apache-2.0
"""Apply the exact one-Toffoli CSWAP-pair rewrite to a pinned DQI artifact.

Generalizes the single local delta of yoyobar e01b8f31af20 relative to its
parent 3f7de9dd (Apache-2.0 public circuits): a pair
    CSWAP(a; b, c)  ...W...  CSWAP(a; b, c)
where W writes none of a, b, c and a clean ancilla t is untouched over the
pair, becomes
  site 1:  CX c>b; CCX a,b>t; CX c>b; CX a>t; CX b>t; CX c>t; X t;
           CX t>b; CX t>c; CX a>b; CX a>c; SWAP b c; X b; X c
           (performs CSWAP and leaves t = NOT a AND NOT (b XOR c))
  site 2:  CX t>b; CX t>c; CX a>b; CX a>c; SWAP b c; X b; X c;
           HMR t -> m; if m: CZ a b; CZ a c; Z a; Z b; Z c; -1
           (performs CSWAP from t and erases t; phase repair
            (-1)^((a+1)(b+c+1)) = (-1)^t)
a and b XOR c are CSWAP-invariant and unchanged in W, so t is correct at
site 2 on every basis path: two paid CSWAPs become one CCX.  Pair and
ancilla eligibility come from generators/dqi_cswap_pair_scan.py (syntactic
write sets plus a sound backward |0> proof).  The template itself is
checked here by exact state-vector simulation on every run.
"""
from __future__ import annotations
import argparse, json, shutil, struct, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import output_workspace, sha256
from dqi_boolean_reduce import read_binary, MAGIC, NAMES
import dqi_cswap_pair_scan as scan


def site1(a, b, c, t):
    return [('CX', c, b), ('CCX', a, b, t), ('CX', c, b), ('CX', a, t), ('CX', b, t), ('CX', c, t), ('X', t),
            ('CX', t, b), ('CX', t, c), ('CX', a, b), ('CX', a, c), ('SWAP', b, c), ('X', b), ('X', c)]


def site2(a, b, c, t, bit):
    return [('CX', t, b), ('CX', t, c), ('CX', a, b), ('CX', a, c), ('SWAP', b, c), ('X', b), ('X', c),
            ('HMR', t, bit), ('cCZ', a, b, bit), ('cCZ', a, c, bit), ('cZ', a, bit), ('cZ', b, bit),
            ('cZ', c, bit), ('cPH', bit)]


def encode(g):
    """Return (type, streams dict) for one gate tuple."""
    k = g[0]
    if k == 'CX': return 0x21, dict(a2=[g[1]], t2=[g[2]])
    if k == 'SWAP': return 0x22, dict(a2=[g[1]], t2=[g[2]])
    if k == 'X': return 0x11, dict(q=[g[1]])
    if k == 'CCX': return 0x31, dict(a3=[g[1]], b3=[g[2]], t3=[g[3]])
    if k == 'HMR': return 0x50, dict(q=[g[1]], bit=[g[2]])
    if k == 'cCZ': return 0xA0, dict(a2=[g[1]], t2=[g[2]], condition=[g[3]])
    if k == 'cZ': return 0x90, dict(q=[g[1]], condition=[g[2]])
    if k == 'cPH': return 0x80, dict(condition=[g[1]])
    raise ValueError(k)


def check_template():
    """Exact check: CSWAP . D . CSWAP == site1 . D . site2 (each HMR branch,
    after repair) for random phases D on (a,b,c) and a random input state."""
    rng = np.random.default_rng(0)
    for trial in range(8):
        psi = rng.normal(size=8) + 1j * rng.normal(size=8); psi /= np.linalg.norm(psi)
        ph = np.exp(2j * np.pi * rng.random(8))
        def idx(a, b, c): return a * 4 + b * 2 + c
        def cswap(v):
            w = v.copy()
            for b in (0, 1):
                for c in (0, 1): w[idx(1, c, b)] = v[idx(1, b, c)]
            return w
        ref = cswap(ph * cswap(psi))
        # 4-qubit version: state dict (a,b,c,t) -> amp
        st = {(a, b, c, 0): psi[idx(a, b, c)] for a in (0, 1) for b in (0, 1) for c in (0, 1)}
        def apply(st, g):
            out = {}
            for (a, b, c, t), amp in st.items():
                s = dict(a=a, b=b, c=c, t=t); k = g[0]
                if k == 'CX': s[g[2]] ^= s[g[1]]
                elif k == 'CCX': s[g[3]] ^= s[g[1]] & s[g[2]]
                elif k == 'X': s[g[1]] ^= 1
                elif k == 'SWAP': s[g[1]], s[g[2]] = s[g[2]], s[g[1]]
                key = (s['a'], s['b'], s['c'], s['t']); out[key] = out.get(key, 0) + amp
            return out
        for g in site1('a', 'b', 'c', 't'): st = apply(st, g)
        st = {k: v * ph[idx(*k[:3])] for k, v in st.items()}
        for g in site2('a', 'b', 'c', 't', 0)[:7]: st = apply(st, g)
        for m in (0, 1):
            # HMR: project t onto |m> in X basis -> amplitude (-1)^(m t)/sqrt2, reset t
            br = {}
            for (a, b, c, t), amp in st.items():
                v = amp * (-1) ** (m * t) / np.sqrt(2)
                if m: v *= (-1) ** ((a * b + a * c + a + b + c + 1) & 1)
                br[(a, b, c)] = br.get((a, b, c), 0) + v
            got = np.array([br.get((a, b, c), 0) for a in (0, 1) for b in (0, 1) for c in (0, 1)]) * np.sqrt(2)
            if not np.allclose(got, ref, atol=1e-12): raise AssertionError('template mismatch')
    return 'exact on 8 random states x 8 random diagonal W x both HMR outcomes'


def rewrite_sites(source, destination, edits):
    """edits: dict op_index -> list of gate tuples replacing that op."""
    data = read_binary(source); old = data['packets']; types = old['types']
    ops = np.array(sorted(edits), dtype=np.int64)
    positions = {}
    for names, mask in [(['a3', 'b3', 't3'], (types & 0x30) == 0x30), (['a2', 't2'], (types & 0x30) == 0x20),
                        (['q'], (types & 0x30) == 0x10), (['bit'], (types & 0x40) != 0), (['condition'], (types & 0x80) != 0)]:
        idx = np.flatnonzero(mask); rank = np.searchsorted(idx, ops)
        for name in names: positions[name] = rank
    reps = []
    for o in ops:
        if types[o] != 0x32: raise ValueError('edit site is not an unguarded CSWAP')
        r = {n: [] for n in NAMES[:9]}
        for g in edits[int(o)]:
            t, s = encode(g); r['types'].append(t)
            for k, v in s.items(): r[k].extend(v)
        reps.append(r)
    changed = {}
    for name in NAMES[:9]:
        arr = old[name]; rank = ops if name == 'types' else positions[name]
        remove = 1 if name in ('types', 'a3', 'b3', 't3') else 0
        parts = []; last = 0
        for p, r in zip(rank, reps):
            p = int(p); parts.extend([arr[last:p], np.asarray(r[name], dtype=arr.dtype)]); last = p + remove
        parts.append(arr[last:]); changed[name] = np.concatenate(parts)
    newbits = data['nb'] + sum(1 for r in reps for t in r['types'] if t == 0x50)
    counts = list(data['counts'])
    counts[:6] = [len(changed[n]) for n in ('types', 'a3', 'a2', 'q', 'bit', 'condition')]
    with Path(destination).open('wb') as out:
        out.write(MAGIC); out.write(struct.pack('<4I', 2, data['nq'], newbits, data['nr']))
        out.write(struct.pack('<9Q', *counts)); out.write(data['registers'])
        for i, name in enumerate(NAMES, 1):
            payload = changed.get(name, old[name]); out.write(struct.pack('<2Q', i, payload.nbytes)); out.write(payload.tobytes())
    return dict(sites=len(ops), qubits=data['nq'], bits_before=data['nb'], bits_after=newbits)


def select(scan_result, max_pairs):
    """Deterministic greedy: pairs in op order; each takes the lowest-numbered
    proven ancilla not already assigned to an overlapping selected pair."""
    chosen = []
    for p in scan_result['cswap']['pairs']:
        if any(p['guarded']) or not p['free_ancillas']: continue
        used = {q['t'] for q in chosen if not (q['j'] < p['i'] or p['j'] < q['i'])}
        busy = {w for q in chosen if not (q['j'] < p['i'] or p['j'] < q['i']) for w in (q['a'], q['b'], q['c'])}
        cand = [t for t in p['free_ancillas'] if t not in used and t not in busy]
        if not cand: continue
        chosen.append(dict(p, t=cand[0]))
        if len(chosen) >= max_pairs: break
    return chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-output', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--max-pairs', type=int, default=1 << 30)
    args = ap.parse_args(); start = time.monotonic()
    template = check_template()
    parent = args.parent_output / 'dqi.kmb'; parent_hash = sha256(parent)
    candidate = args.output_dir.parent; code = candidate / 'code'; code.mkdir(exist_ok=True)
    res = scan.analyse(parent)
    chosen = select(res, args.max_pairs)
    # free ancillas were computed against the parent; distinct t per overlapping pair
    # and t never one of another overlapping pair's a/b/c keeps each proof valid.
    edits = {}; bit = None
    data_nb = read_binary(parent)['nb']; bit = data_nb
    for p in chosen:
        edits[p['i']] = site1(p['a'], p['b'], p['c'], p['t'])
        edits[p['j']] = site2(p['a'], p['b'], p['c'], p['t'], bit); bit += 1
    # site-2 bits must be increasing in op order to match sequential allocation
    report = dict(kind='exact_cswap_pair_garbage_ancilla', official_validation=False,
                  created_at=datetime.now(timezone.utc).isoformat(), parent_output=str(args.parent_output.resolve()),
                  parent_sha256=parent_hash, template_check=template, parameters={'max_pairs': args.max_pairs},
                  scan_stats={k: res[k]['stats'] for k in ('cswap', 'ccx')}, pairs=chosen,
                  generator_sha256=sha256(Path(__file__)), scanner_sha256=sha256(Path(scan.__file__)),
                  argv=sys.argv, python_executable=sys.executable, python_prefix=sys.prefix,
                  expected_toffoli_delta=-len(chosen))
    with output_workspace(args.output_dir) as (output, stage):
        report['change'] = rewrite_sites(parent, stage / 'dqi.kmb', edits)
        import kickmix as km
        circuit = km.Circuit.from_file(stage / 'dqi.kmb')
        report['output_operation_statistics'] = dict(circuit.operation_statistics())
        report['parent_operation_statistics'] = dict(km.Circuit.from_file(parent).operation_statistics())
        if circuit.num_qubits != report['change']['qubits']: raise AssertionError('Qubit header changed')
    report['artifacts'] = [{'path': 'dqi.kmb', 'sha256': sha256(output / 'dqi.kmb')}]
    if sha256(parent) != parent_hash: raise RuntimeError('Parent changed during transformation')
    here = Path(__file__).resolve().parent
    for src in ['dqi_cswap_garbage_pairs.py', 'dqi_cswap_pair_scan.py', 'dqi_kmb_ops.py', 'dqi_boolean_reduce.py', 'generate.py']:
        shutil.copy2(here / src, code / src)
    report['elapsed_seconds'] = time.monotonic() - start
    (candidate / 'generation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'pairs'}, indent=2))


if __name__ == '__main__':
    main()

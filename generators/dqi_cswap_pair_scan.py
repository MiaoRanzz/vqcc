# SPDX-License-Identifier: Apache-2.0
"""Find CSWAP pairs that admit the one-Toffoli garbage-ancilla rewrite.

Pattern (seen in yoyobar e01b8f31af20 relative to 3f7de9dd):
  CSWAP(a; b, c)  ...W...  CSWAP(a; b, c)
with W writing none of a, b, c and leaving a clean ancilla t untouched.
Site 1 becomes CSWAP via one CCX that leaves t = NOT a AND NOT (b XOR c);
site 2 performs the swap linearly from t and erases t by HMR with the
phase repair (-1)^((a+1)(b+c+1)).  Both CSWAP values (a, b XOR c) are
invariant under CSWAP and unchanged in W, so t matches at site 2 on every
basis path; the rewrite is exact.  Only syntactic facts are used:
  * a, b, c are not targets of any op strictly between the sites;
  * t is not an operand of any op in [i, j];
  * t is provably |0> at i by a sound backward write-chain proof
    (zero_before): unconditional HMR/reset gives |0>; SWAP moves zero
    provenance; CX/CCX/CSWAP targets stay |0> only if the written value is
    provably 0; X and unknown writes fail; no prior write and no S/E
    register membership means the initial |0>.  Guarded writes keep |0>
    only if the wire was already |0>.
  * both sites are unconditional and at classical-guard depth 0.
Also reports CCX(a,b,t) ... CCX(a,b,t) pairs eligible for HMR uncompute.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dqi_kmb_ops as K

HMR, RST, CSWAP, CCX = 0x50, 0x12, 0x32, 0x31


def analyse(path):
    c = K.load(path); f = K.fields(c)
    op = f['op']; n = len(op); base = op & 0x7f
    depth = np.cumsum((op == 0x81).astype(np.int64) - (op == 0x01).astype(np.int64))
    depth_before = depth - (op == 0x81) + (op == 0x01)  # depth in which op itself executes
    guarded = (depth_before > 0) | ((op & 0x80) != 0) & (op != 0x81)
    nq = c['nq']
    inreg = np.zeros(nq, bool)
    for name, wires in c['regs'].items():
        for w in wires:
            if w & 0x80000000: inreg[w & 0x7fffffff] = True
    # write / touch event lists per qubit
    arity = (op >> 4) & 3
    wr_q, wr_i, to_q, to_i = [], [], [], []
    idx = np.arange(n)
    for k in ('q0', 'q1', 'q2'):
        m = f[k] >= 0
        to_q.append(f[k][m]); to_i.append(idx[m])
    # written operands: arity1 X/RST/HMR q0; CX target q1; SWAP q0,q1; CCX q2; CSWAP q1,q2
    def add(mask, k):
        wr_q.append(f[k][mask]); wr_i.append(idx[mask])
    add(np.isin(base, [0x11, 0x12, 0x50]), 'q0')
    add(base == 0x21, 'q1'); add(base == 0x22, 'q0'); add(base == 0x22, 'q1')
    add(base == 0x31, 'q2'); add(base == 0x32, 'q1'); add(base == 0x32, 'q2')
    known = {0x00, 0x06, 0x07, 0x10, 0x13, 0x17, 0x20, 0x27, 0x30, 0x37, 0x40, 0x41, 0x42, 0x47, 0x01, 0x11, 0x12, 0x50, 0x21, 0x22, 0x31, 0x32}
    unknown = sorted(set(np.unique(base).tolist()) - known - {0x01})
    def lists(qs, ii):
        qs = np.concatenate(qs); ii = np.concatenate(ii)
        o = np.lexsort((ii, qs)); qs, ii = qs[o], ii[o]
        starts = np.searchsorted(qs, np.arange(nq + 1))
        return [ii[starts[q]:starts[q + 1]] for q in range(nq)]
    W = lists(wr_q, wr_i); T = lists(to_q, to_i)
    def next_after(arr, i):
        p = np.searchsorted(arr, i, side='right'); return int(arr[p]) if p < len(arr) else n
    ancillas = [q for q in range(nq) if not inreg[q]]
    zero_reset = np.isin(base, [HMR, RST]) & ~guarded
    q0, q1, q2 = f['q0'], f['q1'], f['q2']
    memo = {}
    def zero_before(q, k, budget=64):
        # True only if wire q is |0> on every path just before op k.
        key = (q, k)
        if key in memo: return memo[key]
        if budget <= 0: return False
        w = W[q]; p = np.searchsorted(w, k)
        if p == 0:
            r = not inreg[q]
        else:
            e = int(w[p - 1]); bt = base[e]; g = bool(guarded[e]); sub = lambda x: zero_before(int(x), e, budget - 1)
            prior = sub(q)
            if bt in (HMR, RST): r = True if not g else prior
            elif bt == 0x22:
                other = int(q1[e]) if int(q0[e]) == q else int(q0[e])
                r = (prior and sub(other)) if g else sub(other)
            elif bt == 0x21: r = prior and sub(q0[e])
            elif bt == CCX: r = prior and (sub(q0[e]) or sub(q1[e]))
            elif bt == CSWAP:
                other = int(q2[e]) if int(q1[e]) == q else int(q1[e])
                r = prior and (sub(other) or sub(q0[e]))
            else: r = False
        memo[key] = r
        return r
    def free_ancillas(i, j):
        out = []
        for t in ancillas:
            tt = T[t]; p = np.searchsorted(tt, i)
            if p < len(tt) and tt[p] <= j: continue
            if zero_before(t, i): out.append(t)
        return out
    res = {'artifact': str(path), 'operations': int(n), 'qubits': int(nq), 'unknown_opcodes': unknown}
    for kind, code in (('cswap', CSWAP), ('ccx', CCX)):
        sites = np.nonzero(base == code)[0]
        pairs = []; stats = dict(sites=int(len(sites)), unguarded=0, paired=0, paired_unguarded=0, with_free_ancilla=0)
        for i in sites:
            i = int(i); a, b, t = int(f['q0'][i]), int(f['q1'][i]), int(f['q2'][i])
            if not guarded[i]: stats['unguarded'] += 1
            if kind == 'cswap':
                j = next_after(W[b], i)
                if j >= n or j != next_after(W[t], i) or base[j] != CSWAP: continue
                if int(f['q0'][j]) != a or {int(f['q1'][j]), int(f['q2'][j])} != {b, t}: continue
                if next_after(W[a], i) < j: continue
            else:
                j = next_after(W[t], i)
                if j >= n or base[j] != CCX or int(f['q2'][j]) != t or {int(f['q0'][j]), int(f['q1'][j])} != {a, b}: continue
                if next_after(W[a], i) < j or next_after(W[b], i) < j: continue
            stats['paired'] += 1
            ug = not guarded[i] and not guarded[j]
            if ug: stats['paired_unguarded'] += 1
            # same guard context check for guarded ones: report only
            fa = free_ancillas(i, j) if kind == 'cswap' else []
            if kind == 'ccx': fa = [t] if zero_before(t, i) else []
            if fa and ug: stats['with_free_ancilla'] += 1
            pairs.append(dict(i=i, j=j, a=a, b=b, c=t, gap=j - i, guarded=[bool(guarded[i]), bool(guarded[j])],
                              depth=[int(depth_before[i]), int(depth_before[j])], free_ancillas=fa[:16], n_free=len(fa)))
        res[kind] = dict(stats=stats, pairs=pairs)
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('kmb'); ap.add_argument('out')
    a = ap.parse_args()
    r = analyse(a.kmb)
    Path(a.out).write_text(json.dumps(r, indent=1))
    print(json.dumps({k: (v['stats'] if isinstance(v, dict) and 'stats' in v else v) for k, v in r.items()}, indent=1))

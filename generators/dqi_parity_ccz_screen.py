# SPDX-License-Identifier: Apache-2.0
"""Screen for classically-selected parity -> CCZ -> uncompute blocks in a DQI .kmb.

Pattern (seen in syed3000 portfolio DQI, b5002f, op 52709166..52709190):
    CX[c_1] x_1 -> t ; ... ; CX[c_k] x_k -> t     (classically conditioned CX, common target t)
    CCZ(a, b, t)                                    (t is one CCZ operand)
    mirrored CX[c_k] x_k -> t ; ... ; CX[c_1] x_1 -> t
(optionally interleaved with mirrored unconditional CX writes into a, b, so the
CCZ acts on linear functions of the controls).
With t zero on entry, t = XOR_i c_i x_i only during the block.  Proposed exact
in-place rewrite (hypothesis dqi_classical_parity_ccz_inplace, NOT implemented
here): compute a classical one-hot pivot p_j = c_j AND NOT(c_1|...|c_{j-1}) with
guarded classical bit ops, then for each j under guard p_j: CX[c_i] x_i -> x_j
(i != j), CCZ(a, b, x_j), undo.  Exactly one guarded CCZ executes when c != 0
(none when c == 0), so mean Toffoli does not increase and t is never used.
Requires x_j not in {a, b} and the x_i distinct.

This screen only measures applicability and how many sampled peak instants
(run starts / run ops from a lane-simulation peak-run JSON) lie inside an
eligible block (i.e. where t's release would remove one live wire).  It does
not build a candidate and is not an official result.

usage: dqi_parity_ccz_screen.py circuit.kmb peak_runs.json out.json [instants.json]
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dqi_kmb_ops as K

CCZ, CX_C, CX = 0x30, 0xA1, 0x21


def main(kmb, runs_path, out):
    c = K.load(kmb); f = K.fields(c); op = f['op']; q0, q1, q2, cond = f['q0'], f['q1'], f['q2'], f['cond']
    sites = np.flatnonzero(op == CCZ)
    blocks = []; reasons = {}
    for s in sites.tolist():
        ops3 = (int(q0[s]), int(q1[s]), int(q2[s]))
        # maximal symmetric CX/CX[c] window around the CCZ
        k = 0
        while (s - 1 - k >= 0 and s + 1 + k < len(op) and op[s - 1 - k] in (CX, CX_C)
               and op[s - 1 - k] == op[s + 1 + k] and q0[s - 1 - k] == q0[s + 1 + k]
               and q1[s - 1 - k] == q1[s + 1 + k] and cond[s - 1 - k] == cond[s + 1 + k]):
            k += 1
        if k == 0:
            continue
        win = [(int(op[s - 1 - i]), int(q0[s - 1 - i]), int(q1[s - 1 - i]), int(cond[s - 1 - i])) for i in range(k)]
        tw = [w for w in win if w[2] in ops3 and w[0] == CX_C]
        if not tw:
            continue
        cnt = {}
        for w in tw: cnt[w[2]] = cnt.get(w[2], 0) + 1
        t = max(cnt, key=cnt.get)
        par = [w for w in win if w[2] == t]
        ctl = [w for w in win if w[2] != t]
        others = [x for x in ops3 if x != t]
        xs = [w[1] for w in par]
        ok = True; why = []
        if len(set(xs)) != len(xs): ok = False; why.append('repeated_x')
        if any(x in others for x in xs): ok = False; why.append('x_in_ccz_controls')
        if any(w[2] not in others for w in ctl): ok = False; why.append('ctl_writes_outside_ccz')
        if any(w[1] == t for w in ctl): ok = False; why.append('ctl_reads_t')
        if any(w[2] in xs for w in ctl): ok = False; why.append('ctl_writes_x')
        for w in why: reasons[w] = reasons.get(w, 0) + 1
        blocks.append(dict(ccz=s, lo=s - k, hi=s + k, t=t, k=len(par), n_ctl=len(ctl), eligible=ok))
    elig = [b for b in blocks if b['eligible']]
    lo = np.array([b['lo'] for b in elig], dtype=np.int64); hi = np.array([b['hi'] for b in elig], dtype=np.int64)
    o = np.argsort(lo); lo, hi = lo[o], hi[o]
    def inside(x):
        i = np.searchsorted(lo, x, side='right') - 1
        return i >= 0 and x <= hi[i]
    rj = json.load(open(runs_path)); runs = rj['runs']
    extra = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else []
    covered = [r for r in runs if inside(r['start']) and inside(r['end'] - 1)]
    start_in = [r for r in runs if inside(r['start'])]
    ks = np.array([b['k'] for b in elig]) if elig else np.array([0])
    res = dict(kind='screen', hypothesis_id='dqi_classical_parity_ccz_inplace', circuit=kmb, peak_runs=runs_path,
               peak=rj.get('peak'), ccz_sites=int(len(sites)), parity_blocks=len(blocks), eligible_blocks=len(elig),
               ineligible_reasons=reasons, k_hist={int(v): int((ks == v).sum()) for v in np.unique(ks)},
               ancilla_wires=sorted({b['t'] for b in elig}),
               peak_runs_total=len(runs), peak_runs_ops=int(sum(r['end'] - r['start'] for r in runs)),
               peak_runs_start_inside_block=len(start_in),
               peak_runs_fully_inside_block=len(covered),
               peak_ops_fully_inside_block=int(sum(r['end'] - r['start'] for r in covered)),
               listed_instants=len(extra), listed_instants_inside_block=sum(1 for x in extra if inside(x)),
               official_validation=False)
    json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:4])

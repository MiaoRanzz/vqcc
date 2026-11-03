# SPDX-License-Identifier: Apache-2.0
"""Decode a version-2 KickMix .kmb op stream into numpy arrays (no simulation).

Layout matches generators/dqi_lane_sim.cpp: header, registers, an opcode
packet and eight operand packets (arity-3 x3, arity-2 x2, arity-1, bit, cond).
Returns per-op arrays op, q0, q1, q2, bit, cond (-1 where unused) and the raw
trailing bytes after the operand packets so a rewriter can re-emit the file.
"""
import struct
import numpy as np


def load(path):
    raw = np.fromfile(path, dtype=np.uint8)
    b = raw.tobytes()
    pos = 16
    ver, nq, nb, nr = struct.unpack_from('<4I', b, pos); pos += 16
    assert ver == 2, ver
    count = list(struct.unpack_from('<9Q', b, pos)); pos += 72
    regs = {}
    for _ in range(nr):
        pos += 16
        namelen, ln = struct.unpack_from('<2I', b, pos); pos += 8
        name = b[pos:pos + namelen].decode(); pos += namelen
        regs[name] = np.frombuffer(b, dtype='<u4', count=ln, offset=pos).copy(); pos += 4 * ln
    header_end = pos

    def packet(typ, nbytes):
        nonlocal pos
        t, n = struct.unpack_from('<2Q', b, pos)
        assert t == typ and n == nbytes, (t, typ, n, nbytes)
        p = pos + 16; pos = p + nbytes
        return p
    ot = packet(1, count[0])
    ops = raw[ot:ot + count[0]]
    groups = [1, 1, 1, 2, 2, 3, 4, 5]
    streams = []
    for j in range(8):
        p = packet(2 + j, 4 * count[groups[j]])
        streams.append(np.frombuffer(b, dtype='<u4', count=count[groups[j]], offset=p))
    trailer = b[pos:]
    return dict(raw=b, nq=nq, nb=nb, nr=nr, count=count, regs=regs, header_end=header_end,
                ops=ops, streams=streams, trailer=trailer, trailer_pos=pos)


def fields(c):
    ops = c['ops'].astype(np.int64)
    n = len(ops)
    arity = (ops >> 4) & 3
    out = {'op': ops}
    for k in ('q0', 'q1', 'q2', 'bit', 'cond'):
        out[k] = np.full(n, -1, dtype=np.int64)
    s = c['streams']
    for a, base in ((3, 0), (2, 3), (1, 5)):
        idx = np.nonzero(arity == a)[0]
        for j in range(a):
            out['q%d' % j][idx] = s[base + j][:len(idx)]
    bi = np.nonzero(ops & 0x40)[0]; out['bit'][bi] = s[6][:len(bi)]
    ci = np.nonzero(ops & 0x80)[0]; out['cond'][ci] = s[7][:len(ci)]
    return out

"""Direct root-controlled GF product phase, independently derived.

For paper-basis x,y and competition-basis mask e, apply
(-1)**(root * <e, backward(x*y)>). No product word is computed.
The unchanged upstream arithmetic is Apache-2.0, pinned by dqi_adapter.py.
"""
from __future__ import annotations


def product_phase_terms(p, backward):
    """Expand the bilinear GF product in the competition output basis.

Each returned (i,j,k) means x_i*y_j contributes to output bit k.
Using the field multiplication definition, rather than its optimized circuit,
keeps this derivation independent of the multiplier's temporary registers.
"""
    terms = []
    for i in range(p.B):
        for j in range(p.B):
            product = p.gmul(1 << i, 1 << j)
            for k, row in enumerate(backward):
                if (product & row).bit_count() & 1:
                    terms.append((i, j, k))
    return tuple(terms)


def emit_product_phase(p, E, root, x, y, controlled_x, terms, mask_bits):
    """Preserve root,x,y; return controlled_x to zero including HMR phase.

The root flag and both operands must stay live until cleanup. All mask controls
are classical input bits. This uses B Toffolis independent of the mask values;
CZ is Clifford even when classically controlled. The measurement repayment
uses root and the unchanged x, so every outcome has the intended phase.
"""
    products = [p.norm_term((root,), 0, (src,), 0, (dst,))
                for src, dst in zip(x, controlled_x)]
    E.emit_mac(products)
    for i, j, k in terms:
        E.b.cz(controlled_x[i], y[j], when=mask_bits[k])
    E.emit_free(products)

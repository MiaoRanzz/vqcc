"""Adapt Gu et al.'s Apache-2.0 DQI circuit to the local competition contract.

Upstream snapshot: 64b5a13aa249f1360846657392e6c66817b26d0f.
Changes: field isomorphism, runtime classical masks, all-position Forney sweep,
and lossless lowering from uncompute gates to kickmix .kmb.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "kickmix"), str(HERE / "upstream")]

import kickmix as km
from uncompute.classical import f2_matinv, f2_transpose
from uncompute.gadgets import linear_in_place
from uncompute.ops import NO_BIT, NO_OUT, OpKind


def load_source():
    path = HERE / "upstream/tasks/dqi-reed-solomon/circuits/discovered/circuit.py"
    import uncompute.testing
    uncompute.testing.load_contract = lambda _: json.loads((path.parents[2] / "contract.json").read_text())
    spec = importlib.util.spec_from_file_location("paper_dqi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def field_isomorphism(p):
    """Map the competition polynomial basis to the paper's polynomial basis."""
    field = km.GF2Field(p.B)
    poly = field.modulus

    def evaluate(x):
        value = 0
        for i in range(p.B, -1, -1):
            value = p.gmul(value, x) ^ ((poly >> i) & 1)
        return value

    beta = next(x for x in range(2, 1 << p.B) if evaluate(x) == 0)
    forward = f2_transpose([p.gpow(beta, i) for i in range(p.B)], p.B)
    backward = f2_matinv(forward, p.B)

    def transform(x, rows):
        return sum(((x & r).bit_count() & 1) << i for i, r in enumerate(rows))

    # Exhaustively check the bijection and multiplication by every basis vector.
    for x in range(1 << p.B):
        y = transform(x, forward)
        assert transform(y, backward) == x
        for bit in range(p.B):
            assert transform(field.mul(x, 1 << bit), forward) == p.gmul(y, p.gpow(beta, bit))
    primitive_image = transform(field.primitive_element, forward)
    return forward, backward, p.LOG[primitive_image], beta


def install_adapter(p, forward, backward, step):
    original_declare = p.declare_registers

    def declare(b, schema):
        registers = original_declare(b, schema)
        for _ in range(p.M):
            b.bit_register(b.bits(p.B))
        for reg in registers.values():
            linear_in_place(b, reg, forward)
        return registers

    def sweep(b, E, A, omega, locator, bezout):
        # At position j, x = alpha_competition^(-j) in the paper's basis.
        # locator evaluates E'(x) + sqrt(x) O'(x); its zeros locate errors.
        # bezout evaluates V(x), with V(x)^2 = 1 / sigma'(x) at these zeros.
        # Thus the original error value is omega(x) * V(x)^2.
        groups = [(omega, list(range(p.W))), (locator, p.LOG_EB), (bezout, p.LOG_AB)]
        rotations = [(word, p.cmrows(p.EXP[(-step * power) % p.M]))
                     for words, powers in groups for word, power in zip(words, powers)]
        with p.opened(E, "sweep_omega", p.B) as om, \
             p.opened(E, "sweep_locator", p.B) as loc, \
             p.opened(E, "sweep_bezout", p.B) as bez, \
             p.opened(E, "sweep_error", p.B) as err:
            with b.repeat(p.M) as j:
                for words, target in [(omega, om), (locator, loc), (bezout, bez)]:
                    for word in words:
                        for src, dst in zip(word, target):
                            b.cx(src, dst)
                linear_in_place(b, bez, p.SQUARE_ROWS)
                product = p.prod_rt(err, om, bez)
                E.emit_mac(product)
                linear_in_place(b, err, backward)
                with p.eq_test(E, loc, 0) as root:
                    for bit in range(p.B):
                        b.cz(root, err[bit], when=j * p.B + bit)
                linear_in_place(b, err, forward)
                E.emit_free(product)
                linear_in_place(b, bez, p.SQRT_ROWS)
                for words, target in [(bezout, bez), (locator, loc), (omega, om)]:
                    for word in reversed(words):
                        for src, dst in zip(word, target):
                            b.cx(src, dst)
                for word, rows in rotations:
                    linear_in_place(b, word, rows)
        # All rotations close exactly: alpha^4095 == 1 for every coefficient.

    p.declare_registers = declare
    p.ZMASKI = [0] * p.N  # Remove the fixed-mask linear phase correction.
    p.emit_sweep = sweep
    # The original cost pins apply to the fixed-mask task, not this adaptation.
    p.assert_metrics = lambda b, _: b.phase_summary()["total_emitted_toffoli"]


def write_kmx(b, path, p):
    """Lower each primitive without conflating input bits and HMR outcomes."""
    bit_offset = b.next_bit
    with path.open("w") as f:
        for r in range(p.N):
            for bit in range(p.B):
                f.write(f"APPEND_TO_REGISTER q{r * p.B + bit} r{r}\n")
            f.write(f'REGISTER r{r} "S{r}"\n')
        for j in range(p.M):
            for bit in range(p.B):
                f.write(f"APPEND_TO_REGISTER b{j * p.B + bit} r{p.N + j}\n")
            f.write(f'REGISTER r{p.N + j} "E{j}"\n')
        count = 0
        for k, qa, qb, qt, ot, oc, rt, ct, cc in b.iter_expanded():
            kind = OpKind(k)
            conditions = []
            if oc != NO_OUT and kind != OpKind.OXOR:
                conditions.append(bit_offset + oc)
            if cc != NO_BIT:
                conditions.append(cc)
            if kind in (OpKind.X, OpKind.Z, OpKind.R):
                line = f"{kind.name} q{qt}"
            elif kind == OpKind.NEG:
                line = "NEG"
            elif kind in (OpKind.CX, OpKind.CZ, OpKind.SWAP):
                line = f"{kind.name} q{qb} q{qt}"
            elif kind in (OpKind.CCX, OpKind.CCZ):
                line = f"{kind.name} q{qa} q{qb} q{qt}"
            elif kind == OpKind.HMR:
                line = f"HMR q{qt} b{bit_offset + ot}"
            elif kind == OpKind.OXOR:
                line = f"BIT_INVERT b{bit_offset + ot}"
                conditions.append(bit_offset + oc)
            elif kind in (OpKind.BIT_INVERT, OpKind.BIT_STORE0, OpKind.BIT_STORE1):
                line = f"{kind.name} b{ct}"
            else:
                raise ValueError(kind)
            if len(conditions) > 1:
                raise ValueError("Unexpected combined outcome and input-bit control")
            if conditions:
                line += f" if b{conditions[0]}"
            f.write(line + "\n")
            count += 1
        return count


def main():
    p = load_source()
    forward, backward, step, beta = field_isomorphism(p)
    print(f"Field isomorphism verified: beta={beta}, exponent={step}", flush=True)
    install_adapter(p, forward, backward, step)
    b, _ = p.build()
    for r in range(p.N):
        linear_in_place(b, list(range(r * p.B, (r + 1) * p.B)), backward)
    print(f"Built adapted circuit: {b.next_qubit} qubits", flush=True)
    output = HERE.parent / "files" / "dqi.kmb"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vqcc-dqi-") as tmp:
        path = Path(tmp) / "dqi.kmx"
        count = write_kmx(b, path, p)
        print(f"Lowered {count:,} primitive instructions", flush=True)
        circuit = km.Circuit.from_file(path, format="kmx")
        circuit.to_file(output, format="kmb")
    report = {
        "upstream_commit": "64b5a13aa249f1360846657392e6c66817b26d0f",
        "competition_polynomial": km.GF2Field(p.B).modulus,
        "paper_polynomial": p.POLY,
        "isomorphism_beta": beta,
        "primitive_exponent": step,
        "field_basis_exhaustively_checked": True,
        "qubits": circuit.num_qubits,
        "instructions": len(circuit),
        "operation_statistics": dict(circuit.operation_statistics()),
    }
    (HERE.parent / "build_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()

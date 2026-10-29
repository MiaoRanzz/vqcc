"""Write the ANGLE_k kickmix circuits for the angle words of a submission.

The verifier scores ``.kmx`` (or binary ``.kmb``, with ``--format kmb``)
circuits. This script writes them, with kickmix alone, from the ``angle_words`` table stored in a ``submission.npz``; it is how
the example's circuits ``FeMoCo76o113e/angle_k_*.kmx`` can be rebuilt. From
the qaggle repository root::

    EX=dfthcsos/example_submission/FeMoCo76o113e
    python dfthcsos/example_submission/angle_k_reference_circuit.py $EX/submission.npz OUT_DIR --brot 12 --batch-size 8
    python dfthcsos/verify.py $EX/submission.npz OUT_DIR --tree-edges $EX/submission.npz

``angle_words`` has one row per vector (``N + R*B`` rows: the ``N`` one-body
rows, then the ``R*B`` two-body rows) and ``N - 1`` integer words of ``brot``
bits each. The input is an ``.npz`` with an ``angle_words`` entry or an
``.npy`` holding the table. ``OUT_DIR`` receives ``angle_k_0.kmx``,
``angle_k_1.kmx``, ...; existing files are not overwritten without
``--overwrite``.

Circuit ``k`` is the XOR oracle ``|a>|z> -> |a>|z XOR delta[k, a]>``: row ``a``
is split into batches of ``J`` words (zero padded), ``delta[0] = batch[0]`` and
``delta[k] = batch[k] XOR batch[k-1]`` (see "What a submission must do" in
``dfthcsos/SCORING_README.md``). Each circuit is an ordinary QROM, built the way
Qualtran's ``QROM`` decomposes: an uncontrolled segment-tree unary iteration
over the ``selection`` register (at most ``N + R*B - 2`` Toffolis and
``ceil(log2(N + R*B)) - 1`` ancillas, uncomputed by measurement) that XORs the
words of each address into the ``word_j`` registers. These are the gates of the
dfthc-sos starter kit's circuits: for the example, the files equal the starter
kit's apart from their comment lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil
from operator import index
from pathlib import Path
import sys
from typing import Any

import kickmix as km
import numpy as np
import numpy.typing as npt

# Development shim: allow `python dfthcsos/example_submission/angle_k_reference_circuit.py` without installing.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[2])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

from dfthcsos.scoreinfra.circuits import (  # noqa: E402
    SELECTION_REGISTER,
    circuit_costs,
    kmb_path,
    kmx_path,
    word_register,
)


def batch_deltas(angle_words: npt.ArrayLike, batch_size: int) -> npt.NDArray[np.int64]:
    """The ``(K, N + R*B, J)`` tables ``delta[k]`` that circuit ``k`` loads.

    Each row of ``angle_words`` is zero padded to ``K * J`` words and split into
    ``K = ceil((N - 1) / J)`` batches; ``delta[k] = batch[k] XOR batch[k - 1]``.
    """
    words = np.asarray(angle_words)
    if words.ndim != 2 or not np.issubdtype(words.dtype, np.integer):
        raise ValueError("angle_words must be a 2-D integer array (N + R*B, N - 1)")
    if np.any(words < 0):
        raise ValueError("angle_words must be non-negative")
    batch_size = index(batch_size)
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    num_vectors, num_angles = words.shape
    num_batches = max(1, ceil(num_angles / batch_size))
    padded = np.zeros((num_vectors, num_batches * batch_size), dtype=np.int64)
    padded[:, :num_angles] = words
    batches = padded.reshape(num_vectors, num_batches, batch_size).transpose(1, 0, 2)
    deltas = batches.copy()
    deltas[1:] ^= batches[:-1]
    return deltas


def build_angle_k_circuit(delta: npt.ArrayLike, brot: int) -> km.Circuit:
    """The XOR oracle of one ``(A, J)`` table ``delta`` as an ordinary QROM.

    The selection register has ``n = ceil(log2(A))`` qubits. Its top bit
    (negated, then restored) controls the two halves of the address range
    directly; every further level of the segment tree computes the AND of its
    parent's control and that level's address bit (negated for the lower half)
    into one of the ``n - 1`` ancillas. A node with one address, or whose rows
    all hold one value (Qualtran's QROM ``_break_early``), XORs its first row
    into the words.
    """
    delta = np.asarray(delta, dtype=np.int64)
    brot = index(brot)
    if not 1 <= brot <= 63:
        raise ValueError("brot must be an integer between 1 and 63")
    if delta.ndim != 2 or delta.shape[0] < 2:
        raise ValueError("delta must have shape (A, J) with A >= 2 addresses")
    if np.any(delta < 0) or np.any(delta >= np.int64(1) << brot):
        raise ValueError(f"words must lie in [0, 2**{brot})")
    num_rows, batch_size = delta.shape
    num_bits = (num_rows - 1).bit_length()
    builder = km.CircuitBuilder()
    selection = builder.create_quantum_register(num_bits, SELECTION_REGISTER)
    words = [builder.create_quantum_register(brot, word_register(j)) for j in range(batch_size)]
    ancillas = builder.alloc_qubits(num_bits - 1) if num_bits > 1 else []
    bits = [selection[i] for i in reversed(range(num_bits))]  # most significant first

    def load(row: int, control: Any) -> None:
        # One CX per set bit of the row's words, most significant bit first.
        for j in range(batch_size):
            for bit in reversed(range(brot)):
                if (int(delta[row, j]) >> bit) & 1:
                    builder.cx(control, words[j][bit])

    def node(control: Any, level: int, lo: int, hi: int) -> None:
        # `control` is ON exactly when the address lies in [lo, hi).
        if lo >= num_rows:
            return
        if hi <= num_rows and (hi - lo == 1 or np.all(delta[lo:hi] == delta[lo, 0])):
            load(lo, control)
            return
        mid = (lo + hi) // 2
        if num_rows <= mid:
            node(control, level + 1, lo, mid)
            return
        bit, ancilla = bits[level], ancillas[level - 1]
        builder.x(bit)
        builder.init_and(control, bit, ancilla)  # ancilla = control AND NOT bit
        builder.x(bit)
        node(ancilla, level + 1, lo, mid)
        builder.cx(control, ancilla)  # ancilla = control AND bit
        node(ancilla, level + 1, mid, hi)
        builder.del_and(control, bit, ancilla)  # uncompute by measurement (HMR + CZ if b)

    half = 1 << (num_bits - 1)
    builder.x(bits[0])  # NOT top bit: ON on the lower half
    node(bits[0], 1, 0, half)
    builder.x(bits[0])  # top bit: ON on the upper half
    node(bits[0], 1, half, 2 * half)
    return builder.finish_circuit()


def build_angle_k_family(
    angle_words: npt.ArrayLike, brot: int, batch_size: int
) -> tuple[km.Circuit, ...]:
    """The ``ceil((N - 1) / J)`` circuits ANGLE_0, ANGLE_1, ... of a word table."""
    return tuple(build_angle_k_circuit(delta, brot) for delta in batch_deltas(angle_words, batch_size))


def write_kmx_family(
    circuits: Sequence[km.Circuit],
    directory: str | Path,
    *,
    format: str = "kmx",
    overwrite: bool = False,
) -> list[Path]:
    """Write ``angle_k_<k>.kmx`` (or ``.kmb``) files; refuse to overwrite unless asked.

    The verifier reads ``angle_k_0``, ``angle_k_1``, ... up to the first
    missing file, so the files of an earlier, longer family count as existing
    and are removed when overwriting.
    """
    if format not in ("kmx", "kmb"):
        raise ValueError(f"format must be 'kmx' or 'kmb', got {format!r}")
    family_path = kmb_path if format == "kmb" else kmx_path
    directory = Path(directory)
    paths = [family_path(directory, k) for k in range(len(circuits))]
    stale = []
    while family_path(directory, len(paths) + len(stale)).is_file():
        stale.append(family_path(directory, len(paths) + len(stale)))
    existing = [path for path in paths + stale if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"{existing[0]} exists; pass overwrite=True (--overwrite) to replace it")
    directory.mkdir(parents=True, exist_ok=True)
    for path in stale:
        path.unlink()
    for k, (path, circuit) in enumerate(zip(paths, circuits)):
        if format == "kmb":
            circuit.to_file(path, format="kmb")
        else:
            path.write_text(f"# ANGLE_{k}\n" + str(circuit).rstrip("\n") + "\n", encoding="utf-8")
    return paths


def load_angle_words(path: str | Path) -> npt.NDArray[np.int64]:
    """``angle_words`` from an ``.npz`` (entry ``angle_words``) or an ``.npy``."""
    loaded: Any = np.load(path, allow_pickle=False)
    if isinstance(loaded, np.ndarray):
        words = loaded
    else:
        with loaded as archive:
            if "angle_words" not in archive.files:
                raise KeyError(f"{path} has no angle_words entry")
            words = np.array(archive["angle_words"])
    if words.ndim != 2 or not np.issubdtype(words.dtype, np.integer):
        raise ValueError(f"{path}: angle_words must be a 2-D integer array")
    return words.astype(np.int64)


__all__ = [
    "batch_deltas",
    "build_angle_k_circuit",
    "build_angle_k_family",
    "load_angle_words",
    "write_kmx_family",
]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Write the ANGLE_k kickmix circuits for an angle-word table."
    )
    parser.add_argument("angle_words", type=Path, help="submission.npz (an .npz with angle_words) or an .npy")
    parser.add_argument("output_directory", type=Path, help="receives angle_k_0.kmx, angle_k_1.kmx, ...")
    parser.add_argument("--brot", type=int, required=True, help="bits per word (the word register width)")
    parser.add_argument("--batch-size", type=int, default=8, help="words per circuit, J (default 8)")
    parser.add_argument("--format", choices=("kmx", "kmb"), default="kmx", help="circuit file format (default kmx)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing circuit files")
    args = parser.parse_args()
    circuits = build_angle_k_family(load_angle_words(args.angle_words), args.brot, args.batch_size)
    paths = write_kmx_family(circuits, args.output_directory, format=args.format, overwrite=args.overwrite)
    for path, costs in zip(paths, circuit_costs(circuits)):
        print(f"{path}: {costs['num_qubits']} qubits, max_magic {costs['max_magic']}")


if __name__ == "__main__":
    main()

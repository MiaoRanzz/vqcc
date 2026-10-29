"""Read and simulate Task 3 circuits for ``verify``; defines the register rules.

``verify`` calls this for you. Use it directly only to check your own circuits,
e.g. ``recover_words_from_circuits(load_circuits("run_dir/"), num_vectors=N + R*B,
num_angles=N - 1)`` returns the angle words they load, or raises
``InvalidCircuits`` with the reason.

What the circuits must do
-------------------------
Circuit ``k`` (file ``angle_k_<k>.kmb`` or ``.kmx``, ``k = 0 .. K-1``, applied
in order) is the XOR oracle ``|a>|z> -> |a>|z XOR f_k(a)>``. ``f_k(a)`` is the XOR of
batches ``k - 1`` and ``k`` of the angle words of row ``a`` (batch ``k`` holds
words ``k*J .. k*J + J - 1``, zero padded). Applied in order to ``z = 0`` the
family loads batch 0, 1, ...; applied in reverse it clears ``z`` again.

Register rules (named kickmix registers, little endian)
-------------------------------------------------------
* ``"selection"``: the address ``a < N + R*B``, using exactly
  ``ceil(log2(N + R*B))`` qubits.
* ``"word_0"`` .. ``"word_{J-1}"``: one register per word, each ``brot`` qubits.
  The verifier reads ``brot`` and ``J`` from these registers.
* All other qubits are workspace: they start and end in ``|0>``, and no phase
  may be left behind.
* No ``Z_POW`` (arbitrary-angle phase) instructions. The phase check only
  tells a half turn from no turn, and rotations are not counted as Toffolis,
  so every phase must be a multiple of pi (``Z``, ``CZ``, ``CCZ``, ``NEG``).

Every circuit must use the same ``selection`` and ``word_j`` registers.

Measurement outcomes (``HMR`` and ``R``) come from a simulator seeded with the
caller's ``seed``; ``verify`` uses ``initial_seed(submission_sha256(...), salt)``,
the SHA-256 of the whole submission (circuits, factorization and tree) merged
with the grader's salt. Every address is simulated ``SHOTS_PER_ADDRESS`` times
with independent outcomes. Every sampled shot must load the same words and
end with an unflipped phase. Observed disagreements or uncorrected phases
are rejected; passing does not establish correctness on unsampled branches.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
from math import ceil
from operator import index
from pathlib import Path
import re
from typing import Any
import zipfile

import kickmix as km
import numpy as np
import numpy.typing as npt

FORMATS = ("auto", "kmb", "kmx")
SELECTION_REGISTER = "selection"
WORD_REGISTER_PREFIX = "word_"
_WORD_REGISTER_PATTERN = re.compile(rf"{WORD_REGISTER_PREFIX}(\d+)")
_ANGLE_FILE_PATTERN = re.compile(r"angle_k_(\d+)\.(kmb|kmx)")


def word_register(j: int) -> str:
    """Name of the register that holds word ``j`` of a batch."""
    return f"{WORD_REGISTER_PREFIX}{j}"


class InvalidCircuits(ValueError):
    """The circuits break the register contract or load the wrong state."""


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def kmb_path(directory: str | Path, k: int) -> Path:
    """File name of circuit ``k`` in a family directory: ``angle_k_<k>.kmb``."""
    return Path(directory) / f"angle_k_{k}.kmb"


def kmx_path(directory: str | Path, k: int) -> Path:
    """File name of circuit ``k`` in a family directory: ``angle_k_<k>.kmx``."""
    return Path(directory) / f"angle_k_{k}.kmx"


def read_circuit(path: str | Path, format: str = "auto") -> km.Circuit:
    """Read one ``.kmb`` or ``.kmx`` circuit file."""
    if format not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {format!r}")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such circuit file: {path}")
    return km.Circuit.from_file(path, format=format)


def read_kmx(path: str | Path) -> km.Circuit:
    """Parse one ``.kmx`` text file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such .kmx file: {path}")
    return km.Circuit(path.read_text(encoding="utf-8"))


def _scan_angle_files(directory: str | Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"kmb": set(), "kmx": set()}
    dir_path = Path(directory)
    if dir_path.is_dir():
        for entry in dir_path.iterdir():
            if entry.is_file() and (match := _ANGLE_FILE_PATTERN.fullmatch(entry.name)):
                found[match.group(2)].add(entry.name)
    return found


def read_kmx_family(directory: str | Path) -> tuple[km.Circuit, ...]:
    """Read ``angle_k_0.kmx``, ``angle_k_1.kmx``, ... from ``directory``."""
    found = _scan_angle_files(directory)["kmx"]
    circuits = []
    while kmx_path(directory, len(circuits)).is_file():
        circuits.append(read_kmx(kmx_path(directory, len(circuits))))
    if not circuits:
        raise FileNotFoundError(f"no angle_k_0.kmx in {directory}")
    expected = {f"angle_k_{k}.kmx" for k in range(len(circuits))}
    if found != expected:
        raise ValueError(
            f"non-contiguous or extra .kmx files in {directory}: {sorted(found - expected)}"
        )
    return tuple(circuits)


def read_circuit_family(directory: str | Path, format: str = "auto") -> tuple[km.Circuit, ...]:
    """Read ``angle_k_0``, ``angle_k_1``, ... (``.kmb`` or ``.kmx``) from ``directory``.

    With ``format="auto"`` the extension of ``angle_k_0`` decides; a directory
    holding both ``angle_k_0.kmb`` and ``angle_k_0.kmx`` is ambiguous.
    """
    if format not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {format!r}")
    found = _scan_angle_files(directory)
    if format == "auto":
        has_kmb, has_kmx = kmb_path(directory, 0).is_file(), kmx_path(directory, 0).is_file()
        if has_kmb and has_kmx:
            raise ValueError(
                f"both angle_k_0.kmb and angle_k_0.kmx exist in {directory}; "
                "pass format='kmb' or format='kmx'"
            )
        if found["kmb"] and found["kmx"]:
            raise ValueError(
                f"both .kmb and .kmx angle_k_* files exist in {directory}; "
                "pass format='kmb' or format='kmx'"
            )
        format = "kmb" if has_kmb else "kmx"
    path = kmb_path if format == "kmb" else kmx_path
    circuits = []
    while path(directory, len(circuits)).is_file():
        circuits.append(read_circuit(path(directory, len(circuits)), format=format))
    if not circuits:
        raise FileNotFoundError(f"no angle_k_0.kmb or angle_k_0.kmx in {directory}")
    expected = {f"angle_k_{k}.{format}" for k in range(len(circuits))}
    if found[format] != expected:
        raise ValueError(
            f"non-contiguous or extra .{format} files in {directory}: "
            f"{sorted(found[format] - expected)}"
        )
    return tuple(circuits)


def load_circuits(circuits: Any, format: str = "auto") -> tuple[km.Circuit, ...]:
    """Normalize a circuit family argument to a tuple of ``kickmix.Circuit``.

    Accepts a directory (read with ``read_circuit_family``), a single ``.kmb``
    or ``.kmx`` file, or an ordered sequence whose items are circuit paths or
    ``kickmix.Circuit`` objects.
    """
    if isinstance(circuits, (str, Path)):
        path = Path(circuits)
        if path.is_dir():
            return read_circuit_family(path, format=format)
        return (read_circuit(path, format=format),)
    if isinstance(circuits, km.Circuit):
        return (circuits,)
    loaded = tuple(
        item if isinstance(item, km.Circuit) else read_circuit(item, format=format)
        for item in circuits
    )
    if not loaded:
        raise ValueError("circuits must be nonempty")
    return loaded


# ---------------------------------------------------------------------------
# Submission hash and simulator seed
# ---------------------------------------------------------------------------


# The ``.npz`` entries hashed after the circuits, in this order.
HASHED_NPZ_KEYS = ("U", "W", "H2_I", "H1_I", "Hsym_lower", "tree_edges")


def npy_bytes(array: npt.ArrayLike) -> bytes:
    """The ``.npy`` serialization of ``array``: the ``<key>.npy`` entry ``numpy.savez`` writes for it."""
    buf = io.BytesIO()
    np.save(buf, np.asarray(array), allow_pickle=False)
    return buf.getvalue()


def _npz_entries(path: str | Path, keys: Sequence[str]) -> dict[str, bytes]:
    """The ``<key>.npy`` entries of the ``.npz`` at ``path`` that exist, each checked to be exactly one array."""
    path = Path(path)
    if path.suffix.lower() != ".npz":
        raise ValueError(f"{path}: factorizations require .npz files, not pickles or other formats")
    entries = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"{path} contains duplicate archive entries")
        for key in keys:
            if key in names:  # numpy.load would read this entry instead of <key>.npy
                raise ValueError(f"{path}: entry {key!r} must be named {key + '.npy'!r}")
            if f"{key}.npy" in names:
                data = archive.read(f"{key}.npy")
                stream = io.BytesIO(data)
                np.lib.format.read_array(stream, allow_pickle=False)
                if stream.read(1):  # numpy.load would ignore these bytes
                    raise ValueError(f"{path}: {key}.npy has trailing bytes after its array")
                entries[key] = data
    return entries


def submission_sha256(
    circuits: Sequence[km.Circuit],
    factorization: str | Path | Mapping[str, npt.ArrayLike],
    tree_edges: npt.ArrayLike,
) -> str:
    r"""The SHA-256 hex digest of a whole submission, as computed from its files with::

        { printf '%s\n' angle_k_*.kmb | sort -t_ -k3,3n | xargs cat
          for k in U W H2_I H1_I Hsym_lower tree_edges; do unzip -p submission.npz "$k.npy"; done
        } | sha256sum

    That is, the canonical ``.kmb`` bytes of ``circuits`` in order, then the
    ``.npy`` entries ``HASHED_NPZ_KEYS`` of ``factorization`` (an ``.npz``
    path, or a mapping of arrays serialized with ``numpy.save``), with no
    separators. ``tree_edges`` is used when the ``.npz`` has no
    ``tree_edges.npy``.

    The digest depends only on the circuits' gates and the arrays' bytes,
    dtype, shape and order, not on ``.kmx`` comments or ``.npz`` packaging.
    Each entry must be exactly one array, as ``numpy.load`` reads it; ``.kmb``
    and ``.npy`` headers then fix where every piece ends, so no two different
    submissions hash the same bytes. The verifier's simulator seed is
    ``initial_seed(submission_sha256(...), salt)``.
    """
    circuits = tuple(circuits)
    if not circuits:
        raise ValueError("circuits must be nonempty")
    if isinstance(factorization, Mapping):
        entries = {key: npy_bytes(factorization[key]) for key in HASHED_NPZ_KEYS if key in factorization}
    else:
        entries = _npz_entries(factorization, HASHED_NPZ_KEYS)
    entries.setdefault("tree_edges", npy_bytes(tree_edges))
    digest = hashlib.sha256()
    for circuit in circuits:
        buf = io.BytesIO()
        circuit.to_file(buf, format="kmb")
        digest.update(buf.getvalue())
    for key in HASHED_NPZ_KEYS:
        digest.update(entries[key])
    return digest.hexdigest()


def initial_seed(digest_hex: str, salt: str = "") -> int:
    """The simulator seed for a SHA-256 hex digest, mixed with an optional ``salt``."""
    if not salt:
        return int(digest_hex, 16)
    return int(hashlib.sha256(f"{digest_hex}{salt}".encode("utf-8")).hexdigest(), 16)


# ---------------------------------------------------------------------------
# Register layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterLayout:
    """The public registers shared by every circuit of a family."""

    selection: Any
    words: tuple[Any, ...]

    @property
    def brot(self) -> int:
        """Bits per angle word (the width of each ``word_j`` register)."""
        return len(self.words[0])

    @property
    def batch_size(self) -> int:
        """``J``, the number of words loaded by each circuit."""
        return len(self.words)

    @property
    def public_qubits(self) -> frozenset[int]:
        return frozenset(
            q.id for register in (self.selection, *self.words) for q in register
        )


def register_layout(circuits: Sequence[km.Circuit]) -> RegisterLayout:
    """Read and validate the ``selection`` / ``word_j`` registers of a family.

    Raises ``InvalidCircuits`` if a register is missing, the word registers are
    not numbered ``0 .. J-1`` or differ in width, registers overlap, or the
    circuits do not all use the same public registers.
    """
    circuits = tuple(circuits)
    if not circuits:
        raise ValueError("circuits must be nonempty")
    registers = circuits[0].register_data
    if SELECTION_REGISTER not in registers:
        raise InvalidCircuits(f"missing the {SELECTION_REGISTER!r} register")
    indices = sorted(
        int(match.group(1))
        for name in registers
        if (match := _WORD_REGISTER_PATTERN.fullmatch(name))
    )
    if not indices:
        raise InvalidCircuits(
            f"no word registers; expected {word_register(0)!r}, {word_register(1)!r}, ..."
        )
    if indices != list(range(len(indices))):
        raise InvalidCircuits(
            f"word registers must be numbered 0..J-1 without gaps, got {indices}"
        )
    selection = registers[SELECTION_REGISTER]
    words = tuple(registers[word_register(j)] for j in indices)
    if len(selection) == 0 or any(len(word) == 0 for word in words):
        raise InvalidCircuits("public registers must be nonempty")
    widths = {len(word) for word in words}
    if len(widths) != 1:
        raise InvalidCircuits(
            f"every word register must have the same width (brot), got {sorted(widths)}"
        )
    if not all(isinstance(q, km.q) for register in (selection, *words) for q in register):
        raise InvalidCircuits("public registers must hold qubits, not classical bits")
    ids = [q.id for register in (selection, *words) for q in register]
    if len(ids) != len(set(ids)):
        raise InvalidCircuits("the selection and word registers overlap")
    names = (SELECTION_REGISTER, *(word_register(j) for j in indices))
    for k, circuit in enumerate(circuits[1:], start=1):
        other = circuit.register_data
        for name in names:
            if name not in other or other[name] != registers[name]:
                raise InvalidCircuits(
                    f"ANGLE_{k} does not use the same {name!r} register as ANGLE_0"
                )
        extra = {
            name for name in other if _WORD_REGISTER_PATTERN.fullmatch(name)
        } - set(names)
        if extra:
            raise InvalidCircuits(f"ANGLE_{k} declares extra word registers {sorted(extra)}")
    return RegisterLayout(selection=selection, words=words)


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------


def circuit_costs(circuits: Sequence[km.Circuit]) -> list[dict[str, int]]:
    """Per-circuit ``num_qubits``, ``max_magic`` (static CCX/CCZ bound), reaction depth."""
    return [
        {
            "k": k,
            "num_qubits": int(circuit.num_qubits),
            "max_magic": int(circuit.operation_statistics().num_toffoli_like),
            "reaction_depth": int(circuit.reaction_depth()),
            "num_instructions": len(circuit),
        }
        for k, circuit in enumerate(circuits)
    ]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

# Shots simulated per address. kickmix follows one classical trajectory per
# shot: every ``HMR`` outcome (and the dephasing of ``R`` on a nonzero qubit)
# is drawn fresh and uniformly at random, and the shot's phase is flipped only
# when the outcome is 1 and the qubit was |1>. For a fixed input and check,
# a failure of probability p is missed by s independent shots with probability
# (1 - p)**s. A single, always-executed missing HMR correction on |1> has
# p = 1/2; rare conditional faults need not. Running forward and reverse does not
# give a universal 2**(-2*s) bound. Observed word disagreements are rejected,
# but agreement alone does not prove that the output is deterministic.
# The shots share one batch
# (kickmix packs 256 shots per machine word): the Fe2S2 family verifies in
# about 80 ms, a 3976-address family in about 14 s.
SHOTS_PER_ADDRESS = 64


def _check_state(
    sim: km.Simulator,
    circuit: km.Circuit,
    layout: RegisterLayout,
    address_bits: np.ndarray,
    label: str,
) -> None:
    if np.any(sim.read_phase_flipped_across_shots()):
        raise InvalidCircuits(f"{label}: uncorrected phase (measurement kickback)")
    if not np.array_equal(sim.read_across_shots(layout.selection), address_bits):
        raise InvalidCircuits(f"{label}: the selection register changed")
    public = layout.public_qubits
    work = [km.q(i) for i in range(circuit.num_qubits) if i not in public]
    if work and np.any(sim.read_across_shots(km.array(work))):
        raise InvalidCircuits(f"{label}: workspace qubits are not returned to |0>")


def _reject_rotations(circuits: Sequence[km.Circuit]) -> None:
    """Raise ``InvalidCircuits`` if a circuit has a ``Z_POW`` instruction.

    kickmix prints ``Z_POW`` and ``Z_POW_IF`` as ``Z_POW q<i> <half turns>``
    (``... if b<j>`` for the conditioned form); ``Circuit`` has no rotation
    count, so the circuit text is scanned.
    """
    for k, circuit in enumerate(circuits):
        if any(line.startswith("Z_POW") for line in str(circuit).splitlines()):
            raise InvalidCircuits(
                f"ANGLE_{k}: Z_POW rotations are not allowed (phases must be multiples of pi)"
            )


def recover_words_from_circuits(
    circuits: Sequence[km.Circuit],
    *,
    num_vectors: int,
    num_angles: int,
    shots_per_address: int = SHOTS_PER_ADDRESS,
    seed: int,
) -> tuple[npt.NDArray[np.int64], RegisterLayout, float]:
    """Simulate a family on every address; return the words, layout and Toffoli count.

    ``seed`` (a non-negative integer) seeds the simulator's ``HMR`` and ``R``
    outcomes; ``verify`` passes ``initial_seed(submission_sha256(...), salt)``.
    The Toffoli count is the mean number of Toffoli-like gates (``CCX``, ``CCZ``,
    ``CSWAP``; a conditioned gate counts only on the shots whose bit is set)
    executed per shot over the forward and reverse pass together.
    Circuits with ``Z_POW`` instructions are rejected before simulating.
    ``brot`` and ``J`` are read from the word registers (``register_layout``).
    Every address ``a`` is simulated on ``shots_per_address`` shots with
    independent measurement outcomes (shot ``a + r * num_vectors`` has
    selection ``a``; see ``SHOTS_PER_ADDRESS``), and the word registers start
    at zero on every shot. After circuit ``k`` they must hold batch ``k`` of
    the words of row ``a``, the same on every shot of ``a``; the batches are
    concatenated and the zero padding beyond ``num_angles`` is checked and
    dropped. The circuits are then applied in reverse order, which must clear
    the word registers. After every circuit the selection must be unchanged,
    the workspace clean and the phase unflipped on every shot. Raises
    ``InvalidCircuits`` on any violation.
    """
    circuits = tuple(circuits)
    _reject_rotations(circuits)
    layout = register_layout(circuits)
    brot, batch_size = layout.brot, layout.batch_size
    expected = ceil(num_angles / batch_size)
    if len(circuits) != expected:
        raise InvalidCircuits(
            f"{num_angles} angles in batches of J={batch_size} need {expected} "
            f"circuits, got {len(circuits)}"
        )
    # Extra address bits would be uncharged workspace in the cost model.
    selection_bits = (index(num_vectors) - 1).bit_length()
    if len(layout.selection) != selection_bits:
        raise InvalidCircuits(
            f"the selection register must have exactly {selection_bits} qubits "
            f"for {num_vectors} vectors, got {len(layout.selection)}"
        )
    try:
        repeats = index(shots_per_address)
    except TypeError as exc:
        raise ValueError("shots_per_address must be a positive integer") from exc
    if repeats < 1:
        raise ValueError("shots_per_address must be a positive integer")

    try:
        base_seed = index(seed)
    except TypeError as exc:
        raise ValueError("seed must be a non-negative integer") from exc
    if base_seed < 0:
        raise ValueError(f"seed must be non-negative, got {base_seed}")
    sim_seed = int.from_bytes(
        np.random.SeedSequence(base_seed, pool_size=8).generate_state(4, dtype=np.uint64),
        "little",
    )

    sim = km.Simulator(batch_size=num_vectors * repeats, debug_print=False, seed=sim_seed, counting_operations=True)
    sim.use_same_registers_as(circuits[0])
    addresses = np.tile(np.arange(num_vectors, dtype=np.int64), repeats)
    address_bits = (
        (addresses[None, :] >> np.arange(len(layout.selection))[:, None]) & 1
    ).astype(bool)
    sim.write_across_shots(layout.selection, address_bits)
    place_values = np.int64(1) << np.arange(brot, dtype=np.int64)

    def read_words(label: str) -> np.ndarray:
        # (num_vectors, J) integers from the J little-endian word registers.
        # The repeated shots of an address must agree: a word that depends on
        # a measurement outcome is random rather than a function of the address.
        table = np.stack(
            [
                place_values @ sim.read_across_shots(word).astype(np.int64)
                for word in layout.words
            ],
            axis=1,
        ).reshape(repeats, num_vectors, batch_size)
        if np.any(table != table[0]):
            raise InvalidCircuits(
                f"{label}: repeated shots of the same address loaded different words"
            )
        return table[0]

    def reset_between_circuits(batch: np.ndarray | None) -> None:
        sim.clear_for_shot()
        sim.write_across_shots(layout.selection, address_bits)
        if batch is not None:
            tiled = np.tile(batch, (repeats, 1))
            for j, word in enumerate(layout.words):
                bits = (
                    (tiled[:, j][None, :] >> np.arange(brot, dtype=np.int64)[:, None]) & 1
                ).astype(bool)
                sim.write_across_shots(word, bits)

    batches = []
    for k, circuit in enumerate(circuits):
        sim.do(circuit)
        _check_state(sim, circuit, layout, address_bits, f"ANGLE_{k}")
        batch = read_words(f"ANGLE_{k}")
        batches.append(batch)
        reset_between_circuits(batch)
    words = np.concatenate(batches, axis=1)
    if np.any(words[:, num_angles:]):
        raise InvalidCircuits("padding words beyond N - 1 are not zero")

    for k in reversed(range(len(circuits))):
        sim.do(circuits[k])
        _check_state(sim, circuits[k], layout, address_bits, f"reverse ANGLE_{k}")
        actual = read_words(f"reverse ANGLE_{k}")
        if k > 0:
            if not np.array_equal(actual, batches[k - 1]):
                raise InvalidCircuits(
                    f"reverse ANGLE_{k} did not restore the ANGLE_{k - 1} word registers"
                )
            reset_between_circuits(batches[k - 1])
        elif np.any(actual):
            raise InvalidCircuits("the reverse traversal did not clear the word registers")
    toffoli = sim.operation_statistics().num_toffoli_like / (num_vectors * repeats)
    return words[:, :num_angles], layout, toffoli


__all__ = [
    "FORMATS",
    "HASHED_NPZ_KEYS",
    "InvalidCircuits",
    "RegisterLayout",
    "SELECTION_REGISTER",
    "SHOTS_PER_ADDRESS",
    "WORD_REGISTER_PREFIX",
    "circuit_costs",
    "initial_seed",
    "kmb_path",
    "kmx_path",
    "load_circuits",
    "npy_bytes",
    "read_circuit",
    "read_circuit_family",
    "read_kmx",
    "read_kmx_family",
    "recover_words_from_circuits",
    "register_layout",
    "submission_sha256",
    "word_register",
]

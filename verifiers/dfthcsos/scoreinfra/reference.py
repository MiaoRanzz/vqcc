"""Verifier inputs: the FeMoCo76o113e system, its reference integrals and factorizations.

The competition is scored against one system, FeMoCo76o113e (76 spatial
orbitals, 113 electrons). Its constants live here, and its reference
integrals ship with the package as ``FeMoCo76o113e.fcidump`` (128 MB), so
nothing has to be installed.

Nothing here imports ``dfthc``. The FCIDUMP reader reproduces
``dfthc.load_integrals.fci_from_fcidump`` value for value, and the
factorization loader replaces ``dfthc.dfthc_u_to_tei.load_solution``. It reads
``.npz`` archives only, never pickles, because ``pickle.load`` on a submitted
file would run arbitrary code.

FCIDUMP
-------
The verifier always scores against the packaged ``FeMoCo76o113e.fcidump``
(``PACKAGED_FCIDUMP``); there is no option to use another file.
``FCIDUMP_SHA256`` is the checksum of that file; ``check_fcidump`` compares a
file (by default the packaged one) against it.

Factorization ``.npz``
----------------------
The arrays of the trainer's ``params_best`` (``U`` (R, B, N), ``W`` (R, B, C),
``H2_I`` (R, C), ``H1_I`` (scalar), ``Hsym_lower`` (N(N+1)/2,)); other keys
are ignored. Write one with ``numpy.savez(path, U=..., W=..., H2_I=...,
H1_I=..., Hsym_lower=...)``; the starter trainer writes NPZ directly.
No legacy pickle reader or converter is provided.

Fixed symmetry shifts
---------------------
The symmetry shift ``(S, beta_1)`` is not an optimization variable: the
verifier scores every submission with the shift of the provided baseline,
whose ``H1_I`` and ``Hsym_lower`` ship as ``FeMoCo76o113e.fixed_shifts.npz``
(``PACKAGED_FIXED_SHIFTS``, checksum ``FIXED_SHIFTS_SHA256``).
``load_fixed_shifts`` reads them; the submitted ``H1_I`` and ``Hsym_lower``
are ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import os
from pathlib import Path
from typing import Any
import zipfile

import numpy as np
import numpy.typing as npt

# The competition system (dfthc-sos ``data/systems.toml`` entry "FeMoCo76o113e").
SYSTEM = "FeMoCo76o113e"
ORBITALS = 76  # N, spatial orbitals
ELECTRONS = 113  # eta
UPPER_ENERGY = -22140.27335  # E_upper (Hartree), upper bound on the ground-state energy
BASELINE_SHAPE = (65, 60, 60)  # (R, B, C) of the provided baseline factorization

FCIDUMP_NAME = "FeMoCo76o113e.fcidump"
FCIDUMP_BYTES = 128128348
FCIDUMP_SHA256 = "e5a48af746fd075026dec9e8f5df2d363802a121e8c53af9a0b984bde695e1bd"
# Shipped at the top of the dfthcsos package, one level above this module.
PACKAGED_FCIDUMP = Path(__file__).resolve().parents[1] / FCIDUMP_NAME

FACTORIZATION_KEYS = ("U", "W", "H2_I", "H1_I", "Hsym_lower")

FIXED_SHIFTS_NAME = f"{SYSTEM}.fixed_shifts.npz"
FIXED_SHIFTS_SHA256 = "7b7facf63fe35a9d9d3d00787ffdb700c863fa845fe4724d7f7c54778151cd87"
PACKAGED_FIXED_SHIFTS = Path(__file__).resolve().parents[1] / FIXED_SHIFTS_NAME
FIXED_SHIFTS_KEYS = ("H1_I", "Hsym_lower")


# ---------------------------------------------------------------------------
# The reference FCIDUMP
# ---------------------------------------------------------------------------


def fcidump_sha256(path: str | Path) -> tuple[str, int]:
    """SHA-256 and size in bytes of an FCIDUMP (under 1 s)."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1 << 24):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def check_fcidump(path: str | Path = PACKAGED_FCIDUMP) -> Path:
    """``path`` (by default the packaged FCIDUMP), after checking it is the reference file.

    Raises ``FileNotFoundError`` if it is missing and ``ValueError`` if its
    size or SHA-256 differs from ``FCIDUMP_BYTES`` / ``FCIDUMP_SHA256``.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"FCIDUMP not found: {path}")
    if fcidump_sha256(path) != (FCIDUMP_SHA256, FCIDUMP_BYTES):
        raise ValueError(f"{path} is not the {SYSTEM} reference FCIDUMP (sha256 {FCIDUMP_SHA256})")
    return path


# ---------------------------------------------------------------------------
# The fixed symmetry shifts
# ---------------------------------------------------------------------------


def load_fixed_shifts(path: str | Path = PACKAGED_FIXED_SHIFTS) -> dict[str, np.ndarray]:
    """The baseline's ``H1_I`` and ``Hsym_lower``, after checking the file's SHA-256.

    Raises ``ValueError`` if the bytes of ``path`` (by default the packaged
    file) do not match ``FIXED_SHIFTS_SHA256``.
    """
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXED_SHIFTS_SHA256:
        raise ValueError(f"{path} is not the {SYSTEM} fixed shifts file (sha256 {FIXED_SHIFTS_SHA256})")
    with np.load(io.BytesIO(raw), allow_pickle=False) as data:
        return {key: np.array(data[key]) for key in FIXED_SHIFTS_KEYS}


# ---------------------------------------------------------------------------
# Reference integrals
# ---------------------------------------------------------------------------


def _pair_index(i: int, j: int) -> int:
    """Row-major index of the pair (max(i, j), min(i, j)) in a packed triangle."""
    high, low = max(i, j), min(i, j)
    return high * (high + 1) // 2 + low


def _parse_header(header: str) -> dict[str, str]:
    """Key-value pairs of an ``&FCI ... &END`` header (``FCIDumpFileContent``)."""
    rest_header = header[4:-4]
    values = {}
    while (ind := rest_header.find("=")) > -1:
        key = rest_header[0:ind].strip()
        rest_header = rest_header[ind + 1:]
        # The value runs to the next comma, or to the next space for ORBSYM.
        ind = rest_header.find("," if key != "ORBSYM" else " ")
        value = rest_header[0:ind].strip()
        rest_header = rest_header[ind + 1:]
        if key == "ORBSYM":
            value = value[:-1]
        values[key] = value
    return values


def _h2_full_from_lower(h2_lower: np.ndarray, num_orbitals: int) -> np.ndarray:
    """Expand packed-pair ``(pq|rs)`` to the full chemist-order N^4 tensor."""
    n = num_orbitals
    rows, cols = np.tril_indices(n)
    sym = np.zeros((n * (n + 1) // 2, n, n))
    sym[:, rows, cols] = np.array(h2_lower)
    sym[:, cols, rows] = np.array(h2_lower)
    h2_full = np.zeros((n, n, n, n))
    h2_full[rows, cols, :, :] = sym
    h2_full[cols, rows, :, :] = sym
    return h2_full


def load_reference(fcidump: str | Path) -> dict[str, Any]:
    """Read an FCIDUMP into the reference used by the verifier.

    Returns ``orbitals`` (N), ``electrons`` (eta), ``ecore``, ``oei`` (N, N),
    ``tei`` (N, N, N, N) in chemist order and ``h1_thc``
    (``oei - 1/2 sum_r (pr|rq)``).

    Like ``dfthc.load_integrals``, the two-electron integrals are stored as
    float32 before they are expanded, so ``tei`` holds float32-rounded values
    (``oei`` is float64). The score depends on this rounding; keep it.
    """
    path = Path(fcidump)
    with path.open("r", encoding="utf-8") as stream:
        first = stream.readline().strip()
        if not first.startswith("&FCI"):
            raise ValueError(f"{path} is not an FCIDUMP file: it does not start with &FCI")
        header = ""
        line = first
        while True:
            header += line + " "
            if line.endswith("&END"):
                break
            line = stream.readline()
            if not line:
                raise ValueError(f"{path}: the FCIDUMP header has no &END")
            line = line.strip()
        values = _parse_header(header)
        num_orbitals = int(values["NORB"])
        num_electrons = int(values["NELEC"])

        num_pairs = num_orbitals * (num_orbitals + 1) // 2
        oei = np.zeros((num_orbitals, num_orbitals))
        h2_lower = np.zeros((num_pairs, num_pairs), dtype=np.float32)
        ecore = 0.0
        for line in stream:
            tokens = line.split()
            if not tokens:
                continue
            coefficient = float(tokens[0])
            indices = [int(token) - 1 for token in tokens[1:] if token != "0"]
            if len(indices) == 2:
                i, j = sorted(indices)
                oei[i, j] = coefficient
                oei[j, i] = coefficient
            elif len(indices) == 4:
                # Mulliken (ij|kl) to Dirac order, then the canonical member of
                # the eightfold permutation group.
                i, j, k, l = indices[0], indices[2], indices[3], indices[1]
                i, j, k, l = min(
                    [i, j, k, l], [j, i, l, k], [k, l, i, j], [l, k, j, i],
                    [i, k, j, l], [k, i, l, j], [j, l, i, k], [l, j, k, i],
                )
                ii, jj = _pair_index(i, l), _pair_index(j, k)
                h2_lower[ii, jj] = coefficient
                h2_lower[jj, ii] = coefficient
            elif not indices:
                ecore = coefficient

    tei = _h2_full_from_lower(h2_lower, num_orbitals)
    h1_thc = np.array(oei - 0.5 * np.einsum("pqqs->ps", tei))
    return {
        "orbitals": num_orbitals,
        "electrons": num_electrons,
        "ecore": ecore,
        "oei": oei,
        "tei": tei,
        "h1_thc": h1_thc,
    }


# ---------------------------------------------------------------------------
# Factorizations
# ---------------------------------------------------------------------------


def load_factorization(
    factorization: str | Path | Mapping[str, npt.ArrayLike],
) -> dict[str, np.ndarray]:
    """Read and validate a factorization: an ``.npz`` path or a mapping of arrays.

    Returns the five arrays of ``FACTORIZATION_KEYS`` with their stored
    dtypes. ``.npz`` files are opened with ``allow_pickle=False``.
    """
    if isinstance(factorization, (str, os.PathLike)):
        path = Path(factorization)
        if path.suffix.lower() != ".npz":
            raise ValueError(
                f"{path}: factorizations require .npz files, not pickles or other formats; save the "
                f"arrays {FACTORIZATION_KEYS} with numpy.savez (the starter trainer "
                "writes NPZ directly)"
            )
        if not path.is_file():
            raise FileNotFoundError(f"no such factorization file: {path}")
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            if len(names) != len(set(names)):
                raise ValueError(f"{path} contains duplicate archive entries")
        try:
            loaded = np.load(path, allow_pickle=False)
        except ValueError as error:
            raise ValueError(f"{path} is not an .npz archive of arrays: {error}") from error
        if isinstance(loaded, np.ndarray):
            raise ValueError(f"{path} holds a single array; expected an .npz with {FACTORIZATION_KEYS}")
        with loaded as archive:
            missing = [key for key in FACTORIZATION_KEYS if key not in archive.files]
            if missing:
                raise KeyError(f"{path} has no {missing} entries")
            params = {key: np.array(archive[key]) for key in FACTORIZATION_KEYS}
        source = str(path)
    elif isinstance(factorization, Mapping):
        missing = [key for key in FACTORIZATION_KEYS if key not in factorization]
        if missing:
            raise KeyError(f"factorization has no {missing} entries")
        params = {key: np.array(factorization[key]) for key in FACTORIZATION_KEYS}
        source = "factorization"
    else:
        raise TypeError("factorization must be an .npz path or a mapping of arrays")

    for key, value in params.items():
        if not (np.issubdtype(value.dtype, np.floating) or np.issubdtype(value.dtype, np.integer)):
            raise ValueError(f"{source}: {key} must be a real numeric array, got {value.dtype}")
        if not np.all(np.isfinite(value)):
            raise ValueError(f"{source}: {key} must contain finite values")
    U, W = params["U"], params["W"]
    if U.ndim != 3 or W.ndim != 3:
        raise ValueError(f"{source}: U and W must have shapes (R, B, N) and (R, B, C)")
    if U.shape[:2] != W.shape[:2]:
        raise ValueError(f"{source}: U and W must have the same (R, B) leading dimensions")
    rank_r, bases_b, copies_c = W.shape
    if min(rank_r, bases_b, copies_c, U.shape[-1]) <= 0:
        raise ValueError(f"{source}: factorization dimensions must be positive")
    if params["H2_I"].shape != (rank_r, copies_c):
        raise ValueError(f"{source}: H2_I must have shape (R, C) = {(rank_r, copies_c)}")
    if params["H1_I"].size != 1:
        raise ValueError(f"{source}: H1_I must be a scalar")
    params["H1_I"] = params["H1_I"].reshape(())
    orbitals = U.shape[-1]
    if params["Hsym_lower"].shape != (orbitals * (orbitals + 1) // 2,):
        raise ValueError(f"{source}: Hsym_lower has the wrong packed-pair dimension")
    return params


__all__ = [
    "BASELINE_SHAPE",
    "ELECTRONS",
    "FACTORIZATION_KEYS",
    "FCIDUMP_BYTES",
    "FCIDUMP_NAME",
    "FCIDUMP_SHA256",
    "ORBITALS",
    "PACKAGED_FCIDUMP",
    "SYSTEM",
    "UPPER_ENERGY",
    "check_fcidump",
    "fcidump_sha256",
    "load_factorization",
    "load_reference",
]

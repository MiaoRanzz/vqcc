"""State-preparation and Givens-rotation cost model used by the score (Toffoli and qubit counts).

A subset of ``SpinFreeData_V1`` from ``dfthc/spin_free_block_encoding_costs.py``,
copied so that the verifier does not import ``dfthc``. Only the methods the
score uses are kept: ``outer_state_prep``, ``inner_state_prep``,
``givens_rotations`` and their ``*_qubit_cost`` counterparts
(``dfthcsos.verify.heuristic_costs``). Their arithmetic is identical to this
repository's copy of ``dfthc`` (this module raises ``ValueError`` where
``dfthc`` asserts). Changing it changes the score.

Both differ from the original model, still unchanged in the dfthc-sos
repository, in three places:

* ``inner_state_prep`` decrements ``k2_opt`` by ``1`` per step (``k2_opt -= 1``)
  when ``B < 2**k2_opt``, instead of the original's cumulative ``k2_opt -= ii``.
* ``inner_state_prep`` allows a QROAM block of exactly ``B``
  (``B >= 2**k2_opt``), both when lowering ``k2_opt`` and in the final check.
  The original requires ``B > 2**k2_opt``, so it fails when they are equal at
  the start (e.g. B = 64 at beta = 16) and otherwise skips that block size,
  overpricing power-of-two B such as 16 and 32.
* ``inner_state_prep_qubit_cost`` uses the same inner-QROAM word width
  ``b2 = ceil(log2 B) + chi + 1`` as ``inner_state_prep``. The original drops
  the ``+ 1`` there, so it priced qubits for a narrower word than Toffolis.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


def QR(L: int, M1: int) -> tuple[int, int]:
    """Optimal ``k`` and minimal cost of a QROM over ``L`` values of size ``M1``."""
    k = 0.5 * np.log2(L / M1)
    if k < 0:
        k = 0
    value = lambda k: L / np.power(2.0, k) + M1 * (np.power(2.0, k) - 1)  # noqa: E731
    k_int = [np.floor(k), np.ceil(k)]  # restrict optimal k to integers
    k_opt = k_int[np.argmin(value(k_int))]  # obtain optimal k
    val_opt = np.ceil(value(k_opt))  # obtain ceiling of optimal value given k
    if not (k_opt.is_integer() and val_opt.is_integer()):
        raise ValueError(f"QR({L}, {M1}) did not produce integer k and cost")
    return int(k_opt), int(val_opt)


def QI(L: int) -> tuple[int, int]:
    """Optimal ``k`` and minimal cost of an inverse QROM over ``L`` values."""
    k = 0.5 * np.log2(L)
    if k < 0:
        k = 0
    value = lambda k: L / np.power(2.0, k) + np.power(2.0, k) - 1  # noqa: E731
    k_int = [np.floor(k), np.ceil(k)]  # restrict optimal k to integers
    k_opt = k_int[np.argmin(value(k_int))]  # obtain optimal k
    val_opt = np.ceil(value(k_opt))  # obtain ceiling of optimal value given k
    if not (k_opt.is_integer() and val_opt.is_integer()):
        raise ValueError(f"QI({L}) did not produce integer k and cost")
    return int(k_opt), int(val_opt)


@dataclass(frozen=True)
class SpinFreeData_V1:  # noqa: N801 (name kept from the cost-model source)
    """Outer and inner state-preparation costs of the spin-free block encoding.

    Args:
        R: rank (number of ``rho``).
        B: number of basis vectors per ``rho``.
        C: ensemble rank (number of ``c``).
        N: number of spatial orbitals.
        chi: bits of precision of the keep values.
        beta: bits of precision of the rotations (``brot``).
        optimize_qubits: trade a few Toffolis for fewer temporary qubits.
    """

    R: int
    B: int
    C: int
    N: int
    chi: int
    beta: int
    optimize_qubits: bool = True

    def find_qroam_size_to_minimize_global_temp_ancilla(self, b2: int) -> int:
        """QROAM size for the inner preparation whose temporary qubits fit in
        the rotations' persistent ancilla, so they cost nothing extra."""
        k2_opt = QR(self.R * self.C * self.B, b2)[0]
        if self.optimize_qubits:
            for j in range(k2_opt + 1):  # start from zero in case k2_opt is already optimal
                k2_opt_new = k2_opt - j
                if math.ceil(math.log2(self.R * self.C * math.ceil(self.B / 2**k2_opt_new))) + ((2**k2_opt_new) - 1) * b2 < self.beta * (self.N - 1):
                    k2_opt = k2_opt_new
                    break
            else:
                raise ValueError(
                    "Could not find k2_opt that lowers temp inner-qroam costs below "
                    "rotation persistent ancilla"
                )
        return k2_opt

    # Toffoli costs.

    def outer_state_prep(self) -> int:
        """Toffolis of the state preparation over the linear combination of T_2."""
        X_o = self.N + self.R * self.C
        uniform = 4 * math.ceil(math.log2(X_o))
        uniform_dag = uniform
        b_k1 = self.chi
        b1 = math.ceil(math.log2(X_o)) + b_k1
        # The additional b_k1 is for the inequality test and ceil(log2(X_o)) for swaps.
        alias_sampling = QR(X_o, b1)[1] + b1
        alias_sampling_dag = QI(X_o)[1] + b1 + 1
        return uniform + uniform_dag + alias_sampling + alias_sampling_dag

    def inner_state_prep(self) -> int:
        """Toffolis of the inner state preparation."""
        b_k2 = self.chi
        b2 = math.ceil(math.log2(self.B)) + b_k2 + 1
        k2_opt = QR(self.R * self.C * self.B, b2)[0]

        if self.optimize_qubits:
            k2_opt = self.find_qroam_size_to_minimize_global_temp_ancilla(b2)

        if self.B < 2**k2_opt:
            for ii in range(k2_opt):
                k2_opt -= 1
                if self.B >= 2**k2_opt:
                    break
        if not self.B >= 2**k2_opt:
            raise ValueError(f"inner_state_prep needs B >= 2**k2_opt, got B={self.B}, k2_opt={k2_opt}")
        RC = self.R * self.C
        for_qroam = RC * math.ceil((self.B + 1) / (2**k2_opt)) + (2**k2_opt) * b2

        # QR gives ceil(RC / 2^k) + (2^k - 1) (B + 1), so B is added below.
        k4_opt, QI_cost = QR(self.R * self.C, self.B + 1)
        for_qroam_dag = QI_cost + (self.B + 1) + self.N + b2
        uniform_b = 4 * math.ceil(math.log2(self.B + 1))
        uniform_b_dag = uniform_b
        return for_qroam + for_qroam_dag + uniform_b + uniform_b_dag

    def givens_rotations(self) -> int:
        """Toffolis of the ``N - 1`` Givens rotations across the forward and reverse passes.

        Each Givens rotation uses a ``beta``-bit controlled adder into the
        phase-gradient register, costing ``2 * beta - 1`` Toffolis per pass.
        """
        return 2 * (self.N - 1) * (2 * self.beta - 1)

    # Qubit costs.

    def outer_state_prep_qubit_cost(self) -> dict[str, int]:
        X_o = self.N + self.R * self.C
        b_k1 = self.chi
        b1 = math.ceil(math.log2(X_o)) + b_k1
        uniform_persistent = math.ceil(math.log2(X_o)) + 2
        uniform_temp = max(0, math.ceil(math.log2(X_o)) - 2)
        persistent_qrom_out_superposition_reg = b1 + b_k1
        k = QR(X_o, b1)[0]
        qrom_temp = math.ceil(math.log2(X_o / 2**k)) + 2**k * b1
        return {
            "persistent": persistent_qrom_out_superposition_reg + uniform_persistent,
            "temporary": qrom_temp + uniform_temp,
            "qrom_temp": qrom_temp,
            "qrom_persistent": persistent_qrom_out_superposition_reg,
            "uniform_temp": uniform_temp,
            "uniform_persistent": uniform_persistent,
        }

    def inner_state_prep_qubit_cost(self) -> dict[str, int]:
        b_k2 = self.chi
        b2 = math.ceil(math.log2(self.B)) + b_k2 + 1
        k2_opt = QR(self.R * self.C * self.B, b2)[0]

        if self.optimize_qubits:
            k2_opt = self.find_qroam_size_to_minimize_global_temp_ancilla(b2)

        RC = self.R * self.C
        persistent_uniform = math.ceil(math.log2(self.B + 1)) + 2
        temporary_uniform = max(0, math.ceil(math.log2(self.B + 1)) - 2)
        persistent_for_qroam = b2 + b_k2 + math.ceil(math.log2(self.R)) + 2
        temporary_for_qroam = math.ceil(math.log2(RC * math.ceil((self.B + 1) / 2**k2_opt))) + ((2**k2_opt) - 1) * b2

        return {
            "persistent": persistent_for_qroam + persistent_uniform,
            "temporary": temporary_uniform + temporary_for_qroam,
            "uniform_persistant": persistent_uniform,
            "uniform_temporary": temporary_uniform,
            "persistent_for_qroam": persistent_for_qroam,
            "temporary_for_qroam": temporary_for_qroam,
        }


__all__ = ["QI", "QR", "SpinFreeData_V1"]

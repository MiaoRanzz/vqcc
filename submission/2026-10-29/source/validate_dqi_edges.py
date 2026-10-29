"""Independent singleton/zero boundary checks using the competition verifier."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "kickmix"), str(ROOT / "verifiers")]
import kickmix as km
import numpy as np
from dqi.verify_submission_dqi import FieldTables, ProblemSpecDQI, verify

spec = ProblemSpecDQI.benchmark_instance(num_shots=4096)
field = km.GF2Field(spec.degree)
tables = FieldTables(field)
rng = np.random.default_rng(20261029)
syndromes = np.zeros((4096, spec.n), dtype=np.int64)
masks = rng.integers(0, spec.q, size=(4096, spec.m), dtype=np.int64)
phases = np.zeros(4096, dtype=bool)
for position in range(spec.m):
    shot = position + 1
    value = int(rng.integers(1, spec.q))
    for i in range(spec.n):
        syndromes[shot, i] = field.mul(value, int(tables.antilog[((i + 1) * position) % spec.m]))
    phases[shot] = (value & int(masks[shot, position])).bit_count() & 1
summary = verify(
    km.Circuit.from_file(HERE.parent / "files/dqi.kmb"), spec,
    shots=(syndromes, masks, phases), max_workers=4, salt="edge-coverage-2026-10-29",
)
assert summary["value_errors"] == summary["phase_errors"] == 0, summary
summary["test_distribution"] = "zero error plus one nonzero error at each of all 4095 positions; independent random masks"
print(json.dumps(summary, indent=2))

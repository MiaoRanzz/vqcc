"""Safety and arithmetic invariants of candidate-generation entrypoints."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_generators", ROOT / "generators/generate.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class GeneratorTests(unittest.TestCase):
    def test_history_and_reference_paths_rejected_including_alias(self):
        for name in ("submission/2026-10-29/files", "sample_submission", "verifiers"):
            with self.assertRaises(ValueError):
                gen.check_output(ROOT / name)
        with tempfile.TemporaryDirectory() as tmp:
            alias = Path(tmp) / "historical-alias"
            alias.symlink_to(ROOT / "submission", target_is_directory=True)
            with self.assertRaises(ValueError):
                gen.check_output(alias / "new-version")

    def test_existing_candidate_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with gen.output_workspace(output) as (_, stage):
                (stage / "invsqrt.kmb").write_bytes(b"frozen circuit")
            with self.assertRaises(FileExistsError):
                with gen.output_workspace(output):
                    self.fail("An existing artifact must never be replaced")
            self.assertEqual((output / "invsqrt.kmb").read_bytes(), b"frozen circuit")

    def test_failed_build_does_not_publish_partial_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with self.assertRaises(RuntimeError):
                with gen.output_workspace(output) as (_, stage):
                    (stage / "dqi.kmb").write_bytes(b"partial")
                    raise RuntimeError("simulated generator failure")
            self.assertEqual(list(output.iterdir()), [])

    def test_angle_precision_round_trip_and_periodic_wrap(self):
        import numpy as np
        words = np.arange(4096, dtype=np.int64).reshape(64, 64)
        raised = gen.requantize_words(words, 12, 15)
        np.testing.assert_array_equal(gen.requantize_words(raised, 15, 12), words)
        # Angle values approaching the period round back to zero; truncating
        # without wrapping would create an illegal word equal to 2**brot.
        self.assertEqual(int(gen.requantize_words(np.array([[4095]]), 12, 11)[0, 0]), 0)
        with self.assertRaises(ValueError):
            gen.requantize_words(np.array([[4096]]), 12, 11)

    def test_default_invsqrt_model_covers_competition_domain(self):
        from invsqrt.nr_reference_circuit import Precision
        result = gen.numeric_screen(Precision())
        self.assertEqual(result["inputs"], 3133452)
        self.assertEqual(result["worst_x"], 2588411)
        self.assertTrue(result["passes_model_tolerance"])
        self.assertFalse(result["official_validation"])

    def test_insufficient_precision_is_rejected_by_model(self):
        from invsqrt.nr_reference_circuit import Precision
        result = gen.numeric_screen(Precision(result_bits=20))
        self.assertFalse(result["passes_model_tolerance"])


if __name__ == "__main__":
    unittest.main()

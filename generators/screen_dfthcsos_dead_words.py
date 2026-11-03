# Screen for "dead" DFTHC-SOS angle words: words whose Givens rotation acts on a
# zero-amplitude branch, so their value cannot affect lambda_eff/e1/e2/E_gap.
# Screen only (no candidates built). Part of the VQCC project. License: Apache-2.0.
# Method: (1) structural - replay verifier's reconstruct_u_vectors and flag word
# (a, i) when parent and child amplitudes before rotation i are both |.|<=tol;
# (2) empirical - for every flagged word, replace the WHOLE word (complement of
# all brot bits, and 0) and re-run the official evaluate_words; dead iff
# lambda_eff, error_1, error_2, E_gap and pass/fail are bit-identical. Also a
# few random non-flagged control words. Official verifier code is imported read-only.
import argparse, hashlib, json, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verifiers"))
sys.path.insert(0, str(ROOT / "kickmix"))
from dfthcsos import verify as V  # noqa: E402

KEYS = ("lambda_eff", "error_1", "error_2", "E_gap")


def fingerprint(m):
    out = {k: float(m[k]) for k in KEYS if k in m}
    out["pass"] = bool(V.passes_accuracy(m))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tol", type=float, default=1e-12)
    ap.add_argument("--controls", type=int, default=20)
    ap.add_argument("--max-empirical", type=int, default=400)
    a = ap.parse_args()
    t0 = time.time()
    sha = hashlib.sha256(a.npz.read_bytes()).hexdigest()
    with np.load(a.npz, allow_pickle=False) as d:
        words = np.array(d["angle_words"]); edges = np.array(d["tree_edges"]); brot = int(d["brot"])
    inputs = V.load_inputs(a.npz)
    base = fingerprint(V.evaluate_words(inputs, words, edges, brot))
    t_eval = time.time()
    _ = V.evaluate_words(inputs, words, edges, brot)
    t_eval = time.time() - t_eval
    # structural replay (same arithmetic as reconstruct_u_vectors)
    nv, na = words.shape
    vec = np.zeros((nv, na + 1)); vec[:, 0] = 1.0
    th = words / (1 << (brot - 1))
    minamp = np.zeros((nv, na))
    for i, (p, c) in enumerate(edges):
        pv, cv = vec[:, p].copy(), vec[:, c].copy()
        minamp[:, i] = np.maximum(np.abs(pv), np.abs(cv))
        t = np.pi * th[:, i]
        vec[:, p] = np.cos(t) * pv - np.sin(t) * cv
        vec[:, c] = np.sin(t) * pv + np.cos(t) * cv
    exact_zero = minamp == 0.0
    flagged = minamp <= a.tol
    J = 5  # J5 loaders: circuit k loads columns 5k..5k+4 (batch_size from register layout)
    nslots = int(np.ceil(na / J))
    idx = np.argwhere(flagged)
    rng = np.random.default_rng(0)
    nonflag = np.argwhere(~flagged)
    ctrl = nonflag[rng.choice(len(nonflag), size=min(a.controls, len(nonflag)), replace=False)]
    emp = []
    mask = (1 << brot) - 1
    for kind, lst in (("flagged", idx[: a.max_empirical]), ("control", ctrl)):
        for r, i in lst:
            res = {"row": int(r), "col": int(i), "kind": kind, "max_amp": float(minamp[r, i])}
            same_all = True
            for name, val in (("complement", int(words[r, i]) ^ mask), ("zero", 0)):
                if val == words[r, i]:
                    continue
                w2 = words.copy(); w2[r, i] = val
                fp = fingerprint(V.evaluate_words(inputs, w2, edges, brot))
                same = fp == base
                res[name + "_identical"] = same
                same_all &= same
            res["dead_empirical"] = bool(same_all)
            emp.append(res)
    per_slot = []
    for k in range(nslots):
        cols = list(range(J * k, min(J * (k + 1), na)))
        sub = flagged[:, cols]
        per_slot.append({
            "slot": k, "columns": cols,
            "dead_words_structural": int(sub.sum()),
            "exact_zero_words": int(exact_zero[:, cols].sum()),
            "rows_with_any_dead": int(sub.any(axis=1).sum()),
            "dead_bits_structural": int(sub.sum()) * brot,
            "indices_row_col": [[int(r), int(c)] for r, c in np.argwhere(flagged[:, cols]) + [0, cols[0]]],
        })
    flag_emp = [e for e in emp if e["kind"] == "flagged"]
    report = {
        "npz": str(a.npz), "npz_sha256": sha, "brot": brot, "shape": [nv, na], "J": J,
        "method": ("structural replay of verifier Givens reconstruction (word dead if parent and child "
                   f"amplitudes before its rotation are <= tol={a.tol}); empirical confirmation by whole-word "
                   "replacement (bit-complement and zero) through official verify.evaluate_words, bit-identical "
                   "lambda_eff/error_1/error_2/E_gap/pass"),
        "baseline": base,
        "total_dead_words_structural": int(flagged.sum()),
        "total_exact_zero_words": int(exact_zero.sum()),
        "amp_histogram_log10": {f"<=1e{e}": int((minamp <= 10.0 ** e).sum()) for e in (-15, -12, -9, -6, -3)},
        "per_slot": per_slot,
        "empirical": {"tested_flagged": len(flag_emp),
                      "flagged_confirmed_dead": sum(e["dead_empirical"] for e in flag_emp),
                      "controls_tested": len(emp) - len(flag_emp),
                      "controls_identical": sum(e["dead_empirical"] for e in emp if e["kind"] == "control"),
                      "details": emp},
        "seconds_per_evaluate_words": t_eval,
        "runtime_seconds": time.time() - t0,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("total_dead_words_structural", "total_exact_zero_words",
          "amp_histogram_log10", "runtime_seconds", "seconds_per_evaluate_words")}))
    print("per-slot dead:", [s["dead_words_structural"] for s in per_slot])
    print("empirical:", {k: v for k, v in report["empirical"].items() if k != "details"})


if __name__ == "__main__":
    main()

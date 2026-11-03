// SPDX-License-Identifier: Apache-2.0
// Peak-instant release screen for a DQI KickMix circuit, on lane-simulation
// snapshots written by dqi_lane_sim (SNAP_OPS/SNAP_OUT, LANE_WORDS=W).
//
// For every snapshot (state of all nq wires on 64*W sampled reachable shots)
// it reports, per instant:
//  * rank of {wire vectors} + all-ones over GF(2); every wire that lies in a
//    sampled null-space vector ("affine candidates", 0-Toffoli CX release).
//    Full rank is an exact disproof of any affine release at that instant.
//  * functional-collision test: wire w is "info-blocked" when two sampled
//    lanes agree on every other wire but differ on w. Then w is not any
//    function of the remaining wires, so NO release of w at this instant is
//    possible (reversible information argument), at any Toffoli cost.
//    A wire that is not blocked is only a candidate (samples cannot prove).
//  * quadratic test (optional, QUAD=1): pairs (a,b) of wires with
//    a&b in span(wires + 1) whose representation uses some wire w not in
//    {a,b}: w = a&b + affine(others) on all samples, i.e. a 1-Toffoli
//    (MBU erase + CCX recompute) candidate. Membership uses 64 random dual
//    vectors (false-positive rate 2^-64 per pair; hits are re-checked exactly).
//
// usage: dqi_peak_relations snap.bin nq out.tsv [first_record count]
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>
#ifndef LANE_WORDS
#define LANE_WORDS 64
#endif
constexpr int W = LANE_WORDS;
#ifndef LIST_MAX
#define LIST_MAX 40
#endif
using u64 = uint64_t;
static inline int par(u64 x) { return __builtin_parityll(x); }

int main(int argc, char** argv) try {
    if (argc != 4 && argc != 6) throw std::runtime_error("usage");
    const int nq = std::stoi(argv[2]);
    const bool quad = std::getenv("QUAD") && std::string(std::getenv("QUAD")) == "1";
    const size_t rec = 1 + size_t(nq) * W;
    std::ifstream in(argv[1], std::ios::binary);
    in.seekg(0, std::ios::end); size_t nrec = size_t(in.tellg()) / (8 * rec); in.seekg(0);
    size_t first = 0, cnt = nrec;
    if (argc == 6) { first = std::stoull(argv[4]); cnt = std::stoull(argv[5]); }
    if (first > nrec) first = nrec;
    if (first + cnt > nrec) cnt = nrec - first;
    in.seekg(8 * rec * first);
    std::ofstream out(argv[3]);
    out << "op\tlive\trank\tnullity\taffine_candidates\tnot_info_blocked\tquad_pairs\tquad_wires\n";
    const int nv = nq + 1, CW = (nv + 63) / 64;
    std::vector<u64> buf(rec);
    for (size_t r = 0; r < cnt; r++) {
        in.read((char*)buf.data(), 8 * rec);
        u64 op = buf[0];
        std::vector<std::array<u64, W>> v(nv);
        for (int q = 0; q < nq; q++) std::memcpy(v[q].data(), &buf[1 + size_t(q) * W], 8 * W);
        v[nq].fill(~0ULL);
        int live = 0; std::vector<char> islive(nq, 0);
        for (int q = 0; q < nq; q++) { u64 x = 0; for (int k = 0; k < W; k++) x |= v[q][k]; if (x) { islive[q] = 1; live++; } }
        // Gaussian elimination with combination tracking (rows = vectors).
        std::vector<std::array<u64, W>> red(nv); std::vector<std::vector<u64>> comb(nv, std::vector<u64>(CW, 0));
        std::vector<int> pivcol(nv, -1); std::vector<int> pivrow_of_col(64 * W, -1);
        std::vector<std::vector<u64>> nulls;
        for (int i = 0; i < nv; i++) {
            auto x = v[i]; std::vector<u64> c(CW, 0); c[i / 64] |= 1ULL << (i % 64);
            for (;;) {
                int p = -1; for (int k = W - 1; k >= 0; k--) if (x[k]) { p = 64 * k + 63 - __builtin_clzll(x[k]); break; }
                if (p < 0) { nulls.push_back(c); break; }
                int pr = pivrow_of_col[p];
                if (pr < 0) { red[i] = x; comb[i] = c; pivcol[i] = p; pivrow_of_col[p] = i; break; }
                for (int k = 0; k < W; k++) x[k] ^= red[pr][k];
                for (int k = 0; k < CW; k++) c[k] ^= comb[pr][k];
            }
        }
        int rank = 0; for (int i = 0; i < nv; i++) if (pivcol[i] >= 0) rank++;
        std::vector<char> affine(nq, 0);
        for (auto& c : nulls) for (int q = 0; q < nq; q++) if (c[q / 64] >> (q % 64) & 1) affine[q] = 1;
        int naff = 0; std::string affs;
        for (int q = 0; q < nq; q++) if (affine[q] && islive[q]) { naff++; if (naff <= LIST_MAX) affs += (affs.empty() ? "" : ",") + std::to_string(q); }
        // Functional collision test: lane columns.
        const int L = 64 * W, QW = (nq + 63) / 64;
        std::vector<std::vector<u64>> col(L, std::vector<u64>(QW, 0));
        for (int q = 0; q < nq; q++) for (int l = 0; l < L; l++) if (v[q][l / 64] >> (l % 64) & 1) col[l][q / 64] |= 1ULL << (q % 64);
        auto h = [&](const std::vector<u64>& c) { u64 s = 1469598103934665603ULL; for (u64 w : c) { s ^= w; s *= 1099511628211ULL; s ^= s >> 29; } return s; };
        std::unordered_multimap<u64, int> idx; idx.reserve(2 * L);
        for (int l = 0; l < L; l++) idx.emplace(h(col[l]), l);
        std::vector<char> blocked(nq, 0);
        for (int l = 0; l < L; l++) for (int q = 0; q < nq; q++) {
            if (blocked[q] || !islive[q]) continue;
            auto c = col[l]; c[q / 64] ^= 1ULL << (q % 64);
            auto range = idx.equal_range(h(c));
            for (auto it = range.first; it != range.second; ++it) if (col[it->second] == c) { blocked[q] = 1; break; }
        }
        int nfree = 0; std::string frees;
        for (int q = 0; q < nq; q++) if (islive[q] && !blocked[q]) { nfree++; if (nfree <= LIST_MAX) frees += (frees.empty() ? "" : ",") + std::to_string(q); }
        // Quadratic test.
        long qpairs = 0; std::string qw;
        if (quad) {
            // Dual vectors: h with <h, v_i> = 0 for all i. Build RREF over pivot columns.
            std::vector<int> prow; for (int i = 0; i < nv; i++) if (pivcol[i] >= 0) prow.push_back(i);
            std::vector<std::array<u64, W>> R; std::vector<int> pc;
            for (int i : prow) { R.push_back(red[i]); pc.push_back(pivcol[i]); }
            // full back-substitution so each pivot column appears in one row only
            for (size_t a = 0; a < R.size(); a++) for (size_t b = 0; b < R.size(); b++) if (a != b && (R[b][pc[a] / 64] >> (pc[a] % 64) & 1)) for (int k = 0; k < W; k++) R[b][k] ^= R[a][k];
            std::array<u64, W> pivmask{}; for (int p : pc) pivmask[p / 64] |= 1ULL << (p % 64);
            std::mt19937_64 rng(0x5EED0000ULL + op);
            const int H = 64; std::vector<std::array<u64, W>> hs(H);
            for (int j = 0; j < H; j++) {
                std::array<u64, W> hv; for (int k = 0; k < W; k++) hv[k] = rng() & ~pivmask[k];
                for (size_t a = 0; a < R.size(); a++) { int s = 0; for (int k = 0; k < W; k++) s ^= par(R[a][k] & hv[k]); if (s) hv[pc[a] / 64] |= 1ULL << (pc[a] % 64); }
                hs[j] = hv;
            }
            // pre-mask: hv&a for each wire, then parity(hv&a&b)
            std::vector<int> lw; for (int q = 0; q < nq; q++) if (islive[q]) lw.push_back(q);
            std::vector<std::array<u64, W>> ha(size_t(lw.size()) * H);
            for (size_t i = 0; i < lw.size(); i++) for (int j = 0; j < H; j++) for (int k = 0; k < W; k++) ha[i * H + j][k] = hs[j][k] & v[lw[i]][k];
            std::vector<char> qhit(nq, 0);
            for (size_t i = 0; i < lw.size(); i++) for (size_t j2 = i + 1; j2 < lw.size(); j2++) {
                int a = lw[i], b = lw[j2]; bool in_span = true;
                for (int j = 0; j < H && in_span; j++) { u64 s = 0; for (int k = 0; k < W; k++) s ^= ha[i * H + j][k] & v[b][k]; if (par(s)) in_span = false; }
                if (!in_span) continue;
                // exact representation of p=a&b
                std::array<u64, W> x; for (int k = 0; k < W; k++) x[k] = v[a][k] & v[b][k];
                std::vector<u64> c(CW, 0); bool ok = true;
                for (;;) {
                    int p = -1; for (int k = W - 1; k >= 0; k--) if (x[k]) { p = 64 * k + 63 - __builtin_clzll(x[k]); break; }
                    if (p < 0) break;
                    int pr = pivrow_of_col[p]; if (pr < 0) { ok = false; break; }
                    for (int k = 0; k < W; k++) x[k] ^= red[pr][k];
                    for (int k = 0; k < CW; k++) c[k] ^= comb[pr][k];
                }
                if (!ok) continue;
                // wires usable as w: in representation (or any null-space-supported wire, already affine), excluding a,b
                bool any = false;
                for (int q = 0; q < nq; q++) if (q != a && q != b && (c[q / 64] >> (q % 64) & 1) && islive[q] && !blocked[q]) { qhit[q] = 1; any = true; }
                if (any) qpairs++;
            }
            int nh = 0; for (int q = 0; q < nq; q++) if (qhit[q]) { nh++; if (nh <= LIST_MAX) qw += (qw.empty() ? "" : ",") + std::to_string(q); }
            qw = std::to_string(nh) + ":" + qw;
        }
        out << op << '\t' << live << '\t' << rank << '\t' << nulls.size() << '\t' << naff << ':' << affs << '\t' << nfree << ':' << frees << '\t' << (quad ? std::to_string(qpairs) : "-") << '\t' << (quad ? qw : "-") << '\n';
        out.flush();
    }
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }

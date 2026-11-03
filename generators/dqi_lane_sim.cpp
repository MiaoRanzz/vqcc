// SPDX-License-Identifier: Apache-2.0
// Bit-parallel classical simulation of a version-2 KickMix DQI circuit on
// 256 sampled basis-state shots, for liveness profiling only (no phase).
// Independent implementation; opcode layout matches dqi_boolean_screen.cpp.
// A qubit counts as live at an op when it is nonzero in at least one lane:
// this is a LOWER bound on structural liveness, never a proof of zero.
//
// usage: dqi_lane_sim circuit.kmb inputs.bin transitions.bin summary.json
//        [access_lo access_hi wires.txt accesses.bin]
// inputs.bin: u32 lanes(=256), u32 nregs_used; then for each S/E register
// value: u32 kind(0=S,1=E) u32 index, then 256 u32 values.
#include <array>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef LANE_WORDS
#define LANE_WORDS 4
#endif
constexpr int W = LANE_WORDS;  // W x 64 lanes
using L = std::array<uint64_t, W>;
static inline L land(const L& a, const L& b) { L r; for (int i = 0; i < W; i++) r[i] = a[i] & b[i]; return r; }
static inline bool any(const L& a) { uint64_t x = 0; for (int i = 0; i < W; i++) x |= a[i]; return x != 0; }
struct File {
    std::vector<uint8_t> raw; size_t pos = 0;
    explicit File(const char* p) { std::ifstream f(p, std::ios::binary); if (!f) throw std::runtime_error("open");
        f.seekg(0, std::ios::end); raw.resize(f.tellg()); f.seekg(0); f.read((char*)raw.data(), raw.size()); }
    template <class T> T get() { T v; std::memcpy(&v, raw.data() + pos, sizeof(T)); pos += sizeof(T); return v; }
    size_t packet(uint64_t type, uint64_t bytes) { if (get<uint64_t>() != type || get<uint64_t>() != bytes) throw std::runtime_error("packet"); size_t p = pos; pos += bytes; return p; }
    uint32_t operand(size_t off, size_t i) const { uint32_t v; std::memcpy(&v, raw.data() + off + 4 * i, 4); return v; }
};
static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static inline uint64_t rnd() { rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17; return rng_state; }
int main(int argc, char** argv) try {
    if (argc != 5 && argc != 9) throw std::runtime_error("usage");
    File f(argv[1]);
    f.pos = 16; if (f.get<uint32_t>() != 2) throw std::runtime_error("version");
    uint32_t nq = f.get<uint32_t>(), nb = f.get<uint32_t>(), nr = f.get<uint32_t>();
    std::array<uint64_t, 9> count; for (auto& n : count) n = f.get<uint64_t>();
    std::vector<L> qs(nq, L{}), bs(nb, L{});
    std::map<std::string, std::vector<uint32_t>> regs;
    std::vector<uint8_t> is_s(nq, 0);
    for (uint32_t r = 0; r < nr; r++) {
        f.get<uint64_t>(); f.get<uint64_t>(); auto namelen = f.get<uint32_t>(), len = f.get<uint32_t>();
        std::string name((char*)f.raw.data() + f.pos, namelen); f.pos += namelen;
        auto& v = regs[name]; for (uint32_t j = 0; j < len; j++) v.push_back(f.get<uint32_t>());
    }
    // inputs
    std::ifstream in(argv[2], std::ios::binary); uint32_t lanes, nvals; in.read((char*)&lanes, 4); in.read((char*)&nvals, 4);
    if (lanes != 64 * W) throw std::runtime_error("lanes");
    std::map<std::string, std::vector<uint32_t>> initial;
    for (uint32_t k = 0; k < nvals; k++) {
        uint32_t kind, idx; in.read((char*)&kind, 4); in.read((char*)&idx, 4);
        std::vector<uint32_t> vals(lanes); in.read((char*)vals.data(), 4 * lanes);
        std::string name = (kind == 0 ? "S" : "E") + std::to_string(idx);
        auto& wires = regs.at(name);
        for (size_t j = 0; j < wires.size(); j++) {
            L v{}; for (uint32_t l = 0; l < lanes; l++) if (vals[l] >> j & 1) v[l / 64] |= 1ULL << (l % 64);
            uint32_t w = wires[j];
            if (w & 0x80000000u) { qs[w & 0x7fffffff] = v; } else bs[w] = v;
        }
        if (kind == 0) initial[name] = vals;
    }
    if (!in) throw std::runtime_error("inputs");
    for (auto& [name, wires] : regs) if (name[0] == 'S') for (auto w : wires) is_s[w & 0x7fffffff] = 1;
    size_t ot = f.packet(1, count[0]); std::array<size_t, 8> off; std::array<int, 8> groups = {1, 1, 1, 2, 2, 3, 4, 5};
    for (int j = 0; j < 8; j++) off[j] = f.packet(2 + j, 4 * count[groups[j]]);
    std::array<size_t, 6> ix{};
    std::vector<L> stack; L all; all.fill(~0ULL); stack.push_back(all);
    std::vector<uint8_t> live(nq, 0); uint32_t nlive = 0, peak = 0; uint64_t peak_first = 0, peak_last = 0, peak_ops = 0;
    for (uint32_t q = 0; q < nq; q++) if (any(qs[q])) { live[q] = 1; nlive++; }
    std::ofstream tr(argv[3], std::ios::binary);
    auto emit = [&](uint64_t op, uint32_t q, uint8_t s) { uint64_t rec = (op << 12) | (uint64_t(q) << 1) | s; tr.write((char*)&rec, 8); };
    for (uint32_t q = 0; q < nq; q++) if (live[q]) emit(0, q, 1);
    // access dump
    uint64_t alo = 0, ahi = 0; std::vector<uint8_t> watch(nq, 0); std::ofstream acc;
    if (argc == 9) { alo = std::stoull(argv[5]); ahi = std::stoull(argv[6]); std::ifstream wl(argv[7]); uint32_t w; while (wl >> w) watch[w] = 1; acc.open(argv[8], std::ios::binary); }
    uint64_t ccx_lane_total = 0;
    // Optional snapshots: env SNAP_OPS (sorted op indices) -> SNAP_OUT; each
    // record is the op index then nq*W words of qubit lanes before that op.
    std::vector<uint64_t> snaps; size_t snap_ix = 0; std::ofstream snap_out;
    if (const char* so = std::getenv("SNAP_OPS")) { std::ifstream sf(so); uint64_t v; while (sf >> v) snaps.push_back(v); snap_out.open(std::getenv("SNAP_OUT"), std::ios::binary); }
    for (uint64_t i = 0; i < count[0]; i++) {
        while (snap_ix < snaps.size() && snaps[snap_ix] == i) { snap_out.write((char*)&i, 8); for (uint32_t qq = 0; qq < nq; qq++) snap_out.write((char*)qs[qq].data(), 8 * W); snap_ix++; }
        uint8_t t = f.raw[ot + i], base = t & 0x7f; unsigned arity = (t >> 4) & 3;
        uint32_t q[3] = {0, 0, 0};
        int stream = arity == 3 ? 0 : arity == 2 ? 3 : 5;
        for (unsigned j = 0; j < arity; j++) q[j] = f.operand(off[stream + j], ix[arity == 3 ? 1 : arity == 2 ? 2 : 3]);
        if (arity) ix[arity == 3 ? 1 : arity == 2 ? 2 : 3]++;
        uint32_t bit = 0, cond = 0;
        if (t & 0x40) bit = f.operand(off[6], ix[4]++);
        if (t & 0x80) cond = f.operand(off[7], ix[5]++);
        if (t == 0x81) { stack.push_back(land(stack.back(), bs[cond])); continue; }
        if (t == 0x01) { stack.pop_back(); continue; }
        L m = stack.back(); if (t & 0x80) m = land(m, bs[cond]);
        if (argc == 9 && i >= alo && i < ahi) for (unsigned j = 0; j < arity; j++) if (watch[q[j]]) {
            uint64_t rec[2] = {i, (uint64_t(t) << 40) | (uint64_t(j) << 32) | q[j]}; acc.write((char*)rec, 16); }
        bool active = any(m);
        int changed[2] = {-1, -1};
        switch (base) {
        case 0x00: case 0x06: case 0x10: case 0x20: case 0x30: break;
        case 0x11: for (int k = 0; k < W; k++) qs[q[0]][k] ^= m[k]; changed[0] = q[0]; break;
        case 0x12: for (int k = 0; k < W; k++) qs[q[0]][k] &= ~m[k]; changed[0] = q[0]; break;
        case 0x50: for (int k = 0; k < W; k++) { uint64_t r = rnd(); bs[bit][k] = (bs[bit][k] & ~m[k]) | (r & m[k]); qs[q[0]][k] &= ~m[k]; } changed[0] = q[0]; break;
        case 0x40: for (int k = 0; k < W; k++) bs[bit][k] &= ~m[k]; break;
        case 0x41: for (int k = 0; k < W; k++) bs[bit][k] |= m[k]; break;
        case 0x42: for (int k = 0; k < W; k++) bs[bit][k] ^= m[k]; break;
        case 0x21: for (int k = 0; k < W; k++) qs[q[1]][k] ^= qs[q[0]][k] & m[k]; changed[0] = q[1]; break;
        case 0x22: for (int k = 0; k < W; k++) { uint64_t d = (qs[q[0]][k] ^ qs[q[1]][k]) & m[k]; qs[q[0]][k] ^= d; qs[q[1]][k] ^= d; } changed[0] = q[0]; changed[1] = q[1]; break;
        case 0x31: for (int k = 0; k < W; k++) qs[q[2]][k] ^= qs[q[0]][k] & qs[q[1]][k] & m[k]; changed[0] = q[2]; if (active) ccx_lane_total++; break;
        case 0x32: for (int k = 0; k < W; k++) { uint64_t d = (qs[q[1]][k] ^ qs[q[2]][k]) & qs[q[0]][k] & m[k]; qs[q[1]][k] ^= d; qs[q[2]][k] ^= d; } changed[0] = q[1]; changed[1] = q[2]; break;
        default: throw std::runtime_error("opcode " + std::to_string(t));
        }
        for (int c : changed) if (c >= 0) {
            uint8_t now = any(qs[c]);
            if (now != live[c]) { live[c] = now; nlive += now ? 1 : -1; emit(i + 1, c, now); }
        }
        if (nlive > peak) { peak = nlive; peak_first = i + 1; peak_last = i + 1; peak_ops = 0; }
        if (nlive == peak) { peak_last = i + 1; peak_ops++; }
    }
    // sanity: S restored, ancillas zero
    uint64_t s_bad = 0, anc_bad = 0;
    for (auto& [name, vals] : initial) { auto& wires = regs.at(name); for (size_t j = 0; j < wires.size(); j++) { L e{}; for (uint32_t l = 0; l < lanes; l++) if (vals[l] >> j & 1) e[l / 64] |= 1ULL << (l % 64); if (e != qs[wires[j] & 0x7fffffff]) s_bad++; } }
    for (uint32_t qq = 0; qq < nq; qq++) if (!is_s[qq] && any(qs[qq])) anc_bad++;
    std::ofstream out(argv[4]);
    out << "{\"operations\":" << count[0] << ",\"qubits\":" << nq << ",\"lanes\":" << lanes << ",\"sampled_peak_live\":" << peak
        << ",\"peak_first_op\":" << peak_first << ",\"peak_last_op\":" << peak_last << ",\"ops_at_peak\":" << peak_ops
        << ",\"s_wire_mismatch\":" << s_bad << ",\"ancilla_nonzero_at_end\":" << anc_bad << ",\"active_ccx_ops\":" << ccx_lane_total << "}\n";
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }

// SPDX-License-Identifier: Apache-2.0
// Conservative proof of qubit zeroness for a version-2 KickMix circuit.
// Every qubit and classical bit is an XOR of atoms (atom 0 = constant 1).
// Products are opaque hash-consed atoms; HMR outcomes and expression
// overflows are fresh atoms. Classical guards are folded in exactly as
// products with the guard expression, so a guarded gate applied twice under
// the same captured guard cancels. An empty expression proves the qubit is
// |0> on every input; a non-empty one is merely "not proven zero".
//
// usage: dqi_proven_live circuit.kmb transitions.bin summary.json [cap]
// transitions: u64 records (op<<12 | wire<<1 | nonzero) where op is the
// index of the first operation executed with the new status.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
// Product atoms are keyed by a 128-bit digest of the sorted operand pair.
// A digest collision (probability ~n^2/2^128) is the only unsound step.
static inline uint64_t mix(uint64_t x) { x += 0x9e3779b97f4a7c15ULL; x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL; x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL; return x ^ (x >> 31); }
struct Digest { uint64_t h1, h2; bool operator==(const Digest& o) const { return h1 == o.h1 && h2 == o.h2; } bool operator<(const Digest& o) const { return h1 < o.h1 || (h1 == o.h1 && h2 < o.h2); } };
static Digest digest(const std::vector<uint32_t>& v) { uint64_t a = 0x1234567ULL ^ v.size(), b = 0x89abcdefULL + v.size(); for (auto x : v) { a = mix(a ^ x); b = mix(b + x * 0x2545F4914F6CDD1DULL); } return {a, b}; }
struct DHash { size_t operator()(const Digest& d) const { return d.h1; } };
using Expr = std::vector<uint32_t>;
// Products are flattened, idempotent factor sets: x*x = x, x*(x*y) = x*y,
// x*(x+1) = 0. Each non-product factor is identified by its digest.
struct Factor { Digest d, complement; };
struct Algebra {
    uint32_t next = 1; size_t cap; uint64_t overflows = 0;
    std::unordered_map<Digest, uint32_t, DHash> products;
    std::unordered_map<uint32_t, std::vector<Factor>> factor_sets;
    explicit Algebra(size_t c) : cap(c) {}
    Expr fresh() { if (next == UINT32_MAX) throw std::runtime_error("atom overflow"); return {next++}; }
    Expr add(const Expr& a, const Expr& b) {
        if (a.empty()) return b; if (b.empty()) return a;
        Expr c; c.reserve(a.size() + b.size());
        std::set_symmetric_difference(a.begin(), a.end(), b.begin(), b.end(), std::back_inserter(c));
        if (c.size() > cap) { ++overflows; return fresh(); }
        return c;
    }
    std::vector<Factor> factors(const Expr& e) {
        if (e.size() == 1) { auto it = factor_sets.find(e[0]); if (it != factor_sets.end()) return it->second; }
        Expr c = add(e, Expr{0});
        return {Factor{digest(e), digest(c)}};
    }
    Expr mul(const Expr& a, const Expr& b) {
        if (a.empty() || b.empty()) return {};
        if (a == Expr{0} || a == b) return b;
        if (b == Expr{0}) return a;
        auto fa = factors(a), fb = factors(b);
        std::vector<Factor> f = fa; f.insert(f.end(), fb.begin(), fb.end());
        std::sort(f.begin(), f.end(), [](const Factor& x, const Factor& y) { return x.d < y.d; });
        f.erase(std::unique(f.begin(), f.end(), [](const Factor& x, const Factor& y) { return x.d == y.d; }), f.end());
        for (auto& x : f) for (auto& y : f) if (x.complement == y.d) return {};
        if (f.size() == fa.size()) return a;   // b's factors are a subset of a's
        if (f.size() == fb.size()) return b;
        std::vector<uint32_t> words; words.reserve(4 * f.size());
        for (auto& x : f) { words.push_back(uint32_t(x.d.h1)); words.push_back(uint32_t(x.d.h1 >> 32)); words.push_back(uint32_t(x.d.h2)); words.push_back(uint32_t(x.d.h2 >> 32)); }
        Digest key = digest(words);
        auto [it, inserted] = products.emplace(key, 0);
        if (inserted) { it->second = fresh()[0]; factor_sets.emplace(it->second, std::move(f)); }
        return {it->second};
    }
};
struct File {
    std::vector<uint8_t> raw; size_t pos = 0;
    explicit File(const char* p) { std::ifstream f(p, std::ios::binary); if (!f) throw std::runtime_error("open");
        f.seekg(0, std::ios::end); raw.resize(f.tellg()); f.seekg(0); f.read((char*)raw.data(), raw.size()); }
    template <class T> T get() { T v; std::memcpy(&v, raw.data() + pos, sizeof(T)); pos += sizeof(T); return v; }
    size_t packet(uint64_t type, uint64_t bytes) { if (get<uint64_t>() != type || get<uint64_t>() != bytes) throw std::runtime_error("packet"); size_t p = pos; pos += bytes; return p; }
    uint32_t operand(size_t off, size_t i) const { uint32_t v; std::memcpy(&v, raw.data() + off + 4 * i, 4); return v; }
};
int main(int argc, char** argv) try {
    if (argc < 4) throw std::runtime_error("usage");
    File f(argv[1]); f.pos = 16; if (f.get<uint32_t>() != 2) throw std::runtime_error("version");
    uint32_t nq = f.get<uint32_t>(), nb = f.get<uint32_t>(), nr = f.get<uint32_t>();
    std::array<uint64_t, 9> count; for (auto& n : count) n = f.get<uint64_t>();
    Algebra alg(argc > 4 ? std::stoul(argv[4]) : 256);
    std::vector<Expr> qs(nq), bs(nb);
    for (uint32_t r = 0; r < nr; r++) {
        f.get<uint64_t>(); f.get<uint64_t>(); auto namelen = f.get<uint32_t>(), len = f.get<uint32_t>(); f.pos += namelen;
        for (uint32_t j = 0; j < len; j++) { auto v = f.get<uint32_t>(); if (v & 0x80000000u) qs[v & 0x7fffffff] = alg.fresh(); else bs[v] = alg.fresh(); }
    }
    size_t ot = f.packet(1, count[0]); std::array<size_t, 8> off; std::array<int, 8> groups = {1, 1, 1, 2, 2, 3, 4, 5};
    for (int j = 0; j < 8; j++) off[j] = f.packet(2 + j, 4 * count[groups[j]]);
    std::array<size_t, 6> ix{};
    std::vector<Expr> stack{Expr{0}};
    std::vector<uint8_t> live(nq, 0); uint32_t nlive = 0, peak = 0; uint64_t peak_ops = 0;
    std::ofstream tr(argv[2], std::ios::binary);
    auto emit = [&](uint64_t op, uint32_t q, uint8_t s) { uint64_t rec = (op << 12) | (uint64_t(q) << 1) | s; tr.write((char*)&rec, 8); };
    for (uint32_t q = 0; q < nq; q++) if (!qs[q].empty()) { live[q] = 1; nlive++; emit(0, q, 1); }
    const Expr one{0};
    for (uint64_t i = 0; i < count[0]; i++) {
        uint8_t t = f.raw[ot + i], base = t & 0x7f; unsigned arity = (t >> 4) & 3;
        uint32_t q[3] = {0, 0, 0};
        int stream = arity == 3 ? 0 : arity == 2 ? 3 : 5;
        for (unsigned j = 0; j < arity; j++) q[j] = f.operand(off[stream + j], ix[arity == 3 ? 1 : arity == 2 ? 2 : 3]);
        if (arity) ix[arity == 3 ? 1 : arity == 2 ? 2 : 3]++;
        uint32_t bit = 0, cond = 0;
        if (t & 0x40) bit = f.operand(off[6], ix[4]++);
        if (t & 0x80) cond = f.operand(off[7], ix[5]++);
        if (t == 0x81) { stack.push_back(alg.mul(stack.back(), bs[cond])); continue; }
        if (t == 0x01) { stack.pop_back(); continue; }
        Expr a = (t & 0x80) ? alg.mul(stack.back(), bs[cond]) : stack.back();
        int changed[2] = {-1, -1};
        switch (base) {
        case 0x00: case 0x06: case 0x10: case 0x20: case 0x30: break;
        case 0x11: qs[q[0]] = alg.add(qs[q[0]], a); changed[0] = q[0]; break;
        case 0x12: qs[q[0]] = alg.add(qs[q[0]], alg.mul(a, qs[q[0]])); changed[0] = q[0]; break;
        case 0x50: qs[q[0]] = alg.add(qs[q[0]], alg.mul(a, qs[q[0]]));
                   bs[bit] = alg.add(bs[bit], alg.mul(a, alg.add(bs[bit], alg.fresh()))); changed[0] = q[0]; break;
        case 0x40: bs[bit] = alg.add(bs[bit], alg.mul(a, bs[bit])); break;
        case 0x41: bs[bit] = alg.add(bs[bit], alg.mul(a, alg.add(bs[bit], one))); break;
        case 0x42: bs[bit] = alg.add(bs[bit], a); break;
        case 0x21: qs[q[1]] = alg.add(qs[q[1]], alg.mul(a, qs[q[0]])); changed[0] = q[1]; break;
        case 0x22: { Expr d = alg.mul(a, alg.add(qs[q[0]], qs[q[1]])); qs[q[0]] = alg.add(qs[q[0]], d); qs[q[1]] = alg.add(qs[q[1]], d); changed[0] = q[0]; changed[1] = q[1]; break; }
        case 0x31: qs[q[2]] = alg.add(qs[q[2]], alg.mul(a, alg.mul(qs[q[0]], qs[q[1]]))); changed[0] = q[2]; break;
        case 0x32: { Expr d = alg.mul(a, alg.mul(qs[q[0]], alg.add(qs[q[1]], qs[q[2]]))); qs[q[1]] = alg.add(qs[q[1]], d); qs[q[2]] = alg.add(qs[q[2]], d); changed[0] = q[1]; changed[1] = q[2]; break; }
        default: throw std::runtime_error("opcode " + std::to_string(t));
        }
        for (int c : changed) if (c >= 0) {
            uint8_t now = !qs[c].empty();
            if (now != live[c]) { live[c] = now; nlive += now ? 1 : -1; emit(i + 1, c, now); }
        }
        if (nlive > peak) { peak = nlive; peak_ops = 0; }
        if (nlive == peak) peak_ops++;
        if (i % 8000000 == 0) std::cerr << i << " ops, atoms " << alg.next << ", products " << alg.products.size() << '\n';
    }
    uint32_t end_live = 0; for (auto& e : qs) end_live += !e.empty();
    std::ofstream out(argv[3]);
    out << "{\"operations\":" << count[0] << ",\"qubits\":" << nq << ",\"proven_peak_live\":" << peak << ",\"ops_at_peak\":" << peak_ops
        << ",\"not_proven_zero_at_end\":" << end_live << ",\"atoms\":" << alg.next << ",\"products\":" << alg.products.size()
        << ",\"overflows\":" << alg.overflows << ",\"cap\":" << alg.cap << "}\n";
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }

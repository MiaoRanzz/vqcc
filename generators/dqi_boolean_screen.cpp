// Independent, conservative Boolean proof screen for version-2 KickMix circuits.
// Binary layout checked against kickmix-macos 3251528 (Apache-2.0); no upstream
// implementation copied. A fresh atom is an overapproximation, never a sample.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include <unordered_map>
using Expr = std::vector<uint32_t>;
struct Algebra {
    uint32_t next = 1;
    size_t cap;
    uint64_t overflows = 0, recovered = 0;
    size_t xor_cache_limit;
    std::unordered_map<uint32_t,std::pair<Expr,Expr>> sums;
    std::map<std::pair<Expr,Expr>,uint32_t> products;
    explicit Algebra(size_t c,size_t cache=0):cap(c),xor_cache_limit(cache) {}
    Expr fresh() { if(next == UINT32_MAX) throw std::runtime_error("atom overflow"); return {next++}; }
    Expr add(const Expr& a,const Expr& b) {
        // Retain exact inverse relations for compressed XOR expressions. Eviction
        // only loses proof power; it never assigns a value to a fresh atom.
        for(int reverse=0;reverse<2;reverse++) {
            const Expr &x=reverse?b:a,&y=reverse?a:b;
            if(x.size()!=1)continue;
            auto it=sums.find(x[0]);if(it==sums.end())continue;
            if(y==it->second.first){recovered++;return it->second.second;}
            if(y==it->second.second){recovered++;return it->second.first;}
        }
        Expr c; c.reserve(a.size()+b.size());
        std::set_symmetric_difference(a.begin(),a.end(),b.begin(),b.end(),std::back_inserter(c));
        if(c.size()>cap) {
            ++overflows;Expr result=fresh();
            if(xor_cache_limit){
                if(sums.size()>=xor_cache_limit)sums.clear();
                sums.emplace(result[0],std::make_pair(a,b));
            }
            return result;
        } return c;
    }
    Expr mul(const Expr& a,const Expr& b) {
        if(a.empty()||b.empty()) return {};
        if(a==Expr{0}||a==b) return b;
        if(b==Expr{0}) return a;
        // Complement identity without creating a fresh atom on overflow.
        if(a.size()+1==b.size() && b[0]==0 && std::equal(a.begin(),a.end(),b.begin()+1)) return {};
        if(b.size()+1==a.size() && a[0]==0 && std::equal(b.begin(),b.end(),a.begin()+1)) return {};
        auto key=a<b?std::make_pair(a,b):std::make_pair(b,a);
        auto [it,inserted]=products.emplace(std::move(key),0);
        if(inserted) it->second=fresh()[0];
        return {it->second};
    }
};
struct File {
    std::vector<uint8_t> raw;
    size_t pos=0;
    explicit File(const char* path) {
        std::ifstream f(path,std::ios::binary); if(!f) throw std::runtime_error("open");
        f.seekg(0,std::ios::end); raw.resize(f.tellg());f.seekg(0);f.read((char*)raw.data(),raw.size());
        if(!f) throw std::runtime_error("read");
    }
    template<class T> T get() { if(pos+sizeof(T)>raw.size()) throw std::runtime_error("truncated");T v;std::memcpy(&v,raw.data()+pos,sizeof(T));pos+=sizeof(T);return v; }
    void skip(size_t n) { if(n>raw.size()-pos) throw std::runtime_error("truncated");pos+=n; }
    size_t packet(uint64_t type,uint64_t bytes) {if(get<uint64_t>()!=type||get<uint64_t>()!=bytes)throw std::runtime_error("packet");size_t p=pos;skip(bytes);return p;}
    uint32_t operand(size_t offset,size_t i) const {uint32_t v;std::memcpy(&v,raw.data()+offset+4*i,4);return v;}
};
int main(int argc,char**argv) try {
    if(argc<5 || argc>7) throw std::runtime_error("usage: scanner source.kmb proofs.tsv summary.json term_cap [xor_cache_limit] [classical_guards]");
    auto start=std::chrono::steady_clock::now();
    File f(argv[1]); const uint8_t magic[]={0xd7,0x50,0xc7,0xd5,0xc3,0x29,0xd3,0x26,0xe3,0xcc,0x9f,0x68,0x34,0xf2,0xb8,0xbf};
    if(f.raw.size()<104||std::memcmp(f.raw.data(),magic,16))throw std::runtime_error("magic");
    f.pos=16;
    if(f.get<uint32_t>()!=2)throw std::runtime_error("version");
    uint32_t nq=f.get<uint32_t>(),nb=f.get<uint32_t>(),nr=f.get<uint32_t>();
    std::array<uint64_t,9> count;for(auto &n:count)n=f.get<uint64_t>();
    Algebra alg(std::stoul(argv[4]),argc>=6?std::stoul(argv[5]):0);std::vector<Expr> state(nq),bits(nb);
    bool guards=argc==7 && std::stoul(argv[6]);
    std::vector<Expr> stack{Expr{0}};
    for(uint32_t r=0;r<nr;r++) {
        if(f.get<uint64_t>()!=0)throw std::runtime_error("register packet");
        auto bytes=f.get<uint64_t>(); auto namelen=f.get<uint32_t>(),len=f.get<uint32_t>();
        if(bytes!=8+namelen+4ULL*len)throw std::runtime_error("register size");
        f.skip(namelen);
        for(uint32_t j=0;j<len;j++){auto v=f.get<uint32_t>();if(v&0x80000000){v&=0x7fffffff;if(v>=nq)throw std::runtime_error("register qubit");state[v]=alg.fresh();}else{if(v>=nb)throw std::runtime_error("register bit");bits[v]=alg.fresh();}}
    }
    size_t ot=f.packet(1,count[0]);std::array<size_t,8> offsets;
    std::array<int,8> groups={1,1,1,2,2,3,4,5};
    for(int j=0;j<8;j++)offsets[j]=f.packet(2+j,4*count[groups[j]]);
    f.packet(10,16*count[6]);
    if(f.get<uint64_t>()!=11)throw std::runtime_error("tags");
    auto tagsize=f.get<uint64_t>();f.skip(tagsize);
    if(f.pos!=f.raw.size())throw std::runtime_error("trailing bytes");
    std::array<size_t,6> ix{};int depth=0;
    uint64_t ccx=0,conditional=0,uncompute=0,zero=0,linear=0;
    uint64_t ccz=0,cswap=0,phase_reductions=0,swap_reductions=0;
    uint64_t false_guards=0,true_guards=0,dead_three=0;
    std::ofstream proof(argv[2]);if(!proof)throw std::runtime_error("proof output");
    proof << "op\tkind\ta\tb\ttarget\n";
    for(uint64_t i=0;i<count[0];i++) {
        uint8_t t=f.raw[ot+i],base=t&0x7f; unsigned arity=(t>>4)&3;
        std::array<uint32_t,3> q{};
        int stream=arity==3?0:arity==2?3:5;
        for(unsigned j=0;j<arity;j++){q[j]=f.operand(offsets[stream+j],ix[arity==3?1:arity==2?2:3]);if(q[j]>=nq)throw std::runtime_error("qubit range");}
        if(arity)ix[arity==3?1:arity==2?2:3]++;
        uint32_t bit=0,condition=0;
        if(t&0x40){bit=f.operand(offsets[6],ix[4]++);if(bit>=nb)throw std::runtime_error("bit range");}
        if(t&0x80){condition=f.operand(offsets[7],ix[5]++);if(condition>=nb)throw std::runtime_error("condition range");}
        // PUSH captures the current bit value, even if that bit later changes.
        if(t==0x81){depth++;if(guards)stack.push_back(alg.mul(stack.back(),bits[condition]));continue;}
        if(t==1){if(--depth<0)throw std::runtime_error("condition stack");if(guards)stack.pop_back();continue;}
        bool cond=(t&0x80)||depth>0;
        if(guards) {
            Expr active=(t&0x80)?alg.mul(stack.back(),bits[condition]):stack.back();
            if(active.empty()) {
                false_guards++;
                if(base==0x30||base==0x31||base==0x32){dead_three++;proof<<i<<"\tdead\t"<<q[0]<<'\t'<<q[1]<<'\t'<<q[2]<<'\n';}
                continue;
            }
            if(cond && active==Expr{0})true_guards++;
            cond=active!=Expr{0};
            if(base==0x40||base==0x41||base==0x42||base==0x50) {
                Expr value=base==0x40?Expr{}:base==0x41?Expr{0}:base==0x42?alg.add(bits[bit],Expr{0}):alg.fresh();
                bits[bit]=cond?alg.add(bits[bit],alg.mul(active,alg.add(bits[bit],value))):value;
            }
        }
        auto fresh_target=[&](unsigned j){state[q[j]]=alg.fresh();};
        switch(base) {
        case 0x11: if(cond)fresh_target(0);else state[q[0]]=alg.add(state[q[0]],Expr{0});break;
        case 0x12: case 0x50: if(cond)fresh_target(0);else state[q[0]]={};break;
        case 0x21: if(q[0]==q[1])throw std::runtime_error("aliased CX");if(cond)fresh_target(1);else state[q[1]]=alg.add(state[q[1]],state[q[0]]);break;
        case 0x22: if(cond){fresh_target(0);fresh_target(1);}else std::swap(state[q[0]],state[q[1]]);break;
        case 0x31: {
            if(q[0]==q[1]||q[0]==q[2]||q[1]==q[2])throw std::runtime_error("aliased CCX");
            ccx++;
            if(cond){conditional++;fresh_target(2);break;}
            Expr delta=alg.mul(state[q[0]],state[q[1]]);
            std::string kind;
            if(delta.empty()){kind="zero";zero++;}
            else if(delta==state[q[0]]){kind="cx_a";linear++;}
            else if(delta==state[q[1]]){kind="cx_b";linear++;}
            else if(delta==state[q[2]]){kind="hmr";uncompute++;}
            if(!kind.empty())proof<<i<<'\t'<<kind<<'\t'<<q[0]<<'\t'<<q[1]<<'\t'<<q[2]<<'\n';
            state[q[2]]=alg.add(state[q[2]],delta);break;
        }
        case 0x30: {
            ccz++; if(cond)break;
            // Try each factorization: opaque product atoms need not recognize
            // associativity. Every equality is exact on all allowed inputs.
            std::string kind;
            for(int j=0;j<3 && kind.empty();j++) {
                Expr phase=alg.mul(alg.mul(state[q[j]],state[q[(j+1)%3]]),state[q[(j+2)%3]]);
                if(phase.empty())kind="ccz_zero";
                else if(phase==Expr{0})kind="ccz_neg";
                else {
                    for(int k=0;k<3 && kind.empty();k++)
                        if(phase==state[q[k]])kind="ccz_z"+std::to_string(k);
                    for(int k=0;k<3 && kind.empty();k++)
                        if(phase==alg.mul(state[q[k]],state[q[(k+1)%3]]))kind="ccz_cz"+std::to_string(k);
                }
            }
            if(!kind.empty()){phase_reductions++;proof<<i<<'\t'<<kind<<'\t'<<q[0]<<'\t'<<q[1]<<'\t'<<q[2]<<'\n';}
            break;
        }
        case 0x32: cswap++; if(cond){fresh_target(1);fresh_target(2);}else {
            Expr difference=alg.add(state[q[1]],state[q[2]]);
            Expr delta=alg.mul(state[q[0]],difference);
            std::string kind;
            if(delta.empty())kind="cswap_zero";
            else if(delta==difference)kind="cswap_swap";
            else if(delta==state[q[0]])kind="cswap_cx";
            if(!kind.empty()){swap_reductions++;proof<<i<<'\t'<<kind<<'\t'<<q[0]<<'\t'<<q[1]<<'\t'<<q[2]<<'\n';}
            state[q[1]]=alg.add(state[q[1]],delta);state[q[2]]=alg.add(state[q[2]],delta);
        }break;
        case 0x00:case 0x06:case 0x07:case 0x10:case 0x13:case 0x17:case 0x20:case 0x27:case 0x37:case 0x40:case 0x41:case 0x42:case 0x47: break;
        default:throw std::runtime_error("unsupported opcode "+std::to_string(t));
        }
        if(i%10000000==0)std::cerr<<i<<" ops, "<<uncompute+zero+linear<<" proofs\n";
    }
    if(depth)throw std::runtime_error("unclosed conditions");
    for(int j=1;j<=5;j++)if(ix[j]!=count[j])throw std::runtime_error("stream count");
    double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ofstream out(argv[3]);out<<"{\"operations\":"<<count[0]<<",\"qubits\":"<<nq<<",\"bits\":"<<nb<<",\"ccx\":"<<ccx<<",\"conditional_ccx\":"<<conditional<<",\"hmr_replacements\":"<<uncompute<<",\"zero_replacements\":"<<zero<<",\"linear_replacements\":"<<linear<<",\"term_cap\":"<<alg.cap<<",\"expression_overflows\":"<<alg.overflows<<" ,\"xor_cache_limit\":"<<alg.xor_cache_limit<<",\"xor_recoveries\":"<<alg.recovered<<",\"product_atoms\":"<<alg.products.size()<<",\"atoms\":"<<alg.next-1<<",\"elapsed_seconds\":"<<elapsed<<",\"ccz\":"<<ccz<<",\"cswap\":"<<cswap<<",\"phase_reductions\":"<<phase_reductions<<",\"swap_reductions\":"<<swap_reductions<<",\"classical_guards\":"<<guards<<",\"false_guard_operations\":"<<false_guards<<",\"true_guard_operations\":"<<true_guards<<",\"dead_three_qubit_gates\":"<<dead_three<<"}\n";
    if(!proof||!out)throw std::runtime_error("output write");
    return 0;
} catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}

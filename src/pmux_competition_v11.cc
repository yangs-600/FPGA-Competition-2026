// Conditional constant propagation for mux data selected by equality decoders.
// No testcase names, source paths, probe synthesis, or register changes.
#include "kernel/yosys.h"
#include "kernel/sigtools.h"
#include <functional>
#include <map>
#include <tuple>
USING_YOSYS_NAMESPACE
PRIVATE_NAMESPACE_BEGIN

struct PmuxCompetitionOpt : public Pass {
    PmuxCompetitionOpt() : Pass("pmux_competition_opt", "propagate decoder constraints into selected mux data") {}
    void help() override {
        log("    pmux_competition_opt\n");
        log("Replace data bits implied by a true equality decoder in mux/pmux arms.\n");
        log("Shares complete equality-decoded PMUX trees; preserves priority muxes and sequential cells. No synthesis probes.\n");
    }
    void execute(std::vector<std::string> args, RTLIL::Design *design) override {
        extra_args(args, 1, design);
        log_header(design, "Executing PMUX_COMPETITION_OPT v11.\n");
        int replaced = 0;
        for (auto module : design->selected_modules()) {
            if (module->get_bool_attribute(ID::blackbox)) continue;
            SigMap sigmap(module);
            dict<SigBit, dict<SigBit, SigBit>> facts;
            dict<SigBit, std::pair<SigSpec,int>> decode;
            for (auto c : module->cells()) {
                if (!c->type.in(ID($eq), ID($logic_not))) continue;
                auto y = sigmap(c->getPort(ID::Y));
                if (GetSize(y) != 1 || !y[0].wire) continue;
                auto a = sigmap(c->getPort(ID::A));
                SigSpec b = c->type == ID($logic_not) ? SigSpec(State::S0, GetSize(a)) : sigmap(c->getPort(ID::B));
                if (a.is_fully_const()) std::swap(a, b);
                if (!b.is_fully_const() || GetSize(a) != GetSize(b)) continue;
                bool known = true;
                for (auto bit : b) known &= bit == State::S0 || bit == State::S1;
                if (!known) continue;
                dict<SigBit, SigBit> f;
                bool consistent = true;
                for (int i = 0; i < GetSize(a); i++) {
                    if (!a[i].wire) { consistent &= a[i] == b[i]; continue; }
                    if (f.count(a[i]) && f.at(a[i]) != b[i]) consistent = false;
                    f[a[i]] = b[i];
                }
                if (consistent) { facts[y[0]] = f; if (GetSize(a) >= 3 && GetSize(a) <= 6 && GetSize(f)==GetSize(a)) decode[y[0]] = {a,b.as_int()}; }
            }
            for (auto c : module->selected_cells()) {
                if (!c->type.in(ID($mux), ID($pmux)) || c->get_bool_attribute(ID::keep)) continue;
                auto s = sigmap(c->getPort(ID::S));
                auto b = c->getPort(ID::B);
                int width = GetSize(c->getPort(ID::Y));
                if (GetSize(b) != width * GetSize(s)) continue;
                bool changed = false;
                for (int arm = 0; arm < GetSize(s); arm++) {
                    if (!facts.count(s[arm])) continue;
                    auto &f = facts.at(s[arm]);
                    for (int bit = 0; bit < width; bit++) {
                        int index = arm * width + bit;
                        auto value = sigmap(b[index]);
                        if (f.count(value)) {
                            b[index] = f.at(value);
                            changed = true;
                            replaced++;
                        }
                    }
                }
                if (changed) c->setPort(ID::B, b);
            }
            // Build a shared bit-level Shannon DAG, low selector bit outermost.
            // Commit only when the mux-node estimate is no greater than the AND/OR LUT estimate.
            dict<SigBit,int> leaves;
            std::vector<SigBit> wires;
            std::vector<std::tuple<int,int,int>> nodes;
            std::map<std::tuple<int,int,int>,int> memo;
            auto leaf = [&](SigBit bit) {
                bit=sigmap(bit);
                if (!leaves.count(bit)) { leaves[bit]=GetSize(wires); wires.push_back(bit); }
                return leaves.at(bit);
            };
            // Negative IDs are internal nodes, nonnegative IDs are original bits.
            std::function<int(const std::vector<int>&,const std::vector<int>&,int)> build;
            build = [&](const std::vector<int>& data,const std::vector<int>& sel,int depth) -> int {
                if (GetSize(data)==1) return data[0];
                std::vector<int> lo,hi;
                for (int i=0;i<GetSize(data);i++) (i&1 ? hi:lo).push_back(data[i]);
                int a=build(lo,sel,depth+1), b=build(hi,sel,depth+1);
                if (a==b) return a;
                auto key=std::make_tuple(sel[depth],a,b);
                auto it=memo.find(key); if(it!=memo.end()) return it->second;
                int id=-1-GetSize(nodes);nodes.push_back(key);memo[key]=id;return id;
            };
            std::vector<std::pair<Cell*,std::vector<int>>> targets;
            int estimated_luts=0;
            for (auto c:module->selected_cells()) {
                if(c->type!=ID($pmux) || c->get_bool_attribute(ID::keep)) continue;
                auto ss=sigmap(c->getPort(ID::S));int arms=GetSize(ss),width=GetSize(c->getPort(ID::Y));
                if(width<8 || arms<8 || !decode.count(ss[0])) continue;
                auto ctrl=decode.at(ss[0]).first; int bits=GetSize(ctrl);
                if(arms!=(1<<bits)) continue;
                std::vector<SigSpec> table(arms); std::vector<bool> seen(arms,false);bool valid=true;
                auto data=sigmap(c->getPort(ID::B));
                for(int i=0;i<arms;i++) {
                    if(!decode.count(ss[i]) || decode.at(ss[i]).first!=ctrl) {valid=false;break;}
                    int code=decode.at(ss[i]).second;
                    if(code<0 || code>=arms || seen[code]) {valid=false;break;}
                    seen[code]=true;table[code]=data.extract(i*width,width);
                }
                if(!valid) continue;
                std::vector<int> sel,outputs;
                for(auto bit:ctrl) sel.push_back(leaf(bit));
                for(int bit=0;bit<width;bit++) {
                    std::vector<int> column;
                    for(auto &arm:table) column.push_back(leaf(arm[bit]));
                    outputs.push_back(build(column,sel,0));
                }
                targets.push_back({c,outputs});
                estimated_luts+=width*((arms+1)/2+(arms/2+2)/3);
            }
            log("PMUX_TREE_ESTIMATE cells=%d nodes=%d before=%d\n",GetSize(targets),GetSize(nodes),estimated_luts);
            if(!targets.empty() && GetSize(nodes)<=estimated_luts) {
                std::vector<SigBit> mapped;
                auto resolve=[&](int id)->SigBit {return id>=0?wires.at(id):mapped.at(-1-id);};
                for(auto node:nodes) {
                    SigBit out=module->addWire(NEW_ID);
                    module->addMux(NEW_ID,resolve(std::get<1>(node)),resolve(std::get<2>(node)),resolve(std::get<0>(node)),out);
                    mapped.push_back(out);
                }
                for(auto &target:targets) {
                    SigSpec result;for(int id:target.second) result.append(resolve(id));
                    module->connect(target.first->getPort(ID::Y),result);module->remove(target.first);
                }
                log("PMUX_SHARED_TREE cells=%d mux_nodes=%d estimate_before=%d\n",GetSize(targets),GetSize(nodes),estimated_luts);
            }
        }
        log("PMUX_COMPETITION_OPT substituted_bits=%d\n", replaced);
    }
} PmuxCompetitionOpt;
PRIVATE_NAMESPACE_END

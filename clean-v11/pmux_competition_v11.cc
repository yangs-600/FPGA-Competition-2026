// Conditional constant propagation for mux data selected by equality decoders.
// No testcase names, source paths, probe synthesis, or register changes.
#include "kernel/yosys.h"
#include "kernel/sigtools.h"
#include <algorithm>
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
        log("Shares equality-decoded PMUX trees, safely completes default codes, and searches selector order.\n");
        log("Preserves priority muxes and sequential cells. No synthesis probes.\n");
    }
    void execute(std::vector<std::string> args, RTLIL::Design *design) override {
        extra_args(args, 1, design);
        log_header(design, "Executing PMUX_COMPETITION_OPT v14.\n");
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
            // Collect provably complete tables. Equality decoders on the same
            // control vector are mutually exclusive, so every unlisted code
            // selects the PMUX default input A.
            struct TableTarget {
                Cell *cell;
                SigSpec ctrl;
                int width;
                int codes;
                int explicit_arms;
                std::vector<SigSpec> table;
            };
            std::vector<TableTarget> all_targets;
            for (auto c:module->selected_cells()) {
                if(c->type!=ID($pmux) || c->get_bool_attribute(ID::keep)) continue;
                auto ss=sigmap(c->getPort(ID::S));int arms=GetSize(ss),width=GetSize(c->getPort(ID::Y));
                if(width<8 || arms==0 || !decode.count(ss[0])) continue;
                auto ctrl=decode.at(ss[0]).first; int bits=GetSize(ctrl),codes=1<<bits;
                if(arms>codes) continue;
                std::vector<SigSpec> table(codes); std::vector<bool> seen(codes,false);bool valid=true;
                auto data=sigmap(c->getPort(ID::B));
                for(int i=0;i<arms;i++) {
                    if(!decode.count(ss[i]) || decode.at(ss[i]).first!=ctrl) {valid=false;break;}
                    int code=decode.at(ss[i]).second;
                    if(code<0 || code>=codes || seen[code]) {valid=false;break;}
                    seen[code]=true;table[code]=data.extract(i*width,width);
                }
                if(valid && arms<codes) {
                    if(GetSize(c->getPort(ID::A))!=width) valid=false;
                    else {
                        auto fallback=sigmap(c->getPort(ID::A));
                        for(int code=0;code<codes;code++) if(!seen[code]) table[code]=fallback;
                    }
                }
                if(!valid) continue;
                all_targets.push_back({c,ctrl,width,codes,arms,table});
            }
            std::vector<std::vector<int>> groups;
            for (int i=0;i<GetSize(all_targets);i++) {
                int group=-1;
                for (int g=0;g<GetSize(groups);g++)
                    if(all_targets.at(groups.at(g).at(0)).ctrl==all_targets.at(i).ctrl) {group=g;break;}
                if(group<0) groups.push_back({i}); else groups.at(group).push_back(i);
            }
            int total_cells=0,total_nodes=0,total_estimated=0;
            for(auto &group:groups) {
                auto &first=all_targets.at(group.at(0));
                int bits=GetSize(first.ctrl),codes=first.codes;
                dict<SigBit,int> leaves;
                std::vector<SigBit> wires;
                auto leaf=[&](SigBit bit) {
                    bit=sigmap(bit);
                    if(!leaves.count(bit)) {leaves[bit]=GetSize(wires);wires.push_back(bit);}
                    return leaves.at(bit);
                };
                std::vector<int> selectors;
                for(auto bit:first.ctrl) selectors.push_back(leaf(bit));
                std::vector<int> order(bits),best_order;
                for(int i=0;i<bits;i++) order.at(i)=i;
                std::vector<std::tuple<int,int,int>> best_nodes;
                std::vector<std::vector<int>> best_outputs;
                bool have_best=false;
                auto make_graph=[&](const std::vector<int> &candidate_order,
                                    std::vector<std::tuple<int,int,int>> &graph_nodes,
                                    std::vector<std::vector<int>> &graph_outputs) {
                    std::map<std::tuple<int,int,int>,int> memo;
                    std::function<int(const std::vector<int>&,const std::vector<int>&,int)> build;
                    build=[&](const std::vector<int> &column,const std::vector<int> &active_codes,int depth)->int {
                        if(GetSize(active_codes)==1) return column.at(active_codes.at(0));
                        std::vector<int> lo,hi;
                        for(auto code:active_codes) ((code>>candidate_order.at(depth))&1?hi:lo).push_back(code);
                        int a=build(column,lo,depth+1),b=build(column,hi,depth+1);
                        if(a==b) return a;
                        auto key=std::make_tuple(selectors.at(candidate_order.at(depth)),a,b);
                        auto it=memo.find(key);if(it!=memo.end()) return it->second;
                        int id=-1-GetSize(graph_nodes);graph_nodes.push_back(key);memo[key]=id;return id;
                    };
                    std::vector<int> active_codes(codes);
                    for(int code=0;code<codes;code++) active_codes.at(code)=code;
                    graph_outputs.clear();
                    for(auto target_index:group) {
                        auto &target=all_targets.at(target_index);
                        std::vector<int> outputs;
                        for(int bit=0;bit<target.width;bit++) {
                            std::vector<int> column(codes);
                            for(int code=0;code<codes;code++) column.at(code)=leaf(target.table.at(code)[bit]);
                            outputs.push_back(build(column,active_codes,0));
                        }
                        graph_outputs.push_back(outputs);
                    }
                };
                std::sort(order.begin(),order.end());
                do {
                    std::vector<std::tuple<int,int,int>> trial_nodes;
                    std::vector<std::vector<int>> trial_outputs;
                    make_graph(order,trial_nodes,trial_outputs);
                    if(!have_best || GetSize(trial_nodes)<GetSize(best_nodes)) {
                        best_order=order;best_nodes.swap(trial_nodes);best_outputs.swap(trial_outputs);have_best=true;
                    }
                } while(std::next_permutation(order.begin(),order.end()));
                int estimated_luts=0;
                for(auto target_index:group) {
                    auto &target=all_targets.at(target_index);
                    // Compare against the PMUX structure actually being replaced,
                    // not the larger completed truth-table space.
                    estimated_luts+=target.width*((target.explicit_arms+1)/2+(target.explicit_arms/2+2)/3);
                }
                total_cells+=GetSize(group);total_nodes+=GetSize(best_nodes);total_estimated+=estimated_luts;
                if(have_best && GetSize(best_nodes)<=estimated_luts) {
                    std::vector<SigBit> mapped;
                    auto resolve=[&](int id)->SigBit {return id>=0?wires.at(id):mapped.at(-1-id);};
                    for(auto node:best_nodes) {
                        SigBit out=module->addWire(NEW_ID);
                        module->addMux(NEW_ID,resolve(std::get<1>(node)),resolve(std::get<2>(node)),resolve(std::get<0>(node)),out);
                        mapped.push_back(out);
                    }
                    int target_number=0;
                    for(auto target_index:group) {
                        SigSpec result;
                        for(int id:best_outputs.at(target_number++)) result.append(resolve(id));
                        module->connect(all_targets.at(target_index).cell->getPort(ID::Y),result);
                        module->remove(all_targets.at(target_index).cell);
                    }
                    log("PMUX_SHARED_TREE cells=%d mux_nodes=%d estimate_before=%d order=",GetSize(group),GetSize(best_nodes),estimated_luts);
                    for(auto bit:best_order) log("%d",bit);
                    log("\n");
                }
            }
            log("PMUX_TREE_ESTIMATE cells=%d nodes=%d before=%d\n",total_cells,total_nodes,total_estimated);
        }
        log("PMUX_COMPETITION_OPT substituted_bits=%d\n", replaced);
    }
} PmuxCompetitionOpt;
PRIVATE_NAMESPACE_END

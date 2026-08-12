"""Stage 2 (fast): 20-paper ablation with text-truncation fix."""

import sys, os, json, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from granular_agent.agent import GranularFlowAgent
from granular_agent.gap_discovery import active_gap_scan

WORKTREE = "C:/Users/D0n9/Desktop/LogicKG-benchmark"
OUTPUT_DIR = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "stage2_fast_output")
PURIFIED = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "purified_corpus_1186.jsonl")

def select_20_papers():
    rows = [json.loads(l) for l in open(PURIFIED, encoding="utf-8") if l.strip()]
    by_sub = {}
    for r in rows:
        s = r.get("subdomain", "other")
        by_sub.setdefault(s, []).append(r)
    selected = []
    for sub in ["theory", "experiment", "rheology", "DEM", "geophysical", "simulation"]:
        for p in by_sub.get(sub, [])[:4]:
            selected.append(p["paper_id"])
            if len(selected) >= 20:
                break
        if len(selected) >= 20:
            break
    return selected[:20]


def main():
    paper_ids = select_20_papers()
    print(f"Selected {len(paper_ids)} papers")
    print()

    sv_dir = os.path.join(WORKTREE, "schema_versions")

    # --- Run 1: self-evolution OFF ---
    print("="*50)
    print("RUN 1: Self-evolution OFF (20 papers)")
    print("="*50)
    if os.path.exists(sv_dir):
        shutil.rmtree(sv_dir)
    agent_off = GranularFlowAgent(worktree=WORKTREE, llms=["deepseek"], self_evolution_enabled=False)
    results_off = []
    for i, pid in enumerate(paper_ids, 1):
        print(f"[{i}/{len(paper_ids)}] {pid}", end=" ", flush=True)
        try:
            r = agent_off.process_paper(pid)
            results_off.append(r)
            print(f"atoms={r['n_atoms']}", flush=True)
        except Exception as e:
            print(f"ERROR: {str(e)[:60]}", flush=True)
            results_off.append({"paper_id": pid, "n_atoms": 0, "atoms": [], "gaps": [], "qa_pairs": [], "schema_changes": []})

    # --- Run 2: self-evolution ON ---
    print(f"\n{'='*50}")
    print("RUN 2: Self-evolution ON (20 papers)")
    print("="*50)
    if os.path.exists(sv_dir):
        shutil.rmtree(sv_dir)
    agent_on = GranularFlowAgent(worktree=WORKTREE, llms=["deepseek"], self_evolution_enabled=True)
    results_on = []
    for i, pid in enumerate(paper_ids, 1):
        print(f"[{i}/{len(paper_ids)}] {pid}", end=" ", flush=True)
        try:
            r = agent_on.process_paper(pid)
            results_on.append(r)
            print(f"atoms={r['n_atoms']} gaps={len(r['gaps'])} changes={len(r['schema_changes'])}", flush=True)
        except Exception as e:
            print(f"ERROR: {str(e)[:60]}", flush=True)
            results_on.append({"paper_id": pid, "n_atoms": 0, "atoms": [], "gaps": [], "qa_pairs": [], "schema_changes": []})

    # Active gap scan
    print("\nActive gap scan...", flush=True)
    candidates = active_gap_scan(results_on, agent_on.schema_manager, min_recurrence=2)
    print(f"Candidates (min_recurrence=2): {len(candidates)}")
    for c in candidates[:5]:
        print(f"  [{c['gap_type']}] {c['value']} (x{c['recurrence']})")

    # Compare
    total_off = sum(r.get("n_atoms", 0) for r in results_off)
    total_on = sum(r.get("n_atoms", 0) for r in results_on)
    gaps_off = sum(len(r.get("gaps", [])) for r in results_off)
    gaps_on = sum(len(r.get("gaps", [])) for r in results_on)
    changes = len(agent_on.schema_evolution_log)
    zero_off = sum(1 for r in results_off if r.get("n_atoms", 0) == 0)
    zero_on = sum(1 for r in results_on if r.get("n_atoms", 0) == 0)

    print(f"\n{'='*50}")
    print("COMPARISON (C5)")
    print(f"{'='*50}")
    print(f"{'Metric':<25}{'OFF':>10}{'ON':>10}{'Diff':>10}")
    print("-"*55)
    print(f"{'Total atoms':<25}{total_off:>10}{total_on:>10}{total_on-total_off:>+10}")
    print(f"{'Zero-atom papers':<25}{zero_off:>10}{zero_on:>10}{zero_on-zero_off:>+10}")
    print(f"{'Gaps':<25}{gaps_off:>10}{gaps_on:>10}{gaps_on-gaps_off:>+10}")
    print(f"{'Schema evolutions':<25}{0:>10}{changes:>10}")
    print(f"{'Schema version':<25}{'4.0':>10}{agent_on.schema_manager.current_version:>10}")
    print()

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    agent_on.save_results(OUTPUT_DIR)
    comp = {"papers": len(paper_ids), "off_atoms": total_off, "on_atoms": total_on,
            "off_zeros": zero_off, "on_zeros": zero_on, "off_gaps": gaps_off, "on_gaps": gaps_on,
            "schema_evolutions": changes, "active_candidates": len(candidates)}
    with open(os.path.join(OUTPUT_DIR, "comparison.json"), "w", encoding="utf-8") as f:
        json.dump(comp, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

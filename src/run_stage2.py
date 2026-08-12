"""Stage 2: 50-paper validation + self-evolution ablation (C5).

Runs the agent on 50 papers across subdomains, with and without self-evolution,
to test whether self-evolution discovers real gaps and improves extraction.
"""

import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from granular_agent.agent import GranularFlowAgent

WORKTREE = "C:/Users/D0n9/Desktop/LogicKG-benchmark"
OUTPUT_DIR = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "stage2_output")
PURIFIED = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "purified_corpus_1186.jsonl")

def select_50_papers():
    """Select 50 papers spanning subdomains."""
    rows = [json.loads(l) for l in open(PURIFIED, encoding="utf-8") if l.strip()]
    by_sub = {}
    for r in rows:
        s = r.get("subdomain", "other")
        by_sub.setdefault(s, []).append(r)

    selected = []
    # Distribute across subdomains proportional to availability
    quotas = {
        "theory": 10, "experiment": 10, "rheology": 8,
        "DEM": 7, "geophysical": 5, "simulation": 5, "other": 5
    }
    for sub, quota in quotas.items():
        papers = by_sub.get(sub, [])
        for p in papers[:quota]:
            selected.append({"paper_id": p["paper_id"], "title": p["title"], "subdomain": sub})
        if len(selected) >= 50:
            break
    return selected[:50]


def run_ablation():
    """Run ablation: self-evolution ON vs OFF on 50 papers."""
    papers = select_50_papers()
    paper_ids = [p["paper_id"] for p in papers]
    print(f"Selected {len(papers)} papers across subdomains:")
    from collections import Counter
    sub_dist = Counter(p["subdomain"] for p in papers)
    for s, c in sub_dist.most_common():
        print(f"  {s}: {c}")
    print()

    # --- Run 1: self-evolution OFF (fixed v4 schema) ---
    print("="*60)
    print("RUN 1: Self-evolution OFF (fixed v4 schema)")
    print("="*60)

    # Clean schema versions directory for fresh run
    import shutil
    sv_dir = os.path.join(WORKTREE, "schema_versions")
    if os.path.exists(sv_dir):
        shutil.rmtree(sv_dir)
    cl_path = os.path.join(sv_dir, "CHANGELOG.jsonl")
    if os.path.exists(cl_path):
        os.remove(cl_path)

    agent_off = GranularFlowAgent(
        worktree=WORKTREE,
        llms=["deepseek"],
        self_evolution_enabled=False,
    )
    print(f"Schema version: {agent_off.schema_manager.current_version}")
    print()

    results_off = []
    for i, pid in enumerate(paper_ids, 1):
        print(f"[{i}/{len(paper_ids)}] ", end="", flush=True)
        try:
            result = agent_off.process_paper(pid)
            results_off.append(result)
        except Exception as e:
            print(f"  ERROR: {str(e)[:80]}")
            results_off.append({"paper_id": pid, "error": str(e)[:100], "atoms": [], "gaps": [], "n_atoms": 0, "qa_pairs": [], "schema_changes": []})

    # Save run 1
    agent_off.save_results(os.path.join(OUTPUT_DIR, "evolution_off"))

    # --- Run 2: self-evolution ON ---
    print("\n" + "="*60)
    print("RUN 2: Self-evolution ON")
    print("="*60)

    # Clean schema versions for fresh run
    if os.path.exists(sv_dir):
        shutil.rmtree(sv_dir)

    agent_on = GranularFlowAgent(
        worktree=WORKTREE,
        llms=["deepseek"],
        self_evolution_enabled=True,
    )
    print(f"Schema version: {agent_on.schema_manager.current_version}")
    print()

    results_on = []
    for i, pid in enumerate(paper_ids, 1):
        print(f"[{i}/{len(paper_ids)}] ", end="", flush=True)
        try:
            result = agent_on.process_paper(pid)
            results_on.append(result)
        except Exception as e:
            print(f"  ERROR: {str(e)[:80]}")
            results_on.append({"paper_id": pid, "error": str(e)[:100], "atoms": [], "gaps": [], "n_atoms": 0, "qa_pairs": [], "schema_changes": []})

    # Active gap scan at end of batch
    print("\n  Running active gap scan...", flush=True)
    candidates = active_gap_scan_wrapper(agent_on, results_on)
    print(f"  Active candidates: {len(candidates)}")

    # Save run 2
    agent_on.save_results(os.path.join(OUTPUT_DIR, "evolution_on"))

    # --- Compare ---
    print("\n" + "="*60)
    print("ABLATION COMPARISON (C5)")
    print("="*60)

    total_atoms_off = sum(r.get("n_atoms", 0) for r in results_off)
    total_atoms_on = sum(r.get("n_atoms", 0) for r in results_on)
    total_gaps_off = sum(len(r.get("gaps", [])) for r in results_off)
    total_gaps_on = sum(len(r.get("gaps", [])) for r in results_on)
    total_qa_off = sum(len(r.get("qa_pairs", [])) for r in results_off)
    total_qa_on = sum(len(r.get("qa_pairs", [])) for r in results_on)
    total_changes = len(agent_on.schema_evolution_log)

    # L3 contributions count
    l3_off = sum(1 for r in results_off for a in r.get("atoms", []) if isinstance(a, dict) and a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION")
    l3_on = sum(1 for r in results_on for a in r.get("atoms", []) if isinstance(a, dict) and a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION")

    print(f"{'Metric':<30}{'Evo OFF':>12}{'Evo ON':>12}{'Diff':>10}")
    print("-"*64)
    print(f"{'Total atoms':<30}{total_atoms_off:>12}{total_atoms_on:>12}{total_atoms_on-total_atoms_off:>+10}")
    print(f"{'L3 CONTRIBUTIONs':<30}{l3_off:>12}{l3_on:>12}{l3_on-l3_off:>+10}")
    print(f"{'Gaps detected':<30}{total_gaps_off:>12}{total_gaps_on:>12}{total_gaps_on-total_gaps_off:>+10}")
    print(f"{'QA pairs':<30}{total_qa_off:>12}{total_qa_on:>12}{total_qa_on-total_qa_off:>+10}")
    print(f"{'Schema evolutions':<30}{0:>12}{total_changes:>12}{total_changes:>+10}")
    print(f"{'Schema version':<30}{'4.0':>12}{agent_on.schema_manager.current_version:>12}")
    print()

    # Schema evolution details
    if agent_on.schema_evolution_log:
        print("SCHEMA EVOLUTIONS:")
        for change in agent_on.schema_evolution_log:
            print(f"  v{change['version']}: +{change['value']} ({change['gap_type']}) [paper: {change['paper_id']}]")
        print()

    # C5 VERDICT
    print("C5 VERDICT:")
    if total_changes > 0:
        print(f"  Self-evolution triggered {total_changes} schema extensions.")
        print(f"  Schema grew from v4.0 to v{agent_on.schema_manager.current_version}.")
        if total_atoms_on > total_atoms_off:
            print(f"  Extraction atom count increased ({total_atoms_off} → {total_atoms_on}).")
            print(f"  C5: Self-evolution affects extraction — signal detected.")
        elif total_gaps_on != total_gaps_off:
            print(f"  Gap detection changed ({total_gaps_off} → {total_gaps_on}).")
            print(f"  C5: Self-evolution affects gap detection — signal detected.")
        else:
            print(f"  But atom count and gap count unchanged.")
            print(f"  C5: Self-evolution triggered but no measurable quality change — inconclusive.")
    else:
        print(f"  Self-evolution triggered 0 schema extensions in 50 papers.")
        print(f"  C5: Kill point — self-evolution may be unnecessary for current schema coverage.")
        print(f"  NOTE: v4 schema may already cover granular flow well; need more diverse papers or lower validation threshold.")

    # Save comparison
    comparison = {
        "papers": len(paper_ids),
        "evolution_off": {"total_atoms": total_atoms_off, "l3_contributions": l3_off, "gaps": total_gaps_off, "qa_pairs": total_qa_off, "schema_version": "4.0", "schema_evolutions": 0},
        "evolution_on": {"total_atoms": total_atoms_on, "l3_contributions": l3_on, "gaps": total_gaps_on, "qa_pairs": total_qa_on, "schema_version": agent_on.schema_manager.current_version, "schema_evolutions": total_changes},
        "schema_evolution_log": agent_on.schema_evolution_log,
    }
    with open(os.path.join(OUTPUT_DIR, "ablation_comparison.json"), "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print(f"\nComparison saved to {OUTPUT_DIR}/ablation_comparison.json")


def active_gap_scan_wrapper(agent, results):
    """Wrapper to call active_gap_scan with proper import."""
    from granular_agent.gap_discovery import active_gap_scan, validate_gap
    candidates = active_gap_scan(results, agent.schema_manager, min_recurrence=3)
    return candidates


if __name__ == "__main__":
    run_ablation()

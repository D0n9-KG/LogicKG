"""Run the agent on Jop 2006 (PPR_B0E8916D4E19) — first end-to-end test."""

import sys, os, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from granular_agent.agent import GranularFlowAgent

WORKTREE = "C:/Users/D0n9/Desktop/LogicKG-benchmark"
OUTPUT_DIR = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "agent_test_output")
PAPER_ID = "PPR_B0E8916D4E19"  # Jop 2006

def main():
    print("="*60)
    print("GranularFlow-Bench Agent: first end-to-end test on Jop 2006")
    print("="*60)

    agent = GranularFlowAgent(
        worktree=WORKTREE,
        llms=["deepseek"],  # single LLM first
        self_evolution_enabled=True,
    )

    print(f"\nInitial schema version: {agent.schema_manager.current_version}")
    print(f"Entity types: {agent.schema_manager.get_entity_types()}")
    print(f"Contribution subtypes: {agent.schema_manager.get_contribution_subtypes()}")
    print(f"Relation types: {agent.schema_manager.get_relation_types()}")
    print()

    result = agent.process_paper(PAPER_ID)

    print(f"\n{'='*60}")
    print(f"RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"Paper: {result['paper_id']}")
    print(f"Atoms extracted: {result['n_atoms']}")
    print(f"Gaps detected: {len(result['gaps'])}")
    print(f"Schema changes: {len(result['schema_changes'])}")
    print(f"QA pairs: {len(result['qa_pairs'])}")
    print(f"Schema version: {result['schema_version']}")
    print()

    # Print gaps
    if result['gaps']:
        print("GAPS DETECTED:")
        for g in result['gaps']:
            print(f"  [{g['type']}] {g['value']}")
        print()

    # Print schema changes
    if result['schema_changes']:
        print("SCHEMA EVOLUTION:")
        for c in result['schema_changes']:
            print(f"  v{c['version']}: +{c['value']} ({c['gap_type']})")
        print()

    # Print L3 contributions
    l3_contribs = [a for a in result['atoms'] if isinstance(a, dict) and a.get('layer') == 'L3' and a.get('type') == 'CONTRIBUTION']
    print(f"L3 CONTRIBUTIONS ({len(l3_contribs)}):")
    for a in l3_contribs:
        subs = ', '.join(a.get('subtypes', []))
        print(f"  [{subs}] {a.get('statement', '')[:100]}")
    print()

    # Print QA pairs
    if result['qa_pairs']:
        print(f"QA PAIRS ({len(result['qa_pairs'])}):")
        for qa in result['qa_pairs'][:3]:
            print(f"  Q: {qa.get('question', '')[:80]}")
            print(f"  A: {qa.get('answer', '')[:80]}")
            print()
    else:
        print("No QA pairs generated")

    # Save results
    agent.save_results(OUTPUT_DIR)

    # Print schema evolution summary
    summary = agent.get_schema_evolution_summary()
    print(f"\nSCHEMA EVOLUTION SUMMARY:")
    print(f"  Initial: {summary['initial_version']}")
    print(f"  Current: {summary['current_version']}")
    print(f"  Total evolutions: {summary['total_evolutions']}")
    if summary['changelog']:
        for entry in summary['changelog']:
            print(f"    v{entry['version']}: {entry['action']} +{entry['what_changed']}")

    print(f"\n{'='*60}")
    print("END-TO-END TEST COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

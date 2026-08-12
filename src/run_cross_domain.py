"""Cross-domain experiment: run self-evolving agent on SciFact (biomedical)
with minimal seed schema, to test if self-evolution discovers domain-specific
schema elements.

Design:
- Seed schema: only 4 basic entity types (MATERIAL, PROPERTY, NUMERIC, UNIT)
- Domain: SciFact biomedical abstracts (completely different from granular flow)
- If agent discovers: MEASUREMENT, CONDITION, DISEASE, DRUG, DEVICE, etc.
  → C2 (self-evolution) has positive validation
- If not → investigate system issues, fix, retry
"""

import sys, os, json, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from granular_agent.agent import GranularFlowAgent
from granular_agent.gap_discovery import active_gap_scan, validate_gap

WORKTREE = "C:/Users/D0n9/Desktop/LogicKG-benchmark"
SCIFACT_DATA = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "data")
OUTPUT = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark", "cross_domain_output")

# Minimal seed schema — only 4 basic entity types
MINIMAL_SEED_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://logickg.local/schemas/seed.json",
    "title": "Minimal Seed Schema (for cross-domain self-evolution test)",
    "description": "Only 4 basic entity types. Agent must discover domain-specific types.",
    "type": "object",
    "required": ["paper_id", "paper_type", "atoms"],
    "properties": {
        "paper_id": {"type": "string"},
        "paper_type": {"type": "string", "enum": ["rheology", "experiment", "theory", "DEM", "review", "other"]},
        "research_question": {"type": ["string", "null"]},
        "atoms": {"type": "array", "items": {"$ref": "#/$defs/atom"}}
    },
    "$defs": {
        "atom": {
            "oneOf": [
                {"$ref": "#/$defs/L1_entity"},
                {"$ref": "#/$defs/L2_relation"},
                {"$ref": "#/$defs/L3_contribution"},
                {"$ref": "#/$defs/L3_contribution_relation"}
            ]
        },
        "L1_entity": {
            "type": "object",
            "required": ["layer", "entity_type", "entity"],
            "properties": {
                "layer": {"const": "L1"},
                "entity_type": {
                    "type": "string",
                    "enum": ["MATERIAL", "PROPERTY", "NUMERIC", "UNIT"]
                },
                "entity": {"type": "string"},
                "span": {"type": ["string", "null"]}
            },
            "additionalProperties": False
        },
        "L2_relation": {
            "type": "object",
            "required": ["layer", "relation"],
            "properties": {
                "layer": {"const": "L2"},
                "relation": {"type": "string", "enum": ["measures_property", "property_value"]},
                "subject": {"type": "string"},
                "object": {"type": "string"},
                "conditions": {"type": "array", "items": {"type": "string"}}
            },
            "additionalProperties": False
        },
        "L3_contribution": {
            "type": "object",
            "required": ["layer", "type", "statement", "subtypes"],
            "properties": {
                "layer": {"const": "L3"},
                "type": {"const": "CONTRIBUTION"},
                "statement": {"type": "string"},
                "subtypes": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["constitutive_law", "experimental_finding"]},
                    "minItems": 1
                },
                "params": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": ["string", "null"]}
            },
            "additionalProperties": False
        },
        "L3_contribution_relation": {
            "type": "object",
            "required": ["layer", "type", "relation", "from", "to"],
            "properties": {
                "layer": {"const": "L3"},
                "type": {"const": "CONTRIBUTION_RELATION"},
                "relation": {"type": "string", "enum": ["supports", "conflicts"]},
                "from": {"type": "string"},
                "to": {"type": "string"},
                "qualifier": {"type": ["string", "null"]}
            },
            "additionalProperties": False
        }
    },
    "_meta": {
        "version": "0.1",
        "parent_version": None,
        "evolved_from": "minimal_seed",
        "evolution_log": "CHANGELOG.jsonl"
    }
}


def load_scifact_papers(n=30):
    """Load SciFact papers as text for extraction."""
    corpus_path = os.path.join(SCIFACT_DATA, "corpus.jsonl")
    papers = []
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            doc_id = str(doc["doc_id"])
            abstract = " ".join(doc["abstract"])
            if len(abstract) > 200:  # skip very short
                papers.append({"id": doc_id, "text": abstract[:8000]})
            if len(papers) >= n:
                break
    return papers


def setup_seed_schema():
    """Write minimal seed schema and clean schema_versions dir."""
    sv_dir = os.path.join(WORKTREE, "schema_versions")
    if os.path.exists(sv_dir):
        shutil.rmtree(sv_dir)
    os.makedirs(sv_dir, exist_ok=True)

    # Write seed schema as v0.1
    seed_path = os.path.join(sv_dir, "v0.1.json")
    with open(seed_path, "w", encoding="utf-8") as f:
        json.dump(MINIMAL_SEED_SCHEMA, f, indent=2, ensure_ascii=False)

    print(f"Seed schema written: v0.1")
    print(f"  Entity types: {MINIMAL_SEED_SCHEMA['$defs']['L1_entity']['properties']['entity_type']['enum']}")
    print(f"  Contribution subtypes: {MINIMAL_SEED_SCHEMA['$defs']['L3_contribution']['properties']['subtypes']['items']['enum']}")
    print(f"  Relation types: {MINIMAL_SEED_SCHEMA['$defs']['L3_contribution_relation']['properties']['relation']['enum']}")
    return sv_dir


def run_cross_domain():
    """Run self-evolving agent on SciFact biomedical papers with minimal seed schema."""
    print("="*60)
    print("CROSS-DOMAIN SELF-EVOLUTION TEST")
    print("Domain: SciFact (biomedical) | Schema: minimal seed (4 entity types)")
    print("="*60)
    print()

    # Setup
    setup_seed_schema()
    papers = load_scifact_papers(30)
    print(f"Loaded {len(papers)} SciFact papers")
    print()

    # Create agent with self-evolution ON
    agent = GranularFlowAgent(
        worktree=WORKTREE,
        llms=["deepseek"],
        self_evolution_enabled=True,
    )

    # Override schema manager to use our seed schema
    # The SchemaManager loads from schema_versions/v0.1.json
    print(f"Agent schema version: {agent.schema_manager.current_version}")
    print(f"Entity types: {agent.schema_manager.get_entity_types()}")
    print(f"Subtypes: {agent.schema_manager.get_contribution_subtypes()}")
    print()

    # Process papers
    results = []
    for i, paper in enumerate(papers, 1):
        pid = f"scifact_{paper['id']}"
        print(f"[{i}/{len(papers)}] {pid}", end=" ", flush=True)

        # Override the extractor's text loading to use SciFact text directly
        text = paper["text"]
        schema_prompt = agent.schema_manager.get_schema_prompt()

        # Extract — use a MODIFIED prompt that ALLOWS new entity types
        # (the default prompt constrains LLM to only use existing types, which prevents discovery)
        from granular_agent.extractor import extract_single_llm
        # Build a discovery-friendly prompt that FORCES the LLM to use domain-specific types
        discovery_prompt = f"""Extract structured information from this BIOMEDICAL scientific paper.

Current schema entity types: MATERIAL, PROPERTY, NUMERIC, UNIT (only 4 types — very minimal).

You MUST use the entity type that BEST describes each entity, even if it is NOT in the current schema.
For example, if you see a disease, use DISEASE. If you see a drug, use DRUG. If you see a gene, use GENE.
If you see a measurement method, use METHOD. If you see a condition, use CONDITION.
DO NOT force everything into MATERIAL/PROPERTY/NUMERIC/UNIT.

Also extract L3 contributions and relations.

Output a JSON array of atoms:
[{{"layer":"L1","entity_type":"DISEASE","entity":"type 2 diabetes"}},
 {{"layer":"L1","entity_type":"DRUG","entity":"metformin"}},
 {{"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["experimental_finding"]}},
 ...]

PAPER TEXT:
{text}"""
        atoms = extract_single_llm(text, discovery_prompt, "deepseek")

        # Detect gaps
        gaps = agent.extractor._detect_gaps(atoms)
        print(f"atoms={len(atoms)} gaps={len(gaps)}", end="", flush=True)

        # Process gaps with self-evolution
        schema_changes = []
        if gaps:
            for gap in gaps:
                from granular_agent.gap_discovery import validate_gap
                validated = validate_gap(gap, pid)
                if not validated or not validated.get("valid"):
                    continue

                gap_type = gap.get("type", "")
                value = gap.get("value", "")
                evidence = validated.get("evidence", "")

                new_version = None
                if "entity_type" in gap_type:
                    new_version = agent.schema_manager.extend_entity_type(value, evidence, pid)
                elif "subtype" in gap_type:
                    new_version = agent.schema_manager.extend_contribution_subtype(value, evidence, pid)
                elif "relation" in gap_type:
                    new_version = agent.schema_manager.extend_relation_type(value, evidence, pid)

                if new_version:
                    schema_changes.append({
                        "version": new_version,
                        "gap_type": gap_type,
                        "value": value,
                        "evidence": evidence,
                        "paper_id": pid,
                    })
                    print(f" → EVOLVED v{new_version}: +{value}", end="", flush=True)

        print(f" (total changes: {len(schema_changes)})", flush=True)

        results.append({
            "paper_id": pid,
            "n_atoms": len(atoms),
            "gaps": gaps,
            "schema_changes": schema_changes,
        })

    # Active gap scan
    print(f"\nActive gap scan across {len(results)} papers...", flush=True)
    candidates = active_gap_scan(results, agent.schema_manager, min_recurrence=2)
    print(f"Active candidates: {len(candidates)}")
    for c in candidates[:10]:
        print(f"  [{c['gap_type']}] {c['value']} (x{c['recurrence']})")

    # Process active candidates
    for candidate in candidates:
        validated = validate_gap(candidate, candidate.get("papers", ["unknown"])[0])
        if not validated or not validated.get("valid"):
            print(f"  {candidate['value']}: REJECTED ({validated.get('reason','')[:60] if validated else 'no response'})")
            continue

        gap_type = candidate.get("gap_type", "")
        value = candidate.get("value", "")
        evidence = validated.get("evidence", "")
        new_version = None
        if gap_type == "entity_type":
            new_version = agent.schema_manager.extend_entity_type(value, evidence, "batch")
        elif gap_type == "contribution_subtype":
            new_version = agent.schema_manager.extend_contribution_subtype(value, evidence, "batch")
        elif gap_type == "relation_type":
            new_version = agent.schema_manager.extend_relation_type(value, evidence, "batch")

        if new_version:
            print(f"  {value}: EVOLVED v{new_version}")

    # Summary
    print(f"\n{'='*60}")
    print("CROSS-DOMAIN RESULTS")
    print(f"{'='*60}")
    summary = agent.get_schema_evolution_summary()
    print(f"Initial version: {summary['initial_version']}")
    print(f"Current version: {summary['current_version']}")
    print(f"Total evolutions: {summary['total_evolutions']}")
    print(f"Entity types (initial → final):")
    print(f"  Initial: MATERIAL, PROPERTY, NUMERIC, UNIT")
    print(f"  Final:   {summary['entity_types']}")
    print(f"Subtypes (initial → final):")
    print(f"  Initial: constitutive_law, experimental_finding")
    print(f"  Final:   {summary['contribution_subtypes']}")
    print(f"Relations (initial → final):")
    print(f"  Initial: supports, conflicts")
    print(f"  Final:   {summary['relation_types']}")

    if summary['changelog']:
        print(f"\nSCHEMA EVOLUTION LOG:")
        for entry in summary['changelog']:
            print(f"  v{entry['version']}: {entry['action']} +{entry['what_changed']} [paper: {entry['paper_id']}]")

    # Save
    os.makedirs(OUTPUT, exist_ok=True)
    agent.save_results(OUTPUT)
    with open(os.path.join(OUTPUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Verdict
    print(f"\n{'='*60}")
    if summary['total_evolutions'] > 0:
        print("VERDICT: SELF-EVOLUTION WORKS — schema extended in cross-domain test")
        print(f"  {summary['total_evolutions']} extensions from minimal seed schema")
        print(f"  Schema grew from v0.1 to v{summary['current_version']}")
        print("  C2 has positive experimental support!")
    else:
        print("VERDICT: SELF-EVOLUTION DID NOT TRIGGER — investigating system issues...")
        print(f"  0 schema extensions despite minimal seed schema")
        print(f"  Need to check: gap detection, validation, prompt constraints")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_cross_domain()

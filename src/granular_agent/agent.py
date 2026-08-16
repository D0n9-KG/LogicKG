"""GranularFlow-Bench Agent: self-evolving schema extraction agent.

Main entry point. Orchestrates the full pipeline:
  Extract → Fuse → GapDiscovery → Validate → ExtendSchema → QAGenerate

Uses Pydantic AI for the agent framework (capabilities + hooks),
but the core flow is deterministic with event-triggered branches.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from granular_agent.schema_manager import SchemaManager
from granular_agent.extractor import Extractor
from granular_agent.structure_mapper import load_paper_blocks, full_text_from_blocks, map_structure
from granular_agent.chained_extractor import extract_chained
from granular_agent import grounding as grounding_mod
from granular_agent.gap_discovery import active_gap_scan, validate_gap
from granular_agent.qa_generator import generate_qa
from granular_agent.llm_client import call_llm, parse_json_response
from granular_agent.hypergraph_schema import seed_meta_hypergraph, InstanceCorpus, MetaHypergraph
from granular_agent.hypergraph_extractor import extract_hypergraph
from granular_agent.hypergraph_evolution import (
    EvolutionTrigger, run_split, run_merge, run_retire, run_rename,
    infer_pattern_dependencies)


class GranularFlowAgent:
    """Self-evolving schema extraction agent for granular flow literature.

    Architecture: single-agent + capabilities + hooks (not multi-agent, not autonomous).
    Deterministic flow with event-triggered schema evolution branches.
    """

    def __init__(self, worktree: str = "C:/Users/D0n9/Desktop/LogicKG-benchmark",
                 llms: list[str] = None,
                 self_evolution_enabled: bool = True):
        self.worktree = worktree
        self.schema_manager = SchemaManager(worktree)
        self.llms = llms or ["deepseek"]
        self.extractor = Extractor(self.schema_manager, llms=self.llms)
        self.self_evolution_enabled = self_evolution_enabled

        # Hook registry (event-driven triggers)
        self.hooks = {
            "on_extraction_complete": [],
            "on_gap_found": [],
            "on_batch_complete": [],
            "on_schema_extended": [],
            "on_qa_generated": [],
        }

        # State
        self.extraction_results = []
        self.schema_evolution_log = []
        self.qa_pairs = []

        # Hypergraph (deep self-evolution) path state. Shared across papers so
        # the meta-hypergraph + trigger persist (cross-paper evolution). This
        # path is parallel to the old atom pipeline; see process_paper_hypergraph.
        self.meta_hg = seed_meta_hypergraph()
        self.hg_trigger = EvolutionTrigger()
        self.hg_results = []
        # cross-paper instance corpus (Path C stage-3): accumulates each
        # paper's InstanceHypergraph + merges nodes by surface so cross-paper
        # downstream (QA/retrieval/conflict) works — the shared meta alone
        # was only a schema bridge, this is the instance bridge.
        self.hg_corpus = InstanceCorpus()

    def register_hook(self, event: str, handler):
        """Register an event hook."""
        if event in self.hooks:
            self.hooks[event].append(handler)

    def _fire_hooks(self, event: str, data: dict):
        """Fire all hooks for an event."""
        for handler in self.hooks.get(event, []):
            handler(data)

    def _extract_adaptive(self, paper_id: str, intra_dag_evolution: bool = False) -> dict:
        """Three-phase extraction: structure map → chained DAG → grounding.

        Replaces the truncating Extractor.extract() for full-text coverage.
        Falls back to the old extractor only if structure mapping fails.
        When intra_dag_evolution=True, schema evolves DURING Phase 1 (v2 design).
        """
        blocks = load_paper_blocks(paper_id)
        if not blocks:
            return {"atoms": [], "gaps": [], "error": "no_text", "n_calls": 0}

        llm = self.llms[0] if self.llms else "deepseek"

        # Phase 0: structure mapping (1 call, full text in context)
        smap = map_structure(paper_id, blocks, llm=llm)
        if not smap or not smap.get("dag", {}).get("nodes"):
            # Fallback to old truncated extractor if structure mapping fails
            print(f"    [fallback] structure mapping failed → old extractor", flush=True)
            return self.extractor.extract(paper_id)

        full_text = full_text_from_blocks(blocks)

        # Phase 1: chained extraction over DAG (4-8 calls)
        ext = extract_chained(smap, blocks, self.schema_manager, llm=llm,
                             intra_dag_evolution=intra_dag_evolution,
                             full_text=full_text, paper_id=paper_id)
        atoms = ext["atoms"]
        n_calls = ext["n_calls"]
        intra_evolutions = ext.get("schema_evolutions", [])
        intra_gap_count = len(ext.get("gap_records", []))
        if intra_dag_evolution:
            print(f"    Phase1 [intra-DAG]: {intra_gap_count} gaps detected across nodes, "
                  f"{len(intra_evolutions)} extensions accepted", flush=True)
        print(f"    Phase1: {len(atoms)} atoms in {n_calls} calls ({ext['fissions']} fissions)", flush=True)

        # Phase 2: grounding + rebind + lookup (deterministic + 0-1 LLM call)
        atoms = grounding_mod.attach_discourse_roles(atoms, smap)
        atoms = grounding_mod.ground_atoms(atoms, full_text)
        rebind_candidates = grounding_mod.find_rebind_candidates(atoms)
        pre = grounding_mod.summary(atoms)
        print(f"    Phase2-pre: in_text {pre['n_in_text']}/{pre['n_atoms']} "
              f"({pre['n_in_text']/pre['n_atoms']:.3f} compliance) | "
              f"supported {pre['n_supported']}/{pre['n_atoms']} "
              f"({pre['n_supported']/pre['n_atoms']:.3f} REAL support)", flush=True)
        lookup_needed = pre["n_atoms"] - pre["n_grounded"] > 0 or pre["n_low_conf"] > 0
        atoms = grounding_mod.lookup(atoms, smap, blocks, llm=llm)
        if lookup_needed:
            n_calls += 1  # one lookup call ran
        atoms = grounding_mod.filter_grounded(atoms)
        post = grounding_mod.summary(atoms)
        print(f"    Phase2: grounded {pre['n_grounded']}/{pre['n_atoms']} → kept {post['n_atoms']} "
              f"({len(rebind_candidates)} rebind candidates)", flush=True)

        # Detect schema gaps on the grounded atoms (reuse extractor's logic)
        gaps = self.extractor._detect_gaps(atoms)
        return {
            "atoms": atoms,
            "gaps": gaps,
            "n_calls": n_calls + 1,  # +1 for Phase 0
            "rebind_candidates": rebind_candidates,
            "grounding": {"pre": pre, "post": post},
            "intra_evolutions": intra_evolutions,
            "intra_gap_count": intra_gap_count,
        }

    def process_paper(self, paper_id: str, intra_dag_evolution: bool = False) -> dict:
        """Process a single paper through the full pipeline.

        Returns: {paper_id, atoms, gaps, qa_pairs, schema_changes, schema_version}
        """
        print(f"  Processing {paper_id} (schema v{self.schema_manager.current_version})...", flush=True)

        # Step 1: Adaptive three-phase extraction (full text, no truncation)
        result = self._extract_adaptive(paper_id, intra_dag_evolution=intra_dag_evolution)
        atoms = result.get("atoms", [])
        gaps = result.get("gaps", [])
        n_calls = result.get("n_calls", 0)
        print(f"    Extracted {len(atoms)} atoms, {len(gaps)} gaps detected ({n_calls} calls)", flush=True)

        # Hook: on_extraction_complete
        self._fire_hooks("on_extraction_complete", {
            "paper_id": paper_id, "atoms": atoms, "gaps": gaps
        })

        # Step 2: Schema evolution
        # Intra-DAG evolution (arm C) already ran inside _extract_adaptive —
        # merge those and skip the post-hoc loop. Post-hoc evolution (arm B)
        # runs here when self_evolution_enabled and not intra_dag.
        schema_changes = list(result.get("intra_evolutions", []))
        if self.self_evolution_enabled and not intra_dag_evolution and gaps:
            for gap in gaps:
                # Hook: on_gap_found
                self._fire_hooks("on_gap_found", {"paper_id": paper_id, "gap": gap})

                # Step 3: Validate (evidence-linked)
                validated = validate_gap(gap, paper_id, self.schema_manager)
                if not validated or not validated.get("valid"):
                    continue

                # Step 4: Extend schema
                gap_type = gap.get("type", "")
                value = gap.get("value", "")
                evidence = validated.get("evidence", "")

                new_version = None
                if "entity_type" in gap_type:
                    new_version = self.schema_manager.extend_entity_type(value, evidence, paper_id)
                elif "subtype" in gap_type:
                    new_version = self.schema_manager.extend_contribution_subtype(value, evidence, paper_id)
                elif "relation" in gap_type:
                    new_version = self.schema_manager.extend_relation_type(value, evidence, paper_id)

                if new_version:
                    change = {
                        "version": new_version,
                        "gap_type": gap_type,
                        "value": value,
                        "evidence": evidence,
                        "paper_id": paper_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    schema_changes.append(change)
                    self.schema_evolution_log.append(change)

                    # Hook: on_schema_extended
                    self._fire_hooks("on_schema_extended", change)
                    print(f"    Schema evolved: v{new_version} +{value} ({gap_type})", flush=True)

        # Step 5: QA generation
        qa_pairs = generate_qa(paper_id, atoms)
        self.qa_pairs.extend(qa_pairs)

        # Hook: on_qa_generated
        self._fire_hooks("on_qa_generated", {"paper_id": paper_id, "qa_pairs": qa_pairs})

        result = {
            "paper_id": paper_id,
            "atoms": atoms,
            "n_atoms": len(atoms),
            "n_calls": n_calls,
            "gaps": gaps,
            "schema_changes": schema_changes,
            "schema_version": self.schema_manager.current_version,
            "qa_pairs": qa_pairs,
            "intra_gap_count": result.get("intra_gap_count", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.extraction_results.append(result)
        return result

    def process_batch(self, paper_ids: list[str]) -> list[dict]:
        """Process a batch of papers with active gap discovery."""
        results = []
        for pid in paper_ids:
            result = self.process_paper(pid)
            results.append(result)

        # Active gap discovery: scan across all papers
        if self.self_evolution_enabled:
            print(f"  Active gap scan across {len(results)} papers...", flush=True)
            candidates = active_gap_scan(results, self.schema_manager, min_recurrence=3)
            print(f"    Found {len(candidates)} recurring gap candidates", flush=True)

            for candidate in candidates:
                # Hook: on_gap_found
                self._fire_hooks("on_gap_found", {"paper_id": "batch", "gap": candidate})

                # Validate
                validated = validate_gap(candidate, candidate.get("papers", ["unknown"])[0], self.schema_manager)
                if not validated or not validated.get("valid"):
                    continue

                # Extend schema
                gap_type = candidate.get("gap_type", "")
                value = candidate.get("value", "")
                evidence = validated.get("evidence", "")

                new_version = None
                if gap_type == "entity_type":
                    new_version = self.schema_manager.extend_entity_type(value, evidence, "batch")
                elif gap_type == "contribution_subtype":
                    new_version = self.schema_manager.extend_contribution_subtype(value, evidence, "batch")
                elif gap_type == "relation_type":
                    new_version = self.schema_manager.extend_relation_type(value, evidence, "batch")

                if new_version:
                    change = {
                        "version": new_version,
                        "gap_type": gap_type,
                        "value": value,
                        "evidence": evidence,
                        "paper_id": "batch",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    self.schema_evolution_log.append(change)
                    self._fire_hooks("on_schema_extended", change)
                    print(f"    Schema evolved (batch): v{new_version} +{value} ({gap_type})", flush=True)

        # Hook: on_batch_complete
        self._fire_hooks("on_batch_complete", {"results": results})

        return results

    def process_paper_hypergraph(self, paper_id: str) -> dict:
        """Process one paper through the DEEP self-evolution hypergraph path.

        Uses the shared meta-hypergraph + trigger (cross-paper evolution):
        patterns added by earlier papers are available to this one, and
        structural-mismatch recurrence accumulates across papers. The
        meta-hypergraph is mutated in place.
        """
        llm = self.llms[0] if self.llms else "deepseek"
        blocks = load_paper_blocks(paper_id)
        if not blocks:
            return {"paper_id": paper_id, "error": "no_text", "n_nodes": 0, "n_hyperedges": 0}
        smap = map_structure(paper_id, blocks, llm=llm)
        if not smap or not smap.get("dag", {}).get("nodes"):
            print(f"  [hypergraph] structure mapping failed for {paper_id}", flush=True)
            return {"paper_id": paper_id, "error": "structure_map_failed"}
        pre_v = self.meta_hg.version
        pre_patterns = set(self.meta_hg.patterns_ids())
        res = extract_hypergraph(smap, blocks, self.meta_hg, llm=llm, paper_id=paper_id,
                                 trigger=self.hg_trigger)
        acc = [e for e in res["evolutions"] if not e.get("rejected")]
        rej = [e for e in res["evolutions"] if e.get("rejected")]
        # pattern-level repair: split over-wide patterns (deterministic trigger,
        # LLM names only), merge near-dup (DIAL-KG op, cited), retire orphans.
        # These mutate the shared meta_hg + re-attribute this paper's instance.
        inst = res["instance"]
        pre_repair_v = self.meta_hg.version
        splits = run_split(self.meta_hg, inst, paper_id=paper_id, llm=llm)
        merges = run_merge(self.meta_hg, inst, paper_id=paper_id, llm=llm)
        retires = run_retire(self.meta_hg, inst, paper_id=paper_id)
        renames = run_rename(self.meta_hg, llm=llm)
        deps = infer_pattern_dependencies(self.meta_hg, inst, paper_id=paper_id)
        violations = self.meta_hg.detect_constraint_violations(inst)
        result = {
            "paper_id": paper_id,
            "n_nodes": res["n_nodes"],
            "n_hyperedges": res["n_hyperedges"],
            "validation_failures": res["validation_failures"],
            "n_calls": res["n_calls"] + 1,  # +1 structure map
            "n_acc": len(acc),
            "n_rej": len(rej),
            "cross_node": sorted(set(e.get("cross_node", 1) for e in acc)),
            "new_patterns": [e.get("type_id") for e in acc
                             if e.get("op") in ("add_pattern", "add_meta_node", "add_subclass", "split_meta_node")],
            "version_before": pre_v,
            "version_after": self.meta_hg.version,
            "total_patterns_after": len(self.meta_hg.patterns),
            "repair": {
                "splits": [{"pattern": s.get("pattern_id"),
                            "sub_patterns": s.get("sub_patterns"),
                            "method": s.get("method"),
                            "cluster_sizes": s.get("cluster_sizes")}
                           for s in splits if not s.get("skipped")],
                "merges": [{"merged": m.get("merged"), "into": m.get("into"),
                            "cosine": m.get("cosine")}
                           for m in merges if not m.get("skipped")],
                "retires": [r.get("pattern_id") for r in retires],
                "version_before_repair": pre_repair_v,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.hg_results.append(result)
        # accumulate into the cross-paper instance corpus (instance bridge)
        self.hg_corpus.add_paper(inst)
        print(f"  [hypergraph] {paper_id}: {res['n_nodes']} nodes / {res['n_hyperedges']} he / "
              f"{len(acc)} acc / {len(rej)} rej | cross_node={result['cross_node']} | "
              f"v{pre_v}->{self.meta_hg.version} ({len(self.meta_hg.patterns)} patterns) | "
              f"split={len([s for s in splits if not s.get('skipped')])} "
              f"merge={len([m for m in merges if not m.get('skipped')])} "
              f"retire={len(retires)}", flush=True)
        return result

    def process_batch_hypergraph(self, paper_ids: list[str]) -> list[dict]:
        """Run the hypergraph path over a batch. Meta + trigger persist across
        papers (cross-paper deep evolution). Returns per-paper results."""
        return [self.process_paper_hypergraph(pid) for pid in paper_ids]

    def save_hypergraph_results(self, output_dir: str):
        """Save hypergraph instances + evolved meta-hypergraph (FULL field,
        round-trippable) + the cross-paper instance corpus."""
        os.makedirs(output_dir, exist_ok=True)
        # full-field meta (replaces the lossy summary that dropped
        # is_abstract/family/deprecated/family_roots — load_meta restores all).
        with open(os.path.join(output_dir, "meta_hypergraph.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta_hg.to_dict(), f, ensure_ascii=False, indent=2)
        # per-paper instances (each a full InstanceHypergraph.to_dict)
        for pid, inst in self.hg_corpus.papers.items():
            with open(os.path.join(output_dir, f"instance_{pid}.json"), "w", encoding="utf-8") as f:
                json.dump(inst.to_dict(), f, ensure_ascii=False, indent=2)
        # corpus index: cross-paper merged nodes + per-paper summary
        corpus_summary = {
            "n_papers": self.hg_corpus.n_papers(),
            "n_merged_nodes": self.hg_corpus.n_merged_nodes(),
            "n_cross_paper_nodes": len(self.hg_corpus.cross_paper_nodes()),
            "cross_paper_nodes": [n.surface for n in self.hg_corpus.cross_paper_nodes()][:50],
            "per_paper": self.hg_results,
        }
        with open(os.path.join(output_dir, "corpus_index.json"), "w", encoding="utf-8") as f:
            json.dump(corpus_summary, f, ensure_ascii=False, indent=2)
        print(f"  [hypergraph] saved meta (full-field) + {self.hg_corpus.n_papers()} instances "
              f"+ corpus ({corpus_summary['n_cross_paper_nodes']} cross-paper nodes) to {output_dir}", flush=True)

    def save_meta(self, path: str):
        """Save JUST the evolved meta-hypergraph (full-field, round-trippable)
        to `path`. Use for incremental-evolution checkpoints across sessions."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.meta_hg.to_dict(), f, ensure_ascii=False, indent=2)

    def load_meta(self, path: str) -> bool:
        """Load an evolved meta-hypergraph from a save_meta output, replacing
        the current seed meta. Closes the 'schema gone after the run' gap:
        an evolved schema can be restored and incrementally evolved further
        across sessions (the self-evolution asset is now durable). Returns
        True on success."""
        try:
            with open(path, encoding="utf-8") as f:
                self.meta_hg = MetaHypergraph.from_dict(json.load(f))
            print(f"  [hypergraph] loaded meta v{self.meta_hg.version} "
                  f"({len(self.meta_hg.patterns)} patterns) from {path}", flush=True)
            return True
        except Exception as e:
            print(f"  [hypergraph] load_meta failed ({e}); keeping seed", flush=True)
            return False

    def get_schema_evolution_summary(self) -> dict:
        """Get summary of schema evolution."""
        changelog = self.schema_manager.get_changelog()
        return {
            "initial_version": "4.0",
            "current_version": self.schema_manager.current_version,
            "total_evolutions": len(changelog),
            "changelog": changelog,
            "entity_types": self.schema_manager.get_entity_types(),
            "contribution_subtypes": self.schema_manager.get_contribution_subtypes(),
            "relation_types": self.schema_manager.get_relation_types(),
        }

    def save_results(self, output_dir: str):
        """Save all results to output directory."""
        os.makedirs(output_dir, exist_ok=True)

        # Extraction results
        with open(os.path.join(output_dir, "extraction_results.json"), "w", encoding="utf-8") as f:
            json.dump(self.extraction_results, f, ensure_ascii=False, indent=2)

        # QA pairs
        with open(os.path.join(output_dir, "qa_pairs.json"), "w", encoding="utf-8") as f:
            json.dump(self.qa_pairs, f, ensure_ascii=False, indent=2)

        # Schema evolution summary
        with open(os.path.join(output_dir, "schema_evolution.json"), "w", encoding="utf-8") as f:
            json.dump(self.get_schema_evolution_summary(), f, ensure_ascii=False, indent=2)

        print(f"  Results saved to {output_dir}", flush=True)

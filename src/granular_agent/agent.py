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
from granular_agent.gap_discovery import active_gap_scan, validate_gap
from granular_agent.qa_generator import generate_qa
from granular_agent.llm_client import call_llm, parse_json_response


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
        self.extractor = Extractor(self.schema_manager, llms=llms or ["deepseek"])
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

    def register_hook(self, event: str, handler):
        """Register an event hook."""
        if event in self.hooks:
            self.hooks[event].append(handler)

    def _fire_hooks(self, event: str, data: dict):
        """Fire all hooks for an event."""
        for handler in self.hooks.get(event, []):
            handler(data)

    def process_paper(self, paper_id: str) -> dict:
        """Process a single paper through the full pipeline.

        Returns: {paper_id, atoms, gaps, qa_pairs, schema_changes, schema_version}
        """
        print(f"  Processing {paper_id} (schema v{self.schema_manager.current_version})...", flush=True)

        # Step 1: Extract
        result = self.extractor.extract(paper_id)
        atoms = result.get("atoms", [])
        gaps = result.get("gaps", [])
        print(f"    Extracted {len(atoms)} atoms, {len(gaps)} gaps detected", flush=True)

        # Hook: on_extraction_complete
        self._fire_hooks("on_extraction_complete", {
            "paper_id": paper_id, "atoms": atoms, "gaps": gaps
        })

        # Step 2: Gap discovery (passive already done in extractor)
        # If self-evolution enabled and gaps found, validate + extend
        schema_changes = []
        if self.self_evolution_enabled and gaps:
            for gap in gaps:
                # Hook: on_gap_found
                self._fire_hooks("on_gap_found", {"paper_id": paper_id, "gap": gap})

                # Step 3: Validate (evidence-linked)
                validated = validate_gap(gap, paper_id)
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
            "gaps": gaps,
            "schema_changes": schema_changes,
            "schema_version": self.schema_manager.current_version,
            "qa_pairs": qa_pairs,
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
                validated = validate_gap(candidate, candidate.get("papers", ["unknown"])[0])
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

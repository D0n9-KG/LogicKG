"""Schema version manager: append-only + provenance tracking.

Manages schema versions with full history. Each evolution creates a new
version file (never overwrites) and appends a CHANGELOG entry.
"""

from __future__ import annotations

import json
import os
import copy
from datetime import datetime, timezone
from pathlib import Path


class SchemaManager:
    """Manages schema versions with append-only evolution and provenance."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.versions_dir = self.base_dir / "schema_versions"
        self.changelog_path = self.versions_dir / "CHANGELOG.jsonl"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

        # Load or initialize from v4 base
        self._current = self._load_current()

    def _load_current(self) -> dict:
        """Load the latest schema version, or initialize from v4 base."""
        versions = sorted(self.versions_dir.glob("v*.json"))
        if not versions:
            # Copy from the base schema v4
            base_path = self.base_dir / "schema" / "granular_flow.schema.json"
            if base_path.exists():
                schema = json.load(open(base_path, encoding="utf-8"))
                # Add _meta block
                schema["_meta"] = {
                    "version": "4.0",
                    "parent_version": None,
                    "evolved_from": "manual_v4",
                    "evolution_log": "CHANGELOG.jsonl"
                }
                self._save_version("4.0", schema)
                return schema
            else:
                raise FileNotFoundError(f"Base schema not found: {base_path}")
        # Load latest version
        latest = versions[-1]
        schema = json.load(open(latest, encoding="utf-8"))
        # Update current version path
        self._current_version = schema.get("_meta", {}).get("version", "4.0")
        return schema

    def _save_version(self, version: str, schema: dict):
        """Save a new schema version file (never overwrite)."""
        path = self.versions_dir / f"v{version}.json"
        schema["_meta"] = schema.get("_meta", {})
        schema["_meta"]["version"] = version
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)

    def _next_version(self) -> str:
        """Get next version number (e.g., 4.0 -> 4.1)."""
        current = self._current.get("_meta", {}).get("version", "4.0")
        parts = current.split(".")
        major = parts[0]
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"{major}.{minor + 1}"

    @property
    def current_schema(self) -> dict:
        return self._current

    @property
    def current_version(self) -> str:
        return self._current.get("_meta", {}).get("version", "4.0")

    def get_entity_types(self) -> list[str]:
        """Get L1 entity types from the schema."""
        try:
            return self._current["$defs"]["L1_entity"]["properties"]["entity_type"]["enum"]
        except (KeyError, TypeError):
            return []

    def get_contribution_subtypes(self) -> list[str]:
        """Get L3 CONTRIBUTION subtypes from the schema."""
        try:
            items = self._current["$defs"]["L3_contribution"]["properties"]["subtypes"]["items"]["enum"]
            return items
        except (KeyError, TypeError):
            return []

    def get_relation_types(self) -> list[str]:
        """Get L3 CONTRIBUTION_RELATION types."""
        try:
            return self._current["$defs"]["L3_contribution_relation"]["properties"]["relation"]["enum"]
        except (KeyError, TypeError):
            return []

    def extend_entity_type(self, new_type: str, evidence: str, paper_id: str) -> str | None:
        """Add a new L1 entity type. Returns new version string or None if already exists."""
        existing = self.get_entity_types()
        if new_type.upper() in [t.upper() for t in existing]:
            return None  # Already exists

        new_schema = copy.deepcopy(self._current)
        new_schema["$defs"]["L1_entity"]["properties"]["entity_type"]["enum"].append(new_type.upper())

        version = self._next_version()
        self._save_version(version, new_schema)
        self._log_change(version, "add_entity_type", new_type, evidence, paper_id)
        self._current = new_schema
        return version

    def extend_contribution_subtype(self, new_subtype: str, evidence: str, paper_id: str) -> str | None:
        """Add a new L3 CONTRIBUTION subtype."""
        existing = self.get_contribution_subtypes()
        if new_subtype.lower() in [s.lower() for s in existing]:
            return None

        new_schema = copy.deepcopy(self._current)
        new_schema["$defs"]["L3_contribution"]["properties"]["subtypes"]["items"]["enum"].append(new_subtype.lower())

        version = self._next_version()
        self._save_version(version, new_schema)
        self._log_change(version, "add_contribution_subtype", new_subtype, evidence, paper_id)
        self._current = new_schema
        return version

    def extend_relation_type(self, new_type: str, evidence: str, paper_id: str) -> str | None:
        """Add a new L3 CONTRIBUTION_RELATION type."""
        existing = self.get_relation_types()
        if new_type.lower() in [t.lower() for t in existing]:
            return None

        new_schema = copy.deepcopy(self._current)
        new_schema["$defs"]["L3_contribution_relation"]["properties"]["relation"]["enum"].append(new_type.lower())

        version = self._next_version()
        self._save_version(version, new_schema)
        self._log_change(version, "add_relation_type", new_type, evidence, paper_id)
        self._current = new_schema
        return version

    def _log_change(self, version: str, action: str, what_changed: str,
                    evidence: str, paper_id: str):
        """Append a changelog entry."""
        entry = {
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "what_changed": what_changed,
            "evidence": evidence,
            "paper_id": paper_id,
            "who_decided": "self-evolving-agent"
        }
        with open(self.changelog_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_changelog(self) -> list[dict]:
        """Read the full changelog."""
        if not self.changelog_path.exists():
            return []
        entries = []
        with open(self.changelog_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def canonicalize(self) -> list[dict]:
        """EDC-style canonicalize: merge near-duplicate enum values across all
        dimensions. Uses token-set Jaccard >=0.7 to detect near-duplicates.
        Returns list of merges performed. Call after a batch to prevent bloat.
        """
        from granular_agent.grounding import _tokens
        merges = []
        for dim, def_path in [
            ("entity_type", ["$defs", "L1_entity", "properties", "entity_type", "enum"]),
            ("contribution_subtype", ["$defs", "L3_contribution", "properties", "subtypes", "items", "enum"]),
            ("relation_type", ["$defs", "L3_contribution_relation", "properties", "relation", "enum"]),
        ]:
            try:
                enum = self._current
                for p in def_path:
                    enum = enum[p]
            except (KeyError, TypeError):
                continue
            # find near-duplicate pairs
            to_remove = set()
            for i, a in enumerate(enum):
                if a in to_remove:
                    continue
                a_tokens = _tokens(a)
                if not a_tokens:
                    continue
                for j in range(i + 1, len(enum)):
                    b = enum[j]
                    if b in to_remove:
                        continue
                    b_tokens = _tokens(b)
                    if not b_tokens:
                        continue
                    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
                    if overlap >= 0.7 and a.lower() != b.lower():
                        # merge b into a (keep the more general / shorter one)
                        keep, drop = (a, b) if len(a) <= len(b) else (b, a)
                        to_remove.add(drop)
                        merges.append({"dimension": dim, "kept": keep, "dropped": drop, "overlap": round(overlap, 2)})
            if to_remove:
                new_schema = copy.deepcopy(self._current)
                target = new_schema
                for p in def_path[:-1]:
                    target = target[p]
                target[def_path[-1]] = [v for v in target[def_path[-1]] if v not in to_remove]
                version = self._next_version()
                self._save_version(version, new_schema)
                self._log_change(version, "canonicalize", ",".join(sorted(to_remove)),
                                 f"merged {len(to_remove)} near-duplicates", "canonicalize")
                self._current = new_schema
        return merges

    def get_schema_prompt(self) -> str:
        """Generate a prompt fragment describing the current schema for LLM extraction."""
        entity_types = self.get_entity_types()
        subtypes = self.get_contribution_subtypes()
        relations = self.get_relation_types()

        return f"""Schema (v{self.current_version}, contribution-centric):

L1 entities ({', '.join(entity_types)}).
L2 relations: measures_property, property_value, condition_environment, condition_sampleFeatures, condition_instrument, taken_from.
L3 contribution layer:
  - CONTRIBUTION (reified, multi-label subtypes: {', '.join(subtypes)})
  - CONTRIBUTION_RELATION: {', '.join(relations)}
  - RESEARCH_QUESTION: the paper's research question.
  - CLOSURE (optional, for multi-variable constitutive laws)
Paper-level: paper_type = rheology | experiment | theory | DEM | review | other."""

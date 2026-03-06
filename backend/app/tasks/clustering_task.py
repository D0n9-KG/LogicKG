"""Async task for proposition clustering into semantic groups."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.ops_config_store import merge_similarity_config
from app.settings import Settings
from app.similarity.clustering import cluster_propositions
from app.similarity.embedding import get_embeddings_batch

logger = logging.getLogger(__name__)


def _normalized_similarity_threshold(raw: Any, *, default: float = 0.85) -> float:
    """Parse and clamp clustering threshold to valid range [0.0, 1.0].

    Args:
        raw: Raw threshold value from settings (float, str, or other)
        default: Default value if parsing fails

    Returns:
        Normalized threshold in range [0.0, 1.0]
    """
    try:
        value = float(raw)
    except (ValueError, TypeError):
        value = float(default)
    return max(0.0, min(1.0, value))


def _normalized_clustering_method(raw: Any, *, default: str = "agglomerative") -> str:
    value = str(raw or default).strip().lower()
    if value not in {"agglomerative", "louvain", "hybrid"}:
        return str(default).strip().lower()
    return value


def _effective_similarity_config(settings_obj: Settings) -> dict[str, Any]:
    merged = merge_similarity_config({})
    return {
        "group_clustering_threshold": _normalized_similarity_threshold(
            merged.get("group_clustering_threshold", getattr(settings_obj, "group_clustering_threshold", 0.85)),
            default=0.85,
        ),
        "group_clustering_method": _normalized_clustering_method(
            merged.get("group_clustering_method", getattr(settings_obj, "group_clustering_method", "hybrid")),
            default="hybrid",
        ),
    }


def run_proposition_clustering(task_id: str | None = None) -> dict[str, Any]:
    """
    Async task: Cluster propositions into semantic groups.

    Args:
        task_id: Optional task ID for status tracking

    Returns:
        Result summary dict with status, groups_created, propositions_clustered
    """
    try:
        logger.info(f"Starting proposition clustering task: {task_id}")

        settings = Settings()

        # P1-Top3: Get clustering controls from centralized config (settings as fallback).
        similarity_cfg = _effective_similarity_config(settings)
        threshold = float(similarity_cfg["group_clustering_threshold"])
        clustering_method = str(similarity_cfg["group_clustering_method"])

        # 1. Fetch all propositions from Neo4j
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            query = """
            MATCH (p:Proposition)
            RETURN p.prop_id as prop_id,
                   p.canonical_text as text,
                   coalesce(p.paper_count, 0) as paper_count
            ORDER BY p.created_at
            """
            with client._driver.session() as session:
                result = session.run(query)
                propositions = [dict(record) for record in result]

        # P1-Top3: If no propositions, clean stale groups before returning
        if not propositions:
            logger.warning("No propositions found for clustering; clearing stale groups")
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                cleanup_stats = _clear_existing_proposition_groups(client)
            logger.info(
                "Cleared %s old groups and %s IN_GROUP memberships (no propositions available)",
                cleanup_stats["groups_deleted"],
                cleanup_stats["memberships_deleted"],
            )
            return {
                "status": "completed",
                "groups_created": 0,
                "propositions_clustered": 0,
                "groups_deleted": cleanup_stats["groups_deleted"],
                "memberships_deleted": cleanup_stats["memberships_deleted"],
                "similarity_threshold": threshold,
            }

        logger.info(f"Fetched {len(propositions)} propositions")

        # 2. Generate embeddings
        texts = [p["text"] for p in propositions]
        embedding_model = settings.effective_embedding_model() or "text-embedding-3-small"
        embeddings = get_embeddings_batch(texts, model=embedding_model)

        logger.info(f"Generated {len(embeddings)} embeddings")

        # 3. Cluster propositions
        groups = cluster_propositions(
            embeddings,
            texts,
            threshold=threshold,
            method=clustering_method,
        )

        logger.info(f"Found {len(groups)} proposition groups")

        # 4. Write PropositionGroups to Neo4j (clean rebuild)
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            cleanup_stats = _clear_existing_proposition_groups(client)
            logger.info(
                "Cleared %s old groups and %s IN_GROUP memberships",
                cleanup_stats["groups_deleted"],
                cleanup_stats["memberships_deleted"],
            )
            for group in groups:
                # Get proposition IDs for this group
                member_prop_ids = [propositions[i]["prop_id"] for i in group["member_indices"]]

                # P1-Top3: Calculate real paper_count for this group
                paper_count = _count_unique_papers_for_propositions(client, member_prop_ids)

                # Use avg_similarity as score for all members (could be refined)
                similarity_scores = [group["avg_similarity"]] * len(member_prop_ids)

                group_id = _create_proposition_group(
                    client=client,
                    label_text=group["representative_text"],
                    member_prop_ids=member_prop_ids,
                    similarity_scores=similarity_scores,
                    paper_count=paper_count,
                    model=embedding_model,
                    version="2024-01",
                    threshold=threshold,
                    method=clustering_method,
                )
                logger.info(f"Created group {group_id} with {group['member_count']} members")

        return {
            "status": "completed",
            "groups_created": len(groups),
            "propositions_clustered": len(propositions),
            "groups_deleted": cleanup_stats["groups_deleted"],
            "memberships_deleted": cleanup_stats["memberships_deleted"],
            "similarity_threshold": threshold,
            "clustering_method": clustering_method,
        }

    except Exception as e:
        logger.error(f"Clustering task failed: {e}", exc_info=True)
        # Re-raise to fail the task properly (don't return success-like payload)
        raise RuntimeError(f"Proposition clustering failed: {str(e)}") from e


def _clear_existing_proposition_groups(client: Neo4jClient) -> dict[str, int]:
    """Remove existing PropositionGroup nodes and IN_GROUP edges before rebuild."""
    with client._driver.session() as session:
        rel_summary = session.run(
            """
            MATCH (:Proposition)-[r:IN_GROUP]->(:PropositionGroup)
            DELETE r
            """
        ).consume()
        group_summary = session.run(
            """
            MATCH (pg:PropositionGroup)
            DETACH DELETE pg
            """
        ).consume()

    return {
        "memberships_deleted": int(rel_summary.counters.relationships_deleted or 0),
        "groups_deleted": int(group_summary.counters.nodes_deleted or 0),
    }


def _count_unique_papers_for_propositions(client: Neo4jClient, prop_ids: list[str]) -> int:
    """Count distinct papers represented by a group's proposition members.

    Args:
        client: Neo4j client
        prop_ids: List of proposition IDs

    Returns:
        Number of distinct papers that contain these propositions
    """
    cleaned = [str(x).strip() for x in (prop_ids or []) if str(x).strip()]
    if not cleaned:
        return 0

    query = """
UNWIND $prop_ids AS prop_id
MATCH (pr:Proposition {prop_id: prop_id})
OPTIONAL MATCH (pr)<-[:MAPS_TO]-(:Claim)<-[:HAS_CLAIM]-(p:Paper)
RETURN count(DISTINCT p.paper_id) AS paper_count
"""
    with client._driver.session() as session:
        result = session.run(query, prop_ids=cleaned)
        row = result.single()

    if not row:
        return 0
    return int(row["paper_count"] or 0)


def _create_proposition_group(
    client: Neo4jClient,
    label_text: str,
    member_prop_ids: list[str],
    similarity_scores: list[float],
    paper_count: int,
    model: str,
    version: str,
    threshold: float,
    method: str
) -> str:
    """
    Create a PropositionGroup node and IN_GROUP relationships.

    Args:
        client: Neo4j client
        label_text: Representative text for the group
        member_prop_ids: List of proposition IDs in this group
        similarity_scores: Similarity scores for each member
        paper_count: Number of distinct papers represented by members
        model: Embedding model used
        version: Model version
        threshold: Clustering threshold
        method: Clustering method name

    Returns:
        The created group_id
    """
    # Generate group_id from label text (deterministic)
    group_id = hashlib.sha256(label_text.encode("utf-8", errors="ignore")).hexdigest()[:24]

    now = datetime.now(tz=timezone.utc).isoformat()

    # P1-Top3: Create group node with real paper_count (not hardcoded 0)
    create_group_query = """
    MERGE (pg:PropositionGroup {group_id: $group_id})
    ON CREATE SET
        pg.label_text = $label_text,
        pg.proposition_count = $proposition_count,
        pg.paper_count = $paper_count,
        pg.embedding_model = $model,
        pg.model_version = $version,
        pg.similarity_threshold = $threshold,
        pg.clustering_method = $method,
        pg.build_status = 'ready',
        pg.created_at = $created_at,
        pg.updated_at = $updated_at
    ON MATCH SET
        pg.updated_at = $updated_at,
        pg.proposition_count = $proposition_count,
        pg.paper_count = $paper_count
    """

    with client._driver.session() as session:
        session.run(
            create_group_query,
            group_id=group_id,
            label_text=label_text,
            proposition_count=len(member_prop_ids),
            paper_count=max(0, int(paper_count)),
            model=model,
            version=version,
            threshold=threshold,
            method=method,
            created_at=now,
            updated_at=now
        )

        # Create IN_GROUP relationships
        for prop_id, score in zip(member_prop_ids, similarity_scores, strict=True):
            rel_query = """
            MATCH (p:Proposition {prop_id: $prop_id})
            MATCH (pg:PropositionGroup {group_id: $group_id})
            MERGE (p)-[r:IN_GROUP]->(pg)
            ON CREATE SET
                r.similarity_score = $score,
                r.model = $model,
                r.version = $version,
                r.added_at = $added_at
            ON MATCH SET
                r.similarity_score = $score,
                r.added_at = $added_at
            """
            session.run(
                rel_query,
                prop_id=prop_id,
                group_id=group_id,
                score=score,
                model=model,
                version=version,
                added_at=now
            )

    return group_id

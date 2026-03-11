from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _adapter_module():
    return importlib.import_module("app.community.tree_comm_adapter")


def _vendored_tree_comm_module():
    sys.modules.pop("vendor.youtu_graphrag.utils.tree_comm", None)
    return importlib.import_module("vendor.youtu_graphrag.utils.tree_comm")


def test_vendored_tree_comm_upstream_note_exists() -> None:
    upstream = Path(__file__).resolve().parents[1] / "vendor" / "youtu_graphrag" / "UPSTREAM.md"
    assert upstream.is_file(), "Expected backend/vendor/youtu_graphrag/UPSTREAM.md to document the vendored source."


def test_vendored_tree_comm_uses_internal_compat_layers() -> None:
    module = _vendored_tree_comm_module()

    assert module.torch.__name__.startswith("vendor.youtu_graphrag.")
    assert module.SentenceTransformer.__module__.startswith("vendor.youtu_graphrag.")


def test_run_tree_comm_uses_vendored_fast_tree_comm(monkeypatch) -> None:
    adapter = _adapter_module()
    graph = adapter.MultiDiGraph()
    graph.add_node("ke-1", label="KnowledgeEntity", properties={"name": "Finite Element Method"})
    graph.add_node("cl-1", label="Claim", properties={"name": "Finite element meshes improve stability."})
    graph.add_edge("ke-1", "cl-1", relation="RELATES_TO")

    calls: dict[str, object] = {}

    class _FakeFastTreeComm:
        def __init__(self, graph, embedding_model="all-MiniLM-L6-v2", struct_weight=0.3, config=None):  # noqa: ANN001
            calls["graph"] = graph
            calls["embedding_model"] = embedding_model
            calls["struct_weight"] = struct_weight
            calls["config"] = config

        def detect_communities(self, level_nodes, **kwargs):  # noqa: ANN001
            calls["level_nodes"] = list(level_nodes)
            calls["detect_kwargs"] = dict(kwargs)
            return {7: ["ke-1", "cl-1"]}

        def extract_keywords_from_community(self, community_nodes, top_k=5):  # noqa: ANN001
            calls["keyword_nodes"] = list(community_nodes)
            calls["top_k"] = top_k
            return ["ke-1", "cl-1"]

    def _fusion_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("fusion helper should not run once TreeComm is vendored")

    monkeypatch.setattr(adapter, "FastTreeComm", _FakeFastTreeComm, raising=False)
    monkeypatch.setattr(adapter, "detect_fusion_communities", _fusion_called, raising=False)
    monkeypatch.setattr(adapter, "extract_fusion_keywords", _fusion_called, raising=False)

    result = adapter.run_tree_comm(graph, top_keywords=2, version="vtest")

    assert calls["graph"] is graph
    assert sorted(calls["level_nodes"]) == ["cl-1", "ke-1"]
    assert calls["top_k"] == 2

    communities = result["communities"]
    keywords = result["keywords"]
    assert len(communities) == 1
    assert set(communities[0]["member_ids"]) == {"ke-1", "cl-1"}
    assert communities[0]["version"] == "vtest"
    assert len(keywords) == 2
    assert {item["keyword"] for item in keywords} == {
        "Finite Element Method",
        "Finite element meshes improve stability.",
    }

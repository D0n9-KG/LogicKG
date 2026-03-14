import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings


_SETTINGS_FIELDS_TO_RESTORE = (
    "ingest_llm_max_workers",
    "phase1_chunk_claim_max_workers",
    "phase1_grounding_max_workers",
    "phase2_conflict_max_workers",
    "ingest_pre_llm_max_workers",
    "faiss_embed_max_workers",
    "llm_global_max_concurrent",
    "llm_provider",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "deepseek_api_key",
    "openrouter_api_key",
    "openai_api_key",
    "embedding_provider",
    "embedding_base_url",
    "embedding_api_key",
    "embedding_model",
    "siliconflow_api_key",
    "neo4j_uri",
    "neo4j_user",
    "neo4j_password",
    "pageindex_enabled",
    "pageindex_index_dir",
    "crossref_mailto",
    "crossref_user_agent",
    "global_community_version",
    "global_community_max_nodes",
    "global_community_max_edges",
    "global_community_top_keywords",
    "global_community_tree_comm_embedding_model",
    "global_community_tree_comm_struct_weight",
)


@pytest.fixture(autouse=True)
def _restore_settings_after_test():
    snapshot = {field: getattr(settings, field) for field in _SETTINGS_FIELDS_TO_RESTORE}
    try:
        yield
    finally:
        for field, value in snapshot.items():
            setattr(settings, field, value)


def _is_field(fields: list[dict], key: str, anchor: str) -> bool:
    return any((str(row.get("key")) == key and str(row.get("anchor")) == anchor) for row in fields)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def test_config_center_profile_roundtrip(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    client = TestClient(app)
    r0 = client.get("/config-center/profile")
    assert r0.status_code == 200, r0.text
    profile0 = r0.json()["profile"]
    assert "discovery" not in profile0["modules"]
    assert "group_clustering_threshold" in profile0["modules"]["similarity"]
    assert "runtime" in profile0["modules"]
    assert "providers" in profile0["modules"]
    assert "llm_workers" in profile0["modules"]
    assert "infra" in profile0["modules"]
    assert "integrations" in profile0["modules"]
    assert "community" in profile0["modules"]
    assert profile0["modules"]["runtime"]["ingest_llm_max_workers"] == 5
    assert profile0["modules"]["runtime"]["phase1_chunk_claim_max_workers"] == 4
    assert profile0["modules"]["runtime"]["llm_global_max_concurrent"] == 32
    assert profile0["modules"]["providers"]["llm_provider"] == "deepseek"
    assert profile0["modules"]["llm_workers"]["items"] == []
    assert profile0["modules"]["integrations"]["crossref_user_agent"] == "LogicKG/1.0"

    update = {
        "modules": {
            "discovery": {
                "domain": "fine_powder_flow",
                "max_gaps": 11,
                "community_method": "hybrid",
                "prompt_optimization_method": "rl_bandit",
            },
            "similarity": {
                "group_clustering_method": "louvain",
                "group_clustering_threshold": 0.91,
            },
            "runtime": {
                "ingest_llm_max_workers": 2,
                "phase1_chunk_claim_max_workers": 2,
                "phase1_grounding_max_workers": 2,
                "phase2_conflict_max_workers": 2,
                "ingest_pre_llm_max_workers": 4,
                "faiss_embed_max_workers": 3,
                "llm_global_max_concurrent": 10,
            },
            "providers": {
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-mini",
                "llm_api_key": "test-llm-key",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "embedding_api_key": "test-embed-key",
            },
            "llm_workers": {
                "items": [
                    {
                        "id": "worker-a",
                        "label": "Gateway A",
                        "base_url": "https://gw-a.example.com/v1",
                        "api_key": "key-a",
                        "model": "deepseek-chat",
                        "max_concurrent": 3,
                        "enabled": True,
                    },
                    {
                        "id": "",
                        "label": "",
                        "base_url": "https://gw-b.example.com/v1",
                        "api_key": "key-b",
                        "model": "",
                        "max_concurrent": 4,
                        "enabled": "yes",
                    },
                ]
            },
            "infra": {
                "neo4j_uri": "bolt://db.internal:7687",
                "neo4j_user": "graph",
                "neo4j_password": "secret",
                "pageindex_enabled": True,
                "pageindex_index_dir": "storage/pageindex-custom",
            },
            "integrations": {
                "crossref_mailto": "ops@example.com",
                "crossref_user_agent": "LogicKG-Test/1.0",
            },
            "community": {
                "global_community_version": "v2",
                "global_community_max_nodes": 120000,
                "global_community_max_edges": 180000,
                "global_community_top_keywords": 12,
                "global_community_tree_comm_embedding_model": "all-mpnet-base-v2",
                "global_community_tree_comm_struct_weight": 0.45,
            },
        }
    }
    r1 = client.put("/config-center/profile", json=update)
    assert r1.status_code == 200, r1.text
    profile1 = r1.json()["profile"]
    assert "discovery" not in profile1["modules"]
    assert profile1["modules"]["similarity"]["group_clustering_method"] == "louvain"
    assert abs(float(profile1["modules"]["similarity"]["group_clustering_threshold"]) - 0.91) < 1e-9
    assert profile1["modules"]["runtime"]["ingest_llm_max_workers"] == 4
    assert profile1["modules"]["runtime"]["phase1_chunk_claim_max_workers"] == 2
    assert profile1["modules"]["runtime"]["llm_global_max_concurrent"] == 10
    assert profile1["modules"]["providers"]["llm_provider"] == "openai"
    assert profile1["modules"]["providers"]["llm_api_key"] == "test-llm-key"
    assert len(profile1["modules"]["llm_workers"]["items"]) == 2
    assert profile1["modules"]["llm_workers"]["items"][0]["id"] == "worker-a"
    assert profile1["modules"]["llm_workers"]["items"][0]["base_url"] == "https://gw-a.example.com/v1"
    assert profile1["modules"]["llm_workers"]["items"][1]["id"]
    assert profile1["modules"]["llm_workers"]["items"][1]["max_concurrent"] == 4
    assert profile1["modules"]["llm_workers"]["items"][1]["enabled"] is True
    assert profile1["modules"]["infra"]["neo4j_uri"] == "bolt://db.internal:7687"
    assert profile1["modules"]["integrations"]["crossref_mailto"] == "ops@example.com"
    assert profile1["modules"]["community"]["global_community_version"] == "v2"
    assert profile1["modules"]["community"]["global_community_max_nodes"] == 120000

    r2 = client.get("/config-center/profile")
    assert r2.status_code == 200, r2.text
    profile2 = r2.json()["profile"]
    assert "discovery" not in profile2["modules"]
    assert profile2["modules"]["runtime"]["ingest_llm_max_workers"] == 4
    assert profile2["modules"]["runtime"]["llm_global_max_concurrent"] == 10
    assert profile2["modules"]["providers"]["llm_model"] == "gpt-4.1-mini"
    assert profile2["modules"]["llm_workers"]["items"][0]["label"] == "Gateway A"
    assert profile2["modules"]["infra"]["pageindex_enabled"] is True
    assert profile2["modules"]["integrations"]["crossref_user_agent"] == "LogicKG-Test/1.0"
    assert profile2["modules"]["community"]["global_community_tree_comm_struct_weight"] == 0.45
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-4.1-mini"
    assert settings.llm_api_key == "test-llm-key"
    assert settings.neo4j_uri == "bolt://db.internal:7687"
    assert settings.crossref_mailto == "ops@example.com"
    assert settings.global_community_version == "v2"
    assert settings.global_community_max_nodes == 120000


def test_config_center_catalog_and_assistant(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    client = TestClient(app)
    catalog_resp = client.get("/config-center/catalog")
    assert catalog_resp.status_code == 200, catalog_resp.text
    catalog = catalog_resp.json()
    modules = {str(m.get("id")): m for m in (catalog.get("modules") or []) if isinstance(m, dict)}
    assert "discovery" not in modules
    assert "similarity" in modules
    assert "runtime" in modules
    assert "schema" in modules
    assert "providers" in modules
    assert "llm_workers" in modules
    assert "infra" in modules
    assert "integrations" in modules
    assert "community" in modules
    assert _is_field(modules["similarity"].get("fields") or [], "group_clustering_method", "similarity.group_clustering_method")
    assert _is_field(modules["runtime"].get("fields") or [], "ingest_llm_max_workers", "runtime.ingest_llm_max_workers")
    assert _is_field(modules["runtime"].get("fields") or [], "phase1_chunk_claim_max_workers", "runtime.phase1_chunk_claim_max_workers")
    assert _is_field(modules["runtime"].get("fields") or [], "llm_global_max_concurrent", "runtime.llm_global_max_concurrent")
    assert not _is_field(modules["providers"].get("fields") or [], "llm_api_key", "providers.llm_api_key")
    assert _is_field(modules["providers"].get("fields") or [], "embedding_api_key", "providers.embedding_api_key")
    assert _is_field(modules["llm_workers"].get("fields") or [], "base_url", "llm_workers.base_url")
    assert _is_field(modules["infra"].get("fields") or [], "neo4j_uri", "infra.neo4j_uri")
    assert _is_field(modules["integrations"].get("fields") or [], "crossref_mailto", "integrations.crossref_mailto")
    assert _is_field(modules["community"].get("fields") or [], "global_community_max_nodes", "community.global_community_max_nodes")
    assert _is_field(modules["schema"].get("fields") or [], "rules_json", "schema.rules_json")
    similarity_fields = modules["similarity"].get("fields") or []
    assert similarity_fields
    assert not any("proposition" in str(field.get("description") or "").lower() for field in similarity_fields if isinstance(field, dict))

    assist_resp = client.post(
        "/config-center/assistant",
        json={"goal": "improve graph extraction quality and reduce noise", "max_suggestions": 6, "locale": "zh-CN"},
    )
    assert assist_resp.status_code == 200, assist_resp.text
    payload = assist_resp.json()
    assert payload.get("locale") == "zh-CN"
    suggestions = payload.get("suggestions") or []
    assert suggestions, payload
    assert any(_has_cjk(str(item.get("rationale") or "")) for item in suggestions if isinstance(item, dict))
    anchors = {str(item.get("anchor")) for item in suggestions if isinstance(item, dict)}
    assert "discovery.max_gaps" not in anchors
    assert "similarity.group_clustering_threshold" in anchors
    assert not any("鍛介" in str(item.get("rationale") or "") for item in suggestions if isinstance(item, dict))

    speed_resp = client.post(
        "/config-center/assistant",
        json={"goal": "speed up batch extraction throughput", "max_suggestions": 6, "locale": "en-US"},
    )
    assert speed_resp.status_code == 200, speed_resp.text
    speed_suggestions = speed_resp.json().get("suggestions") or []
    speed_anchors = {str(item.get("anchor")) for item in speed_suggestions if isinstance(item, dict)}
    assert "runtime.ingest_llm_max_workers" not in speed_anchors


def test_config_center_assistant_keeps_extraction_accuracy_goals_off_discovery(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    client = TestClient(app)
    assist_resp = client.post(
        "/config-center/assistant",
        json={"goal": "improve extraction accuracy for the knowledge graph", "max_suggestions": 6, "locale": "zh-CN"},
    )
    assert assist_resp.status_code == 200, assist_resp.text

    payload = assist_resp.json()
    suggestions = payload.get("suggestions") or []
    assert suggestions, payload

    anchors = {str(item.get("anchor")) for item in suggestions if isinstance(item, dict)}
    assert anchors
    assert not any(anchor.startswith("discovery.") for anchor in anchors)
    assert any(anchor.startswith("schema.") or anchor.startswith("similarity.") for anchor in anchors)


def test_config_center_can_test_llm_worker_connectivity(monkeypatch, tmp_path):
    import app.ops_config_store as config_store
    import app.api.routers.config_center as config_center_router

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    calls: list[dict] = []

    def fake_test_llm_worker_connection(worker: dict[str, object]) -> dict[str, object]:
        calls.append(worker)
        if str(worker.get("base_url")) == "https://broken.example.com/v1":
            return {"ok": False, "error": "401 Unauthorized"}
        return {"ok": True, "error": None}

    monkeypatch.setattr(config_center_router, "test_llm_worker_connection", fake_test_llm_worker_connection)

    client = TestClient(app)
    resp_ok = client.post(
        "/config-center/llm-workers/test",
        json={
            "worker": {
                "id": "worker-a",
                "label": "Gateway A",
                "base_url": "https://gw-a.example.com/v1",
                "api_key": "key-a",
                "model": "deepseek-chat",
                "max_concurrent": 3,
                "enabled": True,
            }
        },
    )
    assert resp_ok.status_code == 200, resp_ok.text
    payload_ok = resp_ok.json()
    assert payload_ok["reachable"] is True
    assert payload_ok["error"] is None
    assert payload_ok["worker"]["id"] == "worker-a"
    assert calls[-1]["base_url"] == "https://gw-a.example.com/v1"

    resp_bad = client.post(
        "/config-center/llm-workers/test",
        json={
            "worker": {
                "id": "worker-b",
                "label": "Gateway B",
                "base_url": "https://broken.example.com/v1",
                "api_key": "key-b",
                "model": "",
                "max_concurrent": 2,
                "enabled": False,
            }
        },
    )
    assert resp_bad.status_code == 200, resp_bad.text
    payload_bad = resp_bad.json()
    assert payload_bad["reachable"] is False
    assert payload_bad["error"] == "401 Unauthorized"
    assert payload_bad["worker"]["id"] == "worker-b"


def test_env_override_beats_config_center_profile(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.setenv("CROSSREF_MAILTO", "env@example.com")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")

    client = TestClient(app)
    resp = client.put(
        "/config-center/profile",
        json={
            "modules": {
                "providers": {"llm_provider": "openai"},
                "integrations": {"crossref_mailto": "cfg@example.com"},
            }
        },
    )
    assert resp.status_code == 200, resp.text

    profile = client.get("/config-center/profile").json()["profile"]
    assert profile["modules"]["providers"]["llm_provider"] == "openai"
    assert profile["modules"]["integrations"]["crossref_mailto"] == "cfg@example.com"
    assert settings.llm_provider == "deepseek"
    assert settings.crossref_mailto == "env@example.com"

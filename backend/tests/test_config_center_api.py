from fastapi.testclient import TestClient

from app.main import app


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
    assert profile0["modules"]["discovery"]["domain"]
    assert "group_clustering_threshold" in profile0["modules"]["similarity"]

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
        }
    }
    r1 = client.put("/config-center/profile", json=update)
    assert r1.status_code == 200, r1.text
    profile1 = r1.json()["profile"]
    assert profile1["modules"]["discovery"]["domain"] == "fine_powder_flow"
    assert profile1["modules"]["discovery"]["max_gaps"] == 11
    assert profile1["modules"]["similarity"]["group_clustering_method"] == "louvain"
    assert abs(float(profile1["modules"]["similarity"]["group_clustering_threshold"]) - 0.91) < 1e-9

    r2 = client.get("/config-center/profile")
    assert r2.status_code == 200, r2.text
    profile2 = r2.json()["profile"]
    assert profile2["modules"]["discovery"]["domain"] == "fine_powder_flow"


def test_config_center_catalog_and_assistant(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    client = TestClient(app)
    catalog_resp = client.get("/config-center/catalog")
    assert catalog_resp.status_code == 200, catalog_resp.text
    catalog = catalog_resp.json()
    modules = {str(m.get("id")): m for m in (catalog.get("modules") or []) if isinstance(m, dict)}
    assert "discovery" in modules
    assert "similarity" in modules
    assert "schema" in modules
    assert _is_field(modules["discovery"].get("fields") or [], "max_gaps", "discovery.max_gaps")
    assert _is_field(modules["similarity"].get("fields") or [], "group_clustering_method", "similarity.group_clustering_method")
    assert _is_field(modules["schema"].get("fields") or [], "rules_json", "schema.rules_json")

    assist_resp = client.post(
        "/config-center/assistant",
        json={"goal": "让图谱抽取更精准一些，减少噪声", "max_suggestions": 6, "locale": "zh-CN"},
    )
    assert assist_resp.status_code == 200, assist_resp.text
    payload = assist_resp.json()
    assert payload.get("locale") == "zh-CN"
    suggestions = payload.get("suggestions") or []
    assert suggestions, payload
    assert any(_has_cjk(str(item.get("rationale") or "")) for item in suggestions if isinstance(item, dict))
    anchors = {str(item.get("anchor")) for item in suggestions if isinstance(item, dict)}
    assert "discovery.max_gaps" in anchors or "similarity.group_clustering_threshold" in anchors

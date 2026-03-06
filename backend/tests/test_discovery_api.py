from fastapi.testclient import TestClient

from app.main import app
from app.ops_config_store import save_profile


def test_discovery_batch_submit_endpoint_exists():
    c = TestClient(app)
    r = c.post(
        "/discovery/batch",
        json={
            "domain": "granular_flow",
            "dry_run": True,
            "max_gaps": 4,
            "candidates_per_gap": 2,
            "use_llm": False,
            "hop_order": 2,
            "adjacent_samples": 4,
            "random_samples": 2,
            "rag_top_k": 3,
            "prompt_optimize": True,
            "community_method": "hybrid",
            "community_samples": 4,
            "prompt_optimization_method": "rl_bandit",
        },
    )
    assert r.status_code in (200, 202, 500)


def test_discovery_batch_uses_config_center_defaults(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    saved = save_profile(
        {
            "modules": {
                "discovery": {
                    "domain": "cfg_domain",
                    "dry_run": True,
                    "max_gaps": 5,
                    "candidates_per_gap": 2,
                    "use_llm": False,
                    "hop_order": 1,
                    "adjacent_samples": 4,
                    "random_samples": 1,
                    "rag_top_k": 3,
                    "prompt_optimize": False,
                    "community_method": "louvain",
                    "community_samples": 2,
                    "prompt_optimization_method": "heuristic",
                }
            }
        }
    )
    assert saved["modules"]["discovery"]["domain"] == "cfg_domain"

    captured: dict[str, object] = {}

    def fake_submit(task_type, payload):  # type: ignore[no-untyped-def]
        captured["task_type"] = task_type
        captured["payload"] = payload
        return "discovery-batch-test"

    monkeypatch.setattr("app.api.routers.discovery.task_manager.submit", fake_submit)

    c = TestClient(app)
    r = c.post("/discovery/batch", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == "discovery-batch-test"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["domain"] == "cfg_domain"
    assert payload["max_gaps"] == 5
    assert payload["community_method"] == "louvain"

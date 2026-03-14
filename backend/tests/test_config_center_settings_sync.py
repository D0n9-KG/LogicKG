from __future__ import annotations

from app.settings import settings


def test_apply_profile_to_settings_uses_config_values_when_env_not_set(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)

    previous_llm_model = settings.llm_model
    previous_crossref_mailto = settings.crossref_mailto
    try:
        config_store.save_profile(
            {
                "modules": {
                    "providers": {"llm_model": "gpt-4.1-mini"},
                    "integrations": {"crossref_mailto": "config@example.com"},
                }
            }
        )

        config_store.apply_profile_to_settings()

        assert settings.llm_model == "gpt-4.1-mini"
        assert settings.crossref_mailto == "config@example.com"
    finally:
        settings.llm_model = previous_llm_model
        settings.crossref_mailto = previous_crossref_mailto


def test_apply_profile_to_settings_keeps_env_overrides(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.setenv("CROSSREF_MAILTO", "env@example.com")

    previous_crossref_mailto = settings.crossref_mailto
    try:
        config_store.save_profile(
            {
                "modules": {
                    "integrations": {"crossref_mailto": "config@example.com"},
                }
            }
        )

        config_store.apply_profile_to_settings()

        assert settings.crossref_mailto == "env@example.com"
    finally:
        settings.crossref_mailto = previous_crossref_mailto


def test_merge_runtime_config_derives_ingest_workers_from_routable_llm_workers(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.delenv("INGEST_LLM_MAX_WORKERS", raising=False)
    monkeypatch.delenv("LLM_GLOBAL_MAX_CONCURRENT", raising=False)

    config_store.save_profile(
        {
            "modules": {
                "runtime": {
                    "ingest_llm_max_workers": 3,
                    "llm_global_max_concurrent": 12,
                },
                "llm_workers": {
                    "items": [
                        {
                            "id": "worker-a",
                            "label": "Gateway A",
                            "base_url": "https://gw-a.example.com/v1",
                            "api_key": "key-a",
                            "model": "model-a",
                            "max_concurrent": 5,
                            "enabled": True,
                        },
                        {
                            "id": "worker-b",
                            "label": "Gateway B",
                            "base_url": "https://gw-b.example.com/v1",
                            "api_key": "key-b",
                            "model": "model-b",
                            "max_concurrent": 5,
                            "enabled": True,
                        },
                    ]
                },
            }
        }
    )

    runtime = config_store.merge_runtime_config({})

    assert runtime["ingest_llm_max_workers"] == 3


def test_merge_runtime_config_caps_derived_ingest_workers_by_global_limit(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.delenv("INGEST_LLM_MAX_WORKERS", raising=False)
    monkeypatch.delenv("LLM_GLOBAL_MAX_CONCURRENT", raising=False)

    config_store.save_profile(
        {
            "modules": {
                "runtime": {
                    "ingest_llm_max_workers": 3,
                    "llm_global_max_concurrent": 7,
                },
                "llm_workers": {
                    "items": [
                        {
                            "id": "worker-a",
                            "label": "Gateway A",
                            "base_url": "https://gw-a.example.com/v1",
                            "api_key": "key-a",
                            "model": "model-a",
                            "max_concurrent": 5,
                            "enabled": True,
                        },
                        {
                            "id": "worker-b",
                            "label": "Gateway B",
                            "base_url": "https://gw-b.example.com/v1",
                            "api_key": "key-b",
                            "model": "model-b",
                            "max_concurrent": 5,
                            "enabled": True,
                        },
                    ]
                },
            }
        }
    )

    runtime = config_store.merge_runtime_config({})

    assert runtime["ingest_llm_max_workers"] == 1


def test_merge_runtime_config_respects_explicit_ingest_env_override(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    monkeypatch.setenv("INGEST_LLM_MAX_WORKERS", "6")
    monkeypatch.delenv("LLM_GLOBAL_MAX_CONCURRENT", raising=False)

    config_store.save_profile(
        {
            "modules": {
                "runtime": {
                    "ingest_llm_max_workers": 3,
                    "llm_global_max_concurrent": 12,
                },
                "llm_workers": {
                    "items": [
                        {
                            "id": "worker-a",
                            "label": "Gateway A",
                            "base_url": "https://gw-a.example.com/v1",
                            "api_key": "key-a",
                            "model": "model-a",
                            "max_concurrent": 5,
                            "enabled": True,
                        }
                    ]
                },
            }
        }
    )

    runtime = config_store.merge_runtime_config({})

    assert runtime["ingest_llm_max_workers"] == 6

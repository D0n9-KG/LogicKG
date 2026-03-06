from app.ops_config_store import save_profile
from app.settings import Settings
from app.tasks.clustering_task import _effective_similarity_config


def test_effective_similarity_config_reads_config_center(monkeypatch, tmp_path):
    import app.ops_config_store as config_store

    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    save_profile(
        {
            "modules": {
                "similarity": {
                    "group_clustering_method": "louvain",
                    "group_clustering_threshold": 0.9,
                }
            }
        }
    )
    cfg = _effective_similarity_config(Settings())
    assert cfg["group_clustering_method"] == "louvain"
    assert abs(float(cfg["group_clustering_threshold"]) - 0.9) < 1e-9


from eval_quality import compute_discovery_metrics


def test_discovery_metrics_include_evidence_support_ratio():
    m = compute_discovery_metrics([])
    assert "support_coverage" in m

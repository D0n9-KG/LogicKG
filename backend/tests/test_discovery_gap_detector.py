from app.discovery.gap_detector import detect_knowledge_gaps


def test_gap_detector_fallback_is_stable():
    rows = detect_knowledge_gaps(domain="granular_flow", limit=2)
    assert len(rows) >= 1
    assert all("gap_id" in r for r in rows)
    assert all("description" in r for r in rows)


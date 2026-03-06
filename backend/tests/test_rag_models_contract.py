from app.rag.models import AskV2Request, AskV2Response, EvidenceItem


def test_ask_v2_response_contract_has_required_fields():
    req = AskV2Request(question="what is granular flow?", locale="zh-CN")
    assert req.locale == "zh-CN"
    res = AskV2Response(answer="ok", evidence=[])
    assert hasattr(res, "answer")
    assert hasattr(res, "evidence")
    assert hasattr(res, "retrieval_mode")


def test_evidence_item_supports_paper_title():
    row = EvidenceItem(paper_id="p1", paper_title="Granular Mixing in Inclined Drums")
    assert row.paper_id == "p1"
    assert row.paper_title == "Granular Mixing in Inclined Drums"

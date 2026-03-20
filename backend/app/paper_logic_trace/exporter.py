from __future__ import annotations

from .models import ClaimTrace, LogicStepTrace, PaperLogicTrace
from .normalization import build_claim_evidence_links, normalize_claim, normalize_logic_step


def export_paper_logic_trace(client, paper_id: str) -> PaperLogicTrace:
    payload = client.get_paper_logic_trace_inputs(paper_id)
    paper_metadata = dict(payload.get('paper_metadata') or {})

    raw_logic_steps = [normalize_logic_step(row) for row in (payload.get('logic_steps') or [])]
    raw_claims = [normalize_claim(row) for row in (payload.get('claims') or [])]

    return PaperLogicTrace(
        schema_version=str(payload.get('schema_version') or 'v1'),
        paper_metadata=paper_metadata,
        logic_steps=[LogicStepTrace.model_validate(row) for row in raw_logic_steps],
        claims=[ClaimTrace.model_validate(row) for row in raw_claims],
        claim_evidence_links=list(payload.get('claim_evidence_links') or build_claim_evidence_links(raw_claims)),
        figures=list(payload.get('figures') or []),
        limitations=list(payload.get('limitations') or []),
        future_work_signals=list(payload.get('future_work_signals') or []),
        citation_acts=list(payload.get('citation_acts') or []),
        quality_tier=str(
            payload.get('quality_tier')
            or paper_metadata.get('phase1_quality_tier')
            or paper_metadata.get('quality_tier')
            or 'unknown'
        ).strip()
        or 'unknown',
    )

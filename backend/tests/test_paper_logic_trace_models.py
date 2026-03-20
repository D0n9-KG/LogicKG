from __future__ import annotations

from app.paper_logic_trace.models import ClaimTrace, LogicStepTrace, PaperLogicTrace


def test_paper_logic_trace_requires_canonical_sections() -> None:
    trace = PaperLogicTrace(
        schema_version='v1',
        paper_metadata={'paper_id': 'paper-1'},
        logic_steps=[
            LogicStepTrace(
                logic_step_id='ls-1',
                step_type='Method',
                summary='Uses graph encoding.',
            )
        ],
        claims=[
            ClaimTrace(
                claim_id='cl-1',
                claim_key='claim-1',
                text='Graph encoding improves retrieval.',
                step_type='Method',
            )
        ],
        claim_evidence_links=[],
        figures=[],
        limitations=[],
        future_work_signals=[],
        citation_acts=[],
        quality_tier='A',
    )

    assert trace.schema_version == 'v1'
    assert trace.logic_steps[0].step_type == 'Method'
    assert trace.claims[0].comparison_target == []

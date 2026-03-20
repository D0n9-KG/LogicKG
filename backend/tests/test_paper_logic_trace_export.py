from __future__ import annotations

from app.paper_logic_trace.exporter import export_paper_logic_trace


class _FakeClient:
    def get_paper_logic_trace_inputs(self, paper_id: str) -> dict:
        return {
            'paper_metadata': {
                'paper_id': paper_id,
                'title': 'Demo Paper',
                'phase1_quality_tier': 'green',
            },
            'logic_steps': [
                {
                    'logic_step_id': 'paper-1:Method',
                    'step_type': 'Method',
                    'summary': 'Uses graph encoding for retrieval.',
                }
            ],
            'claims': [
                {
                    'claim_id': 'cl-1',
                    'claim_key': 'claim-1',
                    'text': 'Graph encoding improves retrieval performance.',
                    'step_type': 'Method',
                    'kinds': ['Result', 'Comparison'],
                }
            ],
            'claim_evidence_links': [{'claim_key': 'claim-1', 'chunk_id': 'chunk-1'}],
            'citation_acts': [],
            'figures': [],
            'limitations': [],
            'future_work_signals': [],
        }


def test_export_paper_logic_trace_adds_l25_slots() -> None:
    trace = export_paper_logic_trace(_FakeClient(), 'paper-1')

    assert trace.logic_steps[0].operation_or_method
    assert 'graph' in ' '.join(trace.logic_steps[0].operation_or_method).lower()
    assert trace.claims[0].comparison_target == []
    assert trace.quality_tier == 'green'

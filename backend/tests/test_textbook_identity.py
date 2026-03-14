from pathlib import Path

from app.ingest.textbook_identity import build_textbook_id, infer_textbook_identity


def test_infer_textbook_identity_prefers_h1_title(tmp_path: Path) -> None:
    md = tmp_path / 'granular-flow.md'
    md.write_text('# Granular Flow\n\nBody text\n', encoding='utf-8')

    identity = infer_textbook_identity(md)

    assert identity.inferred_title == 'Granular Flow'
    assert identity.normalized_title == 'granular flow'
    assert identity.textbook_id.startswith('tb:')


def test_infer_textbook_identity_falls_back_to_filename(tmp_path: Path) -> None:
    md = tmp_path / 'chapter_notes.md'
    md.write_text('Body without heading\n', encoding='utf-8')

    identity = infer_textbook_identity(md)

    assert identity.inferred_title == 'chapter_notes'
    assert identity.normalized_title == 'chapter_notes'


def test_build_textbook_id_is_stable_for_same_title_and_fingerprint() -> None:
    textbook_id_1 = build_textbook_id('Granular Flow', 'abc123')
    textbook_id_2 = build_textbook_id('  granular   flow ', 'abc123')

    assert textbook_id_1 == textbook_id_2
    assert textbook_id_1.startswith('tb:')

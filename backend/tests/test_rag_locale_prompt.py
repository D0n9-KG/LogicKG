from app.rag.service import _build_system_prompt, _normalize_locale


def test_rag_locale_normalization():
    assert _normalize_locale("zh-CN") == "zh-CN"
    assert _normalize_locale("zh") == "zh-CN"
    assert _normalize_locale("en-US") == "en-US"
    assert _normalize_locale("fr-FR") == "en-US"


def test_rag_system_prompt_defaults_to_english():
    prompt = _build_system_prompt(locale="en-US")
    assert "Answer ONLY using the provided evidence snippets" in prompt


def test_rag_system_prompt_zh_requires_chinese_output():
    prompt = _build_system_prompt(locale="zh-CN")
    assert "回答请使用简体中文" in prompt
    assert "引用证据时使用 [E1]" in prompt

"""Tests for extraction noise filters (P0-5).

Tests figure/table caption and pure definition detection to filter low-quality claims.
"""
from app.extraction.noise_filters import (
    is_caption_text,
    is_pure_definition_text,
    filter_claim_candidates,
    _build_whitelist_pattern,
)


def test_detects_figure_caption_with_number():
    """Figure N: pattern should be detected."""
    assert is_caption_text("Figure 1: Experimental setup") is True
    assert is_caption_text("Figure 12: Results overview") is True


def test_detects_table_caption():
    """Table N: pattern should be detected."""
    assert is_caption_text("Table 1: Comparison of methods") is True
    assert is_caption_text("Table 5: Summary statistics") is True


def test_detects_fig_abbreviation():
    """Fig. N: pattern should be detected."""
    assert is_caption_text("Fig. 3: Data distribution") is True


def test_rejects_normal_sentences():
    """Normal scientific text should not be flagged as captions."""
    assert is_caption_text("This figure shows the results") is False
    assert is_caption_text("Our experiments demonstrate that") is False
    assert is_caption_text("The method improves performance") is False


def test_rejects_figure_references():
    """References to figures in text are not captions."""
    assert is_caption_text("as shown in Figure 1") is False
    assert is_caption_text("see Table 2 for details") is False


def test_rejects_none_and_non_string_inputs():
    """None and non-string inputs should return False."""
    assert is_caption_text("") is False
    assert is_caption_text(None) is False
    assert is_caption_text(123) is False  # type: ignore[arg-type]


def test_detects_case_insensitive_caption():
    """Caption detection should be case-insensitive."""
    assert is_caption_text("figure 1: lowercase caption") is True
    assert is_caption_text("TABLE 2: uppercase caption") is True
    assert is_caption_text("fIg. 3: Mixed case pattern") is True


def test_detects_caption_with_leading_whitespace():
    """Captions with leading whitespace should be detected."""
    assert is_caption_text("   Figure 2: With leading spaces") is True
    assert is_caption_text("\tTable 3: With tab") is True
    assert is_caption_text("\n\nFig. 4: With newlines") is True


def test_rejects_caption_without_period_in_fig():
    """Fig without period (Fig 1:) should be rejected per spec."""
    assert is_caption_text("Fig 1: Missing period") is False


def test_rejects_caption_without_colon():
    """Captions without colon (Figure 1 shows) should be rejected."""
    assert is_caption_text("Figure 1 shows the results") is False
    assert is_caption_text("Table 2 presents the data") is False


# Definition Detection Tests


def test_detects_is_definition():
    """`X is a Y` pattern"""
    assert is_pure_definition_text("Machine learning is a method of data analysis") is True
    assert is_pure_definition_text("Deep learning is a subset of machine learning") is True


def test_detects_refers_to_definition():
    """`X refers to Y` pattern"""
    assert is_pure_definition_text("This term refers to the process of optimization") is True


def test_detects_defined_as_pattern():
    """`X is defined as Y` pattern"""
    assert is_pure_definition_text("Accuracy is defined as the ratio of correct predictions") is True


def test_detects_represents_pattern():
    """`X represents Y` pattern with sufficient is/are density"""
    # "represents" + "is" gives pattern=1 and density=0.125 (1/8) > 0.08
    assert is_pure_definition_text("This metric represents what is measured in the study") is True


def test_rejects_high_verb_diversity():
    """Scientific claims with diverse verbs are not definitions"""
    assert is_pure_definition_text(
        "The model achieves better performance and reduces errors significantly"
    ) is False


def test_rejects_comparative_statements():
    """Comparative/causal statements are not definitions"""
    assert is_pure_definition_text("This approach outperforms previous methods") is False
    assert is_pure_definition_text("Increasing temperature causes faster reactions") is False
    # Test inflections
    assert is_pure_definition_text("The model improves performance significantly") is False
    assert is_pure_definition_text("This method is leading to better results") is False


def test_accepts_definition_with_comparative_substring():
    """Definitions containing substring matches should still pass if not word-boundary match"""
    # "moreover" contains "more" but is not comparative
    assert is_pure_definition_text("Moreover, entropy is a measure of uncertainty") is True
    # "leadership" contains "lead" but is not causal
    assert is_pure_definition_text("Leadership is a quality of effective management") is True


def test_rejects_none_and_empty_definition_inputs():
    """None and empty inputs should return False for definition detection"""
    assert is_pure_definition_text(None) is False
    assert is_pure_definition_text("") is False
    assert is_pure_definition_text(123) is False  # type: ignore[arg-type]


# Filter Function Tests


def test_filter_claim_candidates_basic():
    """Test basic filtering removes captions and definitions"""
    from types import SimpleNamespace

    claims = [
        {"text": "Valid scientific claim about performance", "confidence": 0.9},
        {"text": "Figure 1: Experimental setup", "confidence": 0.8},
        {"text": "Machine learning is a method of analysis", "confidence": 0.7},
        {"text": "Another valid claim with evidence", "confidence": 0.85},
    ]

    rules = SimpleNamespace(
        phase1_noise_filter_enabled=True,
        phase1_noise_filter_figure_caption_enabled=True,
        phase1_noise_filter_pure_definition_enabled=True,
    )

    filtered, stats = filter_claim_candidates(claims, rules)

    assert len(filtered) == 2
    assert filtered[0]["text"] == "Valid scientific claim about performance"
    assert filtered[1]["text"] == "Another valid claim with evidence"

    assert stats["raw_count"] == 4
    assert stats["filtered_count"] == 2
    assert stats["caption_filtered"] == 1
    assert stats["definition_filtered"] == 1
    assert stats["filter_rate"] == 0.5


def test_filter_respects_disabled_flags():
    """Test filtering can be selectively disabled"""
    from types import SimpleNamespace

    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "ML is a method", "confidence": 0.7},
    ]

    # Only caption filtering enabled
    rules = SimpleNamespace(
        phase1_noise_filter_enabled=True,
        phase1_noise_filter_figure_caption_enabled=True,
        phase1_noise_filter_pure_definition_enabled=False,
    )

    filtered, stats = filter_claim_candidates(claims, rules)

    assert len(filtered) == 1  # Only definition remains
    assert stats["caption_filtered"] == 1
    assert stats["definition_filtered"] == 0


def test_filter_disabled_returns_all():
    """Test when filtering disabled, all claims returned"""
    from types import SimpleNamespace

    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "ML is a method", "confidence": 0.7},
    ]

    rules = SimpleNamespace(phase1_noise_filter_enabled=False)

    filtered, stats = filter_claim_candidates(claims, rules)

    assert len(filtered) == 2
    assert stats["filter_rate"] == 0.0


def test_filter_with_dict_rules():
    """Test filtering works with dict-based rules (production pattern)"""
    claims = [
        {"text": "Valid claim", "confidence": 0.9},
        {"text": "Figure 1: Caption", "confidence": 0.8},
    ]

    # Dict-based rules like in production
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
    }

    filtered, stats = filter_claim_candidates(claims, rules)

    assert len(filtered) == 1
    assert stats["caption_filtered"] == 1


def test_filter_parses_string_boolean_global_toggle_from_dict():
    """String 'false' should disable filtering, not evaluate truthy."""
    claims = [
        {"text": "Figure 1: Caption", "confidence": 0.8},
        {"text": "ML is a method", "confidence": 0.7},
    ]
    rules = {
        "phase1_noise_filter_enabled": "false",
        "phase1_noise_filter_figure_caption_enabled": "true",
        "phase1_noise_filter_pure_definition_enabled": "true",
    }

    filtered, stats = filter_claim_candidates(claims, rules)

    assert len(filtered) == 2
    assert stats["filtered_count"] == 2
    assert stats["caption_filtered"] == 0
    assert stats["definition_filtered"] == 0
    assert stats["filter_rate"] == 0.0


def test_filter_parses_string_boolean_per_filter_toggle_from_object():
    """String booleans should work for attribute-based rules too."""
    from types import SimpleNamespace

    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "ML is a method", "confidence": 0.7},
        {"text": "Valid claim", "confidence": 0.9},
    ]
    rules = SimpleNamespace(
        phase1_noise_filter_enabled="true",
        phase1_noise_filter_figure_caption_enabled="off",
        phase1_noise_filter_pure_definition_enabled="on",
    )

    filtered, stats = filter_claim_candidates(claims, rules)

    assert [c["text"] for c in filtered] == ["Figure 1: Setup", "Valid claim"]
    assert stats["caption_filtered"] == 0
    assert stats["definition_filtered"] == 1


def test_filter_invalid_string_boolean_falls_back_to_default():
    """Unrecognized values should fall back to the provided default."""
    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "Valid claim", "confidence": 0.9},
    ]
    rules = {
        "phase1_noise_filter_enabled": "true",
        "phase1_noise_filter_figure_caption_enabled": "not-a-bool",
        "phase1_noise_filter_pure_definition_enabled": "false",
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    assert [c["text"] for c in filtered] == ["Valid claim"]
    assert stats["caption_filtered"] == 1
    assert stats["definition_filtered"] == 0


def test_filter_parses_numeric_zero_as_false():
    """Numeric 0 should be parsed as False, not fall back to default True."""
    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "Valid claim", "confidence": 0.9},
    ]
    # Numeric 0 with default=True should still be False
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": 0,  # Numeric 0 should disable
        "phase1_noise_filter_pure_definition_enabled": True,
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    # Caption filter should be DISABLED (0=False), so figure caption should pass
    assert [c["text"] for c in filtered] == ["Figure 1: Setup", "Valid claim"]
    assert stats["caption_filtered"] == 0
    assert stats["definition_filtered"] == 0


def test_filter_parses_numeric_one_as_true():
    """Numeric 1 should be parsed as True."""
    claims = [
        {"text": "Figure 1: Setup", "confidence": 0.8},
        {"text": "Valid claim", "confidence": 0.9},
    ]
    rules = {
        "phase1_noise_filter_enabled": 1,  # Numeric 1 should enable
        "phase1_noise_filter_figure_caption_enabled": 1,
        "phase1_noise_filter_pure_definition_enabled": 1,
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    assert [c["text"] for c in filtered] == ["Valid claim"]
    assert stats["caption_filtered"] == 1


# ── P2-13: Expanded caption patterns ──


def test_detects_supplementary_figure_caption():
    assert is_caption_text("Supplementary Figure 1: Extra data") is True
    assert is_caption_text("Supplementary Table 2: Additional stats") is True
    assert is_caption_text("supplementary figure 3: lowercase") is True


def test_detects_s_prefix_caption():
    """Figure S1:, Table S3: patterns."""
    assert is_caption_text("Figure S1: Supplementary result") is True
    assert is_caption_text("Table S3: Extra comparison") is True
    assert is_caption_text("Fig. S2: Supplementary plot") is True


def test_detects_appendix_caption():
    """Figure A1:, Table A2: patterns."""
    assert is_caption_text("Figure A1: Appendix result") is True
    assert is_caption_text("Table A2: Appendix data") is True


def test_detects_subfigure_caption():
    """Figure 1A:, Figure 12b: patterns."""
    assert is_caption_text("Figure 1A: Subfigure upper") is True
    assert is_caption_text("Figure 12b: Subfigure lower") is True


def test_detects_scheme_algorithm_listing_box():
    """Scheme, Algorithm, Listing, Box captions."""
    assert is_caption_text("Scheme 1: Reaction pathway") is True
    assert is_caption_text("Algorithm 2: Sorting procedure") is True
    assert is_caption_text("Listing 1: Code example") is True
    assert is_caption_text("Box 3: Key definitions") is True


def test_still_rejects_fig_without_period():
    """Fig without period should still be rejected."""
    assert is_caption_text("Fig 1: Missing period") is False


def test_still_rejects_inline_references():
    """Inline references should still be rejected."""
    assert is_caption_text("as shown in Figure S1") is False
    assert is_caption_text("see Supplementary Table 2") is False


# ── P2-13: Domain term whitelist ──


def test_build_whitelist_pattern_empty():
    assert _build_whitelist_pattern([]) is None
    assert _build_whitelist_pattern(["", "  "]) is None


def test_build_whitelist_pattern_matches():
    pat = _build_whitelist_pattern(["DEM", "discrete element"])
    assert pat is not None
    assert pat.search("DEM simulation results") is not None
    assert pat.search("discrete element method") is not None
    assert pat.search("random text") is None


def test_build_whitelist_pattern_handles_special_regex_chars():
    """Terms with special regex chars (C++, A/B) should be escaped properly."""
    pat = _build_whitelist_pattern(["C++", "A/B"])
    assert pat is not None
    assert pat.search("C++ simulation results") is not None
    assert pat.search("An A/B test was run") is not None


def test_build_whitelist_pattern_skips_non_strings():
    """Non-string entries should be silently skipped."""
    pat = _build_whitelist_pattern(["DEM", 123, None, ""])  # type: ignore[list-item]
    assert pat is not None
    assert pat.search("DEM results") is not None


def test_caption_whitelist_bypass():
    """Caption containing whitelisted term should NOT be filtered."""
    wl = _build_whitelist_pattern(["DEM"])
    assert is_caption_text("Figure 1: DEM simulation setup", whitelist_re=wl) is False
    # Without whitelist, same text is a caption
    assert is_caption_text("Figure 1: DEM simulation setup") is True


def test_definition_whitelist_bypass():
    """Definition containing whitelisted term should NOT be filtered."""
    wl = _build_whitelist_pattern(["DEM"])
    assert is_pure_definition_text(
        "DEM is a numerical method for computing", whitelist_re=wl
    ) is False
    # Without whitelist, same text is a definition
    assert is_pure_definition_text(
        "DEM is a numerical method for computing"
    ) is True


def test_filter_with_domain_whitelist():
    """filter_claim_candidates respects domain whitelist from rules."""
    claims = [
        {"text": "Figure 1: DEM particle setup", "confidence": 0.8},
        {"text": "Figure 2: Random caption", "confidence": 0.7},
        {"text": "Valid claim", "confidence": 0.9},
    ]
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
        "phase1_noise_filter_domain_whitelist": ["DEM"],
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    texts = [c["text"] for c in filtered]
    assert "Figure 1: DEM particle setup" in texts  # preserved by whitelist
    assert "Figure 2: Random caption" not in texts  # filtered
    assert stats["whitelist_preserved"] == 1
    assert stats["caption_filtered"] == 1


def test_filter_with_domain_whitelist_counts_definition_preserved():
    """whitelist_preserved should include definition bypasses as well."""
    claims = [
        {"text": "DEM is a numerical method for particle simulation", "confidence": 0.8},
        {"text": "Entropy is a measure of disorder in systems", "confidence": 0.7},
    ]
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
        "phase1_noise_filter_context_aware": False,
        "phase1_noise_filter_domain_whitelist": ["DEM"],
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    texts = [c["text"] for c in filtered]
    assert "DEM is a numerical method for particle simulation" in texts
    assert "Entropy is a measure of disorder in systems" not in texts
    assert stats["whitelist_preserved"] == 1
    assert stats["definition_filtered"] == 1


# ── P2-13: Context-aware definition filtering ──


def test_definition_preserved_when_next_is_comparative():
    """Definition followed by comparative claim should be preserved."""
    assert is_pure_definition_text(
        "Machine learning is a method of data analysis",
        next_text="This approach outperforms previous methods",
    ) is False


def test_definition_filtered_when_next_is_not_comparative():
    """Definition followed by another definition should still be filtered."""
    assert is_pure_definition_text(
        "Machine learning is a method of data analysis",
        next_text="Deep learning is a subset of machine learning",
    ) is True


def test_definition_filtered_when_no_next_text():
    """Definition at end of list (no next_text) should be filtered."""
    assert is_pure_definition_text(
        "Machine learning is a method of data analysis",
        next_text=None,
    ) is True


def test_filter_context_aware_preserves_definition_before_causal():
    """filter_claim_candidates preserves definition before causal claim."""
    claims = [
        {"text": "Entropy is a measure of disorder in the system", "confidence": 0.8},
        {"text": "Higher entropy leads to increased randomness", "confidence": 0.9},
        {"text": "Valid claim about performance", "confidence": 0.85},
    ]
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
        "phase1_noise_filter_context_aware": True,
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    texts = [c["text"] for c in filtered]
    # Definition preserved because next claim is causal ("leads to")
    assert "Entropy is a measure of disorder in the system" in texts
    assert stats["context_preserved"] >= 1


def test_filter_context_aware_disabled():
    """When context_aware is off, definitions are filtered regardless of next claim."""
    claims = [
        {"text": "Entropy is a measure of disorder in the system", "confidence": 0.8},
        {"text": "Higher entropy leads to increased randomness", "confidence": 0.9},
    ]
    rules = {
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
        "phase1_noise_filter_context_aware": False,
    }
    filtered, stats = filter_claim_candidates(claims, rules)
    texts = [c["text"] for c in filtered]
    assert "Entropy is a measure of disorder in the system" not in texts
    assert stats["definition_filtered"] == 1
    assert stats["context_preserved"] == 0



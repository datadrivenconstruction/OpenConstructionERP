"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the international cost_match matcher.

Covers accent folding, multilingual synonym matching, metric/imperial unit
normalisation, the explainable confidence score, and the edge-case guards
(empty query, no candidates, ties, unit mismatch, regex-metacharacter input).
Everything here is pure-function and needs no database or network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.cost_match.matcher import (
    HIGH_CONFIDENCE,
    REVIEW_CONFIDENCE,
    Candidate,
    best_match,
    canonical_tokens,
    explain,
    fold_accents,
    no_match_hint,
    normalize_text,
    normalize_unit,
    score_match,
    suggestion_rate,
    units_compatible,
)

# ── Accent folding + normalisation ──────────────────────────────────────────


class TestNormalisation:
    def test_folds_common_diacritics(self) -> None:
        assert fold_accents("béton") == "beton"
        assert fold_accents("Dämmung") == "Dammung"
        assert fold_accents("hormigón") == "hormigon"

    def test_folds_german_sharp_s_and_nordic(self) -> None:
        assert fold_accents("straße") == "strasse"
        assert fold_accents("Ø") == "o"

    def test_leaves_cyrillic_intact(self) -> None:
        assert fold_accents("бетон") == "бетон"

    def test_normalize_text_lowercases_and_collapses(self) -> None:
        assert normalize_text("  Béton   Armé ") == "beton arme"

    def test_normalize_text_handles_none_and_empty(self) -> None:
        assert normalize_text(None) == ""
        assert normalize_text("   ") == ""

    def test_regex_metacharacters_are_safe(self) -> None:
        # Must not raise and must strip metachars to separators.
        assert normalize_text("C30/37 [*+](}") == "c30 37"


# ── Multilingual synonym matching ───────────────────────────────────────────


class TestSynonyms:
    def test_concrete_across_languages_shares_a_concept(self) -> None:
        for word in ("concrete", "Beton", "hormigón", "calcestruzzo", "бетон"):
            assert "concrete" in canonical_tokens(word), word

    def test_reinforced_concrete_wall_matches_across_languages(self) -> None:
        english = "reinforced concrete wall"
        for other in (
            "Stahlbetonwand",  # de (compound: steel-concrete-wall)
            "mur en béton armé",  # fr
            "muro de hormigón armado",  # es
            "железобетонная стена",  # ru is a single compound word, weaker
        ):
            score = score_match(other, english)
            assert score.confidence > 0.0, other

    def test_de_es_fr_reinforced_concrete_are_confident(self) -> None:
        english = "reinforced concrete"
        for other in ("Beton bewehrung", "hormigón armadura", "béton armature"):
            score = score_match(other, english)
            assert score.confidence >= HIGH_CONFIDENCE, (other, score.confidence)

    def test_stopwords_do_not_dilute(self) -> None:
        # "of the" style glue words are dropped, so coverage stays high.
        score = score_match("insulation of the wall", "wall insulation")
        assert score.confidence >= HIGH_CONFIDENCE


# ── Unit normalisation (metric + imperial) ──────────────────────────────────


class TestUnits:
    @pytest.mark.parametrize(
        ("unit", "dimension"),
        [
            ("m2", "area"),
            ("m²", "area"),
            ("SQM", "area"),
            ("sq ft", "area"),
            ("m3", "volume"),
            ("cu yd", "volume"),
            ("m", "length"),
            ("ft", "length"),
            ("kg", "mass"),
            ("lb", "mass"),
            ("pcs", "count"),
            ("Stück", "count"),
        ],
    )
    def test_unit_dimension_metric_and_imperial(self, unit: str, dimension: str) -> None:
        assert normalize_unit(unit) == dimension

    def test_unknown_unit_is_none(self) -> None:
        assert normalize_unit("wibble") is None
        assert normalize_unit(None) is None

    def test_metric_imperial_same_dimension_is_compatible(self) -> None:
        assert units_compatible("m2", "sq ft") is True

    def test_area_vs_volume_incompatible(self) -> None:
        assert units_compatible("m2", "m3") is False

    def test_unknown_unit_is_no_signal(self) -> None:
        assert units_compatible("m2", "wibble") is None


# ── Confidence scoring + explainability ─────────────────────────────────────


class TestScoring:
    def test_exact_normalized_match_is_perfect(self) -> None:
        score = score_match("Concrete C30/37", "concrete c30 37")
        assert score.confidence == pytest.approx(1.0)
        assert score.factors["exact"] == 1.0
        assert "exact_match" in score.reasons

    def test_score_is_bounded(self) -> None:
        score = score_match("concrete wall", "reinforced concrete masonry wall plaster")
        assert 0.0 <= score.confidence <= 1.0

    def test_factors_are_exposed_for_audit(self) -> None:
        score = score_match("concrete wall", "concrete slab")
        assert set(score.factors) == {"query_coverage", "term_overlap", "unit_factor", "exact"}
        assert 0.0 < score.factors["query_coverage"] < 1.0

    def test_unit_mismatch_lowers_confidence(self) -> None:
        with_ok = score_match("concrete", "concrete", query_unit="m3", candidate_unit="cbm")
        with_bad = score_match("concrete", "concrete", query_unit="m3", candidate_unit="m2")
        assert with_bad.confidence < with_ok.confidence
        assert "unit_mismatch" in with_bad.reasons
        assert "unit_match" in with_ok.reasons

    def test_no_token_overlap_scores_zero(self) -> None:
        score = score_match("window", "concrete")
        assert score.confidence == 0.0

    def test_explain_is_localized(self) -> None:
        score = score_match("concrete", "concrete", query_unit="m3", candidate_unit="m2")
        en = explain(score, locale="en")
        de = explain(score, locale="de")
        assert en and de
        assert en != de
        # No raw reason keys leak through.
        assert "match.reason" not in en


# ── best_match orchestration + edge cases ───────────────────────────────────


def _candidates() -> list[Candidate]:
    return [
        Candidate(ref="c1", text="reinforced concrete wall", unit="m3"),
        Candidate(ref="c2", text="brick masonry wall", unit="m2"),
        Candidate(ref="c3", text="interior wall painting", unit="m2"),
    ]


class TestBestMatch:
    def test_picks_best_candidate(self) -> None:
        # German closed compound: steel + concrete + wall glued into one word.
        result = best_match("Stahlbetonwand", _candidates(), query_unit="m3")
        assert result.candidate is not None
        assert result.candidate.ref == "c1"
        assert result.score is not None
        assert result.score.confidence >= REVIEW_CONFIDENCE

    def test_english_query_is_confident(self) -> None:
        result = best_match("reinforced concrete wall", _candidates(), query_unit="m3")
        assert result.candidate is not None
        assert result.candidate.ref == "c1"
        assert result.is_confident is True
        assert result.hint is None

    def test_empty_query_returns_hint_not_crash(self) -> None:
        result = best_match("   ", _candidates())
        assert result.candidate is None
        assert result.score is None
        assert result.hint == no_match_hint("empty_query")

    def test_no_candidates_returns_hint(self) -> None:
        result = best_match("concrete wall", [])
        assert result.candidate is None
        assert result.hint == no_match_hint("no_candidates")

    def test_low_confidence_returns_hint_but_still_offers_context(self) -> None:
        result = best_match("photovoltaic inverter firmware", _candidates())
        assert result.is_confident is False
        assert result.hint == no_match_hint("no_good_match")
        assert result.score is not None
        assert result.score.confidence < REVIEW_CONFIDENCE

    def test_ties_are_flagged_and_resolved_by_order(self) -> None:
        cands = [
            Candidate(ref="a", text="concrete wall"),
            Candidate(ref="b", text="concrete wall"),
        ]
        result = best_match("concrete wall", cands)
        assert result.tie is True
        assert result.candidate is not None
        assert result.candidate.ref == "a"  # input order breaks the tie

    def test_regex_metacharacter_query_is_handled(self) -> None:
        cands = [Candidate(ref="c1", text="concrete C30/37", unit="m3")]
        result = best_match("concrete C30/37 [*+]", cands, query_unit="m3")
        assert result.candidate is not None
        assert result.candidate.ref == "c1"

    def test_alternatives_are_ranked(self) -> None:
        result = best_match("wall", _candidates(), top_n=3)
        confidences = [score.confidence for _, score in result.alternatives]
        assert confidences == sorted(confidences, reverse=True)


# ── Decimal-exact money pass-through ────────────────────────────────────────


class TestMoneyPassThrough:
    def test_decimal_rate_is_preserved_exactly(self) -> None:
        cand = Candidate(ref="c1", text="concrete", payload={"unit_rate": Decimal("123.45")})
        assert suggestion_rate(cand) == Decimal("123.45")

    def test_string_rate_parsed_without_float_error(self) -> None:
        cand = Candidate(ref="c1", text="concrete", payload={"unit_rate": "0.10"})
        rate = suggestion_rate(cand)
        assert rate == Decimal("0.10")
        # Decimal preserves the exact value that a float would corrupt.
        assert rate + Decimal("0.20") == Decimal("0.30")

    def test_missing_or_unparseable_rate_is_none(self) -> None:
        assert suggestion_rate(Candidate(ref="c1", text="concrete")) is None
        assert suggestion_rate(Candidate(ref="c1", text="x", payload={"unit_rate": "n/a"})) is None

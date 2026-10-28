"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for BIM requirements international helpers (database-free)."""

from datetime import date, datetime
from pathlib import Path

import pytest

from app.modules.bim_requirements import intl

# -- Status localization ----------------------------------------------------


class TestLocalizeStatus:
    """Localized status words with English fallback."""

    def test_english_words(self) -> None:
        assert intl.localize_status(intl.STATUS_MET, "en") == "Met"
        assert intl.localize_status(intl.STATUS_UNMET, "en") == "Unmet"
        assert intl.localize_status(intl.STATUS_NOT_APPLICABLE, "en") == "Not applicable"

    def test_german_and_russian_present(self) -> None:
        assert intl.localize_status(intl.STATUS_MET, "de")
        assert intl.localize_status(intl.STATUS_MET, "ru")

    def test_locale_tag_is_normalized(self) -> None:
        assert intl.localize_status(intl.STATUS_MET, "de-DE") == intl.localize_status(intl.STATUS_MET, "de")
        assert intl.localize_status(intl.STATUS_MET, "en_US") == "Met"

    def test_unsupported_locale_falls_back_to_english(self) -> None:
        assert intl.localize_status(intl.STATUS_MET, "zz") == "Met"
        assert intl.localize_status(intl.STATUS_MET, None) == "Met"

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown requirement status"):
            intl.localize_status("bogus", "en")


class TestExplain:
    """One-line explainers for reporting terms."""

    @pytest.mark.parametrize("term", ["lod", "loi", "met", "unmet", "coverage"])
    def test_terms_have_text_in_all_locales(self, term: str) -> None:
        for loc in ("en", "de", "ru"):
            text = intl.explain(term, loc)
            assert isinstance(text, str)
            assert len(text) > 10

    def test_case_insensitive(self) -> None:
        assert intl.explain("LOD", "en") == intl.explain("lod", "en")

    def test_unsupported_locale_falls_back_to_english(self) -> None:
        assert intl.explain("coverage", "zz") == intl.explain("coverage", "en")

    def test_unknown_term_raises(self) -> None:
        with pytest.raises(ValueError, match="No explainer for term"):
            intl.explain("nope", "en")


# -- LOD parsing / validation -----------------------------------------------


class TestParseLodLevel:
    """LOD level parser and validator."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (300, 300),
            ("300", 300),
            ("LOD300", 300),
            ("LOD 300", 300),
            ("lod_350", 350),
            ("LOD-400", 400),
            (" 500 ", 500),
        ],
    )
    def test_valid_forms(self, raw: object, expected: int) -> None:
        assert intl.parse_lod_level(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "LOD", "abc"])
    def test_empty_or_no_digits_raises(self, raw: str) -> None:
        with pytest.raises(ValueError):
            intl.parse_lod_level(raw)

    @pytest.mark.parametrize("level", [0, 250, 600, 99])
    def test_out_of_set_raises(self, level: int) -> None:
        with pytest.raises(ValueError, match="not one of"):
            intl.parse_lod_level(level)

    def test_boolean_rejected(self) -> None:
        with pytest.raises(ValueError, match="boolean"):
            intl.parse_lod_level(True)

    def test_is_valid_lod_level_never_raises(self) -> None:
        assert intl.is_valid_lod_level("LOD300") is True
        assert intl.is_valid_lod_level("nonsense") is False
        assert intl.is_valid_lod_level(250) is False
        assert intl.is_valid_lod_level(True) is False


# -- Coverage math ----------------------------------------------------------


class TestCoverageRate:
    """Zero-guarded, bounded coverage rate."""

    def test_basic_ratio(self) -> None:
        assert intl.coverage_rate(3, 4) == 0.75

    def test_zero_total_is_zero_not_error(self) -> None:
        assert intl.coverage_rate(0, 0) == 0.0

    def test_all_met(self) -> None:
        assert intl.coverage_rate(5, 5) == 1.0

    def test_result_always_in_unit_interval(self) -> None:
        for met, total in [(0, 7), (1, 3), (7, 7), (0, 0)]:
            rate = intl.coverage_rate(met, total)
            assert 0.0 <= rate <= 1.0

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            intl.coverage_rate(-1, 5)
        with pytest.raises(ValueError, match="must not be negative"):
            intl.coverage_rate(1, -5)

    def test_met_over_total_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            intl.coverage_rate(6, 5)


class TestCoveragePercent:
    """Percentage variant stays within [0, 100]."""

    def test_percent(self) -> None:
        assert intl.coverage_percent(1, 4) == 25.0

    def test_zero_total(self) -> None:
        assert intl.coverage_percent(0, 0) == 0.0

    def test_bounds(self) -> None:
        assert intl.coverage_percent(5, 5) == 100.0
        assert 0.0 <= intl.coverage_percent(2, 3) <= 100.0

    def test_rounding(self) -> None:
        assert intl.coverage_percent(1, 3, ndigits=2) == 33.33


class TestCountsByStatus:
    """Status tally always covers every valid status."""

    def test_all_keys_present(self) -> None:
        tally = intl.counts_by_status([])
        assert set(tally) == set(intl.VALID_STATUSES)
        assert all(v == 0 for v in tally.values())

    def test_counts(self) -> None:
        statuses = [
            intl.STATUS_MET,
            intl.STATUS_MET,
            intl.STATUS_UNMET,
            intl.STATUS_NOT_APPLICABLE,
        ]
        tally = intl.counts_by_status(statuses)
        assert tally[intl.STATUS_MET] == 2
        assert tally[intl.STATUS_UNMET] == 1
        assert tally[intl.STATUS_NOT_APPLICABLE] == 1

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown requirement status"):
            intl.counts_by_status([intl.STATUS_MET, "weird"])


class TestMetVsUnmetBreakdown:
    """Met vs unmet breakdown with explainable components."""

    def test_empty_is_well_defined(self) -> None:
        b = intl.met_vs_unmet_breakdown([])
        assert b["total"] == 0
        assert b["applicable"] == 0
        assert b["coverage_rate"] == 0.0
        assert b["coverage_percent"] == 0.0

    def test_excludes_not_applicable_from_denominator(self) -> None:
        statuses = [
            intl.STATUS_MET,
            intl.STATUS_MET,
            intl.STATUS_UNMET,
            intl.STATUS_NOT_APPLICABLE,
        ]
        b = intl.met_vs_unmet_breakdown(statuses)
        assert b["met"] == 2
        assert b["unmet"] == 1
        assert b["not_applicable"] == 1
        assert b["total"] == 4
        assert b["applicable"] == 3
        # 2 / (2 + 1)
        assert b["coverage_rate"] == pytest.approx(2 / 3)

    def test_components_documented(self) -> None:
        b = intl.met_vs_unmet_breakdown([intl.STATUS_MET])
        comp = b["components"]
        assert comp["numerator"] == 1
        assert comp["denominator"] == 1
        assert comp["formula"] == "met / (met + unmet)"

    def test_labels_localized(self) -> None:
        b = intl.met_vs_unmet_breakdown([intl.STATUS_MET], locale="de")
        assert b["labels"][intl.STATUS_MET] == intl.localize_status(intl.STATUS_MET, "de")

    def test_all_not_applicable_gives_zero_coverage(self) -> None:
        b = intl.met_vs_unmet_breakdown([intl.STATUS_NOT_APPLICABLE] * 3)
        assert b["applicable"] == 0
        assert b["coverage_rate"] == 0.0


class TestSummarizeCheckResults:
    """Breakdown built from raw result rows."""

    def test_reads_status_field(self) -> None:
        rows = [
            {"status": intl.STATUS_MET, "property_name": "FireRating"},
            {"status": intl.STATUS_UNMET, "property_name": "LoadBearing"},
        ]
        b = intl.summarize_check_results(rows)
        assert b["met"] == 1
        assert b["unmet"] == 1
        assert b["coverage_rate"] == 0.5

    def test_missing_status_raises(self) -> None:
        with pytest.raises(ValueError, match="missing a 'status'"):
            intl.summarize_check_results([{"property_name": "x"}])


# -- ISO 8601 dates ---------------------------------------------------------


class TestFormatIso8601:
    """Locale-independent ISO 8601 rendering."""

    def test_date(self) -> None:
        assert intl.format_iso8601(date(2026, 7, 5)) == "2026-07-05"

    def test_datetime_seconds(self) -> None:
        assert intl.format_iso8601(datetime(2026, 7, 5, 14, 30, 0)) == "2026-07-05T14:30:00"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="date or datetime"):
            intl.format_iso8601("2026-07-05")  # type: ignore[arg-type]


# -- Text hygiene: no em-dashes, smart quotes or zero-width characters ------


class TestSourceTextHygiene:
    """The helper source must use plain ASCII punctuation only.

    The banned set is built from chr() code points so this file never itself
    contains a banned character.
    """

    def _banned_code_points(self) -> set[str]:
        points = [
            0x2013,  # en dash
            0x2014,  # em dash
            0x2015,  # horizontal bar
            0x2018,  # left single quote
            0x2019,  # right single quote
            0x201C,  # left double quote
            0x201D,  # right double quote
            0x2026,  # horizontal ellipsis
            0x200B,  # zero width space
            0x200C,  # zero width non-joiner
            0x200D,  # zero width joiner
            0x2060,  # word joiner
            0xFEFF,  # zero width no-break space
        ]
        return {chr(cp) for cp in points}

    def test_intl_module_is_clean(self) -> None:
        source = Path(intl.__file__).read_text(encoding="utf-8")
        banned = self._banned_code_points()
        found = sorted({hex(ord(ch)) for ch in source if ch in banned})
        assert not found, f"banned characters in intl.py: {found}"

    def test_localized_strings_are_clean(self) -> None:
        banned = self._banned_code_points()
        samples: list[str] = []
        for status in intl.VALID_STATUSES:
            for loc in ("en", "de", "ru"):
                samples.append(intl.localize_status(status, loc))
        for term in ("lod", "loi", "met", "unmet", "coverage"):
            for loc in ("en", "de", "ru"):
                samples.append(intl.explain(term, loc))
        for text in samples:
            assert not any(ch in banned for ch in text), f"banned char in: {text!r}"

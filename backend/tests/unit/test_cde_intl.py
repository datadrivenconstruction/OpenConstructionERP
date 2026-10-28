"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international, explainable CDE helpers.

All checks are pure and database free. They pin the plain-language, locale-aware
behaviour added in :mod:`app.modules.cde.intl`: state and status localization
with an English fallback, ISO 8601 date formatting, division-by-zero guards on
the share-published rate, empty-set safety on counts and the latest-revision
selector, and a strict no-typographic-punctuation rule on every shipped string.
"""

from datetime import UTC, date, datetime

import pytest

from app.modules.cde import intl

# ── Banned characters, built from code points (never a literal string) ────
#
# em dash, en dash, curly single/double quotes, and the zero-width family.
# Assembled from chr() so the source file itself stays free of them.
_BANNED_CODE_POINTS = (
    0x2014,  # em dash
    0x2013,  # en dash
    0x2018,  # left single quotation mark
    0x2019,  # right single quotation mark
    0x201C,  # left double quotation mark
    0x201D,  # right double quotation mark
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space
)
_BANNED_CHARS = frozenset(chr(cp) for cp in _BANNED_CODE_POINTS)


def _all_shipped_strings() -> list[str]:
    """Collect every user-facing string the module can emit."""
    out: list[str] = []
    for lang in (*intl.SUPPORTED_LANGUAGES, "xx"):
        out.append(intl.explain_revision(lang))
        for state in intl.CDE_STATE_ORDER:
            out.append(intl.localize_state(state, lang))
            out.append(intl.explain_state(state, lang))
        for status in ("draft", "preliminary", "final"):
            out.append(intl.localize_status(status, lang))
    return out


# ── Language normalisation ────────────────────────────────────────────────


class TestNormalizeLanguage:
    def test_supported(self) -> None:
        assert intl.normalize_language("de") == "de"
        assert intl.normalize_language("ru") == "ru"
        assert intl.normalize_language("en") == "en"

    def test_region_suffix_and_case(self) -> None:
        assert intl.normalize_language("de-DE") == "de"
        assert intl.normalize_language("RU_ru") == "ru"
        assert intl.normalize_language("EN-GB") == "en"

    def test_unsupported_and_empty_fall_back_to_english(self) -> None:
        assert intl.normalize_language("fr") == "en"
        assert intl.normalize_language("") == "en"
        assert intl.normalize_language(None) == "en"


# ── State normalisation ───────────────────────────────────────────────────


class TestCanonicalState:
    def test_case_and_whitespace(self) -> None:
        assert intl.canonical_state("  WIP ") == "wip"
        assert intl.canonical_state("Shared") == "shared"

    def test_unknown_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Unknown CDE state"):
            intl.canonical_state("bogus")

    def test_empty_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            intl.canonical_state("   ")

    def test_is_known_state(self) -> None:
        assert intl.is_known_state("published") is True
        assert intl.is_known_state("PUBLISHED") is True
        assert intl.is_known_state("nope") is False

    def test_state_order_matches_enum(self) -> None:
        assert intl.CDE_STATE_ORDER == ("wip", "shared", "published", "archived")


# ── Localized lookups ─────────────────────────────────────────────────────


class TestLocalization:
    def test_state_labels_per_language(self) -> None:
        assert intl.localize_state("wip", "en") == "Work in progress"
        assert intl.localize_state("wip", "de") == "In Bearbeitung"
        # Russian returns a non-empty Cyrillic label distinct from English.
        ru = intl.localize_state("wip", "ru")
        assert ru and ru != intl.localize_state("wip", "en")

    def test_unsupported_language_falls_back_to_english(self) -> None:
        assert intl.localize_state("shared", "zz") == intl.localize_state("shared", "en")
        assert intl.explain_state("shared", "zz") == intl.explain_state("shared", "en")

    def test_localize_state_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown CDE state"):
            intl.localize_state("bogus", "en")

    def test_explain_state_is_one_line(self) -> None:
        for state in intl.CDE_STATE_ORDER:
            for lang in intl.SUPPORTED_LANGUAGES:
                text = intl.explain_state(state, lang)
                assert text
                assert "\n" not in text

    def test_explain_revision_all_languages(self) -> None:
        for lang in intl.SUPPORTED_LANGUAGES:
            text = intl.explain_revision(lang)
            assert text and "\n" not in text
        assert intl.explain_revision("zz") == intl.explain_revision("en")

    def test_localize_status(self) -> None:
        assert intl.localize_status("draft", "en") == "Draft"
        assert intl.localize_status("draft", "de") == "Entwurf"
        assert intl.localize_status("  DRAFT ", "en") == "Draft"

    def test_localize_status_unknown_returns_input(self) -> None:
        # An unrecognised status must not raise; it echoes the trimmed input.
        assert intl.localize_status("weird", "en") == "weird"
        assert intl.localize_status("", "en") == ""

    def test_describe_states_shape_and_order(self) -> None:
        rows = intl.describe_states("de")
        assert [r["state"] for r in rows] == list(intl.CDE_STATE_ORDER)
        for row in rows:
            assert row["label"] and row["explanation"]


# ── ISO 8601 dates ────────────────────────────────────────────────────────


class TestIsoDates:
    def test_format_date_from_datetime(self) -> None:
        dt = datetime(2026, 7, 5, 13, 30, tzinfo=UTC)
        assert intl.format_date_iso(dt) == "2026-07-05"

    def test_format_date_from_date(self) -> None:
        assert intl.format_date_iso(date(2026, 1, 9)) == "2026-01-09"

    def test_format_date_none(self) -> None:
        assert intl.format_date_iso(None) is None

    def test_format_datetime_iso(self) -> None:
        dt = datetime(2026, 7, 5, 13, 30, 15, tzinfo=UTC)
        assert intl.format_datetime_iso(dt).startswith("2026-07-05T13:30:15")
        assert intl.format_datetime_iso(None) is None

    def test_format_date_bad_type_raises(self) -> None:
        with pytest.raises(ValueError, match="date or datetime"):
            intl.format_date_iso("2026-07-05")  # type: ignore[arg-type]


# ── Counts by state ───────────────────────────────────────────────────────


class TestCountByState:
    def test_empty_is_well_defined(self) -> None:
        counts = intl.count_by_state([])
        assert counts == {
            "wip": 0,
            "shared": 0,
            "published": 0,
            "archived": 0,
            "unknown": 0,
        }

    def test_counts_and_case_insensitive(self) -> None:
        counts = intl.count_by_state(["wip", "WIP", "Shared", "published"])
        assert counts["wip"] == 2
        assert counts["shared"] == 1
        assert counts["published"] == 1
        assert counts["archived"] == 0

    def test_unknown_bucketed_not_dropped(self) -> None:
        counts = intl.count_by_state(["wip", "mystery", ""])
        assert counts["wip"] == 1
        assert counts["unknown"] == 2


# ── Share / published rate ────────────────────────────────────────────────


class TestSharePublishedRate:
    def test_zero_containers_guarded(self) -> None:
        result = intl.share_published_rate(intl.count_by_state([]))
        assert result["rate"] == 0.0
        assert result["percent"] == 0.0
        assert result["denominator"] == 0
        assert result["defined"] is False

    def test_rate_and_components(self) -> None:
        counts = intl.count_by_state(
            ["wip", "wip", "shared", "published", "archived"],
        )
        result = intl.share_published_rate(counts)
        assert result["numerator"] == 2  # shared + published
        assert result["denominator"] == 5
        assert result["rate"] == pytest.approx(0.4)
        assert result["percent"] == pytest.approx(40.0)
        assert result["defined"] is True
        assert result["components"] == {
            "shared": 1,
            "published": 1,
            "wip": 2,
            "archived": 1,
        }

    def test_never_nan_or_inf(self) -> None:
        import math

        for states in ([], ["wip"], ["shared", "published"], ["archived"] * 3):
            result = intl.share_published_rate(intl.count_by_state(states))
            assert math.isfinite(result["rate"])
            assert math.isfinite(result["percent"])
            assert 0.0 <= result["rate"] <= 1.0

    def test_missing_keys_default_to_zero(self) -> None:
        # A partial mapping must not raise; absent states count as zero.
        result = intl.share_published_rate({"shared": 3})
        assert result["numerator"] == 3
        assert result["denominator"] == 3
        assert result["rate"] == pytest.approx(1.0)


# ── Latest revision selector ──────────────────────────────────────────────


class _Rev:
    def __init__(self, revision_number: int, created_at: datetime | None = None) -> None:
        self.revision_number = revision_number
        self.created_at = created_at


class TestLatestRevision:
    def test_empty_returns_none(self) -> None:
        assert intl.latest_revision([]) is None

    def test_picks_highest_number_dicts(self) -> None:
        revs = [
            {"revision_number": 1, "revision_code": "P01"},
            {"revision_number": 3, "revision_code": "P03"},
            {"revision_number": 2, "revision_code": "P02"},
        ]
        assert intl.latest_revision(revs)["revision_code"] == "P03"

    def test_picks_highest_number_objects(self) -> None:
        revs = [_Rev(1), _Rev(4), _Rev(2)]
        assert intl.latest_revision(revs).revision_number == 4

    def test_tie_break_by_created_at(self) -> None:
        earlier = datetime(2026, 1, 1, tzinfo=UTC)
        later = datetime(2026, 6, 1, tzinfo=UTC)
        revs = [_Rev(2, earlier), _Rev(2, later)]
        assert intl.latest_revision(revs).created_at == later

    def test_malformed_number_never_wins_or_raises(self) -> None:
        revs = [
            {"revision_number": None},
            {"revision_number": "x"},
            {"revision_number": 0, "revision_code": "P00"},
        ]
        assert intl.latest_revision(revs)["revision_code"] == "P00"


# ── Transition validity ───────────────────────────────────────────────────


class TestTransitions:
    def test_forward_allowed(self) -> None:
        assert intl.is_transition_allowed("wip", "shared") is True
        assert intl.is_transition_allowed("shared", "published") is True
        assert intl.is_transition_allowed("published", "archived") is True

    def test_skip_and_backward_blocked(self) -> None:
        assert intl.is_transition_allowed("wip", "published") is False
        assert intl.is_transition_allowed("shared", "wip") is False
        assert intl.is_transition_allowed("archived", "published") is False

    def test_allowed_transitions(self) -> None:
        assert intl.allowed_transitions("wip") == ["shared"]
        assert intl.allowed_transitions("archived") == []
        assert intl.allowed_transitions("bogus") == []

    def test_transition_check_ok(self) -> None:
        result = intl.transition_check("wip", "shared", "de")
        assert result["allowed"] is True
        assert result["reason"] == "ok"
        assert result["from_label"] == intl.localize_state("wip", "de")
        assert result["to_label"] == intl.localize_state("shared", "de")
        assert result["next_states"] == ["shared"]

    def test_transition_check_not_allowed_has_reason(self) -> None:
        result = intl.transition_check("wip", "published")
        assert result["allowed"] is False
        assert "not allowed" in result["reason"]

    def test_transition_check_unknown_state_no_raise(self) -> None:
        result = intl.transition_check("bogus", "shared")
        assert result["allowed"] is False
        assert "Invalid state" in result["reason"]
        assert result["from_label"] is None
        assert result["to_label"] == intl.localize_state("shared", "en")


# ── Aggregate summary ─────────────────────────────────────────────────────


class TestStateSummary:
    def test_empty_summary_well_defined(self) -> None:
        summary = intl.state_summary([], "en")
        assert summary["total"] == 0
        assert summary["unknown"] == 0
        assert summary["share_published"]["defined"] is False
        assert [row["state"] for row in summary["by_state"]] == list(intl.CDE_STATE_ORDER)

    def test_summary_counts_and_localization(self) -> None:
        summary = intl.state_summary(["wip", "shared", "shared", "published"], "de")
        by_state = {row["state"]: row for row in summary["by_state"]}
        assert summary["total"] == 4
        assert by_state["shared"]["count"] == 2
        assert by_state["shared"]["label"] == intl.localize_state("shared", "de")
        assert summary["share_published"]["numerator"] == 3
        assert summary["language"] == "de"


# ── No typographic or zero-width characters anywhere ──────────────────────


class TestNoBannedCharacters:
    def test_shipped_strings_are_plain(self) -> None:
        for text in _all_shipped_strings():
            offenders = _BANNED_CHARS.intersection(text)
            assert not offenders, f"banned char in {text!r}: {[hex(ord(c)) for c in offenders]}"

    def test_summary_strings_are_plain(self) -> None:
        summary = intl.state_summary(["wip", "shared"], "ru")
        blob = repr(summary)
        assert not _BANNED_CHARS.intersection(blob)

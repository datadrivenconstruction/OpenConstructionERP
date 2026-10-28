# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``app.modules.notifications.intl``.

Pure - no database, no event bus. Covers the international, edge-case-safe
notification analytics helpers: delivery / read rates with zero guards,
counts by channel and status, unread counts, en/de/ru localization with
English fallback, ISO 8601 timestamps, and a text-hygiene guard that no
user-facing string contains a long dash, smart quote or zero-width character.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.notifications import intl

# ── Rates: happy path ─────────────────────────────────────────────────────


def test_delivery_rate_basic():
    result = intl.delivery_rate(sent=10, delivered=8)
    assert result.numerator == 8
    assert result.denominator == 10
    assert result.rate == 0.8
    assert result.percent == 80.0
    assert result.defined is True
    assert "8 of 10" in result.explainer


def test_read_rate_basic():
    result = intl.read_rate(delivered=8, read=2)
    assert result.numerator == 2
    assert result.denominator == 8
    assert result.rate == 0.25
    assert result.percent == 25.0
    assert result.defined is True
    assert "2 of 8" in result.explainer


def test_rate_stays_in_unit_and_percent_bounds():
    for sent in range(0, 6):
        for delivered in range(0, sent + 1):
            result = intl.delivery_rate(sent, delivered)
            assert 0.0 <= result.rate <= 1.0
            assert 0.0 <= result.percent <= 100.0


def test_full_delivery_is_one():
    result = intl.delivery_rate(sent=7, delivered=7)
    assert result.rate == 1.0
    assert result.percent == 100.0


# ── Rates: zero guards (never NaN, never inf, never 500) ───────────────────


def test_delivery_rate_zero_sent_is_defined_zero():
    result = intl.delivery_rate(sent=0, delivered=0)
    assert result.defined is False
    assert result.rate == 0.0
    assert result.percent == 0.0
    assert result.numerator == 0
    assert result.denominator == 0
    assert "not defined" in result.explainer


def test_read_rate_zero_delivered_is_defined_zero():
    result = intl.read_rate(delivered=0, read=0)
    assert result.defined is False
    assert result.rate == 0.0
    assert result.percent == 0.0


def test_rates_are_finite():
    import math

    for result in (intl.delivery_rate(0, 0), intl.read_rate(0, 0), intl.delivery_rate(3, 1)):
        assert math.isfinite(result.rate)
        assert math.isfinite(result.percent)


# ── Rates: invalid input raises a clean ValueError ─────────────────────────


def test_delivery_rate_negative_raises():
    with pytest.raises(ValueError, match="negative"):
        intl.delivery_rate(sent=-1, delivered=0)
    with pytest.raises(ValueError, match="negative"):
        intl.delivery_rate(sent=5, delivered=-2)


def test_delivery_rate_delivered_over_sent_raises():
    with pytest.raises(ValueError, match="cannot exceed"):
        intl.delivery_rate(sent=3, delivered=4)


def test_read_rate_read_over_delivered_raises():
    with pytest.raises(ValueError, match="cannot exceed"):
        intl.read_rate(delivered=3, read=5)


def test_rate_rejects_bool_and_non_int():
    with pytest.raises(ValueError, match="integer count"):
        intl.delivery_rate(sent=True, delivered=1)
    with pytest.raises(ValueError, match="integer count"):
        intl.read_rate(delivered=2.0, read=1)


# ── Counts by channel ─────────────────────────────────────────────────────


def test_count_by_channel_strings():
    counts = intl.count_by_channel(["inapp", "inapp", "email", "webhook"])
    assert counts["inapp"] == 2
    assert counts["email"] == 1
    assert counts["webhook"] == 1
    assert counts["none"] == 0
    # Unknown bucket only appears when something did not map.
    assert "unknown" not in counts


def test_count_by_channel_all_known_present_on_empty():
    counts = intl.count_by_channel([])
    assert set(counts) == set(intl.CHANNELS)
    assert all(v == 0 for v in counts.values())


def test_count_by_channel_unknown_bucket():
    counts = intl.count_by_channel(["carrier-pigeon", "email", None])
    assert counts["email"] == 1
    assert counts["unknown"] == 2


def test_count_by_channel_objects_and_key():
    class Pref:
        def __init__(self, channel):
            self.channel = channel

    counts = intl.count_by_channel([Pref("EMAIL"), Pref(" inapp ")])
    assert counts["email"] == 1
    assert counts["inapp"] == 1

    mappings = [{"channel": "webhook"}, {"channel": "none"}]
    assert intl.count_by_channel(mappings)["webhook"] == 1

    keyed = intl.count_by_channel([{"c": "email"}], key=lambda m: m["c"])
    assert keyed["email"] == 1


# ── Counts by status and unread ───────────────────────────────────────────


def test_count_by_status_from_flags():
    counts = intl.count_by_status([True, False, False, True, False])
    assert counts["read"] == 2
    assert counts["unread"] == 3


def test_count_by_status_empty_has_both_keys():
    counts = intl.count_by_status([])
    assert counts == {"read": 0, "unread": 0}


def test_unread_count_from_objects():
    class Note:
        def __init__(self, is_read):
            self.is_read = is_read

    assert intl.unread_count([Note(False), Note(True), Note(False)]) == 2
    assert intl.unread_count([{"is_read": True}, {"is_read": False}]) == 1


def test_unread_from_totals_guards():
    assert intl.unread_from_totals(total=10, read=4) == 6
    assert intl.unread_from_totals(total=0, read=0) == 0
    with pytest.raises(ValueError, match="cannot exceed"):
        intl.unread_from_totals(total=3, read=5)
    with pytest.raises(ValueError, match="negative"):
        intl.unread_from_totals(total=-1, read=0)


def test_explain_unread_sentence():
    text = intl.explain_unread(total=10, read=4)
    assert "6 of 10" in text
    assert "\n" not in text


# ── Localization: en / de / ru with English fallback ──────────────────────


def test_localize_channel_all_languages():
    assert intl.localize_channel("email", "en") == "Email"
    assert intl.localize_channel("email", "de") == "E-Mail"
    assert intl.localize_channel("email", "ru")  # non-empty Russian label
    assert intl.localize_channel("none", "de") == "Aus"


def test_localize_read_status():
    assert intl.localize_read_status("read", "en") == "Read"
    assert intl.localize_read_status("unread", "de") == "Ungelesen"


def test_localize_unknown_language_falls_back_to_english():
    assert intl.localize_channel("email", "xx") == "Email"
    assert intl.localize_channel("email", None) == "Email"


def test_localize_region_tag_is_stripped():
    assert intl.normalize_language("en-US") == "en"
    assert intl.normalize_language("de_AT") == "de"
    assert intl.normalize_language("ru-RU") == "ru"
    assert intl.normalize_language("") == "en"


def test_localize_unknown_term_returns_raw():
    assert intl.localize("channel", "carrier-pigeon", "de") == "carrier-pigeon"
    assert intl.localize("channel", None, "de") == ""


# ── ISO 8601 timestamps ───────────────────────────────────────────────────


def test_to_iso8601_naive_assumed_utc():
    text = intl.to_iso8601(datetime(2026, 7, 5, 12, 30, 0))
    assert text == "2026-07-05T12:30:00+00:00"


def test_to_iso8601_converts_aware_to_utc():
    plus_two = timezone(timedelta(hours=2))
    text = intl.to_iso8601(datetime(2026, 7, 5, 14, 30, 0, tzinfo=plus_two))
    assert text == "2026-07-05T12:30:00+00:00"


def test_to_iso8601_rejects_non_datetime():
    with pytest.raises(ValueError, match="datetime"):
        intl.to_iso8601("2026-07-05")


def test_now_iso8601_is_parseable_and_utc():
    parsed = datetime.fromisoformat(intl.now_iso8601())
    assert parsed.utcoffset() == timedelta(0)


# ── Composite summary ─────────────────────────────────────────────────────


def test_engagement_summary_shape_and_values():
    at = datetime(2026, 7, 5, 9, 0, 0, tzinfo=UTC)
    summary = intl.engagement_summary(sent=10, delivered=8, read=2, lang="de", at=at)
    assert summary["delivery"]["percent"] == 80.0
    assert summary["read"]["percent"] == 25.0
    assert summary["counts"] == {"read": 2, "unread": 6}
    assert summary["labels"]["unread"] == "Ungelesen"
    assert summary["generated_at"] == "2026-07-05T09:00:00+00:00"


def test_engagement_summary_zero_sent_defined_false():
    summary = intl.engagement_summary(sent=0, delivered=0, read=0)
    assert summary["delivery"]["defined"] is False
    assert summary["read"]["defined"] is False
    assert summary["counts"] == {"read": 0, "unread": 0}


# ── Text hygiene: no banned characters anywhere in user-facing output ──────


def _banned_characters() -> set[str]:
    """Build the banned set from code points, never as a literal string.

    Covers the long dash (em dash), the en dash, curly single and double
    quotes, and the common zero-width / word-joiner / BOM code points.
    """
    code_points = (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2018,  # left single quote
        0x2019,  # right single quote
        0x201C,  # left double quote
        0x201D,  # right double quote
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
        0xFEFF,  # zero-width no-break space / BOM
    )
    return {chr(cp) for cp in code_points}


def _collect_user_facing_strings() -> list[str]:
    strings: list[str] = []
    # Every localized label in every supported language.
    for kind, terms in intl._LOCALIZED.items():  # noqa: SLF001 - test reads the table on purpose
        for term in terms:
            for lang in intl.SUPPORTED_LANGUAGES:
                strings.append(intl.localize(kind, term, lang))
    # Explainers across defined and undefined branches.
    strings.append(intl.delivery_rate(10, 8).explainer)
    strings.append(intl.delivery_rate(0, 0).explainer)
    strings.append(intl.read_rate(8, 2).explainer)
    strings.append(intl.read_rate(0, 0).explainer)
    strings.append(intl.explain_unread(10, 4))
    return strings


def test_no_banned_characters_in_user_facing_strings():
    banned = _banned_characters()
    for text in _collect_user_facing_strings():
        offenders = banned.intersection(text)
        assert not offenders, f"banned character(s) {[hex(ord(c)) for c in offenders]} in {text!r}"

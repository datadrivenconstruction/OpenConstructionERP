# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the transmittals international reporting layer.

Covers localization with English fallback, the one-line explainers, counts by
status and by purpose, the acknowledgement rate (with its division-by-zero and
range guards), the parameterized overdue-acknowledgement flag and the
response-time-in-days helper. None of these touch a database, so they run by
explicit path without any fixtures.
"""

from __future__ import annotations

import math

import pytest

from app.modules.transmittals.intl import (
    EXPLAINERS,
    SUPPORTED_LOCALES,
    AcknowledgementRate,
    OverdueCheck,
    acknowledgement_overdue,
    acknowledgement_rate,
    counts_by_purpose,
    counts_by_status,
    explain,
    localize_purpose,
    localize_status,
    response_time_days,
)
from app.modules.transmittals.logic import PURPOSE_CODES, VALID_STATUSES

# ── Localization ───────────────────────────────────────────────────────────


def test_localize_status_known_languages() -> None:
    assert localize_status("issued", "en") == "issued"
    assert localize_status("issued", "de") == "ausgestellt"
    assert localize_status("issued", "ru") == "отправлено"


def test_localize_status_falls_back_to_english_for_unknown_locale() -> None:
    # An unsupported language falls back to the English word, never a raw code.
    assert localize_status("draft", "xx") == "draft"
    assert localize_status("draft", None) == "draft"


def test_localize_status_accepts_full_locale_tags() -> None:
    assert localize_status("responded", "de-DE") == "beantwortet"
    assert localize_status("responded", "ru_RU") == "отвечено"


def test_localize_status_unknown_code_returns_code() -> None:
    # A status we do not translate still comes back readable (the code itself),
    # never blank.
    assert localize_status("archived", "de") == "archived"


def test_localize_purpose_known_languages() -> None:
    assert localize_purpose("for_approval", "en") == "for approval"
    assert localize_purpose("for_approval", "de") == "zur Genehmigung"
    assert localize_purpose("for_approval", "ru") == "на утверждение"


def test_localize_purpose_falls_back_to_english() -> None:
    assert localize_purpose("for_tender", "pt") == "for tender"


def test_every_status_and_purpose_has_all_three_languages() -> None:
    # Parity: en / de / ru all localize every real code to a non-empty word.
    for locale in SUPPORTED_LOCALES:
        for code in VALID_STATUSES:
            assert localize_status(code, locale)
        for code in PURPOSE_CODES:
            assert localize_purpose(code, locale)


# ── Explainers ─────────────────────────────────────────────────────────────


def test_explain_returns_one_line_for_known_terms() -> None:
    for term in ("transmittal", "acknowledgement_rate", "overdue_acknowledgement", "response_time"):
        text = explain(term)
        assert text
        # One line, no newlines.
        assert "\n" not in text


def test_explain_unknown_term_is_empty_never_raises() -> None:
    assert explain("nonsense") == ""


# ── Counts by status / purpose ─────────────────────────────────────────────


def test_counts_by_status_seeds_all_known_and_buckets_unknown() -> None:
    counts = counts_by_status(["draft", "issued", "issued", "archived"])
    assert counts["draft"] == 1
    assert counts["issued"] == 2
    assert counts["responded"] == 0
    assert counts["other"] == 1
    # Every known status is present even when it never appears.
    for code in VALID_STATUSES:
        assert code in counts


def test_counts_by_status_empty_and_none_are_all_zero() -> None:
    for empty in ([], None):
        counts = counts_by_status(empty)
        assert counts["other"] == 0
        assert all(counts[code] == 0 for code in VALID_STATUSES)


def test_counts_by_purpose_seeds_all_known_and_buckets_unknown() -> None:
    counts = counts_by_purpose(["for_review", "for_review", "for_demolition"])
    assert counts["for_review"] == 2
    assert counts["for_approval"] == 0
    assert counts["other"] == 1
    for code in PURPOSE_CODES:
        assert code in counts


def test_counts_by_purpose_empty_is_all_zero() -> None:
    counts = counts_by_purpose([])
    assert counts["other"] == 0
    assert all(counts[code] == 0 for code in PURPOSE_CODES)


# ── Acknowledgement rate ───────────────────────────────────────────────────


def test_acknowledgement_rate_typical() -> None:
    rate = acknowledgement_rate(acknowledged=3, issued=4)
    assert isinstance(rate, AcknowledgementRate)
    assert rate.fraction == 0.75
    assert rate.percent == 75.0
    assert rate.defined is True
    assert 0.0 <= rate.fraction <= 1.0
    assert 0.0 <= rate.percent <= 100.0


def test_acknowledgement_rate_full_and_none() -> None:
    full = acknowledgement_rate(5, 5)
    assert full.fraction == 1.0
    assert full.percent == 100.0
    zero = acknowledgement_rate(0, 5)
    assert zero.fraction == 0.0
    assert zero.percent == 0.0


def test_acknowledgement_rate_zero_issued_is_defined_zero_not_division_error() -> None:
    rate = acknowledgement_rate(0, 0)
    assert rate.fraction == 0.0
    assert rate.percent == 0.0
    assert rate.defined is False
    # Never a NaN or an infinity.
    assert math.isfinite(rate.fraction)
    assert math.isfinite(rate.percent)


def test_acknowledgement_rate_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        acknowledgement_rate(-1, 5)
    with pytest.raises(ValueError, match="cannot be negative"):
        acknowledgement_rate(1, -5)


def test_acknowledgement_rate_rejects_more_acked_than_issued() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        acknowledgement_rate(6, 5)


# ── Overdue acknowledgement ────────────────────────────────────────────────


def test_overdue_flag_true_past_due_under_sla() -> None:
    # Issued 2026-03-01, 7-day SLA -> due 2026-03-08. Checked 2026-03-10.
    check = acknowledgement_overdue("2026-03-01", "2026-03-10", sla_days=7)
    assert isinstance(check, OverdueCheck)
    assert check.due_date == "2026-03-08"
    assert check.is_overdue is True
    assert check.days_overdue == 2


def test_overdue_flag_false_within_sla() -> None:
    check = acknowledgement_overdue("2026-03-01", "2026-03-05", sla_days=7)
    assert check.due_date == "2026-03-08"
    assert check.is_overdue is False
    assert check.days_overdue == 0


def test_overdue_flag_false_on_due_date_itself() -> None:
    # Due date is inclusive: still on time on the due date.
    check = acknowledgement_overdue("2026-03-01", "2026-03-08", sla_days=7)
    assert check.is_overdue is False
    assert check.days_overdue == 0


def test_overdue_never_when_already_acknowledged() -> None:
    check = acknowledgement_overdue("2026-03-01", "2026-04-01", sla_days=7, acknowledged=True)
    assert check.is_overdue is False
    assert check.days_overdue == 0


def test_overdue_undecidable_when_a_date_missing() -> None:
    assert acknowledgement_overdue(None, "2026-03-10", sla_days=7).is_overdue is False
    assert acknowledgement_overdue("2026-03-01", None, sla_days=7).is_overdue is False


def test_overdue_reference_before_issue_is_not_negative() -> None:
    # A reference date before the issue date must never yield a negative overdue.
    check = acknowledgement_overdue("2026-03-10", "2026-03-01", sla_days=7)
    assert check.is_overdue is False
    assert check.days_overdue == 0


def test_overdue_rejects_negative_sla() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        acknowledgement_overdue("2026-03-01", "2026-03-10", sla_days=-1)


def test_overdue_accepts_iso_timestamp_inputs() -> None:
    # The service stores the issue moment as a full ISO timestamp; only the
    # calendar-date part should be used.
    check = acknowledgement_overdue(
        "2026-03-01T09:15:00+00:00",
        "2026-03-10T23:59:00+00:00",
        sla_days=7,
    )
    assert check.due_date == "2026-03-08"
    assert check.is_overdue is True
    assert check.days_overdue == 2


# ── Response time ──────────────────────────────────────────────────────────


def test_response_time_whole_days() -> None:
    assert response_time_days("2026-03-01", "2026-03-06") == 5
    # Same day is zero days, not a negative or a fraction.
    assert response_time_days("2026-03-01", "2026-03-01") == 0


def test_response_time_none_when_a_date_is_missing() -> None:
    assert response_time_days(None, "2026-03-06") is None
    assert response_time_days("2026-03-01", None) is None


def test_response_time_rejects_reply_before_issue() -> None:
    with pytest.raises(ValueError, match="cannot be earlier"):
        response_time_days("2026-03-10", "2026-03-01")


def test_response_time_accepts_iso_timestamp_inputs() -> None:
    assert response_time_days("2026-03-01T08:00:00+00:00", "2026-03-06T17:30:00+00:00") == 5


# ── Punctuation hygiene ────────────────────────────────────────────────────


def test_no_banned_punctuation_in_user_facing_strings() -> None:
    # Guard against em-dashes, smart quotes and zero-width characters slipping
    # into any string a user reads. Built from code points so this test source
    # stays pure ASCII: em-dash, en-dash, left/right single quotes, left/right
    # double quotes, zero-width space, zero-width non-joiner, zero-width joiner,
    # word joiner.
    banned = [chr(cp) for cp in (0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D, 0x200B, 0x200C, 0x200D, 0x2060)]

    samples: list[str] = []
    samples.extend(EXPLAINERS.values())
    samples.extend(explain(t) for t in EXPLAINERS)
    samples.append(acknowledgement_rate(3, 4).explanation)
    samples.append(acknowledgement_rate(0, 0).explanation)
    samples.append(acknowledgement_overdue("2026-03-01", "2026-03-10", sla_days=7).explanation)
    samples.append(acknowledgement_overdue("2026-03-01", "2026-03-05", sla_days=7).explanation)
    samples.append(acknowledgement_overdue("2026-03-01", "2026-04-01", sla_days=7, acknowledged=True).explanation)
    samples.append(acknowledgement_overdue(None, None, sla_days=7).explanation)
    for locale in SUPPORTED_LOCALES:
        samples.extend(localize_status(code, locale) for code in VALID_STATUSES)
        samples.extend(localize_purpose(code, locale) for code in PURPOSE_CODES)

    for text in samples:
        for ch in banned:
            assert ch not in text

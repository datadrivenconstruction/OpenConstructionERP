# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the framework-free approval-routes intl helpers.

Pure date / Decimal / string math, no database and no FastAPI, so this file
runs on its own without any fixtures. Covers the international guarantees:
locale-neutral ISO 8601 dates, a parameterised SLA/overdue threshold, localised
decision and status words with an English fallback, zero-division guards, and
rates kept inside their defined range with no NaN or infinity.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.approval_routes import intl

# -- Localised decision / status words -----------------------------------------


def test_describe_decision_english() -> None:
    assert intl.describe_decision("approved") == "Approved"
    assert intl.describe_decision("pending") == "Pending"
    assert intl.describe_decision("rejected") == "Rejected"


def test_describe_decision_localised_de_ru() -> None:
    assert intl.describe_decision("approved", "de") == "Genehmigt"
    assert intl.describe_decision("rejected", "ru") == "Отклонено"


def test_describe_decision_falls_back_to_english_for_unknown_locale() -> None:
    # An unsupported locale falls back to the English label, never a raw code.
    assert intl.describe_decision("approved", "zz") == "Approved"
    assert intl.describe_decision("approved", "zz-XX") == "Approved"


def test_describe_decision_region_locale_is_reduced() -> None:
    assert intl.describe_decision("approved", "de-CH") == "Genehmigt"
    assert intl.describe_decision("approved", "de_AT") == "Genehmigt"


def test_describe_status_english_and_localised() -> None:
    assert intl.describe_status("cancelled") == "Cancelled"
    assert intl.describe_status("cancelled", "de") == "Abgebrochen"
    assert intl.describe_status("cancelled", "ru") == "Отменено"


def test_describe_status_covers_every_canonical_code() -> None:
    for code in intl.STATUS_CODES:
        for locale in ("en", "de", "ru"):
            label = intl.describe_status(code, locale)
            assert label  # a non-blank, capitalised label
            assert label[0].isupper()


def test_describe_missing_code_is_unknown_word_not_blank() -> None:
    assert intl.describe_decision(None) == "Unknown"
    assert intl.describe_decision(None, "de") == "Unbekannt"
    assert intl.describe_decision(None, "ru") == "Неизвестно"


def test_describe_unknown_code_is_humanised_not_blank() -> None:
    # A code a newer workflow might add is shown readably, never blank.
    assert intl.describe_status("part_approved") == "Part approved"


# -- Explainers ----------------------------------------------------------------


def test_explain_returns_one_line_for_known_concepts() -> None:
    for concept in ("approval_step", "step_completion_rate", "overdue_step", "sla_days"):
        text = intl.explain(concept)
        assert text
        assert "\n" not in text  # one line


def test_explain_rejects_unknown_concept() -> None:
    with pytest.raises(ValueError, match="Unknown approval concept"):
        intl.explain("not_a_concept")


# -- Counting helpers ----------------------------------------------------------


def test_counts_by_decision_tallies_known_codes() -> None:
    counts = intl.counts_by_decision(["approved", "approved", "rejected", "pending"])
    assert counts == {"pending": 1, "approved": 2, "rejected": 1, "other": 0}


def test_counts_by_decision_empty_is_all_zero() -> None:
    counts = intl.counts_by_decision([])
    assert counts == {"pending": 0, "approved": 0, "rejected": 0, "other": 0}


def test_counts_by_decision_normalises_case_and_whitespace() -> None:
    counts = intl.counts_by_decision([" Approved ", "APPROVED"])
    assert counts["approved"] == 2


def test_counts_by_decision_unknown_and_none_go_to_other() -> None:
    counts = intl.counts_by_decision(["approved", "escalated", None, ""])
    assert counts["approved"] == 1
    assert counts["other"] == 3
    # Total always equals the number of inputs.
    assert sum(counts.values()) == 4


def test_counts_by_status_covers_four_states_plus_other() -> None:
    counts = intl.counts_by_status(["pending", "approved", "rejected", "cancelled", "cancelled"])
    assert counts == {"pending": 1, "approved": 1, "rejected": 1, "cancelled": 2, "other": 0}


# -- Step completion rate ------------------------------------------------------


def test_step_completion_rate_basic_fraction() -> None:
    report = intl.step_completion_rate(4, 1)
    assert report["rate"] == "0.2500"
    assert report["rate_percent"] == "25.00"
    assert report["pending_steps"] == "3"
    assert report["is_complete"] == "false"


def test_step_completion_rate_full_route() -> None:
    report = intl.step_completion_rate(3, 3)
    assert report["rate"] == "1.0000"
    assert report["rate_percent"] == "100.00"
    assert report["is_complete"] == "true"


def test_step_completion_rate_zero_steps_is_guarded_not_error() -> None:
    # Division-by-zero guard: no steps -> a well-defined zero, never a crash.
    report = intl.step_completion_rate(0, 0)
    assert report["rate"] == "0.0000"
    assert report["rate_percent"] == "0.00"
    assert report["is_complete"] == "false"


def test_step_completion_rate_stays_within_zero_to_one() -> None:
    # Sweep a range of ratios; the rate must never leave [0, 1] / [0, 100].
    for total in range(0, 12):
        for completed in range(0, total + 1):
            report = intl.step_completion_rate(total, completed)
            rate = Decimal(report["rate"])
            pct = Decimal(report["rate_percent"])
            assert Decimal("0") <= rate <= Decimal("1")
            assert Decimal("0") <= pct <= Decimal("100")
            # No NaN / infinity ever leaks through.
            assert rate.is_finite()
            assert pct.is_finite()


def test_step_completion_rate_rejects_completed_over_total() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        intl.step_completion_rate(2, 3)


def test_step_completion_rate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.step_completion_rate(-1, 0)


def test_step_completion_rate_rejects_fractional() -> None:
    with pytest.raises(ValueError, match="whole number"):
        intl.step_completion_rate("2.5", 1)


def test_step_completion_rate_rejects_bool() -> None:
    with pytest.raises(ValueError, match="whole number"):
        intl.step_completion_rate(3, True)


def test_completion_from_decisions_counts_decided_steps() -> None:
    report = intl.completion_from_decisions(["approved", "rejected", "pending"])
    assert report["total_steps"] == "3"
    assert report["completed_steps"] == "2"
    assert report["approved"] == "1"
    assert report["rejected"] == "1"
    assert report["pending"] == "1"
    assert report["rate"] == "0.6667"


def test_completion_from_decisions_honours_explicit_total() -> None:
    # Two decision rows but a five-step route: pending steps counted honestly.
    report = intl.completion_from_decisions(["approved", "approved"], total_steps=5)
    assert report["total_steps"] == "5"
    assert report["completed_steps"] == "2"
    assert report["pending_steps"] == "3"


def test_completion_from_decisions_empty_is_guarded() -> None:
    report = intl.completion_from_decisions([])
    assert report["rate"] == "0.0000"
    assert report["is_complete"] == "false"


# -- ISO 8601 dates ------------------------------------------------------------


def test_format_iso_date_from_string_date_and_datetime() -> None:
    assert intl.format_iso_date("2026-07-05") == "2026-07-05"
    assert intl.format_iso_date(date(2026, 7, 5)) == "2026-07-05"
    assert intl.format_iso_date(datetime(2026, 7, 5, 13, 30)) == "2026-07-05"


def test_format_iso_date_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.format_iso_date("05/07/2026")


# -- Overdue step flag (parameterised SLA) -------------------------------------


def test_is_step_overdue_after_due_date_with_no_grace() -> None:
    assert intl.is_step_overdue("2026-07-01", "2026-07-02") is True


def test_is_step_overdue_on_due_date_is_not_overdue() -> None:
    assert intl.is_step_overdue("2026-07-01", "2026-07-01") is False


def test_is_step_overdue_respects_sla_grace_days() -> None:
    # Three days late but a 5-day SLA grace: still on time.
    assert intl.is_step_overdue("2026-07-01", "2026-07-04", sla_days=5) is False
    # Six days late against the same 5-day grace: overdue.
    assert intl.is_step_overdue("2026-07-01", "2026-07-07", sla_days=5) is True


def test_is_step_overdue_none_due_date_is_never_overdue() -> None:
    # A step with no deadline can never be overdue and must not raise.
    assert intl.is_step_overdue(None, "2026-07-07") is False


def test_days_overdue_counts_days_past_grace_and_clamps_at_zero() -> None:
    assert intl.days_overdue("2026-07-01", "2026-07-10", sla_days=2) == 7
    # On time -> zero, never negative.
    assert intl.days_overdue("2026-07-01", "2026-06-20") == 0


def test_days_overdue_accepts_datetime_reference() -> None:
    assert intl.days_overdue("2026-07-01", datetime(2026, 7, 5, 9, 0)) == 4


def test_overdue_rejects_negative_sla_days() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.is_step_overdue("2026-07-01", "2026-07-02", sla_days=-1)


# -- No banned typography anywhere in the module's output ----------------------


def _banned_characters() -> set[str]:
    """Build the banned-character set from code points, never as literals.

    Covers em dash, en dash, the smart single and double quotes, and the
    zero-width / word-joiner / BOM code points. Constructing them via ``chr``
    keeps a literal banned glyph out of this source file entirely.
    """
    code_points = (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2018,  # left single smart quote
        0x2019,  # right single smart quote
        0x201C,  # left double smart quote
        0x201D,  # right double smart quote
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
        0xFEFF,  # zero-width no-break space / BOM
    )
    return {chr(cp) for cp in code_points}


def test_localised_labels_contain_no_banned_typography() -> None:
    banned = _banned_characters()
    samples: list[str] = []
    for code in intl.DECISION_CODES:
        for locale in ("en", "de", "ru", "fr"):
            samples.append(intl.describe_decision(code, locale))
    for code in intl.STATUS_CODES:
        for locale in ("en", "de", "ru", "fr"):
            samples.append(intl.describe_status(code, locale))
    for concept in intl.CONCEPTS:
        samples.append(intl.explain(concept))
    for text in samples:
        assert not (banned & set(text)), f"banned typography in output: {text!r}"

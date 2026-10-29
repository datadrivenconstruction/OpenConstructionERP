"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the enterprise-workflows international reporting helpers.

These tests are pure and DB-free: they exercise ``app.modules.
enterprise_workflows.intl`` only, which has no database, framework or I/O
dependency. They lock the international, edge-case and explainability
contract:

* Rates stay finite and inside [0, 1] or [0, 100]; zero steps and zero
  instances never divide by zero.
* Negative or impossible counts raise a plain ValueError, never a 500.
* Dates are read as ISO 8601; SLA / grace days are a parameter.
* Status and action words localize into en / de / ru with an English
  fallback for any unknown locale.
* The module source carries no em-dashes, smart quotes or zero-width
  characters (the banned set is built from chr() code points).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.modules.enterprise_workflows import intl
from tests._watermark import strip_marks

# ── Locale normalization and localization ────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("de-DE", "de"),
        ("de_AT", "de"),
        ("RU", "ru"),
        ("en-US", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize_locale(raw: str | None, expected: str) -> None:
    assert intl.normalize_locale(raw) == expected


def test_localize_status_three_languages() -> None:
    assert intl.localize_status("approved", "en") == "Approved"
    assert intl.localize_status("approved", "de") == "Genehmigt"
    assert intl.localize_status("approved", "ru") == "Одобрено"


def test_localize_status_unknown_locale_falls_back_to_english() -> None:
    # An unsupported locale must not error and must return the English word.
    assert intl.localize_status("rejected", "zz") == "Rejected"
    assert intl.localize_status("rejected", "zz-ZZ") == "Rejected"


def test_localize_status_unknown_status_is_readable() -> None:
    # An unknown status is title-cased rather than left as a raw token.
    assert intl.localize_status("on_hold", "en") == "On Hold"
    assert intl.localize_status("", "en") == ""


def test_localize_action_type_localizes_and_falls_back() -> None:
    assert intl.localize_action_type("sign_off", "de") == "Endgueltige Freigabe"
    assert intl.localize_action_type("sign_off", "ru") == "Окончательное утверждение"
    # Unknown action type -> readable English-style title.
    assert intl.localize_action_type("escalate", "en") == "Escalate"


def test_explain_returns_localized_one_liner() -> None:
    for figure in (
        "workflow_step",
        "step_completion_rate",
        "active_vs_done",
        "overdue",
        "cycle_time_days",
    ):
        assert intl.explain(figure, "en")
        assert intl.explain(figure, "de")
        assert intl.explain(figure, "ru")
    # Unknown figure -> empty string, never an exception.
    assert intl.explain("does_not_exist", "en") == ""
    # Unknown locale falls back to English text.
    assert intl.explain("overdue", "zz") == intl.explain("overdue", "en")


# ── Step completion rate: zero guard, bounds, errors ─────────────────────


def test_step_completion_rate_basic() -> None:
    assert intl.step_completion_rate(1, 2) == 0.5
    assert intl.step_completion_rate(1, 2, scale="percent") == 50.0
    assert intl.step_completion_rate(4, 4) == 1.0


def test_step_completion_rate_zero_total_is_well_defined() -> None:
    # No steps must not divide by zero; the rate is a defined 0.0.
    result = intl.step_completion_rate(0, 0)
    assert result == 0.0
    assert math.isfinite(result)


def test_step_completion_rate_stays_in_range_and_finite() -> None:
    for completed in range(0, 6):
        rate = intl.step_completion_rate(completed, 5)
        assert 0.0 <= rate <= 1.0
        assert math.isfinite(rate)
        pct = intl.step_completion_rate(completed, 5, scale="percent")
        assert 0.0 <= pct <= 100.0
        assert math.isfinite(pct)


def test_step_completion_rate_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        intl.step_completion_rate(-1, 5)
    with pytest.raises(ValueError):
        intl.step_completion_rate(1, -5)
    with pytest.raises(ValueError):
        intl.step_completion_rate(6, 5)
    with pytest.raises(ValueError):
        intl.step_completion_rate(1, 2, scale="ratio")


def test_step_completion_breakdown_exposes_components() -> None:
    b = intl.step_completion_breakdown(1, 4, locale="de")
    assert b["completed"] == 1
    assert b["total"] == 4
    assert b["remaining"] == 3
    assert b["rate_fraction"] == 0.25
    assert b["rate_percent"] == 25.0
    assert b["explanation"]  # localized non-empty explainer


# ── Counts by state, active vs done ──────────────────────────────────────


def test_counts_by_state_from_strings_dicts_objects() -> None:
    class _Req:
        def __init__(self, status: str) -> None:
            self.status = status

    items: list[object] = [
        "pending",
        {"status": "PENDING"},
        _Req("approved"),
        "rejected",
    ]
    counts = intl.counts_by_state(items)
    assert counts == {"pending": 2, "approved": 1, "rejected": 1}


def test_counts_by_state_empty_and_unknown() -> None:
    assert intl.counts_by_state([]) == {}
    assert intl.counts_by_state([{"status": None}, "  "]) == {"unknown": 2}


def test_active_vs_done_split() -> None:
    items = ["pending", "pending", "approved", "rejected", "cancelled", "weird"]
    split = intl.active_vs_done(items)
    assert split["active"] == 2
    assert split["done"] == 3
    assert split["other"] == 1
    assert split["total"] == 6


def test_active_vs_done_empty_is_all_zero() -> None:
    assert intl.active_vs_done([]) == {"active": 0, "done": 0, "other": 0, "total": 0}


# ── Overdue: ISO 8601 dates, parameterized SLA ───────────────────────────


def test_is_step_overdue_respects_sla_days() -> None:
    due = "2026-07-01"
    ref = "2026-07-03T09:00:00"
    # Two days late with no grace -> overdue.
    assert intl.is_step_overdue(due, ref, sla_days=0) is True
    # A three-day SLA grace absorbs the delay -> not overdue.
    assert intl.is_step_overdue(due, ref, sla_days=3) is False
    # Exactly at the deadline is not yet overdue (strict later-than).
    assert intl.is_step_overdue(due, "2026-07-01", sla_days=0) is False


def test_is_step_overdue_accepts_date_objects_and_z_suffix() -> None:
    assert intl.is_step_overdue(date(2026, 7, 1), date(2026, 7, 5), sla_days=1) is True
    # Trailing Z is read as UTC and does not raise.
    assert intl.is_step_overdue("2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z") is True


def test_is_step_overdue_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        intl.is_step_overdue("2026-07-01", "2026-07-02", sla_days=-1)
    with pytest.raises(ValueError):
        intl.is_step_overdue("not-a-date", "2026-07-02")
    with pytest.raises(ValueError):
        intl.is_step_overdue("2026-07-01", "")


def test_overdue_breakdown_components() -> None:
    b = intl.overdue_breakdown("2026-07-01", "2026-07-05", sla_days=1, locale="ru")
    assert b["is_overdue"] is True
    assert b["sla_days"] == 1
    assert b["deadline"].startswith("2026-07-02")
    assert b["days_overdue"] == pytest.approx(3.0)
    assert b["explanation"]
    # Not overdue -> zero days over, deadline still reported.
    ok = intl.overdue_breakdown("2026-07-01", "2026-07-01")
    assert ok["is_overdue"] is False
    assert ok["days_overdue"] == 0.0


# ── Cycle time in days ───────────────────────────────────────────────────


def test_cycle_time_days_basic_and_fractional() -> None:
    assert intl.cycle_time_days("2026-07-01", "2026-07-04") == pytest.approx(3.0)
    half = intl.cycle_time_days("2026-07-01T00:00:00", "2026-07-01T12:00:00")
    assert half == pytest.approx(0.5)
    assert math.isfinite(half)


def test_cycle_time_days_mixed_tz_awareness() -> None:
    # One aware, one naive: the naive side is read as UTC, no TypeError.
    aware = datetime(2026, 7, 2, tzinfo=UTC)
    naive = datetime(2026, 7, 1)
    assert intl.cycle_time_days(naive, aware) == pytest.approx(1.0)


def test_cycle_time_days_negative_guard() -> None:
    with pytest.raises(ValueError):
        intl.cycle_time_days("2026-07-04", "2026-07-01")
    # Opt-in signed value for diagnostics.
    signed = intl.cycle_time_days("2026-07-04", "2026-07-01", allow_negative=True)
    assert signed == pytest.approx(-3.0)


# ── Step description ─────────────────────────────────────────────────────


def test_describe_step_plain_language() -> None:
    step = {"name": "Design review", "action_type": "review", "role": "manager"}
    text_en = intl.describe_step(step, index=2, locale="en")
    assert text_en.startswith("Step 2:")
    assert "Design review" in text_en
    assert "manager" in text_en

    text_de = intl.describe_step(step, index=2, locale="de")
    assert text_de.startswith("Schritt 2:")

    text_ru = intl.describe_step(step, index=1, locale="ru")
    assert text_ru.startswith("Шаг 1:")


def test_describe_step_defaults_and_no_index() -> None:
    # No name -> falls back to the localized action label; no index -> no prefix.
    text = intl.describe_step({"action_type": "sign_off"}, locale="en")
    assert text == "Final sign-off"


def test_describe_step_rejects_non_dict() -> None:
    with pytest.raises(ValueError):
        intl.describe_step(["not", "a", "dict"])  # type: ignore[arg-type]


# ── Banned-character guard (built from chr() code points) ────────────────


def test_module_source_has_no_banned_characters() -> None:
    """The intl module and this test must avoid em-dashes, smart quotes and
    zero-width characters. The banned set is assembled from code points so
    no banned glyph ever appears as a literal in this file.
    """
    banned = {
        chr(0x2013),  # en dash
        chr(0x2014),  # em dash
        chr(0x2018),  # left single quote
        chr(0x2019),  # right single quote
        chr(0x201C),  # left double quote
        chr(0x201D),  # right double quote
        chr(0x2026),  # horizontal ellipsis
        chr(0x200B),  # zero width space
        chr(0x200C),  # zero width non-joiner
        chr(0x200D),  # zero width joiner
        chr(0x2060),  # word joiner
        chr(0xFEFF),  # zero width no-break space / BOM
    }
    targets = [
        Path(intl.__file__),
        Path(__file__),
    ]
    for path in targets:
        text = strip_marks(path.read_text(encoding="utf-8"))
        found = banned.intersection(text)
        assert not found, f"{path.name} contains banned characters: {[hex(ord(c)) for c in found]}"

"""Unit tests for the meetings international helpers.

Scope:
    Pure, database-free helpers in ``app.modules.meetings.intl``:
    language normalization and translation with English fallback, ISO
    8601 date parsing, the completion-rate zero guard, status counting,
    the overdue flag with a configurable threshold, and the aggregate
    summary. No database, ORM, or network is touched.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.modules.meetings.intl import (
    ActionItemSummary,
    action_completion_rate,
    count_actions_by_status,
    count_overdue_open_actions,
    explainers,
    is_overdue,
    localize_status,
    normalize_lang,
    open_vs_done,
    overdue_label,
    parse_iso_date,
    summarize_action_items,
    translate,
)

# ── Language + translation ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("de", "de"),
        ("ru", "ru"),
        ("de-DE", "de"),
        ("RU_ru", "ru"),
        ("  EN  ", "en"),
        ("fr", "fr"),
        ("xx", "en"),  # not a platform language -> English
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize_lang(raw: str | None, expected: str) -> None:
    assert normalize_lang(raw) == expected


def test_translate_uses_requested_language() -> None:
    assert translate("status.open", "de") == "Offen"
    assert translate("status.completed", "ru") == "Выполнено"


def test_translate_falls_back_to_english_then_key() -> None:
    # A language the platform does not carry falls back to English.
    assert translate("status.open", "xx") == "Open"
    # Unknown key echoes the key itself.
    assert translate("does.not.exist", "en") == "does.not.exist"


def test_localize_status_known_and_unknown() -> None:
    assert localize_status("completed", "de") == "Erledigt"
    assert localize_status("cancelled", "ru") == "Отменено"
    assert localize_status(None, "en") == "Open"  # defaults to open
    # An unknown status is echoed back, never a raw key.
    assert localize_status("deferred", "en") == "deferred"


def test_overdue_label_localized() -> None:
    assert overdue_label(True, "en") == "Overdue"
    assert overdue_label(False, "en") == "On track"
    assert overdue_label(True, "ru") == "Просрочено"


def test_explainers_all_present_and_localized() -> None:
    en = explainers("en")
    assert set(en) == {"action_item", "completion_rate", "open_vs_done", "overdue"}
    assert all(v.strip() for v in en.values())
    de = explainers("de")
    # German differs from English for the completion-rate explainer.
    assert de["completion_rate"] != en["completion_rate"]
    # Unknown locale falls back to English text.
    assert explainers("xx")["overdue"] == en["overdue"]


def test_every_summary_word_is_in_the_locale_files_for_en_de_ru() -> None:
    import json

    from app.core.i18n import LOCALES_DIR

    def group(code: str) -> dict[str, dict[str, str]]:
        return json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))["meetings"]["actions"]

    english = group("en")
    assert english["status"].keys() == {"open", "completed", "cancelled"}
    for code in ("de", "ru"):
        own = group(code)
        assert {k: set(v) for k, v in own.items()} == {k: set(v) for k, v in english.items()}, code
    assert translate("flag.overdue", "de") == "Überfällig"


# ── Date parsing ───────────────────────────────────────────────────────────


def test_parse_iso_date_accepts_str_date_datetime() -> None:
    assert parse_iso_date("2026-07-05") == date(2026, 7, 5)
    assert parse_iso_date(date(2026, 7, 5)) == date(2026, 7, 5)
    assert parse_iso_date(datetime(2026, 7, 5, 14, 30)) == date(2026, 7, 5)
    # Timestamp prefix is tolerated (first 10 chars).
    assert parse_iso_date("2026-07-05T09:00:00Z") == date(2026, 7, 5)


def test_parse_iso_date_returns_none_on_bad_input() -> None:
    assert parse_iso_date(None) is None
    assert parse_iso_date("") is None
    assert parse_iso_date("   ") is None
    assert parse_iso_date("not-a-date") is None
    assert parse_iso_date("2026-13-40") is None


# ── Completion rate (zero guard, range, ValueError) ───────────────────────


def test_completion_rate_basic() -> None:
    assert action_completion_rate(1, 4) == 0.25
    assert action_completion_rate(4, 4) == 1.0
    assert action_completion_rate(0, 4) == 0.0


def test_completion_rate_zero_total_is_guarded() -> None:
    # No division by zero, no NaN: an empty set is defined as 0.0.
    assert action_completion_rate(0, 0) == 0.0


def test_completion_rate_percent_in_range() -> None:
    assert action_completion_rate(1, 4, as_percent=True) == 25.0
    assert action_completion_rate(0, 0, as_percent=True) == 0.0
    pct = action_completion_rate(1, 3, as_percent=True)
    assert 0.0 <= pct <= 100.0


def test_completion_rate_always_in_unit_range() -> None:
    for done, total in [(0, 0), (0, 5), (3, 5), (5, 5), (1, 1)]:
        rate = action_completion_rate(done, total)
        assert 0.0 <= rate <= 1.0


def test_completion_rate_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        action_completion_rate(-1, 4)
    with pytest.raises(ValueError, match="non-negative"):
        action_completion_rate(1, -4)


def test_completion_rate_rejects_done_over_total() -> None:
    with pytest.raises(ValueError, match="exceed"):
        action_completion_rate(5, 4)


# ── Status counting ───────────────────────────────────────────────────────


def test_count_actions_by_status_basic() -> None:
    items = [
        {"description": "a", "status": "open"},
        {"description": "b", "status": "completed"},
        {"description": "c", "status": "cancelled"},
        {"description": "d"},  # missing status -> open
    ]
    counts = count_actions_by_status(items)
    assert counts == {"open": 2, "completed": 1, "cancelled": 1}


def test_count_actions_by_status_empty_and_none() -> None:
    zeros = {"open": 0, "completed": 0, "cancelled": 0}
    assert count_actions_by_status([]) == zeros
    assert count_actions_by_status(None) == zeros


def test_count_actions_by_status_unknown_bucketed_as_other() -> None:
    items = [{"status": "deferred"}, {"status": "open"}]
    counts = count_actions_by_status(items)
    assert counts["other"] == 1
    assert counts["open"] == 1


def test_count_actions_by_status_ignores_non_dicts() -> None:
    items = [{"status": "open"}, "garbage", None, 42]
    counts = count_actions_by_status(items)
    assert counts == {"open": 1, "completed": 0, "cancelled": 0}


def test_open_vs_done() -> None:
    items = [
        {"status": "open"},
        {"status": "open"},
        {"status": "completed"},
        {"status": "cancelled"},
    ]
    assert open_vs_done(items) == (2, 1)
    assert open_vs_done([]) == (0, 0)


# ── Overdue flag (threshold as a parameter) ───────────────────────────────


def test_is_overdue_true_when_past_due_and_open() -> None:
    assert is_overdue("2026-07-01", "2026-07-05") is True


def test_is_overdue_false_when_not_yet_due() -> None:
    assert is_overdue("2026-07-10", "2026-07-05") is False
    # Same day is not overdue (strictly before).
    assert is_overdue("2026-07-05", "2026-07-05") is False


def test_is_overdue_only_open_items() -> None:
    assert is_overdue("2026-07-01", "2026-07-05", status="completed") is False
    assert is_overdue("2026-07-01", "2026-07-05", status="cancelled") is False


def test_is_overdue_grace_days_threshold() -> None:
    # Due 3 days ago, but a 5-day grace threshold keeps it on track.
    assert is_overdue("2026-07-02", "2026-07-05", grace_days=5) is False
    # A 1-day grace still leaves it overdue.
    assert is_overdue("2026-07-02", "2026-07-05", grace_days=1) is True


def test_is_overdue_false_on_bad_dates() -> None:
    assert is_overdue(None, "2026-07-05") is False
    assert is_overdue("2026-07-01", None) is False
    assert is_overdue("garbage", "2026-07-05") is False


def test_count_overdue_open_actions() -> None:
    items = [
        {"status": "open", "due_date": "2026-07-01"},  # overdue
        {"status": "open", "due_date": "2026-07-10"},  # future
        {"status": "completed", "due_date": "2026-06-01"},  # done, not overdue
        {"status": "open", "due_date": None},  # no due date
        {"status": "open", "due_date": "2026-07-02"},  # overdue
    ]
    assert count_overdue_open_actions(items, "2026-07-05") == 2


def test_count_overdue_open_actions_bad_reference_is_zero() -> None:
    items = [{"status": "open", "due_date": "2026-07-01"}]
    assert count_overdue_open_actions(items, "not-a-date") == 0
    assert count_overdue_open_actions(items, None) == 0


def test_count_overdue_open_actions_respects_threshold() -> None:
    items = [{"status": "open", "due_date": "2026-07-02"}]
    assert count_overdue_open_actions(items, "2026-07-05") == 1
    assert count_overdue_open_actions(items, "2026-07-05", grace_days=10) == 0


# ── Aggregate summary ─────────────────────────────────────────────────────


def test_summarize_action_items_full() -> None:
    items = [
        {"status": "open", "due_date": "2026-07-01"},  # overdue
        {"status": "open", "due_date": "2026-08-01"},  # future
        {"status": "completed", "due_date": "2026-06-01"},
        {"status": "cancelled", "due_date": "2026-06-01"},
    ]
    summary = summarize_action_items(
        items,
        reference_date="2026-07-05",
        lang="de",
    )
    assert isinstance(summary, ActionItemSummary)
    assert summary.total == 4
    assert summary.open == 2
    assert summary.done == 1
    assert summary.cancelled == 1
    assert summary.overdue_open == 1
    # completion_rate = done / total = 1 / 4.
    assert summary.completion_rate == 0.25
    assert summary.completion_percent == 25.0
    assert summary.lang == "de"
    assert summary.explainers["completion_rate"]


def test_summarize_action_items_empty_is_zero_and_safe() -> None:
    summary = summarize_action_items([], reference_date="2026-07-05")
    assert summary.total == 0
    assert summary.completion_rate == 0.0
    assert summary.completion_percent == 0.0
    assert summary.overdue_open == 0
    # Explainers are always present even for an empty set.
    assert set(summary.explainers) == {
        "action_item",
        "completion_rate",
        "open_vs_done",
        "overdue",
    }


def test_summarize_action_items_without_reference_date() -> None:
    items = [{"status": "open", "due_date": "2026-07-01"}]
    summary = summarize_action_items(items)
    # No reference date -> overdue cannot be judged, stays 0, no error.
    assert summary.overdue_open == 0
    assert summary.open == 1


def test_summary_as_dict_is_json_friendly() -> None:
    summary = summarize_action_items(
        [{"status": "completed"}],
        reference_date="2026-07-05",
        lang="ru",
    )
    data = summary.as_dict()
    assert data["total"] == 1
    assert data["done"] == 1
    assert data["completion_rate"] == 1.0
    assert data["lang"] == "ru"
    assert isinstance(data["explainers"], dict)

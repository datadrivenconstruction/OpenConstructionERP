# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Age rule for offline field captures (``field_diary.offline_op_fresh``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.validation.engine import validation_engine
from app.core.validation.messages import is_key_present
from app.modules.field_diary.capture_age import MAX_OP_AGE_DAYS, op_age_days, parse_captured_at

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def test_age_is_whole_days_and_never_negative() -> None:
    assert op_age_days((NOW - timedelta(days=3, hours=5)).isoformat(), NOW) == 3
    assert op_age_days((NOW + timedelta(days=2)).isoformat(), NOW) == 0  # device clock ahead


def test_unreadable_or_missing_time_has_no_age() -> None:
    assert op_age_days(None, NOW) is None
    assert op_age_days("not a date", NOW) is None
    assert parse_captured_at("2026-11-01T08:00:00Z") == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


def test_naive_timestamp_is_read_as_utc() -> None:
    assert parse_captured_at("2026-11-01T08:00:00").tzinfo is UTC


@pytest.mark.parametrize(("days", "fails"), [(MAX_OP_AGE_DAYS, False), (MAX_OP_AGE_DAYS + 1, True), (0, False)])
@pytest.mark.asyncio
async def test_rule_boundary(days: int, fails: bool) -> None:
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()

    captured = (datetime.now(UTC) - timedelta(days=days, minutes=5)).isoformat()
    report = await validation_engine.validate(
        data={"captured_at": captured, "kind": "ncr", "max_age_days": MAX_OP_AGE_DAYS},
        rule_sets=["field_diary_capture"],
        target_type="ncr",
        target_id="x",
        metadata={"locale": "de"},
    )
    assert report.has_errors is fails
    if fails:
        assert "30" in report.errors[0].message


@pytest.mark.parametrize("locale", ["en", "de", "ru", "ja", "ar", "zh"])
def test_messages_exist_in_locale(locale: str) -> None:
    assert is_key_present("field_diary.offline_op_fresh.fail", locale)
    assert is_key_present("field_diary.offline_op_fresh.suggestion", locale)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, "captured_at_missing"),
        ("  ", "captured_at_missing"),
        ("nope", "captured_at_unreadable"),
        ("2026-11-01T08:00:00Z", None),
    ],
)
def test_capture_time_warning(value: str | None, code: str | None) -> None:
    from app.modules.field_diary.capture_age import capture_time_warning

    assert capture_time_warning(value) == code

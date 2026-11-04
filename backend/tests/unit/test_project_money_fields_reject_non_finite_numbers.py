"""Non-finite numbers in project money/percentage fields are a 422, never a 500 or a stored 'Infinity'."""

from __future__ import annotations

import pytest

from app.modules.dashboard.router import _parse_uuid_list
from app.modules.projects.schemas import _validate_money, _validate_percentage


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "-Infinity", "inf"])
def test_money_rejects_non_finite(raw: str) -> None:
    with pytest.raises(ValueError, match="valid number"):
        _validate_money(raw, "budget_estimate")


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity"])
def test_percentage_rejects_non_finite(raw: str) -> None:
    with pytest.raises(ValueError):
        _validate_percentage(raw, "contingency_pct")


def test_finite_values_still_pass() -> None:
    assert _validate_money("1250.50", "budget_estimate") == "1250.50"
    assert _validate_percentage("7.5", "contingency_pct") == "7.5"


def test_blank_project_ids_filter_is_absent_not_empty() -> None:
    assert _parse_uuid_list("") is None
    assert _parse_uuid_list(" , ") is None
    assert _parse_uuid_list("not-a-uuid") == []


@pytest.mark.asyncio
async def test_unusable_project_ids_filter_returns_no_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.dashboard import service

    async def _admin(*_a, **_k) -> bool:
        return True

    class _Boom:
        async def execute(self, *_a, **_k):
            raise AssertionError("must not query when the filter selected nothing")

    monkeypatch.setattr(service, "is_admin", _admin)
    assert await service.accessible_projects(_Boom(), "u", requested_ids=[]) == []


@pytest.mark.parametrize(
    ("a", "b"), [("2026-13-45", "2026-12-31"), ("2026-02-30", "2026-03-01"), ("2026-05-02", "2026-05-01")]
)
def test_retainage_period_must_be_real_and_ordered(a: str, b: str) -> None:
    from fastapi import HTTPException

    from app.modules.reporting.router import _check_period

    with pytest.raises(HTTPException) as ei:
        _check_period(a, b)
    assert ei.value.status_code == 422


def test_retainage_period_valid_passes() -> None:
    from app.modules.reporting.router import _check_period

    _check_period("2026-01-01", "2026-01-01")

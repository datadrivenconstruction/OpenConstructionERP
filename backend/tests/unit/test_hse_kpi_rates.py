"""HSE KPI: recordable / lost-time classification, configurable rate bases, exposure hours."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.hse_advanced.service import (
    HSEAdvancedService,
    compute_ltifr,
    compute_trir,
    is_lost_time_incident,
    is_recordable_incident,
)


def _inc(day="2026-03-10", itype="injury", treatment=None, lost=0, away=None, restricted=None, flag=False):
    return SimpleNamespace(
        incident_date=day,
        incident_type=itype,
        treatment_type=treatment,
        days_lost=lost,
        days_away=away,
        days_restricted=restricted,
        osha_recordable=flag,
    )


def test_lost_time_needs_days_away_or_fatality() -> None:
    assert is_lost_time_incident(_inc(lost=3))
    assert is_lost_time_incident(_inc(away=2))
    assert is_lost_time_incident(_inc(treatment="fatality"))
    assert not is_lost_time_incident(_inc(treatment="medical"))
    assert not is_lost_time_incident(_inc(restricted=4))


def test_near_miss_and_property_damage_are_never_recordable() -> None:
    assert not is_recordable_incident(_inc(itype="near_miss", lost=5, flag=True))
    assert not is_recordable_incident(_inc(itype="property_damage", treatment="hospital"))


def test_recordable_covers_flag_treatment_restricted_and_every_lti() -> None:
    assert is_recordable_incident(_inc(flag=True))
    assert is_recordable_incident(_inc(treatment="hospital"))
    assert is_recordable_incident(_inc(restricted=2))
    assert is_recordable_incident(_inc(away=1))
    assert not is_recordable_incident(_inc(treatment="first_aid"))


def test_rate_bases_are_configurable() -> None:
    assert compute_trir(2, 400_000) == Decimal("1.0000")
    assert compute_trir(2, 400_000, base=1_000_000) == Decimal("5.0000")
    assert compute_ltifr(1, 400_000) == Decimal("2.5000")
    assert compute_ltifr(1, 400_000, base=200_000) == Decimal("0.5000")


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows, scalar

    def scalars(self):
        return MagicMock(all=lambda: self._rows)

    def scalar_one(self):
        return self._scalar


def _service(incidents, field_hours):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result(rows=incidents), _Result(scalar=field_hours)])
    return HSEAdvancedService(session)


@pytest.mark.asyncio
async def test_worked_example_from_incidents_and_field_time_hours() -> None:
    incidents = [
        _inc("2026-02-01", lost=4),  # LTI + recordable
        _inc("2026-02-20", treatment="medical"),  # recordable only
        _inc("2026-03-01", itype="near_miss"),  # excluded
        _inc("2025-12-01", lost=9),  # outside the period
    ]
    svc = _service(incidents, Decimal("400000"))
    kpi = await svc.project_kpi(
        uuid.uuid4(),
        hours_worked=None,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
    )
    assert (kpi.recordable_count, kpi.lti_count) == (2, 1)
    assert kpi.hours_source == "field_time"
    assert kpi.trir == Decimal("1.0000")
    assert kpi.ltifr == Decimal("2.5000")


@pytest.mark.asyncio
async def test_no_exposure_hours_gives_null_rates_not_zero() -> None:
    svc = _service([_inc(lost=2)], Decimal("0"))
    kpi = await svc.project_kpi(uuid.uuid4(), hours_worked=None, period_start=None, period_end=None)
    assert kpi.hours_source == "none"
    assert kpi.trir is None
    assert kpi.ltifr is None
    assert kpi.lti_count == 1


@pytest.mark.asyncio
async def test_supplied_hours_win_and_bases_apply() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_Result(rows=[_inc(lost=1)])])
    kpi = await HSEAdvancedService(session).project_kpi(
        uuid.uuid4(),
        hours_worked=Decimal("200000"),
        period_start=None,
        period_end=None,
        trir_base=1_000_000,
        ltifr_base=200_000,
    )
    assert kpi.hours_source == "supplied"
    assert kpi.trir == Decimal("5.0000")
    assert kpi.ltifr == Decimal("1.0000")

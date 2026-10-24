# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The certified payroll demo seed: which weeks it builds and where it runs."""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.certified_payroll import seed


def test_week_ends_on_the_last_completed_saturday() -> None:
    assert seed._last_saturday(date(2026, 10, 24)) == date(2026, 10, 17)
    assert seed._last_saturday(date(2026, 10, 26)) == date(2026, 10, 24)


def test_hours_are_a_working_week_with_no_sunday() -> None:
    for worker in range(len(seed._CREW)):
        for week in range(seed._WEEKS):
            assert seed._hours(worker, week, 0) == "0"
            weekdays = [seed._hours(worker, week, d) for d in range(1, 6)]
            assert all(h in {"8", "9"} for h in weekdays)


def test_every_worker_is_paid_at_least_the_determination() -> None:
    for _name, _ssn4, trade_ix, premium in seed._CREW:
        assert trade_ix < len(seed._TRADES)
        assert not premium.startswith("-")


class _Session:
    def __init__(self, project: object) -> None:
        self.project = project

    async def get(self, _model: object, _pid: object) -> object:
        return self.project


@pytest.mark.asyncio
async def test_skips_projects_outside_the_us_showcases() -> None:
    project = SimpleNamespace(metadata_={"demo_id": "consultancy-riyadh"}, name="Riyadh")
    assert await seed.seed_certified_payroll(_Session(project), project_id=uuid.uuid4()) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_skips_a_missing_project() -> None:
    assert await seed.seed_certified_payroll(_Session(None), project_id=uuid.uuid4()) == {}  # type: ignore[arg-type]

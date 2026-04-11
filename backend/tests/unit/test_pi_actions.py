"""Unit tests for project_intelligence.actions backend action executors.

These tests exercise the three real backend actions (``_run_validation``,
``_match_cwicr_prices``, ``_generate_schedule``) with the real domain
services patched out. The goal is to guarantee that:

1. Each action returns an ``ActionResult`` instance (never raises).
2. When the underlying service succeeds, ``ActionResult.success`` is True
   and the data payload carries the service's real identifiers.
3. When the project has no BOQ, each action fails cleanly with a
   descriptive message instead of silently redirecting.
4. When the underlying service raises, each action catches the exception
   and returns ``ActionResult(success=False, ...)``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.project_intelligence.actions import (
    ActionResult,
    _generate_schedule,
    _match_cwicr_prices,
    _run_validation,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_session() -> MagicMock:
    """Return a MagicMock AsyncSession with async commit/rollback stubs."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_boq(n_positions: int = 0) -> SimpleNamespace:
    """Build a fake BOQ object with the fields the actions read."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Main BOQ",
        positions=[_make_position() for _ in range(n_positions)],
    )


def _make_position(
    *,
    unit_rate: str = "0",
    quantity: str = "10",
    description: str = "Concrete wall C30/37",
    unit: str = "m3",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total="0",
        classification={},
        metadata_={},
    )


# ── _run_validation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_validation_success() -> None:
    session = _make_session()
    boq = _make_boq()
    project_id = str(uuid.uuid4())

    fake_report = {
        "report_id": str(uuid.uuid4()),
        "status": "passed",
        "passed_count": 12,
        "warning_count": 2,
        "error_count": 0,
    }

    svc_instance = MagicMock()
    svc_instance.run_validation = AsyncMock(return_value=fake_report)

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.validation.service.ValidationModuleService",
            return_value=svc_instance,
        ),
    ):
        result = await _run_validation(session, project_id)

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.data is not None
    assert result.data["report_id"] == fake_report["report_id"]
    assert result.data["error_count"] == 0
    svc_instance.run_validation.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_validation_no_boq() -> None:
    session = _make_session()
    with patch(
        "app.modules.project_intelligence.actions._find_project_boq",
        AsyncMock(return_value=None),
    ):
        result = await _run_validation(session, str(uuid.uuid4()))

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert "No BOQ" in result.message


@pytest.mark.asyncio
async def test_run_validation_service_raises() -> None:
    session = _make_session()
    boq = _make_boq()
    svc_instance = MagicMock()
    svc_instance.run_validation = AsyncMock(side_effect=RuntimeError("engine down"))

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.validation.service.ValidationModuleService",
            return_value=svc_instance,
        ),
    ):
        result = await _run_validation(session, str(uuid.uuid4()))

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert "engine down" in result.message


# ── _match_cwicr_prices ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_cwicr_prices_updates_zero_priced() -> None:
    session = _make_session()
    boq = _make_boq()
    # One zero-priced position + one already priced + one section header.
    zero = _make_position(unit_rate="0", quantity="5")
    priced = _make_position(unit_rate="100", quantity="5")
    header = _make_position(unit_rate="0", quantity="0", description="Section", unit="")
    boq.positions = [zero, priced, header]

    suggestion = SimpleNamespace(
        cost_item_id=str(uuid.uuid4()),
        code="CWR-001",
        unit_rate=150.0,
        score=0.87,
    )
    cost_svc_instance = MagicMock()
    cost_svc_instance.suggest_for_bim_element = AsyncMock(return_value=[suggestion])

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.costs.service.CostItemService",
            return_value=cost_svc_instance,
        ),
    ):
        result = await _match_cwicr_prices(session, str(uuid.uuid4()))

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.data["count_updated"] == 1
    assert result.data["count_skipped"] == 0
    # Zero position now carries the matched rate; priced and header untouched.
    from decimal import Decimal

    assert Decimal(zero.unit_rate) == Decimal("150")
    assert Decimal(zero.total) == Decimal("750")
    assert priced.unit_rate == "100"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_match_cwicr_prices_no_match_is_skipped() -> None:
    session = _make_session()
    boq = _make_boq()
    boq.positions = [_make_position(unit_rate="0", quantity="5")]

    cost_svc_instance = MagicMock()
    cost_svc_instance.suggest_for_bim_element = AsyncMock(return_value=[])

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.costs.service.CostItemService",
            return_value=cost_svc_instance,
        ),
    ):
        result = await _match_cwicr_prices(session, str(uuid.uuid4()))

    assert result.success is True
    assert result.data["count_updated"] == 0
    assert result.data["count_skipped"] == 1


@pytest.mark.asyncio
async def test_match_cwicr_prices_no_boq() -> None:
    session = _make_session()
    with patch(
        "app.modules.project_intelligence.actions._find_project_boq",
        AsyncMock(return_value=None),
    ):
        result = await _match_cwicr_prices(session, str(uuid.uuid4()))
    assert result.success is False
    assert "No BOQ" in result.message


# ── _generate_schedule ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_schedule_success() -> None:
    session = _make_session()
    boq = _make_boq()
    new_schedule = SimpleNamespace(id=uuid.uuid4())
    activities = [SimpleNamespace(id=uuid.uuid4()) for _ in range(7)]

    svc_instance = MagicMock()
    svc_instance.list_schedules_for_project = AsyncMock(return_value=([], 0))
    svc_instance.create_schedule = AsyncMock(return_value=new_schedule)
    svc_instance.generate_from_boq = AsyncMock(return_value=activities)

    proj_repo_instance = MagicMock()
    proj_repo_instance.get_by_id = AsyncMock(
        return_value=SimpleNamespace(planned_start_date="2026-05-01", actual_start_date=None)
    )

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.schedule.service.ScheduleService",
            return_value=svc_instance,
        ),
        patch(
            "app.modules.projects.repository.ProjectRepository",
            return_value=proj_repo_instance,
        ),
    ):
        result = await _generate_schedule(session, str(uuid.uuid4()))

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.data["activity_count"] == 7
    assert result.data["schedule_id"] == str(new_schedule.id)
    assert result.data["start_date"] == "2026-05-01"
    svc_instance.create_schedule.assert_awaited_once()
    svc_instance.generate_from_boq.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_schedule_refuses_if_exists() -> None:
    session = _make_session()
    boq = _make_boq()
    existing = [SimpleNamespace(id=uuid.uuid4())]

    svc_instance = MagicMock()
    svc_instance.list_schedules_for_project = AsyncMock(return_value=(existing, 1))
    svc_instance.create_schedule = AsyncMock()
    svc_instance.generate_from_boq = AsyncMock()

    with (
        patch(
            "app.modules.project_intelligence.actions._find_project_boq",
            AsyncMock(return_value=boq),
        ),
        patch(
            "app.modules.schedule.service.ScheduleService",
            return_value=svc_instance,
        ),
    ):
        result = await _generate_schedule(session, str(uuid.uuid4()))

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert "already exists" in result.message
    svc_instance.create_schedule.assert_not_awaited()
    svc_instance.generate_from_boq.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_schedule_no_boq() -> None:
    session = _make_session()
    with patch(
        "app.modules.project_intelligence.actions._find_project_boq",
        AsyncMock(return_value=None),
    ):
        result = await _generate_schedule(session, str(uuid.uuid4()))
    assert result.success is False
    assert "No BOQ" in result.message

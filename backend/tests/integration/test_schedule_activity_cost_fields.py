"""Integration: an activity's cost and progress-rigor columns survive the API.

``Activity`` has carried ``cost_planned`` / ``cost_actual`` and the four
progress-rigor columns for several releases, but none of them appeared in
``ActivityCreate`` / ``ActivityUpdate`` / ``ActivityResponse``. Both request
schemas declare ``extra="ignore"``, so a client that sent a planned cost got
HTTP 200 and an activity with no cost on it. The earned-value rollup then
summed ``cost_planned`` over rows that were all ``None``, reported
``budget_at_completion`` of zero and ``has_cost_data`` false, and every derived
figure on the page was wrong with nothing anywhere reporting an error.

These run against a real (async) throwaway PostgreSQL because the numeric
columns have to round-trip through the database for the wire strings to be the
ones a client would actually receive. The response is built through
``router._activity_to_response``, the hand-written constructor every activity
route goes through - validating an ORM row straight into ``ActivityResponse``
would pass while the live endpoint still returned null. The owner check is
stubbed to a no-op so the test stays on the handler path, not the JWT/RBAC
stack.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.schedule import router as schedule_router
from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session


async def _fresh_body(service: ScheduleService, session, activity_id: uuid.UUID) -> dict:
    """Re-read an activity from the database and render it as JSON.

    ``expire_all`` forces the numeric columns to come back from PostgreSQL at
    their declared scale, so the asserted strings are the ones a client sees
    rather than whatever Python object happened to be written.
    """
    session.expire_all()
    activity = await service.get_activity(activity_id)
    return schedule_router._activity_to_response(activity).model_dump(mode="json")


@pytest.mark.asyncio
async def test_created_activity_keeps_its_cost_and_rigor_fields() -> None:
    """POST an activity carrying cost and unit data, then read it back.

    Red before the fix: every one of the six values is dropped by
    ``extra="ignore"`` on the way in and absent from the response on the way
    out, so each assertion compares ``None`` against the number that was sent.
    """
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=uuid.uuid4(), name="Cost-loaded", start_date="2024-01-01")
        )
        schedule_id = schedule.id

        activity = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Foundations",
                start_date="2024-01-01",
                end_date="2024-01-31",
                progress_pct=25.0,
                cost_planned=Decimal("1000.00"),
                cost_actual=Decimal("250.00"),
                percent_complete_type="units",
                remaining_duration=15,
                budgeted_units=Decimal("100"),
                installed_units=Decimal("25"),
            )
        )
        body = await _fresh_body(service, session, activity.id)

        assert body.get("cost_planned") == "1000.0000", f"planned cost discarded: {body.get('cost_planned')!r}"
        assert body.get("cost_actual") == "250.0000", f"actual cost discarded: {body.get('cost_actual')!r}"
        assert body.get("percent_complete_type") == "units", body.get("percent_complete_type")
        assert body.get("remaining_duration") == 15, body.get("remaining_duration")
        assert body.get("budgeted_units") == "100.0000", body.get("budgeted_units")
        assert body.get("installed_units") == "25.0000", body.get("installed_units")


@pytest.mark.asyncio
async def test_patched_activity_keeps_its_cost_and_rigor_fields() -> None:
    """PATCH the same six fields onto an activity created without them.

    Red before the fix for the same reason as the create path: the update
    schema drops the keys, ``model_dump(exclude_unset=True)`` yields nothing to
    write, and the activity comes back exactly as it went in.
    """
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=uuid.uuid4(), name="Cost-loaded later", start_date="2024-01-01")
        )
        activity = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule.id,
                name="Slab",
                start_date="2024-02-01",
                end_date="2024-02-29",
            )
        )
        activity_id = activity.id

        # The activity starts with no cost on it at all - that is the state a
        # schedule imported from a Gantt tool arrives in.
        before = await _fresh_body(service, session, activity_id)
        assert before.get("cost_planned") is None

        await service.update_activity(
            activity_id,
            ActivityUpdate(
                cost_planned=Decimal("4000.50"),
                cost_actual=Decimal("1200.25"),
                percent_complete_type="duration",
                remaining_duration=7,
                budgeted_units=Decimal("80"),
                installed_units=Decimal("20"),
            ),
        )
        body = await _fresh_body(service, session, activity_id)

        assert body.get("cost_planned") == "4000.5000", f"planned cost discarded: {body.get('cost_planned')!r}"
        assert body.get("cost_actual") == "1200.2500", f"actual cost discarded: {body.get('cost_actual')!r}"
        # The column is NOT NULL with a "physical" server default, so the
        # activity above was created as physical and the PATCH moved it.
        assert body.get("percent_complete_type") == "duration", body.get("percent_complete_type")
        assert body.get("remaining_duration") == 7, body.get("remaining_duration")
        assert body.get("budgeted_units") == "80.0000", body.get("budgeted_units")
        assert body.get("installed_units") == "20.0000", body.get("installed_units")


@pytest.mark.asyncio
async def test_evm_summary_of_a_cost_loaded_schedule_is_not_zero() -> None:
    """Build a cost-loaded schedule through the API, then ask it for its EVM.

    This is the figure the community report was about. Red before the fix:
    ``budget_at_completion`` is ``Decimal("0")`` and ``has_cost_data`` is
    false, because the two activities reached the database with
    ``cost_planned = NULL`` even though the client sent the amounts. The whole
    defect is visible in the BAC assertion: 0 where 3000 was posted.
    """
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=uuid.uuid4(), name="EVM", start_date="2024-01-01")
        )
        schedule_id = schedule.id

        await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Earthworks",
                start_date="2024-01-01",
                end_date="2024-01-31",
                progress_pct=100.0,
                cost_planned=Decimal("1000"),
                cost_actual=Decimal("1100"),
            )
        )
        await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Structure",
                start_date="2024-02-01",
                end_date="2024-02-29",
                progress_pct=50.0,
                cost_planned=Decimal("2000"),
                cost_actual=Decimal("900"),
            )
        )

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            summary = await schedule_router.get_evm_summary(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
                as_of_date="2024-12-31",
            )
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

        # BAC is the plain sum of the two planned costs.
        assert summary.budget_at_completion == Decimal("3000"), (
            f"BAC of a schedule posted with 3000 of planned cost: {summary.budget_at_completion}"
        )
        assert summary.has_cost_data is True, "a schedule posted with costs reports itself as having none"
        # EV = 100% of 1000 plus 50% of 2000; AC is the sum of the actuals.
        assert summary.earned_value == Decimal("2000"), summary.earned_value
        assert summary.actual_cost == Decimal("2000"), summary.actual_cost
        # Both activities finished before the data date, so PV is the full BAC.
        assert summary.planned_value == Decimal("3000"), summary.planned_value
        assert summary.cpi == 1.0


@pytest.mark.asyncio
async def test_control_rollup_maths_was_never_the_broken_part() -> None:
    """Control. Passes on purpose both before and after the fix.

    ``compute_evm_summary`` is handed cost rows directly, bypassing the
    schemas entirely, so it never saw the defect and must not change
    behaviour now. If this one ever goes red, the fix broke the earned-value
    arithmetic rather than the plumbing that feeds it.
    """
    from app.modules.schedule.evm_math import EvmCostRow, compute_evm_summary

    summary = compute_evm_summary(
        [
            EvmCostRow(
                start_date="2024-01-01",
                end_date="2024-01-31",
                cost_planned=Decimal("1000"),
                cost_actual=Decimal("400"),
                progress_pct="50",
            )
        ],
        date(2024, 12, 31),
    )

    assert summary.has_cost_data is True
    assert summary.budget_at_completion == Decimal("1000")
    assert summary.earned_value == Decimal("500")
    assert summary.actual_cost == Decimal("400")


@pytest.mark.asyncio
async def test_control_an_uncosted_schedule_still_reports_no_cost_data() -> None:
    """Control. Passes on purpose both before and after the fix.

    Adding the fields must not invent money for a schedule that carries none:
    an activity created without costs still has ``cost_planned = NULL`` and the
    rollup still declines to report ratios.
    """
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=uuid.uuid4(), name="No cost", start_date="2024-01-01")
        )
        schedule_id = schedule.id
        await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Survey",
                start_date="2024-01-01",
                end_date="2024-01-05",
                progress_pct=50.0,
            )
        )

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            summary = await schedule_router.get_evm_summary(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
                as_of_date="2024-12-31",
            )
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

        assert summary.has_cost_data is False
        assert summary.budget_at_completion == Decimal("0")
        assert summary.spi is None
        assert summary.cpi is None

"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``POST /options/{option_id}/link/``.

A design option is a whole alternative, not a model, so it has to be able to
point at the estimate, the programme and the carbon inventory the project
already holds. These tests pin the four properties that make that safe: a
reference from another project is invisible, a linked bill prices the option
through the same rollup the generated one uses, presence in the request body
decides what changes, and a figure nobody supplied stays unanswered rather than
becoming a zero the comparison would rank on.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel
from app.modules.carbon.models import CarbonInventory, EmbodiedCarbonEntry
from app.modules.design_options.models import DesignOption
from app.modules.schedule.models import Activity, Schedule
from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_boq,
    make_option,
    make_position,
    make_project,
    make_set,
    make_user,
)


async def _make_schedule(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    activities: tuple[tuple[str, str], ...] = (("2026-03-01", "2026-03-31"),),
    start_date: str | None = None,
    end_date: str | None = None,
) -> Schedule:
    """A schedule whose span comes from its activities unless it has none."""
    schedule = Schedule(
        project_id=project_id,
        name=f"Programme {uuid.uuid4().hex[:6]}",
        start_date=start_date,
        end_date=end_date,
    )
    session.add(schedule)
    await session.flush()
    for index, (start, end) in enumerate(activities):
        session.add(
            Activity(
                schedule_id=schedule.id,
                name=f"Activity {index + 1}",
                start_date=start,
                end_date=end,
                duration_days=0,
                sort_order=index,
            )
        )
    await session.flush()
    return schedule


async def _make_inventory(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    entries: tuple[tuple[str, str], ...] = (("a1a3", "1000"),),
) -> CarbonInventory:
    """An inventory with embodied entries at the given EN 15978 stages."""
    inventory = CarbonInventory(project_id=project_id, name=f"Inventory {uuid.uuid4().hex[:6]}")
    session.add(inventory)
    await session.flush()
    for stage, carbon_kg in entries:
        session.add(
            EmbodiedCarbonEntry(
                inventory_id=inventory.id,
                description=f"{stage} line",
                quantity="1",
                unit="kg",
                factor_value_used="0",
                carbon_kg=carbon_kg,
                stage=stage,
            )
        )
    await session.flush()
    return inventory


async def _reload(session: AsyncSession, option_id: uuid.UUID) -> DesignOption:
    """Read the option back from the database, not from the identity map.

    ``update_option_fields`` is a bulk UPDATE that also patches the in-memory
    instance, so without expunging first an assertion cannot tell a row that was
    written from one that was merely synchronised.
    """
    session.expunge_all()
    return (await session.execute(select(DesignOption).where(DesignOption.id == option_id))).scalar_one()


# ── Linking a bill: the founder's "option estimates" ─────────────────────────


async def test_linking_a_bill_prices_the_option_without_any_model(session: AsyncSession) -> None:
    """An estimate the project already holds is enough to price an option."""
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="500")
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Hand-built scheme")
    boq = await make_boq(session, project.id, name="Scheme B estimate")
    await make_position(session, boq.id, quantity="10", unit_rate="250", total="2500")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["boq_id"] == str(boq.id)
    assert body["status"] == "priced"
    # Says the money came from an estimate this module does not own.
    assert body["boq_source"] == "linked"
    assert Decimal(body["direct_cost"]) == Decimal("2500")
    assert Decimal(body["cost_per_m2"]) == Decimal("5")
    assert body["currency"] == "EUR"
    # No model was ever attached: the option is estimable on its bill alone.
    assert body["bim_model_id"] is None


async def test_a_linked_bill_and_a_generated_one_report_the_same_figures(session: AsyncSession) -> None:
    """Both paths price through one rollup, so identical bills read identically.

    The generated path writes its own bill and totals it; the linked path totals
    a bill it was handed. Were the two rollups written twice they would drift on
    exactly the case that matters - the same positions - so this compares the
    linked option against the figures the shared helper produces.
    """
    from app.modules.design_options.service import DesignOptionsService
    from app.modules.projects.models import Project

    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="200")
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Linked")
    boq = await make_boq(session, project.id)
    await make_position(session, boq.id, quantity="4", unit_rate="125", total="500")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})
    assert res.status_code == 200, res.text

    reloaded = await _reload(session, option.id)
    project_row = await session.get(Project, project.id)
    priced = await DesignOptionsService(session)._price_from_boq(reloaded, boq.id, project_row)

    assert Decimal(reloaded.direct_cost) == priced.direct
    assert Decimal(reloaded.grand_total) == priced.grand
    assert Decimal(reloaded.cost_per_m2) == priced.cost_per_m2
    assert reloaded.currency == priced.currency


@pytest.mark.tenant_isolation
async def test_a_bill_from_another_project_is_invisible(session: AsyncSession) -> None:
    """A foreign estimate reads 404, so option ids cannot probe other tenants."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_owner = await make_user(session)
    other_project = await make_project(session, other_owner.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    foreign_boq = await make_boq(session, other_project.id, name="Someone else's estimate")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(foreign_boq.id)})

    assert res.status_code == 404
    assert (await _reload(session, option.id)).boq_id is None


@pytest.mark.tenant_isolation
async def test_an_unknown_bill_reads_the_same_as_a_foreign_one(session: AsyncSession) -> None:
    """404 either way: the response never distinguishes absent from forbidden."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(uuid.uuid4())})

    assert res.status_code == 404


# ── Linking a programme ──────────────────────────────────────────────────────


async def test_linking_a_schedule_reads_the_span_off_its_activities(session: AsyncSession) -> None:
    """Duration spans the earliest start to the latest finish, both days counted."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    schedule = await _make_schedule(
        session,
        project.id,
        activities=(("2026-03-01", "2026-03-10"), ("2026-03-05", "2026-03-20")),
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"schedule_id": str(schedule.id)})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schedule_id"] == str(schedule.id)
    # 1 March to 20 March inclusive of both end days.
    assert Decimal(body["duration_days"]) == Decimal("20")
    assert body["finish_date"] == "2026-03-20"


async def test_a_schedule_with_no_activities_falls_back_to_its_own_dates(session: AsyncSession) -> None:
    """An imported shell schedule still dates the option from its header."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    schedule = await _make_schedule(
        session,
        project.id,
        activities=(),
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"schedule_id": str(schedule.id)})

    assert res.status_code == 200, res.text
    assert Decimal(res.json()["duration_days"]) == Decimal("31")
    assert res.json()["finish_date"] == "2026-01-31"


@pytest.mark.tenant_isolation
async def test_a_schedule_from_another_project_is_invisible(session: AsyncSession) -> None:
    """The programme reference is guarded exactly like the estimate one."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_owner = await make_user(session)
    other_project = await make_project(session, other_owner.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    foreign_schedule = await _make_schedule(session, other_project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/link/",
            json={"schedule_id": str(foreign_schedule.id)},
        )

    assert res.status_code == 404
    assert (await _reload(session, option.id)).schedule_id is None


# ── Linking a carbon inventory ───────────────────────────────────────────────


async def test_linking_an_inventory_records_a1_to_a5_and_the_area_intensity(session: AsyncSession) -> None:
    """Cradle to practical completion is the figure a design choice commits."""
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="100")
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    inventory = await _make_inventory(
        session,
        project.id,
        # A1-A3 + A4 + A5 add up; the C stage is deliberately outside the figure
        # a scheme choice commits, so it must not appear in the total.
        entries=(("a1a3", "8000"), ("a4", "1500"), ("a5", "500"), ("c1", "9000")),
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/link/",
            json={"carbon_inventory_id": str(inventory.id)},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["carbon_inventory_id"] == str(inventory.id)
    assert Decimal(body["embodied_carbon_kg"]) == Decimal("10000")
    assert Decimal(body["carbon_per_m2"]) == Decimal("100")


@pytest.mark.tenant_isolation
async def test_an_inventory_from_another_project_is_invisible(session: AsyncSession) -> None:
    """The carbon reference is guarded exactly like the other two."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_owner = await make_user(session)
    other_project = await make_project(session, other_owner.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    foreign_inventory = await _make_inventory(session, other_project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/link/",
            json={"carbon_inventory_id": str(foreign_inventory.id)},
        )

    assert res.status_code == 404
    assert (await _reload(session, option.id)).carbon_inventory_id is None


# ── Presence, not value, decides what changes ────────────────────────────────


async def test_an_omitted_field_leaves_its_reference_alone(session: AsyncSession) -> None:
    """A partial update must not silently drop a reference it never mentioned."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    schedule = await _make_schedule(session, project.id)
    inventory = await _make_inventory(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        first = await client.post(
            f"{API_PREFIX}/options/{option.id}/link/",
            json={"schedule_id": str(schedule.id)},
        )
        assert first.status_code == 200, first.text
        second = await client.post(
            f"{API_PREFIX}/options/{option.id}/link/",
            json={"carbon_inventory_id": str(inventory.id)},
        )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["schedule_id"] == str(schedule.id)
    assert body["carbon_inventory_id"] == str(inventory.id)


async def test_an_explicit_null_clears_the_reference_and_its_figures(session: AsyncSession) -> None:
    """Unlinking leaves nothing behind that would still read as an answer."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    schedule = await _make_schedule(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"schedule_id": str(schedule.id)})
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"schedule_id": None})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schedule_id"] is None
    assert Decimal(body["duration_days"]) == Decimal("0")
    assert body["finish_date"] == ""


async def test_unlinking_a_bill_also_unprices_the_option(session: AsyncSession) -> None:
    """Totals sourced from a bill must not outlive the bill they came from."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    boq = await make_boq(session, project.id)
    await make_position(session, boq.id, quantity="2", unit_rate="50", total="100")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": None})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["boq_id"] is None
    assert body["boq_source"] == ""
    assert body["status"] == "draft"
    assert Decimal(body["grand_total"]) == Decimal("0")


async def test_an_empty_body_is_rejected_rather_than_silently_doing_nothing(session: AsyncSession) -> None:
    """A request that asks for nothing is a mistake, not a successful no-op."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={})

    assert res.status_code == 400


@pytest.mark.tenant_isolation
async def test_linking_on_another_users_option_returns_404(session: AsyncSession) -> None:
    """The route is gated on the option's project like every other handler here."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set)
    boq = await make_boq(session, project.id)
    intruder = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=intruder.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})

    assert res.status_code == 404


# ── A linked bill is not this module's to overwrite ──────────────────────────


async def test_generating_over_a_linked_bill_is_refused(session: AsyncSession) -> None:
    """The rule lives in the service, because the route to it is ordinary.

    Link an estimate, then attach a model to the same option - both are things a
    user is meant to do. Generate would then apply matched positions into
    ``boq_id``, which is a bill this module did not write and other parts of the
    project may be reading as the tender or the budget. Guarding this in the
    button alone would leave it open, since attaching a model puts the option
    back into the state whose button offers generation.
    """
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="500")
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Linked scheme")
    boq = await make_boq(session, project.id, name="The project's own estimate")
    await make_position(session, boq.id, quantity="10", unit_rate="250", total="2500")
    model = BIMModel(
        project_id=project.id,
        name="Scheme model",
        model_format="ifc",
        element_count=42,
        status="ready",
    )
    session.add(model)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        linked = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})
        assert linked.status_code == 200, linked.text
        attached = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )
        assert attached.status_code == 200, attached.text
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 400, res.text
    assert "linked" in res.json()["detail"].lower()

    stored = await _reload(session, option.id)
    # Still pointed at the same bill, still saying where the money came from.
    assert stored.boq_id == boq.id
    assert stored.boq_source == "linked"


async def test_saving_the_same_bill_again_refreshes_it_without_relabelling(session: AsyncSession) -> None:
    """Re-sending an unchanged reference is how a stale figure is refreshed.

    The dialog sends all three references on every save, so the common case is a
    bill the option already carries. That must re-read the bill, and it must not
    turn a bill this module generated into a linked one - which would hand the
    option to the refusal above and block a regeneration it is entitled to.
    """
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="100")
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    await make_position(session, boq.id, quantity="2", unit_rate="500", total="1000")
    option = await make_option(
        session,
        option_set,
        name="Generated scheme",
        boq_id=boq.id,
        boq_source="generated",
        status="priced",
        # A figure that has gone stale since the bill was last read.
        direct_cost="1",
        grand_total="1",
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(boq.id)})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["boq_source"] == "generated"
    assert Decimal(body["direct_cost"]) == Decimal("1000")
    assert Decimal(body["cost_per_m2"]) == Decimal("10")


async def test_linking_a_different_bill_over_a_generated_one_says_it_is_linked(session: AsyncSession) -> None:
    """Provenance follows the bill, not the option's history.

    The refresh above keeps "generated" when the same bill comes back. The
    opposite case has to move: pointing an option at a bill somebody else built
    makes that bill linked, whatever the option was priced from before. Getting
    this wrong would label a foreign estimate as this module's own work and let
    a regeneration overwrite it.
    """
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="100")
    option_set = await make_set(session, project.id)
    generated = await make_boq(session, project.id, name="Generated here")
    await make_position(session, generated.id, quantity="1", unit_rate="100", total="100")
    other = await make_boq(session, project.id, name="The project's own estimate")
    await make_position(session, other.id, quantity="1", unit_rate="900", total="900")
    option = await make_option(
        session,
        option_set,
        name="Scheme",
        boq_id=generated.id,
        boq_source="generated",
        status="priced",
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/link/", json={"boq_id": str(other.id)})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["boq_id"] == str(other.id)
    assert body["boq_source"] == "linked"
    assert Decimal(body["direct_cost"]) == Decimal("900")

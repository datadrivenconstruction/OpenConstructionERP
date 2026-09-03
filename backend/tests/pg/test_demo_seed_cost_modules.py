# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The cost-side demo seeds must fill their screens, and fill them only once.

Allowances, the basis of estimate and the value dashboard all shipped with no
demo data at all, so every demo project photographed as an empty state. The
three seeders that fix that share the ways a demo seed goes wrong without
raising anything:

* the register is populated but incoherent - a drawdown larger than the
  allowance it draws against, a document whose coverage does not match the
  estimate it was derived from. Nobody reading a screenshot checks the
  arithmetic, and everybody reading the register does;
* the second boot doubles it, because idempotency in this codebase is per loop
  rather than per seeder;
* the rows exist but the reader downstream cannot use them. The value figures
  are aggregated by the pure engines, so rows that land outside the project
  scope, or on one instant, aggregate to a headline of zero or to a single bar
  with no error anywhere;
* the seed runs on a project that is not a demo project. The boot enrichment
  hands every project in the database to every seeder, so on a real installation
  a customer's own project is offered to all three. Being idempotent does not
  help there - it is the first run that does the damage.

The third is asserted through the value service's own aggregation rather than by
restating its ``WHERE`` clause, so a change to what the dashboard counts fails
here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.audit_log import ActivityLog
from app.modules.allowances.models import Allowance, AllowanceDrawdown
from app.modules.allowances.seed import seed_allowances_demo
from app.modules.boq.models import BOQ, Position
from app.modules.estimate_basis.models import EstimateBasis
from app.modules.estimate_basis.seed import seed_estimate_basis_demo
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.value.seed import seed_value_demo

pytestmark = pytest.mark.asyncio

# Priced line items covering four trades, so the derivation has a real coverage
# picture to draft inclusions from rather than the standard boilerplate alone.
_POSITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("01.10", "Reinforced concrete foundations", "m3", "180000"),
    ("01.20", "Structural steelwork to frame", "t", "240000"),
    ("01.30", "Masonry to external walls", "m2", "96000"),
    ("01.40", "Roof covering and insulation", "m2", "72000"),
    ("02.10", "Electrical installation to floors", "item", "148000"),
    ("02.20", "Mechanical ventilation plant", "item", "132000"),
    ("02.30", "Sanitary installation and pipework", "item", "58000"),
    ("03.10", "External works and paving", "m2", "44000"),
    ("03.20", "Drainage to site boundary", "m", "26000"),
    ("04.10", "Loose furniture and equipment", "item", "18000"),
)

# What the fixture's positions add up to; the register is scaled off this.
_ESTIMATE_TOTAL = sum(Decimal(row[3]) for row in _POSITIONS)


async def _make_project(session, name: str, *, currency: str = "EUR", demo: bool = True) -> uuid.UUID:
    """Build the minimum a project needs before these three seeders can run.

    The owner is an admin because the value seeder tunes the minute factors for
    the estate's admin accounts, and a project with no priced BOQ is a project
    the basis-of-estimate seeder correctly refuses.

    ``demo`` stamps the estate marker the seeders gate on. The marker is
    ``demo_id`` alone, deliberately: the ten demo templates write ``is_demo``
    beside it but the flagship reference project does not, so the fixture
    reproduces the thinner of the two shapes. Passing ``demo=False`` builds the
    project a customer would have - identical in every other respect, which is
    exactly why emptiness cannot be the gate.
    """
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Cost-module seed fixture",
            currency=currency,
            status="active",
            owner_id=owner_id,
            metadata_={"demo_id": f"fixture-{name.lower()}"} if demo else {},
        )
    )
    await session.flush()

    boq_id = uuid.uuid4()
    session.add(
        BOQ(
            id=boq_id,
            project_id=project_id,
            name="Fixture BOQ",
            description="",
            status="draft",
            base_date="2026-01-15",
            metadata_={},
        )
    )
    await session.flush()
    for code, description, unit, total in _POSITIONS:
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=code,
                reference_code=code,
                description=description,
                unit=unit,
                quantity="1",
                unit_rate=total,
                total=total,
                metadata_={},
            )
        )
    await session.flush()
    return project_id


async def _allowances(session, project_id: uuid.UUID) -> list[Allowance]:
    rows = await session.execute(
        select(Allowance).where(Allowance.project_id == project_id).order_by(Allowance.allowance_type),
    )
    return list(rows.scalars().all())


async def _drawn(session, allowance_id: uuid.UUID) -> Decimal:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(AllowanceDrawdown.amount), 0)).where(
                AllowanceDrawdown.allowance_id == allowance_id,
            ),
        )
    ).scalar_one()
    return Decimal(str(total))


async def _documents(session, project_id: uuid.UUID) -> list[EstimateBasis]:
    rows = await session.execute(
        select(EstimateBasis).where(EstimateBasis.project_id == project_id).order_by(EstimateBasis.created_at.desc()),
    )
    return list(rows.scalars().all())


# ── The gate all three share ────────────────────────────────────────────────


async def test_none_of_the_three_touch_a_project_outside_the_demo_estate(pg_session) -> None:
    """A customer's own project must come out of all three seeders untouched.

    This is the one that is not cosmetic. The boot backfill selects every
    project row in the database, and it re-runs on every version upgrade, so a
    real installation hands its real projects to every seeder here. A customer
    project that legitimately has no allowances, no basis of estimate and no
    assisted work is indistinguishable from an unseeded demo one by emptiness
    alone - which is why emptiness is the idempotency guard and the estate
    marker is the gate.

    The fixture below is a full project with a priced BOQ, so nothing except the
    marker is standing between it and three seeders' worth of invented data.
    """
    from app.modules.value.models import TimeSavedFactor

    async def _factor_count() -> int:
        return (await pg_session.execute(select(func.count()).select_from(TimeSavedFactor))).scalar_one()

    project_id = await _make_project(pg_session, "Customer", demo=False)
    factors_before = await _factor_count()

    allowances = await seed_allowances_demo(pg_session, [project_id])
    basis = await seed_estimate_basis_demo(pg_session, [project_id])
    value = await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()

    assert allowances["allowances"] == 0, f"{allowances['allowances']} invented allowance(s) written to a real project"
    assert basis["documents"] == 0, f"{basis['documents']} invented basis document(s) written to a real project"
    assert value["activity_rows"] == 0, f"{value['activity_rows']} invented activity row(s) written to a real project"
    assert value["tuned_factors"] == 0, "a real installation's minute factors were re-tuned"

    assert not await _allowances(pg_session, project_id)
    assert not await _documents(pg_session, project_id)
    activity = (
        await pg_session.execute(
            select(func.count()).select_from(ActivityLog).where(ActivityLog.parent_entity_id == str(project_id)),
        )
    ).scalar_one()
    assert activity == 0, f"{activity} row(s) landed in the customer's activity log"
    assert await _factor_count() == factors_before, "the installation's minute factors were written to"


# ── Allowances ──────────────────────────────────────────────────────────────


async def test_the_allowance_register_carries_all_three_kinds(pg_session) -> None:
    """A seeded project shows a register, not a row: every kind, priced off its estimate."""
    project_id = await _make_project(pg_session, "Quayside")

    counts = await seed_allowances_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["allowances"] >= 8, f"only {counts['allowances']} allowance(s) seeded"
    assert counts["drawdowns"] >= 5, f"only {counts['drawdowns']} drawdown(s) seeded"

    rows = await _allowances(pg_session, project_id)
    assert len(rows) == counts["allowances"]
    assert {row.allowance_type for row in rows} == {"provisional_sum", "pc_sum", "contingency"}, (
        f"the register only carries {sorted({r.allowance_type for r in rows})}"
    )
    for row in rows:
        assert row.currency == "EUR", f"{row.label!r} is denominated in {row.currency!r}, not the project's currency"
        assert Decimal(str(row.held_amount)) > 0, f"{row.label!r} holds nothing"
        assert row.label.strip(), "an allowance was written with no label"

    # The register has to be in proportion to the estimate it sits beside: an
    # estimate of about a million cannot carry allowances worth ten.
    held = sum(Decimal(str(row.held_amount)) for row in rows)
    assert held < _ESTIMATE_TOTAL / 2, f"the register holds {held} against an estimate of {_ESTIMATE_TOTAL}"
    assert held > _ESTIMATE_TOTAL / 100, f"the register holds only {held} against an estimate of {_ESTIMATE_TOTAL}"


async def test_only_one_allowance_per_project_is_over_drawn(pg_session) -> None:
    """The coherence rule the screen is read against.

    Remaining is held minus drawn, and a reader adding the column up must not
    catch us out. Every allowance is drawn within a small margin of what it
    holds, exactly one deliberately runs past it (which is the advisory state the
    module shows an "Over-drawn" badge for, so a register where it never fires
    teaches half the feature), and at least one is settled to exactly zero
    remaining rather than to a rounding residue.
    """
    project_id = await _make_project(pg_session, "Foundry")

    await seed_allowances_demo(pg_session, [project_id])
    await pg_session.flush()

    rows = await _allowances(pg_session, project_id)
    assert rows, "no allowances seeded at all"

    overdrawn: list[str] = []
    settled = 0
    untouched = 0
    for row in rows:
        held = Decimal(str(row.held_amount))
        drawn = await _drawn(pg_session, row.id)
        assert drawn >= 0, f"{row.label!r} carries a negative drawdown total"
        assert drawn <= held * Decimal("1.15"), f"{row.label!r} drew {drawn} against a held amount of {held}"
        if drawn > held:
            overdrawn.append(row.label)
        elif drawn == held:
            settled += 1
        elif drawn == 0:
            untouched += 1

    assert len(overdrawn) == 1, f"expected exactly one over-drawn allowance, saw {overdrawn}"
    assert settled >= 1, (
        "no allowance is settled to exactly zero remaining, so the column never lands on a round figure"
    )
    assert untouched >= 1, "every allowance has been drawn against, which is not what a live register looks like"

    for drawdown in (await pg_session.execute(select(AllowanceDrawdown))).scalars().all():
        assert Decimal(str(drawdown.amount)) > 0, "a drawdown of zero was written"
        assert (drawdown.note or "").strip(), "a drawdown was written with no reason"


async def test_a_second_allowances_pass_adds_no_rows(pg_session) -> None:
    """Running the allowances seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Sawmill")

    await seed_allowances_demo(pg_session, [project_id])
    await pg_session.flush()
    first = await _allowances(pg_session, project_id)
    assert first

    second = await seed_allowances_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["allowances"] == 0, f"the second pass wrote {second['allowances']} allowance(s) again"
    assert len(await _allowances(pg_session, project_id)) == len(first)


async def test_two_projects_do_not_get_the_same_register(pg_session) -> None:
    """A reader flipping between demo projects must not see the same allowances twice.

    Six projects, not two. The register size grows with the project's position in
    the call, so the fifth project is the first one whose requested size runs past
    the catalogue - and a register that asks for the whole catalogue has stopped
    sampling it. Below six that case is never reached, and the labels are checked
    on their own as well as with the money, because two registers carrying the
    same lines at different amounts is the shape that failure takes.
    """
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    projects = [await _make_project(pg_session, name) for name in names]

    await seed_allowances_demo(pg_session, projects)
    await pg_session.flush()

    seen: dict[tuple, str] = {}
    labels_seen: dict[tuple, str] = {}
    for name, project_id in zip(names, projects, strict=True):
        rows = await _allowances(pg_session, project_id)
        assert rows, f"{name} got no register at all"
        shape = tuple(sorted((row.label, str(row.held_amount)) for row in rows))
        clash = seen.get(shape)
        assert clash is None, f"{name} and {clash} rendered the same register"
        seen[shape] = name

        labels = tuple(sorted(row.label for row in rows))
        label_clash = labels_seen.get(labels)
        assert label_clash is None, (
            f"{name} and {label_clash} list exactly the same allowances and differ only in the money"
        )
        labels_seen[labels] = name


# ── Basis of estimate ───────────────────────────────────────────────────────


async def test_the_basis_history_reads_as_a_document_somebody_owns(pg_session) -> None:
    """The newest document is an edited draft behind an issued history."""
    project_id = await _make_project(pg_session, "Brewery")

    counts = await seed_estimate_basis_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["documents"] >= 2, f"only {counts['documents']} document(s) seeded"
    docs = await _documents(pg_session, project_id)
    assert len(docs) == counts["documents"]

    drafts = [doc for doc in docs if doc.status == "draft"]
    assert len(drafts) == 1, f"expected exactly one working draft, saw {[d.status for d in docs]}"
    assert docs[0].status == "draft", "the working draft is not the newest document, so the screen opens on an old one"
    assert all(doc.status == "final" for doc in docs[1:]), "an older version was left unissued"

    current = docs[0]
    lines = (current.inclusions or []) + (current.exclusions or []) + (current.assumptions or [])
    # No allowances register on this fixture, so this is the floor: the trades
    # the estimate prices, the standard exclusions and the standard assumptions.
    # The register adds a line per allowance on top (asserted separately).
    assert len(lines) >= 18, f"the draft carries only {len(lines)} qualification line(s)"
    assert all(str(item.get("text", "")).strip() for item in lines), "a qualification line was written with no text"

    disabled = [item for item in (current.exclusions or []) if not item.get("enabled", True)]
    assert len(disabled) == 1, "no exclusion was switched off, so the toggle the editor offers is never shown"
    manual = [item for item in (current.assumptions or []) if item.get("source") == "manual"]
    assert len(manual) == 1, "no hand-typed assumption, so every line on the screen reads as generated"
    assert (current.notes or "").strip(), "the draft carries no estimator note"

    # An issued version generated today would contradict the history it claims.
    stamps = sorted(str(doc.generated_at or "") for doc in docs)
    assert len(set(stamps)) == len(docs), "two versions were generated at the same instant"
    assert stamps[0] < datetime.now(UTC).isoformat(), "the oldest version is stamped in the future"


async def test_the_basis_quotes_the_projects_own_allowances(pg_session) -> None:
    """The document is derived from this project, not drafted from a template.

    Every allowance in the register has to appear as its own assumption line -
    that is the ordering dependency (allowances before the basis) made visible -
    and the coverage snapshot has to count the estimate's real line items.
    """
    project_id = await _make_project(pg_session, "Granary")

    await seed_allowances_demo(pg_session, [project_id])
    await pg_session.flush()
    await seed_estimate_basis_demo(pg_session, [project_id])
    await pg_session.flush()

    allowances = await _allowances(pg_session, project_id)
    assert allowances, "the fixture seeded no allowances, so this test proves nothing"

    current = (await _documents(pg_session, project_id))[0]
    lines = (current.inclusions or []) + (current.exclusions or []) + (current.assumptions or [])
    assert len(lines) >= 28, f"the draft carries only {len(lines)} line(s) with a register beside it"

    assumption_ids = {str(item.get("id", "")) for item in (current.assumptions or [])}
    missing = [row.label for row in allowances if f"asm-allowance-{row.id}" not in assumption_ids]
    assert not missing, f"the basis does not name {len(missing)} of the project's allowances: {missing[:3]}"
    assert "asm-contingency" in assumption_ids, "the basis says nothing about whether contingency is included"

    coverage = current.coverage or {}
    assert coverage.get("total_positions") == len(_POSITIONS), (
        f"coverage counted {coverage.get('total_positions')} positions against {len(_POSITIONS)} priced line items"
    )
    assert coverage.get("present_trades"), "the coverage snapshot found no trade in a priced estimate"


async def test_projects_do_not_all_carry_the_same_version_history(pg_session) -> None:
    """The length of the history varies by position, and only position 0 was ever tested.

    Every single-project test seeds at position 0, so the shorter history the
    rotation hands the next project is never reached by them.
    """
    projects = [await _make_project(pg_session, name) for name in ("Malthouse", "Ropewalk", "Limekiln")]

    await seed_estimate_basis_demo(pg_session, projects)
    await pg_session.flush()

    lengths = [len(await _documents(pg_session, pid)) for pid in projects]
    assert all(count >= 2 for count in lengths), f"a project got no history at all: {lengths}"
    assert len(set(lengths)) > 1, f"every project carries the same {lengths[0]}-version history"
    for project_id in projects:
        docs = await _documents(pg_session, project_id)
        assert [doc.status for doc in docs].count("draft") == 1, "a project has more than one working draft"


async def test_a_second_basis_pass_adds_no_documents(pg_session) -> None:
    """Running the basis seed twice must not double the version history."""
    project_id = await _make_project(pg_session, "Tannery")

    await seed_estimate_basis_demo(pg_session, [project_id])
    await pg_session.flush()
    first = len(await _documents(pg_session, project_id))
    assert first > 0

    second = await seed_estimate_basis_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["documents"] == 0, f"the second pass wrote {second['documents']} document(s) again"
    assert len(await _documents(pg_session, project_id)) == first


async def test_an_unpriced_project_gets_no_basis(pg_session) -> None:
    """A project with no priced estimate must not get a document of boilerplate.

    Carries the demo marker, so the refusal has to come from the priced-position
    gate. Without it the project would be turned away one gate earlier and this
    would pass without testing anything.
    """
    owner_id = uuid.uuid4()
    pg_session.add(
        User(
            id=owner_id,
            email="bare@example.test",
            hashed_password="x",
            full_name="Bare Owner",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await pg_session.flush()
    project_id = uuid.uuid4()
    pg_session.add(
        Project(
            id=project_id,
            name="Bare",
            description="",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={"demo_id": "fixture-bare"},
        )
    )
    await pg_session.flush()

    counts = await seed_estimate_basis_demo(pg_session, [project_id])
    await pg_session.flush()
    assert counts["documents"] == 0, "a project with no priced estimate was given a basis of estimate anyway"


# ── Value realized ──────────────────────────────────────────────────────────


async def test_the_value_dashboard_reports_real_hours(pg_session) -> None:
    """The seeded activity has to arrive at the engine that reports it.

    Rows that land outside the project scope, or all on one instant, aggregate to
    a headline of zero or to a single bar and nothing raises, so the check runs
    through the value service's own aggregation rather than restating its query.
    """
    from app.modules.value.service import build_hours_saved, build_value_summary

    project_id = await _make_project(pg_session, "Wharf")

    counts = await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["activity_rows"] >= 40, f"only {counts['activity_rows']} activity row(s) seeded"
    assert 0 < counts["credited_rows"] < counts["activity_rows"], (
        "every seeded row credits saved time, so the confidence sample is the raw row count rather than an honest one"
    )

    summary = await build_value_summary(pg_session, project_id)
    assert Decimal(summary.estimated_hours_saved) > 0, "the headline hours figure is still zero"
    assert summary.activity_count == counts["activity_rows"], (
        f"the dashboard sees {summary.activity_count} rows against {counts['activity_rows']} seeded"
    )
    assert 0 < summary.hours_sample < summary.activity_count, (
        f"hours sample {summary.hours_sample} against activity count {summary.activity_count}"
    )

    buckets, total, event_count = await build_hours_saved(pg_session, project_id, by="feature")
    assert len(buckets) >= 4, f"the breakdown shows only {len(buckets)} feature(s)"
    assert total > 0 and event_count == counts["activity_rows"]

    weekly, _total, _events = await build_hours_saved(pg_session, project_id, by="period", period="week")
    assert len(weekly) >= 8, f"the weekly series has only {len(weekly)} bucket(s), so the chart is a single bar"


async def test_the_adoption_benchmark_gets_a_spread_to_compare(pg_session) -> None:
    """Projects must not all book the same volume, or the benchmark has no cohorts.

    The benchmark scores adoption from activity density and splits the portfolio
    into a high and a low cohort. Identical volumes across the estate leave it
    with nothing to contrast, and it reports that as low confidence rather than
    as an error.
    """
    projects = [await _make_project(pg_session, name) for name in ("Slipway", "Drydock", "Capstan", "Windlass")]

    await seed_value_demo(pg_session, projects)
    await pg_session.flush()

    volumes = [
        (
            await pg_session.execute(
                select(func.count()).select_from(ActivityLog).where(ActivityLog.parent_entity_id == str(pid)),
            )
        ).scalar_one()
        for pid in projects
    ]
    assert all(count > 0 for count in volumes), f"a project booked no assisted work: {volumes}"
    assert len(set(volumes)) == len(volumes), f"two projects booked the same volume: {volumes}"


async def test_no_seeded_activity_is_dated_in_the_future(pg_session) -> None:
    """A register that books work tomorrow reads as fabricated, because it is."""
    project_id = await _make_project(pg_session, "Kiln")

    await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()

    latest = (
        await pg_session.execute(
            select(func.max(ActivityLog.created_at)).where(ActivityLog.parent_entity_id == str(project_id)),
        )
    ).scalar_one()
    assert latest is not None, "no activity was seeded at all"
    stamped = latest if latest.tzinfo is not None else latest.replace(tzinfo=UTC)
    assert stamped <= datetime.now(UTC), f"the newest seeded row is stamped {stamped}"


async def test_a_second_value_pass_adds_no_activity(pg_session) -> None:
    """Running the value seed twice must not double the chart."""
    project_id = await _make_project(pg_session, "Boatyard")

    await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()
    first = (
        await pg_session.execute(
            select(func.count()).select_from(ActivityLog).where(ActivityLog.parent_entity_id == str(project_id)),
        )
    ).scalar_one()
    assert first > 0

    second = await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["activity_rows"] == 0, f"the second pass wrote {second['activity_rows']} row(s) again"
    after = (
        await pg_session.execute(
            select(func.count()).select_from(ActivityLog).where(ActivityLog.parent_entity_id == str(project_id)),
        )
    ).scalar_one()
    assert after == first


async def test_a_project_that_has_been_worked_on_gets_no_seeded_activity(pg_session) -> None:
    """A live project must be declined, not merely de-duplicated.

    The boot enrichment hands every project in the database to this seeder,
    including a customer's own on a real installation, and the activity log is
    the contemporaneous record a dispute is later reconstructed from. Idempotency
    alone would not stop that: a marker check finds no marker on a live project
    and seeds it. So the gate is any activity at all, and one real row is enough
    to close it.
    """
    project_id = await _make_project(pg_session, "Quayside")
    pg_session.add(
        ActivityLog(
            tenant_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            entity_type="rfi",
            entity_id=str(uuid.uuid4()),
            action="rfi_answered",
            module="rfi",
            parent_entity_type="project",
            parent_entity_id=str(project_id),
            metadata_={},
        )
    )
    await pg_session.flush()

    counts = await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["activity_rows"] == 0, (
        f"{counts['activity_rows']} fabricated row(s) were written into a project that already has a record of work"
    )
    remaining = (
        await pg_session.execute(
            select(func.count()).select_from(ActivityLog).where(ActivityLog.parent_entity_id == str(project_id)),
        )
    ).scalar_one()
    assert remaining == 1, f"the project's log went from 1 row to {remaining}"


async def test_the_admin_factors_panel_shows_something_tuned(pg_session) -> None:
    """The module's own table gets the rows that make the panel worth opening.

    An override equal to the seed default is deleted rather than stored, so a
    seeder that writes the defaults back writes nothing at all.
    """
    from app.modules.value.time_factors_service import list_factors

    project_id = await _make_project(pg_session, "Cooperage")
    owner_id = (await pg_session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one()

    counts = await seed_value_demo(pg_session, [project_id])
    await pg_session.flush()
    assert counts["tuned_factors"] >= 3, f"only {counts['tuned_factors']} factor(s) tuned"

    rows = await list_factors(pg_session, str(owner_id))
    tuned = [row for row in rows if row.is_override]
    assert len(tuned) >= 3, "the factors panel shows nothing tuned against the inherited defaults"
    for row in tuned:
        assert row.default_minutes is not None
        assert row.minutes != row.default_minutes, f"{row.module}/{row.action} was 'tuned' to its own default"

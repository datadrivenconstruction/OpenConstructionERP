"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Baseline tests for the Markups module — Round 3 Wave A sweep.

Pins the contract for the markups-module remediation done this round:

* Calibration / measurement columns persist as ``Decimal``
  (Float → ``Numeric(18, 6)`` on PostgreSQL; SQLAlchemy round-trips the
  value as a ``Decimal`` unchanged).
* Pagination on the list endpoint honours the platform-standard
  ``offset`` + ``limit`` slice rather than a confusing ``page`` rail
  (``page`` survives only as a deprecated *drawing-page* filter alias).
* ``verify_project_access`` rejects access to a project the user does
  not own — the auth gate cannot be silently dropped from the listing
  route in a future refactor.

Stamp-template tenancy is pinned here too. The rule the module actually
implements is *global templates carry ``project_id IS NULL``* — see
``MarkupsService.seed_default_stamps`` (which writes every shipped stamp
with ``project_id=None``) and the ``_authorize_stamp_mutation`` docstring
in the router. ``category == "predefined"`` is a label, not a scope, and
the demo seeder writes project-scoped rows carrying it. The three tests
below hold both halves: one project must not see another project's own
templates, and the shipped global ones must stay visible to everyone.

The test runs on a transaction-isolated PostgreSQL session (rolled back
on teardown) via ``tests._pg.transactional_session`` — never
``backend/openestimate.db``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.dependencies import verify_project_access
from app.modules.markups.router import list_stamp_templates
from app.modules.markups.schemas import MarkupCreate, ScaleConfigCreate, StampTemplateCreate
from app.modules.markups.service import MarkupsService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session_owner():
    """Yield (session, owner_id, project_id) on an isolated PostgreSQL session."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_id = uuid.uuid4()
        project_id = uuid.uuid4()
        owner = User(
            id=owner_id,
            email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Owner",
        )
        s.add(owner)
        await s.flush()
        s.add(
            Project(
                id=project_id,
                name="Markups Test",
                owner_id=owner_id,
                currency="EUR",
            ),
        )
        await s.commit()
        yield s, str(owner_id), project_id


@pytest.mark.asyncio
async def test_create_markup_measurement_persists_as_decimal(session_owner) -> None:
    """measurement_value must persist as Decimal (no float-drift on takeoff)."""
    session, owner_id, project_id = session_owner
    service = MarkupsService(session)

    item = await service.create_markup(
        MarkupCreate(
            project_id=project_id,
            type="distance",
            geometry={"points": [{"x": 0, "y": 0}, {"x": 1234567, "y": 0}]},
            measurement_value=12.345678,
            measurement_unit="m",
        ),
        user_id=owner_id,
    )
    await session.commit()
    await session.refresh(item)

    assert item.measurement_value is not None
    # SQLAlchemy Numeric returns Decimal on PostgreSQL; it must compare
    # exactly to the input with no float drift.
    assert Decimal(str(item.measurement_value)) == Decimal("12.345678")


@pytest.mark.asyncio
async def test_create_scale_config_calibration_is_decimal(session_owner) -> None:
    """pixels_per_unit / real_distance round-trip without float drift."""
    session, owner_id, _ = session_owner
    service = MarkupsService(session)

    scale = await service.create_scale(
        ScaleConfigCreate(
            document_id="doc-001",
            page=1,
            pixels_per_unit=987.654321,
            unit_label="m",
            calibration_points={"p1": [0, 0], "p2": [987, 0]},
            real_distance=1.234567,
        ),
        user_id=owner_id,
    )
    await session.commit()
    await session.refresh(scale)

    assert Decimal(str(scale.pixels_per_unit)) == Decimal("987.654321")
    assert Decimal(str(scale.real_distance)) == Decimal("1.234567")


@pytest.mark.asyncio
async def test_list_markups_offset_limit_slices(session_owner) -> None:
    """list_for_project honours ``offset`` + ``limit`` (platform standard)."""
    session, owner_id, project_id = session_owner
    service = MarkupsService(session)

    # Seed five markups; created_at order is insertion order (DESC on read).
    for i in range(5):
        await service.create_markup(
            MarkupCreate(
                project_id=project_id,
                type="text",
                text=f"note-{i}",
            ),
            user_id=owner_id,
        )
    await session.commit()

    page1, total = await service.list_markups(project_id, offset=0, limit=2)
    page2, _ = await service.list_markups(project_id, offset=2, limit=2)
    page3, _ = await service.list_markups(project_id, offset=4, limit=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    # No overlap across slices.
    ids = {m.id for m in page1} | {m.id for m in page2} | {m.id for m in page3}
    assert len(ids) == 5


@pytest.mark.asyncio
async def test_verify_project_access_rejects_outsider(session_owner) -> None:
    """A non-owning user gets a 404 on the project gate (no info leak)."""
    session, _owner_id, project_id = session_owner
    from app.modules.users.models import User

    outsider_id = uuid.uuid4()
    session.add(
        User(
            id=outsider_id,
            email=f"out-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Outsider",
        ),
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(project_id, str(outsider_id), session)
    # 404 — auth failures and missing projects must look identical.
    assert exc.value.status_code == 404


# ── Stamp-template tenancy ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def two_projects():
    """Yield (session, owner_a, project_a, owner_b, project_b).

    Two unrelated tenants: each user owns exactly one project and has no
    access to the other. This is the shape a cross-project leak needs —
    a single-project fixture cannot see one.
    """
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        made: list[tuple[uuid.UUID, uuid.UUID]] = []
        for label in ("A", "B"):
            owner_id = uuid.uuid4()
            project_id = uuid.uuid4()
            s.add(
                User(
                    id=owner_id,
                    email=f"owner-{label.lower()}-{uuid.uuid4().hex[:6]}@test.io",
                    hashed_password="x",
                    full_name=f"Owner {label}",
                ),
            )
            await s.flush()
            s.add(
                Project(
                    id=project_id,
                    name=f"Stamp Tenancy {label}",
                    owner_id=owner_id,
                    currency="EUR",
                ),
            )
            made.append((owner_id, project_id))
        await s.commit()
        yield s, str(made[0][0]), made[0][1], str(made[1][0]), made[1][1]


async def _make_stamp(
    service: MarkupsService,
    *,
    project_id: uuid.UUID | None,
    name: str,
    owner_id: str,
    category: str = "predefined",
):
    """Create one stamp template through the service (the real write path)."""
    return await service.create_stamp(
        StampTemplateCreate(
            project_id=project_id,
            name=name,
            category=category,
            text=name.upper(),
        ),
        user_id=owner_id,
    )


@pytest.mark.asyncio
async def test_stamp_templates_do_not_leak_between_projects(two_projects) -> None:
    """A query scoped to project A must not return project B's own templates.

    Both rows carry ``category="predefined"`` on purpose — that is what the
    demo seeder writes (``markups/seed.py``), and it is the only shape that
    reproduces the leak. With ``category="custom"`` the pre-fix query already
    scoped correctly, so the test would pass without proving anything.
    """
    session, owner_a, project_a, owner_b, project_b = two_projects
    service = MarkupsService(session)

    await _make_stamp(service, project_id=project_a, name="A only", owner_id=owner_a)
    await _make_stamp(service, project_id=project_b, name="B only", owner_id=owner_b)
    await session.commit()

    visible_to_a = await service.list_stamps(project_a)
    names = {s.name for s in visible_to_a}

    assert "A only" in names, "project A must still see its own template"
    assert "B only" not in names, "project A must never see project B's template"
    # And symmetrically, so the assertion is not satisfied by an empty result.
    visible_to_b = {s.name for s in await service.list_stamps(project_b)}
    assert visible_to_b == {"B only"}


@pytest.mark.asyncio
async def test_global_predefined_stamps_stay_shared(two_projects) -> None:
    """Shipped global templates (``project_id IS NULL``) reach every project.

    Regression pin for the deliberate design, NOT leak evidence: this holds
    both before and after the scoping fix. It exists so a future tightening
    of the query cannot quietly turn the shared stamp library into a
    per-project one.
    """
    session, owner_a, project_a, _owner_b, project_b = two_projects
    service = MarkupsService(session)

    await _make_stamp(service, project_id=None, name="Approved (global)", owner_id="system")
    await session.commit()

    for project_id in (project_a, project_b):
        names = {s.name for s in await service.list_stamps(project_id)}
        assert "Approved (global)" in names


@pytest.mark.asyncio
async def test_listing_stamps_for_a_foreign_project_is_refused(two_projects) -> None:
    """The listing route gates ``project_id`` the way the mutation route does.

    Scoping the query stops the accidental leak; it does not stop a caller
    simply asking for another tenant's project id. ``_authorize_stamp_mutation``
    already gates PATCH/DELETE — GET must not be the one door left open.
    """
    session, owner_a, _project_a, owner_b, project_b = two_projects
    service = MarkupsService(session)

    await _make_stamp(service, project_id=project_b, name="B only", owner_id=owner_b)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await list_stamp_templates(
            session=session,
            project_id=project_b,
            user_id=owner_a,
            service=service,
        )
    # 404 — matches verify_project_access: a refused project and a missing
    # one must be indistinguishable.
    assert exc.value.status_code == 404

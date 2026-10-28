# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Choosing a formwork system, and getting the chosen one into the bill.

Two endpoints are covered here, and they are the two the module was missing:

* ``POST /systems/compare`` - price one contact area in every candidate system
  on ONE set of assumptions, so "which system" is a comparison rather than a
  list of names. The claims worth testing are that the assumption is held
  constant across candidates, that a system which cannot survive the assumed
  reuse count is flagged rather than silently recommended, and that the
  arithmetic is the same ``compute_cost`` the stored assignment uses.
* ``POST /assignments/{id}/push-to-boq`` - the exit to the priced bill. The
  claim worth testing is idempotency: pushing twice must re-price one position,
  not bill the same formwork twice.

These need real rows, so they run against the database like the rest of the
API suite rather than as pure math.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def header(client: AsyncClient) -> dict[str, str]:
    """Register, force-activate and log in one admin for the whole module."""
    tag = uuid.uuid4().hex[:8]
    email = f"formwork-choice-{tag}@test.io"
    password = f"FormChoice{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Formwork Choice {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="admin", is_active=True),
        )
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


async def _project(client: AsyncClient, header: dict[str, str], name: str) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": name, "description": "formwork choice test"},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _boq(client: AsyncClient, header: dict[str, str], project_id: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": name},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _system(client: AsyncClient, header: dict[str, str], **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": f"Choice test panel {uuid.uuid4().hex[:6]}",
        "system_type": "wall",
        "material": "steel",
        "reuses_max": 100,
        "unit_rate": "65.00",
        "erect_strike_rate": "16.00",
        "strip_time_days": 1,
        "currency": "EUR",
    }
    payload.update(overrides)
    resp = await client.post("/api/v1/formwork/systems/", json=payload, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _assignment(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    system_id: str,
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {
        "project_id": project_id,
        "formwork_system_id": system_id,
        "area_m2": "800.00",
        "reuse_count": 4,
        "waste_pct": "5.00",
    }
    payload.update(overrides)
    resp = await client.post("/api/v1/formwork/assignments/", json=payload, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _by_id(body: dict, system_id: str) -> dict:
    """The one candidate row for ``system_id``, or a clear failure."""
    rows = [c for c in body["candidates"] if c["system_id"] == system_id]
    assert len(rows) == 1, f"expected exactly one candidate for {system_id}, got {len(rows)}"
    return rows[0]


# ── compare ─────────────────────────────────────────────────────────────────


async def test_compare_prices_every_candidate_on_the_same_assumption(
    client: AsyncClient,
    header: dict[str, str],
):
    """One reuse count for all candidates, so the ranking compares systems.

    The alternative - pricing each row at its own published reuse figure - ranks
    the catalogue by how boldly each row claims to be reusable, which is a claim
    rather than a measurement.
    """
    cheap = await _system(
        client,
        header,
        system_type="tunnel",
        unit_rate="210.00",
        erect_strike_rate="7.00",
        typical_reuses=200,
        reuses_max=300,
    )
    dear = await _system(
        client,
        header,
        system_type="tunnel",
        unit_rate="60.00",
        erect_strike_rate="30.00",
        typical_reuses=40,
        reuses_max=100,
    )

    resp = await client.post(
        "/api/v1/formwork/systems/compare",
        json={
            "area_m2": "1000",
            "reuse_count": 50,
            "waste_pct": "0",
            "system_type": "tunnel",
        },
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reuse_count"] == 50

    # 210/50 = 4.20 panels + 7.00 labour = 11.20/m2.
    assert Decimal(_by_id(body, cheap["id"])["unit_cost"]) == Decimal("11.20")
    # 60/50 = 1.20 panels + 30.00 labour = 31.20/m2. The dearer ACQUISITION is
    # the cheaper rate here only because the labour dominates once amortised -
    # which is the comparison the estimator is trying to see.
    assert Decimal(_by_id(body, dear["id"])["unit_cost"]) == Decimal("31.20")

    # Sorted cheapest total first.
    totals = [Decimal(c["total"]) for c in body["candidates"]]
    assert totals == sorted(totals)


async def test_compare_flags_a_system_that_cannot_survive_the_assumption(
    client: AsyncClient,
    header: dict[str, str],
):
    """A single-use liner priced at forty reuses is flagged, not recommended.

    It is still PRICED, deliberately: hiding the row would hide the comparison
    that shows why it is the wrong choice. What must not happen is it winning
    ``cheapest_buildable_system_id``.
    """
    # Priced far below anything the starter catalogue carries, on purpose. The
    # comparison is deliberately catalogue-wide, so a seeded default from
    # another test module is visible here; pinning "the cheapest row is mine"
    # needs a rate nothing else can undercut, not a plausible one.
    liner = await _system(
        client,
        header,
        system_type="column",
        unit_rate="1.00",
        erect_strike_rate="0.50",
        reuses_max=1,
        typical_reuses=1,
    )
    reusable = await _system(
        client,
        header,
        system_type="column",
        unit_rate="62.00",
        erect_strike_rate="19.00",
        reuses_max=100,
        typical_reuses=60,
    )

    resp = await client.post(
        "/api/v1/formwork/systems/compare",
        json={"area_m2": "500", "reuse_count": 40, "waste_pct": "0", "system_type": "column"},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    liner_row = _by_id(body, liner["id"])
    reusable_row = _by_id(body, reusable["id"])
    assert liner_row["exceeds_reuses_max"] is True
    assert reusable_row["exceeds_reuses_max"] is False

    # 1.00/40 = 0.03 + 0.50 = 0.53 beats 62/40 = 1.55 + 19.00 = 20.55, so the
    # impossible row IS the outright cheapest. That is exactly the case the
    # second winner exists for: recommending it would price the job on panels
    # that are in a skip after the first pour.
    assert Decimal(liner_row["unit_cost"]) < Decimal(reusable_row["unit_cost"])
    assert body["cheapest_system_id"] == liner["id"]
    assert body["cheapest_buildable_system_id"] != liner["id"]
    # Whatever wins the buildable slot, it must be a row that survives 40 uses.
    winner = _by_id(body, body["cheapest_buildable_system_id"])
    assert winner["exceeds_reuses_max"] is False


async def test_compare_reports_the_reuse_saving_and_zero_for_a_hired_set(
    client: AsyncClient,
    header: dict[str, str],
):
    """The saving is real on a purchase basis and zero on a per-use one."""
    bought = await _system(
        client,
        header,
        system_type="foundation",
        unit_rate="100.00",
        erect_strike_rate="10.00",
        rate_basis="purchase",
    )
    hired = await _system(
        client,
        header,
        system_type="foundation",
        unit_rate="100.00",
        erect_strike_rate="10.00",
        rate_basis="hire_per_use",
    )

    resp = await client.post(
        "/api/v1/formwork/systems/compare",
        json={"area_m2": "100", "reuse_count": 10, "waste_pct": "0", "system_type": "foundation"},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Bought: 100/10 = 10.00 + 10.00 = 20.00/m2, against 110.00 at one use.
    bought_row = _by_id(body, bought["id"])
    assert Decimal(bought_row["unit_cost"]) == Decimal("20.00")
    assert Decimal(bought_row["reuse_saving"]) == Decimal("9000.00")

    # Hired per use: the rate never amortised, so there is nothing to save.
    hired_row = _by_id(body, hired["id"])
    assert Decimal(hired_row["unit_cost"]) == Decimal("110.00")
    assert Decimal(hired_row["reuse_saving"]) == Decimal("0.00")


async def test_compare_agrees_with_the_rate_the_assignment_stores(
    client: AsyncClient,
    header: dict[str, str],
):
    """The preview and the stored total come from one implementation.

    Two implementations of a rate build-up drift, and the drift shows up as the
    number on the chooser disagreeing with the number in the bill. This is the
    test that would catch that.
    """
    project_id = await _project(client, header, f"Compare parity {uuid.uuid4().hex[:6]}")
    system = await _system(client, header, system_type="beam", unit_rate="55.00")

    resp = await client.post(
        "/api/v1/formwork/systems/compare",
        json={"area_m2": "800.00", "reuse_count": 4, "waste_pct": "5.00", "system_type": "beam"},
        headers=header,
    )
    preview = _by_id(resp.json(), system["id"])

    assignment = await _assignment(client, header, project_id, system["id"])
    assert Decimal(assignment["computed_unit_cost"]) == Decimal(preview["unit_cost"])
    assert Decimal(assignment["computed_total"]) == Decimal(preview["total"])


# ── push to the bill ────────────────────────────────────────────────────────


async def test_push_creates_a_position_carrying_the_formwork_rate(
    client: AsyncClient,
    header: dict[str, str],
):
    """Contact area becomes the quantity, the reuse-aware rate becomes the rate."""
    project_id = await _project(client, header, f"Push create {uuid.uuid4().hex[:6]}")
    boq_id = await _boq(client, header, project_id, "Formwork bill")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/push-to-boq",
        json={"boq_id": boq_id},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] is True
    assert Decimal(body["quantity"]) == Decimal("800.00")
    assert Decimal(body["unit_rate"]) == Decimal(assignment["computed_unit_cost"])

    position = await client.get(f"/api/v1/boq/positions/{body['boq_position_id']}", headers=header)
    assert position.status_code == 200, position.text
    row = position.json()
    # Formwork is measured per m2 of CONTACT AREA - the face the concrete
    # touches - so the unit is not negotiable.
    assert row["unit"] == "m2"
    assert row["source"] == "formwork"


async def test_pushing_twice_reprices_one_position_rather_than_billing_twice(
    client: AsyncClient,
    header: dict[str, str],
):
    """The second push must not double a concrete frame's biggest single cost.

    Re-pushing is the NORMAL case - the estimator changes the system or the
    reuse count and sends it again - so an endpoint that appended every time
    would quietly double-bill on ordinary use rather than on a mistake.
    """
    project_id = await _project(client, header, f"Push twice {uuid.uuid4().hex[:6]}")
    boq_id = await _boq(client, header, project_id, "Formwork bill")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])

    first = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/push-to-boq",
        json={"boq_id": boq_id},
        headers=header,
    )
    assert first.json()["created"] is True

    # Change the assumption, then push again.
    patched = await client.patch(
        f"/api/v1/formwork/assignments/{assignment['id']}",
        json={"reuse_count": 20},
        headers=header,
    )
    assert patched.status_code == 200, patched.text

    second = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/push-to-boq",
        json={"boq_id": boq_id},
        headers=header,
    )
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    assert second.json()["boq_position_id"] == first.json()["boq_position_id"]
    # The re-push carried the NEW rate, it did not just find the old row.
    assert Decimal(second.json()["unit_rate"]) == Decimal(patched.json()["computed_unit_cost"])
    assert Decimal(second.json()["unit_rate"]) < Decimal(first.json()["unit_rate"])

    # Counted straight out of the table rather than through a list endpoint:
    # the claim is about how many ROWS exist, and a listing that paginated or
    # filtered would be able to show one while two were stored.
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Position)
            .where(Position.boq_id == uuid.UUID(boq_id), Position.source == "formwork"),
        )
    assert count == 1, f"pushing twice left {count} formwork positions in the bill"


@pytest.mark.tenant_isolation
async def test_push_refuses_a_bill_belonging_to_another_project(
    client: AsyncClient,
    header: dict[str, str],
):
    """Nothing else stops a rate priced on one job landing in another's tender.

    The bill is named by id and there is deliberately no foreign key from the
    assignment to it, so this check is the only thing standing there.
    """
    own_project = await _project(client, header, f"Push own {uuid.uuid4().hex[:6]}")
    other_project = await _project(client, header, f"Push other {uuid.uuid4().hex[:6]}")
    other_boq = await _boq(client, header, other_project, "Someone else's bill")
    system = await _system(client, header)
    assignment = await _assignment(client, header, own_project, system["id"])

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/push-to-boq",
        json={"boq_id": other_boq},
        headers=header,
    )
    assert resp.status_code == 422, resp.text

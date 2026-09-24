# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End-to-end behaviour of the Formwork API against a real database.

Covers the things that only show up once rows exist: a catalogue rate change
re-pricing every assignment derived from it, the pour cycle driving the reuse
count, the project rollup, the delete guard, explicit-null patching, and the
404-not-403 posture on unknown ids.

The app is built once per module (booting it is the expensive part) and every
test creates its own project so ordering never matters.
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
    email = f"formwork-api-{tag}@test.io"
    password = f"FormApi{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Formwork API {tag}",
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
        json={"name": name, "description": "formwork api test"},
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _system(
    client: AsyncClient,
    header: dict[str, str],
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {
        "name": f"Test wall panel {uuid.uuid4().hex[:6]}",
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


# ── the rate build-up reaches the API ───────────────────────────────────────


async def test_assignment_carries_both_rate_components(client: AsyncClient, header: dict[str, str]):
    """The response splits the amortising half from the per-use half."""
    project_id = await _project(client, header, "Formwork rate build-up")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])

    # 65.00 * 1.05 / 4 = 17.06 material, + 16.00 labour = 33.06 unit.
    assert Decimal(assignment["material_unit_cost"]) == Decimal("17.06")
    assert Decimal(assignment["labour_unit_cost"]) == Decimal("16.00")
    assert Decimal(assignment["computed_unit_cost"]) == Decimal("33.06")
    assert Decimal(assignment["computed_total"]) == Decimal("26448.00")
    # Money serialises as string, never as a JSON number.
    for field in ("material_unit_cost", "labour_unit_cost", "computed_unit_cost", "computed_total"):
        assert isinstance(assignment[field], str)


async def test_assignment_list_carries_the_catalogue_facts(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork detail row")
    system = await _system(client, header, name=f"Detail row system {uuid.uuid4().hex[:6]}")
    await _assignment(client, header, project_id, system["id"])

    resp = await client.get(
        "/api/v1/formwork/assignments/",
        params={"project_id": project_id},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["system_name"] == system["name"]
    assert row["material"] == "steel"
    assert row["reuses_max"] == 100
    assert row["currency"] == "EUR"
    assert Decimal(row["system_unit_rate"]) == Decimal("65.00")
    assert row["schedule_line_count"] == 0


# ── catalogue changes re-price what depends on them ─────────────────────────


async def test_changing_a_catalogue_rate_reprices_every_assignment(
    client: AsyncClient,
    header: dict[str, str],
):
    """The headline invariant: no stored total outlives its own catalogue row.

    Before this, editing a system left every assignment quoting a number the
    catalogue no longer produced, and nothing in the product noticed.
    """
    project_id = await _project(client, header, "Formwork reprice")
    system = await _system(client, header, unit_rate="60.00", erect_strike_rate="0.00")
    assignment = await _assignment(
        client,
        header,
        project_id,
        system["id"],
        area_m2="100.00",
        reuse_count=1,
        waste_pct="0.00",
    )
    assert Decimal(assignment["computed_total"]) == Decimal("6000.00")

    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"unit_rate": "90.00"},
        headers=header,
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["reprice"]["examined"] == 1
    assert body["reprice"]["repriced"] == 1
    assert Decimal(body["reprice"]["delta_total"]) == Decimal("3000.00")

    after = await client.get(
        f"/api/v1/formwork/assignments/{assignment['id']}",
        headers=header,
    )
    assert Decimal(after.json()["computed_total"]) == Decimal("9000.00")


async def test_repricing_reports_unchanged_when_nothing_moves(
    client: AsyncClient,
    header: dict[str, str],
):
    """Editing a field that is not a rate driver must not claim a change."""
    project_id = await _project(client, header, "Formwork reprice no-op")
    system = await _system(client, header)
    await _assignment(client, header, project_id, system["id"])

    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"notes": "renamed only"},
        headers=header,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["reprice"] == {
        "examined": 1,
        "repriced": 0,
        "unchanged": 1,
        "delta_total": "0.00",
    }


async def test_lowering_the_reuse_cap_clamps_and_reprices_upward(
    client: AsyncClient,
    header: dict[str, str],
):
    """A cap cut below a live reuse count raises the rate, never lowers it."""
    project_id = await _project(client, header, "Formwork cap cut")
    system = await _system(client, header, reuses_max=50, erect_strike_rate="0.00")
    assignment = await _assignment(
        client,
        header,
        project_id,
        system["id"],
        area_m2="100.00",
        reuse_count=40,
        waste_pct="0.00",
    )
    before = Decimal(assignment["computed_total"])

    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"reuses_max": 10},
        headers=header,
    )
    assert patch.status_code == 200, patch.text

    after = await client.get(f"/api/v1/formwork/assignments/{assignment['id']}", headers=header)
    body = after.json()
    assert body["reuse_count"] == 10
    assert Decimal(body["computed_total"]) > before


async def test_project_reprice_is_idempotent(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork project reprice")
    system = await _system(client, header)
    await _assignment(client, header, project_id, system["id"])

    first = await client.post(
        "/api/v1/formwork/reprice",
        params={"project_id": project_id},
        headers=header,
    )
    assert first.status_code == 200, first.text
    assert first.json()["examined"] == 1

    second = await client.post(
        "/api/v1/formwork/reprice",
        params={"project_id": project_id},
        headers=header,
    )
    assert second.json()["repriced"] == 0
    assert Decimal(second.json()["delta_total"]) == Decimal("0")


# ── catalogue usage and the delete guard ────────────────────────────────────


async def test_system_usage_reports_what_depends_on_it(client: AsyncClient, header: dict[str, str]):
    project_a = await _project(client, header, "Formwork usage A")
    project_b = await _project(client, header, "Formwork usage B")
    system = await _system(client, header)
    await _assignment(client, header, project_a, system["id"], area_m2="100.00")
    await _assignment(client, header, project_b, system["id"], area_m2="200.00")

    resp = await client.get(f"/api/v1/formwork/systems/{system['id']}/usage", headers=header)
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    assert usage["assignment_count"] == 2
    assert usage["project_count"] == 2
    assert Decimal(usage["total_area_m2"]) == Decimal("300.00")


async def test_deleting_a_system_in_use_is_a_conflict_not_a_crash(
    client: AsyncClient,
    header: dict[str, str],
):
    """The FK is RESTRICT, so without the guard this surfaced as a 500."""
    project_id = await _project(client, header, "Formwork delete guard")
    system = await _system(client, header)
    await _assignment(client, header, project_id, system["id"])

    resp = await client.delete(f"/api/v1/formwork/systems/{system['id']}", headers=header)
    assert resp.status_code == 409, resp.text
    assert "1 assignment" in resp.json()["detail"]


async def test_an_unused_system_still_deletes(client: AsyncClient, header: dict[str, str]):
    system = await _system(client, header)
    resp = await client.delete(f"/api/v1/formwork/systems/{system['id']}", headers=header)
    assert resp.status_code == 204, resp.text
    gone = await client.get(f"/api/v1/formwork/systems/{system['id']}", headers=header)
    assert gone.status_code == 404


# ── partial updates ─────────────────────────────────────────────────────────


async def test_an_explicit_null_clears_a_nullable_field(client: AsyncClient, header: dict[str, str]):
    """Sending ``notes: null`` used to be dropped, so a note could not be removed."""
    system = await _system(client, header, notes="initial note")
    assert system["notes"] == "initial note"

    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"notes": None},
        headers=header,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["system"]["notes"] is None


async def test_an_explicit_null_on_a_not_null_field_is_rejected_by_name(
    client: AsyncClient,
    header: dict[str, str],
):
    system = await _system(client, header)
    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"name": None},
        headers=header,
    )
    assert patch.status_code == 422, patch.text
    assert "name" in patch.json()["detail"]


async def test_clearing_the_boq_link_on_an_assignment(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork unlink")
    system = await _system(client, header)
    position_id = str(uuid.uuid4())
    assignment = await _assignment(
        client,
        header,
        project_id,
        system["id"],
        boq_position_id=position_id,
    )
    assert assignment["boq_position_id"] == position_id

    patch = await client.patch(
        f"/api/v1/formwork/assignments/{assignment['id']}",
        json={"boq_position_id": None},
        headers=header,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["boq_position_id"] is None


async def test_an_omitted_field_is_left_alone(client: AsyncClient, header: dict[str, str]):
    system = await _system(client, header, notes="keep me")
    patch = await client.patch(
        f"/api/v1/formwork/systems/{system['id']}",
        json={"supplier": "Somebody"},
        headers=header,
    )
    assert patch.json()["system"]["notes"] == "keep me"


# ── the pour cycle ──────────────────────────────────────────────────────────


async def _add_pour(
    client: AsyncClient,
    header: dict[str, str],
    assignment_id: str,
    pour_no: int,
    area: str,
    pour_date: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "pour_no": pour_no,
        "level_label": f"L{pour_no:02d}",
        "area_m2": area,
    }
    if pour_date:
        payload["pour_date"] = pour_date
    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment_id}/schedule-lines/",
        json=payload,
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_cycle_reports_the_panel_set_and_the_turnaround(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork cycle")
    system = await _system(client, header, strip_time_days=7)
    assignment = await _assignment(client, header, project_id, system["id"], reuse_count=1)
    for i, area in enumerate(["250.00", "250.00", "250.00", "250.00"]):
        await _add_pour(client, header, assignment["id"], i + 1, area)

    resp = await client.get(
        f"/api/v1/formwork/assignments/{assignment['id']}/cycle",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    cycle = resp.json()
    assert cycle["pour_count"] == 4
    assert Decimal(cycle["peak_pour_area_m2"]) == Decimal("250.00")
    assert Decimal(cycle["total_pour_area_m2"]) == Decimal("1000.00")
    assert cycle["derived_reuse_count"] == 4
    assert cycle["current_reuse_count"] == 1
    assert cycle["in_sync"] is False


async def test_cycle_flags_pours_closer_than_the_striking_time(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork strip time")
    system = await _system(client, header, system_type="slab", strip_time_days=7)
    assignment = await _assignment(client, header, project_id, system["id"])
    await _add_pour(client, header, assignment["id"], 1, "300.00", "2026-04-01")
    await _add_pour(client, header, assignment["id"], 2, "300.00", "2026-04-03")

    resp = await client.get(
        f"/api/v1/formwork/assignments/{assignment['id']}/cycle",
        headers=header,
    )
    cycle = resp.json()
    assert cycle["min_gap_days"] == 2
    assert len(cycle["conflicts"]) == 1
    assert cycle["conflicts"][0]["required_days"] == 7


async def test_derive_from_schedule_writes_the_area_and_reuse_and_reprices(
    client: AsyncClient,
    header: dict[str, str],
):
    """The point of keeping a cycle: it replaces the typed reuse count."""
    project_id = await _project(client, header, "Formwork derive")
    system = await _system(client, header, unit_rate="80.00", erect_strike_rate="0.00")
    assignment = await _assignment(
        client,
        header,
        project_id,
        system["id"],
        area_m2="100.00",
        reuse_count=1,
        waste_pct="0.00",
    )
    assert Decimal(assignment["computed_total"]) == Decimal("8000.00")
    for i in range(4):
        await _add_pour(client, header, assignment["id"], i + 1, "250.00")

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/derive-from-schedule",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is True
    assert body["assignment"]["reuse_count"] == 4
    assert Decimal(body["assignment"]["area_m2"]) == Decimal("1000.00")
    # 80.00 / 4 = 20.00 per m2 over 1000 m2.
    assert Decimal(body["assignment"]["computed_unit_cost"]) == Decimal("20.00")
    assert Decimal(body["assignment"]["computed_total"]) == Decimal("20000.00")
    assert body["analysis"]["in_sync"] is True


async def test_deriving_twice_reports_no_second_change(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork derive twice")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])
    await _add_pour(client, header, assignment["id"], 1, "400.00")
    await _add_pour(client, header, assignment["id"], 2, "400.00")

    first = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/derive-from-schedule",
        headers=header,
    )
    assert first.json()["changed"] is True
    second = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/derive-from-schedule",
        headers=header,
    )
    assert second.json()["changed"] is False


async def test_deriving_without_a_schedule_is_rejected(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork derive empty")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])
    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/derive-from-schedule",
        headers=header,
    )
    assert resp.status_code == 422, resp.text


async def test_derive_clamps_to_the_system_reuse_cap(client: AsyncClient, header: dict[str, str]):
    """A programme can describe more turnarounds than the panels survive."""
    project_id = await _project(client, header, "Formwork derive clamp")
    system = await _system(client, header, reuses_max=3)
    assignment = await _assignment(client, header, project_id, system["id"], reuse_count=1)
    for i in range(6):
        await _add_pour(client, header, assignment["id"], i + 1, "100.00")

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/derive-from-schedule",
        headers=header,
    )
    assert resp.json()["assignment"]["reuse_count"] == 3


# ── project rollup ──────────────────────────────────────────────────────────


async def test_summary_totals_and_the_amortisation_saving(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork summary")
    walls = await _system(client, header, system_type="wall", unit_rate="60.00", erect_strike_rate="0.00")
    slabs = await _system(client, header, system_type="slab", unit_rate="50.00", erect_strike_rate="0.00")
    await _assignment(
        client,
        header,
        project_id,
        walls["id"],
        area_m2="1000.00",
        reuse_count=10,
        waste_pct="0.00",
    )
    await _assignment(
        client,
        header,
        project_id,
        slabs["id"],
        area_m2="500.00",
        reuse_count=5,
        waste_pct="0.00",
    )

    resp = await client.get(
        "/api/v1/formwork/summary",
        params={"project_id": project_id},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["assignment_count"] == 2
    assert summary["system_count"] == 2
    assert Decimal(summary["total_area_m2"]) == Decimal("1500.00")
    # 1000 * 6.00 + 500 * 10.00 = 11000.
    assert Decimal(summary["total_cost"]) == Decimal("11000.00")
    # At one use: 1000 * 60 + 500 * 50 = 85000.
    assert Decimal(summary["single_use_total"]) == Decimal("85000.00")
    assert Decimal(summary["amortisation_saving"]) == Decimal("74000.00")
    assert summary["currency"] == "EUR"
    assert summary["currency_mixed"] is False
    assert summary["unlinked_to_boq"] == 2
    types = {row["system_type"]: row for row in summary["by_system_type"]}
    assert Decimal(types["wall"]["total"]) == Decimal("6000.00")
    assert Decimal(types["slab"]["total"]) == Decimal("5000.00")


async def test_summary_reports_a_mixed_currency_project_as_mixed(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork mixed currency")
    eur = await _system(client, header, currency="EUR")
    gbp = await _system(client, header, currency="GBP")
    await _assignment(client, header, project_id, eur["id"])
    await _assignment(client, header, project_id, gbp["id"])

    resp = await client.get(
        "/api/v1/formwork/summary",
        params={"project_id": project_id},
        headers=header,
    )
    summary = resp.json()
    assert summary["currency_mixed"] is True
    assert summary["currency"] == ""


async def test_summary_of_a_project_with_no_formwork_is_all_zero(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork empty summary")
    resp = await client.get(
        "/api/v1/formwork/summary",
        params={"project_id": project_id},
        headers=header,
    )
    summary = resp.json()
    assert summary["assignment_count"] == 0
    assert Decimal(summary["total_cost"]) == Decimal("0")
    assert Decimal(summary["amortisation_saving"]) == Decimal("0")
    assert summary["by_system_type"] == []


# ── validation through the API ──────────────────────────────────────────────


async def test_assignment_validate_reports_the_unlinked_bill_position(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork validate assignment")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/validate",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["unsupported_rule_sets"] == []
    rule_ids = {f["rule_id"] for f in report["findings"]}
    assert "formwork.boq_position_linked" in rule_ids
    assert report["error_count"] == 0


async def test_assignment_validate_sees_the_pour_cycle(client: AsyncClient, header: dict[str, str]):
    """A reuse count the schedule does not support is reported, not assumed."""
    project_id = await _project(client, header, "Formwork validate cycle")
    system = await _system(client, header)
    assignment = await _assignment(
        client,
        header,
        project_id,
        system["id"],
        area_m2="400.00",
        reuse_count=8,
    )
    await _add_pour(client, header, assignment["id"], 1, "200.00")
    await _add_pour(client, header, assignment["id"], 2, "200.00")

    resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment['id']}/validate",
        headers=header,
    )
    rule_ids = {f["rule_id"] for f in resp.json()["findings"]}
    assert "formwork.reuse_supported_by_schedule" in rule_ids


async def test_project_validate_catches_a_double_charged_bill_position(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork validate project")
    system = await _system(client, header)
    position_id = str(uuid.uuid4())
    await _assignment(client, header, project_id, system["id"], boq_position_id=position_id)
    await _assignment(client, header, project_id, system["id"], boq_position_id=position_id)

    resp = await client.post(
        "/api/v1/formwork/validate",
        params={"project_id": project_id},
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    rule_ids = {f["rule_id"] for f in report["findings"]}
    assert "formwork.boq_position_unique" in rule_ids
    assert report["warning_count"] >= 1


async def test_project_validate_catches_mixed_currencies(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork validate currency")
    eur = await _system(client, header, currency="EUR")
    usd = await _system(client, header, currency="USD")
    await _assignment(client, header, project_id, eur["id"])
    await _assignment(client, header, project_id, usd["id"])

    resp = await client.post(
        "/api/v1/formwork/validate",
        params={"project_id": project_id},
        headers=header,
    )
    report = resp.json()
    assert "formwork.currency_consistent" in {f["rule_id"] for f in report["findings"]}
    assert report["status"] == "errors"


# ── seeding ─────────────────────────────────────────────────────────────────


async def _global_names() -> set[str]:
    """Names of the systems every tenant already sees, the ``tenant_id IS NULL`` rows.

    Seeding for a tenant skips a starter system that exists globally, on
    purpose (see ``FormworkSystemRepository.list_names_for_tenant``). Whether
    any do depends on what ran before this module on the same database: the
    demo installer seeds the catalogue globally, and in a full-suite run some
    earlier test has usually done that. So the expected split between inserted
    and skipped is read from the table rather than assumed to be all-inserted,
    which only held when this module ran against an empty catalogue.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkSystem

    async with async_session_factory() as session:
        rows = await session.execute(select(FormworkSystem.name).where(FormworkSystem.tenant_id.is_(None)))
        return {row[0] for row in rows.all()}


async def test_seeding_is_idempotent_and_counts_the_real_catalogue(
    client: AsyncClient,
    header: dict[str, str],
):
    """``total_after`` is counted from the table, not derived from a name set.

    The expected counts are the LENGTH of the shipped catalogue, not a literal.
    They were literal tens until the catalogue grew from ten rows to eighteen,
    at which point the number under test was a property of the assertion rather
    than of the endpoint: adding a system to the starter library is a normal
    product change and it should not fail a test about idempotency.
    """
    from app.modules.formwork.schemas import default_seed_systems

    names = {row["name"] for row in default_seed_systems()}
    shipped = len(names)
    preinstalled = len(names & await _global_names())

    tenant_id = str(uuid.uuid4())
    first = await client.post(
        "/api/v1/formwork/systems/seed-defaults",
        params={"tenant_id": tenant_id},
        headers=header,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["inserted"] == shipped - preinstalled
    assert body["skipped"] == preinstalled
    assert body["total_after"] >= shipped

    second = await client.post(
        "/api/v1/formwork/systems/seed-defaults",
        params={"tenant_id": tenant_id},
        headers=header,
    )
    repeat = second.json()
    assert repeat["inserted"] == 0
    assert repeat["skipped"] == shipped
    assert repeat["total_after"] == body["total_after"]


async def test_seeded_systems_carry_the_full_rate_build_up(
    client: AsyncClient,
    header: dict[str, str],
):
    """A starter catalogue that only fills the panel rate teaches a bad habit.

    The two per-row checks used to be ``erect_strike_rate > 0`` and
    ``strip_time_days >= 1``, which hold for any catalogue anyone could
    plausibly write and so said nothing about this one. They now compare
    against the shipped figures, so a row that loses its labour rate or its
    strip time on the way through the endpoint fails here.

    The same loop is where the catalogue's de-branding is held at the API
    level: these rows were named after real products from four suppliers
    until v3271, and a row arriving with a supplier attached is the shape
    that regression would take.
    """
    from app.modules.formwork.schemas import default_seed_systems

    catalogue = {row["name"]: row for row in default_seed_systems()}

    tenant_id = str(uuid.uuid4())
    await client.post(
        "/api/v1/formwork/systems/seed-defaults",
        params={"tenant_id": tenant_id},
        headers=header,
    )
    listing = await client.get("/api/v1/formwork/systems/", params={"limit": 500}, headers=header)
    assert listing.status_code == 200, listing.text
    # What this tenant sees for each starter name: its own row, or the global
    # one that made the seed skip it. Both came through the same seeding path.
    visible: dict[str, dict] = {}
    for row in listing.json():
        if row["name"] in catalogue and row["tenant_id"] in (tenant_id, None):
            if row["tenant_id"] == tenant_id or row["name"] not in visible:
                visible[row["name"]] = row
    seeded = list(visible.values())
    assert seeded, "seeded systems should be visible in the catalogue"
    assert {s["name"] for s in seeded} == set(catalogue), "seeded names do not match the shipped catalogue"
    for system in seeded:
        expected = catalogue[system["name"]]
        assert Decimal(system["erect_strike_rate"]) == expected["erect_strike_rate"]
        assert system["strip_time_days"] == expected["strip_time_days"]
        assert system["supplier"] is None, f"{system['name']!r} arrived carrying supplier {system['supplier']!r}"
    # Slab systems keep their props in far longer than wall systems.
    slabs = [s for s in seeded if s["system_type"] == "slab"]
    walls = [s for s in seeded if s["system_type"] == "wall"]
    assert slabs and walls
    assert min(s["strip_time_days"] for s in slabs) > max(w["strip_time_days"] for w in walls)


# ── access posture ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/formwork/systems/{id}",
        "/api/v1/formwork/systems/{id}/usage",
        "/api/v1/formwork/assignments/{id}",
        "/api/v1/formwork/assignments/{id}/cycle",
    ],
)
async def test_unknown_ids_answer_404_never_403(
    client: AsyncClient,
    header: dict[str, str],
    path: str,
):
    """Probing for a UUID must never leak whether the row exists."""
    resp = await client.get(path.format(id=uuid.uuid4()), headers=header)
    assert resp.status_code == 404, resp.text


async def test_creating_an_assignment_against_an_unknown_system_is_404(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork unknown system")
    resp = await client.post(
        "/api/v1/formwork/assignments/",
        json={
            "project_id": project_id,
            "formwork_system_id": str(uuid.uuid4()),
            "area_m2": "10.00",
        },
        headers=header,
    )
    assert resp.status_code == 404, resp.text


async def test_reuse_beyond_the_cap_is_refused_on_create(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork cap on create")
    system = await _system(client, header, reuses_max=5)
    resp = await client.post(
        "/api/v1/formwork/assignments/",
        json={
            "project_id": project_id,
            "formwork_system_id": system["id"],
            "area_m2": "10.00",
            "reuse_count": 50,
        },
        headers=header,
    )
    assert resp.status_code == 422, resp.text


# ── schedule lines ──────────────────────────────────────────────────────────


async def test_deleting_an_assignment_takes_its_pour_lines_with_it(
    client: AsyncClient,
    header: dict[str, str],
):
    project_id = await _project(client, header, "Formwork cascade")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])
    line = await _add_pour(client, header, assignment["id"], 1, "100.00")

    resp = await client.delete(
        f"/api/v1/formwork/assignments/{assignment['id']}",
        headers=header,
    )
    assert resp.status_code == 204, resp.text

    orphan = await client.patch(
        f"/api/v1/formwork/schedule-lines/{line['id']}",
        json={"area_m2": "1.00"},
        headers=header,
    )
    assert orphan.status_code == 404


async def test_clearing_a_pour_date_is_possible(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork clear date")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])
    line = await _add_pour(client, header, assignment["id"], 1, "100.00", "2026-05-01")
    assert line["pour_date"] == "2026-05-01"

    patch = await client.patch(
        f"/api/v1/formwork/schedule-lines/{line['id']}",
        json={"pour_date": None},
        headers=header,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["pour_date"] is None


async def test_a_null_level_label_is_rejected_by_name(client: AsyncClient, header: dict[str, str]):
    project_id = await _project(client, header, "Formwork null label")
    system = await _system(client, header)
    assignment = await _assignment(client, header, project_id, system["id"])
    line = await _add_pour(client, header, assignment["id"], 1, "100.00")

    patch = await client.patch(
        f"/api/v1/formwork/schedule-lines/{line['id']}",
        json={"level_label": None},
        headers=header,
    )
    assert patch.status_code == 422, patch.text
    assert "level_label" in patch.json()["detail"]

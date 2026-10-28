"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Set and option CRUD routes: success paths and every failure path they have.

Covers ``POST /sets/``, ``GET /sets/``, ``GET /sets/{id}``,
``POST /sets/{id}/options/``, ``POST /sets/{id}/baseline/``,
``DELETE /sets/{id}`` and ``DELETE /options/{id}``, plus the cross-tenant reads
of the comparison endpoints. ``attach-model`` and ``generate`` have their own
files.

The app is driven with :class:`httpx.AsyncClient` over an in-process
``ASGITransport`` so it runs on the test's own event loop; a synchronous
``TestClient`` would drive it from a worker thread on a second loop and break
the asyncpg session the router is handed.

Every cross-tenant attempt must read 404, never 403: the module keeps
"resource missing" and "access denied" indistinguishable so an id cannot be used
as an existence oracle. The caller in these tests is always a persisted
non-admin user, because the access guard reads ``User.role`` from the database
rather than from the token payload.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design_options.models import DesignOption, DesignOptionSet
from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_option,
    make_project,
    make_set,
    make_user,
)


async def _exists(session: AsyncSession, model: type, row_id: uuid.UUID) -> bool:
    """Existence by query - ``session.get`` would answer from the identity map."""
    return (await session.execute(select(model).where(model.id == row_id))).scalar_one_or_none() is not None


# ── POST /sets/ ──────────────────────────────────────────────────────────────


async def test_create_set_returns_201_with_an_empty_option_list(session: AsyncSession) -> None:
    """A new set is created for the caller's project and starts with no options."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/sets/",
            json={"project_id": str(project.id), "name": "Frame options", "comparison_currency": "usd"},
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Frame options"
    assert body["project_id"] == str(project.id)
    # The requested currency is normalised to upper case on the way in.
    assert body["comparison_currency"] == "USD"
    assert body["baseline_option_id"] is None
    assert body["options"] == []
    assert await _exists(session, DesignOptionSet, uuid.UUID(body["id"]))


@pytest.mark.tenant_isolation
async def test_create_set_in_another_users_project_returns_404(session: AsyncSession) -> None:
    """A set cannot be planted in a project the caller cannot reach."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/sets/",
            json={"project_id": str(project.id), "name": "Intruder"},
        )

    assert res.status_code == 404, res.text
    assert (await session.execute(select(DesignOptionSet))).scalars().all() == []


async def test_create_set_with_a_blank_name_returns_422(session: AsyncSession) -> None:
    """``name`` has a minimum length, so an empty set name is rejected."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/", json={"project_id": str(project.id), "name": "   "})

    assert res.status_code == 422, res.text


# ── GET /sets/ ───────────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
async def test_list_sets_returns_the_projects_sets_newest_first(session: AsyncSession) -> None:
    """The list is scoped to one project and ordered newest first."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_project = await make_project(session, user.id)
    older = await make_set(session, project.id, name="Older")
    newer = await make_set(session, project.id, name="Newer")
    await make_set(session, other_project.id, name="Elsewhere")
    # created_at is set in Python on flush, so nudge the pair apart explicitly.
    older.created_at = older.created_at.replace(year=older.created_at.year - 1)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/", params={"project_id": str(project.id)})

    assert res.status_code == 200, res.text
    assert [s["name"] for s in res.json()] == ["Newer", "Older"]
    assert {s["id"] for s in res.json()} == {str(newer.id), str(older.id)}


@pytest.mark.tenant_isolation
async def test_list_sets_for_another_users_project_returns_404(session: AsyncSession) -> None:
    """Listing is gated on the project, so a foreign project reads as missing."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    await make_set(session, project.id, name="Private")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/", params={"project_id": str(project.id)})

    assert res.status_code == 404, res.text


async def test_list_sets_without_a_project_id_returns_422(session: AsyncSession) -> None:
    """``project_id`` is a required query parameter, not an optional filter."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/")

    assert res.status_code == 422, res.text


# ── GET /sets/{set_id} ───────────────────────────────────────────────────────


async def test_get_set_returns_its_options_in_sort_order(session: AsyncSession) -> None:
    """One set is returned with its options ordered by sort order."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await make_option(session, option_set, name="Second", sort_order=1)
    await make_option(session, option_set, name="First", sort_order=0)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}")

    assert res.status_code == 200, res.text
    assert [o["name"] for o in res.json()["options"]] == ["First", "Second"]


async def test_get_unknown_set_returns_404(session: AsyncSession) -> None:
    """An id that never existed is a 404 from the service, before the guard."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{uuid.uuid4()}")

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_get_another_users_set_returns_404_not_403(session: AsyncSession) -> None:
    """A real set from another tenant is indistinguishable from a missing one."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id, name="Secret")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}")

    assert res.status_code == 404, res.text
    assert "Secret" not in res.text


# ── POST /sets/{set_id}/options/ ─────────────────────────────────────────────


async def test_create_option_appends_with_the_next_sort_order(session: AsyncSession) -> None:
    """Each new option lands after the current last one."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        first = await client.post(f"{API_PREFIX}/sets/{option_set.id}/options/", json={"name": "Steel"})
        second = await client.post(f"{API_PREFIX}/sets/{option_set.id}/options/", json={"name": "Timber"})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["sort_order"] == 0
    assert second.json()["sort_order"] == 1
    # The project is denormalised onto the option so option reads can be scoped
    # without a join back through the set.
    assert second.json()["project_id"] == str(project.id)
    assert second.json()["status"] == "draft"
    assert second.json()["grand_total"] == "0"


async def test_create_option_in_an_unknown_set_returns_404(session: AsyncSession) -> None:
    """The set is resolved before anything is written."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/{uuid.uuid4()}/options/", json={"name": "Steel"})

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_create_option_in_another_users_set_returns_404(session: AsyncSession) -> None:
    """No option may be grafted onto a foreign set."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/{option_set.id}/options/", json={"name": "Intruder"})

    assert res.status_code == 404, res.text
    assert (await session.execute(select(DesignOption))).scalars().all() == []


async def test_create_option_with_a_blank_name_returns_422(session: AsyncSession) -> None:
    """An option must be nameable so the comparison columns can be told apart."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/{option_set.id}/options/", json={"name": ""})

    assert res.status_code == 422, res.text


# ── POST /sets/{set_id}/baseline/ ────────────────────────────────────────────


async def test_set_baseline_marks_the_option_and_echoes_the_set(session: AsyncSession) -> None:
    """The chosen option becomes the set's baseline and the update is persisted."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/{option_set.id}/baseline/", json={"option_id": str(option.id)})

    assert res.status_code == 200, res.text
    assert res.json()["baseline_option_id"] == str(option.id)
    # Expunge first: the set was written by a bulk UPDATE that also patched
    # the in-memory instance, so a plain select would return that instance
    # rather than reading the row back.
    session.expunge_all()
    stored = (await session.execute(select(DesignOptionSet).where(DesignOptionSet.id == option_set.id))).scalar_one()
    assert stored.baseline_option_id == option.id


async def test_set_baseline_with_an_option_from_another_set_returns_404(session: AsyncSession) -> None:
    """A baseline must live in the set it is the baseline of."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id, name="A")
    other_set = await make_set(session, project.id, name="B")
    foreign_option = await make_option(session, other_set, name="Elsewhere")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/sets/{option_set.id}/baseline/",
            json={"option_id": str(foreign_option.id)},
        )

    assert res.status_code == 404, res.text
    # Expunge first: the set was written by a bulk UPDATE that also patched
    # the in-memory instance, so a plain select would return that instance
    # rather than reading the row back.
    session.expunge_all()
    stored = (await session.execute(select(DesignOptionSet).where(DesignOptionSet.id == option_set.id))).scalar_one()
    assert stored.baseline_option_id is None


async def test_set_baseline_with_an_unknown_option_returns_404(session: AsyncSession) -> None:
    """An id that resolves to nothing cannot become the baseline."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/sets/{option_set.id}/baseline/",
            json={"option_id": str(uuid.uuid4())},
        )

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_set_baseline_on_another_users_set_returns_404(session: AsyncSession) -> None:
    """The baseline call is gated on the set's project like every other route."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/sets/{option_set.id}/baseline/", json={"option_id": str(option.id)})

    assert res.status_code == 404, res.text


# ── DELETE /sets/{set_id} ────────────────────────────────────────────────────


async def test_delete_set_returns_204_and_takes_its_options_with_it(session: AsyncSession) -> None:
    """Deleting a set cascades to every option inside it."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/sets/{option_set.id}")

    assert res.status_code == 204, res.text
    assert not await _exists(session, DesignOptionSet, option_set.id)
    assert not await _exists(session, DesignOption, option.id)


async def test_delete_unknown_set_returns_404(session: AsyncSession) -> None:
    """Deleting something that is not there is a 404, not a silent 204."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/sets/{uuid.uuid4()}")

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_delete_another_users_set_returns_404_and_keeps_it(session: AsyncSession) -> None:
    """A foreign set survives the attempt and the caller learns nothing."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/sets/{option_set.id}")

    assert res.status_code == 404, res.text
    assert await _exists(session, DesignOptionSet, option_set.id)


# ── DELETE /options/{option_id} ──────────────────────────────────────────────


async def test_delete_option_returns_204_and_leaves_the_set(session: AsyncSession) -> None:
    """One option is removed; the set and its siblings stay."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    doomed = await make_option(session, option_set, name="Steel", sort_order=0)
    survivor = await make_option(session, option_set, name="Timber", sort_order=1)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/options/{doomed.id}")

    assert res.status_code == 204, res.text
    assert not await _exists(session, DesignOption, doomed.id)
    assert await _exists(session, DesignOption, survivor.id)
    assert await _exists(session, DesignOptionSet, option_set.id)


async def test_delete_option_clears_it_as_the_sets_baseline(session: AsyncSession) -> None:
    """Deleting the baseline option must not leave the set pointing at a ghost.

    ``baseline_option_id`` is a soft pointer with no foreign key, so nothing in
    the database clears it. Left dangling, the comparison finds no baseline
    column, silently reports every delta as zero, and the fairness banner still
    withholds its "no baseline chosen" notice because the id is not null.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    baseline = await make_option(session, option_set, name="Steel", sort_order=0)
    await make_option(session, option_set, name="Timber", sort_order=1)
    option_set.baseline_option_id = baseline.id
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/options/{baseline.id}")

    assert res.status_code == 204, res.text
    # Expunge first: the set was written by a bulk UPDATE that also patched
    # the in-memory instance, so a plain select would return that instance
    # rather than reading the row back.
    session.expunge_all()
    stored = (await session.execute(select(DesignOptionSet).where(DesignOptionSet.id == option_set.id))).scalar_one()
    assert stored.baseline_option_id is None


async def test_delete_option_leaves_a_baseline_that_points_elsewhere(session: AsyncSession) -> None:
    """Deleting a non-baseline option must not disturb the chosen baseline."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    baseline = await make_option(session, option_set, name="Steel", sort_order=0)
    other = await make_option(session, option_set, name="Timber", sort_order=1)
    option_set.baseline_option_id = baseline.id
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/options/{other.id}")

    assert res.status_code == 204, res.text
    # Expunge first: the set was written by a bulk UPDATE that also patched
    # the in-memory instance, so a plain select would return that instance
    # rather than reading the row back.
    session.expunge_all()
    stored = (await session.execute(select(DesignOptionSet).where(DesignOptionSet.id == option_set.id))).scalar_one()
    assert stored.baseline_option_id == baseline.id


async def test_delete_unknown_option_returns_404(session: AsyncSession) -> None:
    """An unknown option id is a 404 before any access check runs."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/options/{uuid.uuid4()}")

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_delete_another_users_option_returns_404_and_keeps_it(session: AsyncSession) -> None:
    """The option's denormalised project is what gates the delete."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.delete(f"{API_PREFIX}/options/{option.id}")

    assert res.status_code == 404, res.text
    assert await _exists(session, DesignOption, option.id)


# ── Cross-tenant reads of the comparison endpoints ───────────────────────────


@pytest.mark.tenant_isolation
async def test_comparison_of_another_users_set_returns_404(session: AsyncSession) -> None:
    """The JSON comparison is gated on the set's project."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id, name="Secret")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison/")

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_comparison_export_of_another_users_set_returns_404(session: AsyncSession) -> None:
    """The spreadsheet export is gated exactly like the JSON comparison."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id, name="Secret")
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{option_set.id}/comparison.xlsx")

    assert res.status_code == 404, res.text


async def test_comparison_of_an_unknown_set_returns_404(session: AsyncSession) -> None:
    """An unknown set id never reaches the aggregator."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{uuid.uuid4()}/comparison/")

    assert res.status_code == 404, res.text


async def test_comparison_export_of_an_unknown_set_returns_404(session: AsyncSession) -> None:
    """The export resolves the set before it builds a workbook."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.get(f"{API_PREFIX}/sets/{uuid.uuid4()}/comparison.xlsx")

    assert res.status_code == 404, res.text

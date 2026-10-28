"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: a price edit re-prices its own line, and a resource edit only what it names.

Two defects on the single-position PATCH path, both reported as "the BOQ freezes
when I put in a price".

The money one. A ``unit_rate`` edit on a position with resources rescales that
position's resource rates (OC-21). The resource propagation of issue #133 then
read the rescaled rates as a person editing the master resource definition, and
when the edited position was the oldest carrier of a resource code it rewrote
that resource on every other position of the project sharing the code. On the
demo bill that was 299 other lines re-priced, 300 UPDATEs and 300 events for one
typed number, and at 2,080 lines the request did not finish. Paste, fill-down,
the bulk rate factor, the audit fix and restore-field all send a bare
``unit_rate``, so none of it needed the locked rate cell.

The load one. Every PATCH loaded the whole bill, positions and markups, three
times over (ownership guard, lock guard, activity log) plus once more for the
duplicate check.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql

from app.modules.boq.models import BOQ, Position
from app.modules.boq.repository import PositionRepository, resource_code_prefilter
from app.modules.boq.router import _verify_boq_owner
from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User

SHARED = "SHR-100"

_T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def _res(code: str, qty: str, rate: str, **extra: Any) -> dict[str, Any]:
    return {
        "code": code,
        "name": f"Resource {code}",
        "type": "material",
        "unit": "m3",
        "quantity": qty,
        "unit_rate": rate,
        "total": str(Decimal(qty) * Decimal(rate)),
        **extra,
    }


async def _owner_project_boq(session) -> tuple[User, Project, BOQ]:
    owner = User(email=f"reprice-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Reprice")
    session.add(owner)
    await session.flush()
    project = Project(name="Reprice", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Shared codes")
    session.add(boq)
    await session.flush()
    return owner, project, boq


def _position(boq: BOQ, n: int, qty: str, resources: list[dict[str, Any]]) -> Position:
    rate = sum((Decimal(r["quantity"]) * Decimal(r["unit_rate"]) for r in resources), Decimal("0"))
    return Position(
        boq_id=boq.id,
        ordinal=f"01.{n:03d}",
        description=f"Line {n}",
        unit="m3",
        quantity=qty,
        unit_rate=str(rate),
        total=str(rate * Decimal(qty)),
        metadata_={"resources": resources},
        sort_order=n,
        # Explicit and strictly increasing: the oldest carrier of a code owns it.
        created_at=_T0 + timedelta(minutes=n),
    )


async def _shared_code_bill(session) -> dict[str, Any]:
    """Four lines. A is the oldest carrier of SHR-100, B shares it at its own rate,
    C shares it but was diverged on purpose, D does not carry it."""
    owner, project, boq = await _owner_project_boq(session)
    a = _position(boq, 1, "5", [_res(SHARED, "1", "100.0000"), _res("OWN-7", "2", "10.0000")])
    b = _position(boq, 2, "2", [_res(SHARED, "3", "90.0000")])
    c = _position(boq, 3, "1", [_res(SHARED, "1", "95.0000", _code_overridden=True)])
    d = _position(boq, 4, "1", [_res("X-9", "1", "50.0000")])
    session.add_all([a, b, c, d])
    await session.flush()
    return {"owner": owner, "project": project, "boq": boq, "a": a.id, "b": b.id, "c": c.id, "d": d.id}


async def _stored(session, position_id: uuid.UUID) -> dict[str, Any]:
    """What the database holds for a line, read past the identity map."""
    row = (
        await session.execute(
            select(Position.unit_rate, Position.total, Position.version, Position.metadata_).where(
                Position.id == position_id
            )
        )
    ).one()
    return {"unit_rate": row[0], "total": row[1], "version": row[2], "metadata": row[3]}


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    """Record what ``update_position`` publishes instead of deferring it to a commit."""
    import app.modules.boq.service as boq_service

    events: list[tuple[str, dict[str, Any]]] = []

    async def _record(name: str, data: dict[str, Any], source_module: str = "oe_boq", *, session=None) -> None:
        events.append((name, data))

    monkeypatch.setattr(boq_service, "_safe_publish", _record)
    return events


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


# ── A price edit changes no other line ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_price_edit_on_the_first_holder_changes_no_other_line(pg_session, published) -> None:
    """The reported path: a bare unit_rate on the oldest carrier of a shared code."""
    bill = await _shared_code_bill(pg_session)
    before = {k: await _stored(pg_session, bill[k]) for k in ("b", "c", "d")}

    edited = await BOQService(pg_session).update_position(
        bill["a"], PositionUpdate(unit_rate=Decimal("150")), actor_id=bill["owner"].id
    )

    for key in ("b", "c", "d"):
        assert await _stored(pg_session, bill[key]) == before[key], f"line {key} was re-priced by a price edit on A"
    # OC-21 itself still holds on the edited line: its own resources follow its rate.
    a_res = {r["code"]: r for r in (await _stored(pg_session, bill["a"]))["metadata"]["resources"]}
    assert Decimal(a_res[SHARED]["unit_rate"]) == Decimal("125")
    assert Decimal(a_res["OWN-7"]["unit_rate"]) == Decimal("12.5")
    assert Decimal(str(edited.unit_rate)) == Decimal("150")
    assert _names(published) == ["boq.position.updated"]
    assert (getattr(edited, "_link_propagation_info", None) or {}).get("resource_propagated_to", 0) == 0


@pytest.mark.asyncio
async def test_a_price_edit_that_echoes_the_stored_metadata_changes_no_other_line(pg_session, published) -> None:
    """Same edit with the unchanged metadata sent along, as the AI-match accept does.

    That one went through the old gate outright, which only asked whether the
    request carried metadata, not whether the client changed a resource in it.
    """
    bill = await _shared_code_bill(pg_session)
    before = {k: await _stored(pg_session, bill[k]) for k in ("b", "c", "d")}
    stored_meta = (await _stored(pg_session, bill["a"]))["metadata"]

    await BOQService(pg_session).update_position(
        bill["a"],
        PositionUpdate(unit_rate=Decimal("150"), metadata=stored_meta),
        actor_id=bill["owner"].id,
    )

    for key in ("b", "c", "d"):
        assert await _stored(pg_session, bill[key]) == before[key], f"line {key} was re-priced by a price edit on A"
    assert "boq.positions.resource_propagated" not in _names(published)


@pytest.mark.asyncio
async def test_a_resource_quantity_edit_does_not_push_the_untouched_rates(pg_session, published) -> None:
    """The editor sends every resource back with its rate coerced to a number.

    ``"100.0000"`` returns as ``100.0``. Compared as text, every rate beside
    the edited quantity read as a new master definition, and B's own 90 was
    overwritten with A's 100.
    """
    bill = await _shared_code_bill(pg_session)
    before = {k: await _stored(pg_session, bill[k]) for k in ("b", "c", "d")}
    sent = [
        {**_res(SHARED, "1", "100"), "quantity": 1.0, "unit_rate": 100.0, "total": 100.0},
        {**_res("OWN-7", "3", "10"), "quantity": 3.0, "unit_rate": 10.0, "total": 30.0},
    ]

    await BOQService(pg_session).update_position(
        bill["a"],
        PositionUpdate(unit_rate=Decimal("130"), metadata={"resources": sent}),
        actor_id=bill["owner"].id,
    )

    for key in ("b", "c", "d"):
        assert await _stored(pg_session, bill[key]) == before[key], f"line {key} changed on a quantity edit of A"
    assert "boq.positions.resource_propagated" not in _names(published)


# ── A real resource edit still propagates, in one statement and one event ──


@pytest.mark.asyncio
async def test_a_resource_rate_edit_on_the_master_still_reaches_every_holder(pg_session, published) -> None:
    """Issue #133 as designed: the master's new rate lands on B at B's own quantity."""
    bill = await _shared_code_bill(pg_session)
    c_before = await _stored(pg_session, bill["c"])
    d_before = await _stored(pg_session, bill["d"])
    b_version = (await _stored(pg_session, bill["b"]))["version"]
    sent = [
        {**_res(SHARED, "1", "110"), "quantity": 1.0, "unit_rate": 110.0, "total": 110.0},
        {**_res("OWN-7", "2", "10"), "quantity": 2.0, "unit_rate": 10.0, "total": 20.0},
    ]

    edited = await BOQService(pg_session).update_position(
        bill["a"],
        PositionUpdate(unit_rate=Decimal("130"), metadata={"resources": sent}),
        actor_id=bill["owner"].id,
    )

    b_after = await _stored(pg_session, bill["b"])
    (b_res,) = b_after["metadata"]["resources"]
    assert b_res["unit_rate"] == 110.0, "B did not take the master's new rate"
    assert Decimal(str(b_res["quantity"])) == Decimal("3"), "B's own quantity must never propagate"
    assert b_res["total"] == 330.0
    assert Decimal(b_after["unit_rate"]) == Decimal("330")
    assert Decimal(b_after["total"]) == Decimal("660")
    assert b_after["version"] == b_version + 1
    # The diverged holder and the non-holder are left alone.
    assert await _stored(pg_session, bill["c"]) == c_before
    assert await _stored(pg_session, bill["d"]) == d_before
    # What went out is what was stored on the master.
    a_res = {r["code"]: r for r in (await _stored(pg_session, bill["a"]))["metadata"]["resources"]}
    assert a_res[SHARED]["unit_rate"] == b_res["unit_rate"]

    assert edited._link_propagation_info["resource_propagated_to"] == 1  # type: ignore[attr-defined]
    assert _names(published).count("boq.positions.resource_propagated") == 1
    assert _names(published).count("boq.position.updated") == 1, "the fan-out must not publish one event per line"
    (payload,) = [data for name, data in published if name == "boq.positions.resource_propagated"]
    assert payload["count"] == 1
    assert payload["changes"]["position_ids"] == [str(bill["b"])]
    assert payload["changes"]["positions_by_boq"] == {str(bill["boq"].id): [str(bill["b"])]}


@pytest.mark.asyncio
async def test_a_resource_rate_edit_reaches_the_holders_in_another_bill(pg_session, published) -> None:
    """The code is shared across the project, not the bill.

    The event's own ``boq_id`` is the edited line's bill, so it also says which
    lines of which other bill changed: the activity log writes one entry per
    bill from ``positions_by_boq``, and a bill's feed filters by its own id.
    """
    owner, project, boq = await _owner_project_boq(pg_session)
    other = BOQ(project_id=project.id, name="Second bill")
    pg_session.add(other)
    await pg_session.flush()
    master = _position(boq, 1, "1", [_res(SHARED, "1", "100")])
    near = _position(boq, 2, "1", [_res(SHARED, "1", "100")])
    far = _position(other, 3, "2", [_res(" shr-100 ", "2", "100")])
    kept = _position(other, 4, "1", [_res("SHR-1000", "1", "100")])
    pg_session.add_all([master, near, far, kept])
    await pg_session.flush()
    kept_before = await _stored(pg_session, kept.id)
    sent = [{**_res(SHARED, "1", "120"), "quantity": 1.0, "unit_rate": 120.0, "total": 120.0}]

    edited = await BOQService(pg_session).update_position(
        master.id, PositionUpdate(metadata={"resources": sent}), actor_id=owner.id
    )

    assert edited._link_propagation_info["resource_propagated_to"] == 2  # type: ignore[attr-defined]
    far_after = await _stored(pg_session, far.id)
    assert Decimal(str(far_after["metadata"]["resources"][0]["unit_rate"])) == Decimal("120")
    assert Decimal(far_after["unit_rate"]) == Decimal("240")
    assert await _stored(pg_session, kept.id) == kept_before, "a longer code is a different code"
    (payload,) = [data for name, data in published if name == "boq.positions.resource_propagated"]
    assert payload["boq_id"] == str(boq.id)
    assert payload["changes"]["positions_by_boq"] == {
        str(boq.id): [str(near.id)],
        str(other.id): [str(far.id)],
    }


@pytest.mark.asyncio
async def test_the_carrier_scan_keeps_every_spelling_the_code_match_accepts(pg_session) -> None:
    """The SQL narrowing may keep too much, never too little.

    The service matches a code as ``strip().casefold()``. A stored ``" shr-100 "``
    and a stored ``"ſhr-100"`` (long s, folds to ``s``) are both the same code as
    ``SHR-100``; a line without it has to be dropped, or the narrowing is not
    narrowing anything.
    """
    _owner, project, boq = await _owner_project_boq(pg_session)
    lines = [
        _position(boq, 1, "1", [_res(SHARED, "1", "1")]),
        _position(boq, 2, "1", [_res(" shr-100 ", "1", "1")]),
        _position(boq, 3, "1", [_res("ſhr-100", "1", "1")]),
        _position(boq, 4, "1", [_res("OTHER-1", "1", "1")]),
    ]
    pg_session.add_all(lines)
    await pg_session.flush()
    kept_ids = [line.id for line in lines[:3]]

    rows = await PositionRepository(pg_session).list_resource_carrier_rows(project.id, [SHARED])

    assert [r.id for r in rows] == kept_ids
    assert rows[0].meta["resources"][0]["code"] == SHARED


@pytest.mark.asyncio
async def test_the_carrier_scan_reads_like_wildcards_in_a_code_literally(pg_session) -> None:
    """``_`` and ``%`` are characters of the code, not ``LIKE`` wildcards.

    As wildcards ``WALL_50%`` would also keep ``WALLX50Y``. Keeping too much is
    allowed, so that alone is harmless, but it would mean the escaping is off,
    and an escape that is off can just as well drop the line that has the code.
    """
    _owner, project, boq = await _owner_project_boq(pg_session)
    lines = [
        _position(boq, 1, "1", [_res("wall_50%", "1", "1")]),
        _position(boq, 2, "1", [_res("WALLX50Y", "1", "1")]),
        _position(boq, 3, "1", [_res("OTHER-1", "1", "1")]),
    ]
    pg_session.add_all(lines)
    await pg_session.flush()

    rows = await PositionRepository(pg_session).list_resource_carrier_rows(project.id, ["WALL_50%"])

    assert [r.id for r in rows] == [lines[0].id]


def test_the_carrier_scan_folds_the_metadata_once_per_row() -> None:
    """One ``translate`` for all the patterns, not one per pattern.

    With an ``OR`` branch per pattern PostgreSQL rendered and folded the whole
    metadata 25 times a row for a three-code resource: 2.7 s on a 2160-position
    project, for the scan alone, on every resource edit that propagates.
    """
    cond = resource_code_prefilter(["A-1", "B-2", "C-3"], "postgresql")
    assert cond is not None
    sql = str(cond.compile(dialect=postgresql.dialect()))

    assert sql.count("translate(") == 1
    assert "LIKE ANY" in sql
    assert resource_code_prefilter(["A-1"], "sqlite") is None


# ── The PATCH path no longer loads the bill ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_price_edit_loads_its_own_line_and_not_the_bill(pg_session, published) -> None:
    """Count the Position objects the ORM builds for one price edit.

    Counting statements would not do: the old path ran a constant number of
    them, each returning the whole bill. The last block proves the counter sees
    a full load, so a green here is not a counter that counts nothing.
    """
    owner, _project, boq = await _owner_project_boq(pg_session)
    lines = [_position(boq, n, "2", [_res(f"R-{n % 7}", "1", "10"), _res("OWN-7", "2", "3")]) for n in range(60)]
    pg_session.add_all(lines)
    await pg_session.flush()
    target_id = lines[30].id
    boq_id = boq.id
    owner_id = owner.id
    del lines
    pg_session.expunge_all()

    built: list[uuid.UUID] = []

    def _on_load(target: Position, _context: Any) -> None:
        built.append(target.id)

    event.listen(Position, "load", _on_load)
    try:
        service = BOQService(pg_session)
        existing = await service.position_repo.get_by_id(target_id)
        await _verify_boq_owner(pg_session, existing.boq_id, str(owner_id), None)
        await service.update_position(target_id, PositionUpdate(unit_rate=Decimal("30")), actor_id=owner_id)
        edit_loads = len(built)

        built.clear()
        await service.get_boq(boq_id)
        full_load = len(built)
    finally:
        event.remove(Position, "load", _on_load)

    assert edit_loads <= 3, f"one price edit built {edit_loads} Position objects for a 60-line bill"
    assert full_load >= 59, f"the counter saw only {full_load} objects on a full bill load"


@pytest.mark.asyncio
async def test_a_price_edit_on_a_locked_bill_is_still_refused(pg_session) -> None:
    """The lighter lock guard answers exactly as the one it replaced."""
    bill = await _shared_code_bill(pg_session)
    await pg_session.execute(update(BOQ).where(BOQ.id == bill["boq"].id).values(is_locked=True))
    await pg_session.flush()

    with pytest.raises(HTTPException) as refused:
        await BOQService(pg_session).update_position(bill["d"], PositionUpdate(unit_rate=Decimal("1")))

    assert refused.value.status_code == 409
    assert "locked" in str(refused.value.detail)

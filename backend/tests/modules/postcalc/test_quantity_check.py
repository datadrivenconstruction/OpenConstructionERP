# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quantity check against real rows: contract quantity, measured quantity, cost effect.

The bill below goes through the life the check exists for. It is priced, one
position carries the estimating take-off its quantity was derived from, the
bill is locked (which freezes the contract quantities), unlocked to measure,
and then measured two ways: a sheet saved in the editor, which also rewrites
the bill quantity, and a GAEB X31 apply, which does not. The check must still
read the contract quantities the bill was let at.

Every figure asserted is worked out in the test by hand, from the quantities
and rates the bill was built with.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.modules.boq.gaeb_exchange_router import X31ApplyItem, X31ApplyRequest, apply_boq_gaeb_x31
from app.modules.boq.models import BOQ, BOQSnapshot, Position
from app.modules.boq.quantity_baseline import BASELINE_META_KEY, designated_baseline_id
from app.modules.boq.router import lock_boq, unlock_boq
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.postcalc.router import QuantityBaselineRequest, get_quantity_check, set_quantity_baseline
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal
EDITOR = {"role": "editor"}
MANAGER = {"role": "manager"}


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session) -> Any:
    user = User(email=f"qc-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="Controller", role="editor")
    session.add(user)
    await session.flush()
    # Plain ids from here on: the lock and unlock routes expire the whole
    # session, and an expired ORM attribute read outside the loader is IO.
    return SimpleNamespace(id=user.id)


def _sheet(formula: str) -> dict:
    return {"lines": [{"description": "site", "formula": formula, "variables": {}, "factor": "1", "sign": "+"}]}


async def _bill(
    session,
    owner: Any,
    *,
    country: str = "",
    project_currency: str = "EUR",
    bill_currency: str | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    project = Project(
        name=f"Depot {uuid.uuid4().hex[:6]}", owner_id=owner.id, currency=project_currency, country_code=country
    )
    session.add(project)
    await session.flush()
    meta = {"currency": bill_currency} if bill_currency else {}
    boq = BOQ(project_id=project.id, name="Main bill", status="draft", metadata_=meta)
    session.add(boq)
    await session.flush()
    svc = BOQService(session)
    for ordinal, unit, qty, rate in (
        ("01", "section", 0, 0),
        ("01.0010", "m3", 100, 50),
        ("01.0020", "m2", 200, 10),
        ("01.0030", "pcs", 5, 7),
        ("01.0040", "m", 0, 30),
        ("01.0050", "m2", 50, 20),
    ):
        await svc.add_position(
            PositionCreate(
                boq_id=boq.id, ordinal=ordinal, description=f"Pos {ordinal}", unit=unit, quantity=qty, unit_rate=rate
            )
        )
    await session.flush()
    rows = (await session.execute(select(Position.id, Position.ordinal).where(Position.boq_id == boq.id))).all()
    return SimpleNamespace(id=project.id), SimpleNamespace(id=boq.id), {o: SimpleNamespace(id=i) for i, o in rows}


async def _save_sheet_like_the_editor(session, owner: Any, position: Any, quantity: str, formula: str) -> None:
    """What the measurement drawer does: the sheet AND its total as the bill quantity."""
    meta = (await session.execute(select(Position.metadata_).where(Position.id == position.id))).scalar_one()
    await BOQService(session).update_position(
        position.id,
        PositionUpdate(quantity=float(quantity), metadata={**(meta or {}), "measurement": _sheet(formula)}),
        actor_id=owner.id,
    )
    await session.flush()


async def _check(session, project_id, user_id, *, boq_id=None, snapshot_id=None) -> dict:
    return await get_quantity_check(project_id, str(user_id), session, boq_id=boq_id, snapshot_id=snapshot_id)


def _by_ref(report: dict) -> dict[str, dict]:
    return {ln["ordinal"]: ln for ln in report["lines"]}


async def _measured_after_lock(session, owner: Any):
    """Take-off on 01.0050, lock, unlock, then measure 01.0010 (editor), 01.0020 (X31), 01.0040 (editor)."""
    project, boq, pos = await _bill(session, owner)
    # The estimating take-off the bill quantity of 01.0050 was derived from.
    await _save_sheet_like_the_editor(session, owner, pos["01.0050"], "50", "5*10")
    await lock_boq(boq.id, str(owner.id), EDITOR, BOQService(session))
    await unlock_boq(boq.id, str(owner.id), MANAGER, BOQService(session))

    await _save_sheet_like_the_editor(session, owner, pos["01.0010"], "112", "100+12")
    await _save_sheet_like_the_editor(session, owner, pos["01.0040"], "4", "4")
    applied = await apply_boq_gaeb_x31(
        boq.id,
        str(owner.id),
        EDITOR,
        session,
        X31ApplyRequest(
            file_name="site.x31",
            items=[X31ApplyItem(position_id=pos["01.0020"].id, quantity="180", oz="01.0020")],
        ),
    )
    assert applied["applied"] == [str(pos["01.0020"].id)]
    return project, boq, pos


# ── The maths ─────────────────────────────────────────────────────────────


async def test_over_under_not_measured_and_zero_contract_quantity(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _measured_after_lock(session, owner)

    # The editor really did overwrite the bill quantity, which is why the
    # check cannot read the contract side from the live bill.
    live = (
        await session.execute(select(Position.quantity).where(Position.boq_id == boq.id, Position.ordinal == "01.0010"))
    ).scalar_one()
    assert D(str(live)) == D("112")

    report = await _check(session, project.id, owner.id, boq_id=boq.id)
    assert report["baseline"]["kind"] == "snapshot"
    assert report["baseline"]["designated"] is True
    assert report["warnings"] == []
    lines = _by_ref(report)
    assert "01" not in lines  # the section row is not a position

    over = lines["01.0010"]
    assert D(over["contract_quantity"]) == D("100")
    assert D(over["measured_quantity"]) == D("112")
    assert over["measured_source"] == "measurement_sheet"
    assert D(over["difference"]) == D("12")
    assert D(over["difference_pct"]) == D("12.0")
    assert D(over["cost_effect"]) == D("600.00")  # 12 m3 x 50
    assert over["status"] == "over"

    under = lines["01.0020"]
    assert D(under["contract_quantity"]) == D("200")
    assert D(under["measured_quantity"]) == D("180")
    assert under["measured_source"] == "gaeb_x31"
    assert D(under["difference_pct"]) == D("-10.0")
    assert D(under["cost_effect"]) == D("-200.00")  # -20 m2 x 10
    assert under["status"] == "under"

    not_measured = lines["01.0030"]
    assert not_measured["status"] == "not_measured"
    assert not_measured["measured_quantity"] is None
    assert not_measured["cost_effect"] is None

    zero = lines["01.0040"]
    assert D(zero["contract_quantity"]) == D("0")
    assert D(zero["difference"]) == D("4")
    assert zero["difference_pct"] is None  # no ratio against nothing
    assert D(zero["cost_effect"]) == D("120.00")  # 4 m x 30
    assert zero["status"] == "over"

    totals = report["totals"]
    assert totals["line_count"] == 5
    assert totals["measured_count"] == 3
    assert totals["not_measured_count"] == 2
    assert D(totals["cost_effect_over"]) == D("720.00")
    assert D(totals["cost_effect_under"]) == D("-200.00")
    assert D(totals["cost_effect_net"]) == D("520.00")
    # 100x50 + 200x10 + 5x7 + 0x30 + 50x20
    assert D(totals["contract_value"]) == D("8035.00")


async def test_the_take_off_sheet_the_bill_was_let_with_is_not_a_measurement(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _measured_after_lock(session, owner)
    line = _by_ref(await _check(session, project.id, owner.id, boq_id=boq.id))["01.0050"]
    assert line["status"] == "not_measured"
    assert line["sheet_unchanged_since_baseline"] is True
    assert line["measured_quantity"] is None


async def test_a_site_sheet_replacing_the_take_off_is_a_measurement(session) -> None:
    owner = await _user(session)
    project, boq, pos = await _measured_after_lock(session, owner)
    await _save_sheet_like_the_editor(session, owner, pos["01.0050"], "47.5", "5*9.5")
    line = _by_ref(await _check(session, project.id, owner.id, boq_id=boq.id))["01.0050"]
    assert line["status"] == "under"
    assert line["sheet_unchanged_since_baseline"] is False
    assert D(line["difference"]) == D("-2.5")
    assert D(line["cost_effect"]) == D("-50.00")  # -2.5 m2 x 20


async def test_a_bill_in_its_own_currency_keeps_it(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _bill(session, owner, project_currency="EUR", bill_currency="CHF")
    report = await _check(session, project.id, owner.id, boq_id=boq.id)
    assert report["currency"] == "CHF"
    assert next(b for b in report["boqs"] if b["id"] == str(boq.id))["currency"] == "CHF"

    project2, boq2, _ = await _bill(session, owner, project_currency="PLN")
    assert (await _check(session, project2.id, owner.id, boq_id=boq2.id))["currency"] == "PLN"


async def test_a_position_added_after_the_baseline_is_flagged_and_priced_at_its_rate(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _measured_after_lock(session, owner)
    added = await BOQService(session).add_position(
        PositionCreate(boq_id=boq.id, ordinal="01.0060", description="Extra", unit="m", quantity=0, unit_rate=15)
    )
    await _save_sheet_like_the_editor(session, owner, added, "3", "3")
    line = _by_ref(await _check(session, project.id, owner.id, boq_id=boq.id))["01.0060"]
    assert line["in_baseline"] is False
    assert line["contract_quantity"] is None
    assert D(line["difference"]) == D("3")
    assert line["difference_pct"] is None
    assert D(line["cost_effect"]) == D("45.00")


# ── The baseline ──────────────────────────────────────────────────────────


async def test_relocking_after_measuring_does_not_move_the_baseline(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _measured_after_lock(session, owner)
    first = designated_baseline_id(await session.get(BOQ, boq.id))
    assert first is not None

    await lock_boq(boq.id, str(owner.id), EDITOR, BOQService(session))
    session.expire_all()
    again = await session.get(BOQ, boq.id)
    assert designated_baseline_id(again) == first
    count = len((await session.execute(select(BOQSnapshot.id).where(BOQSnapshot.boq_id == boq.id))).all())
    assert count == 1
    # And the check still reads the quantities the bill was let at.
    line = _by_ref(await _check(session, project.id, owner.id, boq_id=boq.id))["01.0010"]
    assert D(line["contract_quantity"]) == D("100")


async def test_a_copied_bill_gets_its_own_baseline_on_lock(session) -> None:
    owner = await _user(session)
    project, source, _pos = await _bill(session, owner)
    await lock_boq(source.id, str(owner.id), EDITOR, BOQService(session))
    source_meta = (await session.execute(select(BOQ.metadata_).where(BOQ.id == source.id))).scalar_one()
    source_baseline = designated_baseline_id(SimpleNamespace(metadata_=source_meta))
    assert source_baseline is not None

    # A copy carries the source's metadata, pointer included.
    copy = BOQ(project_id=project.id, name="Copy", status="draft", metadata_=dict(source_meta))
    session.add(copy)
    await session.flush()
    copy_id = copy.id
    await lock_boq(copy_id, str(owner.id), EDITOR, BOQService(session))
    session.expire_all()
    named = designated_baseline_id(await session.get(BOQ, copy_id))
    assert named is not None and named != source_baseline
    owner_of_named = (await session.execute(select(BOQSnapshot.boq_id).where(BOQSnapshot.id == named))).scalar_one()
    assert owner_of_named == copy_id


async def test_without_a_baseline_the_live_bill_is_used_and_says_so(session) -> None:
    owner = await _user(session)
    project, boq, pos = await _bill(session, owner)
    await _save_sheet_like_the_editor(session, owner, pos["01.0010"], "112", "100+12")
    report = await _check(session, project.id, owner.id, boq_id=boq.id)
    assert report["baseline"]["kind"] == "current"
    assert "no_baseline" in report["warnings"]
    line = _by_ref(report)["01.0010"]
    # The editor wrote 112 into the bill, so "contract" equals "measured" and
    # the line says the contract figure may already be the measurement.
    assert line["status"] == "matches"
    assert line["contract_quantity_may_be_measured"] is True


async def test_a_deleted_baseline_snapshot_falls_back_and_says_so(session) -> None:
    owner = await _user(session)
    project, boq, _pos = await _measured_after_lock(session, owner)
    await session.execute(delete(BOQSnapshot).where(BOQSnapshot.boq_id == boq.id))
    await session.flush()
    report = await _check(session, project.id, owner.id, boq_id=boq.id)
    assert report["baseline"]["kind"] == "current"
    assert "baseline_snapshot_missing" in report["warnings"]
    assert report["designated_snapshot_id"] is None


async def test_freeze_designate_and_clear_through_the_endpoint(session) -> None:
    owner = await _user(session)
    project, boq, pos = await _bill(session, owner)
    frozen = await set_quantity_baseline(
        project.id, str(owner.id), session, QuantityBaselineRequest(boq_id=boq.id, freeze=True)
    )
    assert frozen["baseline"]["kind"] == "snapshot"
    first_id = frozen["baseline"]["snapshot_id"]

    await _save_sheet_like_the_editor(session, owner, pos["01.0010"], "112", "100+12")
    second = await BOQService(session).create_snapshot(boq.id, name="After site", user_id=owner.id)

    # Reading against another snapshot is a view, it does not move the pointer.
    viewed = await _check(session, project.id, owner.id, boq_id=boq.id, snapshot_id=second.id)
    assert viewed["baseline"]["snapshot_id"] == str(second.id)
    assert viewed["baseline"]["designated"] is False
    assert viewed["designated_snapshot_id"] == first_id

    moved = await set_quantity_baseline(
        project.id, str(owner.id), session, QuantityBaselineRequest(boq_id=boq.id, snapshot_id=second.id)
    )
    assert moved["designated_snapshot_id"] == str(second.id)

    cleared = await set_quantity_baseline(project.id, str(owner.id), session, QuantityBaselineRequest(boq_id=boq.id))
    assert cleared["baseline"]["kind"] == "current"
    row = await session.get(BOQ, boq.id)
    assert BASELINE_META_KEY not in (row.metadata_ or {})


# ── Access ────────────────────────────────────────────────────────────────


async def test_a_stranger_gets_404_on_read_and_write(session) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    project, boq, _pos = await _bill(session, owner)
    with pytest.raises(HTTPException) as read:
        await _check(session, project.id, stranger.id, boq_id=boq.id)
    assert read.value.status_code == 404
    with pytest.raises(HTTPException) as write:
        await set_quantity_baseline(
            project.id, str(stranger.id), session, QuantityBaselineRequest(boq_id=boq.id, freeze=True)
        )
    assert write.value.status_code == 404
    assert (await session.execute(select(BOQSnapshot.id).where(BOQSnapshot.boq_id == boq.id))).first() is None


async def test_a_bill_or_snapshot_of_another_project_is_404(session) -> None:
    owner = await _user(session)
    victim_owner = await _user(session)
    mine, my_boq, _ = await _bill(session, owner)
    _theirs, their_boq, _ = await _bill(session, victim_owner)
    their_snap = await BOQService(session).create_snapshot(their_boq.id, name="theirs", user_id=victim_owner.id)

    # My project id, their bill: access to my project must not reach their bill.
    with pytest.raises(HTTPException) as read:
        await _check(session, mine.id, owner.id, boq_id=their_boq.id)
    assert read.value.status_code == 404
    with pytest.raises(HTTPException) as snap_read:
        await _check(session, mine.id, owner.id, boq_id=my_boq.id, snapshot_id=their_snap.id)
    assert snap_read.value.status_code == 404
    with pytest.raises(HTTPException) as write:
        await set_quantity_baseline(
            mine.id, str(owner.id), session, QuantityBaselineRequest(boq_id=their_boq.id, freeze=True)
        )
    assert write.value.status_code == 404
    with pytest.raises(HTTPException) as point:
        await set_quantity_baseline(
            mine.id, str(owner.id), session, QuantityBaselineRequest(boq_id=my_boq.id, snapshot_id=their_snap.id)
        )
    assert point.value.status_code == 404
    session.expire_all()
    assert designated_baseline_id(await session.get(BOQ, my_boq.id)) is None
    assert designated_baseline_id(await session.get(BOQ, their_boq.id)) is None

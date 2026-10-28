# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The release guard on the tender award (``TenderingService.apply_winner``).

An award above the item's release (plus tolerance) is warned and proceeds when
the matrix enforces ``warn``, is refused with 409 and leaves the package and
bill untouched under ``block``, and is silent under ``off`` or when no guard is
registered. An award within the release is ``ok`` in every mode.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import commitment_guard
from app.modules.commitment_release import guard
from app.modules.commitment_release.guard import check_document, enforcement_of
from app.modules.commitment_release.models import CommitmentItem
from app.modules.commitment_release.service import CommitmentService
from tests._pg import isolated_engine
from tests.pg.commitment_fixtures import World, build_world, decide, guard_rows, item, link, request

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    commitment_guard.register_commitment_guard(check_document, enforcement_of)
    try:
        async with isolated_engine() as engine:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            monkeypatch.setattr(guard, "session_factory", factory)
            yield await build_world(factory)
    finally:
        commitment_guard.unregister_commitment_guard()


async def _package(w: World, bid_total: str) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.boq.models import BOQ
    from app.modules.tendering.models import TenderBid, TenderPackage

    async with w.factory() as s:
        boq = BOQ(project_id=w.project_id, name="Bill")
        s.add(boq)
        await s.flush()
        pkg = TenderPackage(project_id=w.project_id, boq_id=boq.id, name="Structure", status="evaluating")
        s.add(pkg)
        await s.flush()
        bid = TenderBid(package_id=pkg.id, company_name="Sub Ltd", total_amount=bid_total, currency="EUR")
        s.add(bid)
        await s.commit()
        return pkg.id, bid.id


async def _released_item(w: World, amount: str) -> uuid.UUID:
    iid = await item(w, amount=amount)
    d = await request(w, iid, amount)
    await decide(w, d, w.pm)
    return iid


async def _enforcement(w: World, mode: str) -> None:
    async with w.factory() as s:
        await CommitmentService(s).set_matrix(
            w.project_id, actor_id=w.manager, tenant_id=str(w.manager), enforcement=mode
        )
        await s.commit()


async def _award(w: World, pkg: uuid.UUID, bid: uuid.UUID) -> dict:
    from app.modules.tendering.service import TenderingService

    async with w.factory() as s:
        out = await TenderingService(s).apply_winner(pkg, bid, awarded_by=str(w.manager))
        await s.commit()
        return out


async def _package_status(w: World, pkg: uuid.UUID) -> str:
    from app.modules.tendering.models import TenderPackage

    async with w.factory() as s:
        return (await s.get(TenderPackage, pkg)).status


async def _bid_status(w: World, bid: uuid.UUID) -> str:
    from app.modules.tendering.models import TenderBid

    async with w.factory() as s:
        return (await s.get(TenderBid, bid)).status


async def test_preview_check_records_nothing(world: World) -> None:
    from decimal import Decimal

    iid = await _released_item(world, "40000")
    pkg, _bid = await _package(world, "60000")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "block")
    async with world.factory() as s:
        out = await CommitmentService(s).check_document(
            world.project_id, kind="tender_package", document_id=pkg, new_amount=Decimal("60000"), currency="EUR"
        )
        await s.commit()
    assert out["result"] == "block"
    assert await guard_rows(world, pkg) == []


async def test_award_over_release_is_warned_and_proceeds_under_warn(world: World) -> None:
    iid = await _released_item(world, "40000")
    pkg, bid = await _package(world, "60000")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "warn")
    out = await _award(world, pkg, bid)
    assert out["commitment_guard"]["result"] == "warn"
    assert out["commitment_guard"]["reasons"][0]["code"] == "commitment_not_released"
    assert out["commitment_guard"]["item_id"] == str(iid)
    assert await _package_status(world, pkg) == "awarded"
    assert await guard_rows(world, pkg) == ["guard_warn"]


async def test_award_over_release_is_refused_under_block_and_nothing_moves(world: World) -> None:
    iid = await _released_item(world, "40000")
    pkg, bid = await _package(world, "60000")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "block")
    with pytest.raises(HTTPException) as exc:
        await _award(world, pkg, bid)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "commitment_not_released"
    # The refused award left nothing behind, but the refusal itself is on record.
    assert await _package_status(world, pkg) == "evaluating"
    assert await _bid_status(world, bid) != "accepted"
    assert await guard_rows(world, pkg) == ["guard_block"]


async def test_award_within_release_and_tolerance_is_ok_under_block(world: World) -> None:
    iid = await _released_item(world, "40000")
    # 40,000 + 2% tolerance = 40,800.
    pkg, bid = await _package(world, "40800")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "block")
    out = await _award(world, pkg, bid)
    assert "commitment_guard" not in out
    assert await _package_status(world, pkg) == "awarded"
    assert await guard_rows(world, pkg) == []


async def test_unreleased_item_blocks_the_award(world: World) -> None:
    iid = await item(world, amount="40000")
    pkg, bid = await _package(world, "1000")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "block")
    with pytest.raises(HTTPException):
        await _award(world, pkg, bid)
    async with world.factory() as s:
        assert (await s.get(CommitmentItem, iid)).status == "planned"


async def test_off_mode_and_no_registered_guard_are_silent(world: World) -> None:
    iid = await _released_item(world, "40000")
    pkg, bid = await _package(world, "60000")
    await link(world, iid, "tender_package", pkg)
    await _enforcement(world, "off")
    assert "commitment_guard" not in await _award(world, pkg, bid)

    pkg2, bid2 = await _package(world, "60000")
    await link(world, iid, "tender_package", pkg2)
    await _enforcement(world, "block")
    commitment_guard.unregister_commitment_guard()
    assert await _award(world, pkg2, bid2)
    assert await _package_status(world, pkg2) == "awarded"

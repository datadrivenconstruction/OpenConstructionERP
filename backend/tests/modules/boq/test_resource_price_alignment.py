"""A bill's resource prices are aligned with the region's price sheet only where the estimator selects.

Worked example: the sheet prices cement ``CEM-1`` at 120 EUR and mason
``LAB-1`` at 30 EUR.

* P1, quantity 10: cement 0.3 at 100, mason 2 at 25, unit rate 80.00.
  Cement drifts +20 (bill effect 10 x 0.3 x 20 = 60.00), mason +5 (100.00).
* P2, quantity 4: cement 1.5 at 110. Bill effect 4 x 1.5 x 10 = 60.00.
* P3: cement priced in USD. Never aligned, counted as skipped.

Cement: old prices 100 and 110, 2 positions, effect 120.00. Aligning only
cement gives P1 0.3 x 120 + 2 x 25 = 86.00 (total 860.00) and P2 180.00
(total 720.00); the mason row keeps 25.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.price_alignment import align_rows, apply_alignment, find_drift, preview_alignment
from app.modules.boq.validators import AlignedPriceNotInRate
from tests._pg import transactional_session

REGION = "ZZ_ALIGN"
SHEET = {"CEM-1": (Decimal("120"), "EUR", "Cement"), "LAB-1": (Decimal("30"), "EUR", "Mason")}


def _row(code: str, qty: float, rate: float, ccy: str = "") -> dict:
    return {"code": code, "name": code, "quantity": qty, "unit_rate": rate, "currency": ccy}


def _positions() -> list[dict]:
    return [
        {"id": "p1", "quantity": "10", "metadata": {"resources": [_row("CEM-1", 0.3, 100), _row("LAB-1", 2, 25)]}},
        {"id": "p2", "quantity": "4", "metadata": {"resources": [_row("CEM-1", 1.5, 110, "EUR")]}},
        {"id": "p3", "quantity": "1", "metadata": {"resources": [_row("CEM-1", 1, 90, "USD")]}},
    ]


def test_leaf_split_is_linear_on_a_large_bill() -> None:
    import time
    from types import SimpleNamespace

    from app.modules.boq.price_alignment import _leaf_inputs, _leaves

    root = uuid.uuid4()
    rows = [SimpleNamespace(id=root, parent_id=None, quantity="1", metadata_={})]
    rows += [SimpleNamespace(id=uuid.uuid4(), parent_id=root, quantity="1", metadata_={}) for _ in range(20_000)]
    started = time.perf_counter()
    leaves = _leaves(rows)
    assert time.perf_counter() - started < 1.0
    assert len(leaves) == 20_000
    assert root not in {p.id for p in leaves}
    assert [r["id"] for r in _leaf_inputs(rows)] == [p.id for p in leaves]


def test_drift_follows_the_worked_example() -> None:
    groups, skipped = find_drift(_positions(), SHEET)
    by_key = {g["resource_key"]: g for g in groups}
    assert skipped == 1
    cem = by_key["CEM-1"]
    assert cem["old_prices"] == [Decimal("100.00"), Decimal("110.00")]
    assert (cem["positions"], cem["rows"], cem["amount_delta"]) == (2, 2, Decimal("120.00"))
    assert by_key["LAB-1"]["amount_delta"] == Decimal("100.00")


def test_only_selected_resources_are_aligned() -> None:
    rows, changes = align_rows(_positions()[0]["metadata"]["resources"], SHEET, {"CEM-1"})
    assert [c["resource_key"] for c in changes] == ["CEM-1"]
    assert rows[0]["unit_rate"] == 120.0
    assert rows[1]["unit_rate"] == 25


@pytest.mark.asyncio
async def test_rule_flags_a_kept_rate() -> None:
    from app.core.validation.engine import ValidationContext

    ctx = ValidationContext(
        data={
            "positions": [
                {"id": "a", "ordinal": "01", "metadata": {"price_alignment": {"rate_kept": True, "rows": [{}]}}},
                {"id": "b", "ordinal": "02", "metadata": {"price_alignment": {"rate_kept": False}}},
            ]
        }
    )
    results = await AlignedPriceNotInRate().validate(ctx)
    assert [r.element_ref for r in results] == ["a"]


@pytest.mark.asyncio
async def test_apply_rewrites_selected_rows_and_rederives_rates() -> None:
    from sqlalchemy import select

    from app.modules.boq.models import BOQ, Position
    from app.modules.costs.models import ResourcePrice

    async with transactional_session(disable_fks=True) as session:
        for key, (price, ccy, name) in SHEET.items():
            session.add(
                ResourcePrice(
                    region=REGION,
                    resource_key=key,
                    resource_code=key,
                    resource_name=name,
                    resource_type="material",
                    unit_price=str(price),
                    currency=ccy,
                    source="user",
                    is_active=True,
                )
            )
        boq = BOQ(id=uuid.uuid4(), project_id=uuid.uuid4(), name="Align")
        session.add(boq)
        await session.flush()
        ids = []
        for i, pos in enumerate(_positions()):
            p = Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                ordinal=f"0{i + 1}",
                description=pos["id"],
                unit="m3",
                quantity=pos["quantity"],
                unit_rate="80.00",
                total="0",
                source="manual",
                metadata_=pos["metadata"],
            )
            session.add(p)
            ids.append(p.id)
        await session.flush()

        preview = await preview_alignment(session, boq.id, REGION)
        assert preview["amount_delta_total"] == Decimal("220.00")
        assert preview["rows_skipped_currency"] == 1

        user = str(uuid.uuid4())
        result = await apply_alignment(session, boq.id, REGION, ["CEM-1"], user_id=user)
        assert (result["positions_changed"], result["rows_changed"], result["rates_kept"]) == (2, 2, 0)

        rows = {p.id: p for p in (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars()}
        for p in rows.values():
            await session.refresh(p)
        p1, p2, p3 = (rows[i] for i in ids)
        assert (Decimal(p1.unit_rate), Decimal(p1.total)) == (Decimal("86.00"), Decimal("860.00"))
        assert p1.metadata_["resources"][1]["unit_rate"] == 25
        assert Decimal(p2.unit_rate) == Decimal("180.00")
        assert p3.metadata_["resources"][0]["unit_rate"] == 90
        assert p1.metadata_["price_alignment"]["rows"][0]["to"] == "120"


@pytest.mark.asyncio
async def test_another_users_bill_is_refused_on_both_alignment_routes() -> None:
    from fastapi import HTTPException

    from app.modules.boq.models import BOQ
    from app.modules.boq.router import apply_price_alignment, preview_price_alignment
    from app.modules.boq.schemas import PriceAlignmentApplyRequest
    from app.modules.projects.models import Project

    async with transactional_session(disable_fks=True) as session:
        owner, stranger = uuid.uuid4(), str(uuid.uuid4())
        project = Project(id=uuid.uuid4(), name="P", owner_id=owner)
        boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="B")
        session.add_all([project, boq])
        await session.flush()
        with pytest.raises(HTTPException) as exc:
            await preview_price_alignment(boq.id, stranger, {}, session, region=REGION)
        assert exc.value.status_code == 404
        body = PriceAlignmentApplyRequest(region=REGION, resource_keys=["CEM-1"])
        with pytest.raises(HTTPException) as exc:
            await apply_price_alignment(boq.id, body, stranger, {}, session)
        assert exc.value.status_code == 404
        preview = await preview_price_alignment(boq.id, str(owner), {}, session, region=REGION)
        assert preview.rows == []

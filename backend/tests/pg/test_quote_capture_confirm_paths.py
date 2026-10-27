# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: a reviewed quote becomes a bid, a price list or a draft PO, with its audit trail.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.quote_capture.demo import seed_demo_quotes
from app.modules.quote_capture.schemas import HeaderFieldUpdate, LineUpdate, QuoteUpdate
from app.modules.quote_capture.service import QuoteCaptureService
from app.modules.quote_capture.validators import register_quote_capture_rules
from app.modules.supplier_catalogs.models import CatalogEntry, PriceList
from app.modules.tendering.models import TenderBid
from tests.pg.tender_award_fixtures import _bill, _package, _project

pytestmark = pytest.mark.asyncio


def _text(extra: str = "") -> str:
    issued = (date.today() - timedelta(days=2)).isoformat()
    return (
        "Supplier: Alder Facade Works\n"
        f"Quote date: {issued}\n"
        "Valid for 30 days\n"
        "1  Wall formwork  10  m3  48.00  480.00\n"
        "2  Slab concrete  10  m2  52.00  520.00\n"
        f"{extra}"
        "Total net 1,000.00 EUR\n"
    )


async def _setup(pg_session, extra: str = ""):
    register_quote_capture_rules()
    project = await _project(pg_session)
    boq, pos = await _bill(
        pg_session, project, [("a", "01", "Wall formwork", "m3", None), ("b", "02", "Slab concrete", "m2", None)]
    )
    package = await _package(pg_session, project, boq)
    package.status = "evaluating"
    svc = QuoteCaptureService(pg_session)
    quote = await svc.create_from_text(
        project_id=project.id, package_id=package.id, text=_text(extra), filename="q.txt", user_id=None,
        locale="en", llm=False,
    )  # fmt: skip
    return svc, project, package, pos, quote


async def test_capture_matches_lines_to_the_package_scope(pg_session) -> None:
    _svc, _project_row, _package_row, pos, quote = await _setup(pg_session)
    assert quote.extraction_engine == "rules"
    assert [ln["match"]["position_id"] for ln in quote.lines] == [str(pos["a"].id), str(pos["b"].id)]
    assert quote.supplier_name == "Alder Facade Works"


async def test_confirm_as_bid_keeps_the_audit_trail(pg_session) -> None:
    svc, _p, package, pos, quote = await _setup(pg_session)
    quote = await svc.update_line(quote, "L1", LineUpdate(unit_rate="47.00", total="470.00", reviewed=True), "u1")
    quote = await svc.update(quote, QuoteUpdate(header={"quote_total": HeaderFieldUpdate(value="990.00")}), "u1")
    result = await svc.confirm(quote, "bid", None, accept_warnings=True)

    bid = await pg_session.get(TenderBid, uuid.UUID(result["target_id"]))
    assert bid.package_id == package.id and bid.total_amount == "990.00"
    assert {li["position_id"] for li in bid.line_items} == {str(pos["a"].id), str(pos["b"].id)}
    audit = {a["field"]: a for a in bid.metadata_["quote_capture"]["audit"]}
    assert audit["line.L1.unit_rate"] == {"field": "line.L1.unit_rate", "machine": "48.00", "human": "47.00"}
    assert audit["header.quote_total"]["machine"] == "1000.00"
    assert quote.status == "confirmed" and quote.confirmation["target"] == "bid"

    with pytest.raises(HTTPException) as exc:
        await svc.update_line(quote, "L1", LineUpdate(reviewed=False), "u1")
    assert exc.value.status_code == 409


async def test_unacknowledged_exclusion_blocks_the_confirm(pg_session) -> None:
    svc, *_rest, quote = await _setup(pg_session, extra="Excluding scaffolding.\n")
    note = next(n for n in quote.notes if n["kind"] == "exclusion")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm(quote, "bid", None, accept_warnings=True)
    assert exc.value.status_code == 409
    assert any(f["rule_id"] == "quote_capture.exclusions_acknowledged" for f in exc.value.detail["findings"])

    quote = await svc.update(quote, QuoteUpdate(acknowledge_notes=[note["id"]]), "u1")
    result = await svc.confirm(quote, "bid", None, accept_warnings=True)
    assert result["target"] == "bid"


async def test_confirm_as_price_list(pg_session) -> None:
    svc, *_rest, quote = await _setup(pg_session)
    result = await svc.confirm(quote, "price_list", None, accept_warnings=True)
    plist = await pg_session.get(PriceList, uuid.UUID(result["target_id"]))
    entries = (
        (await pg_session.execute(select(CatalogEntry).where(CatalogEntry.price_list_id == plist.id))).scalars().all()
    )
    assert plist.status == "draft" and plist.currency == "EUR"
    assert sorted(str(e.unit_price.normalize()) for e in entries) == ["48", "52"]


async def test_confirm_as_po_draft(pg_session) -> None:
    svc, project, *_rest, quote = await _setup(pg_session)
    result = await svc.confirm(quote, "po_draft", None, accept_warnings=True)
    po = await pg_session.get(PurchaseOrder, uuid.UUID(result["target_id"]))
    assert po.project_id == project.id and po.status == "draft"
    items = (
        (await pg_session.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id))).scalars().all()
    )
    assert len(items) == 2
    assert po.metadata_["quote_capture"]["quote_id"] == str(quote.id)


async def test_warnings_need_explicit_acceptance(pg_session) -> None:
    svc, *_rest, quote = await _setup(pg_session)
    quote = await svc.update_line(quote, "L1", LineUpdate(clear_match=True), "u1")
    with pytest.raises(HTTPException) as exc:
        await svc.confirm(quote, "po_draft", None, accept_warnings=False)
    assert exc.value.status_code == 409


async def test_demo_quotes_level_with_a_gap_and_an_exclusion(pg_session) -> None:
    register_quote_capture_rules()
    project = await _project(pg_session)
    boq, _pos = await _bill(
        pg_session,
        project,
        [
            ("a", "01", "Wall formwork", "m3", None),
            ("b", "02", "Slab concrete", "m2", None),
            ("c", "03", "Steel rebar", "t", None),
        ],
    )
    package = await _package(pg_session, project, boq)
    assert await seed_demo_quotes(pg_session, project_id=project.id) == 3
    assert await seed_demo_quotes(pg_session, project_id=project.id) == 0, "seeding twice adds nothing"
    out = await QuoteCaptureService(pg_session).levelling(package.id)
    by = {q["supplier"]: q for q in out["quotes"]}
    assert by["Birchway Building Services"]["gap_rows"] == 1
    assert by["Alder Facade Works"]["exclusions"] == 1
    assert all(q["gap_rows"] == 0 for name, q in by.items() if name != "Birchway Building Services")
    assert {q["rank"] for q in out["quotes"]} == {1, 2, 3}

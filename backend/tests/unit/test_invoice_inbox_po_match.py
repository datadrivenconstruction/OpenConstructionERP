# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Supplier invoice inbox: order link, goods-receipt match, e-invoice intake, cost actuals.

No database: the service is driven with a fake session and a recording cost spine, so the
outcomes (match findings, acknowledgement gate, what is posted where) are asserted exactly.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.einvoice.inbound import parse_inbound
from app.modules.finance import invoice_capture_logic as logic
from app.modules.finance import invoice_capture_service as svc_mod
from app.modules.finance import router as _finance_router  # noqa: F401  (import order: router first)
from app.modules.finance.invoice_capture_router import capture_router
from app.modules.finance.invoice_capture_service import InvoiceCaptureService

# ── Pure checks ──────────────────────────────────────────────────────────────


def _po(**kw: Any) -> dict:
    base = {"number": "PO-0007", "status": "issued", "vendor_contact_id": "c1", "currency_code": "EUR"}
    base.update(kw)
    return base


def test_po_reference_extracted_from_text() -> None:
    assert logic.extract_po_reference("Invoice 12\nPurchase order: PO-2026-0007\nTotal 10.00") == "PO-2026-0007"
    assert logic.extract_po_reference("Bestellnummer B-4711") == "B-4711"
    assert logic.extract_po_reference("no order here, invoice 2026-14") == ""


def test_no_link_and_no_reference_is_silent() -> None:
    assert logic.validate_po_link(po=None, po_reference="", supplier_contact_id=None, currency_code="EUR") == []


def test_unresolved_reference_warns() -> None:
    f = logic.validate_po_link(po=None, po_reference="PO-9", supplier_contact_id=None, currency_code="EUR")
    assert [(x.severity, x.code) for x in f] == [("warning", "po_reference_unresolved")]
    assert "PO-9" in f[0].message


def test_clean_link_has_no_findings() -> None:
    assert logic.validate_po_link(po=_po(), po_reference="PO-0007", supplier_contact_id="c1", currency_code="eur") == []


@pytest.mark.parametrize(
    ("po", "supplier", "currency", "code"),
    [
        (_po(status="draft"), "c1", "EUR", "po_not_open"),
        (_po(status="cancelled"), "c1", "EUR", "po_not_open"),
        (_po(), "other", "EUR", "po_supplier_mismatch"),
        (_po(), "c1", "USD", "po_currency_mismatch"),
        ({}, "c1", "EUR", "po_missing"),
    ],
)
def test_link_mismatches_are_errors(po: dict, supplier: str, currency: str, code: str) -> None:
    f = logic.validate_po_link(po=po, po_reference="", supplier_contact_id=supplier, currency_code=currency)
    assert [x.code for x in f] == [code]
    assert f[0].is_error


def test_match_report_keeps_only_failed_rules_with_their_message() -> None:
    results = [
        {"rule_id": "procurement.invoice_within_order", "passed": True, "severity": "warning", "message": "ok"},
        {
            "rule_id": "procurement.invoice_quantity_received",
            "passed": False,
            "severity": "warning",
            "message": "Line 1 invoices 20 kg, 16 kg received.",
        },
    ]
    f = logic.match_report_findings(results)
    assert [(x.severity, x.code) for x in f] == [("warning", "po_match:procurement.invoice_quantity_received")]
    assert f[0].message == "Line 1 invoices 20 kg, 16 kg received."


def test_unacknowledged_match_blocks_until_acknowledged() -> None:
    match = [logic.Finding("warning", "po_match:r1", "m")]
    assert [x.code for x in logic.match_unacknowledged(match, set())] == ["po_match_unacknowledged"]
    assert logic.match_unacknowledged(match, {"po_match:r1"}) == []
    assert logic.match_unacknowledged([], set()) == []


# ── Inbound e-invoice: order reference and lines ─────────────────────────────

_UBL = b"""<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>R-118</cbc:ID><cbc:IssueDate>2026-03-01</cbc:IssueDate><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:OrderReference><cbc:ID>PO-0007</cbc:ID></cac:OrderReference>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Stahl GmbH</cbc:RegistrationName>
  </cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:TaxTotal><cbc:TaxAmount>19.00</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>100.00</cbc:TaxExclusiveAmount>
  <cbc:TaxInclusiveAmount>119.00</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>50</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Reinforcement B500B</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount>2.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</Invoice>"""


def test_inbound_ubl_carries_order_reference_and_lines() -> None:
    inv = parse_inbound(_UBL)
    assert inv.order_reference == "PO-0007"
    assert inv.lines == [
        {"description": "Reinforcement B500B", "quantity": "50", "unit_rate": "2.00", "amount": "100.00"}
    ]


def test_inbox_extract_uses_the_einvoice_parser() -> None:
    engine, _text, fields, conf = InvoiceCaptureService._extract_einvoice(_UBL)
    assert engine == "einvoice_ubl"
    assert fields["po_reference"] == "PO-0007"
    assert fields["line_items"][0]["description"] == "Reinforcement B500B"
    assert fields["invoice_number"] == "R-118"
    assert conf["invoice_number"] == 1.0


# ── Permissions ──────────────────────────────────────────────────────────────


def _perm(path: str, method: str) -> str:
    for route in capture_router.routes:
        if route.path == path and method in route.methods:
            for dep in route.dependant.dependencies:
                perm = getattr(dep.call, "permission", None)
                if perm:
                    return perm
    raise AssertionError(f"{method} {path} not found")


def test_link_needs_capture_create_and_approve_stays_manager_only() -> None:
    assert _perm("/inbox/{capture_id}/purchase-order", "PUT") == "finance.capture.create"
    assert _perm("/inbox/{capture_id}/approve", "POST") == "finance.approve"
    assert _perm("/inbox/{capture_id}/post", "POST") == "finance.gl.post_journal"


# ── Service with a fake session ──────────────────────────────────────────────


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _FakeSession:
    def __init__(self, cost_lines: dict[str, uuid.UUID] | None = None) -> None:
        self.cost_lines = cost_lines or {}

    async def execute(self, _stmt: Any) -> _Rows:
        return _Rows(list(self.cost_lines.items()))

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def flush(self) -> None:
        return None


def _service(session: Any) -> InvoiceCaptureService:
    s = InvoiceCaptureService.__new__(InvoiceCaptureService)
    s.session = session
    return s


def _row(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "invoice_number": "R-118",
        "currency_code": "EUR",
        "booking_cost_code": "03.10",
        "line_items": [],
        "metadata_": {},
        "purchase_order_id": None,
        "posted_invoice_id": None,
        "amount_net": Decimal("100"),
        "supplier_contact_id": "c1",
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_lines_that_add_up_post_one_actual_each_on_their_cost_line() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    service = _service(_FakeSession({"03.10": a, "03.20": b}))
    row = _row(
        line_items=[
            {"description": "x", "amount": "60.00", "cost_code": "03.10"},
            {"description": "y", "amount": "40.00", "cost_code": "03.20"},
        ]
    )
    out = await service._resolve_cost_lines(row, row.project_id, Decimal("100"))
    assert out == [(0, a, Decimal("60.00")), (1, b, Decimal("40.00"))]


@pytest.mark.asyncio
async def test_lines_that_do_not_add_up_post_the_net_on_the_booking_code() -> None:
    a = uuid.uuid4()
    service = _service(_FakeSession({"03.10": a}))
    row = _row(line_items=[{"description": "x", "amount": "60.00"}])
    out = await service._resolve_cost_lines(row, row.project_id, Decimal("100"))
    assert out == [(None, a, Decimal("100"))]


@pytest.mark.asyncio
async def test_unknown_cost_code_still_posts_uncategorised() -> None:
    service = _service(_FakeSession({}))
    row = _row()
    assert await service._resolve_cost_lines(row, row.project_id, Decimal("100")) == [(None, None, Decimal("100"))]


@pytest.mark.asyncio
async def test_actuals_go_to_the_spine_once_per_line_with_stable_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _Spine:
        def __init__(self, _session: Any) -> None: ...

        async def post_actual_to_budget_line(self, **kw: Any) -> None:
            calls.append(kw)

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _id: Any) -> Any:
            return SimpleNamespace(currency="EUR", fx_rates=None, metadata_={})

    monkeypatch.setattr("app.modules.costmodel.service.CostSpineService", _Spine)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo)
    a = uuid.uuid4()
    service = _service(_FakeSession())
    row = _row()
    result = await service._post_actuals(
        row, uuid.uuid4(), row.project_id, [(None, a, Decimal("100")), (1, None, Decimal("0"))]
    )
    assert result["posted"] == 1
    assert len(calls) == 1
    call = calls[0]
    assert call["cost_line_id"] == a
    assert call["source_kind"] == "inbox_invoice"
    assert call["source_ref"] == f"{row.id}:0"
    assert Decimal(call["amount_base"]) == Decimal("100.00")
    assert row.metadata_["cost_actuals"]["posted"] == 1


@pytest.mark.asyncio
async def test_foreign_amount_without_fx_rate_is_not_posted_as_base(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _Spine:
        def __init__(self, _session: Any) -> None: ...

        async def post_actual_to_budget_line(self, **kw: Any) -> None:
            calls.append(kw)

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _id: Any) -> Any:
            return SimpleNamespace(currency="EUR", fx_rates=None, metadata_={})

    monkeypatch.setattr("app.modules.costmodel.service.CostSpineService", _Spine)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo)
    row = _row(currency_code="USD")
    result = await _service(_FakeSession())._post_actuals(
        row, uuid.uuid4(), row.project_id, [(None, uuid.uuid4(), Decimal("100"))]
    )
    assert calls == []
    assert result["posted"] == 0
    assert "USD" in result["errors"][0]


@pytest.mark.asyncio
async def test_a_spine_refusal_does_not_strand_the_booking(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Spine:
        def __init__(self, _session: Any) -> None: ...

        async def post_actual_to_budget_line(self, **_kw: Any) -> None:
            raise HTTPException(400, "Project has no base currency configured")

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _id: Any) -> Any:
            return SimpleNamespace(currency="", fx_rates=None, metadata_={})

    monkeypatch.setattr("app.modules.costmodel.service.CostSpineService", _Spine)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo)
    row = _row()
    result = await _service(_FakeSession())._post_actuals(
        row, uuid.uuid4(), row.project_id, [(None, None, Decimal("100"))]
    )
    assert result["posted"] == 0
    assert "base currency" in result["errors"][0]


class _FakeProcurement:
    def __init__(self, po: Any, results: list[dict]) -> None:
        self.po, self.results = po, results
        self.seen: dict = {}

    async def get_po(self, _id: Any) -> Any:
        if self.po is None:
            raise HTTPException(404, "Purchase order not found")
        return self.po

    async def check_invoice_against_po(self, _id: Any, **kw: Any) -> dict:
        self.seen = kw
        return {"results": self.results}


def _purchase_order(**kw: Any) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "po_number": "PO-0007",
        "status": "issued",
        "vendor_contact_id": "c1",
        "currency_code": "EUR",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _validate_with(monkeypatch: pytest.MonkeyPatch, proc: _FakeProcurement) -> InvoiceCaptureService:
    service = _service(_FakeSession())
    monkeypatch.setattr(InvoiceCaptureService, "_procurement", staticmethod(lambda _s: proc))
    return service


@pytest.mark.asyncio
async def test_match_uses_the_procurement_matcher_with_net_and_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProcurement(_purchase_order(), [])
    service = _validate_with(monkeypatch, proc)
    row = _row(purchase_order_id=uuid.uuid4(), line_items=[{"description": "x", "quantity": "5"}])
    summary, results = await service._po_summary_and_match(row)
    assert summary["number"] == "PO-0007" and results == []
    assert proc.seen["invoice_net"] == "100"
    assert proc.seen["lines"] == [{"description": "x", "quantity": "5"}]
    assert proc.seen["invoice_ref"] == "R-118"


@pytest.mark.asyncio
async def test_deleted_order_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _validate_with(monkeypatch, _FakeProcurement(None, []))
    summary, _ = await service._po_summary_and_match(_row(purchase_order_id=uuid.uuid4()))
    assert summary == {}


@pytest.mark.asyncio
async def test_link_rejects_other_project_and_draft_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row(status="captured")
    service = _service(_FakeSession())

    async def _get(_id: Any) -> Any:
        return row

    monkeypatch.setattr(service, "get", _get)
    monkeypatch.setattr(service, "_guard_editable", lambda _r: None)
    monkeypatch.setattr(service, "_snapshot", lambda _r: {})

    foreign = _purchase_order()  # different project
    monkeypatch.setattr(InvoiceCaptureService, "_procurement", staticmethod(lambda _s: _FakeProcurement(foreign, [])))
    with pytest.raises(HTTPException) as exc:
        await service.link_purchase_order(row.id, foreign.id, None)
    assert exc.value.status_code == 404

    draft = _purchase_order(project_id=row.project_id, status="draft")
    monkeypatch.setattr(InvoiceCaptureService, "_procurement", staticmethod(lambda _s: _FakeProcurement(draft, [])))
    with pytest.raises(HTTPException) as exc:
        await service.link_purchase_order(row.id, draft.id, None)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "invoice_capture_po_not_billable"


@pytest.mark.asyncio
async def test_link_sets_reference_and_supplier_and_clears_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row(
        status="captured",
        supplier_contact_id=None,
        po_reference=None,
        metadata_={"po_match_ack": {"codes": ["x"]}, "keep": 1},
    )
    po = _purchase_order(project_id=row.project_id)
    service = _service(_FakeSession())

    async def _get(_id: Any) -> Any:
        return row

    async def _log(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(service, "get", _get)
    monkeypatch.setattr(service, "_guard_editable", lambda _r: None)
    monkeypatch.setattr(service, "_snapshot", lambda _r: {})
    monkeypatch.setattr(service, "_log", _log)
    monkeypatch.setattr(InvoiceCaptureService, "_procurement", staticmethod(lambda _s: _FakeProcurement(po, [])))
    await service.link_purchase_order(row.id, po.id, "u1")
    assert row.purchase_order_id == po.id
    assert row.po_reference == "PO-0007"
    assert row.supplier_contact_id == "c1"
    assert row.metadata_ == {"keep": 1}


@pytest.mark.asyncio
async def test_mismatch_blocks_approval_until_acknowledged(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = [
        {
            "rule_id": "procurement.invoice_quantity_received",
            "passed": False,
            "severity": "warning",
            "message": "Line 1 invoices 20 kg, 16 kg received.",
        }
    ]
    service = _validate_with(monkeypatch, _FakeProcurement(_purchase_order(), failing))
    row = _row(
        status="coded",
        purchase_order_id=uuid.uuid4(),
        amount_tax=Decimal("19"),
        amount_gross=Decimal("119"),
        supplier_name="Stahl GmbH",
        approver_id=None,
        booking_expense_account="5000",
        booking_payable_account="1600",
        booking_tax_account="1576",
        po_reference="PO-0007",
    )

    async def _no_dup(_row: Any) -> None:
        return None

    monkeypatch.setattr(service, "_find_duplicate", _no_dup)
    blocked = await service._validate(row, require_booking=True, require_approval=False, enforce_match_ack=True)
    assert "po_match_unacknowledged" in {f.code for f in blocked}
    assert any(f.code.startswith("po_match:") for f in blocked)

    ok = await service._validate(
        row, require_booking=True, require_approval=False, enforce_match_ack=True, ack_all=True
    )
    assert not [f for f in ok if f.is_error]

    row.metadata_ = {"po_match_ack": {"codes": ["po_match:procurement.invoice_quantity_received"]}}
    again = await service._validate(row, require_booking=True, require_approval=False, enforce_match_ack=True)
    assert not [f for f in again if f.is_error]


def test_module_exposes_the_service() -> None:
    assert svc_mod.InvoiceCaptureService is InvoiceCaptureService


def test_negative_lines_are_flagged_not_dropped() -> None:
    from app.modules.finance import invoice_capture_logic as logic

    found = logic.negative_line_findings([{"amount": "100.00"}, {"amount": "-10.00"}])
    assert [(f.severity, f.code) for f in found] == [("warning", "negative_line")]
    assert logic.negative_line_findings([{"amount": "5"}, {}]) == []


@pytest.mark.asyncio
async def test_a_negative_line_posts_as_a_credit_actual(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _Spine:
        def __init__(self, _session: Any) -> None: ...

        async def post_actual_to_budget_line(self, **kw: Any) -> None:
            calls.append(kw)

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _id: Any) -> Any:
            return SimpleNamespace(currency="EUR", fx_rates=None, metadata_={})

    monkeypatch.setattr("app.modules.costmodel.service.CostSpineService", _Spine)
    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _Repo)
    row = _row()
    result = await _service(_FakeSession())._post_actuals(
        row, uuid.uuid4(), row.project_id, [(0, None, Decimal("100")), (1, None, Decimal("-10"))]
    )
    assert result["posted"] == 2
    assert sum(Decimal(c["amount_base"]) for c in calls) == Decimal("90.00")

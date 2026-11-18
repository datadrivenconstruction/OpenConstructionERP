# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice and the payment record on the block engine: pack binding, the VAT column, custom layouts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.doc_templates import legal
from app.core.doc_templates.layout import template as tpl
from app.core.doc_templates.layout.compile import compile_layout
from app.core.doc_templates.legal import LegalRequirement
from app.modules.doc_templates import layout_service as ls
from app.modules.finance.layouts import INVOICE, PAYMENT, invoice_standard, payment_standard
from app.modules.finance.pdf_export import invoice_context, payment_context
from tests.unit import _record_pdf_samples as samples

_DE_PACK = (
    Path(__file__).resolve().parents[4]
    / "packs/germany-de/src/openconstructionerp_germany_de/document_requirements.json"
)


def _invoice_ctx(**over: object) -> object:
    return invoice_context(samples.invoice(**over), project=samples.PROJECT, people=samples.PEOPLE)


def test_every_field_the_german_pack_requires_is_a_value_of_the_invoice() -> None:
    requirements = legal._parse(json.loads(_DE_PACK.read_text(encoding="utf-8")), "DE")
    invoice = [r for r in requirements if r.kind == INVOICE.key]
    assert invoice, "the German pack has invoice requirements"
    values = _invoice_ctx().values
    for req in invoice:
        for path in req.required_fields:
            assert any(p in values for p in path.split("|")), f"{req.id}: {path} is not an invoice value"
        if req.when:
            assert req.when in values, f"{req.id}: {req.when} is not an invoice value"


def test_the_vat_column_drops_out_when_no_line_carries_a_rate() -> None:
    line = SimpleNamespace(**{**vars(samples.invoice().line_items[0]), "vat_rate": None})
    with_rate = compile_layout(invoice_standard(), INVOICE, _invoice_ctx())
    without = compile_layout(invoice_standard(), INVOICE, _invoice_ctx(line_items=[line]))
    assert len(with_rate.blocks[0].rows[0]) == 7 and "19 %" in with_rate.blocks[0].rows[1]
    assert len(without.blocks[0].rows[0]) == 6


def test_retention_and_amount_due_print_only_when_retention_is_held() -> None:
    held = compile_layout(invoice_standard(), INVOICE, _invoice_ctx())
    none = compile_layout(invoice_standard(), INVOICE, _invoice_ctx(retention_amount=Decimal("0")))
    assert len(held.blocks[1].rows) == 5
    assert len(none.blocks[1].rows) == 3


def test_a_custom_invoice_layout_moves_the_notes_above_the_lines_and_renames_the_total() -> None:
    template = invoice_standard()
    body = template["body"]
    notes = next(b for b in body if b["id"] == "notes")
    body.remove(notes)
    body.insert(1, notes)
    totals = next(b for b in body if b["id"] == "totals")
    totals["rows"][2]["label"] = {"en": "Amount payable"}
    document = compile_layout(tpl.normalise(template), INVOICE, _invoice_ctx())
    assert document.blocks[0].title == "Notes"
    assert ["Amount payable", document.blocks[2].rows[2][1]] == document.blocks[2].rows[2]


def test_the_standard_invoice_and_payment_templates_pass_their_own_checks() -> None:
    for spec, standard in ((INVOICE, invoice_standard), (PAYMENT, payment_standard)):
        assert [i for i in tpl.check(tpl.normalise(standard()), spec) if i.severity == "error"] == []


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> None:
    note = LegalRequirement(
        id="xx.invoice.supply",
        kind=INVOICE.key,
        country="XX",
        text={"en": "Date of supply: {{doc.supply_date}}"},
        source="XX VAT Act",
        required_fields=("doc.supply_date", "recipient.address"),
    )
    monkeypatch.setattr(legal, "_all_requirements", lambda: (note,))


def test_a_pack_note_on_the_invoice_merges_the_supply_date(pack: None) -> None:
    ctx = invoice_context(
        samples.invoice(invoice_direction="receivable"),
        project=samples.PROJECT,
        people=samples.PEOPLE,
        parties={samples.VENDOR_ID: samples_party()},
    )
    notes, issues = ls.data_issues(INVOICE, ctx, ["XX"])
    assert len(notes) == 1 and notes[0].text == f"Date of supply: {ctx.values['doc.supply_date']}"
    assert "2026" in notes[0].text
    assert not [i for i in issues if i.severity == "error"]


def test_an_invoice_without_the_recipient_address_a_pack_requires_is_refused(pack: None) -> None:
    from fastapi import HTTPException

    _notes, issues = ls.data_issues(INVOICE, _invoice_ctx(), ["XX"])
    with pytest.raises(HTTPException) as caught:
        ls._refuse_issue(issues)
    assert caught.value.status_code == 422


def test_the_payment_record_hides_the_exchange_rate_at_par_and_shows_it_otherwise() -> None:
    def grid(**over: object) -> list[list[str]]:
        ctx = payment_context(
            samples.payment(**over), invoice=samples.invoice(), project=samples.PROJECT, people=samples.PEOPLE
        )
        return [list(r) for r in compile_layout(payment_standard(), PAYMENT, ctx).grid]

    assert len(grid()) == 2
    assert len(grid(exchange_rate_snapshot=Decimal("1.0823"))) == 3


def samples_party() -> object:
    from app.core.party_names import PartyDetails

    return PartyDetails(tax_id="DE811111111", address="Hafenweg 3, 20457 Hamburg")

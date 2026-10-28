# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The printed purchase order, goods receipt, invoice and payment (#514).

Checked on the form layer (:func:`app.core.register_export.record_text_lines`,
every string the form prints in reading order) and on the rendered bytes:

* each document renders to a PDF and carries its stored amounts exactly, in
  the project's separators, with nothing recomputed from a rate;
* every section the settings offer for a type disappears from the form when
  it is switched off, and only that section;
* the per-type hidden sections persist next to the appearance without
  disturbing it, and the settings API refuses a section the type lacks;
* the forms read in English, German and Russian.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

import pypdf
import pytest

from app.core.pdf_appearance import (
    DOCUMENT_TYPES,
    read_appearance,
    read_hidden_sections,
    read_overrides,
    resolve_sections,
    sanitise_hidden_sections,
    write_appearance,
    write_hidden_sections,
    write_override,
)
from app.core.register_export import record_text_lines
from app.modules.finance.pdf_export import invoice_record, payment_record
from app.modules.procurement.pdf_export import goods_receipt_record, purchase_order_record
from tests.unit import _record_pdf_samples as samples

RECORD_TYPES = ("purchase_order", "goods_receipt", "invoice", "payment")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


def _record(doc_type: str, sections: dict[str, bool] | None = None, locale: str = "en") -> Any:
    context = {"project": samples.PROJECT, "people": samples.PEOPLE, "sections": sections, "locale": locale}
    if doc_type == "purchase_order":
        return purchase_order_record(samples.purchase_order(), **context)
    if doc_type == "goods_receipt":
        return goods_receipt_record(samples.goods_receipt(), po=samples.purchase_order(), **context)
    if doc_type == "invoice":
        return invoice_record(samples.invoice(), **context)
    return payment_record(samples.payment(), invoice=samples.invoice(), **context)


def _lines(doc_type: str, **kwargs: Any) -> list[str]:
    return record_text_lines(_record(doc_type, **kwargs))


RENDERERS = {
    "purchase_order": samples.render_purchase_order,
    "goods_receipt": samples.render_goods_receipt,
    "invoice": samples.render_invoice,
    "payment": samples.render_payment,
}


# ── The registry ──────────────────────────────────────────────────────────


def test_the_four_record_types_are_configurable_and_offer_sections() -> None:
    for key in RECORD_TYPES:
        kind = DOCUMENT_TYPES[key]
        assert kind.configurable
        assert kind.sections
        assert "signatures" in kind.sections
    assert "notes" in DOCUMENT_TYPES["purchase_order"].sections
    assert "notes" in DOCUMENT_TYPES["goods_receipt"].sections
    assert "notes" in DOCUMENT_TYPES["invoice"].sections


# ── Rendering and amounts ─────────────────────────────────────────────────


@pytest.mark.parametrize("doc_type", RECORD_TYPES)
def test_each_document_renders_a_pdf_with_its_number(doc_type: str, data_dir: Path) -> None:
    pdf = RENDERERS[doc_type]()
    assert pdf.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    number = {"purchase_order": "PO-0042", "goods_receipt": "DN-77", "invoice": "INV-2026-0042"}.get(
        doc_type, "SEPA-55012"
    )
    assert number in text


def test_the_purchase_order_prints_the_three_stored_amounts_exactly() -> None:
    lines = _lines("purchase_order")
    assert "1.234,57\u00a0EUR" in lines  # net
    assert "234,57\u00a0EUR" in lines  # tax as stored, not 19 % of the net (234,5683)
    assert lines.count("1.469,14\u00a0EUR") == 2  # the grid total and the totals block
    # The tax is never added to a total that already carries it.
    assert not any("1.703,71" in line for line in lines)
    # A unit rate keeps the decimals it was stored with.
    assert "98,7656" in lines
    assert "12,5" in lines


def test_the_invoice_prints_its_totals_and_the_payable_after_retention() -> None:
    lines = _lines("invoice")
    for amount in ("1.234,57\u00a0EUR", "234,57\u00a0EUR", "73,96\u00a0EUR", "1.395,18\u00a0EUR"):
        assert amount in lines, amount
    assert "1.469,14\u00a0EUR" in lines
    assert not any("1.703,71" in line for line in lines)
    assert "19 %" in lines  # the line's stored VAT rate


def test_an_invoice_without_retention_prints_no_retention_rows() -> None:
    record = invoice_record(
        samples.invoice(retention_amount=0), project=samples.PROJECT, people=samples.PEOPLE, locale="en"
    )
    lines = record_text_lines(record)
    assert "Retention" not in lines
    assert "Payable after retention" not in lines


def test_the_payment_prints_cash_withholding_and_the_gross_it_settled() -> None:
    lines = _lines("payment")
    assert "1.395,18\u00a0EUR" in lines
    assert "73,96\u00a0EUR" in lines
    assert "1.469,14\u00a0EUR" in lines  # the gross settled and the invoice total


def test_a_goods_receipt_lists_what_arrived_and_what_was_turned_away() -> None:
    lines = _lines("goods_receipt")
    assert "Ready-mix concrete C30/37" in lines
    assert "0,5 m3" in lines
    assert "Slump out of tolerance" in lines
    assert "PO-0042" in lines


# ── Section toggles ───────────────────────────────────────────────────────


#: A string each section prints and nothing else on the form does.
SECTION_MARKERS: dict[str, dict[str, str]] = {
    "purchase_order": {
        "line_items": "Line items",
        "totals": "Total incl. tax",
        "terms": "Payment terms",
        "supplier_confirmation": "AB-7781",
        "notes": "Deliver to gate B between 7 and 9 am.",
        "signatures": "Signatures",
    },
    "goods_receipt": {
        "line_items": "LOT-2209",
        "rejections": "Slump out of tolerance",
        "notes": "Two bags torn on arrival.",
        "signatures": "Signatures",
    },
    "invoice": {
        "line_items": "Ready-mix concrete C30/37",
        "totals": "Total incl. tax",
        "payments": "SEPA-55012",
        "notes": "Quote the invoice number on the transfer.",
        "signatures": "Signatures",
    },
    "payment": {
        "invoice": "Invoice no.",
        "withholding": "Gross amount settled",
        "signatures": "Signatures",
    },
}


def test_every_offered_section_has_a_marker_here() -> None:
    for key in RECORD_TYPES:
        assert set(SECTION_MARKERS[key]) == set(DOCUMENT_TYPES[key].sections), key


@pytest.mark.parametrize(
    ("doc_type", "section"),
    [(key, section) for key in RECORD_TYPES for section in DOCUMENT_TYPES[key].sections],
)
def test_switching_a_section_off_removes_it_and_nothing_else(doc_type: str, section: str) -> None:
    marker = SECTION_MARKERS[doc_type][section]
    full = _lines(doc_type)
    assert any(marker in line for line in full), f"{doc_type}: {marker!r} is not on the full form"
    cut = _lines(doc_type, sections={section: False})
    assert not any(marker in line for line in cut), f"{doc_type}: hiding {section} left {marker!r}"
    for other, other_marker in SECTION_MARKERS[doc_type].items():
        if other != section and other_marker != marker:
            assert any(other_marker in line for line in cut), f"{doc_type}: hiding {section} also hid {other}"


@pytest.mark.parametrize("doc_type", RECORD_TYPES)
def test_a_stored_hidden_section_reaches_the_rendered_pdf(doc_type: str, data_dir: Path) -> None:
    section = "signatures"
    before = RENDERERS[doc_type]()
    write_hidden_sections(doc_type, [section], data_dir)
    after = RENDERERS[doc_type]()
    assert after != before
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(after)).pages)
    assert "Signatures" not in text


# ── Storage of hidden sections ────────────────────────────────────────────


def test_with_nothing_stored_every_section_prints(data_dir: Path) -> None:
    for key in RECORD_TYPES:
        assert resolve_sections(key, data_dir) == dict.fromkeys(DOCUMENT_TYPES[key].sections, True)


def test_hidden_sections_round_trip_and_leave_the_look_alone(data_dir: Path) -> None:
    write_appearance({"accent_color": "#123456"}, data_dir)
    write_override("invoice", {"footer_text": "Invoice footer"}, data_dir)

    stored = write_hidden_sections("invoice", ["signatures", "notes", "notes", "colour"], data_dir)

    assert stored == ["notes", "signatures"]  # the type's order, unknowns and repeats dropped
    assert read_hidden_sections("invoice", data_dir) == ["notes", "signatures"]
    assert resolve_sections("invoice", data_dir)["notes"] is False
    assert resolve_sections("invoice", data_dir)["totals"] is True
    assert read_appearance(data_dir)["accent_color"] == "#123456"
    assert read_overrides(data_dir) == {"invoice": {"footer_text": "Invoice footer"}}
    # And the look's writers carry the sections through.
    write_appearance({"accent_color": "#654321"}, data_dir)
    write_override("invoice", {}, data_dir)
    assert read_hidden_sections("invoice", data_dir) == ["notes", "signatures"]


def test_clearing_the_hidden_sections_removes_the_file_when_nothing_else_is_stored(data_dir: Path) -> None:
    write_hidden_sections("payment", ["withholding"], data_dir)
    assert (data_dir / "pdf_appearance.json").exists()
    write_hidden_sections("payment", [], data_dir)
    assert not (data_dir / "pdf_appearance.json").exists()


def test_a_section_of_another_type_or_an_unknown_type_is_dropped() -> None:
    assert sanitise_hidden_sections("payment", ["notes"]) == []
    assert sanitise_hidden_sections("quotation", ["notes"]) == []
    assert sanitise_hidden_sections("invoice", "notes") == []


# ── The settings API ──────────────────────────────────────────────────────


def _client(role: str | None = "admin") -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.branding_router import router
    from app.dependencies import get_current_user_payload

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if role is not None:
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(uuid.uuid4()), "role": role}
    return TestClient(app)


def test_the_registry_lists_the_sections_and_the_hidden_ones(data_dir: Path) -> None:
    write_hidden_sections("purchase_order", ["notes"], data_dir)
    body = _client("viewer").get("/api/v1/document-appearance/types/").json()
    po = next(entry for entry in body if entry["key"] == "purchase_order")
    assert po["sections"] == list(DOCUMENT_TYPES["purchase_order"].sections)
    assert po["hidden_sections"] == ["notes"]
    rfi = next(entry for entry in body if entry["key"] == "rfi")
    assert rfi["sections"] == []
    assert rfi["hidden_sections"] == []


def test_an_admin_sets_the_hidden_sections(data_dir: Path) -> None:
    response = _client("admin").put(
        "/api/v1/document-appearance/types/goods_receipt/sections/", json={"hidden": ["rejections"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["hidden_sections"] == ["rejections"]
    assert resolve_sections("goods_receipt", data_dir)["rejections"] is False


@pytest.mark.parametrize("role", ["viewer", "editor", "manager"])
def test_a_non_admin_cannot_hide_a_section(data_dir: Path, role: str) -> None:
    response = _client(role).put("/api/v1/document-appearance/types/invoice/sections/", json={"hidden": ["notes"]})
    assert response.status_code == 403
    assert read_hidden_sections("invoice", data_dir) == []


def test_a_section_the_type_lacks_is_refused_not_dropped(data_dir: Path) -> None:
    response = _client("admin").put(
        "/api/v1/document-appearance/types/payment/sections/", json={"hidden": ["notes", "signatures"]}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_document_type_sections"
    assert detail["sections"] == ["notes"]
    assert read_hidden_sections("payment", data_dir) == []


def test_an_unknown_type_is_a_404(data_dir: Path) -> None:
    response = _client("admin").put("/api/v1/document-appearance/types/quotation/sections/", json={"hidden": []})
    assert response.status_code == 404


# ── Languages ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("locale", "titles"),
    [
        ("en", ("Purchase Order", "Goods Receipt", "Invoice", "Payment")),
        ("de", ("Bestellung", "Wareneingang", "Rechnung", "Zahlung")),
        ("ru", ("Заказ на поставку", "Приёмка поставки", "Счёт", "Платёж")),
    ],
)
def test_the_forms_read_in_the_document_language(locale: str, titles: tuple[str, ...]) -> None:
    for doc_type, title in zip(RECORD_TYPES, titles, strict=True):
        record = _record(doc_type, locale=locale)
        assert record.title == title
        assert record.page_label != "" and "{page}" in record.page_label


def test_an_unsupported_language_falls_back_to_english() -> None:
    assert _record("invoice", locale="xx").title == "Invoice"

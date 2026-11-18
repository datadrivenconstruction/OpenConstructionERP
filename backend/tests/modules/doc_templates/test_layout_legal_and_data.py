# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pack legal notes on layouts, the data a document lacks, and the purchase order's delivery address.

DOMAIN.md: a pack note is fixed legal text printed in the legal zone; a firm's layout
can neither hide nor move it. Data a pack requires blocks issuing; the PO's delivery
address is platform-standard data, so a PO saved before the field existed still prints.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.core.doc_templates import legal
from app.core.doc_templates.layout import template as tpl
from app.core.doc_templates.legal import LegalRequirement
from app.modules.doc_templates import layout_service as ls
from app.modules.procurement.layouts import PURCHASE_ORDER, purchase_order_standard
from app.modules.procurement.pdf_export import purchase_order_context
from tests.unit import _record_pdf_samples as samples

_NOTE = LegalRequirement(
    id="po_site_rules",
    kind="procurement.purchase_order",
    country="XX",
    text={"en": "Deliveries follow the site rules of {{project.name}}.", "de": "Lieferungen nach Baustellenordnung."},
    source="Test pack § 1",
)
_DATA = LegalRequirement(
    id="po_supplier_tax",
    kind="procurement.purchase_order",
    country="XX",
    text={},
    source="Test pack § 2",
    required_fields=("supplier.tax_id",),
    labels={"supplier.tax_id": "Supplier tax id"},
    where="contacts",
)


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal, "_all_requirements", lambda: (_NOTE, _DATA))


def _ctx(locale: str = "en", **over: Any) -> Any:
    return purchase_order_context(samples.purchase_order(**over), project=samples.PROJECT, locale=locale)


def _texts(document: Any) -> str:
    return "\n".join(m for b in document.blocks for m in (b.markup or []))


def test_pack_note_prints_on_a_custom_layout_after_the_body(pack: None) -> None:
    custom = tpl.normalise(purchase_order_standard())
    custom["body"].insert(1, {"id": "intro", "type": "text", "text": {"en": "Thank you."}, "hidden": False})
    ctx = _ctx()
    notes, issues = ls.data_issues(PURCHASE_ORDER, ctx, ["XX"])
    document = ls.render(PURCHASE_ORDER, tpl.normalise(custom), ctx, legal=notes)
    assert "Deliveries follow the site rules of" in _texts(document)
    assert "Test pack § 1" in _texts(document)
    assert document.blocks[-1].markup and "site rules" in document.blocks[-1].markup[0]
    assert [i.rule_id for i in issues if i.severity == "error"] == ["doctpl.legal_data_missing"]


def test_pack_note_prints_in_the_document_language(pack: None) -> None:
    notes, _issues = ls.data_issues(PURCHASE_ORDER, _ctx("de"), ["XX"])
    assert notes[0].text == "Lieferungen nach Baustellenordnung."


def test_no_pack_country_means_no_note_and_no_block(pack: None) -> None:
    notes, issues = ls.data_issues(PURCHASE_ORDER, _ctx(), [])
    assert notes == []
    assert all(i.severity == "warning" for i in issues)


def test_missing_pack_data_refuses_the_issue(pack: None) -> None:
    _notes, issues = ls.data_issues(PURCHASE_ORDER, _ctx(), ["XX"])
    with pytest.raises(HTTPException) as caught:
        ls._refuse_issue(issues)  # noqa: SLF001
    assert caught.value.status_code == 422
    assert caught.value.detail["issues"][0]["params"]["field"] == "Supplier tax id"


def test_missing_delivery_address_is_a_warning_not_a_block() -> None:
    _notes, issues = ls.data_issues(PURCHASE_ORDER, _ctx(), [])
    missing = [i for i in issues if i.params and i.params.get("field") == "Delivery address"]
    assert [i.severity for i in missing] == ["warning"]
    ls._refuse_issue(issues)  # noqa: SLF001 - warnings never refuse


def test_delivery_address_prints_in_order_details_when_set() -> None:
    ctx = _ctx(delivery_address="Riverside Block B, gate 2")
    document = ls.render(PURCHASE_ORDER, None, ctx)
    cells = [cell for row in document.grid for cell in row]
    assert "Riverside Block B, gate 2" in cells
    assert "Delivery address" in cells
    _notes, issues = ls.data_issues(PURCHASE_ORDER, ctx, [])
    assert not [i for i in issues if i.params and i.params.get("field") == "Delivery address"]


def test_empty_delivery_address_leaves_the_form_unchanged() -> None:
    cells = [cell for row in ls.render(PURCHASE_ORDER, None, _ctx()).grid for cell in row]
    assert "Delivery address" not in cells


def test_editor_lists_pack_notes_as_locked_blocks(pack: None) -> None:
    described = ls.describe(PURCHASE_ORDER, "en", ["XX"])
    assert [b["id"] for b in described["legal"]] == ["po_site_rules", "po_supplier_tax"]
    assert described["legal"][0]["source"] == "Test pack § 1"
    assert ls.describe(PURCHASE_ORDER, "en", [])["legal"] == []

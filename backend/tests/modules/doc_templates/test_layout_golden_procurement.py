# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The purchase order and goods receipt print exactly what they printed before the block engine.

The digests in ``golden_procurement_forms.json`` were taken from the hand-written
record forms before they moved onto document layouts. A PDF is a pure function of
the record form it is drawn from (plus the workspace look), so an equal form means
an identical PDF. Every case renders through the engine's standard template.

Regenerate only on an intended change of the printed form:
``python -m tests.modules.doc_templates.test_layout_golden_procurement``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.party_names import PartyDetails
from tests.unit import _record_pdf_samples as samples

GOLDEN = Path(__file__).with_name("golden_procurement_forms.json")
_GENERATED = "2026-11-18 09:30 UTC"
_PARTIES = {samples.VENDOR_ID: PartyDetails(tax_id="DE811111111", address="Hafenweg 3\n20457 Hamburg")}
_PO_SECTIONS = ("line_items", "totals", "terms", "supplier_confirmation", "notes", "signatures")
_GR_SECTIONS = ("line_items", "rejections", "notes", "signatures")
_LOCALES = ("en", "de", "ru", "ar", "fr", "tr", "zh", "es")


#: Fields the hand-written forms had; layout-only fields must keep their defaults on a standard form.
_FORM_KEYS = (
    "title",
    "number",
    "project_label",
    "status_text",
    "subject",
    "grid",
    "blocks",
    "page_label",
    "generated_label",
    "generated",
    "doc_type",
)
_BLOCK_KEYS = ("title", "kind", "text", "empty_text", "rows", "weights", "right_aligned", "keep_together", "total_rows")


def _legacy_shape(record: Any) -> dict[str, Any]:
    """The form as the hand-written builders described it; fails if a layout-only field is set."""
    defaults = {f.name: f.default for f in dataclasses.fields(record) if f.name not in _FORM_KEYS}
    for name, default in defaults.items():
        assert getattr(record, name) == default, f"standard form sets layout field {name}"
    data = {key: dataclasses.asdict(record)[key] for key in _FORM_KEYS if key != "blocks"}
    blocks = []
    for block in record.blocks:
        extra = {f.name: f.default for f in dataclasses.fields(block) if f.name not in _BLOCK_KEYS}
        for name, default in extra.items():
            assert getattr(block, name) == default, f"standard block sets layout field {name}"
        blocks.append({key: dataclasses.asdict(block)[key] for key in _BLOCK_KEYS})
    data["blocks"] = blocks
    return data


def _digest(record: Any) -> str:
    payload = json.dumps(_legacy_shape(record), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cases() -> Iterator[tuple[str, Callable[[], Any]]]:
    from app.modules.procurement.pdf_export import goods_receipt_record, purchase_order_record

    def po(locale: str = "en", sections: dict[str, bool] | None = None, parties: Any = None, **over: Any) -> Any:
        return lambda: purchase_order_record(
            samples.purchase_order(**over),
            project=samples.PROJECT,
            people=samples.PEOPLE,
            parties=parties,
            sections=sections,
            locale=locale,
            generated=_GENERATED,
        )

    def gr(locale: str = "en", sections: dict[str, bool] | None = None, po_over: Any = None, **over: Any) -> Any:
        return lambda: goods_receipt_record(
            samples.goods_receipt(**over),
            po=samples.purchase_order(**(po_over or {})),
            project=samples.PROJECT,
            people=samples.PEOPLE,
            parties=_PARTIES,
            sections=sections,
            locale=locale,
            generated=_GENERATED,
        )

    for locale in _LOCALES:
        yield f"po-{locale}", po(locale)
        yield f"po-{locale}-parties", po(locale, parties=_PARTIES)
        yield f"gr-{locale}", gr(locale)
    for section in _PO_SECTIONS:
        yield f"po-hide-{section}", po(sections={s: s != section for s in _PO_SECTIONS})
    for section in _GR_SECTIONS:
        yield f"gr-hide-{section}", gr(sections={s: s != section for s in _GR_SECTIONS})
    yield "po-unacknowledged", po(supplier_acknowledged_at=None)
    yield "po-no-retention", po(retention_percent=Decimal("0"))
    yield "po-retention-none", po(retention_percent=None)
    yield "po-retain-on-receipt", po(retain_on_receipt=True)
    yield "po-no-items", po(items=[])
    yield "po-no-notes", po(notes="")
    yield "po-tolerance-abs", po(invoice_tolerance_abs="50", invoice_tolerance_pct=None)
    yield "po-no-currency", po(currency_code=None)
    yield "po-unknown-vendor", po(vendor_contact_id=None, created_by=None)
    yield "po-draft-status", po(status=None)
    yield "po-delivery-address", po(delivery_address="Riverside Block B, gate 2, 10115 Berlin")
    yield "gr-no-items", gr(items=[])
    yield "gr-no-notes", gr(notes=None)
    yield (
        "gr-no-rejections",
        gr(
            items=[
                SimpleNamespace(
                    po_item_id=samples.PO_ITEM_ID,
                    quantity_ordered="12.5",
                    quantity_received="12.5",
                    quantity_rejected="0",
                    rejection_reason="",
                    batch_lot="",
                )
            ]
        ),
    )
    yield "gr-no-delivery-note", gr(delivery_note_number="")


def _current() -> dict[str, str]:
    return {name: _digest(build()) for name, build in _cases()}


def test_every_golden_case_is_still_generated() -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(stored) == {name for name, _ in _cases()}


@pytest.mark.parametrize(("name", "build"), list(_cases()), ids=[name for name, _ in _cases()])
def test_the_standard_template_prints_the_form_it_printed_before(name: str, build: Callable[[], Any]) -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _digest(build()) == stored[name], f"{name}: the printed form changed"


if __name__ == "__main__":  # pragma: no cover - regeneration helper
    GOLDEN.write_text(json.dumps(_current(), indent=1, sort_keys=True) + "\n", encoding="utf-8")

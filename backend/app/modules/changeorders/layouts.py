# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layout of the change order.

The layout declares the merge fields, the item columns, the section only this
module draws (the description) and what may never be hidden, and ships the
standard template that prints the form exactly as the hand-written form did.
It shares its key with the change order's document wording, so one name means
one document everywhere.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.doc_templates.layout.spec import (
    COMMON_FIELDS,
    CollectionSpec,
    ColumnSpec,
    LayoutContext,
    LayoutSpec,
    SectionSpec,
    register_layout,
)
from app.core.doc_templates.registry import MandatoryField, MergeField
from app.core.register_export import ProjectHeader

__all__ = ["CHANGE_ORDER", "change_order_standard", "register_changeorder_layouts"]

_STANDARD = "Platform standard"
_KEY = "changeorders.change_order"


def change_order_standard(_sections: Any = None) -> dict[str, Any]:
    """The standard change order form."""
    return {
        "schema": 1,
        "primary_locale": "en",
        "title": {},
        "subject": {},
        "show_subject": True,
        "page": {"size": "A4", "orientation": "portrait"},
        "branding": {},
        "watermark": {},
        "header": [],
        "footer": [],
        "body": [
            {
                "id": "order_details",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": [
                    {"field": path}
                    for path in (
                        "doc.reason",
                        "doc.instrument",
                        "doc.contractor_amount",
                        "doc.engineer_amount",
                        "doc.approved_amount",
                        "doc.cost_impact",
                        "doc.time_impact",
                        "doc.approved_time",
                        "doc.submitted_at",
                        "doc.submitted_by",
                        "doc.approved_at",
                        "doc.approved_by",
                    )
                ],
            },
            {"id": "description", "type": "section", "section": "description", "hidden": False},
            {
                "id": "items",
                "type": "table",
                "collection": "items",
                "hidden": False,
                "omit_empty": True,
                "total_row": True,
                "columns": [
                    {"id": "description"},
                    {"id": "unit"},
                    {"id": "original_quantity"},
                    {"id": "new_quantity"},
                    {"id": "original_rate"},
                    {"id": "new_rate"},
                    {"id": "cost_delta"},
                ],
            },
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": False,
                "signers": [{"field": "doc.submitted_by"}, {"field": "doc.approved_by"}],
            },
        ],
    }


_FIELDS = (
    MergeField("doc.number", "text", "CO-007", "document"),
    MergeField("doc.title", "text", "Extra drainage at the north wall", "document"),
    MergeField("doc.description", "text", "Ground water found during excavation.", "document"),
    MergeField("doc.reason", "text", "Unforeseen conditions", "document"),
    MergeField("doc.instrument", "text", "Works change", "document"),
    MergeField("doc.status", "text", "Submitted", "document"),
    MergeField("doc.currency", "text", "EUR", "document"),
    MergeField("doc.contractor_amount", "money", "1.234,56 €", "document"),
    MergeField("doc.engineer_amount", "money", "1.000,00 €", "document"),
    MergeField("doc.approved_amount", "money", "1.100,00 €", "document"),
    MergeField("doc.cost_impact", "money", "1.100,00 €", "document"),
    MergeField("doc.time_impact", "text", "3 days", "document"),
    MergeField("doc.approved_time", "text", "2 days", "document"),
    MergeField("doc.submitted_at", "date", "10.10.2026", "document"),
    MergeField("doc.approved_at", "date", "14.10.2026", "document"),
    MergeField("doc.submitted_by", "text", "Maria Keller", "sender"),
    MergeField("doc.approved_by", "text", "Tom Berger", "recipient"),
    *COMMON_FIELDS,
)

_COLUMNS = (
    ColumnSpec("no", "No.", "index", right=True, weight=0.5, keep=True),
    ColumnSpec("description", "Description / change", "text", required=True, weight=4.4, source=_STANDARD),
    ColumnSpec("unit", "Unit", "text", weight=0.8, keep=True),
    ColumnSpec("original_quantity", "Original quantity", "quantity", right=True, weight=1.1, keep=True),
    ColumnSpec("new_quantity", "New quantity", "quantity", right=True, weight=1.1, keep=True),
    ColumnSpec("original_rate", "Original rate", "number", right=True, weight=1.3, keep=True),
    ColumnSpec("new_rate", "New rate", "number", right=True, weight=1.3, keep=True),
    ColumnSpec(
        "cost_delta", "Cost change", "money", required=True, right=True, weight=1.5, keep=True, source=_STANDARD
    ),
)

_SAMPLE_PROJECT = ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR")


def _sample_order() -> SimpleNamespace:
    item = SimpleNamespace(
        sort_order=0,
        description="Drainage pipe DN100",
        change_type="added",
        unit="m",
        original_quantity=Decimal("10"),
        new_quantity=Decimal("12.5"),
        original_rate=Decimal("100"),
        new_rate=Decimal("98.765"),
        cost_delta=Decimal("234.56"),
    )
    return SimpleNamespace(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        project_id=None,
        code="CO-007",
        title="Extra drainage at the north wall",
        description="Ground water found during excavation.",
        reason_category="unforeseen",
        variation_type="works_change",
        status="submitted",
        submitted_at="2026-10-10T08:00:00+00:00",
        approved_at=None,
        submitted_by="Maria Keller",
        approved_by=None,
        contractor_amount=Decimal("1234.56"),
        engineer_amount=Decimal("1000"),
        approved_amount=None,
        cost_impact=Decimal("1234.56"),
        currency="EUR",
        time_impact_days=3,
        schedule_impact_days=3,
        approved_time_days=None,
        items=[item],
    )


def _sample(locale: str) -> LayoutContext:
    from app.modules.changeorders.pdf_export import change_order_context

    return change_order_context(_sample_order(), project=_SAMPLE_PROJECT, locale=locale)


async def _records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.changeorders.models import ChangeOrder

    stmt = select(ChangeOrder.id, ChangeOrder.code, ChangeOrder.title).order_by(ChangeOrder.code).limit(50)
    if project_ids is not None:
        stmt = stmt.where(ChangeOrder.project_id.in_(project_ids))
    return [(str(i), f"{c} {t}") for i, c, t in (await session.execute(stmt)).all()]


async def change_order_layout_context(session: Any, order: Any, locale: str) -> LayoutContext:
    """One stored change order's layout context, names resolved."""
    from app.core.party_names import resolve_party_names
    from app.core.register_context import generated_now, load_project_header
    from app.modules.changeorders.pdf_export import change_order_context
    from app.modules.changeorders.pdf_translations import normalize_pdf_locale, tr

    project = await load_project_header(session, order.project_id)
    lang = normalize_pdf_locale(locale)
    return change_order_context(
        order,
        project=project,
        people=await resolve_party_names(session, [order.submitted_by, order.approved_by]),
        locale=lang,
        generated=generated_now(tr(lang, "datetime_format"), project),
    )


async def _context(session: Any, record_id: str, locale: str) -> LayoutContext:
    from app.modules.changeorders.service import ChangeOrderService

    try:
        order = await ChangeOrderService(session).get_order(uuid.UUID(str(record_id)))
    except Exception as exc:  # noqa: BLE001 - a bad id or a missing order is one answer
        raise LookupError(record_id) from exc
    return await change_order_layout_context(session, order, locale)


CHANGE_ORDER = LayoutSpec(
    key=_KEY,
    module="changeorders",
    label="Change order",
    appearance_type="change_order",
    fields=_FIELDS,
    collections=(CollectionSpec("items", "Items", _COLUMNS),),
    sections=(
        SectionSpec("order_details", "Order details", required=True, source=_STANDARD),
        SectionSpec("description", "Description", builtin=True),
        SectionSpec("items", "Items", required=True, source=_STANDARD),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=change_order_standard,
    sample=_sample,
    context=_context,
    records=_records,
    statuses=("draft", "submitted", "approved", "rejected", "executed"),
    mandatory=(
        MandatoryField(("doc.number",), "Change order number", _STANDARD, "change order"),
        MandatoryField(("doc.title",), "Title", _STANDARD, "change order"),
        MandatoryField(("doc.reason",), "Reason", _STANDARD, "change order"),
    ),
    locked_fields={"doc.cost_impact": _STANDARD, "doc.time_impact": _STANDARD},
)


def register_changeorder_layouts() -> None:
    """Register the change order layout with the document engine. Idempotent."""
    from app.modules.changeorders.pdf_translations import CATALOGUE

    langs = tuple(CATALOGUE.supported)
    register_layout(replace(CHANGE_ORDER, languages=langs if "en" in langs else ("en", *langs)))

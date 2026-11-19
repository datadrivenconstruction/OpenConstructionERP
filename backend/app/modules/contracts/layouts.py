# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layout of the contract.

The layout declares the merge fields, the schedule of values columns and what may
never be hidden, and ships the standard template that prints the contract as a
form: the terms, the schedule of values and the signature block. A firm restyles
it in the document editor; the standard form stays the fallback.
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

__all__ = ["CONTRACT", "contract_standard", "register_contract_layouts"]

_STANDARD = "Platform standard"
_KEY = "contracts.contract"


def contract_standard(_sections: Any = None) -> dict[str, Any]:
    """The standard contract form."""
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
                "id": "terms",
                "type": "fields",
                "layout": "pairs",
                "hidden": False,
                "fields": [
                    {"field": path, **({"omit_empty": True} if path in ("doc.original_value", "doc.signed_at") else {})}
                    for path in (
                        "doc.role",
                        "doc.counterparty",
                        "doc.type",
                        "doc.total_value",
                        "doc.original_value",
                        "doc.retention_percent",
                        "doc.start_date",
                        "doc.end_date",
                        "doc.signed_at",
                    )
                ],
            },
            {
                "id": "lines",
                "type": "table",
                "collection": "lines",
                "hidden": False,
                "omit_empty": True,
                "total_row": True,
                "columns": [
                    {"id": "code"},
                    {"id": "description"},
                    {"id": "unit"},
                    {"id": "quantity"},
                    {"id": "unit_rate"},
                    {"id": "total_value"},
                ],
            },
            {
                "id": "signatures",
                "type": "signatures",
                "hidden": False,
                "signers": [{"field": "entity.legal_name"}, {"field": "doc.counterparty"}],
            },
        ],
    }


_FIELDS = (
    MergeField("doc.number", "text", "C-001", "document"),
    MergeField("doc.title", "text", "Structural works, block B", "document"),
    MergeField("doc.type", "text", "Lump sum", "document"),
    MergeField("doc.role", "text", "Subcontract", "document"),
    MergeField("doc.counterparty", "text", "Keller Rohbau GmbH", "recipient"),
    MergeField("doc.status", "text", "Active", "document"),
    MergeField("doc.currency", "text", "EUR", "document"),
    MergeField("doc.total_value", "money", "120.000,00 €", "document"),
    MergeField("doc.original_value", "money", "100.000,00 €", "document"),
    MergeField("doc.retention_percent", "text", "5 %", "document"),
    MergeField("doc.start_date", "date", "01.10.2026", "document"),
    MergeField("doc.end_date", "date", "30.06.2027", "document"),
    MergeField("doc.signed_at", "date", "28.09.2026", "document"),
    *COMMON_FIELDS,
)

_COLUMNS = (
    ColumnSpec("code", "Code", "text", weight=1.0, keep=True),
    ColumnSpec("description", "Description", "text", required=True, weight=4.4, source=_STANDARD),
    ColumnSpec("unit", "Unit", "text", weight=0.8, keep=True),
    ColumnSpec("quantity", "Quantity", "quantity", right=True, weight=1.1, keep=True),
    ColumnSpec("unit_rate", "Unit rate", "number", right=True, weight=1.3, keep=True),
    ColumnSpec("total_value", "Total", "money", required=True, right=True, weight=1.5, keep=True, source=_STANDARD),
)

_SAMPLE_PROJECT = ProjectHeader(name="Riverside Block B", code="RB-B", currency="EUR")


def _sample_contract() -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    line = SimpleNamespace(
        order_index=0,
        code="01.10",
        description="Reinforced concrete walls C30/37",
        unit="m3",
        quantity=Decimal("120"),
        unit_rate=Decimal("1000"),
        total_value=Decimal("120000"),
    )
    contract = SimpleNamespace(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000005"),
        project_id=None,
        code="C-001",
        title="Structural works, block B",
        contract_type="lump_sum",
        counterparty_type="subcontractor",
        status="active",
        currency="EUR",
        total_value=Decimal("120000"),
        original_contract_value=Decimal("100000"),
        retention_percent=Decimal("5"),
        start_date="2026-10-01",
        end_date="2027-06-30",
        signed_at="2026-09-28",
    )
    return contract, [line]


def _sample(locale: str) -> LayoutContext:
    from app.modules.contracts.pdf_export import contract_context

    contract, lines = _sample_contract()
    return contract_context(contract, lines, project=_SAMPLE_PROJECT, counterparty="Keller Rohbau GmbH", locale=locale)


async def _records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.contracts.models import Contract

    stmt = select(Contract.id, Contract.code, Contract.title).order_by(Contract.code).limit(50)
    if project_ids is not None:
        stmt = stmt.where(Contract.project_id.in_(project_ids))
    return [(str(i), f"{c} {t}") for i, c, t in (await session.execute(stmt)).all()]


async def contract_layout_context(session: Any, contract: Any, locale: str) -> LayoutContext:
    """One stored contract's layout context, counterparty name resolved."""
    from app.core.company_profile import issuing_company
    from app.core.register_context import generated_now, load_project_header
    from app.modules.contracts.pdf_export import contract_context
    from app.modules.contracts.pdf_translations import normalize_pdf_locale, tr
    from app.modules.contracts.repository import ContractLineRepository
    from app.modules.contracts.service import ContractsService
    from app.modules.legal_entities.seller import entity_for_contract, entity_profile

    project = await load_project_header(session, contract.project_id)
    lang = normalize_pdf_locale(locale)
    lines = await ContractLineRepository(session).list_for_contract(contract.id)
    counterparty = await ContractsService(session).resolve_counterparty_name(contract)
    entity = await entity_for_contract(session, contract)
    # The contract names the group company that concludes it, not the install's profile.
    with issuing_company(entity_profile(entity) if entity is not None else None):
        return contract_context(
            contract,
            list(lines),
            project=project,
            counterparty=counterparty,
            locale=lang,
            generated=generated_now(tr(lang, "datetime_format"), project),
        )


async def _context(session: Any, record_id: str, locale: str) -> LayoutContext:
    from app.modules.contracts.service import ContractsService

    try:
        contract = await ContractsService(session).get_contract(uuid.UUID(str(record_id)))
    except Exception as exc:  # noqa: BLE001 - a bad id or a missing contract is one answer
        raise LookupError(record_id) from exc
    return await contract_layout_context(session, contract, locale)


CONTRACT = LayoutSpec(
    key=_KEY,
    module="contracts",
    label="Contract",
    fields=_FIELDS,
    collections=(CollectionSpec("lines", "Schedule of values", _COLUMNS),),
    sections=(
        SectionSpec("terms", "Contract terms", required=True, source=_STANDARD),
        SectionSpec("lines", "Schedule of values", required=True, source=_STANDARD),
        SectionSpec("signatures", "Signatures"),
    ),
    standard=contract_standard,
    sample=_sample,
    context=_context,
    records=_records,
    statuses=("draft", "active", "suspended", "completed", "terminated"),
    mandatory=(
        MandatoryField(("doc.number",), "Contract code", _STANDARD, "contract"),
        MandatoryField(("doc.title",), "Title", _STANDARD, "contract"),
    ),
    locked_fields={"doc.total_value": _STANDARD},
)


def register_contract_layouts() -> None:
    """Register the contract layout with the document engine. Idempotent."""
    from app.modules.contracts.pdf_translations import CATALOGUE

    langs = tuple(CATALOGUE.supported)
    register_layout(replace(CONTRACT, languages=langs if "en" in langs else ("en", *langs)))

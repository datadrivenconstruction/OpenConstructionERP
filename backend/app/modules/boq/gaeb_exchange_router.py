# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Routes for the GAEB site phases: X31 measured quantities and X89 invoices.

Mounted into the BOQ router (the module loader mounts one router per module),
so every path here sits under ``/api/v1/boq``.

* ``GET  /boqs/{boq_id}/export/gaeb-x31/``          measured quantities as X31
* ``POST /boqs/{boq_id}/import/gaeb-x31/preview/``  read an X31, propose, write nothing
* ``POST /boqs/{boq_id}/import/gaeb-x31/apply/``    write the proposals a person confirmed
* ``POST /boqs/{boq_id}/check/gaeb-x89/``           check a received X89 against the bill
* ``GET  /claims/{claim_id}/gaeb-x89/preview/``     what the X89 of a progress claim will say
* ``GET  /claims/{claim_id}/export/gaeb-x89/``      the X89 of a progress claim

The pure work (parsing, matching, writing XML) lives in ``gaeb_x31`` and
``gaeb_x89``; this file only loads rows, checks access and shapes responses.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.content_disposition import attachment_disposition
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.boq.gaeb_common import c2, dec, q3
from app.modules.boq.gaeb_x31 import (
    build_x31_xml,
    measured_quantity_of,
    measurement_from_x31,
    parse_x31,
    propose_x31,
)
from app.modules.boq.gaeb_x89 import (
    CUMULATIVE_INVOICE_TYPES,
    INVOICE_TYPE_PROGRESS,
    InvoiceFigures,
    InvoiceInput,
    InvoiceParty,
    InvoicePlacement,
    build_x89_xml,
    check_x89,
    invoice_lines_from_claim,
    missing_invoice_fields,
    parse_x89,
    x89_figures,
)
from app.modules.boq.importers._base import ImporterParseError

logger = logging.getLogger(__name__)

gaeb_exchange_router = APIRouter(tags=["boq"])

#: Upper bound on proposals one apply call may carry. A bill this size is
#: already far past anything the editor renders comfortably.
_MAX_APPLY_ITEMS = 20000


def _boq_service(session: SessionDep) -> Any:
    from app.modules.boq.service import BOQService

    return BOQService(session)


def _is_section(position: Any) -> bool:
    from app.modules.boq.service import _is_section as service_is_section

    return service_is_section(position)


async def _verify_boq(session: Any, boq_id: uuid.UUID, user_id: str, payload: dict | None) -> None:
    from app.modules.boq.router import _verify_boq_owner

    await _verify_boq_owner(session, boq_id, user_id, payload)


async def _read_upload(file: UploadFile, *, extensions: tuple[str, ...], label: str) -> tuple[bytes, str]:
    name = file.filename or ""
    if not name.lower().endswith(extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImporterParseError(
                f"Unsupported file type. Please upload a {label} file ({', '.join(extensions)}).",
                code="gaeb_file_type",
                params={"format": label, "extensions": ", ".join(extensions)},
            ).as_detail(),
        )
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImporterParseError("Uploaded file is empty.", code="gaeb_empty_file").as_detail(),
        )
    return content, name


# ── X31 export ───────────────────────────────────────────────────────────


@gaeb_exchange_router.get(
    "/boqs/{boq_id}/export/gaeb-x31",
    summary="Export measured quantities as GAEB X31 (no-slash alias)",
    dependencies=[Depends(RequirePermission("boq.read"))],
    include_in_schema=False,
)
@gaeb_exchange_router.get(
    "/boqs/{boq_id}/export/gaeb-x31/",
    summary="Export the measured quantities of a BOQ as GAEB DA XML 3.3 X31 (Mengenermittlung)",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def export_boq_gaeb_x31(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    basis: Literal["measured", "quantity"] = Query(
        "measured",
        description=(
            "``measured`` (default) writes the total of each position's measurement sheet and leaves out "
            "positions that have none. ``quantity`` writes every position's bill quantity."
        ),
    ),
) -> StreamingResponse:
    """Write the bill's measured quantities as an X31, one total per OZ.

    Positions whose OZ cannot be written are left out and counted in the
    ``X-GAEB-Skipped`` header, together with the written count in
    ``X-GAEB-Written``. With ``basis=measured`` and no measured position at all
    the call answers 422 rather than handing over an empty measurement.
    """
    from app.modules.projects.repository import ProjectRepository

    await _verify_boq(session, boq_id, user_id, payload)
    service = _boq_service(session)
    boq = await service.boq_repo.get_by_id(boq_id)
    if boq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("errors.boq_not_found", locale=get_locale())
        )
    positions = await service.position_repo.list_all_for_boq(boq_id)

    entries: list[tuple[str, Decimal]] = []
    index_of: dict[str, str] = {}
    for pos in positions:
        if _is_section(pos):
            continue
        meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
        recorded_index = str(meta.get("gaeb_rno_index") or "").strip()
        if recorded_index:
            index_of[str(pos.ordinal or "").strip()] = recorded_index
        if basis == "measured":
            measured = measured_quantity_of(pos)
            if measured is None:
                continue
            entries.append((str(pos.ordinal or ""), measured))
        else:
            entries.append((str(pos.ordinal or ""), dec(pos.quantity) or Decimal("0")))

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ImporterParseError(
                (
                    "No position of this bill has a measurement sheet yet, so there is no measured "
                    "quantity to export. Measure the positions first, or export the bill quantities."
                )
                if basis == "measured"
                else "There are no position quantities to export.",
                code="gaeb_no_measured_quantities" if basis == "measured" else "gaeb_no_quantities",
            ).as_detail(),
        )

    project = await ProjectRepository(session).get_by_id(boq.project_id)
    project_name = project.name if project else ""
    exported = await asyncio.to_thread(
        build_x31_xml,
        entries,
        boq_name=str(boq.name or ""),
        project_name=project_name,
        index_of=index_of,
    )
    filename = f"{boq.name or 'boq'}.X31"
    return StreamingResponse(
        iter([exported.xml]),
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "X-GAEB-Written": str(len(exported.written)),
            "X-GAEB-Skipped": str(len(exported.skipped)),
            "Access-Control-Expose-Headers": "X-GAEB-Written, X-GAEB-Skipped",
        },
    )


# ── X31 import: preview and apply ────────────────────────────────────────


@gaeb_exchange_router.post(
    "/boqs/{boq_id}/import/gaeb-x31/preview/",
    summary="Read a GAEB X31 and propose measured quantities per OZ (writes nothing)",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def preview_boq_gaeb_x31(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    file: UploadFile = File(..., description="GAEB X31 file (.x31 or .xml)"),
) -> dict[str, Any]:
    """Match every OZ of the file to a position and propose its measured quantity.

    Nothing is written. The response lists each matched position with the
    quantity it carries now, its current measured total and the quantity
    from the file, and every OZ that matched nothing (unknown OZ, an OZ two
    positions answer to, an OZ the file names twice, or rows without a
    total). The person picks the proposals to keep and sends them to
    ``/apply/``.
    """
    await _verify_boq(session, boq_id, user_id, payload)
    content, name = await _read_upload(file, extensions=(".x31", ".xml"), label="GAEB X31")
    try:
        parsed = await asyncio.to_thread(parse_x31, content)
    except ImporterParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.as_detail()) from exc

    service = _boq_service(session)
    positions = await service.position_repo.list_all_for_boq(boq_id)
    proposal = propose_x31(parsed, positions, is_section=_is_section)
    proposal["file_name"] = name
    return proposal


class X31ApplyItem(BaseModel):
    """One proposal the person confirmed."""

    position_id: uuid.UUID
    quantity: str = Field(..., max_length=40, description="The measured quantity, as a decimal string.")
    oz: str = Field(default="", max_length=120)
    rows: list[str] = Field(default_factory=list, max_length=500)
    version: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The position's version the preview read (``position_version``). When the position has been "
            "edited since, the item is refused with ``version_conflict`` instead of overwriting the edit."
        ),
    )


class X31ApplyRequest(BaseModel):
    """The confirmed part of an X31 preview."""

    file_name: str = Field(default="", max_length=255)
    set_boq_quantity: bool = Field(
        default=False,
        description=(
            "Also make the measured quantity the position's bill quantity. Off by default: the bill "
            "quantity prices the bill, and a measurement is not a decision to re-price it."
        ),
    )
    items: list[X31ApplyItem] = Field(..., min_length=1, max_length=_MAX_APPLY_ITEMS)


@gaeb_exchange_router.post(
    "/boqs/{boq_id}/import/gaeb-x31/apply/",
    summary="Apply confirmed GAEB X31 measured quantities to positions",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def apply_boq_gaeb_x31(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    body: X31ApplyRequest = Body(...),
) -> dict[str, Any]:
    """Write each confirmed measured quantity as the position's measurement sheet.

    The sheet is one line holding the measured total, so the measurement
    drawer, the reconciliation against the bill quantity and the REB / OENORM
    renderings read it like any other sheet. It replaces the sheet the
    position had; the preview says how many lines that sheet has, and the
    dialog does not tick a position whose take-off has more than one. The
    bill quantity changes only when ``set_boq_quantity`` is true. Every write
    goes through the normal position update, so the lock and the activity
    log apply, and an item that carries the ``version`` its preview read is
    refused with ``version_conflict`` when the position was edited since.

    A position that is not in this bill, a section row, or an unreadable
    quantity is refused per item and reported; the other items still apply.
    Confirming the same file twice leaves the same state: an item whose sheet
    and quantity already say what it would write is counted as unchanged and
    not written again.
    """
    from app.modules.boq.schemas import PositionUpdate

    await _verify_boq(session, boq_id, user_id, payload)
    service = _boq_service(session)
    await service._ensure_boq_writable(boq_id)
    positions = {p.id: p for p in await service.position_repo.list_all_for_boq(boq_id)}

    applied: list[str] = []
    unchanged: list[str] = []
    errors: list[dict[str, str]] = []
    seen: set[uuid.UUID] = set()
    for item in body.items:
        pid = item.position_id
        if pid in seen:
            errors.append({"position_id": str(pid), "error": "duplicate_item"})
            continue
        seen.add(pid)
        pos = positions.get(pid)
        if pos is None:
            # Not in this bill. Said the same way whether it exists elsewhere or
            # not at all, so the answer reveals nothing about other bills.
            errors.append({"position_id": str(pid), "error": "position_not_in_boq"})
            continue
        if _is_section(pos):
            errors.append({"position_id": str(pid), "error": "position_is_section"})
            continue
        quantity = dec(item.quantity.replace(",", "."))
        if quantity is None or abs(quantity) >= Decimal("100000000"):
            errors.append({"position_id": str(pid), "error": "invalid_quantity"})
            continue
        quantity = q3(quantity)
        if body.set_boq_quantity and quantity < 0:
            errors.append({"position_id": str(pid), "error": "negative_quantity"})
            continue

        existing_meta = dict(pos.metadata_) if isinstance(pos.metadata_, dict) else {}
        sheet = measurement_from_x31(
            quantity,
            unit=str(pos.unit or ""),
            file_name=body.file_name,
            oz=item.oz or str(pos.ordinal or ""),
            rows=item.rows,
        )
        same_sheet = existing_meta.get("measurement") == sheet
        current_qty = dec(pos.quantity) or Decimal("0")
        same_qty = (not body.set_boq_quantity) or q3(current_qty) == quantity
        if same_sheet and same_qty:
            unchanged.append(str(pid))
            continue
        current_version = int(getattr(pos, "version", 0) or 0)
        if item.version is not None and item.version != current_version:
            errors.append({"position_id": str(pid), "error": "version_conflict"})
            continue

        update_fields: dict[str, Any] = {"metadata": {**existing_meta, "measurement": sheet}}
        if body.set_boq_quantity:
            update_fields["quantity"] = float(quantity)
        if item.version is not None:
            # Checked again inside the update, against the row as it is then.
            update_fields["version"] = item.version
        try:
            await service.update_position(pid, PositionUpdate(**update_fields), actor_id=user_id)
        except HTTPException as exc:
            detail = str(exc.detail)
            is_conflict = exc.status_code == status.HTTP_409_CONFLICT and "version" in detail.lower()
            errors.append({"position_id": str(pid), "error": "version_conflict" if is_conflict else detail[:300]})
            continue
        except ValueError as exc:
            errors.append({"position_id": str(pid), "error": str(exc)[:300]})
            continue
        applied.append(str(pid))

    logger.info(
        "GAEB X31 apply on %s: applied=%d unchanged=%d errors=%d set_quantity=%s",
        boq_id,
        len(applied),
        len(unchanged),
        len(errors),
        body.set_boq_quantity,
    )
    return {
        "applied": applied,
        "unchanged": unchanged,
        "errors": errors,
        "set_boq_quantity": body.set_boq_quantity,
    }


# ── X89 check ────────────────────────────────────────────────────────────


@gaeb_exchange_router.post(
    "/boqs/{boq_id}/check/gaeb-x89/",
    summary="Check a received GAEB X89 invoice against the BOQ (writes nothing)",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def check_boq_gaeb_x89(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    file: UploadFile = File(..., description="GAEB X89 file (.x89 or .xml)"),
) -> dict[str, Any]:
    """Report, per invoiced OZ, how the invoice differs from the bill. Applies nothing.

    Discounts and surcharges the invoice carries as ``MarkupItem`` are held
    against the bill's own markups, and an invoice in another currency than
    the bill's is flagged.
    """
    from app.modules.boq.models import BOQMarkup
    from app.modules.projects.repository import ProjectRepository

    await _verify_boq(session, boq_id, user_id, payload)
    content, name = await _read_upload(file, extensions=(".x89", ".xml"), label="GAEB X89")
    try:
        parsed = await asyncio.to_thread(parse_x89, content)
    except ImporterParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.as_detail()) from exc
    service = _boq_service(session)
    positions = await service.position_repo.list_all_for_boq(boq_id)
    markups = (
        (await session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq_id).order_by(BOQMarkup.sort_order)))
        .scalars()
        .all()
    )
    boq = await service.boq_repo.get_by_id(boq_id)
    bill_currency = ""
    if boq is not None:
        boq_meta = boq.metadata_ if isinstance(boq.metadata_, dict) else {}
        project = await ProjectRepository(session).get_by_id(boq.project_id)
        bill_currency = str(boq_meta.get("currency") or getattr(project, "currency", "") or "")
    report = check_x89(parsed, positions, is_section=_is_section, markups=list(markups), bill_currency=bill_currency)
    report["file_name"] = name
    return report


# ── X89 export from a progress claim ─────────────────────────────────────


@dataclass(slots=True)
class _ClaimInvoice:
    data: InvoiceInput
    vat_source: str
    parties_source: dict[str, str]
    warnings: list[dict[str, str]]
    contract_code: str
    claim_number: str
    figures: InvoiceFigures
    placement: InvoicePlacement
    claim_net_due: Decimal


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _party_from_contact(contact: Any) -> InvoiceParty:
    from app.modules.finance.einvoice_parties import buyer_party_from_contact

    fields = buyer_party_from_contact(contact)
    return InvoiceParty(
        name=fields.get("name", ""),
        street=fields.get("line1", ""),
        postcode=fields.get("postcode", ""),
        city=fields.get("city", ""),
        country=fields.get("country_code", ""),
        vat_id=fields.get("vat_id", ""),
        tax_no="",
    )


def _party_from_details(display_name: str, details: dict[str, Any]) -> InvoiceParty:
    def first(*keys: str) -> str:
        for key in keys:
            value = details.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    raw_address = details.get("address")
    address: dict[str, Any] = raw_address if isinstance(raw_address, dict) else {}
    merged = {**address, **{k: v for k, v in details.items() if k != "address"}}
    details = merged
    return InvoiceParty(
        name=display_name.strip() or first("name", "company_name"),
        street=first("line1", "street", "text", "address_line1"),
        postcode=first("postcode", "postal_code", "zip"),
        city=first("city"),
        country=first("country_code", "country"),
        tax_no=first("tax_no", "tax_number"),
        vat_id=first("vat_id", "vat_number"),
    )


async def _our_party(session: Any) -> InvoiceParty | None:
    """The instance's own invoicing identity, from the e-invoice settings."""
    from app.modules.finance.einvoice_settings_models import DEFAULT_SCOPE, EInvoiceSettings

    row = (
        await session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == DEFAULT_SCOPE))
    ).scalar_one_or_none()
    if row is None:
        return None
    return InvoiceParty(
        name=row.seller_name or "",
        street=row.seller_line1 or "",
        postcode=row.seller_postcode or "",
        city=row.seller_city or "",
        country=row.seller_country_code or "",
        tax_no=row.seller_tax_number or "",
        vat_id=row.seller_vat_id or "",
    )


async def _party_from_subcontractor(session: Any, entity_id: uuid.UUID) -> InvoiceParty | None:
    """A subcontractor row as an invoice party, or ``None`` when there is no such row.

    The register keeps its own legal name, address and tax id. A field the row
    leaves empty is answered by the contact it links to, if any, so an address
    kept on the contact still reaches the invoice.
    """
    from app.modules.contacts.models import Contact

    try:
        from app.modules.subcontractors.models import Subcontractor
    except ImportError:
        # Modules are plugins: an install without the subcontractor register
        # simply has no such row, as the contracts service treats it too.
        return None

    sub = await session.get(Subcontractor, entity_id)
    if sub is None:
        return None
    address = sub.address if isinstance(sub.address, dict) else {}
    details: dict[str, Any] = {**address, "tax_no": sub.tax_id or ""}
    if sub.country and not details.get("country_code"):
        details["country_code"] = sub.country
    party = _party_from_details(str(sub.legal_name or sub.trade_name or ""), details)
    if sub.contact_id is not None:
        contact = await session.get(Contact, sub.contact_id)
        if contact is not None:
            linked = _party_from_contact(contact)
            for attr in ("name", "street", "postcode", "city", "country", "vat_id"):
                if not getattr(party, attr):
                    setattr(party, attr, getattr(linked, attr))
    return party


async def _counterparty(session: Any, contract: Any, role: str) -> tuple[InvoiceParty | None, str]:
    """The other side of the contract: its linked record, else its party register entry.

    ``counterparty_id`` names a contact or, on a subcontract, a row of the
    subcontractor register; both are tried, the declared type first, as the
    contracts service resolves the name. A party entry is read from the record
    its ``party_type`` points at.
    """
    from app.modules.contacts.models import Contact
    from app.modules.contracts.models import ContractParty

    async def _from_contact(entity_id: uuid.UUID) -> InvoiceParty | None:
        contact = await session.get(Contact, entity_id)
        return _party_from_contact(contact) if contact is not None else None

    async def _from_subcontractor(entity_id: uuid.UUID) -> InvoiceParty | None:
        return await _party_from_subcontractor(session, entity_id)

    if contract.counterparty_id is not None:
        if (contract.counterparty_type or "client") == "subcontractor":
            lookups = ((_from_subcontractor, "subcontractor"), (_from_contact, "contact"))
        else:
            lookups = ((_from_contact, "contact"), (_from_subcontractor, "subcontractor"))
        for lookup, source in lookups:
            found = await lookup(contract.counterparty_id)
            if found is not None:
                return found, source
    rows = (
        (
            await session.execute(
                select(ContractParty).where(
                    ContractParty.contract_id == contract.id,
                    ContractParty.party_role == role,
                )
            )
        )
        .scalars()
        .all()
    )
    rows = sorted(rows, key=lambda p: (not bool(p.is_primary), str(p.display_name or "")))
    for party in rows:
        if party.party_id is not None:
            if party.party_type == "subcontractor":
                linked = await _from_subcontractor(party.party_id)
            elif party.party_type in ("user", "external"):
                linked = None
            else:
                linked = await _from_contact(party.party_id)
            if linked is not None:
                return linked, "contract_party"
        details = party.contact_details if isinstance(party.contact_details, dict) else {}
        return _party_from_details(str(party.display_name or ""), details), "contract_party"
    return None, "none"


async def _dated_country_rate(session: Any, country: str, on_date: date | None) -> Decimal | None:
    """The country's rate on ``on_date`` from the jurisdiction registry, or ``None`` when it cannot say.

    A past period across a rate change has to be invoiced at the rate in
    force then, not today's. ``None`` (registry missing, country taxed by
    subdivision, nothing on record) sends the caller to the undated table.
    """
    try:
        from app.modules.i18n_foundation.service import I18nFoundationService

        resolution = await I18nFoundationService(session).resolve_tax_rate(
            country, on_date=on_date.isoformat() if on_date else None
        )
    except Exception:  # noqa: BLE001 - modules are plugins; the undated table still answers
        logger.debug("Dated VAT for %s could not be resolved", country, exc_info=True)
        return None
    if not getattr(resolution, "resolved", False):
        return None
    return dec(getattr(resolution, "combined_rate_pct", None))


async def _vat_rate_for(
    session: Any,
    *,
    boq_id: uuid.UUID | None,
    project: Any,
    override: Decimal | None,
    warnings: list[dict[str, str]],
    on_date: date | None = None,
) -> tuple[Decimal, str]:
    """The VAT rate in percent and where it came from.

    In order: an explicit rate on the request; the bill's own active tax
    markups, which is where the X84 export reads tax from; the project's
    default VAT rate; the country's rate in force on ``on_date`` (the invoice
    date), read from the jurisdiction registry the way finance reads it, or
    the country's standard rate when the registry has no answer; zero, said so.
    """
    if override is not None:
        return override, "request"
    if boq_id is not None:
        from app.modules.boq.models import BOQMarkup

        markups = (
            (
                await session.execute(
                    select(BOQMarkup).where(
                        BOQMarkup.boq_id == boq_id,
                        BOQMarkup.category == "tax",
                        BOQMarkup.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        rates = [dec(m.percentage) for m in markups if (m.markup_type or "percentage") == "percentage"]
        rates = [r for r in rates if r is not None and r > 0]
        if any((m.markup_type or "percentage") != "percentage" for m in markups):
            warnings.append({"code": "fixed_tax_markup_ignored", "detail": "A fixed-amount tax markup has no rate."})
        if rates:
            if len(rates) > 1:
                warnings.append({"code": "several_tax_markups", "detail": "Rates were added into one VAT rate."})
            return sum(rates, Decimal("0")), "boq_tax_markup"
    if project is not None:
        raw = dec(getattr(project, "default_vat_rate", None))
        if raw is not None:
            return raw, "project_default"
        country = str(getattr(project, "country_code", "") or "").strip().upper()
        if country:
            from app.core.tax import VATNotApplicable, get_vat_rate

            dated = await _dated_country_rate(session, country, on_date)
            if dated is not None:
                return dated, "country_standard"
            try:
                return get_vat_rate(country) * Decimal("100"), "country_standard"
            except VATNotApplicable:
                pass
    warnings.append({"code": "no_vat_rate", "detail": "No VAT rate is known for this claim; 0 % was used."})
    return Decimal("0"), "none"


#: Invoice kinds the export accepts on the wire. The two final kinds are
#: refused with a 422 for now (see :func:`_refuse_cumulative_invoice`).
_InvoiceTypeParam = Literal[
    "deduction",
    "final account",
    "part final account",
    "single invoice",
]

_HALF_CENT = Decimal("0.005")


def _claim_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=translate("errors.claim_not_found", locale=get_locale()),
    )


def _refuse_cumulative_invoice(invoice_type: str) -> None:
    """Refuse a final account until it is built from cumulative figures.

    A Schlussrechnung bills everything performed less what earlier invoices
    already billed. Written from one claim it billed the last period only and
    deducted nothing, which is a wrong document rather than a rough one.
    """
    if invoice_type in CUMULATIVE_INVOICE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=translate("errors.gaeb_x89_final_account_unsupported", locale=get_locale()),
        )


def _rounding_tolerance(line_count: int) -> Decimal:
    """How far a sum of cent-rounded lines may honestly sit from the same sum kept at four decimals."""
    return _HALF_CENT * max(line_count, 1) + _HALF_CENT


def _retention_on_billed_work(
    accrual: Decimal,
    claim_lines: list[Any],
    previous_lines: list[Any],
) -> tuple[Decimal, Decimal, bool]:
    """The retention an X89 deducts, the stored-materials part left out, and whether stored materials moved.

    An X89 bills the work of the period (``period_completed_value``), never
    materials stored on site. The claim's accrual is worked out on both, so
    the part of it that is held on stored materials comes out: the change in
    retention held on stored materials since the previous claim, read from
    the per-line snapshot the retention engine writes. When the engine never
    ran for the claim (flat retention), the accrual is already on the gross
    the lines bill, and stands.

    Stored materials moving between the two claims is what makes the claim's
    net due and the X89 differ even then, so it is reported for the warning.
    """
    stored_now = sum(
        (dec(getattr(cl, "materials_stored_value", 0)) or Decimal("0") for cl in claim_lines), Decimal("0")
    )
    stored_before = sum(
        (dec(getattr(cl, "materials_stored_value", 0)) or Decimal("0") for cl in previous_lines), Decimal("0")
    )
    stored_moved = stored_now != stored_before
    engine_ran = any(getattr(cl, "retention_to_date", None) is not None for cl in claim_lines)
    if not engine_ran:
        return accrual, Decimal("0"), stored_moved
    held_now = sum(
        (dec(getattr(cl, "retention_stored_to_date", None)) or Decimal("0") for cl in claim_lines), Decimal("0")
    )
    held_before = sum(
        (dec(getattr(cl, "retention_stored_to_date", None)) or Decimal("0") for cl in previous_lines), Decimal("0")
    )
    stored_part = held_now - held_before
    return max(accrual - stored_part, Decimal("0")), stored_part, stored_moved


async def _claim_invoice(
    session: Any,
    claim_id: uuid.UUID,
    user_id: str,
    *,
    vat_rate: Decimal | None,
    invoice_type: str,
) -> _ClaimInvoice:
    """Gather an X89's content from a progress claim, its contract and the bill behind it."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
    from app.modules.contracts.periods import claims_before
    from app.modules.contracts.repository import ProgressClaimRepository, RetentionReleaseRepository
    from app.modules.contracts.service import boq_position_id_for_line
    from app.modules.projects.repository import ProjectRepository

    claim = await session.get(ProgressClaim, claim_id)
    if claim is None:
        raise _claim_not_found()
    contract = await session.get(Contract, claim.contract_id)
    if contract is None:
        raise _claim_not_found()
    try:
        await verify_project_access(contract.project_id, user_id, session)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
            # The same answer as a claim that does not exist, so a claim id
            # from another project tells the caller nothing about it.
            raise _claim_not_found() from None
        raise
    project = await ProjectRepository(session).get_by_id(contract.project_id)

    claim_lines = (
        (await session.execute(select(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == claim_id)))
        .scalars()
        .all()
    )
    line_ids = [cl.contract_line_id for cl in claim_lines]
    contract_lines: dict[uuid.UUID, Any] = {}
    if line_ids:
        rows = (await session.execute(select(ContractLine).where(ContractLine.id.in_(line_ids)))).scalars().all()
        contract_lines = {row.id: row for row in rows}
    position_ids = [pid for pid in (boq_position_id_for_line(cl) for cl in contract_lines.values()) if pid]
    linked: dict[uuid.UUID, Any] = {}
    if position_ids:
        rows = (await session.execute(select(Position).where(Position.id.in_(position_ids)))).scalars().all()
        # Only positions of this project's bills: a stale link to another
        # project's position must not lend this invoice its OZ.
        boq_projects = {}
        boq_ids = {row.boq_id for row in rows}
        if boq_ids:
            for bid, pid in (await session.execute(select(BOQ.id, BOQ.project_id).where(BOQ.id.in_(boq_ids)))).all():
                boq_projects[bid] = pid
        linked = {row.id: row for row in rows if boq_projects.get(row.boq_id) == contract.project_id}

    warnings: list[dict[str, str]] = []
    invoice_lines, boq_counts = invoice_lines_from_claim(
        claim_lines,
        contract_lines,
        linked,
        position_for_line=boq_position_id_for_line,
    )

    invoice_date = _parse_date(claim.application_date) or _parse_date(claim.claim_date)
    main_boq_id = max(boq_counts, key=lambda b: boq_counts[b]) if boq_counts else None
    boq_name = ""
    if main_boq_id is not None:
        boq_row = await session.get(BOQ, main_boq_id)
        boq_name = str(getattr(boq_row, "name", "") or "")
    rate, vat_source = await _vat_rate_for(
        session,
        boq_id=main_boq_id,
        project=project,
        override=vat_rate,
        warnings=warnings,
        on_date=invoice_date,
    )

    ours = await _our_party(session) or InvoiceParty()
    is_subcontract = (contract.counterparty_type or "client") == "subcontractor"
    if is_subcontract:
        other, other_source = await _counterparty(session, contract, "subcontractor")
        creator, recipient = other or InvoiceParty(), ours
        parties_source = {"creator": other_source, "recipient": "einvoice_settings"}
        if str(getattr(project, "country_code", "") or "").strip().upper() == "DE":
            warnings.append(
                {
                    "code": "subcontract_reverse_charge_de",
                    "detail": (
                        "The invoice is issued in the subcontractor's name. Check whether reverse charge "
                        "(section 13b UStG) applies before it is sent."
                    ),
                }
            )
    else:
        other, other_source = await _counterparty(session, contract, "employer")
        creator, recipient = ours, other or InvoiceParty()
        parties_source = {"creator": "einvoice_settings", "recipient": other_source}

    # Billing order, as the payment application counts claims. A draft has
    # not been sent and a rejected claim billed nothing, so neither takes a
    # number in the sequence; the claim being written always counts itself.
    claim_repo = ProgressClaimRepository(session)
    ordered = await claim_repo.ordered_for_contract(contract.id)
    earlier = [c for c in claims_before(ordered, claim.id) if c.status not in ("draft", "rejected")]
    sequential_no = len(earlier) + 1

    prior = await claim_repo.prior_claims(contract.id, before_claim_id=claim.id)
    previous_lines: list[Any] = []
    if prior:
        previous_lines = list(
            (
                await session.execute(
                    select(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == prior[-1].id)
                )
            )
            .scalars()
            .all()
        )
    accrual = dec(claim.retention_amount) or Decimal("0")
    retention, _stored_part, stored_moved = _retention_on_billed_work(accrual, list(claim_lines), previous_lines)
    released = sum(
        (dec(r.amount) or Decimal("0") for r in await RetentionReleaseRepository(session).billed_on_claims([claim.id])),
        Decimal("0"),
    )

    data = InvoiceInput(
        invoice_no=str(claim.claim_number or "").strip(),
        invoice_date=invoice_date,
        period_start=_parse_date(claim.period_from) or _parse_date(claim.period_start),
        period_end=_parse_date(claim.period_to) or _parse_date(claim.period_end),
        currency=str(claim.currency or contract.currency or getattr(project, "currency", "") or ""),
        project_name=str(getattr(project, "name", "") or ""),
        boq_name=boq_name or str(contract.code or ""),
        lines=invoice_lines,
        vat_rate=rate,
        retention=retention,
        creator=creator,
        recipient=recipient,
        invoice_type=invoice_type,
        sequential_no=sequential_no,
        release=released,
    )
    gross_claimed = dec(claim.gross_amount) or Decimal("0")
    net_written = sum((c2(ln.amount) for ln in invoice_lines), Decimal("0"))
    gross_differs = abs(gross_claimed - net_written) > _rounding_tolerance(len(invoice_lines))
    if gross_differs:
        warnings.append(
            {
                "code": "claim_gross_differs_from_lines",
                "detail": f"The claim's gross {c2(gross_claimed)} is not the sum of its lines {net_written}.",
            }
        )

    figures, placement = x89_figures(data)
    net_due = dec(claim.net_due) or Decimal("0")
    outstanding = figures.outstanding_before_vat
    if abs(outstanding - net_due) > _rounding_tolerance(len(invoice_lines)):
        if stored_moved:
            reason = "stored_materials"
        elif gross_differs:
            reason = "claim_gross_differs_from_lines"
        elif any(getattr(cl, "retention_to_date", None) is not None for cl in claim_lines):
            reason = "certified_to_date"
        else:
            reason = "other"
        warnings.append(
            {
                "code": "outstanding_differs_from_net_due",
                "reason": reason,
                "detail": f"The invoice states {outstanding} before VAT, the claim's net due is {c2(net_due)}.",
            }
        )
    return _ClaimInvoice(
        data=data,
        vat_source=vat_source,
        parties_source=parties_source,
        warnings=warnings,
        contract_code=str(contract.code or ""),
        claim_number=str(claim.claim_number or ""),
        figures=figures,
        placement=placement,
        claim_net_due=c2(net_due),
    )


def _party_dict(party: InvoiceParty) -> dict[str, str]:
    return {
        "name": party.name,
        "street": party.street,
        "postcode": party.postcode,
        "city": party.city,
        "country": party.country,
        "tax_no": party.tax_no,
        "vat_id": party.vat_id,
    }


@gaeb_exchange_router.get(
    "/claims/{claim_id}/gaeb-x89/preview/",
    summary="Preview the GAEB X89 invoice of a progress claim",
    dependencies=[Depends(RequirePermission("contracts.read"))],
)
async def preview_claim_gaeb_x89(
    claim_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    vat_rate: Decimal | None = Query(None, ge=0, le=100, description="VAT rate in percent, overriding the bill's."),
    invoice_type: _InvoiceTypeParam = Query(INVOICE_TYPE_PROGRESS),
) -> dict[str, Any]:
    """Return the figures, parties and gaps of the X89 this claim would produce.

    ``figures.outstanding_before_vat`` is set beside ``claim_net_due`` so a
    person sees whether the invoice asks for what the claim says is due, and
    a warning names the reason when it does not. ``remapped`` lists every
    line that could not keep its own OZ and the OZ it is written under.
    """
    _refuse_cumulative_invoice(invoice_type)
    gathered = await _claim_invoice(session, claim_id, user_id, vat_rate=vat_rate, invoice_type=invoice_type)
    data = gathered.data
    return {
        "claim_id": str(claim_id),
        "claim_number": gathered.claim_number,
        "contract_code": gathered.contract_code,
        "invoice_type": data.invoice_type,
        "invoice_date": data.invoice_date.isoformat() if data.invoice_date else None,
        "period_start": data.period_start.isoformat() if data.period_start else None,
        "period_end": data.period_end.isoformat() if data.period_end else None,
        "currency": data.currency,
        "line_count": len(gathered.placement.placed),
        "figures": gathered.figures.as_strings(),
        "claim_net_due": str(gathered.claim_net_due),
        "vat_source": gathered.vat_source,
        "creator": _party_dict(data.creator),
        "recipient": _party_dict(data.recipient),
        "parties_source": gathered.parties_source,
        "missing": missing_invoice_fields(data),
        "warnings": gathered.warnings,
        "remapped": gathered.placement.remapped,
        "merged": gathered.placement.merged,
    }


@gaeb_exchange_router.get(
    "/claims/{claim_id}/export/gaeb-x89/",
    summary="Export a progress claim as a GAEB DA XML 3.3 X89 invoice (Rechnung)",
    dependencies=[Depends(RequirePermission("contracts.read"))],
)
async def export_claim_gaeb_x89(
    claim_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    vat_rate: Decimal | None = Query(None, ge=0, le=100, description="VAT rate in percent, overriding the bill's."),
    invoice_type: _InvoiceTypeParam = Query(INVOICE_TYPE_PROGRESS),
) -> StreamingResponse:
    """Write the claim as an X89. Refuses with 422 and the list of gaps when a mandatory field is unknown."""
    _refuse_cumulative_invoice(invoice_type)
    gathered = await _claim_invoice(session, claim_id, user_id, vat_rate=vat_rate, invoice_type=invoice_type)
    missing = missing_invoice_fields(gathered.data)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "gaeb_invoice_fields_missing",
                "message": "The invoice cannot be written until these fields are known: " + ", ".join(missing),
                "missing": missing,
            },
        )
    exported = await asyncio.to_thread(build_x89_xml, gathered.data)
    safe_no = (gathered.claim_number or "claim").replace("/", "-").replace(" ", "_")
    filename = f"{gathered.contract_code or 'contract'}_{safe_no}.X89"
    return StreamingResponse(
        iter([exported.xml]),
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "X-GAEB-Remapped": str(len(exported.remapped)),
            "Access-Control-Expose-Headers": "X-GAEB-Remapped",
        },
    )


__all__ = ["gaeb_exchange_router"]

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""From package header to filed award: the issuing company, controlling figures, rejections, filing.

A package is bought for one company of the group. It names the company itself
(``legal_entity_id``) or takes the project's; letters, the award record and the
contract are issued in that company's name. On award, controlling receives the
project, package, cost line, contract sum and company in the award event (and
through it every webhook). After the award every unsuccessful bidder is sent a
rejection letter in one action, and the contract, award record and letters are
filed as project documents.

Kept apart from ``service.py`` so the award path there only gains calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.schemas import (
    AwardFilingResponse,
    FiledDocument,
    HeaderCostLine,
    IssuingEntity,
    PackageHeaderResponse,
    PackageHeaderUpdate,
    RejectionRow,
    RejectionsPreview,
    RejectionsSendResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.legal_entities.models import LegalEntity
    from app.modules.tendering.service import TenderingService

logger = logging.getLogger(__name__)

#: Bid metadata key holding the rejection notice state: ``{state, sent_at, last_error, document_id}``.
REJECTION_NOTICE_KEY = "rejection_notice"
#: Package metadata key mapping a filed kind to its document id.
FILING_KEY = "award_filing"
#: Header dates in the order a tender runs through them.
_DATE_ORDER = ("issue_date", "questions_until", "bids_due", "award_planned")
_HEADER_FIELDS = tuple(PackageHeaderUpdate.model_fields)
#: Header fields fixed once the package is awarded: the contract is already issued in that name.
_FIXED_AFTER_AWARD = ("legal_entity_id", "cost_line_id")


# ── Issuing company ──────────────────────────────────────────────────────────


async def active_entity_count(session: AsyncSession) -> int:
    from app.modules.legal_entities.models import LegalEntity

    return int(
        (await session.execute(select(func.count(LegalEntity.id)).where(LegalEntity.is_active.is_(True)))).scalar_one()
        or 0
    )


async def issuing_entity(session: AsyncSession, package: TenderPackage) -> tuple[LegalEntity | None, str]:
    """The company the package is issued in, and ``package`` or ``project`` for where it came from."""
    from app.modules.legal_entities.models import LegalEntity
    from app.modules.projects.models import Project

    if package.legal_entity_id is not None:
        entity = await session.get(LegalEntity, package.legal_entity_id)
        if entity is not None:
            return entity, "package"
    project = await session.get(Project, package.project_id)
    if project is not None and project.legal_entity_id is not None:
        entity = await session.get(LegalEntity, project.legal_entity_id)
        if entity is not None:
            return entity, "project"
    return None, "project"


def _issuing_out(entity: LegalEntity | None, source: str) -> IssuingEntity | None:
    if entity is None:
        return None
    return IssuingEntity(id=entity.id, code=entity.code, name=entity.legal_name or entity.name, source=source)  # type: ignore[arg-type]


def issuer_identity(entity: LegalEntity) -> dict[str, Any]:
    """What a letter prints for its sender: name, address, tax and register ids, bank, signatory."""
    from app.modules.legal_entities.tax_ids import primary_tax_id

    address = entity.address or {}
    street = ", ".join(p for p in (address.get("line1"), address.get("line2")) if p)
    town = " ".join(p for p in (address.get("postcode"), address.get("city")) if p)
    bank = entity.bank or {}
    return {
        "name": entity.legal_name or entity.name,
        "address": ", ".join(p for p in (street, town, entity.country_code) if p),
        "tax_id": primary_tax_id(entity.country_code, entity.tax_ids or [], legacy=entity.tax_id),
        "registration": entity.registration_number or "",
        "bank": " / ".join(p for p in (bank.get("bank_name"), bank.get("iban"), bank.get("bic")) if p),
        "signatory": entity.default_signatory or "",
    }


async def issuer_for(session: Any, package: Any) -> dict[str, Any] | None:
    """The sender block for a letter of *package*, or ``None`` when no company is assigned.

    Never a reason to lose a letter: a session that cannot answer leaves the
    letter in the install's letterhead, as before companies existed.
    """
    if not hasattr(session, "execute") or not isinstance(package, TenderPackage):
        return None
    try:
        entity, _source = await issuing_entity(session, package)
    except Exception:  # noqa: BLE001
        logger.exception("Issuing company of package %s could not be read", getattr(package, "id", None))
        return None
    return issuer_identity(entity) if entity is not None else None


# ── Header ───────────────────────────────────────────────────────────────────


def header_warnings(values: dict[str, Any]) -> list[str]:
    """Dates out of order, as codes: ``<earlier>_after_<later>``."""
    out: list[str] = []
    present = [(k, values.get(k)) for k in _DATE_ORDER if values.get(k) is not None]
    for (a, da), (b, db) in zip(present, present[1:], strict=False):
        if da > db:
            out.append(f"{a}_after_{b}")
    return out


async def _package_budget(session: AsyncSession, package: TenderPackage) -> Decimal:
    if package.boq_id is None:
        return Decimal("0")
    from app.modules.boq.service import BOQService
    from app.modules.tendering.package_contents import package_budget
    from app.modules.tendering.service import _positions_in_scope

    try:
        boq = await BOQService(session).get_boq_with_positions(package.boq_id)
    except HTTPException:
        return Decimal("0")
    return package_budget(_positions_in_scope(list(boq.positions), package.metadata_), package.metadata_).effective


async def _cost_line(session: AsyncSession, project_id: uuid.UUID, cost_line_id: uuid.UUID | None) -> Any:
    if cost_line_id is None:
        return None
    from app.modules.costmodel.models import CostLine

    line = await session.get(CostLine, cost_line_id)
    return line if line is not None and line.project_id == project_id else None


async def read_header(session: AsyncSession, package: TenderPackage) -> PackageHeaderResponse:
    from app.modules.projects.models import Project

    entity, source = await issuing_entity(session, package)
    line = await _cost_line(session, package.project_id, package.cost_line_id)
    project = await session.get(Project, package.project_id)
    values = {f: getattr(package, f) for f in _HEADER_FIELDS}
    return PackageHeaderResponse(
        package_id=package.id,
        **values,
        issuing_entity=_issuing_out(entity, source),
        cost_line=(
            HeaderCostLine(
                id=line.id, code=line.code, description=line.description or "", budget=line.estimate_amount or "0"
            )
            if line is not None
            else None
        ),
        budget=format(await _package_budget(session, package), "f"),
        currency=((getattr(project, "currency", "") or "").upper() if project is not None else ""),
        active_entity_count=await active_entity_count(session),
        warnings=header_warnings(values),
    )


async def write_header(session: AsyncSession, package: TenderPackage, data: PackageHeaderUpdate) -> TenderPackage:
    """Apply the header fields sent. A company must exist and be active; a cost line must be the project's."""
    from app.modules.legal_entities.models import LegalEntity

    fields = data.model_dump(exclude_unset=True)
    if package.status in ("awarded", "closed"):
        fixed = [f for f in _FIXED_AFTER_AWARD if f in fields and fields[f] != getattr(package, f)]
        if fixed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Package is {package.status}; its company and cost line are fixed ({', '.join(fixed)})",
            )
    entity_id = fields.get("legal_entity_id")
    if entity_id is not None:
        entity = await session.get(LegalEntity, entity_id)
        if entity is None or not entity.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Company not found or inactive"
            )
    line_id = fields.get("cost_line_id")
    if line_id is not None and await _cost_line(session, package.project_id, line_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cost line is not on this project"
        )
    for key, value in fields.items():
        setattr(package, key, value)
    await session.flush()
    return package


# ── Award to controlling ─────────────────────────────────────────────────────


async def controlling_fields(session: Any, package: TenderPackage, bid: TenderBid) -> dict[str, Any]:
    """What controlling needs from an award, merged into the ``tendering.package.awarded`` event.

    ``contract_sum`` is the awarded bid's total as a Decimal string. Never a
    reason to lose the award: a failure leaves the event as it was.
    """
    out: dict[str, Any] = {
        "project_id": str(package.project_id),
        "package_name": package.name,
        "trade": package.trade,
        "contract_sum": format(Decimal(str(bid.total_amount or "0")), "f"),
        "currency": (bid.currency or "").strip().upper(),
        "cost_line_id": str(package.cost_line_id) if package.cost_line_id else None,
        "cost_code": None,
        "legal_entity_id": None,
        "legal_entity_code": None,
        "legal_entity_name": None,
    }
    if not hasattr(session, "execute"):
        return out
    try:
        line = await _cost_line(session, package.project_id, package.cost_line_id)
        if line is not None:
            out["cost_code"] = line.code
        entity, _source = await issuing_entity(session, package)
        if entity is not None:
            out.update(
                legal_entity_id=str(entity.id),
                legal_entity_code=entity.code,
                legal_entity_name=entity.legal_name or entity.name,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Controlling fields of package %s could not be read", package.id)
    return out


# ── Rejections ───────────────────────────────────────────────────────────────


def _notice(bid: TenderBid) -> dict[str, Any]:
    raw = (bid.metadata_ or {}).get(REJECTION_NOTICE_KEY)
    return raw if isinstance(raw, dict) else {}


def _row(bid: TenderBid) -> RejectionRow:
    notice = _notice(bid)
    email = (bid.contact_email or "").strip()
    state = notice.get("state") or ("pending" if email else "no_email")
    if state == "failed" and not email:
        state = "no_email"
    return RejectionRow(
        bid_id=bid.id,
        company_name=bid.company_name,
        email=email,
        notified_at=notice.get("sent_at"),
        state=state,
        last_error=notice.get("last_error"),
    )


async def _rejected_bids(session: AsyncSession, package: TenderPackage) -> list[TenderBid]:
    rows = (
        await session.execute(
            select(TenderBid)
            .where(TenderBid.package_id == package.id, TenderBid.status == "rejected")
            .order_by(TenderBid.company_name)
        )
    ).scalars()
    return list(rows)


async def rejection_preview(session: AsyncSession, package: TenderPackage) -> RejectionsPreview:
    entity, source = await issuing_entity(session, package)
    awarded = package.status in ("awarded", "closed") and bool((package.metadata_ or {}).get("awarded_bid_id"))
    rows = [_row(b) for b in await _rejected_bids(session, package)] if awarded else []
    return RejectionsPreview(
        package_id=package.id,
        awarded=awarded,
        issuing_entity=_issuing_out(entity, source),
        rows=rows,
        pending=sum(1 for r in rows if r.state in ("pending", "failed")),
    )


def _rejection_email_html(text: Any, values: dict[str, str | None]) -> tuple[str, str]:
    from app.core.letter_templates import render, split_paragraphs

    subject = render(text.subject, values) or str(values.get("package") or "")
    parts = [render(text.heading, values), *split_paragraphs(render(text.body, values)), render(text.closing, values)]
    body = "".join(f"<p>{html.escape(p)}</p>" for p in parts if p)
    if values.get("sender"):
        body += f"<p>{html.escape(str(values['sender']))}</p>"
    return subject, body


async def send_rejections(
    service: TenderingService, package: TenderPackage, bid_ids: list[uuid.UUID], *, actor_id: str | None
) -> RejectionsSendResponse:
    """Email every pending rejected bidder its letter (PDF attached) and file each letter.

    A bidder already told is skipped; one who has no email is listed and not
    sent. One failed delivery is recorded and does not stop the rest.
    """
    from app.config import get_settings
    from app.core.email import EmailAttachment, EmailMessage, get_email_service
    from app.core.email.service import email_delivery_enabled
    from app.modules.doc_templates.service import log_letter_issue
    from app.modules.tendering.letter_texts import REJECTION_KEY

    session = service.session
    preview = await rejection_preview(session, package)
    if not preview.awarded:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rejection letters are sent after the award")
    wanted = {str(b) for b in bid_ids}
    bids = [
        b
        for b in await _rejected_bids(session, package)
        if (not wanted or str(b.id) in wanted) and _row(b).state in ("pending", "failed")
    ]
    mailer = get_email_service()
    issuer = await issuer_for(session, package)
    project_name, _currency = await service._project_name_and_currency(package)
    sent = failed = filed = 0
    for bid in bids:
        pdf, filename = await service.build_rejection_letter_pdf(package.id, bid.id)
        language = service.last_letter_language
        text = await service._letter_text(package, REJECTION_KEY)
        meta = package.metadata_ or {}
        values: dict[str, str | None] = {
            "bidder": bid.company_name,
            "project": project_name,
            "package": package.name,
            "date": datetime.now(UTC).date().isoformat(),
            "sender": meta.get("awarded_by_name") or (issuer or {}).get("signatory") or project_name,
            "company": (issuer or {}).get("name") or "",
        }
        subject, body = _rejection_email_html(text, values)
        result = await mailer.send(
            EmailMessage(
                to=bid.contact_email,
                subject=subject,
                html_body=body,
                tags=["tendering", "rejection_letter"],
                attachments=[EmailAttachment(filename=filename, content=pdf)],
            )
        )
        document_id = await _file_bytes(
            session, package, pdf, filename, kind="rejection_letter", category="correspondence", actor_id=actor_id
        )
        filed += 1 if document_id else 0
        notice = {
            "state": "sent" if result.ok else "failed",
            "sent_at": datetime.now(UTC).isoformat() if result.ok else None,
            "last_error": None if result.ok else (result.reason or "delivery failed")[:300],
            "document_id": str(document_id) if document_id else None,
            "backend": result.backend,
        }
        bid.metadata_ = {**(bid.metadata_ or {}), REJECTION_NOTICE_KEY: notice}
        if result.ok:
            sent += 1
            await log_letter_issue(session, REJECTION_KEY, str(bid.id), package.project_id, language, actor_id)
        else:
            failed += 1
    await session.flush()
    after = await rejection_preview(session, package)
    return RejectionsSendResponse(
        **after.model_dump(),
        sent=sent,
        failed=failed,
        filed=filed,
        backend=mailer.backend_name,
        smtp_configured=email_delivery_enabled(get_settings()),
    )


# ── Filing into project documents ───────────────────────────────────────────


def _award_dir(project_id: uuid.UUID) -> Path:
    from app.core.storage import module_uploads_dir

    return module_uploads_dir("tendering", "award", str(project_id))


async def _file_bytes(
    session: AsyncSession,
    package: TenderPackage,
    content: bytes,
    filename: str,
    *,
    kind: str,
    category: str,
    actor_id: str | None,
) -> uuid.UUID | None:
    """Write *content* under the uploads root and register it as a project document."""
    from app.modules.documents.models import Document

    digest = hashlib.sha256(content).hexdigest()
    target = _award_dir(package.project_id) / f"{package.id.hex[:8]}_{digest[:12]}_{filename}"

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    try:
        await asyncio.to_thread(_write)
        async with session.begin_nested():
            doc = Document(
                project_id=package.project_id,
                name=filename[:255],
                description=package.name[:500],
                category=category,
                file_size=len(content),
                mime_type="application/pdf",
                file_path=str(target),
                version=1,
                uploaded_by=(actor_id or "")[:36],
                tags=["tendering", "award", kind],
                metadata_={"tender_package_id": str(package.id), "kind": kind, "sha256": digest},
            )
            session.add(doc)
            await session.flush()
        return doc.id
    except Exception:  # noqa: BLE001 - the letter is still sent and downloadable
        logger.exception("Filing %s of package %s in documents failed", kind, package.id)
        return None


async def _contract_pdf(session: AsyncSession, package: TenderPackage) -> tuple[bytes, str] | None:
    from app.modules.bid_management.award_contract import find_award_contract

    contract = await find_award_contract(session, package.project_id, keys={"tender_package_id": str(package.id)})
    if contract is None:
        return None
    from app.core.register_context import load_project_header
    from app.modules.contracts.pdf_export import build_contract_pdf
    from app.modules.contracts.repository import ContractLineRepository
    from app.modules.contracts.service import ContractsService

    project = await load_project_header(session, contract.project_id)
    lines = list(await ContractLineRepository(session).list_for_contract(contract.id))
    counterparty = await ContractsService(session).resolve_counterparty_name(contract)
    pdf = await asyncio.to_thread(build_contract_pdf, contract, lines, project=project, counterparty=counterparty)
    return pdf, f"contract_{contract.code}.pdf"


async def file_award_documents(
    service: TenderingService, package: TenderPackage, *, actor_id: str | None
) -> AwardFilingResponse:
    """File the contract draft, the award record and the award letter; each kind once.

    Rejection letters are filed as they are sent and are listed here too.
    """
    session = service.session
    awarded_bid_id = (package.metadata_ or {}).get("awarded_bid_id")
    if package.status not in ("awarded", "closed") or not awarded_bid_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Documents are filed after the award")
    filing = dict((package.metadata_ or {}).get(FILING_KEY) or {})
    out: list[FiledDocument] = []

    async def _one(kind: str, category: str, build: Any) -> None:
        if filing.get(kind):
            out.append(FiledDocument(kind=kind, document_id=filing[kind], name=kind, state="already_filed"))  # type: ignore[arg-type]
            return
        built = await build()
        if built is None:
            out.append(FiledDocument(kind=kind, name=kind, state="skipped", reason="not_drafted"))  # type: ignore[arg-type]
            return
        pdf, filename = built
        doc_id = await _file_bytes(session, package, pdf, filename, kind=kind, category=category, actor_id=actor_id)
        if doc_id is None:
            out.append(FiledDocument(kind=kind, name=filename, state="skipped", reason="storage_failed"))  # type: ignore[arg-type]
            return
        filing[kind] = str(doc_id)
        out.append(FiledDocument(kind=kind, document_id=doc_id, name=filename, state="filed"))  # type: ignore[arg-type]

    await _one("contract", "contract", lambda: _contract_pdf(session, package))
    await _one("award_record", "contract", lambda: service.build_award_record_pdf(package.id))
    await _one(
        "award_letter",
        "correspondence",
        lambda: service.build_award_letter_pdf(package.id, uuid.UUID(str(awarded_bid_id))),
    )
    for bid in await _rejected_bids(session, package):
        doc_id = _notice(bid).get("document_id")
        if doc_id:
            out.append(
                FiledDocument(kind="rejection_letter", document_id=doc_id, name=bid.company_name, state="already_filed")
            )
    package.metadata_ = {**(package.metadata_ or {}), FILING_KEY: filing}
    await session.flush()
    return AwardFilingResponse(package_id=package.id, documents=out)


# ── Validation payload ──────────────────────────────────────────────────────


async def award_validation_payload(session: AsyncSession, package: TenderPackage) -> dict[str, Any]:
    """Payload of the ``tendering_award`` rule set; see ``validators.py``."""
    entity, _source = await issuing_entity(session, package)
    preview = await rejection_preview(session, package)
    return {
        "package_id": str(package.id),
        "active_entity_count": await active_entity_count(session),
        "issuing_entity_id": str(entity.id) if entity is not None else None,
        "awarded": preview.awarded,
        "losers_not_notified": [r.company_name for r in preview.rows if r.state != "sent"],
    }

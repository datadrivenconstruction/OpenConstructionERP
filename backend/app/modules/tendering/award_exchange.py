# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The paper trail of a tender: bill unchanged, award file, offers and request documents.

Buyer side of the exchange around a package:

* **Bill unchanged.** A bill imported from the issuer's file (an X83 from an
  external estimating tool) is compared with the snapshot kept at import
  (``boq.exchange_source``), narrowed to the package's lines.
* **Award file.** The GAEB X86 (Auftragserteilung) is the imported bill with
  its item numbers, units, quantities and texts and the awarded firm's unit
  prices. It is refused while the bill differs from the imported file, and
  every X86 written is filed with the project's documents.
* **Request documents.** Project documents the buyer sends out with the
  package; bidders download them through their own link.
* **Offer files.** What bidders uploaded, per firm, each filed in Documents.

GAEB is one exchange format; the bill-unchanged check is format neutral and
reads any imported file the BOQ module recorded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tendering.models import TenderBidFile, TenderPackage, TenderPackageDocument
from app.modules.tendering.schemas import (
    BidFileResponse,
    BillDifference,
    BillSourceState,
    PackageDocumentResponse,
)

logger = logging.getLogger(__name__)

#: Bid states an award file is never written for.
_NOT_AWARDABLE = frozenset({"rejected", "withdrawn", "disqualified"})
_CENT = Decimal("0.01")


def safe_file_name(name: str, default: str = "file") -> str:
    """A file name safe to put on disk: no path, no control or shell characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    cleaned = re.sub(r"[^\w.\- ]+", "_", base).strip(" .")
    return (cleaned or default)[-150:]


async def store_and_file(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    subdir: str,
    file_name: str,
    content: bytes,
    mime_type: str,
    tags: list[str],
    metadata: dict[str, Any],
    uploaded_by: str = "",
    description: str = "",
) -> tuple[str, uuid.UUID | None]:
    """Write the bytes under the tendering uploads directory and file them as a project document.

    Returns:
        ``(path, document_id)``; ``document_id`` is ``None`` when Documents is
        not installed or filing failed, the bytes are then still on disk.
    """
    from app.core.storage import module_uploads_dir

    digest = hashlib.sha256(content).hexdigest()
    target = module_uploads_dir("tendering", subdir, str(project_id))
    full = target / f"{digest[:12]}_{uuid.uuid4().hex[:6]}_{safe_file_name(file_name)}"

    def _write() -> None:
        target.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)

    await asyncio.to_thread(_write)
    document_id: uuid.UUID | None = None
    try:
        from app.modules.documents.models import Document

        async with session.begin_nested():
            doc = Document(
                project_id=project_id,
                name=safe_file_name(file_name)[:255],
                description=description[:1000],
                category="correspondence",
                file_size=len(content),
                mime_type=mime_type[:100],
                file_path=str(full),
                version=1,
                uploaded_by=uploaded_by[:36],
                tags=tags,
                metadata_=metadata,
            )
            session.add(doc)
            await session.flush()
        document_id = doc.id
    except Exception:  # noqa: BLE001 - the file stays on disk and on the tender
        logger.warning("Filing %s in Documents failed", file_name, exc_info=True)
    return str(full), document_id


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def bid_unit_prices(bid: Any) -> dict[str, Decimal]:
    """Unit price per position id of a bid's lines (lines without a price left out)."""
    prices: dict[str, Decimal] = {}
    for item in bid.line_items or []:
        if not isinstance(item, dict) or not item.get("position_id"):
            continue
        rate = _dec(item.get("unit_rate"))
        if rate is not None and rate >= 0:
            prices[str(item["position_id"])] = rate
    return prices


def _priced_copy(position: Any, rate: Decimal) -> Any:
    quantity = _dec(getattr(position, "quantity", 0)) or Decimal("0")
    total = (quantity * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    if hasattr(position, "model_copy"):
        return position.model_copy(update={"unit_rate": rate, "total": total})
    import copy

    clone = copy.copy(position)
    clone.unit_rate = rate
    clone.total = total
    return clone


def price_package_bill(bill: Any, prices: dict[str, Decimal]) -> tuple[Any, list[str]]:
    """Put the agreed unit prices on a package bill; returns it and the ordinals left unpriced."""
    unpriced: list[str] = []

    def _apply(lines: list[Any]) -> list[Any]:
        out = []
        for position in lines:
            rate = prices.get(str(position.id))
            if rate is None:
                unpriced.append(str(getattr(position, "ordinal", "") or position.id))
                out.append(position)
            else:
                out.append(_priced_copy(position, rate))
        return out

    direct = Decimal("0")
    for section in bill.sections:
        section.positions = _apply(section.positions)
        section.subtotal = sum((_dec(p.total) or Decimal("0") for p in section.positions), Decimal("0"))
        direct += section.subtotal
    bill.positions = _apply(bill.positions)
    direct += sum((_dec(p.total) or Decimal("0") for p in bill.positions), Decimal("0"))
    bill.direct_cost = direct
    bill.net_total = direct
    return bill, unpriced


class AwardExchangeService:
    """Bill source, award export, request documents and offer files of a package."""

    def __init__(self, session: AsyncSession) -> None:
        from app.modules.tendering.service import TenderingService

        self.session = session
        self.tendering = TenderingService(session)

    # Bill unchanged ───────────────────────────────────────────────────────

    async def _positions(self, package: TenderPackage) -> list[Any]:
        if package.boq_id is None:
            return []
        from app.modules.boq.repository import PositionRepository

        return await PositionRepository(self.session).list_all_for_boq(package.boq_id)

    async def raw_bill_state(self, package: TenderPackage) -> dict[str, Any]:
        """``{"source", "changed", "differences"}`` narrowed to the package's lines."""
        if package.boq_id is None:
            return {"source": None, "changed": False, "differences": []}
        from app.modules.boq.exchange_source import bill_state
        from app.modules.tendering.service import _scope_position_ids

        positions = await self._positions(package)
        declared = _scope_position_ids(package.metadata_)
        current = {str(p.id) for p in positions}
        # A declared scope that still matches the bill narrows the check; one
        # that matches nothing is stale and the package covers the whole bill.
        scope = declared if declared & current else None
        return await bill_state(self.session, package.boq_id, positions, scope)

    async def _awarded_bid(self, package_id: uuid.UUID) -> Any:
        bids = await self.tendering.list_bids(package_id)
        return next((b for b in bids if b.status == "accepted"), None)

    async def validation_payload(self, package: TenderPackage) -> dict[str, Any]:
        """The payload the ``tendering_exchange`` rule set reads."""
        from app.modules.tendering.bid_portal import BidPortalService

        state = await self.raw_bill_state(package)
        invitations = await BidPortalService(self.session).list_invitations(package.id)
        state["invitations"] = [
            {"id": str(i.id), "company_name": i.company_name, "status": i.status, "decline_reason": i.decline_reason}
            for i in invitations
        ]
        return state

    async def bill_source_state(self, package: TenderPackage, locale: str | None = None) -> BillSourceState:
        """The imported file, whether the bill still matches it, and the exchange rule results."""
        from app.core.validation.engine import ValidationContext, rule_registry
        from app.modules.tendering.validators import EXCHANGE_RULE_SET

        payload = await self.validation_payload(package)
        context = ValidationContext(data=payload, project_id=str(package.project_id))
        results: list[dict[str, Any]] = []
        for rule in rule_registry.get_rules_for_sets([EXCHANGE_RULE_SET]):
            for result in await rule.validate(context):
                results.append(
                    {
                        "rule_id": result.rule_id,
                        "severity": str(getattr(result.severity, "value", result.severity)),
                        "passed": result.passed,
                        "message": result.message,
                        "element_ref": result.element_ref,
                        "suggestion": result.suggestion,
                    }
                )
        awarded = await self._awarded_bid(package.id)
        return BillSourceState(
            source=payload["source"],
            changed=payload["changed"],
            differences=[BillDifference(**d) for d in payload["differences"]],
            awarded_bid_id=awarded.id if awarded is not None else None,
            rule_results=results,
        )

    # Award file (GAEB X86) ────────────────────────────────────────────────

    async def build_x86(
        self, package: TenderPackage, bid_id: uuid.UUID | None, *, actor_id: str | None = None
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Write the award file of a package: the bill as imported with the awarded prices.

        Args:
            package: The package, access already checked.
            bid_id: The bid to award with; default the accepted bid.
            actor_id: Who asked, recorded on the filed document.

        Returns:
            ``(xml, filename, rule_results)``.

        Raises:
            HTTPException 400: the package has no bill or no lines.
            HTTPException 409: ``bill_changed_since_import`` (with the differences),
                ``no_awarded_bid``, or the bid is rejected or withdrawn.
            HTTPException 422: ``x86_unpriced_lines``, the bid leaves package lines unpriced.
        """
        from app.core.validation.rules.gaeb_phases import run_gaeb_exchange_rules
        from app.modules.boq.exchange_source import BILL_CHANGED
        from app.modules.boq.router import build_gaeb_xml
        from app.modules.boq.service import BOQService, exportable_positions
        from app.modules.tendering.gaeb_package import package_bill, package_line_ids

        if package.boq_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package has no linked BOQ")
        state = await self.raw_bill_state(package)
        if state["changed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": BILL_CHANGED, "differences": state["differences"][:50]},
            )
        if bid_id is None:
            bid = await self._awarded_bid(package.id)
            if bid is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_awarded_bid")
        else:
            bid = await self.tendering.get_bid(bid_id)
            if bid.package_id != package.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
        if bid.status in _NOT_AWARDABLE:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bid_not_awardable")

        boq_service = BOQService(self.session)
        positions = exportable_positions((await boq_service.get_boq_with_positions(package.boq_id)).positions)
        line_ids = package_line_ids(positions, package.metadata_)
        structured = await boq_service.get_boq_structured_for_export(package.boq_id)
        bill = package_bill(structured, line_ids)
        if not bill.sections and not bill.positions:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package has no lines")
        # The issuer's project number and label travel back with the award.
        bill.metadata = getattr(structured, "metadata", None)
        bill, unpriced = price_package_bill(bill, bid_unit_prices(bid))
        if unpriced:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "x86_unpriced_lines", "ordinals": unpriced[:100]},
            )
        project_name, currency = await self.tendering._project_name_and_currency(package)
        xml = await asyncio.to_thread(
            build_gaeb_xml,
            bill,
            project_name=project_name,
            project_currency=(currency or bid.currency or "")[:3].upper(),
            gaeb_format="x86",
            contractor_name=bid.company_name or "",
        )
        results = await run_gaeb_exchange_rules({"gaeb_document": {"phase": "x86", "content": xml, "own": True}})
        filename = f"{package.name or 'award'}.X86"
        await store_and_file(
            self.session,
            project_id=package.project_id,
            subdir="award_files",
            file_name=filename,
            content=xml.encode("utf-8"),
            mime_type="application/xml",
            tags=["tendering", "gaeb_x86", "award"],
            metadata={"source": "tendering_award", "package_id": str(package.id), "bid_id": str(bid.id)},
            uploaded_by=actor_id or "",
            description=f"GAEB X86 award, {bid.company_name}",
        )
        return xml, filename, results

    # Request documents ────────────────────────────────────────────────────

    async def _documents_by_id(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
        if not ids:
            return {}
        try:
            from app.modules.documents.models import Document
        except Exception:  # noqa: BLE001 - Documents not installed
            return {}
        rows = (await self.session.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
        return {row.id: row for row in rows}

    async def package_documents(self, package: TenderPackage) -> list[tuple[TenderPackageDocument, Any]]:
        """(link, document) pairs of a package, documents of other projects or deleted ones left out."""
        links = list(
            (
                await self.session.execute(
                    select(TenderPackageDocument)
                    .where(TenderPackageDocument.package_id == package.id)
                    .order_by(TenderPackageDocument.created_at)
                )
            )
            .scalars()
            .all()
        )
        docs = await self._documents_by_id([link.document_id for link in links])
        out = []
        for link in links:
            doc = docs.get(link.document_id)
            if doc is not None and doc.project_id == package.project_id:
                out.append((link, doc))
        return out

    @staticmethod
    def document_response(link: TenderPackageDocument, doc: Any) -> PackageDocumentResponse:
        return PackageDocumentResponse(
            id=link.id,
            document_id=doc.id,
            name=doc.name,
            file_size=doc.file_size or 0,
            mime_type=doc.mime_type or "",
            category=doc.category or "",
            revision_code=getattr(doc, "revision_code", None),
            added_at=link.created_at,
        )

    async def list_package_documents(self, package: TenderPackage) -> list[PackageDocumentResponse]:
        return [self.document_response(link, doc) for link, doc in await self.package_documents(package)]

    async def attach_documents(
        self, package: TenderPackage, document_ids: list[uuid.UUID], actor_id: str | None
    ) -> list[PackageDocumentResponse]:
        """Attach project documents; a document of another project answers 404, a repeat is ignored.

        Raises:
            HTTPException 404: ``document_not_found`` for an id that is not a document of the package's project.
        """
        wanted = list(dict.fromkeys(document_ids))
        docs = await self._documents_by_id(wanted)
        for doc_id in wanted:
            doc = docs.get(doc_id)
            if doc is None or doc.project_id != package.project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
        have = {link.document_id for link, _ in await self.package_documents(package)}
        for doc_id in wanted:
            if doc_id not in have:
                self.session.add(TenderPackageDocument(package_id=package.id, document_id=doc_id, added_by=actor_id))
        await self.session.flush()
        return await self.list_package_documents(package)

    async def detach_document(self, package: TenderPackage, link_id: uuid.UUID) -> None:
        link = await self.session.get(TenderPackageDocument, link_id)
        if link is None or link.package_id != package.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package document not found")
        await self.session.delete(link)
        await self.session.flush()

    # Offer files ──────────────────────────────────────────────────────────

    @staticmethod
    def file_response(row: TenderBidFile) -> BidFileResponse:
        return BidFileResponse(
            id=row.id,
            kind=row.kind,
            file_name=row.file_name,
            file_size=row.file_size,
            sha256=row.sha256,
            uploaded_at=row.uploaded_at,
            invitation_id=row.invitation_id,
            recipient_id=row.recipient_id,
            company_name=row.company_name,
            bid_id=row.bid_id,
            mime_type=row.mime_type,
            document_id=row.document_id,
        )

    async def list_files(self, package_id: uuid.UUID) -> list[BidFileResponse]:
        rows = (
            (
                await self.session.execute(
                    select(TenderBidFile)
                    .where(TenderBidFile.package_id == package_id)
                    .order_by(TenderBidFile.uploaded_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [self.file_response(row) for row in rows]

    async def file_counts(self, package_id: uuid.UUID) -> dict[str, int]:
        """Uploaded files per recipient id of a package."""
        stmt = (
            select(TenderBidFile.recipient_id, func.count(TenderBidFile.id))
            .where(TenderBidFile.package_id == package_id)
            .group_by(TenderBidFile.recipient_id)
        )
        return {str(rid): int(n) for rid, n in (await self.session.execute(stmt)).all()}

    async def bid_file(self, package_id: uuid.UUID, file_id: uuid.UUID) -> TenderBidFile:
        row = await self.session.get(TenderBidFile, file_id)
        if row is None or row.package_id != package_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid file not found")
        return row

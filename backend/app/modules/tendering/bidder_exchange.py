# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a bidder does through its link besides typing prices.

* **Upload a priced GAEB X84.** The file is checked by the same strict rules
  the buyer's X84 import applies (``x84_import.check_lines``: the item must be
  on the bill, keep its unit and keep its quantity). The bidder sees every
  mismatch per line before anything is stored; a clean file is submitted
  through the link's regular submit path, so sealed mode, deadlines, revisions
  and the receipt behave exactly as for typed prices.
* **Upload an offer PDF, an insurance certificate or attachments.** Kept per
  firm, filed with the project's documents. An insurance certificate of a firm
  the buyer picked from the subcontractor directory also lands in that firm's
  certificate register, awaiting review.
* **Decline to bid,** with a reason the buyer reads per firm.
* **Download request documents** the buyer attached to the package.

Every route resolves the token to exactly one invitation of one package; a
file or document id is only answered when it belongs to that package.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tendering.award_exchange import AwardExchangeService, safe_file_name, store_and_file
from app.modules.tendering.bid_portal import (
    _CLOSED_PACKAGE_STATES,
    BidPortalService,
    _aware,
    deadline_instant,
)
from app.modules.tendering.models import TenderBidFile, TenderBidInvitation, TenderPackage
from app.modules.tendering.schemas import BidPortalPricesRequest, BidPortalView, X84ImportPreview

logger = logging.getLogger(__name__)

#: Upper bound for one offer file or attachment.
MAX_BIDDER_FILE_BYTES = 25 * 1024 * 1024
#: Files one firm may upload to one package.
MAX_FILES_PER_BIDDER = 30
#: Insurance certificates are a scan or a PDF, never an office file.
INSURANCE_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png"})
#: Years a stated insurance expiry may fall in; anything else is a typo.
MIN_VALID_UNTIL_YEAR = 2000
MAX_VALID_UNTIL_YEAR = 2100
#: Kinds a bidder may upload by hand (``x84`` comes only through the X84 route).
UPLOAD_KINDS = frozenset({"offer_pdf", "attachment", "insurance"})
_ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".zip", ".jpg", ".jpeg", ".png", ".x84", ".xml"}
)
_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".zip": "application/zip",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".x84": "application/xml",
    ".xml": "application/xml",
}

#: What the first bytes must read as per extension; plain text has no signature.
_SIGNATURE_BY_EXTENSION = {
    ".pdf": "pdf",
    ".doc": "ole",
    ".xls": "ole",
    ".docx": "zip",
    ".xlsx": "zip",
    ".zip": "zip",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".x84": "xml",
    ".xml": "xml",
}
#: Windows PE, ELF, Mach-O and script openers, refused whatever the name.
_EXECUTABLE_PREFIXES = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"#!")


def _extension(name: str) -> str:
    return Path(name or "").suffix.lower()


def check_upload(kind: str, file_name: str, content: bytes) -> str:
    """The MIME type a bidder file is stored with; 4xx with a bare code when it is refused."""
    from app.core.file_signature import SIGNATURE_BYTES_REQUIRED, detect

    if kind not in UPLOAD_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_file_kind")
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty_file")
    if len(content) > MAX_BIDDER_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="file_too_large")
    ext = _extension(file_name)
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file_type_not_allowed")
    head = content[:SIGNATURE_BYTES_REQUIRED]
    if head.startswith(_EXECUTABLE_PREFIXES):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file_type_not_allowed")
    if kind == "offer_pdf" and ext != ".pdf":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="not_a_pdf")
    if kind == "insurance" and ext not in INSURANCE_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file_type_not_allowed")
    # The bytes must be what the name says, so a renamed program never lands in Documents.
    expected = _SIGNATURE_BY_EXTENSION.get(ext)
    if expected is not None and detect(head) != expected:
        code = "not_a_pdf" if ext == ".pdf" else "file_type_not_allowed"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)
    return _MIME_BY_EXTENSION[ext]


def parse_valid_until(raw: date | str | None) -> date | None:
    """The expiry a bidder states for its insurance; 422 ``invalid_valid_until`` when unreadable."""
    if raw is None or isinstance(raw, date):
        return raw
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_valid_until") from None
    if not MIN_VALID_UNTIL_YEAR <= parsed.year <= MAX_VALID_UNTIL_YEAR:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_valid_until")
    return parsed


class BidderExchangeService:
    """Uploads, decline and request documents behind one bidder link."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.portal = BidPortalService(session)
        self.exchange = AwardExchangeService(session)

    async def _package(self, invitation: TenderBidInvitation) -> TenderPackage:
        return await self.portal.tendering.get_package(invitation.package_id)

    async def _check_upload_window(self, invitation: TenderBidInvitation, package: TenderPackage) -> None:
        """Files come in while the tender runs; a sealed package takes none after submitting."""
        from app.modules.tendering.sealed import SealedTenderService

        if package.status in _CLOSED_PACKAGE_STATES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tender_closed")
        if invitation.declined_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bid_declined")
        sealed = SealedTenderService(self.session)
        sealing = await sealed.get(package.id)
        if sealing is not None:
            if invitation.submitted_at is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bid_already_submitted")
            sealed.check_submission_window(package, sealing)
        due = deadline_instant(package.deadline)
        created = _aware(invitation.created_at)
        if due is not None and created is not None and created < due < datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="bid_link_expired")

    async def _record(
        self,
        invitation: TenderBidInvitation,
        package: TenderPackage,
        *,
        kind: str,
        file_name: str,
        content: bytes,
        mime_type: str,
        bid_id: uuid.UUID | None = None,
    ) -> TenderBidFile:
        count = (
            await self.session.execute(
                select(func.count(TenderBidFile.id)).where(
                    TenderBidFile.package_id == package.id, TenderBidFile.recipient_id == invitation.recipient_id
                )
            )
        ).scalar_one()
        if int(count) >= MAX_FILES_PER_BIDDER:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="too_many_files")
        name = safe_file_name(file_name, "offer")
        path, document_id = await store_and_file(
            self.session,
            project_id=package.project_id,
            subdir="bid_files",
            file_name=name,
            content=content,
            mime_type=mime_type,
            tags=["tendering", "bid_file", kind],
            metadata={
                "source": "bid_portal",
                "package_id": str(package.id),
                "recipient_id": invitation.recipient_id,
                "company_name": invitation.company_name,
                "kind": kind,
            },
            description=f"{invitation.company_name}: {package.name}",
        )
        row = TenderBidFile(
            package_id=package.id,
            invitation_id=invitation.id,
            recipient_id=invitation.recipient_id,
            company_name=invitation.company_name,
            bid_id=bid_id or invitation.bid_id,
            kind=kind,
            file_name=name,
            mime_type=mime_type,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            file_path=path,
            document_id=document_id,
            uploaded_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        logger.info("Bidder file received: package=%s recipient=%s kind=%s", package.id, invitation.recipient_id, kind)
        return row

    async def view(self, token: str) -> BidPortalView:
        return await self.portal.public_view(token)

    async def upload(
        self, token: str, kind: str, file_name: str, content: bytes, valid_until: date | str | None = None
    ) -> BidPortalView:
        """Keep an offer PDF, an insurance certificate or an attachment of the firm and file it in Documents.

        An insurance certificate from a firm that is a directory subcontractor also lands in
        that subcontractor's certificate register, awaiting review.
        """
        invitation = await self.portal._resolve(token, for_update=True)
        package = await self._package(invitation)
        await self._check_upload_window(invitation, package)
        mime = check_upload(kind, file_name, content)
        until = parse_valid_until(valid_until) if kind == "insurance" else None
        row = await self._record(invitation, package, kind=kind, file_name=file_name, content=content, mime_type=mime)
        if kind == "insurance":
            await self._register_certificate(invitation, package, row, until)
        return await self.portal.public_view(token)

    async def _register_certificate(
        self, invitation: TenderBidInvitation, package: TenderPackage, row: TenderBidFile, valid_until: date | None
    ) -> None:
        """File the certificate on the directory firm the buyer invited under this link, if any.

        The subcontractor is read from the buyer's own recipient entry of this invitation,
        never from anything the bidder sends.
        """
        from app.modules.subcontractors.service import SubcontractorService

        if not invitation.recipient_id:
            return
        recipients = (package.metadata_ or {}).get("recipients")
        entry = next(
            (r for r in recipients or [] if isinstance(r, dict) and str(r.get("id")) == invitation.recipient_id), {}
        )
        try:
            subcontractor_id = uuid.UUID(str(entry.get("subcontractor_id")))
        except ValueError:
            return  # not a directory subcontractor: the file stays with the bid files
        svc = SubcontractorService(self.session)
        if await svc.subs.get_by_id(subcontractor_id) is None:
            return
        await svc.record_certificate_from_bid_file(subcontractor_id, package, row, valid_until)
        logger.info("Bidder insurance filed: package=%s subcontractor=%s", package.id, subcontractor_id)

    async def check_x84(self, token: str, file_name: str, content: bytes) -> X84ImportPreview:
        """Match an X84 against the bill this link prices; nothing is stored."""
        from app.modules.tendering.x84_import import X84BidImportService

        invitation = await self.portal._resolve(token)
        preview, _, _ = await X84BidImportService(self.session).check(invitation.package_id, file_name, content)
        return preview

    async def submit_x84(self, token: str, file_name: str, content: bytes, notes: str = "") -> BidPortalView:
        """Submit the bid from an X84: refused while the check reports a blocking issue.

        Raises:
            HTTPException 422: ``{"code": "x84_has_blocking_issues", "preview": ...}`` so the
                bidder sees each mismatch.
        """
        from app.modules.tendering.x84_import import X84BidImportService

        invitation = await self.portal._resolve(token)
        package = await self._package(invitation)
        preview, _, ctx = await X84BidImportService(self.session).check(package.id, file_name, content)
        if preview.blocking:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "x84_has_blocking_issues", "preview": preview.model_dump(mode="json")},
            )
        prices: dict[str, Any] = ctx["prices"]
        body = BidPortalPricesRequest(
            unit_prices={pid: format(rate, "f") for pid, rate in prices.items()},
            notes=notes[:2000],
            currency=ctx["currency"] or None,
        )
        view = await self.portal.submit(token, body)
        invitation = await self.portal._resolve(token)
        bid = await self.portal.tendering.repo.get_bid_by_id(invitation.bid_id) if invitation.bid_id else None
        if bid is not None:
            meta = dict(bid.metadata_) if isinstance(bid.metadata_, dict) else {}
            meta.update({"source": "bid_portal_x84", "file_name": file_name[:255], "file_sha256": preview.sha256})
            bid.metadata_ = meta
        await self._record(
            invitation,
            package,
            kind="x84",
            file_name=file_name or "offer.x84",
            content=content,
            mime_type="application/xml",
            bid_id=invitation.bid_id,
        )
        return await self.portal.enrich(view, invitation, package)

    async def decline(self, token: str, reason: str) -> BidPortalView:
        """Record that the firm will not bid. A submitted bid cannot be declined afterwards."""
        invitation = await self.portal._resolve(token, for_update=True)
        package = await self._package(invitation)
        if invitation.submitted_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bid_already_submitted")
        if package.status in _CLOSED_PACKAGE_STATES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tender_closed")
        if invitation.declined_at is None:
            now = datetime.now(UTC)
            invitation.declined_at = now
            invitation.decline_reason = reason.strip()[:2000]
            if invitation.opened_at is None:
                invitation.opened_at = now
            await self.session.flush()
            logger.info("Bidder declined: package=%s recipient=%s", package.id, invitation.recipient_id)
        return await self.portal.public_view(token)

    async def document_file(self, token: str, link_id: uuid.UUID) -> tuple[Path, str, str]:
        """(path, name, media type) of a request document of this link's package; 404 otherwise."""
        from app.core.storage import is_within_safe_root
        from app.modules.documents.service import UPLOAD_BASE

        invitation = await self.portal._resolve(token)
        package = await self._package(invitation)
        for link, doc in await self.exchange.package_documents(package):
            if link.id != link_id:
                continue
            upload_base = Path(UPLOAD_BASE).resolve()
            raw = Path(doc.file_path) if doc.file_path else None
            if raw is None:
                break
            path = (raw if raw.is_absolute() else upload_base / raw).resolve()
            if not is_within_safe_root(path, extra_roots=[upload_base]) or path.is_symlink() or not path.is_file():
                break
            return path, doc.name, doc.mime_type or "application/octet-stream"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pin a transmittal item to the exact revision it sends.

The client names a file; the server decides which revision that is. A document
or sheet item is resolved against the project (a foreign or unknown id is
refused), its revision is read from the register and written to the snapshot,
and a superseded revision cannot be issued for review, approval, information or
construction. Only a ``for_record`` transmittal may carry an earlier revision,
because filing what was issued then is exactly its purpose.

Other file kinds (photos, models, takeoffs, generated reports) carry no revision
chain and pass through unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_transmittals.models import FileTransmittalItem

RECORD_REASON = "for_record"
# A drawing issued "for construction" must be published in the CDE.
CONSTRUCTION_REASON = "for_construction"


@dataclass(frozen=True)
class ResolvedItem:
    """What the register says about one item: its snapshot and issue state."""

    snapshot: str | None
    superseded: bool
    cde_state: str | None
    label: str


def _fail(detail: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _snapshot(version_number: int | None, revision: str | None) -> str | None:
    parts = [p for p in (str(version_number) if version_number else None, (revision or "").strip() or None) if p]
    return " · ".join(parts)[:32] or None


async def resolve_item(
    session: AsyncSession, project_id: uuid.UUID, file_kind: str, file_id: str
) -> ResolvedItem | None:
    """Look an item up in the register; ``None`` for kinds with no revision chain."""
    if file_kind not in ("document", "sheet"):
        return None
    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, TypeError):
        raise _fail(f"'{file_id}' is not a {file_kind} id") from None

    if file_kind == "document":
        from app.modules.documents.models import Document
        from app.modules.documents.revisions import is_superseded

        doc = (await session.execute(select(Document).where(Document.id == key))).scalar_one_or_none()
        if doc is None or doc.project_id != project_id:
            raise _fail(f"Document {file_id} is not in this project")
        number: int | None = None
        try:
            from app.modules.file_versions.models import FileVersion

            number = (
                await session.execute(
                    select(FileVersion.version_number).where(
                        FileVersion.file_kind == "document",
                        FileVersion.file_id == str(doc.id),
                        FileVersion.is_current.is_(True),
                    )
                )
            ).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - version chain is optional
            number = None
        return ResolvedItem(_snapshot(number, doc.revision_code), is_superseded(doc), doc.cde_state, doc.name)

    from app.modules.documents.models import Sheet

    sheet = (await session.execute(select(Sheet).where(Sheet.id == key))).scalar_one_or_none()
    if sheet is None or sheet.project_id != project_id:
        raise _fail(f"Sheet {file_id} is not in this project")
    label = sheet.sheet_number or sheet.sheet_title or str(sheet.id)
    return ResolvedItem(_snapshot(None, sheet.revision), not sheet.is_current, None, label)


def assert_issuable(resolved: ResolvedItem, reason_code: str) -> None:
    """Refuse a superseded or unpublished revision for a reason that issues it for use."""
    if reason_code == RECORD_REASON:
        return
    if resolved.superseded:
        raise _fail(
            f"'{resolved.label}' is a superseded revision; transmit the current revision "
            f"(only a for_record transmittal may carry an earlier one)",
            status.HTTP_409_CONFLICT,
        )
    if resolved.cde_state == "archived":
        raise _fail(f"'{resolved.label}' is archived and cannot be issued", status.HTTP_409_CONFLICT)
    if reason_code == CONSTRUCTION_REASON and resolved.cde_state not in (None, "published"):
        raise _fail(
            f"'{resolved.label}' is {resolved.cde_state}; only a published document is issued for construction",
            status.HTTP_409_CONFLICT,
        )


async def pin_item(
    session: AsyncSession, project_id: uuid.UUID, reason_code: str, file_kind: str, file_id: str
) -> str | None | bool:
    """Validate one incoming item and return its server-resolved snapshot.

    Returns ``False`` when the kind has no revision chain (keep the client's value).
    """
    resolved = await resolve_item(session, project_id, file_kind, file_id)
    if resolved is None:
        return False
    assert_issuable(resolved, reason_code)
    return resolved.snapshot


async def recheck_items(
    session: AsyncSession, project_id: uuid.UUID, reason_code: str, items: list[FileTransmittalItem]
) -> None:
    """At send time: a revision superseded since the draft was made must not go out."""
    for it in items:
        resolved = await resolve_item(session, project_id, it.file_kind, it.file_id)
        if resolved is not None:
            assert_issuable(resolved, reason_code)

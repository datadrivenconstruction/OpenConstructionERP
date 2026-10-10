# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What every register export has to look up before it can print.

The renderers in :mod:`app.core.register_export` are pure: they take names and
never touch the database. Something has to turn a project id into the name,
number, currency and country the sheet is headed with, and turn the finished
bytes into a download that says which language it is written in. Six modules
need exactly that, so it is written once here and each module's export routes
stay a list of columns.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_disposition import attachment_disposition
from app.core.register_export import (
    ProjectHeader,
    RecordDocument,
    RegisterDocument,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
)

__all__ = [
    "PDF_MEDIA_TYPE",
    "XLSX_MEDIA_TYPE",
    "AcceptLanguageHeader",
    "FormatQuery",
    "LocaleQuery",
    "ProjectHeader",
    "document_download",
    "record_download",
    "register_download",
    "generated_now",
    "load_project_header",
]

#: ``?locale=`` on an export route: forces the document language.
LocaleQuery = Annotated[
    str | None,
    Query(max_length=10, description="Force the document language (e.g. 'tr'). Overrides Accept-Language."),
]
#: The raw ``Accept-Language`` header, read when ``?locale=`` is absent.
AcceptLanguageHeader = Annotated[str | None, Header(alias="accept-language")]
#: ``?format=`` on a register route: a workbook by default, as the RFI log is.
FormatQuery = Annotated[
    str,
    Query(alias="format", pattern="^(xlsx|pdf)$", description="'xlsx' for a workbook, 'pdf' for a printable register."),
]

PDF_MEDIA_TYPE = "application/pdf"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def load_project_header(session: AsyncSession, project_id: uuid.UUID) -> ProjectHeader:
    """Read the header facts of one project.

    Args:
        session: The request's database session.
        project_id: The project a register or record belongs to.

    Returns:
        The header, empty when the project no longer exists.
    """
    from app.modules.projects.models import Project

    row = (
        await session.execute(
            select(Project.name, Project.project_code, Project.currency, Project.country_code).where(
                Project.id == project_id
            )
        )
    ).first()
    if row is None:
        return ProjectHeader()
    return ProjectHeader(
        name=row.name or "",
        code=row.project_code or None,
        currency=(row.currency or "").strip().upper(),
        country=(row.country_code or "").strip().upper() or None,
    )


def generated_now(datetime_format: str) -> str:
    """The current UTC time in a catalogue's ``datetime_format``."""
    return datetime.now(tz=UTC).strftime(datetime_format)


def document_download(content: bytes | io.BytesIO, filename: str, locale: str, media_type: str) -> StreamingResponse:
    """A file download that declares the language it was written in.

    A document catalogue is narrower than the interface's locale list, so the
    language of the body can differ from the one the reader asked for.
    ``Content-Language`` says which it is and overrides the request-derived
    header the Accept-Language middleware would otherwise set.

    Args:
        content: The document, as bytes or a buffer positioned at its start.
        filename: The download name.
        locale: The language the document was rendered in.
        media_type: :data:`PDF_MEDIA_TYPE` or :data:`XLSX_MEDIA_TYPE`.
    """
    body = iter([content]) if isinstance(content, bytes) else content
    return StreamingResponse(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": attachment_disposition(filename),
            "Content-Language": locale,
        },
    )


async def register_download(
    document: RegisterDocument,
    export_format: str,
    filename_for: Callable[[str], str],
) -> StreamingResponse:
    """Render a register in the asked format and return it as a download.

    Rendering is seconds of CPU with no await in it, so it runs in a worker
    thread instead of holding up every other request on the event loop.

    Args:
        document: The translated register.
        export_format: ``"pdf"`` or ``"xlsx"``.
        filename_for: Called with the file extension, returns the download name.
    """
    if export_format == "pdf":
        pdf_bytes = await asyncio.to_thread(build_register_pdf, document)
        return document_download(pdf_bytes, filename_for("pdf"), document.locale, PDF_MEDIA_TYPE)
    workbook = await asyncio.to_thread(build_register_xlsx, document)
    return document_download(workbook, filename_for("xlsx"), document.locale, XLSX_MEDIA_TYPE)


async def record_download(document: RecordDocument, filename: str, locale: str) -> StreamingResponse:
    """Render a single-record form off the event loop and return it as a PDF download."""
    pdf_bytes = await asyncio.to_thread(build_record_pdf, document)
    return document_download(pdf_bytes, filename, locale, PDF_MEDIA_TYPE)

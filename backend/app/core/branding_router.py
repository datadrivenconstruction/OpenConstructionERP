# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Workspace white-label branding API (issue #272).

Branding used to live only in the browser's localStorage, so it never followed
the workspace to another browser or to an invited user's first (pre-auth) view
of the login page. These endpoints persist it once on the server:

    GET    /api/v1/branding/   - PUBLIC. The login page reads it before anyone
                                 signs in, so an invited user sees the workspace
                                 brand on the very first screen.
    PUT    /api/v1/branding/   - admin only. Set the workspace brand.
    DELETE /api/v1/branding/   - admin only. Clear it and revert to default.

    GET    /api/v1/document-appearance/ - any signed-in user. The settings
                                 page reads it; unlike the brand it is never
                                 needed before sign-in, so it is not public.
    PUT    /api/v1/document-appearance/ - admin only. Set how exports look.
    DELETE /api/v1/document-appearance/ - admin only. Back to the platform look.
    GET    /api/v1/document-appearance/sample.pdf - any signed-in user. A
                                 one-page document drawn with the saved look
                                 and letterhead, so the settings page previews
                                 what the server prints rather than an HTML
                                 imitation of it.

    GET    /api/v1/document-appearance/types/ - any signed-in user. Every
                                 document type that can carry its own look:
                                 the fields it honours, its override and the
                                 look it is drawn with.
    PUT    /api/v1/document-appearance/types/{doc_type}/ - admin only. Replace
                                 that type's override.
    DELETE /api/v1/document-appearance/types/{doc_type}/ - admin only. Drop it;
                                 the type follows the workspace look again.
    GET    /api/v1/document-appearance/types/{doc_type}/sample.pdf - any
                                 signed-in user. The sample page with that
                                 type's look.

Persistence is a small JSON file in the data dir (see
:mod:`app.core.app_branding` and :mod:`app.core.pdf_appearance`) - no database
table, so this needs no migration.

The appearance endpoints live here rather than in a router of their own because
they are the same concern seen from two sides: the brand says whose document it
is, the appearance says what it looks like, and both are read by the same PDF
layer. One mount, one place to look.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.app_branding import (
    MAX_COMPANY_NAME,
    read_branding,
    reset_branding,
    write_branding,
)
from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    DOCUMENT_TYPES,
    LOGO_ALIGNMENTS,
    MAX_FONT_SIZE,
    MAX_FOOTER_TEXT,
    MAX_MARGIN_MM,
    MIN_FONT_SIZE,
    MIN_MARGIN_MM,
    PAGE_SIZES,
    USER_PAPER,
    DocumentType,
    read_appearance,
    read_overrides,
    reset_appearance,
    reset_override,
    resolve_appearance,
    sanitise_override,
    write_appearance,
    write_override,
)
from app.dependencies import RequireRole, get_current_user_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["branding"])


class BrandingResponse(BaseModel):
    """The workspace brand. ``mode`` is one of default / logo / text."""

    mode: str = "default"
    logo_data_url: str | None = None
    company_name: str = ""


class BrandingUpdate(BaseModel):
    """Admin payload to set the workspace brand.

    All fields optional so the client can send just what changed; the server
    sanitises and reconciles them (a logo wins; ``text`` needs a name) before
    persisting, so the stored trio is always consistent.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    mode: str | None = None
    logo_data_url: str | None = None
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)


@router.get("/branding/", response_model=BrandingResponse)
@router.get("/branding", response_model=BrandingResponse, include_in_schema=False)
async def get_branding() -> BrandingResponse:
    """Public: the workspace brand for the login page and the app shell.

    Deliberately answered without a token. The login page and the app's first
    render ask for it before anyone has signed in, so that the sign-in screen
    already carries the workspace's logo and name. It answers nothing but the
    logo, the name and which of the two to show.
    """
    return BrandingResponse(**read_branding())


@router.put(
    "/branding/",
    response_model=BrandingResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/branding",
    response_model=BrandingResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_branding(body: BrandingUpdate) -> BrandingResponse:
    """Admin: set the workspace brand so it persists for every browser and user."""
    return BrandingResponse(**write_branding(body.model_dump()))


@router.delete(
    "/branding/",
    response_model=BrandingResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.delete(
    "/branding",
    response_model=BrandingResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def delete_branding() -> BrandingResponse:
    """Admin: clear the custom brand and revert to the default."""
    return BrandingResponse(**reset_branding())


# -- Document appearance ------------------------------------------------------


class DocumentAppearanceResponse(BaseModel):
    """How generated PDFs look. Always a complete, already-sanitised set.

    Never partial: a client that has just saved one field still receives every
    value, so the settings form and the preview cannot drift apart from what the
    server will actually draw with.
    """

    accent_color: str = DEFAULT_APPEARANCE["accent_color"]
    footer_color: str = DEFAULT_APPEARANCE["footer_color"]
    base_font_size: int = DEFAULT_APPEARANCE["base_font_size"]
    page_size: str = DEFAULT_APPEARANCE["page_size"]
    margin_mm: int = DEFAULT_APPEARANCE["margin_mm"]
    logo_align: str = DEFAULT_APPEARANCE["logo_align"]
    footer_text: str = DEFAULT_APPEARANCE["footer_text"]
    show_page_numbers: bool = DEFAULT_APPEARANCE["show_page_numbers"]
    show_letterhead: bool = DEFAULT_APPEARANCE["show_letterhead"]


class DocumentAppearanceOptions(BaseModel):
    """The choices and bounds the UI should offer.

    Served from the same constants the sanitiser enforces, so a form built from
    this response can never offer a value the server would silently discard -
    which is how a settings screen ends up with a control that appears to do
    nothing.
    """

    page_sizes: list[str]
    logo_alignments: list[str]
    min_font_size: int
    max_font_size: int
    min_margin_mm: int
    max_margin_mm: int
    max_footer_text: int
    defaults: DocumentAppearanceResponse


class DocumentAppearanceUpdate(BaseModel):
    """Admin payload. All fields optional so a client can send just what changed.

    Deliberately untyped beyond the basics: bounds and enums are enforced by
    :func:`app.core.pdf_appearance.sanitise`, which also guards the read path,
    so there is exactly one definition of what a legal appearance is. A value
    rejected here would otherwise still have to be rejected there.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    accent_color: str | None = None
    footer_color: str | None = None
    base_font_size: int | None = None
    page_size: str | None = None
    margin_mm: int | None = None
    logo_align: str | None = None
    footer_text: str | None = Field(default=None, max_length=MAX_FOOTER_TEXT)
    show_page_numbers: bool | None = None
    show_letterhead: bool | None = None


@router.get(
    "/document-appearance/",
    response_model=DocumentAppearanceResponse,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/document-appearance",
    response_model=DocumentAppearanceResponse,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_document_appearance() -> DocumentAppearanceResponse:
    """The look every generated PDF is drawn with."""
    return DocumentAppearanceResponse(**read_appearance())


@router.get(
    "/document-appearance/options/",
    response_model=DocumentAppearanceOptions,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/document-appearance/options",
    response_model=DocumentAppearanceOptions,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_document_appearance_options() -> DocumentAppearanceOptions:
    """The legal choices and bounds, so the UI never offers a rejected value."""
    return DocumentAppearanceOptions(
        page_sizes=list(PAGE_SIZES),
        logo_alignments=list(LOGO_ALIGNMENTS),
        min_font_size=MIN_FONT_SIZE,
        max_font_size=MAX_FONT_SIZE,
        min_margin_mm=MIN_MARGIN_MM,
        max_margin_mm=MAX_MARGIN_MM,
        max_footer_text=MAX_FOOTER_TEXT,
        defaults=DocumentAppearanceResponse(**DEFAULT_APPEARANCE),
    )


@router.get(
    "/document-appearance/sample.pdf",
    response_class=Response,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/document-appearance/sample.pdf/",
    response_class=Response,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_document_appearance_sample() -> Response:
    """A one-page sample drawn with the saved look and the company letterhead.

    ``inline`` so the settings page can show it in a frame, and ``no-store``
    because the page fetches it again after every save and a cached copy would
    preview the look from before the save. Rendered on demand from what is
    stored, never from unsaved form values: the preview answers "what will the
    server print", which only the stored settings decide.

    ``Content-Language`` is declared ``en`` because the placeholder text and
    the shared footer are English whatever the reader asked for; left unset,
    the Accept-Language middleware would label the bytes with the reader's
    language instead.
    """
    from app.core.pdf_branding import render_sample_pdf

    # Off the event loop: drawing the sample is CPU with no await in it, and
    # any signed-in reader can ask for it as fast as the settings page will
    # send. On the loop, one slow logo stalls every other request this worker
    # is serving.
    return Response(
        content=await asyncio.to_thread(render_sample_pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="sample.pdf"',
            "Content-Language": "en",
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "/document-appearance/",
    response_model=DocumentAppearanceResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/document-appearance",
    response_model=DocumentAppearanceResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_document_appearance(body: DocumentAppearanceUpdate) -> DocumentAppearanceResponse:
    """Admin: set how exports look. Merged over what is stored, then sanitised.

    Merging rather than replacing is what lets the form save one field at a
    time; sending ``None`` for a field leaves the stored value alone rather than
    resetting it, which is what DELETE is for.
    """
    current = read_appearance()
    patch = {key: value for key, value in body.model_dump().items() if value is not None}
    current.update(patch)
    return DocumentAppearanceResponse(**write_appearance(current))


@router.delete(
    "/document-appearance/",
    response_model=DocumentAppearanceResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.delete(
    "/document-appearance",
    response_model=DocumentAppearanceResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def delete_document_appearance() -> DocumentAppearanceResponse:
    """Admin: clear the custom look and go back to the platform default.

    Per-type overrides are kept; each is cleared on its own endpoint below.
    """
    return DocumentAppearanceResponse(**reset_appearance())


# -- Per-document-type overrides ------------------------------------------------


class DocumentTypeResponse(BaseModel):
    """One document type: what an override may set, what it sets, how it looks.

    ``override`` holds only the fields the type pins; every other field follows
    the workspace look. ``effective`` is the complete look the type's documents
    are drawn with, the workspace look with ``override`` laid over it, so the
    settings page can show an inherited value without computing it.
    """

    key: str
    label: str
    label_key: str
    fields: list[str]
    override: dict[str, Any]
    effective: DocumentAppearanceResponse


class DocumentTypeOverrideUpdate(DocumentAppearanceUpdate):
    """Admin payload for one type's override. Replaces what is stored.

    A field sent is pinned for the type; a field left out or sent as ``null``
    follows the workspace look. That is the difference from the workspace PUT,
    which merges: an override has to be able to stop pinning a field, and
    "leave it alone" cannot say that.

    An unknown field name is refused by the model. A known field the type's
    generator does not honour, or a value the sanitiser would not keep, is
    refused by :func:`_refuse_an_unusable_override`.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


#: What a usable value looks like, for the fields whose values are refused in
#: practice. The others are typed by the model or trimmed rather than refused.
_VALUE_HINTS = {
    "accent_color": "a hex colour such as #1a1a2e",
    "footer_color": "a hex colour such as #999999",
    "logo_align": "one of: " + ", ".join(LOGO_ALIGNMENTS),
}


def _configurable_type(doc_type: str) -> DocumentType:
    """The registered type for ``doc_type``, or a structured 404 / 422."""
    kind = DOCUMENT_TYPES.get(doc_type)
    if kind is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_document_type",
                "document_type": doc_type,
                "message": f"There is no document type {doc_type!r}.",
                "known_types": [key for key, known in DOCUMENT_TYPES.items() if known.configurable],
            },
        )
    if not kind.configurable:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "document_type_not_configurable",
                "document_type": doc_type,
                "reason": "reserved",
                "message": f"{kind.label} documents do not read the document appearance yet, "
                "so there is nothing to set for them.",
            },
        )
    return kind


def _refuse_an_unusable_override(kind: DocumentType, submitted: dict[str, Any]) -> None:
    """Answer 422 when a submitted field would not change this type's documents.

    The storage sanitiser drops such a field without a word, which is right for
    a hand-edited file and wrong behind a 200: an admin who pinned a page size
    for the RFI would be told it was saved while every RFI still printed on A4,
    because the RFI form is always A4. Refusing the whole request leaves the
    stored override exactly as it was.
    """
    not_honoured = [field for field in submitted if field not in kind.fields]
    if not_honoured:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_document_type_override",
                "document_type": kind.key,
                "field": not_honoured[0],
                "fields": not_honoured,
                "reason": "field_not_configurable",
                "message": f"{kind.label} documents do not use {', '.join(not_honoured)}. "
                f"Their own look can set: {', '.join(kind.fields)}.",
                "allowed_fields": list(kind.fields),
            },
        )
    kept = sanitise_override(kind.key, submitted)
    unusable = [field for field in submitted if field not in kept]
    if unusable:
        field = unusable[0]
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_document_type_override",
                "document_type": kind.key,
                "field": field,
                "fields": unusable,
                "reason": "invalid_value",
                "message": f"{submitted[field]!r} is not a usable {field}; "
                f"expected {_VALUE_HINTS.get(field, 'a value the settings accept')}.",
                "allowed_fields": list(kind.fields),
            },
        )


def _document_type_response(kind: DocumentType) -> DocumentTypeResponse:
    return DocumentTypeResponse(
        key=kind.key,
        label=kind.label,
        label_key=kind.label_key,
        fields=list(kind.fields),
        override=read_overrides().get(kind.key, {}),
        effective=DocumentAppearanceResponse(**resolve_appearance(kind.key)),
    )


@router.get(
    "/document-appearance/types/",
    response_model=list[DocumentTypeResponse],
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/document-appearance/types",
    response_model=list[DocumentTypeResponse],
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def list_document_types() -> list[DocumentTypeResponse]:
    """Every document type that can carry its own look, in registry order.

    Reserved types, whose generators do not read the appearance yet, are left
    out: a type with nothing to set is a page of controls that do nothing.
    """
    return [_document_type_response(kind) for kind in DOCUMENT_TYPES.values() if kind.configurable]


@router.put(
    "/document-appearance/types/{doc_type}/",
    response_model=DocumentTypeResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/document-appearance/types/{doc_type}",
    response_model=DocumentTypeResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_document_type_override(doc_type: str, body: DocumentTypeOverrideUpdate) -> DocumentTypeResponse:
    """Admin: replace one type's override. An empty body clears it, as DELETE does."""
    kind = _configurable_type(doc_type)
    submitted = {key: value for key, value in body.model_dump().items() if value is not None}
    _refuse_an_unusable_override(kind, submitted)
    write_override(kind.key, submitted)
    return _document_type_response(kind)


@router.delete(
    "/document-appearance/types/{doc_type}/",
    response_model=DocumentTypeResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.delete(
    "/document-appearance/types/{doc_type}",
    response_model=DocumentTypeResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def delete_document_type_override(doc_type: str) -> DocumentTypeResponse:
    """Admin: drop one type's override, so it follows the workspace look again."""
    kind = _configurable_type(doc_type)
    reset_override(kind.key)
    return _document_type_response(kind)


async def _reader_paper_preference(user_id: Any) -> str | None:
    """The reader's Settings paper size (``oe_users_user.paper_size``), or ``None``.

    Never raises: a row that cannot be read costs the preference, and the
    sample falls back to the platform default sheet.
    """
    try:
        import uuid

        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as session:
            return (
                await session.execute(select(User.paper_size).where(User.id == uuid.UUID(str(user_id))))
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - a preview must not fail on a preference lookup
        logger.debug("Could not read the reader's paper size for a sample; using the default", exc_info=True)
        return None


@router.get(
    "/document-appearance/types/{doc_type}/sample.pdf",
    response_class=Response,
)
@router.get(
    "/document-appearance/types/{doc_type}/sample.pdf/",
    response_class=Response,
    include_in_schema=False,
)
async def get_document_type_sample(
    doc_type: str,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> Response:
    """The sample page drawn with one type's look, on the sheet the type prints on.

    Same headers, and for the same reasons, as the workspace sample above.

    A type printed on the sender's paper (the transmittal cover) is drawn on
    the reader's own Settings paper size, because the reader is who would send
    it. The sample has no project, so an unset preference resolves as it does
    for a project with no country: A4. A real cover on a US project with the
    preference unset prints on Letter.
    """
    from app.core.paper_size import resolve_paper_size
    from app.core.pdf_branding import render_sample_pdf

    kind = _configurable_type(doc_type)
    paper = None
    if kind.sheet is not None and kind.sheet.page_size == USER_PAPER:
        paper = resolve_paper_size(await _reader_paper_preference(payload.get("sub")), None)
    # Off the event loop, for the reason the workspace sample above gives.
    return Response(
        content=await asyncio.to_thread(render_sample_pdf, kind.key, paper=paper),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="sample-{kind.key}.pdf"',
            "Content-Language": "en",
            "Cache-Control": "no-store",
        },
    )

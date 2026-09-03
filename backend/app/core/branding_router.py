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

Persistence is a small JSON file in the data dir (see
:mod:`app.core.app_branding` and :mod:`app.core.pdf_appearance`) - no database
table, so this needs no migration.

The appearance endpoints live here rather than in a router of their own because
they are the same concern seen from two sides: the brand says whose document it
is, the appearance says what it looks like, and both are read by the same PDF
layer. One mount, one place to look.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.app_branding import (
    MAX_COMPANY_NAME,
    merge_branding,
    read_branding,
    reset_branding,
)
from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    LOGO_ALIGNMENTS,
    MAX_FONT_SIZE,
    MAX_FOOTER_TEXT,
    MAX_MARGIN_MM,
    MIN_FONT_SIZE,
    MIN_MARGIN_MM,
    PAGE_SIZES,
    read_appearance,
    reset_appearance,
    write_appearance,
)
from app.dependencies import RequireRole, get_current_user_payload

router = APIRouter(tags=["branding"])


class BrandingResponse(BaseModel):
    """The workspace brand. ``mode`` is one of default / logo / text."""

    mode: str = "default"
    logo_data_url: str | None = None
    company_name: str = ""
    #: Organisation profile - the company facts modules read instead of
    #: hard-coding anyone's employer (see app_branding.DEFAULT_BRANDING).
    org_name: str = ""
    reference_prefix: str = ""
    own_mail_domains: str = ""


class BrandingUpdate(BaseModel):
    """Admin payload to set the workspace brand.

    All fields optional so the client can send just what changed; the server
    merges over what is stored, then sanitises and reconciles (a logo wins;
    ``text`` needs a name) before persisting, so the stored set is always
    consistent.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    mode: str | None = None
    logo_data_url: str | None = None
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)
    org_name: str | None = Field(default=None, max_length=200)
    reference_prefix: str | None = Field(default=None, max_length=40)
    own_mail_domains: str | None = Field(default=None, max_length=500)


@router.get("/branding/", response_model=BrandingResponse)
@router.get("/branding", response_model=BrandingResponse, include_in_schema=False)
async def get_branding() -> BrandingResponse:
    """Public: the workspace brand for the login page and the app shell."""
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
    """Admin: set the workspace brand so it persists for every browser and user.

    Merges over the stored branding first - the docstring above promises
    "send just what changed", and without the merge a partial update (say,
    only the organisation fields) silently wiped the stored logo.
    """
    return BrandingResponse(**merge_branding(body.model_dump(exclude_none=True)))


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
    """Admin: clear the custom look and go back to the platform default."""
    return DocumentAppearanceResponse(**reset_appearance())

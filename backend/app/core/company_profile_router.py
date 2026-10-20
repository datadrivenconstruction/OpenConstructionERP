# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Company profile API - the letterhead printed on generated documents.

    GET    /api/v1/company-profile/         - any signed-in user. The settings
                                              preview reads it, and so does an
                                              export started by a non-admin.
    GET    /api/v1/company-profile/options/ - any signed-in user. The caps the
                                              sanitiser enforces, for the form.
    PUT    /api/v1/company-profile/         - admin only. Merge and persist.
    DELETE /api/v1/company-profile/         - admin only. Clear the profile.

Deliberately NOT mounted alongside the public ``GET /api/v1/branding/`` in
:mod:`app.core.branding_router`. That endpoint answers anonymous callers,
because the login page needs the app brand before sign-in; a registered
address and a tax identifier must never be one field away from it. A router of
its own, reading a file of its own, keeps the two apart structurally rather
than by somebody remembering which keys to leave out of a response.

Persistence is a small JSON file in the data dir (see
:mod:`app.core.company_profile`) - no database table, so this needs no
migration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.app_branding import MAX_LOGO_DATA_URL_CHARS
from app.core.company_profile import (
    LOGO_IMAGE_TYPES,
    MAX_ADDRESS_CHARS,
    MAX_ADDRESS_LINES,
    MAX_EMAIL,
    MAX_LEGAL_NAME,
    MAX_PHONE,
    MAX_REGISTRATION_LINE,
    MAX_WEBSITE,
    read_company_profile,
    reset_company_profile,
    sanitise,
    write_company_profile,
)
from app.dependencies import RequireRole, get_current_user_payload

router = APIRouter(tags=["company-profile"])

#: The accepted logo types as MIME names, for the options and the refusal.
_LOGO_MIME_TYPES = [f"image/{kind}" for kind in LOGO_IMAGE_TYPES]


class CompanyProfileResponse(BaseModel):
    """The letterhead. Always complete and already sanitised; unset is ``""``."""

    document_logo_data_url: str = ""
    #: PNG rasterised in the browser from an SVG logo; PDFs print this one.
    document_logo_png_data_url: str = ""
    legal_name: str = ""
    address: str = ""
    registration_line: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""


class CompanyProfileOptions(BaseModel):
    """The caps the UI form should enforce.

    Served from the same constants the sanitiser uses, so a form built from
    this response cannot accept text the server will quietly trim or a file
    type it will quietly drop.
    """

    max_lengths: dict[str, int]
    max_address_lines: int
    max_logo_data_url_chars: int
    logo_mime_types: list[str]


class CompanyProfileUpdate(BaseModel):
    """Admin payload. All fields optional so a client can send just what changed.

    Deliberately untyped beyond the basics: caps and formats are enforced by
    :func:`app.core.company_profile.sanitise`, which also guards the read path,
    so there is exactly one definition of what a legal profile is. A cap
    repeated here would answer an over-long name with a 422 where the
    sanitiser trims it. The one refusal, an unusable logo, is decided by that
    same sanitiser in :func:`_refuse_an_unusable_logo`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_logo_data_url: str | None = None
    document_logo_png_data_url: str | None = None
    legal_name: str | None = None
    address: str | None = None
    registration_line: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None


@router.get(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_company_profile() -> CompanyProfileResponse:
    """The letterhead every generated document is printed with."""
    return CompanyProfileResponse(**read_company_profile())


@router.get(
    "/company-profile/options/",
    response_model=CompanyProfileOptions,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/company-profile/options",
    response_model=CompanyProfileOptions,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_company_profile_options() -> CompanyProfileOptions:
    """The caps and accepted logo types, so the form never offers a rejected value."""
    return CompanyProfileOptions(
        max_lengths={
            "legal_name": MAX_LEGAL_NAME,
            "address": MAX_ADDRESS_CHARS,
            "registration_line": MAX_REGISTRATION_LINE,
            "phone": MAX_PHONE,
            "email": MAX_EMAIL,
            "website": MAX_WEBSITE,
        },
        max_address_lines=MAX_ADDRESS_LINES,
        max_logo_data_url_chars=MAX_LOGO_DATA_URL_CHARS,
        logo_mime_types=list(_LOGO_MIME_TYPES),
    )


def _refuse_an_unusable_logo(submitted: str | None) -> None:
    """Answer 422 when a submitted logo would not survive the sanitiser.

    Text fields are trimmed on the way in and the admin sees the trimmed value
    in the response. A logo cannot be trimmed: the sanitiser reduces it to
    ``""``, and merged over the stored profile that ``""`` would silently
    delete the logo the firm already had, behind a 200. Refusing the whole
    request leaves the stored profile exactly as it was.

    ``None`` (leave alone) and ``""`` (clear on purpose) are not submissions of
    a logo and pass through. Whether a logo is usable is still the sanitiser's
    call; the length is consulted only to say why it was not.
    """
    if not submitted or sanitise({"document_logo_data_url": submitted})["document_logo_data_url"]:
        return
    if len(submitted) > MAX_LOGO_DATA_URL_CHARS:
        reason = "too_large"
        message = (
            f"The document logo is too large: {len(submitted)} characters as a data URL, "
            f"the limit is {MAX_LOGO_DATA_URL_CHARS}."
        )
    else:
        reason = "unsupported_format"
        message = "The document logo must be a base64 data URL of one of: " + ", ".join(_LOGO_MIME_TYPES) + "."
    raise HTTPException(
        status_code=422,
        detail={
            "error": "invalid_document_logo",
            "field": "document_logo_data_url",
            "reason": reason,
            "message": message,
            "accepted_types": list(_LOGO_MIME_TYPES),
            "max_chars": MAX_LOGO_DATA_URL_CHARS,
        },
    )


@router.put(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_company_profile(body: CompanyProfileUpdate) -> CompanyProfileResponse:
    """Admin: set the letterhead. Merged over what is stored, then sanitised.

    ``None`` leaves the stored value alone, so the form can save one field at a
    time and a client that only changes the logo does not have to resend the
    address. An empty string clears that one field; DELETE clears them all. A
    logo the sanitiser would drop is refused with 422 before anything is
    merged, so it cannot cost the firm the logo already stored.
    """
    _refuse_an_unusable_logo(body.document_logo_data_url)
    current = read_company_profile()
    patch = {key: value for key, value in body.model_dump().items() if value is not None}
    if "document_logo_data_url" in patch:
        # A new logo replaces its PNG too, unless the same request carries one.
        patch.setdefault("document_logo_png_data_url", "")
    current.update(patch)
    return CompanyProfileResponse(**write_company_profile(current))


@router.delete(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.delete(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def delete_company_profile() -> CompanyProfileResponse:
    """Admin: clear the letterhead, so documents print without one again."""
    return CompanyProfileResponse(**reset_company_profile())

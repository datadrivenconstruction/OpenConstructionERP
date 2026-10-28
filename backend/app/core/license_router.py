# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Read the bundled third-party licence texts from the running product.

    GET /api/v1/licenses/        - PUBLIC. Every licence text in this build.
    GET /api/v1/licenses/{name}  - PUBLIC. One text in full.

The texts are the ones :mod:`app.core.license_texts` locates: LGPL-3.0 and
LGPL-2.1 for the libraries NOTICE lists, GPL-3.0 because LGPL-3.0 is written as
additional permissions on top of it, and the OpenSSL, SSLeay, HarfBuzz and
PostgreSQL texts for native binaries arriving inside other packages' wheels.
They have shipped inside every artefact for the life of the product with
nothing in the backend able to read them, so the only way to see one was to go
to gnu.org. On a desktop install with no network that is a link to nothing, and
that is the deployment where somebody is most likely to be looking.

Public on purpose, and it is the same reasoning as ``branding_router``: these
are published documents that anyone may read, they carry nothing about this
workspace, and a licence you have to sign in to read is not much better than a
licence behind a dead link.

Two states, told apart deliberately, because collapsing them is the failure
this endpoint is most likely to ship with:

* ``404`` - this build has no licence by that name. An ordinary answer.
* ``503`` - the directory itself could not be located, so we cannot say what
  this build carries. Answering 404 here would tell a reader "there is no such
  licence" when the truth is "this install is broken", and the reader most
  affected is the one checking compliance.

The listing answers with an envelope rather than a bare array, so a later
addition of paging is not a breaking change for callers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.license_texts import (
    LicenseTextsUnavailable,
    list_license_texts,
    read_license_text,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/licenses", tags=["licenses"])

_UNAVAILABLE_DETAIL = (
    "The bundled licence texts could not be located in this installation. "
    "This is a packaging fault rather than an absence of licences."
)


class LicenseTextSummary(BaseModel):
    """One licence text as the listing describes it, without its body."""

    name: str = Field(description="File name, and the identifier /licenses/{name} takes.")
    title: str = Field(description="The document's own first line, so no table of ours has to be edited.")
    size_bytes: int = Field(description="Length on disk, so a caller can warn before opening 35 kB of GPL.")


class LicenseTextListResponse(BaseModel):
    """Envelope for the listing."""

    items: list[LicenseTextSummary] = Field(default_factory=list)
    total: int = 0


class LicenseTextResponse(BaseModel):
    """One licence text in full."""

    name: str
    title: str
    size_bytes: int
    text: str


def _listing() -> list[LicenseTextSummary]:
    """Return the listing, or raise the HTTP fault for a build we cannot read."""
    try:
        found = list_license_texts()
    except LicenseTextsUnavailable as exc:
        logger.error("licence texts unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc
    return [LicenseTextSummary(name=t.name, title=t.title, size_bytes=t.size_bytes) for t in found]


@router.get("/", response_model=LicenseTextListResponse)
@router.get("", response_model=LicenseTextListResponse, include_in_schema=False)
async def get_license_list() -> LicenseTextListResponse:
    """Public: every licence text this build carries.

    Enumerated from the directory, so a text committed later is served without
    anyone editing this file or the panel that reads it.
    """
    items = _listing()
    return LicenseTextListResponse(items=items, total=len(items))


@router.get("/{name}", response_model=LicenseTextResponse)
async def get_license_text(name: str) -> LicenseTextResponse:
    """Public: one licence text in full.

    ``name`` is matched against a listing of the directory and never joined
    onto it, so there is no traversal defence here to review: a request for a
    name the listing does not hold is refused for the same reason a request
    for ``nonsense`` is.

    Args:
        name: A name exactly as :func:`get_license_list` reported it.

    Raises:
        HTTPException: 404 when this build has no such licence, 503 when the
            directory could not be located at all.
    """
    summary = next((item for item in _listing() if item.name == name), None)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No bundled licence text named {name!r}.")

    text = read_license_text(summary.name)
    if text is None:
        # The listing named it and the read did not find it: the directory
        # changed under us between the two calls. Rare, and still not a 404,
        # because a reader who was just told the file exists needs to know the
        # difference between "gone" and "never there".
        logger.error("licence text %s vanished between listing and read", summary.name)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)

    return LicenseTextResponse(
        name=summary.name,
        title=summary.title,
        size_bytes=summary.size_bytes,
        text=text,
    )

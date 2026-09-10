# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice standalone API routes.

Mounted at ``/api/v1/einvoice/``.

    GET  /profiles           - list the profile registry
    POST /validate           - validate invoice data against EN 16931 rules
    POST /generate           - generate CII/UBL XML (or hybrid PDF) from raw data

These endpoints expose the EN 16931 engine without requiring a persisted
invoice. The finance module's ``/invoices/{id}/einvoice`` endpoint renders
from a stored invoice; these accept raw dicts and return the result in one
call, which is useful for integrations, pre-flight checks and testing.
"""

from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.dependencies import RequirePermission
from app.modules.einvoice.schemas import (
    GenerateRequest,
    ProfileResponse,
    ValidateRequest,
    ValidateResponse,
    ViolationResponse,
)

router = APIRouter()


def _invoice_dict(data: Any) -> dict[str, Any]:
    """Convert a Pydantic invoice schema to the dict shape ``build_einvoice`` expects."""
    return data.model_dump(mode="python")


def _line_dicts(items: list[Any]) -> list[dict[str, Any]]:
    """Convert Pydantic line schemas to the list-of-dicts shape the engine expects."""
    return [item.model_dump(mode="python") for item in items]


@router.get(
    "/profiles",
    response_model=list[ProfileResponse],
    summary="List the EN 16931 country profiles this build can issue",
    description=(
        "The profile registry, one entry per supported country or network "
        "flavour. Adding a country is one registry entry in ``profiles.py``."
    ),
)
async def list_profiles(
    _perm: None = Depends(RequirePermission("finance.read")),
) -> list[dict[str, Any]]:
    """Return every supported e-invoice profile with its syntax and region."""
    from app.modules.einvoice.profiles import PROFILES

    return [
        {
            "key": key,
            "name": p.name,
            "syntax": p.syntax,
            "region": p.region,
            "label": p.label,
        }
        for key, p in PROFILES.items()
    ]


@router.post(
    "/validate",
    response_model=ValidateResponse,
    summary="Validate invoice data against EN 16931 rules",
    description=(
        "Dry-run validation without generating a document. Returns every rule "
        "finding, fatal and advisory alike, each carrying the identifier a "
        "receiver's validator would report (BR-61, BR-CO-15, BR-DE-15, etc.). "
        "Fatal findings block generation; warnings are informational."
    ),
)
async def validate_invoice(
    body: ValidateRequest,
    _perm: None = Depends(RequirePermission("finance.read")),
) -> ValidateResponse:
    """Validate raw invoice data and return structured rule findings."""
    from app.modules.einvoice.rules import FATAL
    from app.modules.einvoice.service import violations_for

    invoice_dict = _invoice_dict(body.invoice)
    line_items = _line_dicts(body.line_items)
    seller = body.seller.model_dump(mode="python") if body.seller else None
    buyer = body.buyer.model_dump(mode="python") if body.buyer else None

    found = violations_for(
        invoice=invoice_dict,
        line_items=line_items,
        profile=body.profile,
        seller=seller,
        buyer=buyer,
    )

    problems = [v.message for v in found if v.severity == FATAL]
    return ValidateResponse(
        format=body.profile,
        valid=not problems,
        problems=problems,
        violations=[
            ViolationResponse(
                rule_id=v.rule_id,
                severity=v.severity,
                message=v.message,
                term=v.term,
                params=v.params,
            )
            for v in found
        ],
    )


@router.post(
    "/generate",
    summary="Generate an EN 16931 e-invoice from raw data",
    description=(
        "Build a CII or UBL XML document (or a Factur-X/ZUGFeRD hybrid PDF "
        "when embed=true) from raw invoice data, without touching the database. "
        "The profile selects the syntax and country flavour. Raises 422 when "
        "the data fails validation."
    ),
    response_description="application/xml or application/pdf stream",
    response_model=None,
)
async def generate_invoice(
    body: GenerateRequest,
    _perm: None = Depends(RequirePermission("finance.read")),
) -> StreamingResponse:
    """Generate and stream an EN 16931 e-invoice from raw data."""
    from app.modules.einvoice.cii import EInvoiceError
    from app.modules.einvoice.profiles import SUPPORTED_PROFILES
    from app.modules.einvoice.service import render_einvoice, render_einvoice_pdf

    profile = (body.profile or "xrechnung").strip().lower()
    if profile not in SUPPORTED_PROFILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown e-invoice profile {body.profile!r}; use one of {', '.join(SUPPORTED_PROFILES)}",
        )

    invoice_dict = _invoice_dict(body.invoice)
    line_items = _line_dicts(body.line_items)
    seller = body.seller.model_dump(mode="python") if body.seller else None
    buyer = body.buyer.model_dump(mode="python") if body.buyer else None

    try:
        if body.embed:
            filename, media_type, data = render_einvoice_pdf(
                invoice=invoice_dict,
                line_items=line_items,
                profile=profile,
                seller=seller,
                buyer=buyer,
                locale=body.locale,
            )
        else:
            filename, media_type, data = render_einvoice(
                invoice=invoice_dict,
                line_items=line_items,
                profile=profile,
                seller=seller,
                buyer=buyer,
            )
    except EInvoiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invoice is not EN 16931 complete for {profile}: {exc}",
        ) from exc

    headers = {"Content-Disposition": attachment_disposition(filename)}
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers=headers,
    )

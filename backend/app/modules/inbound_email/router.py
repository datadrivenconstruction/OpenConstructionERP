# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Inbound email API routes (auto-mounted at /api/v1/inbound-email).

A single endpoint that imports a stored RFC-822 message (a ".eml" file) and
returns the parsed record together with any construction delay signals detected
in it. The intake is a file import, not a live mailbox; nothing is persisted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.dependencies import RequirePermission
from app.modules.inbound_email.schemas import InboundEmailAnalysisOut
from app.modules.inbound_email.service import analyze_inbound_email

router = APIRouter(tags=["Inbound Email"])


@router.post(
    "/parse",
    response_model=InboundEmailAnalysisOut,
    dependencies=[Depends(RequirePermission("inbound_email.read"))],
)
async def parse_inbound_email(
    file: UploadFile = File(description="A stored RFC-822 message (.eml) to import."),
) -> InboundEmailAnalysisOut:
    """Parse an uploaded stored message and flag any delay signals in it."""
    raw = await file.read()
    analysis = analyze_inbound_email(raw)
    return InboundEmailAnalysisOut.model_validate(analysis)

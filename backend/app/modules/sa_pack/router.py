# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠South Africa regional pack API routes.

Endpoints (all require an authenticated user):
    GET  /config            - Full SA regional configuration
    GET  /provinces         - Provinces with indicative location factors
    GET  /cidb/grades       - CIDB grading reference
    GET  /procurement/pppfa - PPPFA preferential procurement reference
    POST /pppfa/score       - Score a bid with the official PPPFA price-points formula
    GET  /vat/calculate     - VAT breakdown for an amount (reuses app.core.tax)

Business logic lives in service.py (pure, unit-testable). This router only
handles transport and translates ValueError / VATNotApplicable into HTTP 422.
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.tax import VATNotApplicable
from app.dependencies import get_current_user_id
from app.modules.sa_pack import service
from app.modules.sa_pack.config import PACK_CONFIG

router = APIRouter(dependencies=[Depends(get_current_user_id)])
logger = logging.getLogger(__name__)


@router.get("/config/")
async def get_config() -> dict:
    """Return the South Africa regional pack configuration."""
    return PACK_CONFIG


@router.get("/provinces/")
async def list_provinces() -> dict:
    """Return the nine provinces with indicative location factors."""
    return {"provinces": PACK_CONFIG["provinces"], "note": PACK_CONFIG["provinces_note"]}


@router.get("/cidb/grades/")
async def cidb_grades() -> dict:
    """Return the CIDB contractor grading reference."""
    return PACK_CONFIG["contractor_grading"]


@router.get("/procurement/pppfa/")
async def pppfa_reference() -> dict:
    """Return the PPPFA preferential procurement reference."""
    return PACK_CONFIG["procurement"]["preferential_framework"]


@router.post("/pppfa/score/")
async def pppfa_score(
    bid_price: Decimal = Query(..., description="Tender price under consideration (ZAR)."),
    lowest_acceptable_price: Decimal = Query(..., description="Lowest acceptable tender price (ZAR)."),
    preference_points: Decimal = Query(Decimal("0"), description="Preference points awarded (e.g. for B-BBEE)."),
    estimated_value: Decimal | None = Query(None, description="Estimated contract value; picks 80/20 vs 90/10."),
    system: str | None = Query(None, description="Force a system: '80/20' or '90/10'. Otherwise derived from value."),
) -> dict:
    """Score a bid with the official PPPFA price-points formula."""
    try:
        return service.score_pppfa(
            bid_price=bid_price,
            lowest_acceptable_price=lowest_acceptable_price,
            preference_points=preference_points,
            estimated_value=estimated_value,
            system=system,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/vat/calculate/")
async def vat_calculate(
    amount: Decimal = Query(..., description="VAT-exclusive amount (ZAR)."),
    kind: str = Query("standard", description="Rate kind: 'standard' or 'zero'."),
) -> dict:
    """Return the VAT breakdown for an amount, using the core SA VAT rate."""
    try:
        return service.calculate_vat(amount=amount, kind=kind)
    except (ValueError, VATNotApplicable) as exc:
        raise HTTPException(422, str(exc)) from exc

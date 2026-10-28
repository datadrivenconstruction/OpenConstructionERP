# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Mexico regional pack API routes.

Endpoints (all require an authenticated user):
    GET  /config             - Full Mexico regional configuration
    GET  /states             - States with indicative location factors
    GET  /apu/structure      - APU (analisis de precios unitarios) structure
    POST /apu/integrate      - Integrate a unit price the LOPSRM reglamento way
    GET  /tax/iva            - IVA and retenciones reference
    GET  /iva/calculate      - IVA breakdown for an amount (reuses app.core.tax)
    POST /retenciones/calculate - IVA and ISR retenciones on a subcontract payment
    GET  /cfdi               - CFDI 4.0 invoicing reference
    GET  /social-housing     - INFONAVIT, FOVISSSTE and CONAVI reference
    GET  /safety             - IMSS and NOM site-safety reference

Business logic lives in service.py (pure, unit-testable). This router only
handles transport and translates ValueError / VATNotApplicable into HTTP 422.
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.tax import VATNotApplicable
from app.dependencies import get_current_user_id
from app.modules.mexico_pack import service
from app.modules.mexico_pack.config import PACK_CONFIG

router = APIRouter(dependencies=[Depends(get_current_user_id)])
logger = logging.getLogger(__name__)


@router.get("/config/")
async def get_config() -> dict:
    """Return the Mexico regional pack configuration."""
    return PACK_CONFIG


@router.get("/states/")
async def list_states() -> dict:
    """Return the 32 states with indicative location factors."""
    return {"states": PACK_CONFIG["states"], "note": PACK_CONFIG["states_note"]}


@router.get("/apu/structure/")
async def apu_structure() -> dict:
    """Return the APU (analisis de precios unitarios) integration structure."""
    return PACK_CONFIG["apu"]


@router.post("/apu/integrate/")
async def apu_integrate(
    materiales: Decimal = Query(..., description="Direct material cost per unit (MXN)."),
    mano_de_obra: Decimal = Query(..., description="Direct labor cost per unit (MXN)."),
    maquinaria: Decimal = Query(Decimal("0"), description="Machinery, equipment and tool cost per unit (MXN)."),
    indirectos_pct: Decimal = Query(..., description="Overhead percentage on the costo directo."),
    financiamiento_pct: Decimal = Query(
        Decimal("0"), description="Financing percentage on costo directo plus indirectos."
    ),
    utilidad_pct: Decimal = Query(..., description="Profit percentage on the accumulated cost."),
    cargos_adicionales_pct: Decimal | None = Query(
        None, description="Additional-charges percentage; defaults to the cinco al millar (0.5 percent)."
    ),
) -> dict:
    """Integrate a unit price (precio unitario) per the LOPSRM reglamento."""
    try:
        return service.integrate_apu(
            materiales=materiales,
            mano_de_obra=mano_de_obra,
            maquinaria=maquinaria,
            indirectos_pct=indirectos_pct,
            financiamiento_pct=financiamiento_pct,
            utilidad_pct=utilidad_pct,
            cargos_adicionales_pct=cargos_adicionales_pct,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/tax/iva/")
async def iva_reference() -> dict:
    """Return the IVA and retenciones reference."""
    return PACK_CONFIG["tax"]


@router.get("/iva/calculate/")
async def iva_calculate(
    amount: Decimal = Query(..., description="IVA-exclusive amount (MXN)."),
    kind: str = Query("standard", description="Rate kind: 'standard', 'border' or 'zero'."),
) -> dict:
    """Return the IVA breakdown for an amount, using the core MX IVA rate."""
    try:
        return service.calculate_iva(amount=amount, kind=kind)
    except (ValueError, VATNotApplicable) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/retenciones/calculate/")
async def retenciones_calculate(
    subtotal: Decimal = Query(..., description="Subcontractor IVA-exclusive amount (MXN)."),
    retener_iva: bool = Query(True, description="Withhold an IVA retention."),
    retener_isr: bool = Query(False, description="Withhold an ISR retention."),
    iva_retention_pct: Decimal | None = Query(
        None, description="IVA retention percentage; defaults to the 6 percent labor-provision reference."
    ),
    isr_retention_pct: Decimal | None = Query(
        None, description="ISR retention percentage; defaults to 0 (set per contract and regime)."
    ),
) -> dict:
    """Compute IVA and ISR retenciones withheld from a subcontractor payment."""
    try:
        return service.calculate_retenciones(
            subtotal=subtotal,
            retener_iva=retener_iva,
            retener_isr=retener_isr,
            iva_retention_pct=iva_retention_pct,
            isr_retention_pct=isr_retention_pct,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/cfdi/")
async def cfdi_reference() -> dict:
    """Return the CFDI 4.0 invoicing reference."""
    return PACK_CONFIG["cfdi"]


@router.get("/social-housing/")
async def social_housing_reference() -> dict:
    """Return the INFONAVIT, FOVISSSTE and CONAVI reference."""
    return PACK_CONFIG["social_housing"]


@router.get("/safety/")
async def safety_reference() -> dict:
    """Return the IMSS and NOM site-safety reference."""
    return PACK_CONFIG["labor_safety"]

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stateless business logic for the Mexico regional pack.

Pure functions with no transport or database dependencies, so they are unit
testable in isolation. The router wraps these and translates ``ValueError`` and
``VATNotApplicable`` into HTTP 422. Money is Decimal in, strings out.

The three computations encode the Mexican specifics:

* :func:`integrate_apu` integrates a unit price (precio unitario) the way the
  LOPSRM reglamento prescribes: costo directo, then indirectos, financiamiento,
  utilidad and cargos adicionales, each applied to the running accumulated cost.
* :func:`calculate_iva` returns an IVA breakdown using the canonical MX rate in
  :mod:`app.core.tax` (16 percent standard, 8 percent border region, 0 zero).
* :func:`calculate_retenciones` computes the IVA and ISR retenciones withheld
  from a subcontractor payment and the resulting net amount.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.tax import get_vat_rate
from app.modules.mexico_pack.config import (
    CINCO_AL_MILLAR_PCT,
    DEFAULT_RETENCION_IVA_PCT,
)

_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")
_MAX_PCT = Decimal("100")

# Map the user-facing IVA kind to the rate kind ``app.core.tax`` understands.
# "border" is the region fronteriza rate, stored there as the "reduced" tier.
_IVA_KIND_TO_TAX_KIND = {"standard": "standard", "border": "reduced", "zero": "zero"}


def _require_non_negative(value: Decimal, name: str) -> None:
    """Raise ``ValueError`` when ``value`` is negative."""
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")


def _require_pct(value: Decimal, name: str) -> None:
    """Raise ``ValueError`` when ``value`` is outside the 0 to 100 range."""
    if value < 0 or value > _MAX_PCT:
        raise ValueError(f"{name} must be a percentage between 0 and 100.")


def integrate_apu(
    materiales: Decimal,
    mano_de_obra: Decimal,
    maquinaria: Decimal,
    indirectos_pct: Decimal,
    financiamiento_pct: Decimal,
    utilidad_pct: Decimal,
    cargos_adicionales_pct: Decimal | None = None,
) -> dict:
    """Integrate a unit price (precio unitario) the LOPSRM reglamento way.

    The precio unitario is built up in order:

    * ``costo_directo`` = materiales + mano de obra + maquinaria/herramienta;
    * ``indirectos`` applies to the costo directo;
    * ``financiamiento`` applies to costo directo plus indirectos;
    * ``utilidad`` applies to costo directo plus indirectos plus financiamiento;
    * ``cargos_adicionales`` applies to all of the above (defaults to the cinco
      al millar 0.5 percent inspection fee).

    IVA is deliberately NOT folded in here: it is applied to the estimate total,
    not to the unit price.

    Args:
        materiales: Direct material cost per unit.
        mano_de_obra: Direct labor cost per unit.
        maquinaria: Machinery, equipment and tool cost per unit.
        indirectos_pct: Overhead percentage on the costo directo.
        financiamiento_pct: Financing percentage on costo directo plus indirectos.
        utilidad_pct: Profit percentage on the accumulated cost before it.
        cargos_adicionales_pct: Additional-charges percentage; defaults to the
            cinco al millar (0.5 percent) when omitted.

    Returns:
        A dict with each component and the integrated ``precio_unitario``, all
        as strings (money convention).

    Raises:
        ValueError: on a negative cost or a percentage outside 0 to 100.
    """
    cargos_pct = Decimal(CINCO_AL_MILLAR_PCT) if cargos_adicionales_pct is None else cargos_adicionales_pct

    _require_non_negative(materiales, "materiales")
    _require_non_negative(mano_de_obra, "mano_de_obra")
    _require_non_negative(maquinaria, "maquinaria")
    _require_pct(indirectos_pct, "indirectos_pct")
    _require_pct(financiamiento_pct, "financiamiento_pct")
    _require_pct(utilidad_pct, "utilidad_pct")
    _require_pct(cargos_pct, "cargos_adicionales_pct")

    costo_directo = (materiales + mano_de_obra + maquinaria).quantize(_CENTS)

    indirectos = (costo_directo * indirectos_pct / _HUNDRED).quantize(_CENTS)
    base_financiamiento = costo_directo + indirectos
    financiamiento = (base_financiamiento * financiamiento_pct / _HUNDRED).quantize(_CENTS)
    base_utilidad = base_financiamiento + financiamiento
    utilidad = (base_utilidad * utilidad_pct / _HUNDRED).quantize(_CENTS)
    base_cargos = base_utilidad + utilidad
    cargos_adicionales = (base_cargos * cargos_pct / _HUNDRED).quantize(_CENTS)
    precio_unitario = (base_cargos + cargos_adicionales).quantize(_CENTS)

    return {
        "materiales": str(materiales.quantize(_CENTS)),
        "mano_de_obra": str(mano_de_obra.quantize(_CENTS)),
        "maquinaria": str(maquinaria.quantize(_CENTS)),
        "costo_directo": str(costo_directo),
        "indirectos_pct": str(indirectos_pct),
        "indirectos": str(indirectos),
        "financiamiento_pct": str(financiamiento_pct),
        "financiamiento": str(financiamiento),
        "utilidad_pct": str(utilidad_pct),
        "utilidad": str(utilidad),
        "cargos_adicionales_pct": str(cargos_pct),
        "cargos_adicionales": str(cargos_adicionales),
        "precio_unitario": str(precio_unitario),
    }


def calculate_iva(amount: Decimal, kind: str = "standard") -> dict:
    """Return the IVA breakdown for an amount using the core MX IVA rate.

    Args:
        amount: IVA-exclusive amount (MXN).
        kind: ``"standard"`` (16 percent), ``"border"`` (8 percent region
            fronteriza) or ``"zero"`` (0 percent).

    Returns:
        A dict with the rate and the exclusive/iva/inclusive amounts, all
        as strings.

    Raises:
        ValueError: if ``amount`` is negative or ``kind`` is not one of the
            three supported values.
        VATNotApplicable: if the core tax table has no MX rate for the resolved
            kind (defensive; MX is covered by app.core.tax).
    """
    _require_non_negative(amount, "amount")
    tax_kind = _IVA_KIND_TO_TAX_KIND.get(kind)
    if tax_kind is None:
        raise ValueError("kind must be one of 'standard', 'border' or 'zero'.")
    rate = get_vat_rate("MX", tax_kind)
    exclusive = amount.quantize(_CENTS)
    iva = (amount * rate).quantize(_CENTS)
    return {
        "country": "MX",
        "kind": kind,
        "iva_rate": str(rate),
        "exclusive": str(exclusive),
        "iva": str(iva),
        "inclusive": str((exclusive + iva).quantize(_CENTS)),
    }


def calculate_retenciones(
    subtotal: Decimal,
    retener_iva: bool = True,
    retener_isr: bool = False,
    iva_retention_pct: Decimal | None = None,
    isr_retention_pct: Decimal | None = None,
) -> dict:
    """Compute IVA and ISR retenciones withheld from a subcontractor payment.

    The contratante invoices IVA on the subtotal (16 percent standard) and may
    withhold an IVA retention and an ISR retention, paying those to the SAT on
    the subcontractor's behalf. The net amount the subcontractor receives is the
    subtotal plus the IVA charged, minus the two retenciones.

    Args:
        subtotal: Subcontractor's IVA-exclusive amount (the retention base).
        retener_iva: Whether to withhold an IVA retention.
        retener_isr: Whether to withhold an ISR retention.
        iva_retention_pct: IVA retention percentage; defaults to the 6 percent
            labor-provision reference when ``retener_iva`` is set and it is
            omitted.
        isr_retention_pct: ISR retention percentage; defaults to 0 when omitted,
            since the rate depends on the payment type and regime.

    Returns:
        A dict with the IVA charged, each retention, and the net payable, all
        as strings.

    Raises:
        ValueError: on a negative subtotal or a percentage outside 0 to 100.
    """
    _require_non_negative(subtotal, "subtotal")
    subtotal_q = subtotal.quantize(_CENTS)

    iva_charged = (subtotal * get_vat_rate("MX", "standard")).quantize(_CENTS)

    iva_pct = Decimal("0")
    if retener_iva:
        iva_pct = Decimal(DEFAULT_RETENCION_IVA_PCT) if iva_retention_pct is None else iva_retention_pct
    _require_pct(iva_pct, "iva_retention_pct")
    retencion_iva = (subtotal * iva_pct / _HUNDRED).quantize(_CENTS)

    isr_pct = Decimal("0")
    if retener_isr:
        isr_pct = Decimal("0") if isr_retention_pct is None else isr_retention_pct
    _require_pct(isr_pct, "isr_retention_pct")
    retencion_isr = (subtotal * isr_pct / _HUNDRED).quantize(_CENTS)

    net_payable = (subtotal_q + iva_charged - retencion_iva - retencion_isr).quantize(_CENTS)

    return {
        "country": "MX",
        "subtotal": str(subtotal_q),
        "iva_charged": str(iva_charged),
        "retencion_iva_pct": str(iva_pct),
        "retencion_iva": str(retencion_iva),
        "retencion_isr_pct": str(isr_pct),
        "retencion_isr": str(retencion_isr),
        "net_payable": str(net_payable),
    }

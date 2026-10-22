# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Peruvian public works limits under the General Public Procurement Law.

Ley 32069 (Ley General de Contrataciones Publicas) and its Reglamento,
D.S. 009-2025-EF as modified by D.S. 001-2026-EF, are in force since
22 April 2025 and replaced Ley 30225. The oversight body is the OECE
(Organismo Especializado para las Contrataciones Publicas Eficientes).

**What was read.** Only Art. 210 of the Reglamento, as quoted in OECE
opinion D000059-2026-OECE-DTN: the contractor presents the monthly valuation
within the first three days of the following month, the supervisor reports
within five days, and the entity pays by the last day of the month in which
the valuation was presented. That figure is a calendar rule, not a number of
days, so ``works_payment_days`` stays empty and the payment clock regime
``pe_lgcp_art210`` counts it.

**What was not read.** The retention and performance guarantee, the advance
payments and the delay damages ceiling come from the working knowledge of
Peruvian contracting, not from the regulation text, and the advance caps are
the partner's brief. The whole regime is therefore ``needs_expert_review``:
every figure is shown and none is enforced until a person reads the article.

Rows of :data:`app.modules.contracts.public_procurement.PUBLIC_WORKS_LIMIT_REGIMES`.
"""

from __future__ import annotations

from typing import Any

_READ = "2026-10-22"
_LAW_URL = "https://www.gob.pe/institucion/oece/normas-legales"
_OPINION_URL = "https://img.lpderecho.pe/wp-content/uploads/2026/07/D000059-2026-OECE-DTN-1.pdf"
#: Ley 32069 came into force on 22 April 2025.
_IN_FORCE = "2025-04-22"
_REG = "Reglamento de la Ley 32069 (D.S. 009-2025-EF)"


def _fig(value: Any, reference: str, note: str, url: str = _LAW_URL) -> dict[str, Any]:
    return {
        "value": value,
        "statute_reference": reference,
        "source_url": url,
        "read_date": _READ,
        "effective_date": _IN_FORCE,
        "note": note,
        "needs_expert_review": True,
    }


def _unread(value: Any, subject: str, note: str) -> dict[str, Any]:
    return _fig(value, f"{_REG}, {subject}; article not read", note)


LGCP_2025: dict[str, Any] = {
    "regime": "pe_lgcp_2025",
    "law": "Ley General de Contrataciones Publicas, Ley 32069; Reglamento D.S. 009-2025-EF as modified by D.S. 001-2026-EF",
    "tender_date_from": _IN_FORCE,
    "tender_date_to": None,
    "confidence": "needs_expert_review",
    "bid_security_max_percent": _unread(None, "bid guarantee", "Not read."),
    "performance_security_percent": _unread(
        "10",
        "garantia de fiel cumplimiento",
        "Ten percent of the contract amount for works, as the partner brief states; the article was not read.",
    ),
    "performance_security_due_working_days": _unread(None, "garantia de fiel cumplimiento", "Not read."),
    "advance_payment_max_percent": _unread(
        "10",
        "adelanto directo",
        "Direct advance up to ten percent of the contract amount, as the partner brief states, against a "
        "guarantee, amortised pro rata in each valuation; the article was not read.",
    ),
    "advance_payment_max_percent_sme": _unread(None, "adelanto directo", "Not read."),
    "interim_payment_percent": _unread(None, "valorizaciones", "Not read."),
    "retention_percent": _unread(
        "10",
        "garantia de fiel cumplimiento",
        "Where the guarantee is lodged as a retention, ten percent of each valuation is held until the works are "
        "received; the article was not read.",
    ),
    "stored_materials_payment_percent": _unread(
        "20",
        "adelanto de materiales",
        "Advance for materials up to twenty percent of the contract amount, as the partner brief states, "
        "amortised as the materials are used; the article was not read.",
    ),
    "works_payment_days": _fig(
        None,
        f"{_REG}, art. 210.3",
        "No number of days: the entity evaluates and pays the valuation by the last day of the month in which it "
        "is presented. The payment clock regime pe_lgcp_art210 counts it.",
        _OPINION_URL,
    ),
    "supplies_payment_days": _unread(None, "payment of goods and services", "Not read."),
    "variation_max_percent_per_item_works": _unread(None, "adicionales de obra", "Not read."),
    "variation_max_percent_per_item_other": _unread(None, "prestaciones adicionales", "Not read."),
    "delay_damages_cap_percent_works": _unread(None, "penalidad por mora", "Not read."),
    "delay_damages_cap_percent_works_long_delay": _unread(None, "penalidad por mora", "Not read."),
    "delay_damages_cap_percent_other": _unread(None, "penalidad por mora", "Not read."),
    "delay_damages_cap_percent_other_long_delay": _unread(None, "penalidad por mora", "Not read."),
    "delay_damages_long_delay_threshold_percent": _unread(None, "penalidad por mora", "Not read."),
    "price_adjustment_min_duration_months": _unread(
        None,
        "reajuste de precios",
        "Works are adjusted by the polynomial formula the bidding documents state; no minimum duration was read. "
        "The price adjustment regime is pe_lgcp_formula_polinomica.",
    ),
}

REGIMES: list[dict[str, Any]] = [LGCP_2025]

__all__ = ["LGCP_2025", "REGIMES"]

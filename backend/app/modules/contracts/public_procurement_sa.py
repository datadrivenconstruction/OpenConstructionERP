# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi public works limits: two Government Tenders and Procurement Laws, by tender date.

The law that governs a Saudi public contract is the one in force when its
tender was floated. The Government Tenders and Procurement Law of 2019 (Royal
Decree M/128) and its Implementing Regulations govern every tender floated
before the new law (Royal Decree M/76 of 27/2/1448H, published in Umm Al-Qura
on 2026-09-04, in force 120 days after publication) takes effect, and keep
governing those contracts afterwards.

**The 2019 regime** was read in the Ministry of Finance English texts of the
law and of the regulations on 2026-10-19. Its figures are enforced.

**The 2026 regime** is known only from law-firm summaries: the implementing
regulations were not issued when it was read and the start date is the
approximate one the summaries compute (publication plus 120 days). Every
figure is ``needs_expert_review``, so the rules show it and never enforce it.

Rows of :data:`app.modules.contracts.public_procurement.PUBLIC_WORKS_LIMIT_REGIMES`;
read through :func:`app.modules.contracts.public_procurement.public_works_limits`.
"""

from __future__ import annotations

from typing import Any

_LAW_URL = (
    "https://www.mof.gov.sa/en/Knowledgecenter/newGovTendandProcLow/Documents/"
    "The%20Government%20Tenders%20and%20Procurement%20Law2.pdf"
)
_IR_URL = "https://mof.gov.sa/en/Knowledgecenter/newGovTendandProcLow/Documents/Executive%20Regulations.pdf"
_IMHORA_URL = (
    "https://imhora.com/disciplines/contract-administration/contract-documents/"
    "cd8-2-the-saudi-government-tenders-and-procurement-law-what/"
)
_GT_URL = (
    "https://www.gtlaw.com/en/insights/2026/8/"
    "the-kingdom-of-saudi-arabia-approves-new-government-tenders-and-procurement-law"
)
_SHURA_URL = "https://shuralawfirm.com/en/saudi-arabia-the-government-tenders-and-procurement-law/"
_READ = "2026-10-19"
#: The Implementing Regulations as amended by Resolution 3479 came into force on 1/9/1441H.
_IR_IN_FORCE = "2020-04-24"
#: Publication on 2026-09-04 plus 120 days, as the summaries compute it; not confirmed by the ministry.
_NEW_LAW_IN_FORCE = "2027-01-02"


def _law(value: Any, article: str, note: str) -> dict[str, Any]:
    """A figure of the 2019 law; its commencement was not read, so the date is not established."""
    return {
        "value": value,
        "statute_reference": f"Government Tenders and Procurement Law 2019 (Royal Decree M/128), {article}",
        "source_url": _LAW_URL,
        "read_date": _READ,
        "effective_date": None,
        "note": note,
    }


def _ir(value: Any, article: str, note: str) -> dict[str, Any]:
    """A figure of the 2019 Implementing Regulations, in force since 2020-04-24."""
    return {
        "value": value,
        "statute_reference": f"Implementing Regulations of the Government Tenders and Procurement Law, {article}",
        "source_url": _IR_URL,
        "read_date": _READ,
        "effective_date": _IR_IN_FORCE,
        "note": note,
    }


def _new(value: Any, url: str, note: str) -> dict[str, Any]:
    """A figure of the new law as a law-firm summary reports it; never enforced."""
    return {
        "value": value,
        "statute_reference": "Government Tenders and Procurement Law 2026 (Royal Decree M/76), as summarised",
        "source_url": url,
        "read_date": _READ,
        "effective_date": _NEW_LAW_IN_FORCE,
        "note": note,
        "needs_expert_review": True,
    }


_PAYMENT_CYCLE = (
    "No calendar figure: the consultant has 10 working days, the agency 15 to issue the payment order and the "
    "Ministry of Finance 45 to pay, 70 working days in all (IR Art. 109). The payment clock regime "
    "sa_gtpl_ir109 counts them."
)

GTPL_2019: dict[str, Any] = {
    "regime": "sa_gtpl_2019",
    "law": (
        "Government Tenders and Procurement Law (Royal Decree M/128 of 2019); Implementing Regulations, "
        "Ministerial Resolution 1242/1441 as amended by Resolution 3479"
    ),
    "tender_date_from": None,
    "tender_date_to": "2027-01-01",
    "confidence": "confirmed",
    "bid_security_max_percent": _law(
        "2",
        "Arts. 41 and 42",
        "The initial guarantee is one to two percent of the bid value as the tender documents set; a bid "
        "without it is excluded. Direct purchases and local small and medium enterprises are exempt.",
    ),
    "performance_security_percent": _law(
        "5",
        "Art. 61",
        "The final guarantee is five percent of the contract value; more only with the Minister's approval "
        "stated in the tender documents.",
    ),
    "performance_security_due_working_days": _law(
        15,
        "Art. 61",
        "Due within 15 working days of the award notice, extendable once.",
    ),
    "advance_payment_max_percent": _ir(
        "10",
        "Art. 108",
        "Up to ten percent of the contract value, against a bank guarantee of the same amount, recovered from "
        "each invoice from the first at the same percentage. None on extensions or additional works.",
    ),
    "advance_payment_max_percent_sme": _ir(
        None,
        "Art. 108",
        "The regulations read set no separate advance payment cap for small and medium enterprises.",
    ),
    "interim_payment_percent": _ir(
        None,
        "Art. 111",
        "No fixed share: the agency may deduct up to ten percent of each invoice until the final invoice is "
        "built, so an interim pays at least ninety percent of the invoice until then.",
    ),
    "retention_percent": _ir(
        "10",
        "Art. 111(1)",
        "Up to ten percent of each invoice is deducted to build the final invoice, paid on initial delivery "
        "against the completion, zakat and tax, and social insurance (GOSI) certificates.",
    ),
    "stored_materials_payment_percent": _ir(
        None,
        "Arts. 108 to 111",
        "Not found in the law or the regulations read.",
    ),
    "works_payment_days": _ir(None, "Art. 109", _PAYMENT_CYCLE),
    "supplies_payment_days": _ir(None, "Art. 109", _PAYMENT_CYCLE),
    "variation_max_percent_per_item_works": _law(
        None,
        "Art. 69",
        "The law limits variations on the contract value, not per item: see the increase and decrease limits.",
    ),
    "variation_max_percent_per_item_other": _law(
        None,
        "Art. 69",
        "The law limits variations on the contract value, not per item: see the increase and decrease limits.",
    ),
    "variation_max_increase_percent_of_contract": _law(
        "10",
        "Art. 69",
        "Change orders may increase the contract's obligations by up to ten percent of its value.",
    ),
    "variation_max_decrease_percent_of_contract": _law(
        "20",
        "Art. 69",
        "Change orders may decrease the contract's obligations by up to twenty percent of its value.",
    ),
    "final_invoice_percent_other_contracts": _ir(
        "5",
        "Art. 111(2)",
        "The final invoice is not less than five percent of the value of contracts other than general construction.",
    ),
    "delay_damages_cap_percent_works": _law(
        "20",
        "Art. 72",
        "Delay penalties on contracts other than supply, works among them, may total at most twenty percent "
        "of the contract value; more only with the Minister's prior approval disclosed to bidders.",
    ),
    "delay_damages_cap_percent_works_long_delay": _law(
        "20",
        "Art. 72",
        "The law has no higher step for a long delay; the twenty percent cap holds throughout.",
    ),
    "delay_damages_cap_percent_other": _law(
        "6",
        "Art. 72",
        "On supply contracts, delay penalties may total at most six percent of the contract value.",
    ),
    "delay_damages_cap_percent_other_long_delay": _law(
        "6",
        "Art. 72",
        "The law has no higher step for a long delay; the six percent cap on supply holds throughout.",
    ),
    "delay_damages_long_delay_threshold_percent": _law(
        None,
        "Art. 72",
        "The law has no long-delay step, so there is no threshold.",
    ),
    "price_adjustment_min_duration_months": _ir(
        None,
        "Art. 113",
        "No minimum duration: price adjustment is a threshold test on listed materials (trigger sa_gtpl_ir113), "
        "not an index formula every contract of a length must carry.",
    ),
}

GTPL_2026: dict[str, Any] = {
    "regime": "sa_gtpl_2026",
    "law": (
        "Government Tenders and Procurement Law (Royal Decree M/76 of 27/2/1448H, published 2026-09-04); "
        "implementing regulations not yet issued"
    ),
    "tender_date_from": _NEW_LAW_IN_FORCE,
    "tender_date_to": None,
    "confidence": "needs_expert_review",
    "bid_security_max_percent": _new(
        "2",
        _IMHORA_URL,
        "One to two percent of the bid value as before, with bids valid for 90 working days.",
    ),
    "performance_security_percent": _new(
        "5",
        _IMHORA_URL,
        "Five percent within 15 working days as before; reportedly not required for contracts up to SAR 300,000.",
    ),
    "performance_security_due_working_days": _new(15, _IMHORA_URL, "Reported unchanged at 15 working days."),
    "advance_payment_max_percent": _new(
        None,
        _IMHORA_URL,
        "Not reported; the new regulations will set it.",
    ),
    "advance_payment_max_percent_sme": _new(None, _IMHORA_URL, "Not reported."),
    "interim_payment_percent": _new(None, _IMHORA_URL, "Not reported; the new regulations will set it."),
    "retention_percent": _new(None, _IMHORA_URL, "Not reported; the new regulations will set it."),
    "stored_materials_payment_percent": _new(None, _IMHORA_URL, "Not reported."),
    "works_payment_days": _new(None, _IMHORA_URL, "Not reported; the new regulations will set the payment cycle."),
    "supplies_payment_days": _new(None, _IMHORA_URL, "Not reported."),
    "variation_max_percent_per_item_works": _new(
        "20",
        _IMHORA_URL,
        "Existing items may reportedly be varied by up to twenty percent either way, new items up to ten.",
    ),
    "variation_max_percent_per_item_other": _new(
        "20",
        _IMHORA_URL,
        "Reported as for works: existing items up to twenty percent either way.",
    ),
    "variation_max_increase_percent_of_contract": _new(
        "20",
        _GT_URL,
        "The total increase by change orders is reportedly raised from ten to twenty percent of the value.",
    ),
    "variation_max_decrease_percent_of_contract": _new(
        "20",
        _IMHORA_URL,
        "Reported unchanged at twenty percent.",
    ),
    "delay_damages_cap_percent_works": _new(
        "15",
        _SHURA_URL,
        "The cap on contracts other than supply is reportedly lowered from twenty to fifteen percent.",
    ),
    "delay_damages_cap_percent_works_long_delay": _new(
        "15",
        _SHURA_URL,
        "No long-delay step is reported; fifteen percent throughout.",
    ),
    "delay_damages_cap_percent_other": _new("6", _SHURA_URL, "Supply contracts reportedly stay at six percent."),
    "delay_damages_cap_percent_other_long_delay": _new("6", _SHURA_URL, "No long-delay step is reported."),
    "delay_damages_long_delay_threshold_percent": _new(None, _SHURA_URL, "No long-delay step is reported."),
    "price_adjustment_min_duration_months": _new(
        None,
        _IMHORA_URL,
        "Price adjustment is reportedly limited to key materials and services, duties, fees and taxes, and "
        "unforeseeable physical difficulties; no minimum duration is reported.",
    ),
}

REGIMES: list[dict[str, Any]] = [GTPL_2019, GTPL_2026]

__all__ = ["GTPL_2019", "GTPL_2026", "REGIMES"]

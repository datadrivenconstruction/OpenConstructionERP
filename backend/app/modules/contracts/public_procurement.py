# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory limits on public works contracts, per country. Data, not branches.

A public procurement law sets numbers a public works contract may not cross:
how much retention, how large an advance payment, how high the delay damages
may run, how much performance security the contractor must post. This module
writes those numbers down once per country, each with the article it comes
from, and the ``contracts`` rule set reads them
(:class:`app.modules.contracts.validators.PublicWorksLimitsRule`). The rules
stay silent unless the project's country has a row here and the project
records its works as ``public``: a private contract agrees its own figures.

Rules this table keeps, the same as :mod:`app.modules.contracts.country_defaults`:

* **No country, no limits.** A country without a row is never measured
  against another country's law.
* **Every figure says where it came from.** ``statute_reference`` names the
  article, ``source_url`` the text that was read, ``read_date`` when, and
  ``effective_date`` the commencement, or ``None`` where it was not
  established from a primary text.
* **What could not be confirmed is data, not a rule.** A figure whose
  ``needs_expert_review`` is true is shown and never enforced; a value that
  was not found at all is ``None`` and the note says why.

The module also carries two reference tables that no rule enforces yet:
contractor classification grades (:data:`CONTRACTOR_CLASSIFICATIONS`) and the
way social insurance is assessed on construction contracts
(:data:`CONTRACTING_SOCIAL_INSURANCE`). Both are flagged for expert review.

Pure data and pure helpers; no ORM, no I/O.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

#: The consolidated English translation of Egypt's Public Contracts Law
#: 182/2018 with its Executive Regulations (Decree 692/2019), Andersen Egypt,
#: January 2026. Every Egyptian limit below was read in it on 2026-10-19.
_EG_LAW_182_URL = "https://eg.andersen.com/wp-content/uploads/2026/01/Law-No.-182-of-2018.pdf"
_EG_READ_DATE = "2026-10-19"

#: The figures a country row carries. A figure is a dict with ``value`` (a
#: decimal string, a whole number, or ``None``), ``statute_reference``,
#: ``source_url``, ``read_date``, ``effective_date`` and ``note``.
LIMIT_FIELDS: tuple[str, ...] = (
    "bid_security_max_percent",
    "performance_security_percent",
    "performance_security_due_working_days",
    "advance_payment_max_percent",
    "advance_payment_max_percent_sme",
    "interim_payment_percent",
    "retention_percent",
    "stored_materials_payment_percent",
    "works_payment_days",
    "supplies_payment_days",
    "variation_max_percent_per_item_works",
    "variation_max_percent_per_item_other",
    "delay_damages_cap_percent_works",
    "delay_damages_cap_percent_works_long_delay",
    "delay_damages_cap_percent_other",
    "delay_damages_cap_percent_other_long_delay",
    "delay_damages_long_delay_threshold_percent",
    "price_adjustment_min_duration_months",
)

#: Figures a row may carry when its law has them. A row that names one is
#: checked like any other figure; a row without one simply has no such tier.
#: France brought the SME tiers of retention and advance under décret
#: 2024-1251, the CCAG-Travaux daily penalty and its waiver; Saudi Arabia the
#: variation caps and the final invoice share that Egypt's law does not set.
OPTIONAL_LIMIT_FIELDS: tuple[str, ...] = (
    "retention_percent_sme",
    "advance_payment_min_percent",
    "advance_payment_min_percent_sme",
    "advance_payment_min_percent_sme_large_body",
    "delay_damages_daily_divisor",
    "delay_damages_waiver_amount",
    "variation_max_increase_percent_of_contract",
    "variation_max_decrease_percent_of_contract",
    "final_invoice_percent_other_contracts",
)

#: The kinds of public buyer a contract may record in ``terms["public_buyer_category"]``.
#: ``state`` is the State itself; ``large_public_body`` a public body the
#: country's law treats like it for SME protection (in France the State's
#: administrative public establishments and local authorities spending more
#: than EUR 60 million a year); ``other`` everyone else.
PUBLIC_BUYER_CATEGORIES: tuple[str, ...] = ("state", "large_public_body", "other")

_FIGURE_KEYS = frozenset({"value", "statute_reference", "source_url", "read_date", "effective_date", "note"})
#: A figure may also say it ``needs_expert_review``: it is shown and never
#: enforced, because :func:`limit_value` answers ``None`` for it.
_OPTIONAL_FIGURE_KEYS = frozenset({"needs_expert_review"})

#: The keys a dated regime carries besides its figures.
_REGIME_KEYS = frozenset({"regime", "law", "tender_date_from", "tender_date_to", "confidence"})
_CONFIDENCE = ("confirmed", "needs_expert_review")


def _eg(value: Any, reference: str, note: str) -> dict[str, Any]:
    return {
        "value": value,
        "statute_reference": reference,
        "source_url": _EG_LAW_182_URL,
        "read_date": _EG_READ_DATE,
        # The commencement of Law 182/2018 and of Decree 692/2019 was not read
        # in a primary text; None is the answer "not established", not "always".
        "effective_date": None,
        "note": note,
    }


#: The table, keyed by ISO 3166-1 alpha-2.
PUBLIC_WORKS_LIMITS: dict[str, dict[str, Any]] = {
    "EG": {
        "law": "Public Contracts Law No. 182 of 2018; Executive Regulations, Minister of Finance Decree 692/2019",
        "bid_security_max_percent": _eg(
            "1.5",
            "Law 182/2018, Art. 16",
            "The provisional guarantee on works, supplies, services and consultancy may not exceed 1.5 percent of "
            "the estimated value (0.5 percent for buying or leasing immovables).",
        ),
        "performance_security_percent": _eg(
            "5",
            "Law 182/2018, Art. 40",
            "The final guarantee is five percent of the contract value, returned within ten working days after "
            "the warranty period ends.",
        ),
        "performance_security_due_working_days": _eg(
            10,
            "Law 182/2018, Art. 40",
            "Due within ten working days of the notice of award (twenty for a contractor abroad), with up to ten "
            "more on the approval of the competent authority.",
        ),
        "advance_payment_max_percent": _eg(
            "25",
            "Law 182/2018, Art. 44; Executive Regulations, Art. 92",
            "Up to 25 percent of the contract value, against an unconditional bank guarantee of the same value "
            "and currency, recovered pro rata from the payments. Higher only with the Minister of Finance's "
            "approval before tendering.",
        ),
        "advance_payment_max_percent_sme": _eg(
            "50",
            "Executive Regulations, Art. 92",
            "Up to 50 percent of the contract value where the contractor is a micro, small or medium enterprise.",
        ),
        "interim_payment_percent": _eg(
            "95",
            "Executive Regulations, Art. 93",
            "Interim payments pay 95 percent of the scheduled value of work actually executed.",
        ),
        "retention_percent": _eg(
            "5",
            "Executive Regulations, Art. 93",
            "The five percent not paid on each interim is held until provisional acceptance, or paid against a "
            "bank guarantee that expires 30 days after it.",
        ),
        "stored_materials_payment_percent": _eg(
            "75",
            "Executive Regulations, Art. 93",
            "Approved materials properly stored on site for the permanent works are paid at 75 percent of their "
            "scheduled value until installed.",
        ),
        "works_payment_days": _eg(
            60,
            "Law 182/2018, Art. 45; Executive Regulations, Art. 93",
            "Interim payments on works within 60 days of the payment certificate being submitted.",
        ),
        "supplies_payment_days": _eg(
            30,
            "Law 182/2018, Art. 45; Executive Regulations, Art. 93",
            "Supplies and services within 30 days of inspection, acceptance and approval.",
        ),
        "variation_max_percent_per_item_works": _eg(
            "25",
            "Law 182/2018, Art. 46; Executive Regulations, Art. 96",
            "The quantity of each item of a works contract may be increased or decreased by up to 25 percent "
            "at the same prices, within the contract term and with the competent authority's approval.",
        ),
        "variation_max_percent_per_item_other": _eg(
            "15",
            "Law 182/2018, Art. 46; Executive Regulations, Art. 96",
            "Up to 15 percent of each item's quantity in contracts other than works.",
        ),
        "delay_damages_cap_percent_works": _eg(
            "10",
            "Law 182/2018, Art. 48; Executive Regulations, Art. 98",
            "On works, delay damages may total at most ten percent of the contract value while the delay is no "
            "longer than ten percent of the execution period.",
        ),
        "delay_damages_cap_percent_works_long_delay": _eg(
            "15",
            "Law 182/2018, Art. 48; Executive Regulations, Art. 98",
            "Fifteen percent once the delay exceeds ten percent of the execution period. Damages fall on the "
            "delayed part only, unless it prevents beneficial use of the rest.",
        ),
        "delay_damages_cap_percent_other": _eg(
            "3",
            "Law 182/2018, Art. 48; Executive Regulations, Art. 98",
            "On other contracts, at most three percent while the delay is no longer than ten percent of the term.",
        ),
        "delay_damages_cap_percent_other_long_delay": _eg(
            "5",
            "Law 182/2018, Art. 48",
            "Five percent once the delay exceeds ten percent of the contract term.",
        ),
        "delay_damages_long_delay_threshold_percent": _eg(
            "10",
            "Law 182/2018, Art. 48",
            "The delay, as a share of the execution period, above which the higher cap applies.",
        ),
        "price_adjustment_min_duration_months": _eg(
            6,
            "Law 182/2018, Art. 47; Executive Regulations, Art. 97",
            "Works contracts of six months or more adjust their value every three contractual months by the "
            "CAPMAS producer price index; the contractor's coefficients are part of the bid and any agreement "
            "to the contrary is void.",
        ),
    },
}

#: France: the Code de la commande publique as consolidated on Légifrance,
#: read through the research brief of 2026-10-19 (docs/design/france/core.md).
_FR_CCP_URL = "https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000037701019"
_FR_CCAG_URL = "https://www.economie.gouv.fr/daj/cahiers-clauses-administratives-generales-et-techniques"
_FR_READ_DATE = "2026-10-19"


def _fr(value: Any, reference: str, note: str, *, effective: str | None, url: str = _FR_CCP_URL) -> dict[str, Any]:
    return {
        "value": value,
        "statute_reference": reference,
        "source_url": url,
        "read_date": _FR_READ_DATE,
        "effective_date": effective,
        "note": note,
    }


def _fr_none(field: str, note: str) -> dict[str, Any]:
    return _fr(None, "Code de la commande publique", f"{field}: {note}", effective=None)


PUBLIC_WORKS_LIMITS["FR"] = {
    "law": "Code de la commande publique; CCAG-Travaux 2021 (arrêté du 30 mars 2021)",
    # A general condition the special conditions (CCAP) may change, provided
    # the change is listed among its derogations. A finding on one of these
    # is a warning to check that list, never a block.
    "derogable_fields": ["advance_payment_max_percent", "delay_damages_cap_percent_works_long_delay"],
    "bid_security_max_percent": _fr_none("bid security", "French procedures ask for no bid security."),
    "performance_security_percent": _fr_none(
        "performance security",
        "No statutory performance security; a buyer may ask for a first-demand guarantee instead of retention.",
    ),
    "performance_security_due_working_days": _fr_none("performance security", "Not set by the Code."),
    "advance_payment_max_percent": _fr(
        "30",
        "Code de la commande publique, art. R2191-7 (décret 2024-1251)",
        "The advance is set between 5 and 30 percent of the initial amount including tax (of twelve months' "
        "worth on contracts longer than a year). A higher rate against a first-demand guarantee was not "
        "confirmed in the text read, so a rate above 30 percent is a warning to check the CCAP.",
        effective="2025-01-01",
    ),
    "advance_payment_max_percent_sme": _fr_none(
        "SME advance maximum", "The Code sets SME minimums, not a separate SME maximum."
    ),
    "advance_payment_min_percent": _fr(
        "5",
        "Code de la commande publique, art. R2191-7",
        "The advance may not be below five percent. A contractor may renounce it, recorded as zero. When it "
        "is owed at all (above EUR 50,000 excluding tax and two months, R2191-3) was not confirmed in the "
        "text read, so a contract without an advance is not reported.",
        effective="2019-04-01",
    ),
    "advance_payment_min_percent_sme": _fr(
        "30",
        "Code de la commande publique, art. R2191-7 (décret 2024-1251)",
        "At least 30 percent when the holder or a subcontractor paid directly is an SME and the buyer is the State.",
        effective="2025-01-01",
    ),
    "advance_payment_min_percent_sme_large_body": _fr(
        "10",
        "Code de la commande publique, art. R2191-7 (décret 2024-1251)",
        "At least 10 percent for an SME when the buyer is a State administrative public establishment or a "
        "local authority whose operating expenses exceed EUR 60 million.",
        effective="2025-01-01",
    ),
    "interim_payment_percent": _fr_none("interim payment", "Instalments pay the work done; no percentage is set."),
    "retention_percent": _fr(
        "5",
        "Code de la commande publique, art. R2191-32 and R2191-33",
        "The retenue de garantie may not exceed five percent of the initial amount including modifications, "
        "and may be replaced by a first-demand guarantee or, with the buyer's consent, a caution.",
        effective="2019-04-01",
    ),
    "retention_percent_sme": _fr(
        "3",
        "Code de la commande publique, art. R2191-32 to R2191-36 (décret 2024-1251)",
        "Three percent where the holder is an SME and the buyer is the State, a State administrative public "
        "establishment or a local authority spending more than EUR 60 million a year, for procedures launched "
        "from 1 January 2025.",
        effective="2025-01-01",
    ),
    "stored_materials_payment_percent": _fr_none("stored materials", "Not read in the Code for this pass."),
    "works_payment_days": _fr(
        30,
        "Code de la commande publique, art. R2192-10",
        "The State and local authorities pay within 30 days; the payment clocks carry the 50 and 60 day buyers.",
        effective="2019-04-01",
    ),
    "supplies_payment_days": _fr(
        30,
        "Code de la commande publique, art. R2192-10",
        "The same 30 days apply to supplies and services.",
        effective="2019-04-01",
    ),
    "variation_max_percent_per_item_works": _fr_none(
        "variation per item", "Modifications are capped on the contract as a whole (R2194-8), not per item."
    ),
    "variation_max_percent_per_item_other": _fr_none(
        "variation per item", "Modifications are capped on the contract as a whole (R2194-8), not per item."
    ),
    "delay_damages_cap_percent_works": _fr(
        "10",
        "CCAG-Travaux 2021, art. 19.2.2",
        "Penalties for delay may total at most ten percent of the amount excluding tax of the contract, "
        "tranche or order, unless the CCAP derogates.",
        effective="2021-04-01",
        url=_FR_CCAG_URL,
    ),
    "delay_damages_cap_percent_works_long_delay": _fr(
        "10",
        "CCAG-Travaux 2021, art. 19.2.2",
        "The CCAG sets one cap however long the delay, so the long-delay cap is the same ten percent.",
        effective="2021-04-01",
        url=_FR_CCAG_URL,
    ),
    "delay_damages_cap_percent_other": _fr_none(
        "delay damages on other contracts", "Supplies and services follow other CCAGs, not read for this pass."
    ),
    "delay_damages_cap_percent_other_long_delay": _fr_none(
        "delay damages on other contracts", "Supplies and services follow other CCAGs, not read for this pass."
    ),
    "delay_damages_long_delay_threshold_percent": _fr_none(
        "long delay threshold", "The CCAG-Travaux has no second tier."
    ),
    "delay_damages_daily_divisor": _fr(
        3000,
        "CCAG-Travaux 2021, art. 19.2.3",
        "Per calendar day of delay, one three-thousandth of the amount excluding tax of the contract, tranche "
        "or order concerned.",
        effective="2021-04-01",
        url=_FR_CCAG_URL,
    ),
    "delay_damages_waiver_amount": _fr(
        1000,
        "CCAG-Travaux 2021, art. 19.2.1",
        "Penalties whose total does not exceed EUR 1,000 excluding tax for the whole contract are not applied.",
        effective="2021-04-01",
        url=_FR_CCAG_URL,
    ),
    "price_adjustment_min_duration_months": _fr(
        3,
        "Code de la commande publique, art. R2112-13 and R2112-14",
        "A contract longer than three months whose costs depend substantially on raw materials must carry a "
        "revision clause with at least one official index. Whether the raw-material share is significant is a "
        "judgement, so a missing clause is a warning.",
        effective="2019-04-01",
    ),
}


_PK_SBD_URL = (
    "https://www.pkha.gov.pk/downloads/Other%20Doc/"
    "Standard%20Bidding%20Documents%20for%20Procurement%20of%20Works%20(Large%20Procurements).pdf"
)
_PK_READ_DATE = "2026-10-23"


def _pk(value: Any, reference: str, note: str) -> dict[str, Any]:
    """A Pakistani figure, always flagged for review and so shown, never enforced.

    The values are entries of the Standard Bidding Documents for Procurement of Works (large contracts,
    2015 edition, harmonized with the Pakistan Engineering Council and the provincial procurement rules).
    They are the form's defaults, which a procuring entity may change in the Appendix to Bid, and not
    limits the Public Procurement Rules 2004 set; the Rules themselves were not read.
    """
    return {
        "value": value,
        "statute_reference": reference,
        "source_url": _PK_SBD_URL,
        "read_date": _PK_READ_DATE,
        "effective_date": "2015-01-01",
        "needs_expert_review": True,
        "note": note,
    }


def _pk_none(field: str, note: str) -> dict[str, Any]:
    return _pk(None, "Standard Bidding Documents for Procurement of Works", f"{field}: {note}")


PUBLIC_WORKS_LIMITS["PK"] = {
    "law": (
        "Public Procurement Rules 2004 (PPRA) and the provincial rules, with the Pakistan Engineering Council "
        "Standard Bidding Documents for Works"
    ),
    "bid_security_max_percent": _pk_none(
        "bid security",
        "The form advises about 1 percent of the estimated cost for large contracts and up to 3 percent for small "
        "ones (Instructions to Bidders 15.1). It is guidance, not a ceiling; the rule that caps it was not read.",
    ),
    "performance_security_percent": _pk(
        "10",
        "Appendix-A to Bid, item 2 (Conditions of Contract 10.1)",
        "Ten percent of the Contract Price in the Letter of Acceptance, commonly a bank guarantee.",
    ),
    "performance_security_due_working_days": _pk_none(
        "performance security due", "The Appendix states the period; no number of working days was read."
    ),
    "advance_payment_max_percent": _pk(
        "15",
        "Appendix-B to Bid, Alternative One (Conditions of Contract 60.12)",
        "An interest-free Mobilization Advance of up to 15 percent of the Contract Price, in two equal parts "
        "against a Mobilization Advance Guarantee from a scheduled bank. Alternative Two pays mobilization as a "
        "bill item of at most 10 percent of the Tender Price.",
    ),
    "advance_payment_max_percent_sme": _pk_none("SME advance", "The form has no separate advance for small firms."),
    "interim_payment_percent": _pk_none("interim payment", "An interim payment is the work measured less retention."),
    "retention_percent": _pk(
        "10",
        "Appendix-A to Bid, item 9 (Conditions of Contract 60.2)",
        "Ten percent of each Interim Payment Certificate, held until the total reaches 5 percent of the Contract "
        "Price (item 10).",
    ),
    "stored_materials_payment_percent": _pk(
        "75",
        "Conditions of Contract 60.11 (a)(6)",
        "A secured advance on non-perishable materials on site, against an indemnity bond, of at most 75 percent "
        "of the landed cost, the ex-factory price or the market price.",
    ),
    "works_payment_days": _pk(
        28,
        "Appendix-A to Bid, item 12 (Conditions of Contract 60.10)",
        "Payment within 28 days of the Engineer's Interim Payment Certificate in local currency (42 days for "
        "foreign funded projects). A provincial edition counts 30 days after joint verification instead.",
    ),
    "supplies_payment_days": _pk_none("supplies payment", "The works form does not cover supplies."),
    "variation_max_percent_per_item_works": _pk_none(
        "variation per item", "No per-item limit was read; an emergency variation is capped at 2 percent (item 1)."
    ),
    "variation_max_percent_per_item_other": _pk_none("variation per item", "No entry in the works form."),
    "delay_damages_cap_percent_works": _pk(
        "10",
        "Appendix-A to Bid, item 7(a) (Conditions of Contract 47.1)",
        "Liquidated damages at a daily rate the entity states, capped at 10 percent of the Contract Price. The "
        "bonus for early completion is capped at 5 percent (item 7(b)).",
    ),
    "delay_damages_cap_percent_works_long_delay": _pk_none("delay damages second tier", "The form has none."),
    "delay_damages_cap_percent_other": _pk_none("delay damages, other contracts", "No entry in the works form."),
    "delay_damages_cap_percent_other_long_delay": _pk_none("delay damages second tier", "The form has none."),
    "delay_damages_long_delay_threshold_percent": _pk_none("delay damages threshold", "The form has no second tier."),
    "price_adjustment_min_duration_months": _pk_none(
        "price adjustment minimum duration",
        "Clause 70 applies where Appendix-C to Bid is filled in; the form states no minimum duration.",
    ),
}
#: Countries whose public works law changed: a list of regimes per country,
#: each bounded by the dates its tenders were floated (``tender_date_from`` and
#: ``tender_date_to``, inclusive ISO dates or ``None`` for open). The law in
#: force when the tender was floated keeps governing the contract. A regime
#: carries ``regime`` (its code), ``law``, ``confidence`` and the figures of
#: :data:`LIMIT_FIELDS`; a regime known from secondary sources only marks every
#: figure ``needs_expert_review``. A country lives in this table or in
#: :data:`PUBLIC_WORKS_LIMITS`, never in both.
PUBLIC_WORKS_LIMIT_REGIMES: dict[str, list[dict[str, Any]]] = {}


def _register_dated_regimes() -> None:
    # Imported here so the country file stays a plain data module.
    from app.modules.contracts import public_procurement_sa  # noqa: PLC0415

    PUBLIC_WORKS_LIMIT_REGIMES["SA"] = public_procurement_sa.REGIMES


_register_dated_regimes()

#: The price adjustment regime each country's public works use, a code of
#: :data:`app.modules.contracts.price_adjustment.PRICE_ADJUSTMENT_REGIMES`.
PUBLIC_WORKS_PRICE_ADJUSTMENT: dict[str, str] = {
    "EG": "eg_law182_art97",
    "FR": "fr_ccag_travaux_2021_art_10_5",
    "PK": "pk_pec_sbd_clause_70",
}

#: The INSEE construction cost indices a French revision formula names (base
#: 2010, monthly, published provisional and then definitive). Names only:
#: the INSEE series identifiers were not confirmed, and index values belong to
#: the tenant's ``price_index`` series, never to the platform.
FR_REVISION_INDICES: tuple[dict[str, Any], ...] = tuple(
    {
        "code": code,
        "name": name,
        "family": family,
        "base": "2010",
        "publisher": "INSEE",
        "source_url": "https://www.insee.fr/fr/metadonnees/source/fichier/MET_BT_TP_BASE_2010_FR.pdf",
        "insee_series_id": None,
        "needs_expert_review": True,
    }
    for code, name, family in (
        ("BT01", "Building, all trades", "BT"),
        ("TP01", "Public works, general index", "TP"),
    )
)


# ── Reference data, not enforced ─────────────────────────────────────────

#: Contractor classification grades. Egypt: the Egyptian Federation for
#: Construction and Building Contractors (EFCBC) classifies contractors in
#: grades 1 (highest) to 7, and the grade caps the value of a project the
#: contractor may take. The value limits are set by Minister of Housing
#: decrees (162/2013, amended 73/2017, tables replaced by 412/2017 and then by
#: 439/2022) that were not read, so every limit is ``None`` and the table is
#: flagged for review. The grades themselves are commonly cited (medium
#: confidence). Law 182/2018 Art. 1 defines works contracting by this
#: classification.
CONTRACTOR_CLASSIFICATIONS: dict[str, dict[str, Any]] = {
    "EG": {
        "body": "Egyptian Federation for Construction and Building Contractors (EFCBC)",
        "statute_reference": (
            "Law 182/2018, Art. 1 (definition of works contracting); Minister of Housing Decree 162/2013 as "
            "amended, tables last replaced by Decree 439/2022"
        ),
        "source_url": _EG_LAW_182_URL,
        "read_date": _EG_READ_DATE,
        "effective_date": None,
        "needs_expert_review": True,
        "review_reason": "The value limit of each grade (Decree 439/2022) was not read in a primary text.",
        "grades": [{"grade": str(grade), "max_project_value": None, "currency": "EGP"} for grade in range(1, 8)],
    },
}

#: How social insurance is assessed on a construction contract. Egypt: the
#: employer's share is assessed not on payroll but on a deemed wage, the
#: contract or certificate value times a percentage by type of work (Table 8
#: of MoSS Decree 152/2019, Arts. 199 to 201), and each interim and the final
#: payment wait for a certificate that the dues are paid (Art. 206(3)). The
#: research found the Table 8 percentages only in a secondary source and the
#: current contribution multiplier under Law 148/2019 in three disagreeing
#: ones, and could not confirm the decree stands unchanged under Law 148/2019,
#: so no percentage is shipped and the table is flagged for review.
CONTRACTING_SOCIAL_INSURANCE: dict[str, dict[str, Any]] = {
    "EG": {
        "authority": "National Organization for Social Insurance (NOSI)",
        "statute_reference": "Law 148/2019; MoSS Decree 152/2019, Arts. 199 to 206",
        "source_url": "https://ahmedazimelgamel.blogspot.com/2019/08/152-2019.html",
        "read_date": _EG_READ_DATE,
        "effective_date": None,
        "needs_expert_review": True,
        "review_reason": (
            "Table 8 percentages and the contribution multiplier were not confirmed in an official text, and "
            "whether Decree 152/2019 stands unchanged under Law 148/2019 is unconfirmed."
        ),
        "basis": "deemed_wage_percent_of_contract_value",
        "contribution_multiplier_percent": None,
        "wage_percent_by_work_type": [],
        "payment_gate": {
            "certificate_type": "social_security_clearance",
            "applies_to_kinds": ["interim", "final"],
            "statute_reference": "MoSS Decree 152/2019, Art. 206(3)",
        },
        "owner_notice_days_before_start": 3,
    },
}


def _check_figure(country: str, field: str, figure: Any) -> None:
    where = f"{country}.{field}"
    if not isinstance(figure, dict) or not _FIGURE_KEYS <= set(figure) <= _FIGURE_KEYS | _OPTIONAL_FIGURE_KEYS:
        raise ValueError(f"{where} must be a figure with {sorted(_FIGURE_KEYS)}")
    if not isinstance(figure.get("needs_expert_review", False), bool):
        raise ValueError(f"{where}.needs_expert_review must be true or false")
    if not figure["statute_reference"] or not figure["source_url"] or not figure["note"]:
        raise ValueError(f"{where} must name its statute, source and note")
    value = figure["value"]
    if value is None or isinstance(value, int) and not isinstance(value, bool):
        return
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{where} is not a number: {value!r}") from exc
    if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("100"):
        raise ValueError(f"{where} must be a percent between 0 and 100, not {value!r}")


def _validate() -> None:
    for country, row in PUBLIC_WORKS_LIMITS.items():
        if len(country) != 2 or not country.isupper():
            raise ValueError(f"country key {country!r} is not ISO 3166-1 alpha-2")
        if not row.get("law"):
            raise ValueError(f"{country} must name its law")
        for field in LIMIT_FIELDS:
            _check_figure(country, field, row.get(field))
        for field in OPTIONAL_LIMIT_FIELDS:
            if field in row:
                _check_figure(country, field, row[field])
        unknown = set(row) - {"law", "derogable_fields", *LIMIT_FIELDS, *OPTIONAL_LIMIT_FIELDS}
        if unknown:
            raise ValueError(f"{country} names fields the table does not have: {sorted(unknown)}")
        stray = set(row.get("derogable_fields") or ()) - {*LIMIT_FIELDS, *OPTIONAL_LIMIT_FIELDS}
        if stray:
            raise ValueError(f"{country} calls derogable fields the table does not have: {sorted(stray)}")
    for country in PUBLIC_WORKS_PRICE_ADJUSTMENT:
        if country not in PUBLIC_WORKS_LIMITS:
            raise ValueError(f"price adjustment regime for {country!r}, which has no limits row")
    problems = validate_limit_regimes(PUBLIC_WORKS_LIMIT_REGIMES)
    if problems:
        raise ValueError("; ".join(problems))


def _iso(raw: Any) -> date | None:
    return date.fromisoformat(raw) if raw else None


def validate_limit_regimes(table: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Describe everything that makes the dated regimes unsafe to read; empty for a sound table."""
    problems: list[str] = []
    for country, regimes in table.items():
        if len(country) != 2 or not country.isupper():
            problems.append(f"country key {country!r} is not ISO 3166-1 alpha-2")
        if country in PUBLIC_WORKS_LIMITS:
            problems.append(f"{country} has both a single limits row and dated regimes")
        spans: list[tuple[date, date, str]] = []
        for regime in regimes:
            where = f"{country}.{regime.get('regime') or '?'}"
            if not regime.get("regime") or not regime.get("law"):
                problems.append(f"{where} must name its code and its law")
            if regime.get("confidence") not in _CONFIDENCE:
                problems.append(f"{where}.confidence must be one of {_CONFIDENCE}")
            try:
                start = _iso(regime.get("tender_date_from")) or date.min
                end = _iso(regime.get("tender_date_to")) or date.max
            except (TypeError, ValueError):
                problems.append(f"{where} has a tender date that is not an ISO date")
                continue
            if end < start:
                problems.append(f"{where} ends before it starts")
            spans.append((start, end, where))
            for field in (*LIMIT_FIELDS, *(f for f in OPTIONAL_LIMIT_FIELDS if f in regime)):
                try:
                    _check_figure(where, field, regime.get(field))
                except ValueError as exc:
                    problems.append(str(exc))
            if regime.get("confidence") == "needs_expert_review":
                unflagged = [
                    f
                    for f in (*LIMIT_FIELDS, *OPTIONAL_LIMIT_FIELDS)
                    if isinstance(regime.get(f), dict) and not regime[f].get("needs_expert_review")
                ]
                if unflagged:
                    problems.append(f"{where} needs expert review but these figures are not flagged: {unflagged}")
            unknown = set(regime) - _REGIME_KEYS - {*LIMIT_FIELDS, *OPTIONAL_LIMIT_FIELDS}
            if unknown:
                problems.append(f"{where} names fields the table does not have: {sorted(unknown)}")
        spans.sort()
        for (_, first_end, first), (second_start, _, second) in zip(spans, spans[1:], strict=False):
            if second_start <= first_end:
                problems.append(f"{first} and {second} overlap on tender dates")
    return problems


_validate()


def has_public_works_limits(country_code: str | None) -> bool:
    """Whether ``country_code`` has statutory public works limits, in either table."""
    code = (country_code or "").strip().upper()
    return code in PUBLIC_WORKS_LIMITS or code in PUBLIC_WORKS_LIMIT_REGIMES


def public_works_limits(country_code: str | None, tender_date: date | None = None) -> dict[str, Any] | None:
    """The statutory public works limits of ``country_code``, or ``None`` when the table has no row.

    A country with dated regimes answers the regime whose tender dates hold
    ``tender_date``; without a tender date, the regime in force today. A
    country with a single row answers it for any date.

    Returns a copy, so a caller cannot edit the shipped figures.
    """
    code = (country_code or "").strip().upper()
    regimes = PUBLIC_WORKS_LIMIT_REGIMES.get(code)
    if regimes is not None:
        when = tender_date or date.today()
        for regime in regimes:
            start = _iso(regime.get("tender_date_from")) or date.min
            end = _iso(regime.get("tender_date_to")) or date.max
            if start <= when <= end:
                return copy.deepcopy(regime)
        return None
    row = PUBLIC_WORKS_LIMITS.get(code)
    return copy.deepcopy(row) if row is not None else None


def limit_value(limits: dict[str, Any] | None, field: str) -> Decimal | None:
    """One figure of a limits row as a ``Decimal``, or ``None`` when the row or the value is absent."""
    figure = (limits or {}).get(field)
    if not isinstance(figure, dict) or figure.get("value") is None or figure.get("needs_expert_review"):
        return None
    return Decimal(str(figure["value"]))


def limit_value_on(limits: dict[str, Any] | None, field: str, on: date | None) -> Decimal | None:
    """Like :func:`limit_value`, but ``None`` when the figure took effect after ``on``.

    An unknown ``on`` reads the figure in force today. A figure with no
    effective date is read on every date, as the table states for itself.
    """
    value = limit_value(limits, field)
    if value is None or on is None:
        return value
    effective = (limits or {}).get(field, {}).get("effective_date")
    if effective and on < date.fromisoformat(str(effective)):
        return None
    return value


def is_derogable(limits: dict[str, Any] | None, field: str) -> bool:
    """Whether the contract's special conditions may lawfully change ``field``."""
    return field in ((limits or {}).get("derogable_fields") or ())


def delay_damages_amount(country_code: str | None, contract_value: Any, days: int) -> Decimal | None:
    """The delay penalty a country's general conditions charge for ``days`` calendar days.

    Daily rate is the contract value over the row's daily divisor, the total
    is capped at the works cap, and a total at or below the waiver amount is
    not charged at all. ``None`` for a country that sets no daily rate.
    France, CCAG-Travaux 2021 art. 19.2: EUR 900,000 excluding tax late 120
    days owes 36,000.00; late 400 days, the 10 percent cap of 90,000.00.
    """
    limits = public_works_limits(country_code)
    divisor = limit_value(limits, "delay_damages_daily_divisor")
    if divisor is None or divisor <= 0 or days <= 0:
        return None if divisor is None else Decimal("0")
    value = Decimal(str(contract_value))
    amount = value / divisor * Decimal(days)
    cap = limit_value(limits, "delay_damages_cap_percent_works")
    if cap is not None:
        amount = min(amount, value * cap / Decimal("100"))
    waiver = limit_value(limits, "delay_damages_waiver_amount")
    if waiver is not None and amount <= waiver:
        return Decimal("0")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = [
    "CONTRACTING_SOCIAL_INSURANCE",
    "CONTRACTOR_CLASSIFICATIONS",
    "FR_REVISION_INDICES",
    "LIMIT_FIELDS",
    "OPTIONAL_LIMIT_FIELDS",
    "PUBLIC_BUYER_CATEGORIES",
    "PUBLIC_WORKS_LIMITS",
    "PUBLIC_WORKS_LIMIT_REGIMES",
    "PUBLIC_WORKS_PRICE_ADJUSTMENT",
    "delay_damages_amount",
    "has_public_works_limits",
    "is_derogable",
    "limit_value",
    "limit_value_on",
    "public_works_limits",
    "validate_limit_regimes",
]

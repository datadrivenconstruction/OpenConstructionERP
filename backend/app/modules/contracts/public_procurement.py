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
from decimal import Decimal, InvalidOperation
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

_FIGURE_KEYS = frozenset({"value", "statute_reference", "source_url", "read_date", "effective_date", "note"})


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

#: The price adjustment regime each country's public works use, a code of
#: :data:`app.modules.contracts.price_adjustment.PRICE_ADJUSTMENT_REGIMES`.
PUBLIC_WORKS_PRICE_ADJUSTMENT: dict[str, str] = {"EG": "eg_law182_art97"}


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
    if not isinstance(figure, dict) or set(figure) != _FIGURE_KEYS:
        raise ValueError(f"{where} must be a figure with {sorted(_FIGURE_KEYS)}")
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
        unknown = set(row) - {"law", *LIMIT_FIELDS}
        if unknown:
            raise ValueError(f"{country} names fields the table does not have: {sorted(unknown)}")
    for country in PUBLIC_WORKS_PRICE_ADJUSTMENT:
        if country not in PUBLIC_WORKS_LIMITS:
            raise ValueError(f"price adjustment regime for {country!r}, which has no limits row")


_validate()


def public_works_limits(country_code: str | None) -> dict[str, Any] | None:
    """The statutory public works limits of ``country_code``, or ``None`` when the table has no row.

    Returns a copy, so a caller cannot edit the shipped figures.
    """
    row = PUBLIC_WORKS_LIMITS.get((country_code or "").strip().upper())
    return copy.deepcopy(row) if row is not None else None


def limit_value(limits: dict[str, Any] | None, field: str) -> Decimal | None:
    """One figure of a limits row as a ``Decimal``, or ``None`` when the row or the value is absent."""
    figure = (limits or {}).get(field)
    if not isinstance(figure, dict) or figure.get("value") is None:
        return None
    return Decimal(str(figure["value"]))


__all__ = [
    "CONTRACTING_SOCIAL_INSURANCE",
    "CONTRACTOR_CLASSIFICATIONS",
    "LIMIT_FIELDS",
    "PUBLIC_WORKS_LIMITS",
    "PUBLIC_WORKS_PRICE_ADJUSTMENT",
    "limit_value",
    "public_works_limits",
]

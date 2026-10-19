# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory social insurance contributions on wages, per country. Data, not branches.

What an hour of labour costs a contractor is the wage plus what the law adds
on top of it, and the second part is national: who pays, how much, on which
part of the wage, up to which ceiling. This module writes those rates down
once per country, each row with the article it comes from, the date it takes
effect and whether a person has confirmed it against the primary text.

**The cohort is an input, never a guess.** A country can charge two employees
on the same day two different rates. Saudi Arabia does: the Social Insurance
Law, in force 2024-07-03, put a person insured for the first time on an
annuities schedule that rises every July until 2028, while a person already
insured stays on the legacy rate, and a non-Saudi employee is insured against
occupational hazards only. A caller states the cohort; an unknown cohort
answers ``None`` rather than borrowing another cohort's rate.

**A date either has rows or it does not.** As in
:mod:`app.core.payment_taxes.tables`, a date outside every row of a cohort
answers ``None``. Two rows for one scheme, payer and cohort in force on the
same day are an error in the table, refused by :func:`validate_rows`.

Standard library only; nothing here imports from ``app.modules``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

__all__ = [
    "CONTRIBUTION_ROWS",
    "COHORTS",
    "PAYERS",
    "WAGE_CAPS",
    "ContributionRow",
    "WageCap",
    "contributory_wage",
    "rows_in_force",
    "total_rate",
    "validate_rows",
]

#: Who a contribution is charged to.
PAYERS: tuple[str, ...] = ("employee", "employer")

#: The cohorts a country may distinguish. ``national_legacy`` is a national
#: insured under the rules before a reform, ``national_new_entrant`` one
#: insured for the first time after it, ``non_national`` a foreign employee.
#: A country with no reform uses ``national_legacy`` for its nationals.
COHORTS: tuple[str, ...] = ("national_legacy", "national_new_entrant", "non_national")

_REVIEW_STATUSES: tuple[str, ...] = ("confirmed", "unconfirmed")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class ContributionRow:
    """One statutory contribution rate, valid for a range of dates.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code of the jurisdiction.
        scheme: The branch of insurance, a house key such as ``annuities``.
        scheme_label: The scheme's name as the authority writes it, in English.
        payer: ``employee`` or ``employer``.
        cohort: One of :data:`COHORTS`.
        rate_pct: Percent of the contributory wage.
        effective_from: First day the row applies (inclusive).
        effective_to: Last day the row applies (inclusive), ``None`` for open.
        legal_reference: Law and article the rate comes from.
        source_url: Where the rate was read.
        read_date: ISO date the source was read.
        review_status: ``confirmed`` once read in the primary text.
        needs_expert_review: True where the sources disagree or the figure is
            secondary only; the rate still resolves and the flag travels with it.
        note: One sentence a person reads beside the figure.
    """

    country_code: str
    scheme: str
    scheme_label: str
    payer: Literal["employee", "employer"]
    cohort: Literal["national_legacy", "national_new_entrant", "non_national"]
    rate_pct: Decimal
    effective_from: date
    effective_to: date | None
    legal_reference: str
    source_url: str
    read_date: str
    review_status: Literal["confirmed", "unconfirmed"]
    needs_expert_review: bool = False
    note: str = ""


@dataclass(frozen=True)
class WageCap:
    """The most of a monthly wage contributions are charged on."""

    country_code: str
    amount: Decimal
    currency: str
    wage_definition: str
    effective_from: date
    effective_to: date | None
    legal_reference: str
    source_url: str
    read_date: str


# ── Saudi Arabia ─────────────────────────────────────────────────────────

_SA_READ = "2026-10-19"
_PWC_SA = "https://taxsummaries.pwc.com/saudi-arabia/individual/other-taxes"
_MERCANS_SA = "https://mercans.com/resources/statutory-alerts/saudi-arabia-new-social-security-law-3-july-2025"
#: The day the Social Insurance Law came into force and split the national
#: cohorts. The table speaks from this day; an earlier payroll date is held,
#: because the rates before it were not read for this table.
_SA_LAW_IN_FORCE = date(2024, 7, 3)
_SA_LAW = "Social Insurance Law (Royal Decree M/273 of 1445H), in force 2024-07-03"
_SA_LEGACY_REF = "Social Insurance Law of 1421H and the Unemployment Insurance (SANED) Law of 1435H"


def _sa(
    scheme: str,
    label: str,
    payer: Literal["employee", "employer"],
    cohort: Literal["national_legacy", "national_new_entrant", "non_national"],
    rate: str,
    *,
    start: date = _SA_LAW_IN_FORCE,
    end: date | None = None,
    reference: str = _SA_LEGACY_REF,
    url: str = _PWC_SA,
    review: bool = False,
    note: str = "",
) -> ContributionRow:
    return ContributionRow(
        country_code="SA",
        scheme=scheme,
        scheme_label=label,
        payer=payer,
        cohort=cohort,
        rate_pct=Decimal(rate),
        effective_from=start,
        effective_to=end,
        legal_reference=reference,
        source_url=url,
        read_date=_SA_READ,
        review_status="unconfirmed",
        needs_expert_review=review,
        note=note,
    )


_SA_STEP_NOTE = (
    "The new-entrant annuities rate rises by half a point a side each July from 2025 to 2028. The schedule is "
    "from secondary sources and one of them puts 9.5 percent in July 2026 rather than July 2025; the day within "
    "July is not confirmed either. Check gosi.gov.sa before relying on a July boundary."
)


def _sa_new_entrant_annuities() -> list[ContributionRow]:
    steps = [
        ("9", _SA_LAW_IN_FORCE, date(2025, 6, 30), False),
        ("9.5", date(2025, 7, 1), date(2026, 6, 30), True),
        ("10", date(2026, 7, 1), date(2027, 6, 30), True),
        ("10.5", date(2027, 7, 1), date(2028, 6, 30), True),
        ("11", date(2028, 7, 1), None, True),
    ]
    return [
        _sa(
            "annuities",
            "Annuities (pensions)",
            payer,  # type: ignore[arg-type]
            "national_new_entrant",
            rate,
            start=start,
            end=end,
            reference=_SA_LAW,
            url=_MERCANS_SA,
            review=review,
            note=_SA_STEP_NOTE if review else "",
        )
        for rate, start, end, review in steps
        for payer in PAYERS
    ]


_SA_ROWS: tuple[ContributionRow, ...] = (
    # Saudi nationals insured before the Social Insurance Law: annuities 9 + 9,
    # SANED 0.75 + 0.75, occupational hazards 2 on the employer, so 9.75 from
    # the employee and 11.75 from the employer (PwC).
    _sa("annuities", "Annuities (pensions)", "employee", "national_legacy", "9"),
    _sa("annuities", "Annuities (pensions)", "employer", "national_legacy", "9"),
    _sa("unemployment", "Unemployment insurance (SANED)", "employee", "national_legacy", "0.75"),
    _sa("unemployment", "Unemployment insurance (SANED)", "employer", "national_legacy", "0.75"),
    _sa("occupational_hazards", "Occupational hazards", "employer", "national_legacy", "2"),
    # Saudi nationals insured for the first time under the new law: SANED and
    # hazards as before, annuities on the July schedule.
    *_sa_new_entrant_annuities(),
    _sa(
        "unemployment", "Unemployment insurance (SANED)", "employee", "national_new_entrant", "0.75", reference=_SA_LAW
    ),
    _sa(
        "unemployment", "Unemployment insurance (SANED)", "employer", "national_new_entrant", "0.75", reference=_SA_LAW
    ),
    _sa("occupational_hazards", "Occupational hazards", "employer", "national_new_entrant", "2", reference=_SA_LAW),
    # Non-Saudi employees: occupational hazards only, on the employer.
    _sa(
        "occupational_hazards",
        "Occupational hazards",
        "employer",
        "non_national",
        "2",
        note="A non-Saudi employee pays no contribution; the employer insures occupational hazards only.",
    ),
)

#: Every shipped row. A country's rows are a slice of this tuple.
CONTRIBUTION_ROWS: tuple[ContributionRow, ...] = _SA_ROWS

#: Monthly contributory wage ceilings, per country.
WAGE_CAPS: tuple[WageCap, ...] = (
    WageCap(
        country_code="SA",
        amount=Decimal("45000"),
        currency="SAR",
        wage_definition="Basic wage plus housing allowance (and commissions where paid)",
        effective_from=_SA_LAW_IN_FORCE,
        effective_to=None,
        legal_reference=_SA_LEGACY_REF,
        source_url=_PWC_SA,
        read_date=_SA_READ,
    ),
)


# ── Reading ──────────────────────────────────────────────────────────────


def _country(value: str | None) -> str:
    return (value or "").strip().upper()


def _in_force(start: date, end: date | None, on: date) -> bool:
    return start <= on and (end is None or on <= end)


def rows_in_force(
    country: str | None,
    cohort: str,
    on: date,
    rows: Sequence[ContributionRow] = CONTRIBUTION_ROWS,
) -> list[ContributionRow]:
    """The contribution rows of one cohort in force on a date, ordered by scheme and payer."""
    wanted = _country(country)
    found = [
        row
        for row in rows
        if _country(row.country_code) == wanted
        and row.cohort == cohort
        and _in_force(row.effective_from, row.effective_to, on)
    ]
    return sorted(found, key=lambda row: (row.scheme, row.payer))


def total_rate(
    country: str | None,
    cohort: str,
    payer: str,
    on: date,
    rows: Sequence[ContributionRow] = CONTRIBUTION_ROWS,
) -> Decimal | None:
    """The sum of one payer's rates for a cohort on a date.

    Returns:
        The percentage, ``Decimal("0")`` when the cohort has rows on that date
        and none of them is charged to ``payer`` (a non-Saudi employee), and
        ``None`` when the table has no row for the cohort on that date at all.
    """
    in_force = rows_in_force(country, cohort, on, rows)
    if not in_force:
        return None
    return sum((row.rate_pct for row in in_force if row.payer == payer), Decimal("0"))


def contributory_wage(country: str | None, monthly_wage: Decimal, on: date) -> Decimal | None:
    """The part of a monthly wage contributions are charged on, or ``None`` with no cap on file."""
    wanted = _country(country)
    caps = [
        cap for cap in WAGE_CAPS if cap.country_code == wanted and _in_force(cap.effective_from, cap.effective_to, on)
    ]
    if not caps:
        return None
    return min(monthly_wage, caps[0].amount)


def _identity(row: ContributionRow) -> str:
    return f"{_country(row.country_code)}/{row.cohort}/{row.scheme}/{row.payer}"


def validate_rows(rows: Sequence[ContributionRow]) -> list[str]:
    """Describe everything that makes a table unsafe to compute from; empty for a sound one."""
    problems: list[str] = []
    for row in rows:
        where = _identity(row)
        if len(_country(row.country_code)) != 2:
            problems.append(f"{where}: country_code is not ISO 3166-1 alpha-2")
        if row.payer not in PAYERS:
            problems.append(f"{where}: payer {row.payer!r} is not one of {PAYERS}")
        if row.cohort not in COHORTS:
            problems.append(f"{where}: cohort {row.cohort!r} is not one of {COHORTS}")
        if not row.scheme.strip() or not row.scheme_label.strip():
            problems.append(f"{where}: scheme and its label are required")
        if not row.rate_pct.is_finite() or not Decimal("0") <= row.rate_pct <= _HUNDRED:
            problems.append(f"{where}: rate_pct must lie between 0 and 100")
        if row.effective_to is not None and row.effective_to < row.effective_from:
            problems.append(f"{where}: effective_to lies before effective_from")
        if not row.legal_reference.strip():
            problems.append(f"{where}: legal_reference is empty")
        if not row.source_url.startswith("https://"):
            problems.append(f"{where}: source_url must be an https address")
        if row.review_status not in _REVIEW_STATUSES:
            problems.append(f"{where}: review_status {row.review_status!r} is not one of {_REVIEW_STATUSES}")
        if row.needs_expert_review and not row.note.strip():
            problems.append(f"{where}: a row flagged for review must say why in its note")
        try:
            date.fromisoformat(row.read_date)
        except ValueError:
            problems.append(f"{where}: read_date {row.read_date!r} is not an ISO date")
    for index, first in enumerate(rows):
        for second in rows[index + 1 :]:
            if _identity(first) != _identity(second):
                continue
            first_ends = first.effective_to is not None and first.effective_to < second.effective_from
            second_ends = second.effective_to is not None and second.effective_to < first.effective_from
            if not (first_ends or second_ends):
                problems.append(
                    f"{_identity(first)}: effective ranges overlap "
                    f"({first.effective_from.isoformat()} and {second.effective_from.isoformat()})"
                )
    return problems

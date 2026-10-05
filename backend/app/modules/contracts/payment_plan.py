# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment plans tied to schedule milestones: the pure arithmetic.

A contract milestone can follow a schedule milestone. When the work before it
slips, the date the instalment falls due moves with it, and the client sees
the new date rather than the one printed in the contract. This module holds
the parts that need no database: when an instalment is expected to fall due,
how its state reads to a client, and which statutory limits on up-front
payments apply where.

The statutory table is research, not legal advice. Every limit carries its
source, the date it was checked and ``verified=False`` until a lawyer for
that jurisdiction has read it, and the rule that uses it warns rather than
blocks: the person drawing up the contract decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.core.day_basis import add_days

#: Triggers whose date comes from the schedule once the milestone is linked.
SCHEDULE_DRIVEN_TRIGGERS: frozenset[str] = frozenset({"completion", "approval"})

ClientStatus = Literal["upcoming", "due", "invoiced", "paid", "overdue"]

#: The one trigger the schedule moves to reached. ``date`` keeps the day the
#: contract names and ``approval`` waits for a person, whatever the schedule
#: says; both may still follow an activity for their forecast.
SCHEDULE_REACHED_TRIGGER = "completion"

#: ``reached_by`` of an instalment the schedule moved, so a reopened milestone
#: takes back only those and never one a person marked.
REACHED_BY_SCHEDULE = "schedule"

#: What a claim raised from an instalment records as its gross basis.
MILESTONE_GROSS_BASIS = "milestone"

#: Gross bases whose figure did not come from the claim's lines. A line added
#: by hand to such a claim is a breakdown, so the gross is never re-read from
#: the lines: a cost-plus claim keeps its recorded cost, an instalment its
#: agreed amount.
GROSS_FIXED_BASES: frozenset[str] = frozenset({"cost", MILESTONE_GROSS_BASIS})

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")
#: A third of the price, exact: 33.3333 percent would put a deposit of exactly
#: one third a cent over the line.
_ONE_THIRD_PERCENT = _HUNDRED / Decimal(3)


@dataclass(frozen=True)
class Forecast:
    """When an instalment is expected to become claimable, and to be paid."""

    reached: date | None
    due: date | None


def forecast_dates(
    *,
    trigger: str,
    planned_date: date | None,
    activity_finish: date | None,
    reached_on: date | None,
    lag_days: int = 0,
    terms_days: int | None = None,
) -> Forecast:
    """Forecast the dates of one instalment.

    The instalment becomes claimable ``lag_days`` after its milestone, and is
    due ``terms_days`` after that. The milestone date is, in order: the day it
    was actually reached; the live finish of the linked schedule activity, for
    a trigger the schedule drives; the planned date written into the contract.
    A ``date`` trigger ignores the schedule on purpose: the contract fixed
    the day.

    Args:
        trigger: The milestone trigger, ``date``, ``completion`` or ``approval``.
        planned_date: The date the contract names, if any.
        activity_finish: The linked activity's current finish, if linked.
        reached_on: The day the milestone was reached, once it has been.
        lag_days: Calendar days from the milestone to the claim.
        terms_days: Calendar days the client has to pay; ``None`` counts as 0.

    Returns:
        Both dates, or ``None`` for both when nothing gives a date yet.
    """
    if reached_on is not None:
        base = reached_on
    elif trigger in SCHEDULE_DRIVEN_TRIGGERS and activity_finish is not None:
        base = activity_finish
    else:
        base = planned_date
    if base is None:
        return Forecast(reached=None, due=None)
    reached = add_days(base, max(lag_days, 0))
    return Forecast(reached=reached, due=add_days(reached, max(terms_days or 0, 0)))


def client_status(milestone_status: str, due: date | None, today: date) -> ClientStatus:
    """How an instalment reads to the client.

    ``pending`` is upcoming whatever its date: nothing is owed before the
    milestone is reached, so a slipping schedule never shows a client an
    overdue payment for work that is not done. Past that, an instalment owed
    after its due date is overdue.
    """
    if milestone_status == "paid":
        return "paid"
    if milestone_status not in ("reached", "invoiced"):
        return "upcoming"
    if due is not None and due < today:
        return "overdue"
    return "invoiced" if milestone_status == "invoiced" else "due"


# ── Statutory limits on up-front payments ─────────────────────────────────


@dataclass(frozen=True)
class DepositLimit:
    """A statutory ceiling on what a consumer may be asked to pay before work starts.

    The ceiling is ``percent`` of the contract price, combined with a fixed
    ``amount`` as the lesser of the two (or the only one set). ``tiers``
    replaces ``percent`` where the statute changes the rate with the price:
    the first tier whose ``below`` the price is under applies, and a tier
    without ``below`` covers the rest.
    """

    jurisdiction: str
    scope: str
    currency: str
    reference: str
    source_url: str
    checked_on: str
    percent: Decimal | None = None
    amount: Decimal | None = None
    tiers: tuple[tuple[Decimal | None, Decimal], ...] = ()
    applies_above: Decimal | None = None
    exemption: str = ""
    verified: bool = False

    def ceiling(self, price: Decimal) -> Decimal:
        """The most that may be taken up front on a contract of ``price``."""
        percent = self.percent
        for below, rate in self.tiers:
            if below is None or price < below:
                percent = rate
                break
        caps: list[Decimal] = []
        if percent is not None:
            caps.append((price * percent / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP))
        if self.amount is not None:
            caps.append(self.amount)
        return min(caps) if caps else price


#: Researched 2026-10-05 from the official texts named in ``source_url``.
#: Scope matters as much as the number: each applies to consumer residential
#: work of the kind ``scope`` names and nothing else.
DEPOSIT_LIMITS: tuple[DepositLimit, ...] = (
    DepositLimit(
        jurisdiction="US-CA",
        scope="home_improvement",
        currency="USD",
        percent=Decimal("10"),
        amount=Decimal("1000"),
        applies_above=Decimal("500"),
        reference="Cal. Bus. & Prof. Code 7159.5(a)(3)",
        source_url="https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=BPC&sectionNum=7159.5",
        checked_on="2026-10-05",
        exemption="Does not apply to a contractor who furnishes approved performance and payment bonds or uses joint control (7159.5(a)(8)).",
    ),
    DepositLimit(
        jurisdiction="US-MD",
        scope="home_improvement",
        currency="USD",
        percent=_ONE_THIRD_PERCENT,
        reference="Md. Code, Bus. Reg. 8-617",
        source_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gbr&section=8-617&enactments=false",
        checked_on="2026-10-05",
    ),
    DepositLimit(
        jurisdiction="US-MA",
        scope="home_improvement",
        currency="USD",
        percent=_ONE_THIRD_PERCENT,
        applies_above=Decimal("1000"),
        reference="Mass. Gen. Laws c.142A s.2",
        source_url="https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXX/Chapter142A/Section2",
        checked_on="2026-10-05",
        exemption="A deposit may also cover the cost of special-order materials, when that is higher.",
    ),
    DepositLimit(
        jurisdiction="AU-NSW",
        scope="residential_building",
        currency="AUD",
        percent=Decimal("10"),
        reference="Home Building Act 1989 (NSW) s.8",
        source_url="https://www.nsw.gov.au/housing-and-construction/building-or-renovating-a-home/preparing/contracts",
        checked_on="2026-10-05",
    ),
    DepositLimit(
        jurisdiction="AU-VIC",
        scope="residential_building",
        currency="AUD",
        tiers=((Decimal("20000"), Decimal("10")), (None, Decimal("5"))),
        reference="Domestic Building Contracts Act 1995 (Vic) s.11",
        source_url="https://www.consumer.vic.gov.au/licensing-and-registration/builders-and-tradespeople/running-your-business/deposits-and-payments",
        checked_on="2026-10-05",
        exemption="Moving into regulations by 2026-12-01 under the 2025 amendment act; review then.",
    ),
)


def deposit_limit_for(jurisdiction: str | None) -> DepositLimit | None:
    """The deposit limit for an ISO 3166-2 subdivision, if one is recorded."""
    code = (jurisdiction or "").strip().upper()
    if not code:
        return None
    return next((limit for limit in DEPOSIT_LIMITS if limit.jurisdiction == code), None)


@dataclass(frozen=True)
class DepositCheck:
    """The outcome of checking a plan's up-front payment against a limit."""

    outcome: Literal["within", "over", "below_threshold", "other_currency"]
    limit: DepositLimit
    ceiling: Decimal | None = None
    deposit: Decimal | None = None


def check_deposit(limit: DepositLimit, *, price: Decimal, deposit: Decimal, currency: str) -> DepositCheck:
    """Compare what a plan asks up front with the statutory ceiling.

    A contract in another currency is not converted: the statute names an
    amount in its own currency, and a converted figure would move with the
    exchange rate. The caller reports that the check could not run.
    """
    if (currency or "").upper() != limit.currency:
        return DepositCheck(outcome="other_currency", limit=limit)
    if limit.applies_above is not None and price <= limit.applies_above:
        return DepositCheck(outcome="below_threshold", limit=limit)
    ceiling = limit.ceiling(price)
    outcome: Literal["within", "over"] = "over" if deposit > ceiling else "within"
    return DepositCheck(outcome=outcome, limit=limit, ceiling=ceiling, deposit=deposit)

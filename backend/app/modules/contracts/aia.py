# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AIA G702/G703 payment-application support (US/CA/AU only).

The AIA G702 (Application and Certificate for Payment) and G703
(Continuation Sheet) are the standard progress-billing documents used in the
United States and, by close adoption, Canada and Australia. They are NOT used
in DACH (DIN/Abschlagsrechnung), the UK (JCT interim certificate) or most other
markets, so this layer is country-gated: it only renders for projects whose
country resolves to US, CA or AU.

This module is deliberately additive on top of the existing progress-claim
engine (``ContractsService``/``ProgressClaim``/``ProgressClaimLine``). It does
NOT duplicate the claim FSM, the retention math or the finance invoice bridge.
What it adds is the AIA presentation layer:

* the gate (:func:`is_aia_eligible`),
* the G703 continuation-line math (:func:`build_g703_line`),
* the single-row sheet for a contract billed without a schedule of values
  (:func:`build_cost_of_work_row`),
* column I from the retention engine's snapshot
  (:func:`apply_retention_snapshot`), and
* the G702 summary roll-up (:func:`build_g702_summary`).

All money is ``Decimal``; no float ever touches a currency value. The builders
are pure functions with hand-verifiable arithmetic so they can be unit-tested
against fixtures without a database.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.contracts.retention import allocate_cents

DEC_ZERO = Decimal("0")
DEC_HUNDRED = Decimal("100")
_QUANT = Decimal("0.01")

#: ISO 3166-1 alpha-2 codes whose projects may use AIA G702/G703.
AIA_COUNTRY_CODES: frozenset[str] = frozenset({"US", "CA", "AU"})

#: Full-name aliases (project.address["country"] stores display names like
#: "United States"). Mapped to the alpha-2 code so either representation gates
#: correctly. Lower-cased keys; lookup lower-cases the input.
_AIA_COUNTRY_ALIASES: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "ca": "CA",
    "can": "CA",
    "canada": "CA",
    "au": "AU",
    "aus": "AU",
    "australia": "AU",
}


def normalise_country(value: str | None) -> str | None:
    """Map a country code or display name to its ISO alpha-2 code.

    Accepts an alpha-2 code (``"US"``), a three-letter code (``"USA"``) or a
    display name (``"United States"``). Returns the alpha-2 code, or ``None``
    when the input is empty or unrecognised.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    return _AIA_COUNTRY_ALIASES.get(raw.lower())


def is_aia_eligible(country_code: str | None, address: Any = None) -> bool:
    """Return True when a project may use AIA G702/G703.

    Gating is purely a function of the project country. The project's
    ``country_code`` column is checked first; when it is empty or not a clean
    alpha-2 we fall back to ``address["country"]`` (a display name). A project
    is eligible only when the resolved country is one of US, CA, AU.
    """
    resolved = normalise_country(country_code)
    if resolved is None and isinstance(address, dict):
        resolved = normalise_country(address.get("country"))
    return resolved in AIA_COUNTRY_CODES


def _dec(value: Any) -> Decimal:
    """Coerce any stored money/number to Decimal, treating None/blank as 0."""
    if value in (None, ""):
        return DEC_ZERO
    return Decimal(str(value))


def _q(value: Decimal) -> Decimal:
    """Round to 2 dp, the AIA presentation precision (cents)."""
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def _allocate_to_cents(exact: list[Decimal]) -> list[Decimal]:
    """Round a column to cents so its rows add up to the column's own total.

    Each row goes down to the cent below it (towards minus infinity, so a
    credit row behaves like any other), and the cents the column is then short
    of ``_q(sum(exact))`` go one each to the rows that lost the most in
    rounding, ties in row order. The printed column therefore adds up to the
    rounded total of the exact figures instead of drifting from it: a hundred
    rows of 1000.05 print a 10% retainage of 10,000.50, where rounding each
    row on its own and adding the results gives 10,001.00.

    Deliberately not :func:`app.modules.contracts.retention.allocate_cents`,
    which is right for its own job and wrong for this one: it gives no share to
    a weight that is not positive, because a credit line holds no retention of
    its own. A credit line still has a scheduled value and a total to date, so
    here it takes its cent like any other row.
    """
    if not exact:
        return []
    floors = [value.quantize(_QUANT, rounding=ROUND_FLOOR) for value in exact]
    short = int((_q(sum(exact, DEC_ZERO)) - sum(floors, DEC_ZERO)) / _QUANT)
    allocated = list(floors)
    # Largest rounding loss first, then row order, so the result is stable.
    for index in sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))[:short]:
        allocated[index] += _QUANT
    return allocated


def build_g703_line(
    contract_line: Any,
    claim_line: Any | None,
    *,
    line_number: int,
    retainage_percent: Decimal,
    previous_when_unbilled: Decimal = DEC_ZERO,
) -> dict[str, Any]:
    """Build one G703 continuation row from a SoV line + its claim line.

    Maps onto the standard AIA G703 columns:

    * A  item number
    * B  description of work
    * C  scheduled value (the contract/SoV line total)
    * D  work completed from previous applications
    * E  work completed this period
    * F  materials presently stored (not in D or E)
    * G  total completed and stored to date (= D + E + F)
    * G% percent G / C
    * H  balance to finish (= C - G)
    * I  retainage (= retainage_percent x G)

    ``claim_line`` may be ``None`` for an SoV line not billed in this period;
    its E and F columns are then zero and column D is
    ``previous_when_unbilled``, what the earlier claims billed on the line,
    so the line still counts in line 4. Previous-period value (column D) is read
    from the claim line's ``prior_completed_value`` when present, else derived
    from ``cumulative_completed_value - period_completed_value``. Stored
    materials (column F) come from ``materials_stored_value`` if present, else
    from the claim-line metadata key ``materials_stored_value`` (no DDL needed).

    All amounts are ``Decimal`` rounded to cents.
    """
    exact = _exact_columns(
        contract_line,
        claim_line,
        retainage_percent=retainage_percent,
        previous_when_unbilled=previous_when_unbilled,
    )
    return _fill_row(
        line_number=line_number,
        item_number=_item_number(contract_line, line_number),
        description=getattr(contract_line, "description", "") or "",
        scheduled=exact["scheduled"],
        previous=_q(exact["previous"]),
        stored=_q(exact["stored"]),
        total=_q(exact["total"]),
        retainage=_q(exact["retainage"]),
        retainage_stored=_q(exact["retainage_stored"]),
    )


def _item_number(contract_line: Any, line_number: int) -> str:
    """Column A: the SoV line's own code, or its position on the sheet."""
    return getattr(contract_line, "code", "") or str(line_number)


def _exact_columns(
    contract_line: Any,
    claim_line: Any | None,
    *,
    retainage_percent: Decimal,
    previous_when_unbilled: Decimal = DEC_ZERO,
) -> dict[str, Decimal]:
    """The G703 columns for one row, unrounded.

    Everything the sheet prints is worked out here at full precision; rounding
    to cents happens once, over the whole column, in :func:`build_g703`. A
    percentage of an odd-cent scheduled value is rarely a whole cent, so
    rounding each row before adding them up is what made the totals drift.
    """
    scheduled = _dec(getattr(contract_line, "total_value", 0))

    if claim_line is None:
        previous = _dec(previous_when_unbilled)
        this_period = DEC_ZERO
        stored = DEC_ZERO
    else:
        this_period = _dec(getattr(claim_line, "period_completed_value", 0))
        # Column D: prefer an explicit prior-value column when the schema has
        # it; otherwise derive from the running cumulative minus this period.
        prior_attr = getattr(claim_line, "prior_completed_value", None)
        if prior_attr not in (None, ""):
            previous = _dec(prior_attr)
        else:
            cumulative = _dec(getattr(claim_line, "cumulative_completed_value", 0))
            previous = cumulative - this_period
            if previous < DEC_ZERO:
                previous = DEC_ZERO
        # Column F: stored materials, from a dedicated column or metadata.
        stored_attr = getattr(claim_line, "materials_stored_value", None)
        if stored_attr not in (None, ""):
            stored = _dec(stored_attr)
        else:
            meta = getattr(claim_line, "metadata_", None) or {}
            stored = _dec(meta.get("materials_stored_value")) if isinstance(meta, dict) else DEC_ZERO

    total_to_date = previous + this_period + stored
    return {
        "scheduled": scheduled,
        "previous": previous,
        "this_period": this_period,
        "stored": stored,
        "total": total_to_date,
        "retainage": retainage_percent * total_to_date / DEC_HUNDRED,
        # The flat rate's split of column I; apply_retention_snapshot replaces
        # all three with the engine's figures on a claim it has worked out.
        "retainage_stored": retainage_percent * stored / DEC_HUNDRED,
    }


def _fill_row(
    *,
    line_number: int,
    item_number: str,
    description: str,
    scheduled: Decimal | None,
    previous: Decimal,
    stored: Decimal,
    total: Decimal,
    retainage: Decimal,
    retainage_stored: Decimal,
) -> dict[str, Any]:
    """Assemble one printed G703 row from its columns, already in cents.

    Column E is what is left of column G once D and F are taken off, rather
    than a rounding of its own, so the row a person reads adds up: D + E + F
    is always exactly G. The percent and column H follow the printed G for the
    same reason.

    ``scheduled`` is None only on the row for money no schedule line carries
    (see :data:`OUT_OF_SCHEDULE_SCHEDULED_VALUE`). The percent and column H
    are then None as well, since there is nothing to measure them against. A
    schedule line whose value is zero is a different thing and keeps printing
    its zero C, zero percent and its balance.
    """
    if scheduled is None:
        percent: Decimal | None = None
        balance: Decimal | None = None
    else:
        scheduled = _q(scheduled)
        percent = _q(total / scheduled * DEC_HUNDRED) if scheduled > DEC_ZERO else DEC_ZERO
        balance = scheduled - total
    return {
        "line_number": line_number,
        "item_number": item_number,
        "description": description,
        "scheduled_value": scheduled,
        "previous_value": previous,
        "this_period_value": total - previous - stored,
        "materials_stored": stored,
        "total_completed_stored": total,
        "percent_complete": percent,
        "balance_to_finish": balance,
        "retainage": retainage,
        "retainage_completed_work": retainage - retainage_stored,
        "retainage_stored_materials": retainage_stored,
    }


def bills_without_schedule(claim: Any, claim_lines: list[Any]) -> bool:
    """Whether this claim's own figures go on a single cost-of-work row.

    A claim carrying a gross with no lines behind it is cost-plus or time and
    materials billing actual cost: there is no schedule of values to roll up,
    and rolling the contract's lines up anyway prints zeros on a claim owed its
    net in full. The shape of the claim decides it, not the contract type, and
    that is deliberate: a GMP or design-build claim generated with no lines
    prints the same zeros, and a check on cost_plus and tm would have left it
    printing them.

    Lives here, beside the sheet it decides the shape of, because the figures
    frozen onto a claim at certification and the figures the sheet prints have
    to agree; two copies of this question are two answers waiting to diverge.
    """
    return not claim_lines and Decimal(str(getattr(claim, "gross_amount", None) or 0)) != DEC_ZERO


def sheet_sov_lines(
    contract_lines: list[Any],
    claim_lines_by_contract_line: dict[Any, Any],
    prior_by_line: dict[Any, Decimal],
) -> list[Any]:
    """The schedule-of-values lines a continuation sheet lists.

    Roll-up rows are the sum of their children, so listing one beside its
    children counts the job twice down column C and prints a parent at 0%
    complete against the whole contract. The generators never bill a parent;
    one that carries a claim line or a prior value was billed by hand, and
    dropping it would take that money off the sheet while the claim still
    holds it, so it stays.
    """
    parent_ids = {ln.parent_line_id for ln in contract_lines if ln.parent_line_id is not None}
    return [
        ln
        for ln in contract_lines
        if ln.id not in parent_ids or ln.id in claim_lines_by_contract_line or prior_by_line.get(ln.id)
    ]


#: Column C on the row carrying work billed outside the schedule of values.
#:
#: That money has no scheduled value of its own: either nobody planned a line
#: for it, or the lines that were planned had no room left to hold it. So
#: column C on that row is None, and :func:`_fill_row` then leaves the two
#: cells measured against C, the percent and column H, as None too. Every
#: reader prints the three as empty cells.
#:
#: An empty cell says there is no answer; a zero says the answer is zero. The
#: row used to carry a zero here as a placeholder, which printed a percent of
#: 0 against a non-zero G and a column H of minus G, two answers to a question
#: the row cannot be asked. Column G still carries the money, and D, E, F and
#: I are what they were.
#:
#: The printed totals row adds up only the cells that have an answer. Its C
#: total is unchanged, because this row used to add a zero. Its H total is the
#: balance left on the schedule lines, which is this row's G higher than the
#: placeholder printed, so on a sheet carrying this row the H total is no
#: longer the C total less the G total. That is accepted, as is column C not
#: tying to the contract sum on a contract billed both ways.
OUT_OF_SCHEDULE_SCHEDULED_VALUE: Decimal | None = None

#: Column A on that row. Empty rather than borrowed: the cost-of-work row
#: prints the contract's own code, and a reader has to be able to tell the
#: two apart, which is the ambiguity this row exists to remove.
OUT_OF_SCHEDULE_ITEM_NUMBER = ""


def build_g703(
    contract_lines: list[Any],
    claim_lines_by_contract_line: dict[Any, Any],
    *,
    retainage_percent: Decimal,
    prior_by_line: dict[Any, Decimal] | None = None,
    prior_without_schedule: Decimal = DEC_ZERO,
    out_of_schedule_retainage: Decimal | None = None,
    out_of_schedule_label: str = "",
) -> list[dict[str, Any]]:
    """Build the full G703 continuation sheet, one row per SoV line.

    ``prior_by_line`` is what the earlier claims billed per SoV line, column D
    for a line this claim does not bill.

    ``prior_without_schedule`` is what earlier claims billed that no schedule
    line carries. It gets a row of its own because column D here is assembled
    from claim lines, so money with no line behind it is invisible to the
    column while remaining visible on line 7, and line 8 then subtracts a
    certificate the columns never added. The row carries the figure in column
    D and its share of retainage, so line 4 and line 5 both see it, and
    None in column C, the percent and column H, which have no answer on it;
    ``out_of_schedule_label`` is its description, resolved by the caller
    because this module is pure and holds no strings.

    Two different things arrive here and the row has to be honest about both.
    An earlier claim may have had no lines at all, billed from cost on a
    contract that can bill either way. Or there was a schedule and the claim
    outran it, and the remainder its gross could not be placed against is
    money no line carries either. Do not describe this row as work billed
    without a schedule: that is true of the first and false of the second.

    Its retainage is ``out_of_schedule_retainage``, what the caller worked
    out those earlier claims actually held on that money less its share of
    any release. The certificate always passes it. Without it the row falls
    back to this sheet's ``retainage_percent``, which equals what those
    claims held only while the rate has not moved: a ladder or an edited
    contract rate makes the two differ, and a release could never reach it.

    The columns are rounded to cents across the whole sheet rather than row by
    row, so the sheet adds up to the same figures the claim itself holds.
    Column G is the anchor, because it is what G702 line 4 and the printed
    totals row read and what column H and the percent are measured against;
    column I is rounded the same way. A row keeps its own column D and F to
    the cent and takes column E as the remainder of G, so every row reads
    D + E + F = G.
    """
    prior = prior_by_line or {}
    # Any rather than Decimal: the out-of-schedule row appended below has no
    # column C, and says so with None.
    exact: list[dict[str, Any]] = [
        _exact_columns(
            cl,
            claim_lines_by_contract_line.get(getattr(cl, "id", None)),
            retainage_percent=retainage_percent,
            previous_when_unbilled=prior.get(getattr(cl, "id", None), DEC_ZERO),
        )
        for cl in contract_lines
    ]
    captions = [
        (_item_number(cl, idx), getattr(cl, "description", "") or "") for idx, cl in enumerate(contract_lines, start=1)
    ]

    outside = _dec(prior_without_schedule)
    if outside > DEC_ZERO:
        # Appended before the cent allocation rather than after, so this row
        # is rounded with the rest of the column and the sheet still totals
        # to the figures the claim holds.
        exact.append(
            {
                "scheduled": OUT_OF_SCHEDULE_SCHEDULED_VALUE,
                "previous": outside,
                "this_period": DEC_ZERO,
                "stored": DEC_ZERO,
                "total": outside,
                "retainage": (
                    retainage_percent * outside / DEC_HUNDRED
                    if out_of_schedule_retainage is None
                    else _dec(out_of_schedule_retainage)
                ),
                "retainage_stored": DEC_ZERO,
            }
        )
        captions.append((OUT_OF_SCHEDULE_ITEM_NUMBER, out_of_schedule_label))

    totals = _allocate_to_cents([columns["total"] for columns in exact])
    retainages = _allocate_to_cents([columns["retainage"] for columns in exact])
    stored_retainages = _allocate_to_cents([columns["retainage_stored"] for columns in exact])
    return [
        _fill_row(
            line_number=idx,
            item_number=item_number,
            description=description,
            scheduled=columns["scheduled"],
            previous=_q(columns["previous"]),
            stored=_q(columns["stored"]),
            total=total,
            retainage=retainage,
            retainage_stored=retainage_stored,
        )
        for idx, ((item_number, description), columns, total, retainage, retainage_stored) in enumerate(
            zip(captions, exact, totals, retainages, stored_retainages, strict=True), start=1
        )
    ]


def build_cost_of_work_row(
    *,
    item_number: str,
    description: str,
    scheduled: Decimal,
    previous: Decimal,
    this_period: Decimal,
    retainage: Decimal,
) -> dict[str, Any]:
    """The one G703 row for a claim billed without a schedule of values.

    Cost-plus and time-and-material contracts bill actual cost plus a fee, so
    there are no SoV lines behind the claim to roll up and a sheet built from
    the contract's lines prints zeros against a claim that is owed money. What
    has been billed goes on a single row instead, taken from the claim's own
    figures: ``previous`` is what the earlier claims billed, ``this_period``
    the claim's gross and ``retainage`` the retention held to date. Line 4 and
    line 5 of the face are then the claim's own gross and retention, and line
    8 is what it is owed.
    """
    return _fill_row(
        line_number=1,
        item_number=item_number,
        description=description,
        scheduled=scheduled,
        previous=_q(previous),
        stored=DEC_ZERO,
        total=_q(previous) + _q(this_period),
        retainage=_q(retainage),
        retainage_stored=DEC_ZERO,
    )


def apply_retention_snapshot(
    rows: list[dict[str, Any]],
    contract_lines: list[Any],
    claim_lines_by_contract_line: dict[Any, Any],
    *,
    held: Decimal,
) -> list[dict[str, Any]]:
    """Put the retention engine's column I on the rows of a claim it has worked out.

    ``held`` is the claim's line 5 as stored. A line this claim bills carries
    its own figures (``retention_to_date`` on work, ``retention_stored_to_date``
    on stored materials); what is left of line 5 goes to the lines it does not
    bill, pro rata to their work to date, in cents. Column I therefore adds
    up to line 5 exactly, before and after a release takes it down. Rows are
    changed in place and returned; ``rows`` and ``contract_lines`` are in the
    same order, as :func:`build_g703` builds them.

    The two are walked strictly in step, so they have to be the same length.
    Pass the schedule rows only. A row with no contract line behind it has
    nothing to pair with and raises here, and it would in any case be read as
    a line this claim did not bill and drawn a pro rata share of what is left
    of line 5, losing the column I :func:`build_g703` rounded for it, which is
    money the certificate then pays out on line 8.

    ``held`` measures the schedule and nothing else: the engine takes
    ``before + max(required - before, 0) - released``, floored at zero, with
    all three on schedule lines. Retention an earlier claim held on money no
    line of its own carries, and that money's share of the releases, are left
    out of it and printed on the out-of-schedule row instead. It used to take
    ``before`` over every prior claim, so such a month ratcheted into ``held``
    and this function spread it over the schedule rows while that row
    printed it again.
    """
    work: dict[int, Decimal] = {}
    stored: dict[int, Decimal] = {}
    unbilled: dict[int, Decimal] = {}
    for index, (row, contract_line) in enumerate(zip(rows, contract_lines, strict=True)):
        claim_line = claim_lines_by_contract_line.get(getattr(contract_line, "id", None))
        if claim_line is not None and getattr(claim_line, "retention_to_date", None) is not None:
            work[index] = _dec(claim_line.retention_to_date)
            stored[index] = _dec(getattr(claim_line, "retention_stored_to_date", None))
        else:
            unbilled[index] = _dec(row["previous_value"]) + _dec(row["this_period_value"])
    rest = _q(_dec(held)) - sum(work.values(), DEC_ZERO) - sum(stored.values(), DEC_ZERO)
    if unbilled and rest > DEC_ZERO and any(weight > DEC_ZERO for weight in unbilled.values()):
        work.update(allocate_cents(rest, unbilled))
    for index, row in enumerate(rows):
        on_work = work.get(index, DEC_ZERO)
        on_stored = stored.get(index, DEC_ZERO)
        row["retainage_completed_work"] = _q(on_work)
        row["retainage_stored_materials"] = _q(on_stored)
        row["retainage"] = _q(on_work + on_stored)
    return rows


def build_g702_summary(
    g703_rows: list[dict[str, Any]],
    *,
    original_contract_sum: Decimal,
    change_orders_net: Decimal = DEC_ZERO,
    previous_certificates_total: Decimal = DEC_ZERO,
    previous_certificates_basis: str | None = None,
) -> dict[str, Any]:
    """Roll the G703 rows into the G702 summary (the certificate face).

    Implements the standard G702 line numbering:

    * 1  original contract sum
    * 2  net change by change orders
    * 3  contract sum to date (= 1 + 2)
    * 4  total completed and stored to date (sum of G703 column G)
    * 5  retainage (sum of G703 column I), split into 5a on completed
      work and 5b on stored material
    * 6  total earned less retainage (= 4 - 5)
    * 7  less previous certificates for payment
    * 8  current payment due (= 6 - 7, floored at zero)
    * 9  balance to finish including retainage (= 3 - 6)

    Pure roll-up over already-built G703 rows; all ``Decimal``.
    ``previous_certificates_basis`` says where line 7 came from, for example
    ``"reconstructed"`` when the caller rebuilt it from the prior claims'
    stored gross and retention, and is passed through so a reader of the
    figure can tell an exact line 7 from a rebuilt one.
    """
    contract_sum_to_date = original_contract_sum + change_orders_net
    total_completed_stored = sum((_dec(r["total_completed_stored"]) for r in g703_rows), DEC_ZERO)
    total_retainage = sum((_dec(r["retainage"]) for r in g703_rows), DEC_ZERO)
    retainage_stored = sum((_dec(r.get("retainage_stored_materials")) for r in g703_rows), DEC_ZERO)
    total_earned_less_retainage = total_completed_stored - total_retainage
    current_payment_due = total_earned_less_retainage - previous_certificates_total
    if current_payment_due < DEC_ZERO:
        current_payment_due = DEC_ZERO
    balance_to_finish = contract_sum_to_date - total_earned_less_retainage

    return {
        "original_contract_sum": _q(original_contract_sum),
        "change_orders_net": _q(change_orders_net),
        "contract_sum_to_date": _q(contract_sum_to_date),
        "total_completed_stored": _q(total_completed_stored),
        "retainage": _q(total_retainage),
        "retainage_completed_work": _q(total_retainage - retainage_stored),
        "retainage_stored_materials": _q(retainage_stored),
        "total_earned_less_retainage": _q(total_earned_less_retainage),
        "previous_certificates_total": _q(previous_certificates_total),
        "previous_certificates_basis": previous_certificates_basis,
        "current_payment_due": _q(current_payment_due),
        "balance_to_finish": _q(balance_to_finish),
    }

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Combining tax rates for one jurisdiction, and the rules a row must obey.

Two things live here, and they are the same subject seen from the write side
and the read side.

**The resolver.** Given every tax row a country carries and the subdivision a
project sits in, work out the total rate payable and say how it was arrived
at. Three regimes have to come out right, and they are not variations of one
shape: a harmonised rate replaces the federal one, a separate provincial rate
is charged alongside it on the same pre-tax amount, and a compounding rate is
charged on the amount including the federal tax. Ontario is 13, British
Columbia is 5 + 7, and a compounding 7 on a federal 5 is 12.35 rather than 12.
An implementation that adds the federal rate to whatever the province charges
is right in British Columbia and reports an 18 % Ontario invoice.

The mirror-image mistake is adding up rates that were never meant to combine.
A country's standard rate and its reduced tiers are *alternatives*: one supply
is charged at one of them, and 19 + 7 is not a German rate anybody pays. Only
sub-national rows combine; tiers are chosen between, and ``is_default`` is what
says which tier is the standard one. This module made that mistake until
2026-08-26, and made it only where no test looked - on the shipped seed file,
where Germany resolved to 26 %, the United Kingdom to 25 % and France to 35.5 %,
while every fixture in the suite carried a single rate per country and passed.

**The write rules.** A row that does not say which subdivision it belongs to
cannot be found by the resolver, so it is not merely wrong, it is invisible:
the province falls back to the federal rate and nothing anywhere says a rate
was missed. :func:`validate_tax_row` is what stops such a row being written,
and it runs on every path into the table rather than on the API schema alone.

No function here touches the database or a Pydantic model. Rows arrive as
:class:`TaxRateRow`, which both a live ORM row and a line of the shipped seed
file convert into, so the arithmetic the tests check against published figures
is the same arithmetic the API serves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NamedTuple

from app.modules.i18n_foundation.models import SUBNATIONAL_COMBINATIONS, TAX_COMBINATIONS
from app.modules.i18n_foundation.subdivisions import (
    SUBDIVISION_CODE_RE,
    has_subdivision_axis,
    is_known_subdivision,
    normalize_subdivision,
    subdivision_name,
)

#: How the resolver arrived at its answer. Every member is a distinct
#: situation a caller may need to act on differently, and in particular the
#: two that produce no provincial rate are kept apart:
#:
#: ``harmonised``
#:     One rate replaces the federal one. Ontario, 13 %.
#: ``stacked``
#:     Federal plus one or more provincial rates, all on the pre-tax amount.
#: ``compounded``
#:     At least one provincial rate is charged on the federal-inclusive
#:     amount, so the total is more than the sum of the rates.
#: ``federal_only``
#:     The subdivision is one this platform knows and it levies nothing of
#:     its own, so the federal rate is the whole answer. Alberta, 5 %.
#: ``national``
#:     The country has no sub-national tax axis at all; its default
#:     country-wide rate is the whole answer. Germany, 19 %.
#: ``subdivision_unknown``
#:     A subdivision was needed and was either not supplied or not one this
#:     platform carries. **No rate is returned.** This is the member that
#:     stops "nobody chose a province" from being served as Alberta.
#: ``no_configuration``
#:     The country has no rates on file at all. No rate is returned.
#: ``default_rate_ambiguous``
#:     The country has several country-wide rates in force and they do not
#:     say which one is the standard rate - none is flagged ``is_default``,
#:     or more than one is. **No rate is returned**, for the same reason
#:     ``subdivision_unknown`` returns none: any of the candidates is a real
#:     figure and picking one would be a guess wearing a real figure's face.
#:
#:     There were three ways to answer this and the ranking between them is
#:     the point, so it is written down rather than left to be re-derived.
#:     Returning **a plausible rate** is the worst kind of wrong: it is a
#:     number a caller puts on an invoice, with nothing on it to say nobody
#:     verified it, so the error is invisible until a customer disputes it.
#:     Returning **zero** is worse still, and it is the one that looks
#:     harmless - zero reads as a deliberate exemption, computes without
#:     complaint, and produces a document that is both wrong and confident.
#:     Returning **no number** is the only one of the three that a caller
#:     cannot mistake for an answer. A gap is visible; a wrong rate is not.
#: ``default_rate_not_in_force``
#:     The country's standard rate is on file and its window does not contain
#:     the date being asked about. What is in force instead is a reduced tier
#:     that runs alongside the standard rate rather than before it. **No rate
#:     is returned.**
#:
#:     This is the member that had been answering with a number. A lone
#:     unflagged row in force was promoted to the standard rate, so Germany
#:     priced 1990 at 7 %, Britain priced 1990 at 0 % and Russia priced 2010
#:     at 10 %, each with ``resolved`` true and nothing on the answer to say
#:     it came from another tier. A rate that exists is not a rate that
#:     applies, and the difference is only visible on the date axis.
#:
#:     It is not ``default_rate_ambiguous``: there the data cannot say which
#:     of the rates in force is the standard one, here it says so plainly and
#:     the answer is that the standard rate had not started yet.
#: ``awaiting_confirmation``
#:     A rate in force for this jurisdiction was marked as needing a local
#:     specialist's confirmation, typically the client's accountant checking
#:     it against the tax authority's own publication, and nobody has
#:     confirmed it yet. **No rate is returned**, and none of the other rows
#:     stands in for it: the unconfirmed figure is the one in doubt, so a
#:     neighbour on file is not an answer either.
ResolutionStatus = Literal[
    "harmonised",
    "stacked",
    "compounded",
    "federal_only",
    "national",
    "subdivision_unknown",
    "no_configuration",
    "default_rate_ambiguous",
    "default_rate_not_in_force",
    "awaiting_confirmation",
]

#: Statuses that carry a rate a caller may price work with. Every status not
#: in here reports that the question could not be answered, and its
#: ``combined_rate_pct`` is ``None`` rather than zero or the federal rate.
#: Stated as the complement rather than as a count of the others on purpose:
#: this tuple has not changed while the vocabulary beside it has grown twice,
#: and a comment that counts the others is wrong the next time it does.
RESOLVED_STATUSES: tuple[ResolutionStatus, ...] = (
    "harmonised",
    "stacked",
    "compounded",
    "federal_only",
    "national",
)


class TaxRuleError(ValueError):
    """A tax row contradicts itself, or contradicts what its country needs.

    Carries the machine-readable ``code`` alongside the sentence, so a caller
    that wants to branch on the reason does not have to match on prose.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TaxRateRow(NamedTuple):
    """One stored rate, flattened to just what combining it needs.

    The resolver reads nothing else, which is why a database row and a line of
    the seed file can both be turned into one of these and get identical
    answers out.

    ``is_default`` is the only thing that separates a country's standard rate
    from its reduced tiers. It carries a default of ``False`` so a fixture that
    predates it still constructs, and because a row that does not claim to be
    the standard rate is not one.
    """

    country_code: str
    tax_code: str | None
    tax_name: str
    rate_pct: str
    tax_type: str
    combination: str
    subdivision_code: str | None
    effective_from: str | None
    effective_to: str | None
    is_default: bool = False
    #: True while the row waits for the local confirmation it was marked as
    #: needing. Such a row resolves to nothing; see ``awaiting_confirmation``.
    awaiting_confirmation: bool = False


#: Where a tax row keeps its local confirmation, inside ``metadata``. Shape:
#: ``{"required": True, "status": "pending" | "confirmed", "accountant_name",
#: "source_reference", "confirmed_by", "confirmed_at"}``. A row without the key
#: needs no confirmation, which is every row shipped before the key existed.
LOCAL_CONFIRMATION_KEY = "local_confirmation"


def is_awaiting_confirmation(metadata: Mapping[str, Any] | None) -> bool:
    """Whether a row's metadata says it is marked for confirmation and not yet confirmed."""
    block = (metadata or {}).get(LOCAL_CONFIRMATION_KEY)
    if not isinstance(block, Mapping) or not block.get("required"):
        return False
    return block.get("status") != "confirmed"


@dataclass(frozen=True)
class RateComponent:
    """One rate that contributed to a total, and what it was charged on."""

    tax_code: str | None
    tax_name: str
    rate_pct: str
    combination: str
    #: ``consideration`` - charged on the pre-tax amount.
    #: ``consideration_plus_federal`` - charged on the federal-inclusive
    #: amount, which is what makes the total exceed the sum of the rates.
    base: Literal["consideration", "consideration_plus_federal"]
    #: The rate this component actually adds to the total. For a stacking or
    #: replacing rate that is ``rate_pct``; for a compounding one it is the
    #: larger grossed-up figure, so the components always sum to the total.
    effective_rate_pct: str


@dataclass(frozen=True)
class TaxResolution:
    """The total rate for one jurisdiction, and how it was reached."""

    country_code: str
    subdivision_code: str | None
    subdivision_name: str | None
    status: ResolutionStatus
    #: ``None`` whenever ``status`` is not in :data:`RESOLVED_STATUSES`. An
    #: unanswerable question returns no number at all - not zero, and not the
    #: federal rate, either of which a caller would put on an invoice.
    combined_rate_pct: str | None
    #: The country-wide rate the sub-national ones were combined with, when
    #: there is one. Reported separately because a caller showing a breakdown
    #: needs it even when a harmonised rate has replaced it (in which case it
    #: is not part of the total).
    federal_rate_pct: str | None
    as_of: str
    components: list[RateComponent] = field(default_factory=list)
    #: One sentence saying why an unresolved answer is unresolved. ``None``
    #: when the resolution succeeded.
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        """Whether a rate was produced at all."""
        return self.status in RESOLVED_STATUSES


# ── Building rows ────────────────────────────────────────────────────────────


def row_from_orm(config: Any) -> TaxRateRow:
    """Flatten a :class:`~app.modules.i18n_foundation.models.TaxConfiguration`.

    Args:
        config: An ORM row. Typed loosely on purpose - this module must not
            import the session machinery to stay usable from a plain test.

    Returns:
        The same rate as a :class:`TaxRateRow`.
    """
    return TaxRateRow(
        country_code=config.country_code,
        tax_code=config.tax_code,
        tax_name=config.tax_name,
        rate_pct=config.rate_pct,
        tax_type=config.tax_type,
        combination=config.combination,
        subdivision_code=config.subdivision_code,
        effective_from=config.effective_from,
        effective_to=config.effective_to,
        is_default=bool(config.is_default),
        awaiting_confirmation=is_awaiting_confirmation(getattr(config, "metadata_", None)),
    )


def row_from_mapping(data: Mapping[str, Any]) -> TaxRateRow:
    """Flatten a seed-file line, or any dict shaped like one.

    Missing optional keys read as ``None`` so a fixture can leave out the
    fields it does not care about, but ``combination`` is required: a row that
    does not say how it combines is the defect this whole axis exists to stop,
    and defaulting it here would reintroduce it in the one place nothing else
    is watching.
    """
    return TaxRateRow(
        country_code=data["country_code"],
        tax_code=data.get("tax_code"),
        tax_name=data.get("tax_name", ""),
        rate_pct=data["rate_pct"],
        tax_type=data.get("tax_type", ""),
        combination=data["combination"],
        subdivision_code=data.get("subdivision_code"),
        effective_from=data.get("effective_from"),
        effective_to=data.get("effective_to"),
        is_default=bool(data.get("is_default", False)),
    )


# ── Selecting what is in force ───────────────────────────────────────────────


def active_rows(rows: Sequence[TaxRateRow], country_code: str, on_date: str) -> list[TaxRateRow]:
    """Rows of one country whose effective window contains ``on_date``.

    Both bounds are inclusive, and dates are ISO strings compared
    lexicographically - the same comparison the repository issues in SQL, so
    the in-memory answer and the queried one cannot disagree at a boundary.
    """
    country = country_code.strip().upper()
    out: list[TaxRateRow] = []
    for row in rows:
        if row.country_code.strip().upper() != country:
            continue
        if row.effective_from is not None and row.effective_from > on_date:
            continue
        if row.effective_to is not None and row.effective_to < on_date:
            continue
        out.append(row)
    return out


# ── The arithmetic ───────────────────────────────────────────────────────────


def _rate(row: TaxRateRow) -> Decimal:
    """A row's percentage as an exact Decimal."""
    try:
        return Decimal(row.rate_pct)
    except (InvalidOperation, TypeError) as exc:
        raise TaxRuleError(
            "rate_not_numeric",
            f"Tax row {row.tax_code or row.tax_name!r} carries rate_pct {row.rate_pct!r}, which is not a number.",
        ) from exc


def _country_wide_standard(rows: Sequence[TaxRateRow]) -> tuple[TaxRateRow | None, str]:
    """Pick the standard rate out of a country's country-wide rows.

    Args:
        rows: The ``national`` and ``federal`` rows in force on the date being
            resolved. Reduced tiers are in here too - that is the whole point,
            because telling them apart is what this does.

    Returns:
        ``(row, "")`` when exactly one row is the standard rate, and
        ``(None, phrase)`` when the data does not say which one is. The phrase
        completes the sentence "the country has N rates in force and ...", so
        the caller's message names the reason rather than restating the count.
    """
    flagged = [r for r in rows if r.is_default]
    if len(flagged) == 1:
        return flagged[0], ""
    if not flagged:
        # One unflagged row is not ambiguous, it is simply a row written before
        # the flag mattered - every fixture in this repo older than the tier
        # question looks like this, and so does a country that only ever had
        # one rate. More than one, with nothing to choose between them, is the
        # case that has to refuse.
        if len(rows) == 1:
            return rows[0], ""
        return None, "none of them is flagged as the default"
    return None, f"{len(flagged)} of them are flagged as the default"


def _dormant_default_rows(rows: Sequence[TaxRateRow], country_code: str, on_date: str) -> list[TaxRateRow]:
    """A country's country-wide rows flagged ``is_default`` that are not in force on ``on_date``.

    Dormant is defined as the complement of :func:`active_rows` rather than by
    a second window comparison written here, so the two cannot drift into
    disagreeing about a boundary day.

    Args:
        rows: Every rate on file, any country.
        country_code: ISO 3166-1 alpha-2, any case.
        on_date: The ISO date being resolved.

    Returns:
        The flagged country-wide rows whose window does not contain
        ``on_date``. Empty for a country that has no standard rate on file at
        all, which is the case a lone unflagged row is allowed to answer.
    """
    country = country_code.strip().upper()
    live = active_rows(rows, country, on_date)
    return [
        row
        for row in rows
        if row.country_code.strip().upper() == country
        and row.combination in ("national", "federal")
        and row.is_default
        and row not in live
    ]


def _is_earlier_period(in_force: Sequence[TaxRateRow], dormant: Sequence[TaxRateRow]) -> bool:
    """Whether the row in force is an earlier period of the standard rate itself.

    Romania is the shape this exists for: the 19 % row was closed on
    2025-07-31 and the 21 % row opened the next day, so a question about 2020
    meets one unflagged row that really is the standard rate of that year.
    Germany is the other shape: its 7 % reduced tier carries no
    ``effective_to`` at all, so it is still in force on the day the 19 %
    standard rate starts. Two rates that overlap are alternatives; one that
    ends where the other begins is its predecessor.

    The test is the end of one window against the start of the next. It needs
    no tax code and no naming convention, so a country that renamed its tax
    between periods still reads as a succession.
    """
    if len(in_force) != 1:
        return False
    ends = in_force[0].effective_to
    starts = [row.effective_from for row in dormant if row.effective_from is not None]
    return ends is not None and bool(starts) and ends < min(starts)


def format_rate(value: Decimal) -> str:
    """Render a rate without exponent notation and without trailing zeros.

    ``Decimal("12.350")`` prints as ``"12.35"`` and ``Decimal("10")`` as
    ``"10"`` rather than ``"1E+1"``, which is what ``normalize`` alone would
    give for a whole number.
    """
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return f"{normalized:f}"


def resolve(
    rows: Sequence[TaxRateRow],
    country_code: str,
    subdivision_code: str | None = None,
    on_date: str | None = None,
) -> TaxResolution:
    """Total tax rate for one jurisdiction on one date.

    Args:
        rows: Every rate on file. Rows of other countries are ignored, so a
            caller may pass the whole table.
        country_code: ISO 3166-1 alpha-2, any case.
        subdivision_code: ISO 3166-2, any case. ``None`` means the caller does
            not know which subdivision the work is in, which is answered as
            ``subdivision_unknown`` for a country that has an axis and is
            simply irrelevant for one that does not.
        on_date: ISO date the rate is wanted for. Defaults to today.

    Returns:
        A :class:`TaxResolution`. Check ``resolved`` before reading
        ``combined_rate_pct``: an unanswerable question returns ``None``
        there rather than a plausible number.
    """
    country = country_code.strip().upper()
    subdivision = normalize_subdivision(subdivision_code)
    as_of = on_date or date.today().isoformat()
    name = subdivision_name(country, subdivision) if subdivision else None

    active = active_rows(rows, country, as_of)
    if not active:
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=name,
            status="no_configuration",
            combined_rate_pct=None,
            federal_rate_pct=None,
            as_of=as_of,
            reason=f"No tax rate is on file for country {country} on {as_of}.",
        )

    # A row in force that still waits for its local confirmation stops the
    # answer for every jurisdiction it takes part in: a country-wide row for
    # all of them, a sub-national one for its own subdivision and for a
    # caller who named none.
    unconfirmed = [
        r
        for r in active
        if r.awaiting_confirmation
        and (
            subdivision is None
            or r.subdivision_code is None
            or normalize_subdivision(r.subdivision_code) == subdivision
        )
    ]
    if unconfirmed:
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=name,
            status="awaiting_confirmation",
            combined_rate_pct=None,
            federal_rate_pct=None,
            as_of=as_of,
            reason=(
                f"A rate in force for {subdivision or country} on {as_of} is waiting for confirmation by a local "
                "specialist and is not used until it is confirmed."
            ),
        )

    federal = [r for r in active if r.combination == "federal"]
    national = [r for r in active if r.combination == "national"]
    subnational = [r for r in active if r.combination in SUBNATIONAL_COMBINATIONS]

    # Does this country need a subdivision before the question can be
    # answered? Two independent signals, either of which is enough: the
    # platform enumerates its subdivisions, or the data itself already
    # carries sub-national rows for it. The second catches a country that has
    # rates per subdivision but no registry yet, which is exactly the United
    # States today.
    axis = has_subdivision_axis(country) or bool(subnational)

    if axis and subdivision is None:
        return TaxResolution(
            country_code=country,
            subdivision_code=None,
            subdivision_name=None,
            status="subdivision_unknown",
            combined_rate_pct=None,
            federal_rate_pct=format_rate(_rate(federal[0])) if federal else None,
            as_of=as_of,
            reason=(
                f"Country {country} charges tax by subdivision, so a rate cannot be given without "
                f"one. Supply an ISO 3166-2 code such as CA-ON."
            ),
        )

    if not axis:
        # No sub-national dimension: one country-wide row is the answer, and
        # the answer is the standard rate. Both ``national`` and ``federal``
        # rows are candidates, because a country whose only row is the federal
        # layer (a zero-rate placeholder, say) still answers with it.
        #
        # These rows are NOT summed. They were, and it was wrong in a way that
        # only showed up on the shipped data rather than in any test: a country
        # carrying a reduced tier alongside its standard rate resolved to the
        # two added together, so Germany reported 26 % (19 + 7), the United
        # Kingdom 25 % and France 35.5 %. Every test written before this read
        # a single-row fixture, which is the one shape the bug cannot appear
        # in. Rate tiers are alternatives - one supply is charged at one of
        # them - and only sub-national rows ever combine.
        countrywide = national + federal

        # Nothing in force claims to be the standard rate, and from here two
        # very different tables look identical.
        #
        # The one being preserved: a country with no standard rate on file
        # anywhere. Nothing is flagged because the flag postdates the row, or
        # because the country only ever had one rate. Its single row is the
        # answer and the picker below still gives it.
        #
        # The one being caught: a country whose standard rate is on file and
        # whose window does not contain this date. What is in force is a
        # reduced tier that runs alongside the standard rate rather than
        # before it, and promoting it answers a question about the standard
        # rate with a number from another tier - Germany 7 % for 1990,
        # Britain 0 %, Russia 10 % for 2010, all reported as resolved.
        if not any(row.is_default for row in countrywide):
            dormant = _dormant_default_rows(rows, country, as_of)
            if dormant and not _is_earlier_period(countrywide, dormant):
                windows = ", ".join(
                    f"{row.tax_code or row.tax_name} from {row.effective_from or 'any date'}"
                    f"{' to ' + row.effective_to if row.effective_to else ''}"
                    for row in dormant
                )
                return TaxResolution(
                    country_code=country,
                    subdivision_code=None,
                    subdivision_name=None,
                    status="default_rate_not_in_force",
                    combined_rate_pct=None,
                    federal_rate_pct=format_rate(_rate(federal[0])) if federal else None,
                    as_of=as_of,
                    reason=(
                        f"Country {country} has a standard rate on file ({windows}) and it was not in "
                        f"force on {as_of}. The {len(countrywide)} country-wide rate(s) that were in "
                        f"force are other tiers, so no standard rate is given for this date."
                    ),
                )

        standard, ambiguity = _country_wide_standard(countrywide)
        if standard is None:
            return TaxResolution(
                country_code=country,
                subdivision_code=None,
                subdivision_name=None,
                status="default_rate_ambiguous",
                combined_rate_pct=None,
                federal_rate_pct=format_rate(_rate(federal[0])) if federal else None,
                as_of=as_of,
                reason=(
                    f"Country {country} has {len(countrywide)} country-wide rates in force on {as_of} "
                    f"and {ambiguity}, so which one is the standard rate cannot be read from the data. "
                    f"Flag exactly one of them is_default."
                ),
            )
        return TaxResolution(
            country_code=country,
            subdivision_code=None,
            subdivision_name=None,
            status="national",
            combined_rate_pct=format_rate(_rate(standard)),
            federal_rate_pct=format_rate(_rate(federal[0])) if federal else None,
            as_of=as_of,
            components=[
                RateComponent(
                    tax_code=standard.tax_code,
                    tax_name=standard.tax_name,
                    rate_pct=format_rate(_rate(standard)),
                    combination=standard.combination,
                    base="consideration",
                    effective_rate_pct=format_rate(_rate(standard)),
                )
            ],
        )

    local = [r for r in subnational if normalize_subdivision(r.subdivision_code) == subdivision]
    federal_rate = sum((_rate(r) for r in federal), Decimal("0"))
    federal_text = format_rate(_rate(federal[0])) if federal else None

    # Sub-national rows that do not say which subdivision they are for. The
    # table's check constraint forbids these, but there is one window where
    # they exist anyway and it is the window that matters: an upgraded install
    # between the schema heal adding ``subdivision_code`` empty and the boot
    # repair filling it. In that state every Canadian rate is present, none is
    # labelled, and a resolver that trusted the labelling would find no
    # provincial row for Ontario, note that Ontario is a province it knows,
    # and answer "federal only, 5 %" - a wrong total, delivered with the same
    # confidence as Alberta's correct one.
    #
    # So the federal-only claim is withheld while any row is unlabelled. That
    # claim is the one made from an *absence*, and an absence proves nothing
    # when the evidence has not been indexed yet. A province that did match a
    # row is still answered: that answer rests on a row that is present, not
    # on one that is missing.
    unlabelled = [r for r in subnational if normalize_subdivision(r.subdivision_code) is None]

    replacing = [r for r in local if r.combination == "replaces_federal"]
    if replacing:
        if len(replacing) > 1:
            raise TaxRuleError(
                "multiple_replacing_rates",
                f"{country}/{subdivision} has {len(replacing)} rates that each replace the federal one "
                f"on {as_of}; only one can.",
            )
        harmonised = replacing[0]
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=name,
            status="harmonised",
            combined_rate_pct=format_rate(_rate(harmonised)),
            federal_rate_pct=federal_text,
            as_of=as_of,
            components=[
                RateComponent(
                    tax_code=harmonised.tax_code,
                    tax_name=harmonised.tax_name,
                    rate_pct=format_rate(_rate(harmonised)),
                    combination=harmonised.combination,
                    base="consideration",
                    effective_rate_pct=format_rate(_rate(harmonised)),
                )
            ],
        )

    if not local and not is_known_subdivision(country, subdivision or ""):
        # No rate on file for this subdivision, and it is not one the platform
        # enumerates - so whether it levies a tax of its own is genuinely
        # unknown, and the federal layer alone would present that gap as a
        # priced answer. Texas, whose state rate we have never loaded.
        #
        # Checked here rather than before the rows are looked at, and that
        # ordering is the point: a subdivision that carries a rate is known by
        # the fact that it carries one. Registry membership only has to decide
        # the case where nothing was found, which is where "levies nothing"
        # and "we have no idea" would otherwise be the same answer.
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=None,
            status="subdivision_unknown",
            combined_rate_pct=None,
            federal_rate_pct=federal_text,
            as_of=as_of,
            reason=(
                f"Subdivision {subdivision} is not one this platform carries rates for, so whether it "
                f"levies a tax of its own is unknown."
            ),
        )

    if not local and unlabelled:
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=name,
            status="subdivision_unknown",
            combined_rate_pct=None,
            federal_rate_pct=federal_text,
            as_of=as_of,
            reason=(
                f"Country {country} has {len(unlabelled)} sub-national rates on file that do not say "
                f"which subdivision they apply in, so whether {subdivision} levies one of its own "
                f"cannot be read from the data. Run the tax_subdivision_backfill repair."
            ),
        )

    if not local:
        # The subdivision is one we know, and it levies nothing of its own.
        # Alberta and the three territories. This is a real answer and must
        # not be confused with the unknown cases, which is the whole reason
        # the known-subdivision registry exists.
        return TaxResolution(
            country_code=country,
            subdivision_code=subdivision,
            subdivision_name=name,
            status="federal_only",
            combined_rate_pct=format_rate(federal_rate),
            federal_rate_pct=federal_text,
            as_of=as_of,
            components=[
                RateComponent(
                    tax_code=r.tax_code,
                    tax_name=r.tax_name,
                    rate_pct=format_rate(_rate(r)),
                    combination=r.combination,
                    base="consideration",
                    effective_rate_pct=format_rate(_rate(r)),
                )
                for r in federal
            ],
        )

    # Federal plus local. A stacking rate is charged on the same pre-tax
    # amount as the federal rate and so simply adds; a compounding one is
    # charged on the amount including the federal tax, which grosses it up by
    # the federal rate. Quebec is the worked example: 9.5 % compounding on a
    # 5 % federal rate came to 9.975 %, and when Quebec moved to a pre-tax
    # base on 2013-01-01 it raised the headline rate to that same 9.975 % so
    # the amount payable did not move.
    gross_up = Decimal("1") + federal_rate / Decimal("100")
    components = [
        RateComponent(
            tax_code=r.tax_code,
            tax_name=r.tax_name,
            rate_pct=format_rate(_rate(r)),
            combination=r.combination,
            base="consideration",
            effective_rate_pct=format_rate(_rate(r)),
        )
        for r in federal
    ]
    total = federal_rate
    compounded = False
    for row in local:
        rate = _rate(row)
        if row.combination == "compounds_on_federal":
            compounded = True
            effective = rate * gross_up
            base: Literal["consideration", "consideration_plus_federal"] = "consideration_plus_federal"
        else:
            effective = rate
            base = "consideration"
        total += effective
        components.append(
            RateComponent(
                tax_code=row.tax_code,
                tax_name=row.tax_name,
                rate_pct=format_rate(rate),
                combination=row.combination,
                base=base,
                effective_rate_pct=format_rate(effective),
            )
        )

    return TaxResolution(
        country_code=country,
        subdivision_code=subdivision,
        subdivision_name=name,
        status="compounded" if compounded else "stacked",
        combined_rate_pct=format_rate(total),
        federal_rate_pct=federal_text,
        as_of=as_of,
        components=components,
    )


# ── The write rules ──────────────────────────────────────────────────────────


def validate_tax_row(
    country_code: str,
    combination: str,
    subdivision_code: str | None,
    *,
    rate_pct: str | None = None,
    country_has_federal_layer: bool = False,
) -> None:
    """Refuse a tax row that cannot be resolved correctly.

    The failure this exists to remove is the quiet one. A Canadian provincial
    rate written without saying it is provincial inherits ``national``, drops
    out of every per-province lookup, and the province then answers with the
    federal 5 % - a wrong total that no error, no log line and no health check
    reports, because nothing was missing, only mislabelled.

    Args:
        country_code: ISO 3166-1 alpha-2 of the row being written.
        combination: The proposed ``combination`` value.
        subdivision_code: The proposed subdivision, already normalized.
        rate_pct: The proposed rate, as it will be stored. Optional only
            because a caller may be validating a row it is not writing the
            rate of; when given it must parse as a decimal, because the column
            is a string and an unparseable rate is not caught until a lookup
            reaches it, at which point it is a 500 on a read of stored data
            rather than a rejection of the write that caused it.
        country_has_federal_layer: Whether the table already holds a
            ``federal`` row for this country. A country with a federal layer
            has a sub-national structure by definition, so ``national`` is
            meaningless there and is rejected. Callers that cannot query
            (the seed loader) leave this ``False`` and rely on the registry
            check, which covers Canada either way.

    Raises:
        TaxRuleError: With a ``code`` naming which rule was broken.
    """
    country = country_code.strip().upper()
    subdivision = normalize_subdivision(subdivision_code)

    if combination not in TAX_COMBINATIONS:
        raise TaxRuleError(
            "unknown_combination",
            f"combination {combination!r} is not one of {', '.join(TAX_COMBINATIONS)}.",
        )

    is_subnational = combination in SUBNATIONAL_COMBINATIONS

    if is_subnational and subdivision is None:
        raise TaxRuleError(
            "subdivision_required",
            f"combination {combination!r} describes a rate belonging to one subdivision, so "
            f"subdivision_code is required. Without it the rate is invisible to every per-subdivision "
            f"lookup and the subdivision reads as though it levied nothing.",
        )

    if not is_subnational and subdivision is not None:
        raise TaxRuleError(
            "subdivision_not_allowed",
            f"combination {combination!r} describes a country-wide rate, so it cannot name the "
            f"subdivision {subdivision}. Use one of {', '.join(SUBNATIONAL_COMBINATIONS)} instead.",
        )

    if subdivision is not None:
        if not SUBDIVISION_CODE_RE.fullmatch(subdivision):
            raise TaxRuleError(
                "subdivision_malformed",
                f"subdivision_code {subdivision!r} is not an ISO 3166-2 code such as CA-ON.",
            )
        if not subdivision.startswith(f"{country}-"):
            raise TaxRuleError(
                "subdivision_country_mismatch",
                f"subdivision_code {subdivision!r} does not belong to country {country}.",
            )
        if has_subdivision_axis(country) and not is_known_subdivision(country, subdivision):
            raise TaxRuleError(
                "subdivision_unknown",
                f"{subdivision!r} is not a subdivision of {country} that this platform carries.",
            )

    if combination == "national" and (has_subdivision_axis(country) or country_has_federal_layer):
        raise TaxRuleError(
            "national_not_allowed",
            f"Country {country} charges tax by subdivision, so a rate there cannot be country-wide "
            f"without saying so. Use 'federal' for the country-wide layer, or one of "
            f"{', '.join(SUBNATIONAL_COMBINATIONS)} together with a subdivision_code.",
        )

    if rate_pct is not None:
        try:
            Decimal(rate_pct)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise TaxRuleError(
                "rate_not_numeric",
                f"rate_pct {rate_pct!r} is not a number. The column stores rates as text, so a "
                f"rate that does not parse is accepted on write and only fails later, on a read "
                f"of the subdivision it belongs to.",
            ) from exc

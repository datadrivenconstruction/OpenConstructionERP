# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The statutory limitation regimes for defect claims, and the dates they produce.

A German construction contract runs the limitation of its defect claims
(Verjährung der Mängelansprüche) on one of two clocks, and which one applies is
decided by the contract rather than by the building. Where the parties agreed the
VOB/B, the period for building works is four years. Where they did not, the BGB
gives five. That one year is the whole point: a claim
brought in the fifth year of a VOB/B contract is out of time, and a claim
abandoned in the fifth year of a BGB contract was still good. A register that
records a period without recording which regime produced it is asserting a date
it cannot justify.

**Nothing here is required, and nothing here happens on its own.** A warranty
entry carries no regime until somebody chooses one. An entry with no regime is
left exactly as it was: no period is derived, no date is rewritten, no finding is
raised and nothing is claimed about why it ends when it ends. A team working
under a legal system with no such regime never has to pick one and never sees one.

Scope, stated here so nobody reads four years as universal. VOB/B § 13 Abs. 4
Nr. 1 applies only where the contract agreed no period of its own, and it sets
shorter periods for parts of industrial firing installations exposed to flame or
flue gas and for mechanical and electrical/electronic plant whose maintenance the
client did not entrust to the contractor. The BGB period likewise covers a
Bauwerk and the planning or supervision work done for one; other work has its own
shorter period. Every one of those cases is recorded the same way: enter the
agreed period by hand. The record then disagrees with the regime it names, and
:mod:`app.modules.defects_liability.validators` reports the disagreement instead
of overwriting it, because the contract outranks the default and only a person
knows which one this contract is.

The regimes are written down here as plain frozen values rather than seeded into
a table, unlike :mod:`app.modules.payment_clock.data`, because there are two of
them and a deployment has no reason to edit either. The field names
(``statute``, ``statute_reference``, ``jurisdiction``, ``country_code``,
``notes``) are that module's, so the platform says the same thing about a statute
in both places. No ORM, database, FastAPI or Pydantic dependency, exactly like
:mod:`app.modules.defects_liability.register`.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# What a period counts from. Both shipped regimes count from Abnahme (acceptance
# of the works); the field exists so a future regime that counts from something
# else cannot be added without saying so.
LIMITATION_STARTS: tuple[str, ...] = ("acceptance",)


class LimitationRegime(StrEnum):
    """The legal regime a defect-claim limitation period is derived from."""

    DE_VOB_B = "de_vob_b"  # VOB/B agreed: four years for building works
    DE_BGB = "de_bgb"  # no VOB/B: the BGB's five years
    EG_CIVIL_651 = "eg_civil_651"  # Egypt: decennial liability of the architect and the contractor
    FR_CIVIL_1792_6 = "fr_civil_1792_6"  # France: garantie de parfait achèvement, one year
    FR_CIVIL_1792_3 = "fr_civil_1792_3"  # France: garantie biennale de bon fonctionnement, two years
    FR_CIVIL_1792 = "fr_civil_1792"  # France: responsabilité décennale, ten years
    SA_SBC_DECENNIAL = "sa_sbc_decennial"  # Saudi Arabia: decennial liability under the building code law


@dataclass(frozen=True)
class LimitationRegimeSpec:
    """One statutory limitation regime, with the provision it comes from.

    ``months`` is the statutory default period, and ``statute`` /
    ``statute_reference`` are the reason the register gives for the date it
    shows. They are legal citations, not prose, so they read the same in every
    language and are never translated; the sentence around them is composed in
    the reader's language on the screen.
    """

    code: str
    jurisdiction: str
    country_code: str
    statute: str
    statute_reference: str
    months: int
    starts_from: str
    notes: str


LIMITATION_REGIMES: tuple[LimitationRegimeSpec, ...] = (
    LimitationRegimeSpec(
        code=LimitationRegime.DE_VOB_B.value,
        jurisdiction="Germany",
        country_code="DE",
        statute="VOB/B § 13 Abs. 4 (Verjährung der Mängelansprüche)",
        statute_reference=(
            "§ 13 Abs. 4 Nr. 1 VOB/B (2016); the period runs from Abnahme of the whole works, or from the "
            "Teilabnahme of a self-contained part, under § 13 Abs. 4 Nr. 3 VOB/B"
        ),
        months=48,
        starts_from="acceptance",
        notes=(
            "Four years is the VOB/B default for building works and applies only where the contract agreed "
            "no period of its own, so a contract that names its own Verjährungsfrist governs and the period "
            "belongs in the record by hand. § 13 Abs. 4 Nr. 1 VOB/B sets shorter periods for parts of "
            "industrial firing installations exposed to flame or flue gas and for mechanical and "
            "electrical/electronic plant whose maintenance the client did not entrust to the contractor; "
            "those are entered by hand for the same reason. The VOB/B applies at all only where the parties "
            "agreed it, which is why the regime is a choice on the record rather than a property of the "
            "country the project is in."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.DE_BGB.value,
        jurisdiction="Germany",
        country_code="DE",
        statute="BGB § 634a Abs. 1 Nr. 2 (Verjährung der Mängelansprüche)",
        statute_reference="§ 634a Abs. 1 Nr. 2 BGB; the period runs from Abnahme under § 634a Abs. 2 BGB",
        months=60,
        starts_from="acceptance",
        notes=(
            "Five years is the statutory period for a Bauwerk and for the planning or supervision work done "
            "for one, and it is what applies when the parties did not agree the VOB/B. Work that is not a "
            "Bauwerk has its own shorter period under § 634a Abs. 1 BGB, so an entry covering such work "
            "carries its period by hand. Where the contractor concealed the defect fraudulently the ordinary "
            "limitation rules displace this period entirely (§ 634a Abs. 3 BGB); that is a legal finding "
            "about a particular defect and nothing a register can compute."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.EG_CIVIL_651.value,
        jurisdiction="Egypt",
        country_code="EG",
        statute="Civil Code (Law 131/1948) Art. 651 (decennial liability)",
        statute_reference=(
            "Art. 651 Egyptian Civil Code: ten years from delivery of the works; the claim lapses three years "
            "after the collapse or the discovery of the defect (Art. 654)"
        ),
        months=120,
        starts_from="acceptance",
        notes=(
            "The architect and the contractor are jointly liable for ten years for the total or partial collapse "
            "of buildings and other fixed structures they built, and for defects that threaten their stability, "
            "even where the defect lies in the ground or the owner approved the faulty work, unless the structure "
            "was meant to last less than ten years. The ten years run from delivery, recorded here as the "
            "acceptance date. An architect who only designed is liable only for design defects (Art. 652), and a "
            "clause that excludes or limits the liability is void. A claim must be brought within three years of "
            "the collapse or of the discovery of the defect (Art. 654), a second clock this register does not "
            "compute because it starts on an event only a person can record. Read in secondary summaries of the "
            "Civil Code; the article numbering of 652 and 653 differs between sources."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.FR_CIVIL_1792_6.value,
        jurisdiction="France",
        country_code="FR",
        statute="Code civil art. 1792-6 (garantie de parfait achèvement)",
        statute_reference=(
            "Art. 1792-6 Code civil: one year from réception; for public works also CCAG-Travaux 2021 art. 44.1"
        ),
        months=12,
        starts_from="acceptance",
        notes=(
            "For one year from réception the contractor repairs every defect reserved at réception or notified "
            "during the year, whatever its seriousness. Réception with reservations starts the year too. The "
            "retenue de garantie is released at its end unless the client objected (loi 71-584, art. 2)."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.FR_CIVIL_1792_3.value,
        jurisdiction="France",
        country_code="FR",
        statute="Code civil art. 1792-3 (garantie biennale de bon fonctionnement)",
        statute_reference="Art. 1792-3 Code civil: at least two years from réception",
        months=24,
        starts_from="acceptance",
        notes=(
            "Equipment that can be removed without damaging the structure (dissociable elements) must work for "
            "at least two years from réception. The contract may agree a longer period, entered by hand."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.FR_CIVIL_1792.value,
        jurisdiction="France",
        country_code="FR",
        statute="Code civil art. 1792 and 1792-4-1 (responsabilité décennale)",
        statute_reference="Art. 1792 and 1792-4-1 Code civil: ten years from réception",
        months=120,
        starts_from="acceptance",
        notes=(
            "Builders are liable as of right for ten years from réception for damage that compromises the "
            "solidity of the works or makes them unfit for their purpose. Builders must insure it (Code des "
            "assurances L241-1) and the owner must take out dommages-ouvrage insurance (L242-1); neither "
            "insurance is a period this register computes."
        ),
    ),
    LimitationRegimeSpec(
        code=LimitationRegime.SA_SBC_DECENNIAL.value,
        jurisdiction="Saudi Arabia",
        country_code="SA",
        statute="Saudi Building Code Application Law (Royal Decree M/43 of 1438H), Art. 29",
        statute_reference=(
            "Art. 29 Saudi Building Code Application Law: the contractor, the designer and the supervising "
            "consultant are jointly liable for ten years from completion"
        ),
        months=120,
        starts_from="acceptance",
        notes=(
            "The contractor, the designer and the supervising consultant are jointly liable for ten years for "
            "the total or partial collapse of the building and for defects that threaten its stability or "
            "safety. The ten years run from completion and handover for occupation, recorded here as the "
            "acceptance date. Inherent defects insurance covering the same decade is compulsory for "
            "qualifying private projects (see MANDATORY_DEFECTS_INSURANCE). Read "
            "in secondary summaries; the window for bringing a claim after a defect appears was not confirmed "
            "and is not computed."
        ),
    ),
)

# Canonical ordered tuple of the shipped regime codes, exposed so the schemas,
# the service, the validators and the tests share one source of truth. Mirrored
# by ``LimitationRegimeLiteral`` in
# :mod:`app.modules.defects_liability.schemas`, which is what the API rejects on.
ALL_LIMITATION_REGIMES: tuple[str, ...] = tuple(spec.code for spec in LIMITATION_REGIMES)

_BY_CODE: dict[str, LimitationRegimeSpec] = {spec.code: spec for spec in LIMITATION_REGIMES}

#: Insurance a country makes compulsory against the defects its decennial
#: liability covers. Data shown beside the limitation regime; nothing enforces
#: it. Saudi Arabia: Cabinet Resolution 509 made inherent defects
#: insurance compulsory for qualifying private projects, starting on 2020-05-02
#: in the main cities of five regions. The current
#: scope (which regions and building types in 2025-2026) was not confirmed in
#: a primary text, so the row is flagged for review.
MANDATORY_DEFECTS_INSURANCE: dict[str, dict[str, object]] = {
    "SA": {
        "name": "Inherent defects insurance (IDI)",
        "statute_reference": "Cabinet Resolution 509; standard policy wording of the insurance regulator",
        "source_url": "https://www.hfw.com/insights/ksa-mandates-inherent-defects-insurance-policy-for-projects-oct-2021",
        "read_date": "2026-10-19",
        "effective_date": "2020-05-02",
        "years": 10,
        "limitation_regime": LimitationRegime.SA_SBC_DECENNIAL.value,
        "covers": "Structural collapse and defects threatening stability or safety of the building",
        "applies_to": "Qualifying private projects; at the start in 2020, those in the main cities of five regions",
        "needs_expert_review": True,
        "review_reason": "The scope in force in 2025-2026 and the phased list of regions were not read.",
    },
}


@dataclass(frozen=True)
class DerivedPeriod:
    """The period a chosen regime produces from a start date.

    ``months`` is the regime's statutory period and ``end_date`` is the day it
    runs out, counted from the acceptance date. ``spec`` is carried along so a
    caller can name the provision without a second lookup.
    """

    months: int
    end_date: date
    spec: LimitationRegimeSpec


def regime_for(code: str | None) -> LimitationRegimeSpec | None:
    """The regime with this code, or ``None``.

    ``None`` in means no regime was chosen, which is the state every entry starts
    in. An unrecognised code also returns ``None`` rather than raising, matching
    the vocabulary convention in
    :mod:`app.modules.defects_liability.register`: a stray value fails to match
    and is silently inert, it never breaks a listing.

    Args:
        code: The stored regime code, or ``None`` when none was chosen.

    Returns:
        The matching :class:`LimitationRegimeSpec`, or ``None``.
    """
    if code is None:
        return None
    return _BY_CODE.get(code)


def add_months(start: date, months: int) -> date:
    """The day ``months`` months after ``start``, clamped to a real calendar day.

    German limitation periods are counted the way § 188 Abs. 2 BGB counts them:
    the period ends with the day of the final month whose number matches the day
    the period started on. § 188 Abs. 3 BGB settles the awkward case - where that
    month has no such day, the period ends on its last day - which is what the
    clamp below does, so an acceptance on 31 August plus six months ends on 28 or
    29 February rather than on a date that does not exist.

    § 187 Abs. 1 BGB excludes the day of the event itself from the count, so the
    period runs from the day after Abnahme and expires at the end of the
    corresponding day. The corresponding day is the one recorded here, because it
    is the last day on which a claim can still be brought and therefore the date
    a quantity surveyor writes down.

    Args:
        start: The day the period counts from (the acceptance date).
        months: How many months the period runs. Zero returns ``start``.

    Returns:
        The last day of the period.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def derive_period(code: str | None, start: date | None) -> DerivedPeriod | None:
    """The period the chosen regime produces, or ``None`` when it produces none.

    Returns ``None`` - deriving nothing at all - in the three cases where there
    is nothing honest to say: no regime was chosen, the code is not one this
    build ships, or no acceptance date is recorded so there is nothing to count
    from. Inventing a date from a missing start would be the one failure this
    whole module exists to prevent.

    Args:
        code: The chosen regime code, or ``None``.
        start: The acceptance date the period counts from, or ``None``.

    Returns:
        A :class:`DerivedPeriod`, or ``None``.
    """
    spec = regime_for(code)
    if spec is None or start is None:
        return None
    return DerivedPeriod(months=spec.months, end_date=add_months(start, spec.months), spec=spec)


def limitation_start(warranty_start_date: date | None, handover_date: date | None) -> date | None:
    """The acceptance date a limitation period counts from, or ``None``.

    Both shipped regimes run from Abnahme. An entry records that date as its
    ``warranty_start_date`` when the two differ (a warranty that was agreed to
    start later than handover), and otherwise as its ``handover_date``, so the
    explicitly recorded start wins and the handover date is the fallback. When
    neither is set nothing is counted from.

    Args:
        warranty_start_date: The recorded warranty start, if any.
        handover_date: The recorded handover date, if any.

    Returns:
        The date to count from, or ``None`` when the entry records neither.
    """
    return warranty_start_date or handover_date


def describe(spec: LimitationRegimeSpec, end_date: date | None = None) -> str:
    """One English sentence naming the provision, the period and its end date.

    Used in validation findings and log lines, which are English throughout the
    platform. The screen does not use this: it composes the same sentence in the
    reader's language from ``statute``, ``months`` and the end date, so a German
    user reads German around a citation that is German already.

    Args:
        spec: The regime being described.
        end_date: The computed end of the period, if one could be computed.

    Returns:
        A sentence with no trailing full stop.
    """
    years, remainder = divmod(spec.months, 12)
    if remainder == 0:
        period = f"{years} year{'s' if years != 1 else ''}"
    else:
        period = f"{spec.months} months"
    sentence = f"{spec.statute} gives {period} from Abnahme"
    if end_date is not None:
        sentence += f", so the period ends on {end_date.isoformat()}"
    return sentence


__all__ = [
    "ALL_LIMITATION_REGIMES",
    "LIMITATION_REGIMES",
    "MANDATORY_DEFECTS_INSURANCE",
    "LIMITATION_STARTS",
    "DerivedPeriod",
    "LimitationRegime",
    "LimitationRegimeSpec",
    "add_months",
    "derive_period",
    "describe",
    "limitation_start",
    "regime_for",
]

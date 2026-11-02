# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country regime registry - what each country does to an invoice.

Three acts, and they are architecturally different acts, not three flavours of
one act:

Every country named as an example below carries its ISO code in parentheses,
and a test parses those codes: each must be a ``COUNTRY_REGIMES`` entry whose
deciding act is the class it illustrates. Name a country here that the
registry does not hold, or under a class its row does not declare, and the
suite says so.

``clearance``
    Pre-issuance. The tax authority validates the document and returns an
    identifier, and the invoice is not legally valid without it. Mexico (MX)
    returns a UUID for a CFDI, Brazil (BR) a chave de acesso for an NF-e,
    Italy (IT) a protocol number from SdI, Poland (PL) a KSeF number, Romania
    (RO) an upload index, Saudi Arabia (SA) a cryptographic stamp, India (IN)
    an IRN, Egypt (EG) a document UUID. The document cannot be handed to the
    buyer until the authority has answered.

``reporting``
    Post-issuance. The invoice is valid the moment it is issued and is reported
    to the authority afterwards, inside a deadline. Spain (ES, SII and
    Verifactu) and Hungary (HU, RTIR) work this way.

``network``
    No authority at all. The document is routed to the buyer over an agreed
    network - Peppol BIS Billing 3.0, XRechnung into the German (DE) public
    sector, Peppol BIS into the Belgian (BE) and Irish (IE) supply chains.
    There is nothing to clear, so what this module records for these countries
    is routing state.

Countries that do more than one of them
=======================================
A country can do two of these acts at once, and calling such a country by one
of the three names alone states something false about it. France (FR) routes
the document to the buyer over a network of accredited platforms and
separately reports transaction and payment data to the DGFiP. Saudi Arabia
(SA) clears its standard tax invoices before they reach the buyer and has its
simplified invoices reported within 24 hours of issue, so its row names
clearance as the deciding act and reporting beside it. A row is classed by what
it declares, and this paragraph names every row the registry classes hybrid.

``regime`` therefore keeps naming the act that decides what a successful answer
means, and ``additional_regimes`` names the other acts the same country also
requires. ``regime_class`` reads ``hybrid`` for any entry that names more than
one, so a country that does two things is not filed under a name that describes
one of them. It is deliberately a derived value and not a fourth entry in
``REGIMES``: the terminal state of a submission is decided by the act it was a
submission under, and "hybrid" would leave that undecidable.

When the obligation starts, and who it starts for
=================================================
A regime is not in force everywhere the day it is legislated. The obligation to
receive and the obligation to issue commonly start years apart, and a mandate
usually arrives in waves keyed to taxpayer size or turnover rather than all at
once. ``commencement`` carries those waves as :class:`CommencementPhase` rows,
one per obligation and wave, and ``scope`` says in words who the regime covers
today. Without them the registry can say what a country does but not whether it
does it to this taxpayer yet, which is the question an operator actually asks.

Every phase names its source and the date that source was read, and the fields
are required rather than optional, because a commencement date without a
citation is indistinguishable from a remembered one and ages silently.
``legal_status`` separates a date that is in force from one that is enacted but
future and from one that is only announced; collapsing those three would let the
product answer "yes, from January" about a wave that has not been legislated.

Why the distinction is in the data and not in the code
======================================================
A single "submit and wait" code path would have to guess what a successful
answer means. Under clearance a success carries an identifier that has to be
printed on the invoice; under reporting a success is an acknowledgement that
changes nothing on the document; under network exchange a success is a delivery
receipt. Those are three different terminal states, so the regime decides the
terminal state rather than the adapter guessing it.

``en16931_profile`` is the one place this module touches document generation.
Where it is set, the country's format is one the platform already builds - the
EN 16931 engine in :mod:`app.modules.einvoice`, which ships CII and UBL and ten
profiles. Where it is empty the national format is outside that engine (CFDI,
NF-e, FatturaPA, KSeF FA(3), ZATCA, the Indian IRP schema, SII, RTIR), and the
caller supplies the payload. Nothing here reimplements a byte of EN 16931.

Country names, platform names and national field names are data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

REGIME_CLEARANCE = "clearance"
REGIME_REPORTING = "reporting"
REGIME_NETWORK = "network"

REGIMES: tuple[str, ...] = (REGIME_CLEARANCE, REGIME_REPORTING, REGIME_NETWORK)

# Not a fourth act, and deliberately not a fourth member of ``REGIMES``. It is
# the class of a country that performs more than one of the three, derived from
# the acts the entry names rather than stored beside them, so the two can never
# disagree.
REGIME_HYBRID = "hybrid"

REGIME_CLASSES: tuple[str, ...] = (*REGIMES, REGIME_HYBRID)

# Profile columns a regime can demand. Named here so the completeness rule can
# report a missing field by the name the operator sees on the form.
PROFILE_FIELDS: tuple[str, ...] = (
    "tax_registration_id",
    "network_participant_id",
    "certificate_reference",
)

# The three obligations a commencement date can attach to. They are separate
# because they commence separately: a business is commonly obliged to receive an
# electronic invoice years before it is obliged to issue one, and one date
# standing for both would tell half the population the wrong year.
OBLIGATION_RECEIVE = "receive"
OBLIGATION_ISSUE = "issue"
OBLIGATION_REPORT = "report"

OBLIGATIONS: tuple[str, ...] = (OBLIGATION_RECEIVE, OBLIGATION_ISSUE, OBLIGATION_REPORT)

# How firm a dated phase is. ``announced`` is not a weaker ``in_force``, it is a
# different kind of claim: a plan published by a ministry that no statute yet
# carries. A model that cannot tell "not yet" from "no" answers confidently and
# wrongly about every date before the one it holds.
LEGAL_STATUS_IN_FORCE = "in_force"
LEGAL_STATUS_ENACTED = "enacted"
LEGAL_STATUS_ANNOUNCED = "announced"

LEGAL_STATUSES: tuple[str, ...] = (
    LEGAL_STATUS_IN_FORCE,
    LEGAL_STATUS_ENACTED,
    LEGAL_STATUS_ANNOUNCED,
)

# What the cancellation window is counted against. The default is what the field
# has always meant; the alternative exists because a rule anchored to the fiscal
# year of issue is a calendar and not a window, and expressing it as a count of
# days is wrong by up to a year depending on the month the invoice was issued in.
CANCELLATION_BASIS_DAYS = "days_from_clearance"
CANCELLATION_BASIS_FISCAL_YEAR = "fiscal_year_of_issue"
# The platform publishes its own window and it is read from the platform at the
# moment of cancelling, not shipped here. A day count copied from a guide would go
# stale the day the authority changes it, and the platform refuses late requests
# itself, so the adapter reads the window when it cancels.
CANCELLATION_BASIS_AUTHORITY = "read_from_authority"

CANCELLATION_BASES: tuple[str, ...] = (
    CANCELLATION_BASIS_DAYS,
    CANCELLATION_BASIS_FISCAL_YEAR,
    CANCELLATION_BASIS_AUTHORITY,
)


@dataclass(frozen=True)
class CommencementPhase:
    """One wave of one obligation, with the source it was read from.

    The provenance fields are required arguments and not defaulted ones on
    purpose. A date in this registry is a date a business will plan around, and
    an uncited one cannot be rechecked, cannot be aged and cannot be told apart
    from a date somebody remembered. Requiring them at construction makes an
    unsourced phase impossible to write rather than merely discouraged.
    """

    # One of ``OBLIGATIONS``.
    obligation: str
    # ISO 8601 ``YYYY-MM-DD``. A string rather than a ``date`` because it travels
    # through ``regime_as_dict`` into JSON and into the validation context, and a
    # value that survives that trip unchanged is one fewer conversion to get
    # wrong. Empty means the wave is known but its date is not yet fixed.
    effective_date: str
    # Who this wave reaches, in the words the rule uses.
    scope: str
    # One of ``LEGAL_STATUSES``.
    legal_status: str
    # The official page the date was taken from.
    source_url: str
    # ISO 8601 ``YYYY-MM-DD``: when that page was read. The date ages the claim,
    # which a URL alone does not.
    read_date: str
    # The turnover or size step that opens this wave, currency qualified. Free
    # text: "SAR 3000000 annual turnover" is a threshold a reader can act on and
    # a number without its currency is not.
    threshold: str = ""
    notes: str = ""

    @property
    def is_dated(self) -> bool:
        """Whether this phase has a date at all, as opposed to only a scope."""
        return bool(self.effective_date)


@dataclass(frozen=True)
class CountryRegime:
    """What one country does to an invoice, and what it needs to do it."""

    country: str
    regime: str
    platform: str
    label: str
    # What the authority hands back on success, in the words the accountant will
    # hear it called. An empty string means the platform returns no identifier.
    identifier_label: str
    # National format key. Free text: it names a format, it does not select code.
    document_format: str
    # The ``app.modules.einvoice`` profile key that produces this document, or ""
    # when the national format is outside that engine.
    en16931_profile: str = ""
    # Profile columns that must be filled before this country will accept a
    # submission at all.
    profile_fields: tuple[str, ...] = ()
    # National fields the EN 16931 semantic model has nowhere to put, carried on
    # the document in ``country_fields``.
    document_fields: tuple[str, ...] = ()
    # Fields the user may fill in on a document that no submission requires, such
    # as the dated invoice mentions the mentions catalogue checks. Kept apart from
    # ``document_fields`` because those are mandatory for every document.
    optional_document_fields: tuple[str, ...] = ()
    # Keys of the registration's ``settings`` the country's rules read, such as
    # the issuer's company size.
    profile_setting_fields: tuple[str, ...] = ()
    # Days from clearance inside which a cancellation is still accepted. ``None``
    # means the platform has no cancellation flow at all and the only correction
    # is a further document - which is a different act with different accounting,
    # so it must not be modelled as a late cancellation.
    cancellation_window_days: int | None = None
    # What ``cancellation_window_days`` is counted against. One of
    # ``CANCELLATION_BASES``.
    cancellation_basis: str = CANCELLATION_BASIS_DAYS
    correction_mechanism: str = "credit note"
    # The other acts this country also performs, drawn from ``REGIMES``. Empty
    # for a country that does one thing, which is most of them.
    additional_regimes: tuple[str, ...] = ()
    # Who the regime covers today, in words. Separate from the phases below
    # because the phases say when a wave opens and this says where the waves
    # have got to, which is the question asked far more often.
    scope: str = ""
    # Every wave of every obligation, each carrying its own source.
    commencement: tuple[CommencementPhase, ...] = ()
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # Pack-owned lifecycle profile: deadlines, grouping, hash chain, QR and the
    # country rule ids they raise. Read by :mod:`lifecycle`; empty means none.
    lifecycle: dict[str, Any] = field(default_factory=dict)
    # Markets the row belongs to, for market scoping.
    markets: tuple[str, ...] = ()

    @property
    def is_cancellable(self) -> bool:
        """Whether the platform accepts a cancellation of a cleared document.

        A window the platform publishes at runtime is a window, even though no
        day count is stored for it here.
        """
        return self.cancellation_window_days is not None or self.cancellation_basis == CANCELLATION_BASIS_AUTHORITY

    @property
    def regimes(self) -> tuple[str, ...]:
        """Every act this country performs, the deciding one first."""
        return (self.regime, *self.additional_regimes)

    @property
    def is_hybrid(self) -> bool:
        """Whether this country performs more than one of the three acts."""
        return bool(self.additional_regimes)

    @property
    def regime_class(self) -> str:
        """``hybrid`` for a country that does more than one act, else the act.

        Derived rather than stored: a country's class is a fact about the acts
        it performs, and a second field holding it would be a second place for
        that fact to be wrong.
        """
        return REGIME_HYBRID if self.is_hybrid else self.regime

    def phases_for(self, obligation: str) -> tuple[CommencementPhase, ...]:
        """Every wave of one obligation, earliest dated first, undated last."""
        wanted = (obligation or "").strip().lower()
        matching = [p for p in self.commencement if p.obligation == wanted]
        return tuple(sorted(matching, key=lambda p: (not p.is_dated, p.effective_date)))


# The catalogue is pack data, one JSON file per country under
# ``app/core/country_data/einvoice_mandates``. Core keeps the schema and the
# loader; a country is added or corrected by editing its file, not this module.
MANDATES_DIR = Path(__file__).resolve().parents[2] / "core" / "country_data" / "einvoice_mandates"
MANDATE_SCHEMA = "oe.einvoice_mandate/1"
_TUPLE_FIELDS = frozenset(
    {"profile_fields", "document_fields", "optional_document_fields", "profile_setting_fields", "additional_regimes"}
)


def _phase_from_json(raw: dict[str, Any]) -> CommencementPhase:
    known = {f.name for f in fields(CommencementPhase)}
    return CommencementPhase(**{k: v for k, v in raw.items() if k in known})


def regime_from_json(document: dict[str, Any]) -> CountryRegime:
    """Build one :class:`CountryRegime` from a mandate file's parsed JSON.

    Raises ``ValueError`` for a file of another schema or one whose country
    code disagrees with itself, because a silently skipped country reads as a
    country with no mandate.
    """
    if document.get("schema") != MANDATE_SCHEMA:
        raise ValueError(f"unknown mandate schema {document.get('schema')!r}")
    country = str(document.get("country") or "").strip().upper()
    if len(country) != 2:
        raise ValueError(f"mandate file has no ISO country code: {country!r}")
    known = {f.name for f in fields(CountryRegime)}
    kwargs: dict[str, Any] = {"country": country}
    for key, value in (document.get("regime") or {}).items():
        if key not in known or key == "country":
            continue
        if key in _TUPLE_FIELDS:
            value = tuple(value or ())
        elif key == "commencement":
            value = tuple(_phase_from_json(p) for p in value or ())
        kwargs[key] = value
    kwargs["lifecycle"] = dict(document.get("lifecycle") or {})
    kwargs["markets"] = tuple(document.get("markets") or (country,))
    return CountryRegime(**kwargs)


def load_country_regimes(directory: Path | None = None) -> dict[str, CountryRegime]:
    """Read every mandate file in ``directory``, keyed by country code."""
    folder = directory or MANDATES_DIR
    loaded: dict[str, CountryRegime] = {}
    for path in sorted(folder.glob("*.json")):
        entry = regime_from_json(json.loads(path.read_text(encoding="utf-8")))
        if entry.country in loaded:
            raise ValueError(f"two mandate files declare {entry.country}")
        loaded[entry.country] = entry
    return loaded


COUNTRY_REGIMES: dict[str, CountryRegime] = load_country_regimes()


SUPPORTED_COUNTRIES: tuple[str, ...] = tuple(sorted(COUNTRY_REGIMES))


def get_country_regime(country: str) -> CountryRegime | None:
    """Look up a country's regime by ISO 3166-1 alpha-2 code, case-insensitive.

    Returns ``None`` for a country this registry has no entry for. The caller
    must refuse rather than guess: assuming network exchange for an unknown
    country would let a clearance country's invoice leave without an identifier
    it is not valid without.
    """
    return COUNTRY_REGIMES.get((country or "").strip().upper())


def countries_by_regime(regime: str) -> tuple[str, ...]:
    """Every country whose deciding act is this one, sorted.

    The deciding act only. A hybrid country appears here under the act that
    decides what a successful submission means, not under the other acts it also
    performs; :func:`countries_performing` answers that wider question.
    """
    wanted = (regime or "").strip().lower()
    return tuple(sorted(code for code, entry in COUNTRY_REGIMES.items() if entry.regime == wanted))


def countries_performing(regime: str) -> tuple[str, ...]:
    """Every country that performs this act at all, deciding or additional."""
    wanted = (regime or "").strip().lower()
    return tuple(sorted(code for code, entry in COUNTRY_REGIMES.items() if wanted in entry.regimes))


def hybrid_countries() -> tuple[str, ...]:
    """Every country that performs more than one of the three acts, sorted."""
    return tuple(sorted(code for code, entry in COUNTRY_REGIMES.items() if entry.is_hybrid))


def phase_as_dict(phase: CommencementPhase) -> dict[str, Any]:
    """Flatten one commencement phase, provenance included.

    The source and the read date travel with the date rather than being dropped
    at the boundary. A reader who is told "1 January 2027" and not told where
    that came from cannot check it, and this registry is exactly the kind of
    data that goes stale between releases.
    """
    return {
        "obligation": phase.obligation,
        "effective_date": phase.effective_date,
        "scope": phase.scope,
        "threshold": phase.threshold,
        "legal_status": phase.legal_status,
        "source_url": phase.source_url,
        "read_date": phase.read_date,
        "notes": phase.notes,
    }


def _company_sizes(country: str) -> tuple[str, ...]:
    """The company sizes the mentions catalogue dates a country's waves by, in catalogue order."""
    from app.modules.einvoice_clearance.mentions import load_catalogue

    sizes = load_catalogue().get("phase_by_size", {}).get(country, {}).get("sizes") or {}
    return tuple(sizes)


def regime_as_dict(entry: CountryRegime) -> dict[str, Any]:
    """Flatten a regime for the validation context and the meta endpoint.

    Additive only. Every key this returned before it learned about commencement
    still means what it meant, because a reader that already parses this shape
    is a reader we cannot see.
    """
    return {
        "country": entry.country,
        "regime": entry.regime,
        "platform": entry.platform,
        "label": entry.label,
        "identifier_label": entry.identifier_label,
        "document_format": entry.document_format,
        "en16931_profile": entry.en16931_profile,
        "profile_fields": list(entry.profile_fields),
        "document_fields": list(entry.document_fields),
        "optional_document_fields": list(entry.optional_document_fields),
        "profile_setting_fields": list(entry.profile_setting_fields),
        "company_sizes": list(_company_sizes(entry.country)),
        "cancellation_window_days": entry.cancellation_window_days,
        "is_cancellable": entry.is_cancellable,
        "correction_mechanism": entry.correction_mechanism,
        "notes": entry.notes,
        # Added later. Absent from no entry: the defaults make a country that
        # does one act and states no commencement read exactly as it always did.
        "regime_class": entry.regime_class,
        "is_hybrid": entry.is_hybrid,
        "additional_regimes": list(entry.additional_regimes),
        "cancellation_basis": entry.cancellation_basis,
        "scope": entry.scope,
        "commencement": [phase_as_dict(p) for p in entry.commencement],
        # Country-specific facts that fit no shared column, such as the platform
        # model, the accepted syntaxes or the fines. Empty for most countries.
        "extra": dict(entry.extra),
        "lifecycle": dict(entry.lifecycle),
        "markets": list(entry.markets),
    }


__all__ = [
    "CANCELLATION_BASES",
    "CANCELLATION_BASIS_AUTHORITY",
    "CANCELLATION_BASIS_DAYS",
    "CANCELLATION_BASIS_FISCAL_YEAR",
    "COUNTRY_REGIMES",
    "LEGAL_STATUSES",
    "MANDATES_DIR",
    "LEGAL_STATUS_ANNOUNCED",
    "LEGAL_STATUS_ENACTED",
    "LEGAL_STATUS_IN_FORCE",
    "OBLIGATIONS",
    "OBLIGATION_ISSUE",
    "OBLIGATION_RECEIVE",
    "OBLIGATION_REPORT",
    "PROFILE_FIELDS",
    "REGIMES",
    "REGIME_CLASSES",
    "REGIME_CLEARANCE",
    "REGIME_HYBRID",
    "REGIME_NETWORK",
    "REGIME_REPORTING",
    "SUPPORTED_COUNTRIES",
    "CommencementPhase",
    "CountryRegime",
    "countries_by_regime",
    "countries_performing",
    "get_country_regime",
    "hybrid_countries",
    "load_country_regimes",
    "phase_as_dict",
    "regime_as_dict",
    "regime_from_json",
]

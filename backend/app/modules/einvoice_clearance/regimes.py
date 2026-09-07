# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country regime registry - what each country does to an invoice.

Three acts, and they are architecturally different acts, not three flavours of
one act:

``clearance``
    Pre-issuance. The tax authority validates the document and returns an
    identifier, and the invoice is not legally valid without it. Mexico returns
    a UUID for a CFDI, Brazil a chave de acesso for an NF-e, Italy a protocol
    number from SdI, Poland a KSeF number, Romania an upload index, Saudi Arabia
    a cryptographic stamp, India an IRN. The document cannot be handed to the
    buyer until the authority has answered.

``reporting``
    Post-issuance. The invoice is valid the moment it is issued and is reported
    to the authority afterwards, inside a deadline. Spain (SII and Verifactu)
    and Hungary (RTIR) work this way.

``network``
    No authority at all. The document is routed to the buyer over an agreed
    network - Peppol BIS Billing 3.0, XRechnung into the German public sector,
    Peppol BIS into the Belgian and Irish supply chains. There is nothing to
    clear, so what this module records for these countries is routing state.

Countries that do more than one of them
=======================================
Several countries do two of these acts at once, and calling such a country by
one of the three names alone states something false about it. France routes the
document to the buyer over a network of accredited platforms and separately
reports transaction and payment data to the DGFiP; Saudi Arabia clears standard
invoices and reports simplified ones; Greece, Croatia and Turkiye each pair a
national submission with a reporting duty of its own.

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
NF-e, FatturaPA, KSeF FA(2), ZATCA, the Indian IRP schema, SII, RTIR), and the
caller supplies the payload. Nothing here reimplements a byte of EN 16931.

Country names, platform names and national field names are data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

CANCELLATION_BASES: tuple[str, ...] = (CANCELLATION_BASIS_DAYS, CANCELLATION_BASIS_FISCAL_YEAR)


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

    @property
    def is_cancellable(self) -> bool:
        """Whether the platform accepts a cancellation of a cleared document."""
        return self.cancellation_window_days is not None

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


# The registry. One entry per country; adding a country is one entry and no code.
#
# The cancellation windows are the ones an accountant works to, and each is
# stated with what it actually means, because "30 days" and "the fiscal year of
# issue" are not the same kind of rule and collapsing them loses the difference.
COUNTRY_REGIMES: dict[str, CountryRegime] = {
    # ── Clearance ────────────────────────────────────────────────────────────
    "MX": CountryRegime(
        country="MX",
        regime=REGIME_CLEARANCE,
        platform="CFDI 4.0",
        label="Mexico - CFDI 4.0 stamped by a certified provider",
        identifier_label="UUID (Folio Fiscal)",
        document_format="cfdi_4_0",
        profile_fields=("tax_registration_id", "certificate_reference"),
        document_fields=("rfc_issuer", "rfc_receiver", "uso_cfdi", "regimen_fiscal"),
        # A CFDI may only be cancelled in the fiscal year it was issued in, which
        # is a calendar and not a window: for a December invoice the deadline is
        # weeks away and for a January one it is nearly a year, and the same
        # count of days models both wrongly. ``cancellation_basis`` says which
        # kind of rule this is, and the day count below is the outside bound the
        # calendar rule can reach rather than the rule itself.
        cancellation_window_days=365,
        cancellation_basis=CANCELLATION_BASIS_FISCAL_YEAR,
        correction_mechanism="cancellation with the buyer's acceptance, then a replacement CFDI",
        notes=(
            "The stamp (timbrado) is applied by a certified provider, not by the tax authority "
            "directly. The UUID it returns is what makes the document deductible."
        ),
    ),
    "BR": CountryRegime(
        country="BR",
        regime=REGIME_CLEARANCE,
        platform="NF-e via SEFAZ",
        label="Brazil - NF-e authorised by the state SEFAZ",
        identifier_label="chave de acesso (44 digits)",
        document_format="nfe_4_0",
        profile_fields=("tax_registration_id", "certificate_reference"),
        document_fields=("cnpj_issuer", "cfop", "ncm"),
        # The federal window is 24 hours and the states depart from it in both
        # directions, some allowing longer and some less than a day. This field
        # cannot hold less than a day and cannot vary by state, so one day here
        # is the federal figure and not a safe floor: for a state with a shorter
        # window it is optimistic, and no rounding of it would be conservative
        # everywhere. Treat it as the federal rule and check the state.
        cancellation_window_days=1,
        correction_mechanism="cancellation inside the SEFAZ window, otherwise a carta de correcao",
        notes="Authorisation is per state. The chave de acesso encodes the state, the issuer and the document.",
    ),
    "CL": CountryRegime(
        country="CL",
        regime=REGIME_CLEARANCE,
        platform="DTE via SII",
        label="Chile - DTE with a folio authorised by the SII",
        identifier_label="folio (from the CAF range)",
        document_format="dte_sii",
        profile_fields=("tax_registration_id", "certificate_reference"),
        document_fields=("rut_issuer", "rut_receiver", "tipo_dte", "caf_reference"),
        # The SII accepts no cancellation of an issued DTE. The correction is a
        # nota de credito, which is a document of its own with its own folio and
        # its own accounting, so it must not be recorded as a late cancellation.
        cancellation_window_days=None,
        correction_mechanism="nota de credito, itself a DTE with its own folio",
        notes=(
            "Folios are drawn in advance: the issuer requests a range from the SII as a CAF file "
            "and stamps each document from it, so a submission can fail for having no folios left "
            "rather than for anything wrong with the invoice. The buyer's window to reject runs "
            "from receipt, and an invoice that passes it becomes enforceable in its own right, "
            "which is why the acknowledgement date matters as much as the clearance."
        ),
    ),
    "CO": CountryRegime(
        country="CO",
        regime=REGIME_CLEARANCE,
        platform="Facturacion electronica via DIAN",
        label="Colombia - invoice validated by the DIAN before it is delivered",
        identifier_label="CUFE",
        document_format="ubl_dian",
        profile_fields=("tax_registration_id", "certificate_reference"),
        document_fields=("nit_issuer", "nit_receiver", "resolucion_number", "prefix"),
        # An issued electronic invoice is not cancelled in Colombia. The
        # correction is a nota credito, itself an electronic document with its
        # own CUFE, so recording it as a late cancellation would lose the link
        # between the two documents that the DIAN expects to see.
        cancellation_window_days=None,
        correction_mechanism="nota credito, itself an electronic document with its own CUFE",
        notes=(
            "Validacion previa: the invoice goes to the DIAN and comes back validated before it "
            "reaches the buyer, so the CUFE is what makes it an invoice at all rather than a "
            "receipt for one. Numbering is not the issuer's own - a resolucion de facturacion "
            "grants a prefix and a range with an expiry date, and a submission fails for an "
            "exhausted or expired range without anything being wrong with the invoice itself. "
            "Worth pairing with the colombia_aiu methodology, where IVA falls on the utilidad "
            "alone and the invoice has to show that split rather than one taxed total."
        ),
    ),
    "IT": CountryRegime(
        country="IT",
        regime=REGIME_CLEARANCE,
        platform="FatturaPA via SdI",
        label="Italy - FatturaPA delivered through the Sistema di Interscambio",
        identifier_label="numero di protocollo",
        document_format="fatturapa_1_2_2",
        profile_fields=("tax_registration_id",),
        document_fields=("partita_iva_issuer", "codice_destinatario", "tipo_documento"),
        # SdI has no cancellation. Once a document is accepted it exists.
        cancellation_window_days=None,
        correction_mechanism="nota di credito (credit note) through SdI",
        notes="A rejected document may be corrected and resent within five days keeping its original date.",
    ),
    "PL": CountryRegime(
        country="PL",
        regime=REGIME_CLEARANCE,
        platform="KSeF",
        label="Poland - KSeF national e-invoicing system",
        identifier_label="KSeF number",
        document_format="ksef_fa_2",
        profile_fields=("tax_registration_id",),
        document_fields=("nip_issuer", "nip_buyer"),
        # Nothing in KSeF can be withdrawn once it has a number.
        cancellation_window_days=None,
        correction_mechanism="faktura korygujaca (corrective invoice) issued through KSeF",
    ),
    "RO": CountryRegime(
        country="RO",
        regime=REGIME_CLEARANCE,
        platform="e-Factura",
        label="Romania - e-Factura through the national portal",
        identifier_label="index incarcare (upload index)",
        document_format="efactura_ro_cius",
        profile_fields=("tax_registration_id",),
        document_fields=("cui_issuer", "cui_buyer"),
        cancellation_window_days=None,
        correction_mechanism="storno invoice through the portal",
        notes=(
            "RO_CIUS is a national specification of EN 16931 in UBL syntax. The platform's UBL writer "
            "produces the base document; the national restrictions on top of it are not implemented here, "
            "so the payload is taken from the caller."
        ),
    ),
    "SA": CountryRegime(
        country="SA",
        regime=REGIME_CLEARANCE,
        platform="ZATCA phase 2 (Fatoora)",
        label="Saudi Arabia - ZATCA phase 2 integration",
        identifier_label="cryptographic stamp and QR",
        document_format="zatca_phase2",
        profile_fields=("tax_registration_id", "certificate_reference"),
        document_fields=("vat_number_issuer", "invoice_hash", "qr_code"),
        cancellation_window_days=None,
        correction_mechanism="credit note reported through the same integration",
        notes=(
            "Standard invoices are cleared before issue; simplified invoices are reported within 24 hours. "
            "This registry models the standard-invoice clearance path."
        ),
    ),
    "IN": CountryRegime(
        country="IN",
        regime=REGIME_CLEARANCE,
        platform="GST e-invoice (IRP)",
        label="India - Invoice Registration Portal",
        identifier_label="IRN (Invoice Reference Number)",
        document_format="gst_einvoice_irn",
        profile_fields=("tax_registration_id",),
        document_fields=("gstin_issuer", "gstin_buyer", "hsn_code"),
        # An IRN can be cancelled within 24 hours of registration and only if no
        # e-way bill has been generated against it.
        cancellation_window_days=1,
        correction_mechanism="credit note (an IRN older than the window cannot be cancelled)",
    ),
    # ── Reporting ────────────────────────────────────────────────────────────
    "ES": CountryRegime(
        country="ES",
        regime=REGIME_REPORTING,
        platform="SII and Verifactu",
        label="Spain - immediate supply of information and verifiable invoicing",
        identifier_label="CSV (acknowledgement reference)",
        document_format="sii_es",
        profile_fields=("tax_registration_id",),
        document_fields=("nif_issuer",),
        # SII wants the record within four calendar days of issue; the same
        # window is what an annulment record is expected inside.
        cancellation_window_days=4,
        correction_mechanism="annulment record, then a corrected record",
        notes="The invoice is valid on issue. Late reporting is a penalty, not an invalid invoice.",
    ),
    "HU": CountryRegime(
        country="HU",
        regime=REGIME_REPORTING,
        platform="RTIR (Online Szamla)",
        label="Hungary - real-time invoice reporting",
        identifier_label="transaction id",
        document_format="rtir_hu",
        profile_fields=("tax_registration_id",),
        document_fields=("tax_number_issuer",),
        cancellation_window_days=None,
        correction_mechanism="modification or annulment invoice, itself reported",
        notes="Reporting is expected immediately on issue; there is no report to withdraw afterwards.",
    ),
    # ── Network exchange ─────────────────────────────────────────────────────
    #
    # No authority. These are the countries where the platform already produces
    # the document, so the module records where it was routed rather than what
    # was cleared.
    "DE": CountryRegime(
        country="DE",
        regime=REGIME_NETWORK,
        platform="XRechnung / Peppol",
        label="Germany - XRechnung into the public sector over Peppol",
        identifier_label="transmission id",
        document_format="xrechnung_3_0",
        en16931_profile="xrechnung",
        profile_fields=("network_participant_id",),
        document_fields=("buyer_reference",),
        correction_mechanism="credit note",
        notes="The Leitweg-ID travels as the buyer reference (BT-10) and public-sector receivers reject without it.",
    ),
    "FR": CountryRegime(
        country="FR",
        regime=REGIME_NETWORK,
        platform="Chorus Pro / Peppol",
        label="France - Chorus Pro for the public sector",
        identifier_label="transmission id",
        document_format="facturx_1_0",
        en16931_profile="facturx",
        profile_fields=("network_participant_id",),
        document_fields=("service_code",),
        correction_mechanism="credit note",
    ),
    "NL": CountryRegime(
        country="NL",
        regime=REGIME_NETWORK,
        platform="Peppol (NLCIUS)",
        label="Netherlands - NLCIUS over Peppol",
        identifier_label="transmission id",
        document_format="nlcius_1_0",
        en16931_profile="nlcius",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "NO": CountryRegime(
        country="NO",
        regime=REGIME_NETWORK,
        platform="Peppol (EHF)",
        label="Norway - EHF Billing 3.0 over Peppol",
        identifier_label="transmission id",
        document_format="ehf_3_0",
        en16931_profile="ehf",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "AU": CountryRegime(
        country="AU",
        regime=REGIME_NETWORK,
        platform="Peppol A-NZ",
        label="Australia - Peppol A-NZ Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_aunz_3_0",
        en16931_profile="peppol_aunz",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "NZ": CountryRegime(
        country="NZ",
        regime=REGIME_NETWORK,
        platform="Peppol A-NZ",
        label="New Zealand - Peppol A-NZ Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_aunz_3_0",
        en16931_profile="peppol_aunz",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "SG": CountryRegime(
        country="SG",
        regime=REGIME_NETWORK,
        platform="Peppol SG",
        label="Singapore - Peppol SG Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_sg_3_0",
        en16931_profile="peppol_sg",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "GB": CountryRegime(
        country="GB",
        regime=REGIME_NETWORK,
        platform="Peppol",
        label="United Kingdom - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "IE": CountryRegime(
        country="IE",
        regime=REGIME_NETWORK,
        platform="Peppol",
        label="Ireland - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "BE": CountryRegime(
        country="BE",
        regime=REGIME_NETWORK,
        platform="Peppol",
        label="Belgium - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "DK": CountryRegime(
        country="DK",
        regime=REGIME_NETWORK,
        platform="Peppol (NemHandel)",
        label="Denmark - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "FI": CountryRegime(
        country="FI",
        regime=REGIME_NETWORK,
        platform="Peppol",
        label="Finland - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
    "SE": CountryRegime(
        country="SE",
        regime=REGIME_NETWORK,
        platform="Peppol",
        label="Sweden - Peppol BIS Billing 3.0",
        identifier_label="transmission id",
        document_format="peppol_bis_3_0",
        en16931_profile="peppol",
        profile_fields=("network_participant_id",),
        correction_mechanism="credit note",
    ),
}

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
    }


__all__ = [
    "CANCELLATION_BASES",
    "CANCELLATION_BASIS_DAYS",
    "CANCELLATION_BASIS_FISCAL_YEAR",
    "COUNTRY_REGIMES",
    "LEGAL_STATUSES",
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
    "phase_as_dict",
    "regime_as_dict",
]

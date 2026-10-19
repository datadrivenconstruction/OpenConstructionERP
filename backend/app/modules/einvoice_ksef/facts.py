# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish KSeF facts as data.

Every date, threshold and host here is a row that names its source, the day the
source was read and how sure the reading is. Code reads these rows; it does not
carry a second copy of any of them. A fact the research could not confirm is
shipped with ``needs_expert_review`` set and is never turned into a refusal.

Confidence follows the research note: ``H`` an official page or two independent
reliable sources, ``M`` one reliable secondary source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

READ_DATE = "2026-10-19"

MF_DOCS = "https://github.com/CIRFMF/ksef-docs"
KSEF_PORTAL = "https://ksef.podatki.gov.pl"


@dataclass(frozen=True)
class SchemaVersion:
    """One invoice structure KSeF accepts or used to accept."""

    key: str
    system_code: str
    schema_version: str
    form_value: str
    variant: str
    namespace: str
    valid_from: str
    # Empty while the structure is current.
    valid_to: str
    source_url: str
    read_date: str = READ_DATE
    confidence: str = "H"
    notes: str = ""

    def in_force_on(self, day: date) -> bool:
        """Whether an invoice issued on ``day`` may use this structure."""
        if day < date.fromisoformat(self.valid_from):
            return False
        return not self.valid_to or day <= date.fromisoformat(self.valid_to)


FA3 = SchemaVersion(
    key="ksef_fa_3",
    system_code="FA (3)",
    schema_version="1-0E",
    form_value="FA",
    variant="3",
    namespace="http://crd.gov.pl/wzor/2025/06/25/13775/",
    valid_from="2026-02-01",
    valid_to="",
    source_url="https://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd",
    notes=(
        "Mandatory for invoices issued from 2026-02-01, also for corrections of invoices first issued in "
        "FA(1) or FA(2). https://ksef.podatki.gov.pl/informacje-ogolne-ksef-20/struktura-logiczna-fa-3/"
    ),
)

# Historical. Kept so an invoice issued in the voluntary KSeF period can still be
# recognised and so the rule that refuses FA(2) can say until when it was right.
FA2 = SchemaVersion(
    key="ksef_fa_2",
    system_code="FA (2)",
    schema_version="1-0E",
    form_value="FA",
    variant="2",
    namespace="http://crd.gov.pl/wzor/2023/06/29/12648/",
    valid_from="2023-09-01",
    valid_to="2026-01-31",
    source_url=f"{MF_DOCS}/blob/main/faktury/schemy/FA/schemat_FA(2)_v1-0E.xsd",
    confidence="M",
    notes=(
        "Voluntary KSeF 1.0 structure. The DEMO and PROD environments of API 2.0 accept FA(3) only "
        f"({MF_DOCS}/blob/main/srodowiska.md). The FA(2) namespace is as published in the MF repository."
    ),
)

SCHEMA_VERSIONS: tuple[SchemaVersion, ...] = (FA3, FA2)


def schema_for_namespace(namespace: str) -> SchemaVersion | None:
    """The structure a document's root namespace names, or ``None``."""
    wanted = (namespace or "").strip()
    return next((s for s in SCHEMA_VERSIONS if s.namespace == wanted), None)


@dataclass(frozen=True)
class DatedFact:
    """A dated obligation or limit, with where it comes from."""

    key: str
    effective_date: str
    description: str
    source_url: str
    read_date: str = READ_DATE
    confidence: str = "M"
    needs_expert_review: bool = False
    threshold: str = ""


# The issue obligation by taxpayer size, and the receive obligation for everyone.
PHASE_RECEIVE_ALL = DatedFact(
    key="receive_all",
    effective_date="2026-02-01",
    description="Every taxpayer receives structured invoices through KSeF.",
    source_url="https://www.ey.com/en_gl/technical/tax-alerts/poland-signs-into-law-mandatory-national-e-invoicing-system",
    confidence="H",
)
PHASE_ISSUE_LARGE = DatedFact(
    key="issue_large",
    effective_date="2026-02-01",
    description="Taxpayers whose 2024 sales including VAT exceeded PLN 200 million issue in KSeF.",
    source_url="https://www.ey.com/en_gl/technical/tax-alerts/poland-signs-into-law-mandatory-national-e-invoicing-system",
    confidence="H",
    threshold="PLN 200000000 sales including VAT in 2024",
)
PHASE_ISSUE_ALL = DatedFact(
    key="issue_all",
    effective_date="2026-04-01",
    description="All other taxpayers issue in KSeF.",
    source_url="https://www.ey.com/en_gl/technical/tax-alerts/poland-signs-into-law-mandatory-national-e-invoicing-system",
    confidence="H",
)
PHASE_ISSUE_MICRO = DatedFact(
    key="issue_micro",
    effective_date="2027-01-01",
    description=(
        "Taxpayers whose monthly invoiced sales do not exceed PLN 10,000 may issue outside KSeF until "
        "2026-12-31; cash-register invoices likewise."
    ),
    source_url="https://www.mddp.pl/ksef-2-0-takes-shape-what-changes-in-the-legislation/",
    threshold="PLN 10000 invoiced sales per month",
)
PENALTIES_FROM = DatedFact(
    key="penalties",
    effective_date="2027-01-01",
    description=(
        "Penalties for an invoice not issued in KSeF: up to 100% of its VAT, or up to 18.7% of the gross "
        "amount where there is no VAT."
    ),
    source_url="https://api.sejm.gov.pl/sejm/term10/interpellations/attachment/ATTDPLJWP/z02943-o1.pdf",
)
TOKEN_AUTH_LAST_DAY = DatedFact(
    key="token_auth_last_day",
    effective_date="2026-12-31",
    description="KSeF tokens authenticate until this day; from 2027-01-01 only certificates and qualified signatures.",
    source_url="https://pomoc.comarch.pl/pos/cee/documentation/nowosci-i-zmiane-w-wersji-2025-0-3-hf-do-wersji-2025-0/",
)
KSEF_NUMBER_IN_PAYMENT_TITLE = DatedFact(
    key="ksef_number_in_payment_title",
    effective_date="2027-01-01",
    description=(
        "A transfer paying a structured invoice between VAT payers carries the KSeF number (or a collective "
        "identifier) in its title, split payment transfers included. Recommended, not required, in 2026."
    ),
    source_url="https://www.ifirma.pl/blog/numer-ksef-w-elektronicznych-przelewach-bankowych-nowy-obowiazek-dla-przedsiebiorcow/",
)

PHASES: tuple[DatedFact, ...] = (PHASE_RECEIVE_ALL, PHASE_ISSUE_LARGE, PHASE_ISSUE_ALL, PHASE_ISSUE_MICRO)


# ── Split payment (MPP) ─────────────────────────────────────────────────────
# Split payment is a VAT rule, not a KSeF fact. Its threshold and the Annex 15
# sections are read from the Polish VAT data (``app.core.vat_construction``);
# see ``split_payment.py``. Nothing here repeats them.


# ── Offline modes ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OfflineMode:
    """One way of issuing an invoice before it reaches KSeF."""

    key: str
    label: str
    # Business days allowed for the upload, counted from ``counted_from``.
    # ``None`` means no upload obligation at all.
    upload_business_days: int | None
    counted_from: str
    legal_basis: str
    # Whether the invoice is still an FA(3) document carrying the QR codes.
    fa3_and_qr: bool = True
    source_url: str = f"{MF_DOCS}/blob/main/tryby-offline.md"
    read_date: str = READ_DATE
    confidence: str = "H"


OFFLINE24 = "offline24"
OFFLINE_UNAVAILABLE = "offline"
OFFLINE_FAILURE = "awaria"
OFFLINE_TOTAL_FAILURE = "awaria_calkowita"

OFFLINE_MODES: dict[str, OfflineMode] = {
    OFFLINE24: OfflineMode(
        key=OFFLINE24,
        label="offline24 (taxpayer side, any reason)",
        upload_business_days=1,
        counted_from="issue",
        legal_basis="VAT Act art. 106nda",
    ),
    OFFLINE_UNAVAILABLE: OfflineMode(
        key=OFFLINE_UNAVAILABLE,
        label="offline (KSeF unavailability announced in BIP)",
        upload_business_days=1,
        counted_from="end_of_event",
        legal_basis="VAT Act art. 106nh",
    ),
    OFFLINE_FAILURE: OfflineMode(
        key=OFFLINE_FAILURE,
        label="awaria (KSeF failure announced in BIP)",
        upload_business_days=7,
        counted_from="end_of_event",
        legal_basis="VAT Act art. 106nf",
    ),
    OFFLINE_TOTAL_FAILURE: OfflineMode(
        key=OFFLINE_TOTAL_FAILURE,
        label="awaria calkowita (total failure announced in the media)",
        upload_business_days=None,
        counted_from="",
        legal_basis="VAT Act art. 106nf",
        fa3_and_qr=False,
    ),
}
# A failure announced while an offline24 or offline invoice waits moves its
# deadline to this many business days after the end of the last failure.
FAILURE_DURING_WAIT_BUSINESS_DAYS = 7


# ── Environments ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Environment:
    """One public KSeF environment."""

    key: str
    api_base_url: str
    qr_base_url: str
    is_production: bool
    source_url: str = f"{MF_DOCS}/blob/main/srodowiska.md"
    read_date: str = READ_DATE


ENVIRONMENTS: dict[str, Environment] = {
    "test": Environment(
        "test", "https://api-test.ksef.mf.gov.pl/v2", "https://qr-test.ksef.mf.gov.pl", is_production=False
    ),
    "demo": Environment(
        "demo", "https://api-demo.ksef.mf.gov.pl/v2", "https://qr-demo.ksef.mf.gov.pl", is_production=False
    ),
    "prod": Environment("prod", "https://api.ksef.mf.gov.pl/v2", "https://qr.ksef.mf.gov.pl", is_production=True),
}


# ── JPK_V7(3) per-document markers ──────────────────────────────────────────
JPK_OFF = "OFF"
JPK_BFK = "BFK"
JPK_DI = "DI"

JPK_V7_3 = DatedFact(
    key="jpk_v7_3",
    effective_date="2026-02-01",
    description=(
        "JPK_V7M / JPK_V7K variant (3): each sales and purchase record carries the KSeF number, or one of "
        "OFF (offline invoice still without a number), BFK (invoice issued outside KSeF), DI (a document "
        "that is not an invoice). Reg. MF of 12.12.2025, Dz.U. 2025 poz. 1800."
    ),
    source_url="https://ksiegowosc.infor.pl/podatki/vat/jpk-vat/7558412,jpk-vat-z-deklaracja-a-ksef-ministerstwo-finansow-wyjasnilo-zasady-stosowania-znacznikow-nrksef-off-bfk-di-w-ewidencji-sprzedazy-i-zakupu.html",
)


@dataclass(frozen=True)
class JpkMarkerRow:
    """Which marker a document without a KSeF number takes, by how it was issued."""

    issued_as: str
    marker: str
    needs_expert_review: bool = False
    notes: str = ""
    source_url: str = JPK_V7_3.source_url
    read_date: str = READ_DATE


JPK_MARKERS: dict[str, JpkMarkerRow] = {
    OFFLINE_FAILURE: JpkMarkerRow(OFFLINE_FAILURE, JPK_OFF),
    OFFLINE_UNAVAILABLE: JpkMarkerRow(OFFLINE_UNAVAILABLE, JPK_OFF),
    OFFLINE24: JpkMarkerRow(
        OFFLINE24,
        JPK_OFF,
        needs_expert_review=True,
        notes=(
            "Sources disagree: one vendor help page maps an offline24 invoice still without a number to DI, "
            "law-firm and press summaries of the MF table map every offline mode to OFF. Confirm with the MF "
            "explanations before relying on it."
        ),
    ),
    OFFLINE_TOTAL_FAILURE: JpkMarkerRow(OFFLINE_TOTAL_FAILURE, JPK_BFK),
    "outside_ksef": JpkMarkerRow("outside_ksef", JPK_BFK),
    "not_an_invoice": JpkMarkerRow("not_an_invoice", JPK_DI),
}


@dataclass(frozen=True)
class FactSheet:
    """Everything above in one serialisable view, for the regime row and the UI."""

    schemas: tuple[SchemaVersion, ...] = SCHEMA_VERSIONS
    phases: tuple[DatedFact, ...] = PHASES
    others: tuple[DatedFact, ...] = field(
        default=(PENALTIES_FROM, TOKEN_AUTH_LAST_DAY, KSEF_NUMBER_IN_PAYMENT_TITLE, JPK_V7_3)
    )


def on_or_after(day: date, fact: DatedFact) -> bool:
    """Whether ``day`` falls on or after the date ``fact`` takes effect."""
    return day >= date.fromisoformat(fact.effective_date)


__all__ = [
    "ENVIRONMENTS",
    "FA2",
    "FA3",
    "FAILURE_DURING_WAIT_BUSINESS_DAYS",
    "JPK_BFK",
    "JPK_DI",
    "JPK_MARKERS",
    "JPK_OFF",
    "JPK_V7_3",
    "KSEF_NUMBER_IN_PAYMENT_TITLE",
    "OFFLINE24",
    "OFFLINE_FAILURE",
    "OFFLINE_MODES",
    "OFFLINE_TOTAL_FAILURE",
    "OFFLINE_UNAVAILABLE",
    "PENALTIES_FROM",
    "PHASES",
    "PHASE_ISSUE_ALL",
    "PHASE_ISSUE_LARGE",
    "PHASE_ISSUE_MICRO",
    "PHASE_RECEIVE_ALL",
    "SCHEMA_VERSIONS",
    "TOKEN_AUTH_LAST_DAY",
    "DatedFact",
    "Environment",
    "FactSheet",
    "JpkMarkerRow",
    "OfflineMode",
    "SchemaVersion",
    "on_or_after",
    "schema_for_namespace",
]

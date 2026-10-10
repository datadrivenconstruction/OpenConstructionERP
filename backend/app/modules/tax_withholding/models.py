# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding ORM models.

Tables:
    oe_tax_withholding_regime         - a statutory withholding scheme
    oe_tax_withholding_party          - one party's standing under a scheme
    oe_tax_withholding_deduction      - tax withheld from one payment
    oe_tax_withholding_reverse_charge - who accounts for the VAT on one invoice
    oe_tax_withholding_statutory_calc - the inputs and sign-off of one document's payment taxes
    oe_tax_withholding_statutory_line - one statutory tax figure on that document

**The word "withholding" already means something else in this codebase, twice,
and neither of them is a tax.** ``finance.Payment.withholding_amount`` and
``finance.Payment.withholding_release_date`` mean *retainage*: money held back
from a certified claim and paid to the payee later, typically at practical
completion. ``finance/retention_ledger.py`` and
``finance/service.py::compute_payment_withholding`` frame it the same way, and
the ``subcontractors`` module carries its own copy of the concept
(``RetentionLedger``, ``PaymentApplication.retention_amount``,
``SubcontractAgreement.retention_percent``).

Tax withheld under a statutory scheme is never released to the payee - it goes
to the state and the payee reclaims it through their own return. Retainage
always comes back. They are different obligations that happen to share an
English word, so **no column here is a bare ``withholding_amount``**: the money
column is ``tax_withheld``, the figure it is computed on is ``taxable_base``.
Retainage is already implemented in ``finance`` and ``subcontractors`` and is
not rebuilt here.

``payroll`` has a third, unrelated use: employee payroll tax deducted from a
payslip. This module withholds from a *supplier's invoice*, not from a wage.

Money is :class:`~decimal.Decimal` in a ``MoneyType`` column and is serialised
as a string by the schema layer. Every money-carrying row names its own
currency: a scheme that only exists because the work crosses a border cannot
have an implied one.

Nothing is ever queried *inside* a JSON column. On PostgreSQL a ``.contains()``
against a plain JSON column compiles to a string LIKE rather than to JSONB
containment, so a filter written that way would silently mean something else.
``bands`` is read whole and filtered in Python.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

# Deduction lifecycle. ``calculated`` is a figure the product stands behind,
# ``remitted`` means the money has gone to the authority, and ``returned``
# means it has also appeared on a filed return - those last two are separate
# because a payment made on time and a return filed late are different
# failures with different penalties.
DEDUCTION_STATUSES: tuple[str, ...] = ("draft", "calculated", "remitted", "returned", "void")

# Standing of a party under a scheme. ``pending`` is the honest state between
# asking the authority to verify a subcontractor and being told the answer;
# it is not a licence to deduct at the reduced rate meanwhile.
PARTY_STATUSES: tuple[str, ...] = ("pending", "active", "expired", "revoked")

# A reverse-charge determination is a decision about one invoice, and the
# invoice may be reissued, so the old decision is kept as ``superseded``
# rather than edited: it is what the VAT return was filed on.
REVERSE_CHARGE_STATUSES: tuple[str, ...] = ("draft", "applied", "superseded")

# What the party reference points at. No cross-module foreign key: the payee
# may be a subcontractor record, a vendor or a plain contact depending on how
# the deployment records its supply chain, and a hard FK would tie this module
# to one of them.
PARTY_TYPES: tuple[str, ...] = ("subcontractor", "vendor", "contact", "employee_of_record")


class WithholdingRegime(Base):
    """A statutory withholding scheme in one country.

    Reference data, not project data: one row is "UK CIS" or "German
    Bauabzugsteuer under section 48 EStG", with the bands the scheme deducts
    at. The shipped set is seeded from :mod:`app.modules.tax_withholding.data`
    rather than from a migration, so a rate change is an ordinary code change
    and an operator's own edits are never overwritten by an upgrade.

    ``bands`` is the whole rate table: a list of
    ``{"code", "label", "rate_pct", "requires_verification"}``. It is a JSON
    array rather than a child table because the bands of a scheme are read and
    replaced together and nothing ever queries one band across schemes.

    ``materials_excluded`` is the flag that costs real money. Every scheme
    modelled here deducts on labour only, so a deduction taken on the gross
    including materials over-withholds on every single payment. The column
    exists so the rule can be asked rather than remembered.
    """

    __tablename__ = "oe_tax_withholding_regime"
    __table_args__ = (
        UniqueConstraint("country_code", "scheme_code", name="uq_tax_wh_regime_country_scheme"),
        Index("ix_tax_wh_regime_country_active", "country_code", "is_active"),
    )

    # ISO 3166-1 alpha-2. "GB", not "UK": the scheme is HMRC's and the country
    # code has to match what the rest of the platform files under.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    scheme_code: Mapped[str] = mapped_column(String(48), nullable=False)
    scheme_name: Mapped[str] = mapped_column(String(160), nullable=False)
    # The statute, printed on reports and quoted when an inspector asks.
    legal_reference: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    authority: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    bands: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # The band a party falls into when nothing has been verified. Always the
    # highest-rate band of the scheme: an unverified subcontractor is deducted
    # at the punitive rate, not at the reduced one.
    default_band_code: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    materials_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    vat_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # How long a verification lasts before it has to be renewed. Zero means the
    # scheme sets no fixed life and the certificate carries its own end date.
    verification_validity_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # De minimis: payments at or below this figure are outside the scheme
    # (Germany's section 48 EStG exemption limit is the reason this exists).
    # NULL means the scheme has no threshold.
    threshold_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    def __repr__(self) -> str:
        return f"<WithholdingRegime {self.country_code}:{self.scheme_code} bands={len(self.bands or [])}>"


class PartyTaxStatus(Base):
    """One party's standing under one scheme, for a stated window.

    This is the row that decides the rate. A UK subcontractor verified for
    gross payment, a German subcontractor holding a Freistellungsbescheinigung,
    an Irish subcontractor on the zero rate - each is a verification reference
    with a life, and when that life ends the party drops to the scheme's
    default band. The drop is silent in real life, which is exactly why
    ``valid_to`` is a real date column and not a note.
    """

    __tablename__ = "oe_tax_withholding_party"
    __table_args__ = (
        Index("ix_tax_wh_party_party_regime", "party_id", "regime_id"),
        # The expiry sweep: everything active with an end date in view.
        Index("ix_tax_wh_party_status_valid_to", "status", "valid_to"),
    )

    # Plain GUID, deliberately not a foreign key - see ``PARTY_TYPES``.
    party_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    party_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="subcontractor", server_default="subcontractor"
    )
    # Denormalised so a return or an audit trail reads without reaching into
    # whichever module owns the party record.
    party_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    regime_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tax_withholding_regime.id", ondelete="CASCADE", name="fk_tax_wh_party_regime"),
        nullable=False,
    )
    band_code: Mapped[str] = mapped_column(String(32), nullable=False)
    # The CIS verification number, the Freistellungsbescheinigung number, the
    # RCT rate notification. Empty when the party has not been verified.
    verification_reference: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    verified_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date(), nullable=False)
    # NULL means open-ended. It is not the same as "expired" and the rules keep
    # the two apart: a scheme with no fixed certificate life leaves this empty.
    valid_to: Mapped[date | None] = mapped_column(Date(), nullable=True)
    # The scanned certificate in the document store. Plain GUID for the same
    # reason as ``party_id``.
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<PartyTaxStatus party={self.party_id} band={self.band_code} to={self.valid_to}>"


class WithholdingDeduction(Base):
    """Tax withheld from one payment to one party.

    The arithmetic is the point of the table::

        taxable_base = gross_amount - qualifying_materials - vat_amount
        tax_withheld = taxable_base * rate_pct / 100

    ``qualifying_materials`` is the column the money turns on. Every scheme
    modelled here deducts on labour, so a deduction taken on the gross
    over-withholds on every payment, every month, and the subcontractor only
    gets it back at the end of their tax year. The figures are stored rather
    than recomputed on read because a filed return has to still say what it
    said when it was filed, whatever the rates do afterwards.
    """

    __tablename__ = "oe_tax_withholding_deduction"
    __table_args__ = (
        Index("ix_tax_wh_deduction_period", "period_end", "status"),
        Index("ix_tax_wh_deduction_payment_ref", "payment_reference"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_tax_wh_deduction_project"),
        nullable=False,
    )
    regime_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tax_withholding_regime.id", ondelete="RESTRICT", name="fk_tax_wh_deduction_regime"),
        nullable=False,
    )
    # The standing the rate was taken from. Nullable and ``SET NULL`` on
    # delete: the deduction is a filed fact and must survive the party record
    # being tidied away, so it carries its own copy of the band and rate.
    party_status_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_tax_withholding_party.id", ondelete="SET NULL", name="fk_tax_wh_deduction_party"),
        nullable=True,
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    party_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # The subcontractor invoice or payment application this sits on. Free text
    # rather than a foreign key: the payment may live in ``finance``, in
    # ``subcontractors``, or on paper.
    payment_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    qualifying_materials: Mapped[Decimal] = mapped_column(
        MoneyType(), nullable=False, default=Decimal("0"), server_default="0"
    )
    vat_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    taxable_base: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    # Percent, not a fraction: 20 means 20%. Four decimals so a scheme quoting
    # a third of a percent is representable.
    rate_pct: Mapped[Decimal] = mapped_column(
        MoneyType(precision=9, scale=4), nullable=False, default=Decimal("0"), server_default="0"
    )
    band_code: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    # Never ``withholding_amount``: that name is taken by retainage in
    # ``finance``. This money goes to the state and does not come back.
    tax_withheld: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", server_default="draft")
    remitted_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    # The monthly return the deduction was reported on (a CIS return
    # reference, an RCT deduction summary number).
    return_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    @property
    def net_payable(self) -> Decimal:
        """Gross less the tax withheld - what the party is actually paid.

        Derived rather than stored: a stored copy is one more figure that can
        disagree with the two it is made of.
        """
        return (self.gross_amount or Decimal("0")) - (self.tax_withheld or Decimal("0"))

    def __repr__(self) -> str:
        return f"<WithholdingDeduction {self.tax_withheld} {self.currency_code} on base {self.taxable_base}>"


class ReverseChargeDetermination(Base):
    """Who accounts for the VAT on one invoice, and the wording that proves it.

    A reverse charge is not a rate, it is a shift of responsibility: the buyer
    accounts for the VAT instead of the seller. Two things follow, and both are
    columns here because both are what an inspection looks at. The invoice must
    carry the statutory wording (``invoice_wording``), and it must not carry a
    VAT amount (``vat_amount``, which has to be zero whenever
    ``buyer_accounts_for_vat`` is set).

    A determination is kept rather than edited once applied: it is the basis a
    VAT return was filed on. A changed decision supersedes it.
    """

    __tablename__ = "oe_tax_withholding_reverse_charge"
    __table_args__ = (
        UniqueConstraint("project_id", "invoice_reference", name="uq_tax_wh_rc_project_invoice"),
        Index("ix_tax_wh_rc_invoice", "invoice_reference"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_tax_wh_rc_project"),
        nullable=False,
    )
    # Plain GUID at whatever module issued the invoice, plus the human
    # reference that appears on the document itself. The reference is the
    # required one: a determination about an invoice nobody can name is not
    # evidence of anything.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    invoice_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(48), nullable=False, default="", server_default="")
    buyer_accounts_for_vat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    legal_reference: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # The sentence that has to be printed on the invoice. Stored per row and
    # not looked up at print time so a wording change cannot rewrite what an
    # already-issued invoice said.
    invoice_wording: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    net_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    # Must be zero on a reverse-charge invoice. Kept as a column rather than
    # assumed, because the failure being guarded against is an invoice that
    # carries both the wording and a VAT line.
    vat_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", server_default="draft")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        who = "buyer" if self.buyer_accounts_for_vat else "seller"
        return f"<ReverseChargeDetermination {self.invoice_reference} {self.country_code} vat_by={who}>"


# ── Statutory tax lines on a payment document ────────────────────────────────

# The documents a set of statutory tax lines can sit on. No cross-module
# foreign key, for the reason given on ``PARTY_TYPES``: a progress claim lives
# in ``contracts``, a subcontractor payment application in ``subcontractors``
# and an invoice in ``finance``, and this module must load without any of them.
STATUTORY_SOURCE_KINDS: tuple[str, ...] = ("progress_claim", "sub_payment_application", "invoice")

# Which side of the payment we are on. ``borne_by_us``: the tax is withheld
# from what we are paid, and we reclaim it through our own return.
# ``withheld_by_us``: we withhold from a subcontractor and remit to the state.
# The arithmetic is identical; the ledger the figure belongs in is not.
STATUTORY_DIRECTIONS: tuple[str, ...] = ("borne_by_us", "withheld_by_us")

# ``confirmed`` is a person's signature under the figures: from there on the
# rows are frozen and no change to a rate table rewrites them. ``void`` keeps
# the rows as evidence of what was once computed and takes them out of use.
STATUTORY_STATUSES: tuple[str, ...] = ("draft", "confirmed", "void")

# The five figures of one calculation, in their printed order. These are the
# ``kind`` values of :class:`app.core.payment_taxes.Figure`.
STATUTORY_LINE_KINDS: tuple[str, ...] = (
    "vat_computed",
    "vat_withheld",
    "vat_payable",
    "income_withheld",
    "stamp_duty",
)

# Value, not applicable, held. Held is "we cannot say yet", and it is stored
# as a NULL amount, never as zero: a zero prints as a figure somebody decided.
STATUTORY_CALC_STATUSES: tuple[str, ...] = ("value", "not_applicable", "held")

# What a person decided about one tax. The empty string marks the two derived
# figures (computed VAT and payable VAT), which carry no decision of their own.
STATUTORY_CHOICE_STATES: tuple[str, ...] = ("selected", "not_applicable", "unset")


class StatutoryTaxCalc(Base):
    """The inputs and the sign-off behind one document's statutory tax lines.

    One row per source document. It holds what the five figures were computed
    from, so the calculation can be reproduced, and it holds the whole
    lifecycle, so there is exactly one place that says whether the figures are
    a draft, confirmed or void. The lines carry no status of their own: two
    writable copies of one status disagree sooner or later.

    ``vat_rate_pct`` is an input here, not something this module resolves. The
    platform has one source for a VAT rate and the caller reads it there. NULL
    means the rate was not known when the figures were computed, and it is
    never read as zero.

    ``buyer_is_designated`` and ``work_value_incl_vat`` are nullable for the
    same reason: "not stated" has to stay distinguishable from "no" and from
    "nothing", because a withholding that depends on who the buyer is, or on
    the value of the whole work, is held until somebody answers.

    Amounts are stored at four decimal places so a three-decimal currency
    keeps its last digit. They are read back at the currency's own precision.
    """

    __tablename__ = "oe_tax_withholding_statutory_calc"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", name="uq_tax_wh_stat_calc_source"),
        Index("ix_tax_wh_stat_calc_source_id", "source_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_tax_wh_stat_calc_project"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Plain GUID, deliberately not a foreign key - see ``STATUTORY_SOURCE_KINDS``.
    source_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    # The number printed on the document, so the row reads without a join.
    source_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    # The date the document is taxed on: the rate rows are looked up for it.
    document_date: Mapped[date] = mapped_column(Date(), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(MoneyType(precision=18, scale=4), nullable=False)
    vat_rate_pct: Mapped[Decimal | None] = mapped_column(MoneyType(precision=12, scale=6), nullable=True)
    buyer_is_designated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_value_incl_vat: Mapped[Decimal | None] = mapped_column(MoneyType(precision=18, scale=4), nullable=True)
    # What the person says the work value is the value of: this subcontract,
    # or the main work it is part of. Which of the two the law tests is a
    # question for an accountant, so the figure is stored as entered together
    # with their description of it, and is never derived.
    work_value_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Stamp duty is charged on a base of its own, which is not the VAT base
    # (an advance already taxed comes off it). NULL with the flag unset means
    # nobody has stated the base, and the stamp duty figure is held. The flag
    # is a person's statement that the base is the net amount; it is never
    # assumed.
    stamp_duty_base: Mapped[Decimal | None] = mapped_column(MoneyType(precision=18, scale=4), nullable=True)
    stamp_duty_base_same_as_net: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", server_default="draft")
    # Users are referenced by plain GUID: the sign-off has to outlive the
    # account that gave it.
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the figures were confirmed although a rate row behind them had
    # not been confirmed against its primary source. Who accepted that, and
    # when, is the difference between a decision and a silent default.
    unconfirmed_rates_acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    unconfirmed_rates_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The last reopening. Every reopening is also written to the audit log,
    # which keeps the earlier ones.
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    voided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<StatutoryTaxCalc {self.source_kind}:{self.source_id} {self.status}>"


class StatutoryTaxLine(Base):
    """One statutory tax figure on one payment document.

    A row is a stored :class:`app.core.payment_taxes.Figure`: every field of
    the figure has a column, so the result of a calculation can be rebuilt
    from the rows exactly, without running the calculation again. That is what
    freezing means here. A confirmed document answers from these rows whatever
    the rate tables say afterwards.

    ``tax_amount`` and ``base_amount`` are NULL for a figure that is held or
    not applicable. NULL is not zero: a real zero is a ``value`` row holding
    ``0``, and it is the only way a zero gets into this table.

    The three lines that belong to a tax a person decides on (``vat_withheld``,
    ``income_withheld``, ``stamp_duty``) also carry that decision in the
    ``choice_*`` columns. ``code`` is the rate row the figure was computed
    from; ``choice_code`` is what the person picked. They are kept apart so a
    picked code that had no row on the document date still shows what was
    asked for.

    ``project_id``, ``source_kind`` and ``source_id`` repeat the parent's so
    the unique key can be stated on this table and a line can be found without
    the parent.
    """

    __tablename__ = "oe_tax_withholding_statutory_line"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", "kind", name="uq_tax_wh_stat_line_source_kind"),
        Index("ix_tax_wh_stat_line_source_id", "source_id"),
    )

    calc_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tax_withholding_statutory_calc.id", ondelete="CASCADE", name="fk_tax_wh_stat_line_calc"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_tax_wh_stat_line_project"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    calc_status: Mapped[str] = mapped_column(String(24), nullable=False)
    # Never ``withholding_amount``: that name is taken by retainage in
    # ``finance``. NULL unless ``calc_status`` is ``value``.
    tax_amount: Mapped[Decimal | None] = mapped_column(MoneyType(precision=18, scale=4), nullable=True)
    base_amount: Mapped[Decimal | None] = mapped_column(MoneyType(precision=18, scale=4), nullable=True)
    # Percent. A per-mille duty is written as a percent, hence six decimals.
    rate_pct: Mapped[Decimal | None] = mapped_column(MoneyType(precision=12, scale=6), nullable=True)
    # The fraction of the VAT that changes hands, for a VAT withholding.
    numerator: Mapped[int | None] = mapped_column(Integer, nullable=True)
    denominator: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    # Text, not a sized string: both are copied from the rate row as they are,
    # and a reference cut short to fit a column would quote the wrong article.
    legal_reference: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    rate_effective_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    rate_effective_to: Mapped[date | None] = mapped_column(Date(), nullable=True)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    reason_key: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    reason_params: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    choice_state: Mapped[str] = mapped_column(String(24), nullable=False, default="", server_default="")
    choice_code: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    choice_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # The amount a person entered in place of the computed one. Kept apart
    # from ``tax_amount`` so a recalculation can apply the same override again
    # instead of guessing it back out of the result.
    override_amount: Mapped[Decimal | None] = mapped_column(MoneyType(precision=18, scale=4), nullable=True)
    override_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<StatutoryTaxLine {self.kind} {self.calc_status} {self.tax_amount} {self.currency_code}>"

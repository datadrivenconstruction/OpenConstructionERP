# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tax withholding: statutory construction withholding and VAT reverse charge.

Two taxes that both land on a subcontractor payment and that the product had
nowhere to record. The payer deducts tax and remits it to the state (UK CIS,
German Bauabzugsteuer under section 48 EStG, Irish RCT, Italian ritenuta
d'acconto, US backup withholding); and on a reverse-charge supply the buyer
accounts for the VAT, so the invoice has to carry the statutory wording and no
VAT amount.

None of this is retainage, which is already modelled twice - in ``finance`` as
``Payment.withholding_amount`` and in ``subcontractors`` as
``RetentionLedger`` - and which shares an English word with it and nothing
else. Tax withheld goes to the authority and the payee reclaims it themselves;
retainage is released back by the payer. No column added here is a bare
``withholding_amount``.

``oe_tax_withholding_regime``
    A statutory scheme in one country, with its rate bands as a JSON array.
    ``materials_excluded`` and ``vat_excluded`` differ between schemes and are
    the expensive part: the UK deducts on labour, so materials leave the base,
    while section 48 EStG deducts from the whole consideration including VAT.
    The rows themselves are seeded by the module from
    ``app/modules/tax_withholding/data.py`` and not from this revision, so a
    rate change ships as an ordinary code change and an operator's own edits
    survive an upgrade.

``oe_tax_withholding_party``
    One party's standing under one scheme for a stated window. ``valid_to`` is
    a real date column because a verification lapsing is silent in real life
    and moves the party to the scheme's highest band.

``oe_tax_withholding_deduction``
    Tax withheld from one payment: gross, qualifying materials, VAT, the base
    the rate was applied to, the rate, and the money. Stored rather than
    recomputed on read - a filed return has to keep saying what it said.

``oe_tax_withholding_reverse_charge``
    Who accounts for the VAT on one invoice, the statute, and the wording that
    has to be printed on it.

Nothing is backfilled. There is no earlier source: the deductions taken before
this module existed were computed in a spreadsheet or by an accountant, and a
guess at them would be worse than an honest empty table.

Ids are ``String(36)``, not native ``UUID``: the ORM's ``GUID`` type is
``VARCHAR(36)`` on every dialect, and a native ``uuid`` column here would build
a schema the application reads with the wrong type on one of the two install
routes. Money is ``NUMERIC(18, 2)``, matching ``MoneyType``.

Idempotent: every step is guarded by the inspector, so a fresh install built by
``Base.metadata.create_all`` is a no-op here.

Revision ID: v3283_withholding
Revises: v3282_einvoicing
Create Date: 2026-08-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3283_withholding"
down_revision: Union[str, Sequence[str], None] = "v3282_einvoicing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REGIME = "oe_tax_withholding_regime"
_PARTY = "oe_tax_withholding_party"
_DEDUCTION = "oe_tax_withholding_deduction"
_REVERSE_CHARGE = "oe_tax_withholding_reverse_charge"

# Money columns are NUMERIC(18, 2) - what ``MoneyType`` resolves to on
# PostgreSQL. The rate is NUMERIC(9, 4) so a scheme quoting a fraction of a
# percent is representable without rounding it into the money.
_MONEY = sa.Numeric(18, 2)
_RATE = sa.Numeric(9, 4)

# Indexes declared on the models themselves.
_MODEL_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_tax_wh_regime_country_active", _REGIME, ["country_code", "is_active"]),
    ("ix_tax_wh_party_party_regime", _PARTY, ["party_id", "regime_id"]),
    ("ix_tax_wh_party_status_valid_to", _PARTY, ["status", "valid_to"]),
    ("ix_tax_wh_deduction_period", _DEDUCTION, ["period_end", "status"]),
    ("ix_tax_wh_deduction_payment_ref", _DEDUCTION, ["payment_reference"]),
    ("ix_tax_wh_rc_invoice", _REVERSE_CHARGE, ["invoice_reference"]),
)

# ``app.core.pg_optimizations`` hangs these off the tables when the schema is
# built by ``create_all``, and it does not run on the alembic path. Declaring
# them here is what stops an upgraded deployment getting a measurably different
# schema from a fresh install: a single-column index on every foreign key that
# is not already the leftmost column of one, plus the ``project_id`` composites
# it adds wherever both columns are present.
_PERFORMANCE_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_oe_tax_withholding_party_regime_id", _PARTY, ["regime_id"]),
    ("ix_oe_tax_withholding_deduction_project_id", _DEDUCTION, ["project_id"]),
    ("ix_oe_tax_withholding_deduction_regime_id", _DEDUCTION, ["regime_id"]),
    ("ix_oe_tax_withholding_deduction_party_status_id", _DEDUCTION, ["party_status_id"]),
    ("ix_oe_tax_withholding_deduction_project_id_created_at", _DEDUCTION, ["project_id", "created_at"]),
    ("ix_oe_tax_withholding_deduction_project_id_status", _DEDUCTION, ["project_id", "status"]),
    # No single-column project_id index on the reverse charge table: the
    # unique constraint on (project_id, invoice_reference) already leads with
    # it, and a fresh install no longer adds the duplicate. Installs that ran
    # this revision earlier keep theirs, which is harmless.
    (
        "ix_oe_tax_withholding_reverse_charge_project_id_created_at",
        _REVERSE_CHARGE,
        ["project_id", "created_at"],
    ),
    ("ix_oe_tax_withholding_reverse_charge_project_id_status", _REVERSE_CHARGE, ["project_id", "status"]),
)


def _table_exists(table: str) -> bool:
    """Whether ``table`` is present in the database being migrated."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    """Index names on ``table`` (empty when the table does not exist)."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def _create_indexes() -> None:
    """Create every declared index that is not already there."""
    seen: dict[str, set[str]] = {}
    for name, table, columns in (*_MODEL_INDEXES, *_PERFORMANCE_INDEXES):
        if not _table_exists(table):
            continue
        existing = seen.setdefault(table, _indexes(table))
        if name in existing:
            continue
        op.create_index(name, table, columns)
        existing.add(name)


def upgrade() -> None:
    if not _table_exists(_REGIME):
        op.create_table(
            _REGIME,
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("scheme_code", sa.String(48), nullable=False),
            sa.Column("scheme_name", sa.String(160), nullable=False),
            sa.Column("legal_reference", sa.String(200), server_default="", nullable=False),
            sa.Column("authority", sa.String(160), server_default="", nullable=False),
            sa.Column("currency_code", sa.String(3), nullable=False),
            # Generic JSON: an event listener renders it as JSONB on PostgreSQL.
            # Never queried inside - a ``.contains()`` on a JSON column compiles
            # to a string LIKE there, not to containment.
            sa.Column("bands", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("default_band_code", sa.String(32), server_default="", nullable=False),
            sa.Column("materials_excluded", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("vat_excluded", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("verification_validity_months", sa.Integer(), server_default="0", nullable=False),
            sa.Column("threshold_amount", _MONEY, nullable=True),
            sa.Column("notes", sa.Text(), server_default="", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tax_withholding_regime"),
            sa.UniqueConstraint("country_code", "scheme_code", name="uq_tax_wh_regime_country_scheme"),
        )

    if not _table_exists(_PARTY):
        op.create_table(
            _PARTY,
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            # Not a foreign key: the payee may be a subcontractor record, a
            # vendor or a contact depending on how the deployment records its
            # supply chain, and a hard FK would tie this module to one of them.
            sa.Column("party_id", sa.String(36), nullable=False),
            sa.Column("party_type", sa.String(32), server_default="subcontractor", nullable=False),
            sa.Column("party_name", sa.String(200), server_default="", nullable=False),
            sa.Column("regime_id", sa.String(36), nullable=False),
            sa.Column("band_code", sa.String(32), nullable=False),
            sa.Column("verification_reference", sa.String(64), server_default="", nullable=False),
            sa.Column("verified_on", sa.Date(), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("evidence_document_id", sa.String(36), nullable=True),
            sa.Column("evidence_reference", sa.String(255), server_default="", nullable=False),
            sa.Column("status", sa.String(24), server_default="pending", nullable=False),
            sa.Column("notes", sa.Text(), server_default="", nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tax_withholding_party"),
            sa.ForeignKeyConstraint(
                ["regime_id"],
                [f"{_REGIME}.id"],
                name="fk_tax_wh_party_regime",
                ondelete="CASCADE",
            ),
        )

    if not _table_exists(_DEDUCTION):
        op.create_table(
            _DEDUCTION,
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("regime_id", sa.String(36), nullable=False),
            sa.Column("party_status_id", sa.String(36), nullable=True),
            sa.Column("party_id", sa.String(36), nullable=True),
            sa.Column("party_name", sa.String(200), server_default="", nullable=False),
            sa.Column("payment_reference", sa.String(128), server_default="", nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("gross_amount", _MONEY, server_default="0", nullable=False),
            sa.Column("qualifying_materials", _MONEY, server_default="0", nullable=False),
            sa.Column("vat_amount", _MONEY, server_default="0", nullable=False),
            sa.Column("taxable_base", _MONEY, server_default="0", nullable=False),
            sa.Column("rate_pct", _RATE, server_default="0", nullable=False),
            sa.Column("band_code", sa.String(32), server_default="", nullable=False),
            # Named for what it is. ``withholding_amount`` means retainage in
            # ``finance`` and reusing it here would make the two indexable by
            # the same grep and confusable by the next reader.
            sa.Column("tax_withheld", _MONEY, server_default="0", nullable=False),
            sa.Column("currency_code", sa.String(3), nullable=False),
            sa.Column("status", sa.String(24), server_default="draft", nullable=False),
            sa.Column("remitted_at", sa.Date(), nullable=True),
            sa.Column("return_reference", sa.String(128), server_default="", nullable=False),
            sa.Column("notes", sa.Text(), server_default="", nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tax_withholding_deduction"),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                name="fk_tax_wh_deduction_project",
                ondelete="CASCADE",
            ),
            # RESTRICT, not CASCADE: a scheme that has been deducted under
            # cannot be deleted out from under the deductions that quote it.
            sa.ForeignKeyConstraint(
                ["regime_id"],
                [f"{_REGIME}.id"],
                name="fk_tax_wh_deduction_regime",
                ondelete="RESTRICT",
            ),
            # SET NULL: the deduction is a filed fact and carries its own copy
            # of the band and the rate, so it survives the standing being
            # tidied away.
            sa.ForeignKeyConstraint(
                ["party_status_id"],
                [f"{_PARTY}.id"],
                name="fk_tax_wh_deduction_party",
                ondelete="SET NULL",
            ),
        )

    if not _table_exists(_REVERSE_CHARGE):
        op.create_table(
            _REVERSE_CHARGE,
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("invoice_id", sa.String(36), nullable=True),
            sa.Column("invoice_reference", sa.String(128), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("rule_code", sa.String(48), server_default="", nullable=False),
            sa.Column("buyer_accounts_for_vat", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("legal_reference", sa.String(200), server_default="", nullable=False),
            sa.Column("invoice_wording", sa.Text(), server_default="", nullable=False),
            sa.Column("net_amount", _MONEY, server_default="0", nullable=False),
            # Has to be zero whenever the buyer accounts for the VAT. Kept as a
            # column rather than assumed, because the failure being guarded
            # against is an invoice carrying both the wording and a VAT line.
            sa.Column("vat_amount", _MONEY, server_default="0", nullable=False),
            sa.Column("currency_code", sa.String(3), nullable=False),
            sa.Column("status", sa.String(24), server_default="draft", nullable=False),
            sa.Column("notes", sa.Text(), server_default="", nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_oe_tax_withholding_reverse_charge"),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                name="fk_tax_wh_rc_project",
                ondelete="CASCADE",
            ),
            # One decision per invoice per project. A changed decision
            # supersedes the old one rather than sitting beside it.
            sa.UniqueConstraint("project_id", "invoice_reference", name="uq_tax_wh_rc_project_invoice"),
        )

    _create_indexes()


def downgrade() -> None:
    # Going down loses every recorded deduction and determination. There is
    # nowhere else to keep one: what a payer withheld and remitted exists only
    # in these tables.
    if _table_exists(_REVERSE_CHARGE):
        op.drop_table(_REVERSE_CHARGE)
    if _table_exists(_DEDUCTION):
        op.drop_table(_DEDUCTION)
    if _table_exists(_PARTY):
        op.drop_table(_PARTY)
    if _table_exists(_REGIME):
        op.drop_table(_REGIME)

"""Statutory tax lines, payment certificate lines, tax office, submittal register.

Three new tables: the inputs and sign-off of one document's statutory payment
taxes with its five figures, and the entered and frozen lines of a payment
certificate. Two tax-office columns, one on a contact and one on the seller of
the e-invoice settings. Thirteen columns and two indexes that turn the
submittal table into a procurement register.

Everything above is created only when missing. An installed database gets the
tables from the boot-time ``create_all`` and the columns and indexes from the
boot-time column healer, so on such a database those steps find them in place.

One step is different. ``oe_submittals_submittal.submitted_by_org`` goes from
``VARCHAR(36)`` to ``VARCHAR(255)``: it holds a contact id or a typed company
name, the API has always accepted 255 characters, and PostgreSQL refused a
name longer than 36. Neither ``create_all`` nor the healer changes the type of
an existing column, so this migration MUST be RUN (``alembic upgrade``), not
merely stamped, for an installed database to accept a long name.

No row is rewritten. The downgrade narrows the column back only when every
stored value still fits 36 characters, and otherwise leaves it wide.

Revision ID: v67_statutory_tax_lines_and_submittal_register
Revises: v66_project_legal_entity
"""

import sqlalchemy as sa
from alembic import op

revision = "v67_statutory_tax_lines_and_submittal_register"
down_revision = "v66_project_legal_entity"
branch_labels = None
depends_on = None

_CALC = "oe_tax_withholding_statutory_calc"
_LINE = "oe_tax_withholding_statutory_line"
_CERTIFICATE = "oe_contracts_certificate_line"
_PROJECT = "oe_projects_project"
_CONTACT = "oe_contacts_contact"
_EINVOICE = "oe_finance_einvoice_settings"
_SUBMITTAL = "oe_submittals_submittal"

# Index name, table, columns. The names are the ones the models produce.
_NEW_TABLE_INDEXES = (
    ("ix_tax_wh_stat_calc_source_id", _CALC, ["source_id"]),
    ("ix_tax_wh_stat_line_source_id", _LINE, ["source_id"]),
    ("ix_oe_contracts_certificate_line_source_id", _CERTIFICATE, ["source_id"]),
    # ``app.core.pg_optimizations`` hangs these off a table that ``create_all``
    # builds, and it does not run on the alembic path. Declaring them here
    # keeps a migrated database on the same indexes as a fresh install.
    ("ix_oe_tax_withholding_statutory_calc_project_id", _CALC, ["project_id"]),
    ("ix_oe_tax_withholding_statutory_calc_project_id_created_at", _CALC, ["project_id", "created_at"]),
    ("ix_oe_tax_withholding_statutory_calc_project_id_status", _CALC, ["project_id", "status"]),
    ("ix_oe_tax_withholding_statutory_line_calc_id", _LINE, ["calc_id"]),
    ("ix_oe_tax_withholding_statutory_line_project_id", _LINE, ["project_id"]),
    ("ix_oe_tax_withholding_statutory_line_project_id_created_at", _LINE, ["project_id", "created_at"]),
)
_SUBMITTAL_INDEXES = (
    ("ix_oe_submittals_submittal_discipline", "discipline"),
    ("ix_oe_submittals_submittal_review_outcome", "review_outcome"),
)

_ORG_COLUMN = "submitted_by_org"
_ORG_OLD_LENGTH = 36
_ORG_NEW_LENGTH = 255


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _text(name: str) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=False, server_default="")


def _submittal_columns() -> list[sa.Column]:
    return [
        sa.Column("discipline", sa.String(50), nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model_reference", sa.String(255), nullable=True),
        sa.Column("country_of_origin", sa.String(2), nullable=True),
        sa.Column("supplier", sa.String(255), nullable=True),
        sa.Column("review_outcome", sa.String(50), nullable=True),
        sa.Column("review_code", sa.String(20), nullable=True),
        sa.Column("review_period_days", sa.Integer(), nullable=True),
        sa.Column("review_history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("required_on_site_date", sa.String(20), nullable=True),
        sa.Column("long_lead", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("lead_time_weeks", sa.Integer(), nullable=True),
        sa.Column("linked_drawing_ids", sa.JSON(), nullable=False, server_default="[]"),
    ]


def _columns(inspector, table: str) -> set[str] | None:
    if not inspector.has_table(table):
        return None
    return {c["name"] for c in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _org_length(inspector) -> int | None:
    """Declared length of the submitting company column, None when it cannot be read."""
    if not inspector.has_table(_SUBMITTAL):
        return None
    for column in inspector.get_columns(_SUBMITTAL):
        if column["name"] == _ORG_COLUMN:
            return getattr(column["type"], "length", None)
    return None


def _create_tables(inspector) -> None:
    # ``String(36)``: ``GUID`` is a TypeDecorator over String(36), so this is
    # the type create_all builds and the foreign keys below can reference it.
    guid = sa.String(36)
    money = sa.Numeric(18, 4)
    rate = sa.Numeric(12, 6)

    if not inspector.has_table(_CALC):
        op.create_table(
            _CALC,
            sa.Column("id", guid, primary_key=True),
            *_timestamps(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(f"{_PROJECT}.id", ondelete="CASCADE", name="fk_tax_wh_stat_calc_project"),
                nullable=False,
            ),
            sa.Column("source_kind", sa.String(32), nullable=False),
            sa.Column("source_id", guid, nullable=False),
            sa.Column("source_reference", sa.String(128), nullable=False, server_default=""),
            sa.Column("direction", sa.String(24), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("currency_code", sa.String(3), nullable=False),
            sa.Column("document_date", sa.Date(), nullable=False),
            sa.Column("net_amount", money, nullable=False),
            sa.Column("vat_rate_pct", rate, nullable=True),
            sa.Column("buyer_is_designated", sa.Boolean(), nullable=True),
            sa.Column("work_value_incl_vat", money, nullable=True),
            _text("work_value_note"),
            sa.Column("stamp_duty_base", money, nullable=True),
            sa.Column("stamp_duty_base_same_as_net", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("confirmed_by", guid, nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unconfirmed_rates_acknowledged_by", guid, nullable=True),
            sa.Column("unconfirmed_rates_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reopened_by", guid, nullable=True),
            sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
            _text("reopen_reason"),
            sa.Column("voided_by", guid, nullable=True),
            sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
            _text("void_reason"),
            sa.UniqueConstraint("source_kind", "source_id", name="uq_tax_wh_stat_calc_source"),
        )

    if not inspector.has_table(_LINE):
        op.create_table(
            _LINE,
            sa.Column("id", guid, primary_key=True),
            *_timestamps(),
            sa.Column(
                "calc_id",
                guid,
                sa.ForeignKey(f"{_CALC}.id", ondelete="CASCADE", name="fk_tax_wh_stat_line_calc"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(f"{_PROJECT}.id", ondelete="CASCADE", name="fk_tax_wh_stat_line_project"),
                nullable=False,
            ),
            sa.Column("source_kind", sa.String(32), nullable=False),
            sa.Column("source_id", guid, nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("calc_status", sa.String(24), nullable=False),
            sa.Column("tax_amount", money, nullable=True),
            sa.Column("base_amount", money, nullable=True),
            sa.Column("rate_pct", rate, nullable=True),
            sa.Column("numerator", sa.Integer(), nullable=True),
            sa.Column("denominator", sa.Integer(), nullable=True),
            sa.Column("code", sa.String(32), nullable=False, server_default=""),
            sa.Column("currency_code", sa.String(3), nullable=False),
            _text("legal_reference"),
            _text("source_url"),
            sa.Column("rate_effective_from", sa.Date(), nullable=True),
            sa.Column("rate_effective_to", sa.Date(), nullable=True),
            sa.Column("review_status", sa.String(16), nullable=False, server_default=""),
            sa.Column("reason_key", sa.String(64), nullable=False, server_default=""),
            sa.Column("reason_params", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("choice_state", sa.String(24), nullable=False, server_default=""),
            sa.Column("choice_code", sa.String(32), nullable=False, server_default=""),
            _text("choice_reason"),
            sa.Column("overridden", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("override_amount", money, nullable=True),
            _text("override_reason"),
            sa.Column("overridden_by", guid, nullable=True),
            sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("source_kind", "source_id", "kind", name="uq_tax_wh_stat_line_source_kind"),
        )

    if not inspector.has_table(_CERTIFICATE):
        op.create_table(
            _CERTIFICATE,
            sa.Column("id", guid, primary_key=True),
            *_timestamps(),
            sa.Column("source_kind", sa.String(32), nullable=False),
            sa.Column("source_id", guid, nullable=False),
            sa.Column("line_key", sa.String(64), nullable=False),
            sa.Column("calc_status", sa.String(24), nullable=False),
            sa.Column("amount", money, nullable=True),
            sa.Column("pct", sa.Numeric(9, 4), nullable=True),
            sa.Column("basis", sa.JSON(), nullable=False, server_default="{}"),
            _text("note"),
            sa.Column("frozen", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("entered_by", guid, nullable=True),
            sa.UniqueConstraint(
                "source_kind",
                "source_id",
                "line_key",
                "frozen",
                name="uq_oe_contracts_certificate_line_source_key",
            ),
        )


def upgrade() -> None:
    bind = op.get_bind()
    _create_tables(sa.inspect(bind))

    # A fresh inspector: the one above cached the catalogue before the tables
    # were created.
    inspector = sa.inspect(bind)
    for name, table, columns in _NEW_TABLE_INDEXES:
        if inspector.has_table(table) and name not in _index_names(inspector, table):
            op.create_index(name, table, columns)

    present = _columns(inspector, _CONTACT)
    if present is not None and "tax_office" not in present:
        op.add_column(_CONTACT, sa.Column("tax_office", sa.String(100), nullable=True))

    present = _columns(inspector, _EINVOICE)
    if present is not None and "seller_tax_office" not in present:
        op.add_column(_EINVOICE, sa.Column("seller_tax_office", sa.String(100), nullable=False, server_default=""))

    present = _columns(inspector, _SUBMITTAL)
    if present is None:
        return
    for column in _submittal_columns():
        if column.name not in present:
            op.add_column(_SUBMITTAL, column)
    existing = _index_names(inspector, _SUBMITTAL)
    for name, column_name in _SUBMITTAL_INDEXES:
        if name not in existing:
            op.create_index(name, _SUBMITTAL, [column_name])

    length = _org_length(inspector)
    if bind.dialect.name == "postgresql" and length is not None and length < _ORG_NEW_LENGTH:
        op.alter_column(
            _SUBMITTAL,
            _ORG_COLUMN,
            existing_type=sa.String(length),
            type_=sa.String(_ORG_NEW_LENGTH),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    present = _columns(inspector, _SUBMITTAL)
    if present is not None:
        length = _org_length(inspector)
        if bind.dialect.name == "postgresql" and length is not None and length > _ORG_OLD_LENGTH:
            # Narrowing would refuse, or cut, a company name longer than an
            # id. Only a table whose values all still fit is narrowed.
            too_long = bind.execute(
                sa.text(f'SELECT 1 FROM "{_SUBMITTAL}" WHERE char_length("{_ORG_COLUMN}") > :old_length LIMIT 1'),
                {"old_length": _ORG_OLD_LENGTH},
            ).first()
            if too_long is None:
                op.alter_column(
                    _SUBMITTAL,
                    _ORG_COLUMN,
                    existing_type=sa.String(length),
                    type_=sa.String(_ORG_OLD_LENGTH),
                    existing_nullable=True,
                )
        existing = _index_names(inspector, _SUBMITTAL)
        for name, _column_name in reversed(_SUBMITTAL_INDEXES):
            if name in existing:
                op.drop_index(name, table_name=_SUBMITTAL)
        for column in reversed(_submittal_columns()):
            if column.name in present:
                op.drop_column(_SUBMITTAL, column.name)

    present = _columns(inspector, _EINVOICE)
    if present is not None and "seller_tax_office" in present:
        op.drop_column(_EINVOICE, "seller_tax_office")

    present = _columns(inspector, _CONTACT)
    if present is not None and "tax_office" in present:
        op.drop_column(_CONTACT, "tax_office")

    # Lines before the calculation they reference.
    for table in (_CERTIFICATE, _LINE, _CALC):
        if inspector.has_table(table):
            op.drop_table(table)

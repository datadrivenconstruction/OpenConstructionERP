# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - register of bank guarantees and bonds.

Creates the four register tables (guarantee, audit event, document link, bank
credit line) and adds ``guarantee_id`` to ``oe_contracts_security``.

Bond and bank guarantee rows already on contracts move into the register: each
gets a register entry carrying its type, bank, amount, dates and status, and the
contract row is pointed at it. From then on the register writes those fields and
the contract API refuses to edit them, so the bond has one record, not two.
Insurance lines stay on the contract. Downgrade drops the link and the tables;
the contract rows keep the last values the register wrote.

Inspector-guarded, so a fresh install whose tables ``create_all`` already built
is a no-op.

Revision ID: vg01_guarantees_register
Revises: v201_takeoff_measurement_drawing_ref
Create Date: 2026-10-26
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "vg01_guarantees_register"
down_revision: str | Sequence[str] | None = "v201_takeoff_measurement_drawing_ref"
branch_labels = None
depends_on = None

_G = "oe_guarantees_guarantee"
_E = "oe_guarantees_event"
_D = "oe_guarantees_document"
_F = "oe_guarantees_facility"
_SEC = "oe_contracts_security"

_TYPE_MAP = {
    "performance_bond": "performance_bond",
    "payment_bond": "performance_bond",
    "advance_payment_bond": "advance_payment",
    "retention_bond": "retention_bond",
    "parent_company_guarantee": "parent_company",
    "bank_guarantee": "performance_bond",
}
_STATUS_MAP = {
    "required": "requested",
    "received": "issued",
    "active": "issued",
    "expired": "expired",
    "released": "released",
    "claimed": "called",
}
_PREFIX = {
    "performance_bond": "PB",
    "advance_payment": "APG",
    "retention_bond": "RB",
    "parent_company": "PCG",
}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _create() -> None:
    have = _tables()
    if _G not in have:
        op.create_table(
            _G,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reference", sa.String(length=60), nullable=False),
            sa.Column("guarantee_type", sa.String(length=40), nullable=False),
            sa.Column("direction", sa.String(length=20), nullable=False, server_default="given"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
            sa.Column("issuer_bank", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("bank_reference", sa.String(length=120), nullable=True),
            sa.Column("beneficiary", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("applicant", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("original_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
            sa.Column("percent_of_contract", sa.Numeric(7, 4), nullable=True),
            sa.Column("contract_value", sa.Numeric(18, 4), nullable=True),
            sa.Column("issue_date", sa.Date(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("auto_extend", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("extension_months", sa.Integer(), nullable=True),
            sa.Column("claim_period_days", sa.Integer(), nullable=True),
            sa.Column("defects_period_months", sa.Integer(), nullable=True),
            sa.Column("advance_amount", sa.Numeric(18, 4), nullable=True),
            sa.Column("advance_recovered", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("advance_recovery_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("replaces_cash_retention", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("commission_rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("form_code", sa.String(length=60), nullable=True),
            sa.Column("contract_id", sa.String(length=36), nullable=True),
            sa.Column("contract_security_id", sa.String(length=36), nullable=True),
            sa.Column("subcontractor_id", sa.String(length=36), nullable=True),
            sa.Column("tender_id", sa.String(length=36), nullable=True),
            sa.Column("bid_id", sa.String(length=36), nullable=True),
            sa.Column("facility_id", sa.String(length=36), nullable=True),
            sa.Column("last_alert_band", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            *_ts(),
            sa.UniqueConstraint("project_id", "reference", name="uq_guarantees_project_reference"),
        )
        op.create_index("ix_oe_guarantees_guarantee_project_id", _G, ["project_id"])
        op.create_index("ix_guarantees_project_status", _G, ["project_id", "status"])
        op.create_index("ix_guarantees_contract", _G, ["contract_id"])
        op.create_index("ix_guarantees_expiry", _G, ["expiry_date"])
    if _E not in have:
        op.create_table(
            _E,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "guarantee_id", sa.String(length=36), sa.ForeignKey(f"{_G}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("action", sa.String(length=30), nullable=False),
            sa.Column("from_status", sa.String(length=20), nullable=True),
            sa.Column("to_status", sa.String(length=20), nullable=True),
            sa.Column("amount_before", sa.Numeric(18, 4), nullable=True),
            sa.Column("amount_after", sa.Numeric(18, 4), nullable=True),
            sa.Column("changes", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("source", sa.String(length=60), nullable=True),
            sa.Column("source_id", sa.String(length=36), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            *_ts(),
        )
        op.create_index("ix_guarantees_event_guarantee", _E, ["guarantee_id", "created_at"])
    if _D not in have:
        op.create_table(
            _D,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "guarantee_id", sa.String(length=36), sa.ForeignKey(f"{_G}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("kind", sa.String(length=30), nullable=False, server_default="original"),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            *_ts(),
            sa.UniqueConstraint("guarantee_id", "document_id", name="uq_guarantees_document"),
        )
        op.create_index("ix_oe_guarantees_document_guarantee_id", _D, ["guarantee_id"])
        op.create_index("ix_oe_guarantees_document_document_id", _D, ["document_id"])
    if _F not in have:
        op.create_table(
            _F,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("bank_name", sa.String(length=255), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("limit_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("legal_entity_id", sa.String(length=36), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            *_ts(),
            sa.UniqueConstraint("bank_name", "currency", "name", name="uq_guarantees_facility"),
        )


def _add_link() -> None:
    if _SEC not in _tables():
        return
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_SEC)}
    if "guarantee_id" not in cols:
        op.add_column(_SEC, sa.Column("guarantee_id", sa.String(length=36), nullable=True))
        op.create_index("ix_oe_contracts_security_guarantee_id", _SEC, ["guarantee_id"])


def _date(value: object) -> str | None:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _move_contract_bonds() -> None:
    """One register entry per bond row on a contract, and the row pointed at it."""
    if _SEC not in _tables() or "oe_contracts_contract" not in _tables():
        return
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT s.id, s.contract_id, s.security_type, s.reference, s.provider_name, s.amount, s.currency, "
            "s.percent_of_contract, s.valid_from, s.valid_to, s.status, s.notes, c.project_id, c.total_value, "
            "c.currency AS contract_currency "
            f"FROM {_SEC} s JOIN oe_contracts_contract c ON c.id = s.contract_id "
            "WHERE s.guarantee_id IS NULL"
        )
    ).mappings()
    taken: dict[str, set[str]] = {}
    now = datetime.now(UTC)
    for row in list(rows):
        gtype = _TYPE_MAP.get(row["security_type"])
        if gtype is None:
            continue
        project = str(row["project_id"])
        if project not in taken:
            taken[project] = {
                r for (r,) in bind.execute(sa.text(f"SELECT reference FROM {_G} WHERE project_id = :p"), {"p": project})
            }
        reference = (row["reference"] or "").strip()[:60]
        if not reference or reference in taken[project]:
            n = len(taken[project]) + 1
            while f"{_PREFIX[gtype]}-{n:04d}" in taken[project]:
                n += 1
            reference = f"{_PREFIX[gtype]}-{n:04d}"
        taken[project].add(reference)
        gid = str(uuid.uuid4())
        status = _STATUS_MAP.get(row["status"], "draft")
        bind.execute(
            sa.text(
                f"INSERT INTO {_G} (id, project_id, reference, guarantee_type, direction, status, issuer_bank, "
                "beneficiary, applicant, amount, original_amount, currency, percent_of_contract, contract_value, "
                "issue_date, expiry_date, auto_extend, advance_recovered, replaces_cash_retention, contract_id, "
                "contract_security_id, notes, metadata, created_at, updated_at) VALUES (:id, :project, :ref, "
                ":gtype, 'given', :status, :bank, '', '', :amount, :amount, :currency, :pct, :value, :issue, "
                ":expiry, false, 0, false, :contract, :sec, :notes, '{}', :now, :now)"
            ),
            {
                "id": gid,
                "project": project,
                "ref": reference,
                "gtype": gtype,
                "status": status,
                "bank": row["provider_name"] or "",
                "amount": row["amount"] or 0,
                "currency": (row["currency"] or row["contract_currency"] or "")[:3],
                "pct": row["percent_of_contract"],
                "value": row["total_value"],
                "issue": _date(row["valid_from"]),
                "expiry": _date(row["valid_to"]),
                "contract": str(row["contract_id"]),
                "sec": str(row["id"]),
                "notes": row["notes"],
                "now": now,
            },
        )
        bind.execute(
            sa.text(
                f"INSERT INTO {_E} (id, guarantee_id, action, to_status, amount_after, changes, source, source_id, "
                "created_at, updated_at) VALUES (:id, :g, 'created', :status, :amount, '{}', 'contract_security', "
                ":sec, :now, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "g": gid,
                "status": status,
                "amount": row["amount"] or 0,
                "sec": str(row["id"]),
                "now": now,
            },
        )
        bind.execute(sa.text(f"UPDATE {_SEC} SET guarantee_id = :g WHERE id = :id"), {"g": gid, "id": str(row["id"])})


def upgrade() -> None:
    _create()
    _add_link()
    _move_contract_bonds()


def downgrade() -> None:
    have = _tables()
    if _SEC in have:
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_SEC)}
        if "guarantee_id" in cols:
            op.drop_index("ix_oe_contracts_security_guarantee_id", table_name=_SEC)
            op.drop_column(_SEC, "guarantee_id")
    for table in (_D, _E, _F, _G):
        if table in have:
            op.drop_table(table)

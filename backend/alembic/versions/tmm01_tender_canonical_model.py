# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""tenders: one canonical model, legacy map, copy of tendering and rfq_bidding

The ``oe_bid_management_*`` tables become the one tender store. This revision
adds what the other two modules hold and bid management did not (portal link
lifecycle, quote validity and exchange rate, late admission, free bid lines,
award method and basis, submission adjustments), the ``oe_tender_legacy_map``
table, and copies every tendering package and RFQ into the canonical tables.

Schema: additive, inspector-guarded, the one alteration is ``line_item_id``
dropping NOT NULL (no existing row can refuse it), so a healed database and a
walked chain end up the same. Data: the copy writes only new mirror rows and
map rows and never touches a source row; it is re-runnable through the map.

Run this migration (``alembic upgrade``) rather than stamping it where an
operator wants the copy at upgrade time; installs that only heal at boot get
the same copy from the boot repair below.

# boot-repair: registry=tender_legacy_copy
# data-rewrite-ack: oe_bid_management_package - inserts mirror rows only, one per source package, batched per package

Revision ID: tmm01_tender_canonical_model
Revises: svr01_survey_register_surfaces
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tmm01_tender_canonical_model"
down_revision: str | Sequence[str] | None = "cpb01_central_purchasing_bundles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PACKAGE = "oe_bid_management_package"
_SUB_LINE = "oe_bid_management_submission_line"
_ADJUSTMENT = "oe_bid_management_submission_adjustment"
_MAP = "oe_tender_legacy_map"

_NEW_COLUMNS: dict[str, list[tuple[str, sa.types.TypeEngine]]] = {
    _PACKAGE: [
        ("legacy_source", sa.String(32)),
        ("boq_id", sa.String(36)),
        ("legal_entity_id", sa.String(36)),
        ("cost_line_ids", sa.JSON()),
        ("evaluation_method", sa.String(30)),
        ("require_full_scope", sa.Boolean()),
    ],
    "oe_bid_management_invitation": [
        ("expires_at", sa.String(40)),
        ("revoked_at", sa.String(40)),
        ("draft_saved_at", sa.String(40)),
        ("draft", sa.JSON()),
    ],
    "oe_bid_management_bidder": [
        ("withdrawn_at", sa.String(40)),
        ("withdrawn_reason", sa.Text()),
    ],
    "oe_bid_management_submission": [
        ("validity_days", sa.Integer()),
        ("exchange_rate", sa.Numeric(18, 8)),
        ("exchange_rate_date", sa.String(20)),
        ("exchange_rate_source", sa.String(60)),
        ("admitted_by", sa.String(36)),
        ("admitted_at", sa.String(40)),
        ("admission_reason", sa.Text()),
        ("late_reason", sa.Text()),
    ],
    _SUB_LINE: [
        ("description", sa.Text()),
        ("unit", sa.String(20)),
        ("unit_conversion_factor", sa.Numeric(18, 6)),
    ],
    "oe_bid_management_award": [
        ("method", sa.String(30)),
        ("is_override", sa.Boolean()),
        ("recommended_bidder_id", sa.String(36)),
        ("basis", sa.JSON()),
    ],
}
_NEW_INDEXES = (
    ("ix_oe_bid_management_package_legacy_source", _PACKAGE, ["legacy_source"]),
    ("ix_oe_bid_management_package_boq_id", _PACKAGE, ["boq_id"]),
    ("ix_oe_bid_management_package_legal_entity_id", _PACKAGE, ["legal_entity_id"]),
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    for table, cols in _NEW_COLUMNS.items():
        if table not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, kind in cols:
            if name not in have:
                op.add_column(table, sa.Column(name, kind, nullable=True))
    if _PACKAGE in existing:
        have_ix = {i["name"] for i in insp.get_indexes(_PACKAGE)}
        for name, table, cols in _NEW_INDEXES:
            if name not in have_ix:
                op.create_index(name, table, cols)

    if _SUB_LINE in existing:
        line_item = next(c for c in insp.get_columns(_SUB_LINE) if c["name"] == "line_item_id")
        if not line_item.get("nullable", True):
            op.alter_column(_SUB_LINE, "line_item_id", existing_type=sa.String(36), nullable=True)

    if _ADJUSTMENT not in existing:
        op.create_table(
            _ADJUSTMENT,
            *_timestamps(),
            sa.Column(
                "submission_id",
                sa.String(36),
                sa.ForeignKey("oe_bid_management_submission.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("included_in_bid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(20), nullable=False, server_default="bidder"),
        )
        op.create_index("ix_oe_bid_management_submission_adjustment_submission_id", _ADJUSTMENT, ["submission_id"])

    if _MAP not in existing:
        op.create_table(
            _MAP,
            *_timestamps(),
            sa.Column("source_table", sa.String(64), nullable=False),
            sa.Column("source_id", sa.String(36), nullable=False),
            sa.Column("target_table", sa.String(64), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=False),
            sa.Column("package_id", sa.String(36), nullable=True),
            sa.Column("copied_at", sa.String(40), nullable=True),
            sa.UniqueConstraint("source_table", "source_id", name="uq_oe_tender_legacy_map_source"),
        )
        op.create_index("ix_oe_tender_legacy_map_target", _MAP, ["target_table", "target_id"])
        op.create_index("ix_oe_tender_legacy_map_package", _MAP, ["package_id"])

    if _PACKAGE in existing:
        from app.modules.bid_management.legacy_copy import copy_all  # noqa: PLC0415

        copy_all(bind, apply=True, only_unmapped=True, reflect=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    if _PACKAGE in existing and _MAP in existing:
        # Mirrors are copies; the source rows were never touched.
        mirror = sa.text(f"SELECT id FROM {_PACKAGE} WHERE legacy_source IS NOT NULL")  # noqa: S608
        ids = [r[0] for r in bind.execute(mirror)]
        if ids:
            from app.modules.bid_management.legacy_copy import LegacyCopier, LegacyMap, _PackageWriter  # noqa: PLC0415

            copier = LegacyCopier(bind, reflect=True)
            for package_id in ids:
                _PackageWriter(copier.t, LegacyMap(copier.t), str(package_id), {}).clear_children()
            bind.execute(sa.text(f"DELETE FROM {_PACKAGE} WHERE legacy_source IS NOT NULL"))  # noqa: S608
    for table in (_MAP, _ADJUSTMENT):
        if table in existing:
            op.drop_table(table)
    if _PACKAGE in existing:
        have_ix = {i["name"] for i in insp.get_indexes(_PACKAGE)}
        for name, table, _cols in _NEW_INDEXES:
            if name in have_ix:
                op.drop_index(name, table_name=table)
    for table, cols in _NEW_COLUMNS.items():
        if table not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, _kind in cols:
            if name in have:
                op.drop_column(table, name)

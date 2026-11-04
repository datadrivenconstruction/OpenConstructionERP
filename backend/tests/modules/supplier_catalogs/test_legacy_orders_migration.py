# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The vdup9 revision copies supplier-catalogue orders and receipts into procurement.

Runs the revision's real ``upgrade()``/``downgrade()`` against legacy rows in a
schema of its own. What is pinned: the copy maps status, currency, unit and
vendor; a posted receipt arrives already posted with its stock effect claimed
and its ledger rows re-pointed; a row that cannot be mapped is reported and
skipped without stopping the others; a second run changes nothing; the
downgrade removes the copies and restores the ledger.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

from app.core.event_effects import EventEffect
from app.database import Base
from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrder, PurchaseOrderItem
from app.modules.supplier_catalogs import legacy_migration as lm
from app.modules.supplier_catalogs.models import (
    CatalogItem,
    GRLine,
    ItemCategory,
    LegacyMigrationReport,
    POLine,
    PRLine,
    PurchaseRequisition,
    StockMovement,
    SupplierGoodsReceipt,
    SupplierPurchaseOrder,
    Vendor,
    Warehouse,
)

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[3] / "alembic" / "versions" / "vdup9_orders_receipts_role_split.py"
)
_TABLES = [
    m.__table__
    for m in (
        EventEffect,
        ItemCategory,
        CatalogItem,
        Vendor,
        Warehouse,
        PurchaseRequisition,
        PRLine,
        SupplierPurchaseOrder,
        POLine,
        SupplierGoodsReceipt,
        GRLine,
        StockMovement,
        LegacyMigrationReport,
        PurchaseOrder,
        PurchaseOrderItem,
        GoodsReceipt,
        GoodsReceiptItem,
    )
]
PROJECT = str(uuid.uuid4())
CONTACT = str(uuid.uuid4())


class Db:
    """A throwaway schema of the test cluster; every connection it hands out is pinned to it."""

    def __init__(self, engine: Engine, schema: str) -> None:
        self.engine = engine
        self.schema = schema

    def connect(self) -> Connection:
        conn = self.engine.connect()
        conn.execute(text(f'SET search_path TO "{self.schema}"'))
        conn.commit()
        return conn

    def scalar(self, sql: str, **params):
        with self.connect() as conn:
            return conn.execute(text(sql), params).scalar()


@pytest.fixture
def db() -> Iterator[Db]:
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg2")
    engine = create_engine(url, poolclass=NullPool)
    schema = f"vdup9_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET search_path TO "{schema}"'))
        Base.metadata.create_all(conn, tables=_TABLES)
    yield Db(engine, schema)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def _seed(db: Db) -> dict[str, str]:
    keys = ("vendor", "novendor", "wh", "item", "po", "po2", "po3", "gr", "gr_draft", "pl", "pl2", "pl3", "gl", "mv")
    ids = {k: str(uuid.uuid4()) for k in keys}
    vendor_sql = (
        "INSERT INTO oe_supplier_catalogs_vendor (id, code, name, contact_id, status, currency, "
        "payment_terms_days, categories_json, preferred_for_json, contacts_json) VALUES "
        "(:i, 'V1', 'Nordstahl', :c, 'active', 'EUR', 30, '[]', '[]', '[]'), "
        "(:n, 'V2', 'NoContact', NULL, 'active', 'EUR', 30, '[]', '[]', '[]')"
    )
    with db.connect() as c, c.begin():
        c.execute(text(vendor_sql), {"i": ids["vendor"], "c": CONTACT, "n": ids["novendor"]})
        c.execute(
            text(
                "INSERT INTO oe_supplier_catalogs_warehouse (id, code, name, project_id, status) "
                "VALUES (:w, 'W1', 'Yard', :p, 'active')"
            ),
            {"w": ids["wh"], "p": PROJECT},
        )
        c.execute(
            text(
                "INSERT INTO oe_supplier_catalogs_catalog_item (id, sku, name, unit_of_measure, active, "
                "reorder_point, spec_json, commodity_scheme) VALUES (:i, 'S1', 'Rebar', 't', true, 0, '{}', 'unspsc')"
            ),
            {"i": ids["item"]},
        )

        def po(key: str, number: str, vendor: str, status: str) -> None:
            c.execute(
                text(
                    "INSERT INTO oe_supplier_catalogs_po (id, number, vendor_id, project_id, status, order_date, "
                    "currency, subtotal, tax, total, terms) VALUES "
                    "(:i, :n, :v, :p, :s, '2026-05-01', 'EUR', 1000, 190, 1190, 'net 30')"
                ),
                {"i": ids[key], "n": number, "v": vendor, "p": PROJECT, "s": status},
            )

        po("po", "SPO-1", ids["vendor"], "partial")
        po("po2", "SPO-2", ids["novendor"], "sent")
        po("po3", "SPO-3", ids["vendor"], "weird")
        c.execute(
            text(
                "INSERT INTO oe_supplier_catalogs_po_line (id, po_id, catalog_item_id, description, ordered_qty, "
                "unit_of_measure, unit_price, line_total, received_qty, invoiced_qty) "
                "VALUES (:l, :po, :it, 'Rebar B500', 10, ' t ', 100, 1000, 6, 0)"
            ),
            {"l": ids["pl"], "po": ids["po"], "it": ids["item"]},
        )
        for key, po_key in (("pl2", "po2"), ("pl3", "po3")):
            c.execute(
                text(
                    "INSERT INTO oe_supplier_catalogs_po_line (id, po_id, description, ordered_qty, "
                    "unit_of_measure, unit_price, line_total, received_qty, invoiced_qty) "
                    "VALUES (:l, :po, 'x', 1, 'pcs', 1, 1, 0, 0)"
                ),
                {"l": ids[key], "po": ids[po_key]},
            )
        for key, status in (("gr", "posted"), ("gr_draft", "draft")):
            c.execute(
                text(
                    "INSERT INTO oe_supplier_catalogs_gr (id, number, po_id, warehouse_id, received_at, status, "
                    "scan_method, photos_json) VALUES (:i, :n, :po, :w, '2026-05-10T08:00:00', :s, 'manual', '[]')"
                ),
                {"i": ids[key], "n": f"GR-{status}", "po": ids["po"], "w": ids["wh"], "s": status},
            )
        c.execute(
            text(
                "INSERT INTO oe_supplier_catalogs_gr_line (id, gr_id, po_line_id, received_qty, accepted_qty, "
                "rejected_qty, batch_lot) VALUES (:l, :g, :pl, 6, 5, 1, 'B-7')"
            ),
            {"l": ids["gl"], "g": ids["gr"], "pl": ids["pl"]},
        )
        c.execute(
            text(
                "INSERT INTO oe_supplier_catalogs_stock_movement (id, warehouse_id, catalog_item_id, "
                "movement_type, quantity, reference_type, reference_id, metadata) "
                "VALUES (:m, :w, :it, 'in', 5, 'gr', :g, '{}')"
            ),
            {"m": ids["mv"], "w": ids["wh"], "it": ids["item"], "g": ids["gr"]},
        )
    return ids


def _run(db: Db, fn: str) -> None:
    spec = importlib.util.spec_from_file_location("mig_vdup9", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with db.connect() as conn, conn.begin(), Operations.context(MigrationContext.configure(connection=conn)):
        getattr(module, fn)()


def test_copy_maps_the_order_and_its_posted_receipt(db: Db) -> None:
    ids = _seed(db)
    _run(db, "upgrade")

    with db.connect() as conn:
        po = (
            conn.execute(text("SELECT * FROM oe_procurement_po WHERE legacy_id = :i"), {"i": ids["po"]})
            .mappings()
            .one()
        )
        item = (
            conn.execute(text("SELECT * FROM oe_procurement_po_item WHERE legacy_id = :i"), {"i": ids["pl"]})
            .mappings()
            .one()
        )
        gr = (
            conn.execute(text("SELECT * FROM oe_procurement_goods_receipt WHERE legacy_id = :i"), {"i": ids["gr"]})
            .mappings()
            .one()
        )
        mv_ref = conn.execute(text("SELECT reference_id FROM oe_supplier_catalogs_stock_movement")).scalar_one()
        claimed = conn.execute(text("SELECT event_key FROM oe_event_effect")).scalars().all()
        back = conn.execute(
            text("SELECT migrated_to_id FROM oe_supplier_catalogs_po WHERE id = :i"), {"i": ids["po"]}
        ).scalar_one()

    assert po["status"] == "partially_received" and po["currency_code"] == "EUR"
    assert po["vendor_contact_id"] == CONTACT and po["amount_total"] == "1190"
    assert po["legacy_source"] == "supplier_catalogs" and back == po["id"]
    assert item["unit"] == "t" and item["quantity"] == "10" and item["unit_rate"] == "100"
    assert item["catalog_item_id"] == ids["item"]
    assert gr["status"] == "confirmed" and gr["receipt_date"] == "2026-05-10"
    assert gr["metadata"]["stock_moved"] is True
    assert mv_ref == gr["id"], "the ledger row follows the copied receipt"
    assert claimed == [f"gr:{gr['id']}:posted"], "the stock effect is claimed so it never moves twice"
    assert db.scalar("SELECT count(*) FROM oe_procurement_goods_receipt") == 2


def test_unmappable_rows_are_reported_and_do_not_stop_the_rest(db: Db) -> None:
    ids = _seed(db)
    _run(db, "upgrade")

    with db.connect() as conn:
        rows = conn.execute(text("SELECT legacy_id, reason FROM oe_supplier_catalogs_migration_report")).all()
    reasons = {r.legacy_id: r.reason for r in rows}
    assert "contacts directory" in reasons[ids["po2"]]
    assert "weird" in reasons[ids["po3"]]
    assert db.scalar("SELECT count(*) FROM oe_procurement_po") == 1


def test_a_second_run_changes_nothing(db: Db) -> None:
    _seed(db)
    counts = (
        "SELECT (SELECT count(*) FROM oe_procurement_po), (SELECT count(*) FROM oe_procurement_goods_receipt), "
        "(SELECT count(*) FROM oe_procurement_gr_item), (SELECT count(*) FROM oe_event_effect)"
    )

    def snapshot() -> tuple:
        with db.connect() as conn:
            return tuple(conn.execute(text(counts)).one())

    _run(db, "upgrade")
    first = snapshot()
    _run(db, "upgrade")
    assert snapshot() == first == (1, 2, 1, 1)


def test_preview_writes_nothing_and_counts_the_same(db: Db) -> None:
    _seed(db)
    with db.connect() as conn:
        result = lm.migrate_project(conn, PROJECT, write=False).as_dict()
        assert conn.execute(text("SELECT count(*) FROM oe_procurement_po")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM oe_supplier_catalogs_migration_report")).scalar_one() == 0
    assert result["orders"] == {"total": 3, "to_copy": 1, "already": 0}
    assert result["receipts"] == {"total": 2, "to_copy": 2, "already": 0}
    assert {u["reference"] for u in result["unmappable"]} == {"SPO-2", "SPO-3"}


def test_downgrade_removes_the_copies_and_restores_the_ledger(db: Db) -> None:
    ids = _seed(db)
    _run(db, "upgrade")
    _run(db, "downgrade")

    assert db.scalar("SELECT reference_id FROM oe_supplier_catalogs_stock_movement") == ids["gr"]
    with db.connect() as conn:
        assert "legacy_source" not in {c["name"] for c in sa.inspect(conn).get_columns("oe_procurement_po")}
        assert conn.execute(text("SELECT count(*) FROM oe_procurement_po")).scalar_one() == 0


@pytest.mark.asyncio
async def test_preview_service_reads_through_an_async_session(db: Db) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.modules.supplier_catalogs.service import SupplierCatalogsService

    _seed(db)
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {"search_path": db.schema}})
    try:
        async with AsyncSession(engine) as session:
            result = await SupplierCatalogsService(session).migration_preview(uuid.UUID(PROJECT))
    finally:
        await engine.dispose()
    assert result["orders"]["to_copy"] == 1 and len(result["unmappable"]) == 2
    assert db.scalar("SELECT count(*) FROM oe_procurement_po") == 0

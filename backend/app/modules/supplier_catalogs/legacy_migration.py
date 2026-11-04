# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Copy supplier-catalogue orders and receipts into the procurement tables.

Procurement owns the purchase order and the goods receipt; the supplier
catalogue used to keep a second pair. This module copies each legacy order
(with lines) and receipt (with lines) into procurement, once.

* Idempotent: a copy is identified by ``(legacy_source, legacy_id)``; a second
  run finds it and only repairs the back-pointer ``migrated_to_id``.
* A row that cannot be mapped is written to the report table and skipped; it
  never stops the others.
* A posted receipt is copied as already posted: its stock already moved, so the
  copy is marked ``stock_moved``, its event key is claimed, and the stock
  movements that name the old receipt are re-pointed at the copy.
* The legacy tables are kept (stock movements cascade from them) and are only
  read through ``migrated_to_id`` afterwards.

The functions take a plain synchronous connection so the Alembic revision and
the dry-run endpoint (through ``AsyncSession.run_sync``) share one code path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa

LEGACY_SOURCE = "supplier_catalogs"
REPORT_TABLE = "oe_supplier_catalogs_migration_report"

# supplier_catalogs order status -> procurement order status
PO_STATUS_MAP = {
    "draft": "draft",
    "sent": "issued",
    "acknowledged": "issued",
    "partial": "partially_received",
    "received": "completed",
    "closed": "completed",
    "cancelled": "cancelled",
}
# supplier_catalogs receipt status -> procurement receipt status
GR_STATUS_MAP = {"draft": "draft", "posted": "confirmed"}

_ZERO = Decimal("0")

_meta = sa.MetaData()


def _t(name: str, *cols: sa.Column) -> sa.Table:
    return sa.Table(name, _meta, sa.Column("id", sa.String(36), primary_key=True), *cols)


# Local, minimal table definitions: the revision must not depend on columns a
# later revision adds to the ORM models.
_PO = _t(
    "oe_procurement_po",
    sa.Column("project_id", sa.String(36)),
    sa.Column("vendor_contact_id", sa.String(36)),
    sa.Column("po_number", sa.String(50)),
    sa.Column("po_type", sa.String(50)),
    sa.Column("issue_date", sa.String(40)),
    sa.Column("delivery_date", sa.String(40)),
    sa.Column("currency_code", sa.String(10)),
    sa.Column("amount_subtotal", sa.String(50)),
    sa.Column("tax_amount", sa.String(50)),
    sa.Column("amount_total", sa.String(50)),
    sa.Column("retention_percent", sa.Numeric(5, 2)),
    sa.Column("retain_on_receipt", sa.Boolean),
    sa.Column("retainage_released_amount", sa.String(50)),
    sa.Column("status", sa.String(50)),
    sa.Column("supplier_acknowledged_at", sa.String(40)),
    sa.Column("notes", sa.Text),
    sa.Column("metadata", sa.JSON),
    sa.Column("legacy_source", sa.String(40)),
    sa.Column("legacy_id", sa.String(36)),
)
_ITEM = _t(
    "oe_procurement_po_item",
    sa.Column("po_id", sa.String(36)),
    sa.Column("description", sa.String(500)),
    sa.Column("quantity", sa.String(50)),
    sa.Column("unit", sa.String(20)),
    sa.Column("unit_rate", sa.String(50)),
    sa.Column("amount", sa.String(50)),
    sa.Column("sort_order", sa.Integer),
    sa.Column("requires_inspection", sa.Boolean),
    sa.Column("catalog_item_id", sa.String(36)),
    sa.Column("legacy_source", sa.String(40)),
    sa.Column("legacy_id", sa.String(36)),
)
_GR = _t(
    "oe_procurement_goods_receipt",
    sa.Column("po_id", sa.String(36)),
    sa.Column("receipt_date", sa.String(40)),
    sa.Column("received_by_id", sa.String(36)),
    sa.Column("status", sa.String(50)),
    sa.Column("notes", sa.Text),
    sa.Column("source", sa.String(30)),
    sa.Column("metadata", sa.JSON),
    sa.Column("legacy_source", sa.String(40)),
    sa.Column("legacy_id", sa.String(36)),
)
_GR_ITEM = _t(
    "oe_procurement_gr_item",
    sa.Column("receipt_id", sa.String(36)),
    sa.Column("po_item_id", sa.String(36)),
    sa.Column("quantity_ordered", sa.String(50)),
    sa.Column("quantity_received", sa.String(50)),
    sa.Column("quantity_rejected", sa.String(50)),
    sa.Column("batch_lot", sa.String(100)),
    sa.Column("serial_numbers", sa.JSON),
)
_EFFECT_TABLE = "oe_event_effect"


def _effect_key_column(conn: sa.Connection) -> str:
    """Name of the claim-key column: ``key`` before vev01_event_effect, ``event_key`` after."""
    cols = {c["name"] for c in sa.inspect(conn).get_columns(_EFFECT_TABLE)}
    return "event_key" if "event_key" in cols else "key"


_REPORT = _t(
    REPORT_TABLE,
    sa.Column("project_id", sa.String(36)),
    sa.Column("kind", sa.String(10)),
    sa.Column("legacy_id", sa.String(36)),
    sa.Column("reason", sa.Text),
)


@dataclass
class ProjectResult:
    """Counts and unmappable rows of one project's migration run."""

    project_id: str
    orders_total: int = 0
    orders_copied: int = 0
    orders_already: int = 0
    receipts_total: int = 0
    receipts_copied: int = 0
    receipts_already: int = 0
    unmappable: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "orders": {"total": self.orders_total, "to_copy": self.orders_copied, "already": self.orders_already},
            "receipts": {
                "total": self.receipts_total,
                "to_copy": self.receipts_copied,
                "already": self.receipts_already,
            },
            "unmappable": self.unmappable,
        }


# ── Pure mapping ────────────────────────────────────────────────────────────


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        return _ZERO


def _s(value: Decimal) -> str:
    """Decimal as a plain string without exponent or trailing zeros ("12.5", "3")."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def map_unit(unit: Any) -> str | None:
    """Unit as procurement stores it: trimmed, at most 20 characters, blank is none."""
    cleaned = str(unit or "").strip()[:20]
    return cleaned or None


def map_currency(code: Any) -> str | None:
    """ISO code in upper case; a blank is not a currency."""
    cleaned = str(code or "").strip().upper()
    return cleaned or None


def _uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (ValueError, AttributeError):
        return None


def plan_order(po: dict[str, Any], lines: list[dict[str, Any]], vendor_contact_id: str | None) -> dict[str, Any] | str:
    """The procurement order for one legacy order, or the reason it cannot be mapped."""
    status = PO_STATUS_MAP.get(str(po["status"] or "").strip())
    if status is None:
        return f"status '{po['status']}' has no procurement equivalent"
    currency = map_currency(po["currency"])
    if currency is None:
        return "the order has no currency"
    if not vendor_contact_id:
        return "the vendor has no entry in the contacts directory"
    if not lines:
        return "the order has no lines"
    items = [
        {
            "legacy_id": line["id"],
            "description": str(line["description"])[:500],
            "quantity": _s(_dec(line["ordered_qty"])),
            "unit": map_unit(line["unit_of_measure"]),
            "unit_rate": _s(_dec(line["unit_price"])),
            "amount": _s(_dec(line["line_total"])),
            "sort_order": i,
            "catalog_item_id": line["catalog_item_id"],
        }
        for i, line in enumerate(lines)
    ]
    return {
        "po_number": str(po["number"])[:50],
        "status": status,
        "currency_code": currency,
        "vendor_contact_id": vendor_contact_id,
        "issue_date": po["order_date"],
        "delivery_date": po["expected_delivery"],
        "amount_subtotal": _s(_dec(po["subtotal"])),
        "tax_amount": _s(_dec(po["tax"])),
        "amount_total": _s(_dec(po["total"])),
        "acknowledged_at": po["order_date"] if str(po["status"]) == "acknowledged" else None,
        "notes": po["terms"],
        "metadata": {
            "origin": LEGACY_SOURCE,
            "legacy": {
                "number": po["number"],
                "vendor_id": po["vendor_id"],
                "pr_id": po["pr_id"],
                "contract_id": po["contract_id"],
            },
        },
        "items": items,
    }


def plan_receipt(gr: dict[str, Any], lines: list[dict[str, Any]], item_ids: dict[str, str]) -> dict[str, Any] | str:
    """The procurement receipt for one legacy receipt, or the reason it cannot be mapped."""
    status = GR_STATUS_MAP.get(str(gr["status"] or "").strip())
    if status is None:
        return f"status '{gr['status']}' has no procurement equivalent"
    items = []
    for line in lines:
        item_id = item_ids.get(line["po_line_id"])
        if item_id is None:
            return f"receipt line {line['id']} points at an order line that was not copied"
        items.append(
            {
                "po_item_id": item_id,
                "quantity_ordered": _s(_dec(line["ordered_qty"])),
                "quantity_received": _s(_dec(line["received_qty"])),
                "quantity_rejected": _s(_dec(line["rejected_qty"])),
                "batch_lot": line["batch_lot"],
                "serial_numbers": line["serial_numbers_json"],
            }
        )
    posted = status == "confirmed"
    return {
        "status": status,
        "receipt_date": str(gr["received_at"] or "")[:10] or datetime.now(UTC).date().isoformat(),
        "received_by_id": _uuid_or_none(gr["received_by"]),
        "notes": gr["discrepancy_notes"],
        "stock_moved": posted,
        "metadata": {
            "origin": LEGACY_SOURCE,
            "stock_moved": posted,
            "legacy": {
                "number": gr["number"],
                "warehouse_id": gr["warehouse_id"],
                "scan_method": gr["scan_method"],
                "photos": gr["photos_json"] or [],
            },
        },
        "items": items,
    }


# ── Execution ───────────────────────────────────────────────────────────────


def pending_project_ids(conn: sa.Connection) -> list[str]:
    """Projects that still have a legacy order not yet copied."""
    rows = conn.execute(
        sa.text("SELECT DISTINCT project_id FROM oe_supplier_catalogs_po WHERE migrated_to_id IS NULL")
    ).all()
    return [str(r[0]) for r in rows]


def _report(conn: sa.Connection, project_id: str, kind: str, legacy_id: str, reason: str) -> None:
    present = conn.execute(
        sa.select(_REPORT.c.id).where(_REPORT.c.kind == kind, _REPORT.c.legacy_id == legacy_id)
    ).first()
    if present is None:
        conn.execute(
            sa.insert(_REPORT).values(
                id=str(uuid.uuid4()), project_id=project_id, kind=kind, legacy_id=legacy_id, reason=reason
            )
        )
    else:
        conn.execute(sa.update(_REPORT).where(_REPORT.c.id == present[0]).values(reason=reason))


def _clear_report(conn: sa.Connection, kind: str, legacy_id: str) -> None:
    conn.execute(sa.delete(_REPORT).where(_REPORT.c.kind == kind, _REPORT.c.legacy_id == legacy_id))


_ID_KEYS = ("id", "po_id", "po_line_id", "vendor_id", "pr_id", "warehouse_id", "catalog_item_id", "migrated_to_id")


def _rows(conn: sa.Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    out = []
    for row in conn.execute(sa.text(sql), params).mappings():
        d = dict(row)
        for k in _ID_KEYS:
            if d.get(k) is not None:
                d[k] = str(d[k])
        out.append(d)
    return out


def _item_ids(conn: sa.Connection, line_ids: list[str], planned_orders: set[str]) -> dict[str, str]:
    """Order-line id -> procurement item id (``"planned"`` for a copy a dry run has not written)."""
    if not line_ids:
        return {}
    found = {
        str(r[0]): str(r[1])
        for r in conn.execute(
            sa.select(_ITEM.c.legacy_id, _ITEM.c.id).where(
                _ITEM.c.legacy_source == LEGACY_SOURCE, _ITEM.c.legacy_id.in_(line_ids)
            )
        ).all()
    }
    if planned_orders:
        owners = conn.execute(
            sa.text("SELECT id, po_id FROM oe_supplier_catalogs_po_line WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": line_ids},
        ).all()
        for line_id, po_id in owners:
            if str(po_id) in planned_orders:
                found.setdefault(str(line_id), "planned")
    return found


def migrate_project(conn: sa.Connection, project_id: str, *, write: bool = True) -> ProjectResult:
    """Copy one project's legacy orders and receipts; ``write=False`` only plans and counts.

    Runs in the caller's transaction: the caller decides what one project's
    unit of work is (the revision wraps each project in a savepoint).
    """
    result = ProjectResult(project_id=project_id)
    pos = _rows(
        conn,
        "SELECT p.*, v.contact_id AS vendor_contact_id FROM oe_supplier_catalogs_po p "
        "LEFT JOIN oe_supplier_catalogs_vendor v ON v.id = p.vendor_id "
        "WHERE p.project_id = :p ORDER BY p.created_at, p.id",
        p=project_id,
    )
    taken = {r[0] for r in conn.execute(sa.select(_PO.c.po_number).where(_PO.c.project_id == project_id)).all() if r[0]}
    po_target: dict[str, str] = {}
    fresh: set[str] = set()
    for po in pos:
        result.orders_total += 1
        existing = conn.execute(
            sa.select(_PO.c.id).where(_PO.c.legacy_source == LEGACY_SOURCE, _PO.c.legacy_id == po["id"])
        ).first()
        if existing is not None:
            result.orders_already += 1
            po_target[po["id"]] = str(existing[0])
            if write and po.get("migrated_to_id") is None:
                conn.execute(
                    sa.text("UPDATE oe_supplier_catalogs_po SET migrated_to_id = :n WHERE id = :i"),
                    {"n": str(existing[0]), "i": po["id"]},
                )
            continue
        lines = _rows(
            conn, "SELECT * FROM oe_supplier_catalogs_po_line WHERE po_id = :i ORDER BY created_at, id", i=po["id"]
        )
        plan = plan_order(po, lines, po.get("vendor_contact_id"))
        if not isinstance(plan, str) and plan["po_number"] in taken:
            plan = f"order number '{plan['po_number']}' is already used by a procurement order in this project"
        if isinstance(plan, str):
            result.unmappable.append({"kind": "po", "legacy_id": po["id"], "reference": po["number"], "reason": plan})
            if write:
                _report(conn, project_id, "po", po["id"], plan)
            continue
        taken.add(plan["po_number"])
        result.orders_copied += 1
        new_id = str(uuid.uuid4())
        po_target[po["id"]] = new_id
        fresh.add(po["id"])
        if write:
            _insert_order(conn, project_id, po["id"], plan, new_id)
            _clear_report(conn, "po", po["id"])

    planned_orders = set() if write else fresh
    grs = _rows(
        conn,
        "SELECT g.* FROM oe_supplier_catalogs_gr g "
        "WHERE g.po_id IN (SELECT id FROM oe_supplier_catalogs_po WHERE project_id = :p) "
        "ORDER BY g.created_at, g.id",
        p=project_id,
    )
    for gr in grs:
        result.receipts_total += 1
        existing = conn.execute(
            sa.select(_GR.c.id).where(_GR.c.legacy_source == LEGACY_SOURCE, _GR.c.legacy_id == gr["id"])
        ).first()
        if existing is not None:
            result.receipts_already += 1
            if write and gr.get("migrated_to_id") is None:
                conn.execute(
                    sa.text("UPDATE oe_supplier_catalogs_gr SET migrated_to_id = :n WHERE id = :i"),
                    {"n": str(existing[0]), "i": gr["id"]},
                )
            continue
        new_po = po_target.get(gr["po_id"])
        if new_po is None:
            reason = "the receipt's order was not copied"
            result.unmappable.append({"kind": "gr", "legacy_id": gr["id"], "reference": gr["number"], "reason": reason})
            if write:
                _report(conn, project_id, "gr", gr["id"], reason)
            continue
        lines = _rows(
            conn,
            "SELECT gl.*, pl.ordered_qty FROM oe_supplier_catalogs_gr_line gl "
            "JOIN oe_supplier_catalogs_po_line pl ON pl.id = gl.po_line_id WHERE gl.gr_id = :i "
            "ORDER BY gl.created_at, gl.id",
            i=gr["id"],
        )
        plan = plan_receipt(gr, lines, _item_ids(conn, [ln["po_line_id"] for ln in lines], planned_orders))
        if isinstance(plan, str):
            result.unmappable.append({"kind": "gr", "legacy_id": gr["id"], "reference": gr["number"], "reason": plan})
            if write:
                _report(conn, project_id, "gr", gr["id"], plan)
            continue
        result.receipts_copied += 1
        if write:
            _insert_receipt(conn, gr["id"], plan, new_po)
            _clear_report(conn, "gr", gr["id"])
    return result


def _insert_order(conn: sa.Connection, project_id: str, legacy_id: str, plan: dict[str, Any], new_id: str) -> None:
    conn.execute(
        sa.insert(_PO).values(
            id=new_id,
            project_id=project_id,
            vendor_contact_id=plan["vendor_contact_id"],
            po_number=plan["po_number"],
            po_type="standard",
            issue_date=plan["issue_date"],
            delivery_date=plan["delivery_date"],
            currency_code=plan["currency_code"],
            amount_subtotal=plan["amount_subtotal"],
            tax_amount=plan["tax_amount"],
            amount_total=plan["amount_total"],
            retention_percent=_ZERO,
            retain_on_receipt=False,
            retainage_released_amount="0",
            status=plan["status"],
            supplier_acknowledged_at=plan["acknowledged_at"],
            notes=plan["notes"],
            metadata=plan["metadata"],
            legacy_source=LEGACY_SOURCE,
            legacy_id=legacy_id,
        )
    )
    for item in plan["items"]:
        conn.execute(
            sa.insert(_ITEM).values(
                id=str(uuid.uuid4()),
                po_id=new_id,
                description=item["description"],
                quantity=item["quantity"],
                unit=item["unit"],
                unit_rate=item["unit_rate"],
                amount=item["amount"],
                sort_order=item["sort_order"],
                requires_inspection=False,
                catalog_item_id=item["catalog_item_id"],
                legacy_source=LEGACY_SOURCE,
                legacy_id=item["legacy_id"],
            )
        )
    conn.execute(
        sa.text("UPDATE oe_supplier_catalogs_po SET migrated_to_id = :n WHERE id = :i"), {"n": new_id, "i": legacy_id}
    )


def _insert_receipt(conn: sa.Connection, legacy_id: str, plan: dict[str, Any], new_po: str) -> None:
    new_id = str(uuid.uuid4())
    conn.execute(
        sa.insert(_GR).values(
            id=new_id,
            po_id=new_po,
            receipt_date=plan["receipt_date"],
            received_by_id=plan["received_by_id"],
            status=plan["status"],
            notes=plan["notes"],
            source="site",
            metadata=plan["metadata"],
            legacy_source=LEGACY_SOURCE,
            legacy_id=legacy_id,
        )
    )
    for item in plan["items"]:
        conn.execute(
            sa.insert(_GR_ITEM).values(
                id=str(uuid.uuid4()),
                receipt_id=new_id,
                po_item_id=item["po_item_id"],
                quantity_ordered=item["quantity_ordered"],
                quantity_received=item["quantity_received"],
                quantity_rejected=item["quantity_rejected"],
                batch_lot=item["batch_lot"],
                serial_numbers=item["serial_numbers"],
            )
        )
    if plan["stock_moved"]:
        # The stock moved when the legacy receipt was posted: claim the event
        # key so the subscriber never books it again, and point the ledger rows
        # at the copy.
        conn.execute(
            sa.text(
                f"INSERT INTO oe_event_effect (id, {_effect_key_column(conn)}, effect) VALUES (:id, :key, :effect)"
            ),
            {"id": str(uuid.uuid4()), "key": f"gr:{new_id}:posted", "effect": "supplier_catalogs.stock_in"},
        )
        conn.execute(
            sa.text(
                "UPDATE oe_supplier_catalogs_stock_movement SET reference_id = :n "
                "WHERE reference_type = 'gr' AND reference_id = :o"
            ),
            {"n": new_id, "o": legacy_id},
        )
    conn.execute(
        sa.text("UPDATE oe_supplier_catalogs_gr SET migrated_to_id = :n WHERE id = :i"), {"n": new_id, "i": legacy_id}
    )


def revert_all(conn: sa.Connection) -> None:
    """Undo the copy: ledger rows back to the legacy receipts, copies deleted, pointers cleared."""
    conn.execute(
        sa.text(
            "UPDATE oe_supplier_catalogs_stock_movement m SET reference_id = g.id "
            "FROM oe_supplier_catalogs_gr g WHERE m.reference_type = 'gr' AND m.reference_id = g.migrated_to_id"
        )
    )
    if sa.inspect(conn).has_table(_EFFECT_TABLE):
        conn.execute(
            sa.text(
                f"DELETE FROM oe_event_effect WHERE {_effect_key_column(conn)} IN "
                "(SELECT 'gr:' || migrated_to_id || '\\:posted' FROM oe_supplier_catalogs_gr "
                "WHERE migrated_to_id IS NOT NULL)"
            )
        )
    conn.execute(sa.text("UPDATE oe_supplier_catalogs_gr SET migrated_to_id = NULL"))
    conn.execute(sa.text("UPDATE oe_supplier_catalogs_po SET migrated_to_id = NULL"))
    conn.execute(sa.delete(_GR).where(_GR.c.legacy_source == LEGACY_SOURCE))
    conn.execute(sa.delete(_ITEM).where(_ITEM.c.legacy_source == LEGACY_SOURCE))
    conn.execute(sa.delete(_PO).where(_PO.c.legacy_source == LEGACY_SOURCE))

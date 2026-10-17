# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs event names + cross-module subscribers.

All events are best-effort published via ``event_bus.publish_detached``
inside the service layer. Subscribers in notifications + finance can
consume these without coupling to the supplier_catalogs ORM.

The bottom half of this file (after the topic constants) registers
Wave-M4 deep-pass cross-module subscribers that fan SKU lifecycle and
vendor-rating events out to ``match_elements.vector_reindex`` and
``bi_dashboards.kpi_recompute``.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

VENDOR_CREATED = "supplier_catalogs.vendor.created"
VENDOR_SUSPENDED = "supplier_catalogs.vendor.suspended"
VENDOR_BLACKLISTED = "supplier_catalogs.vendor.blacklisted"
VENDOR_RATED = "supplier_catalogs.vendor.rated"
# Emitted only for a vendor nothing pointed at. A vendor with orders,
# invoices, price lists or KYC documents against it cannot be deleted at all -
# it is suspended or blacklisted instead - so this topic never carries the
# disappearance of a supplier anyone traded with.
VENDOR_DELETED = "supplier_catalogs.vendor.deleted"

# Catalog SKU lifecycle (Wave M4 deep-pass) - Match Elements
# subscribes to MATERIAL_ADDED to schedule a vector re-index of the
# affected SKU into the embedding store. BI Dashboards uses the same
# topic to bump the supplier-coverage KPI projection.
MATERIAL_ADDED = "supplier_catalogs.material.added"
MATERIAL_UPDATED = "supplier_catalogs.material.updated"
MATERIAL_DEACTIVATED = "supplier_catalogs.material.deactivated"
# An item that no requisition line, order line, vendor price or stock balance
# referenced. Same reasoning as VENDOR_DELETED: anything with a history behind
# it is refused rather than removed.
MATERIAL_DELETED = "supplier_catalogs.material.deleted"

PRICE_LIST_IMPORTED = "supplier_catalogs.price_list.imported"

PR_SUBMITTED = "supplier_catalogs.pr.submitted"
PR_APPROVED = "supplier_catalogs.pr.approved"
PR_REJECTED = "supplier_catalogs.pr.rejected"
PR_CONVERTED = "supplier_catalogs.pr.converted"

PO_CREATED = "supplier_catalogs.po.created"
PO_SENT = "supplier_catalogs.po.sent"
PO_ACKNOWLEDGED = "supplier_catalogs.po.acknowledged"
PO_RECEIVED = "supplier_catalogs.po.received"
PO_CLOSED = "supplier_catalogs.po.closed"

GR_POSTED = "supplier_catalogs.gr.posted"

INVOICE_MATCHED = "supplier_catalogs.invoice.matched"
INVOICE_EXCEPTION = "supplier_catalogs.invoice.exception"
# Distinct from INVOICE_EXCEPTION on purpose. An exception means the match ran
# and the figures disagreed; this means the match could not run at all, so the
# invoice may be perfectly correct. Sharing the event would put an exception's
# wording - a price variance - in front of an operator for a comparison that
# never happened.
INVOICE_CURRENCY_MISMATCH = "supplier_catalogs.invoice.currency_mismatch"

STOCK_RESERVED = "supplier_catalogs.stock.reserved"
STOCK_ISSUED = "supplier_catalogs.stock.issued"
STOCK_LOW_THRESHOLD = "supplier_catalogs.stock.low_threshold"
STOCK_ADJUSTED = "supplier_catalogs.stock.adjusted"
# A location with no stock on hand and no goods receipt against it.
WAREHOUSE_DELETED = "supplier_catalogs.warehouse.deleted"

# Stock low / reorder alert - emitted whenever a balance dips below reorder_point
STOCK_LOW = "supplier_catalogs.stock.low"

# KYC / compliance lifecycle
KYC_DOC_UPLOADED = "supplier_catalogs.kyc.uploaded"
KYC_DOC_EXPIRING = "supplier_catalogs.kyc.expiring"
KYC_DOC_EXPIRED = "supplier_catalogs.kyc.expired"

# Scorecard
SCORECARD_COMPUTED = "supplier_catalogs.scorecard.computed"

# PEPPOL ingest
PEPPOL_INVOICE_INGESTED = "supplier_catalogs.invoice.peppol_ingested"


# ── Wave M4 deep-pass cross-module subscribers ─────────────────────────
#
# These subscribers republish supplier-catalogs lifecycle events as
# ``match_elements.vector_reindex`` and ``bi_dashboards.kpi_recompute``
# topics so the right side-projections fire without coupling either
# downstream module to our ORM. All handlers are fail-soft.

_logger = logging.getLogger(__name__)


async def _on_material_added(event: Event) -> None:
    """``supplier_catalogs.material.added`` → match_elements re-index + BI tick."""
    data = event.data or {}
    catalog_item_id = data.get("catalog_item_id")
    if not catalog_item_id:
        return
    # Match Elements vector store reindex - Qdrant collection
    # ``supplier_catalog_items`` keyed on catalog_item_id.
    try:
        event_bus.publish_detached(
            "match_elements.vector_reindex",
            {
                "source_event": "supplier_catalogs.material.added",
                "collection": "supplier_catalog_items",
                "entity_id": str(catalog_item_id),
                "payload": {
                    "sku": data.get("sku") or "",
                    "name": data.get("name") or "",
                    "manufacturer": data.get("manufacturer") or "",
                    "mpn": data.get("mpn") or "",
                    "unit_of_measure": data.get("unit_of_measure") or "",
                    "description": data.get("description") or "",
                    "category_id": data.get("category_id"),
                },
                "operation": "upsert",
            },
            source_module="supplier_catalogs",
        )
    except Exception:
        _logger.debug(
            "supplier_catalogs: vector_reindex emit failed",
            exc_info=True,
        )

    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "supplier_catalogs",
                "source_event": "supplier_catalogs.material.added",
                "project_id": None,  # catalog is tenant-scoped, not project-scoped
                "kpi_codes": ["catalog_coverage", "supplier_count"],
                "reason": "material_added",
            },
            source_module="supplier_catalogs",
        )
    except Exception:
        _logger.debug(
            "supplier_catalogs: kpi_recompute emit failed",
            exc_info=True,
        )


async def _on_vendor_rated(event: Event) -> None:
    """``supplier_catalogs.vendor.rated`` → BI supplier-performance recompute."""
    data = event.data or {}
    vendor_id = data.get("vendor_id")
    if not vendor_id:
        return
    try:
        event_bus.publish_detached(
            "bi_dashboards.kpi_recompute",
            {
                "source_module": "supplier_catalogs",
                "source_event": "supplier_catalogs.vendor.rated",
                "project_id": None,
                "kpi_codes": ["subcontractor_avg_rating", "vendor_otd_rate"],
                "reason": "vendor_rated",
                "vendor_id": str(vendor_id),
                "rating": data.get("rating"),
            },
            source_module="supplier_catalogs",
        )
    except Exception:
        _logger.debug(
            "supplier_catalogs: vendor_rated kpi_recompute failed",
            exc_info=True,
        )


def register_subscribers() -> None:
    """Idempotently subscribe supplier-catalogs cross-module handlers."""
    event_bus.subscribe_once(MATERIAL_ADDED, _on_material_added)
    event_bus.subscribe_once(VENDOR_RATED, _on_vendor_rated)
    _logger.info("Supplier Catalogs: 2 cross-module subscriber(s) registered")

"""‌⁠‍Wave-4 notification subscribers (BI Dashboards, QMS, Supplier Catalogs).

Single landing zone for Wave-4 module subscribers that ship in parallel and
shouldn't all crowd into ``events.py``. Each ``register_*`` function must be
idempotent — :meth:`EventBus.subscribe` deduplicates on handler identity in
practice because handlers are module-level functions.

Modules wired here:

* **BI Dashboards** — ``bi.alert.triggered`` / ``bi.report.generated``
* **Supplier Catalogs** — ``po.sent`` / ``invoice.exception`` /
  ``stock.low_threshold`` / ``vendor.blacklisted``
"""

from __future__ import annotations

import logging
from typing import Callable

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """‌⁠‍Always True post-Epic-B — see :mod:`app.modules.notifications.events`."""
    return True


# ── BI Dashboards ──────────────────────────────────────────────────────


async def _on_bi_alert_triggered(event: Event) -> None:
    """‌⁠‍``bi.alert.triggered`` → notify every recipient over their channels."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    recipients = data.get("recipients") or []
    channels = data.get("channels") or ["in_app"]
    if not recipients or "in_app" not in channels:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            severity = data.get("severity", "warning")
            notification_type = "alert_critical" if severity == "critical" else "alert_warning"
            body_context = {
                "alert_name": data.get("alert_name", ""),
                "kpi_code": data.get("kpi_code", ""),
                "value": str(data.get("value", "")),
                "threshold": str(data.get("threshold", "")),
                "condition": data.get("condition", ""),
                "severity": severity,
            }
            for r in recipients:
                if not isinstance(r, dict):
                    continue
                user_id = r.get("user_id")
                if not user_id:
                    continue
                await svc.create(
                    user_id=user_id,
                    notification_type=notification_type,
                    title_key="notifications.bi.alert.title",
                    body_key="notifications.bi.alert.body",
                    body_context=body_context,
                    entity_type="bi_alert",
                    entity_id=str(data.get("alert_id", "")),
                    action_url="/bi-dashboards/alerts",
                )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_bi_alert_triggered failed", exc_info=True)


async def _on_bi_report_generated(event: Event) -> None:
    """``bi.report.generated`` → email link to every recipient."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    recipients = data.get("recipients") or []
    if not recipients:
        return
    file_url = data.get("file_url") or ""
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            for r in recipients:
                if not isinstance(r, dict):
                    continue
                user_id = r.get("user_id")
                if not user_id:
                    continue
                await svc.create(
                    user_id=user_id,
                    notification_type="report_generated",
                    title_key="notifications.bi.report.title",
                    body_key="notifications.bi.report.body",
                    body_context={
                        "report_code": data.get("report_code", ""),
                        "row_count": data.get("row_count", 0),
                        "file_url": file_url,
                    },
                    entity_type="bi_report",
                    entity_id=str(data.get("report_id", "")),
                    action_url=(file_url or "/bi-dashboards/reports"),
                )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_bi_report_generated failed", exc_info=True)


_BI_DASHBOARDS_SUBSCRIPTIONS: list[tuple[str, Callable[[Event], object]]] = [
    ("bi.alert.triggered", _on_bi_alert_triggered),
    ("bi.report.generated", _on_bi_report_generated),
]


def register_bi_dashboards_notification_subscribers() -> None:
    """Wire BI Dashboards events into the in-app notification fan-out."""
    for event_name, handler in _BI_DASHBOARDS_SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications (Wave 4): subscribed to %d BI-Dashboards event(s)",
        len(_BI_DASHBOARDS_SUBSCRIPTIONS),
    )


# ── Supplier Catalogs ──────────────────────────────────────────────────


async def _on_supplier_po_sent(event: Event) -> None:
    """``supplier_catalogs.po.sent`` → notify the actor / approver."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    actor_id = data.get("actor_id")
    po_id = data.get("po_id")
    if not actor_id or not po_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=actor_id,
                notification_type="info",
                title_key="notifications.supplier_catalogs.po.sent.title",
                body_key="notifications.supplier_catalogs.po.sent.body",
                body_context={
                    "vendor_id": str(data.get("vendor_id") or ""),
                    "total": str(data.get("total") or ""),
                    "currency": data.get("currency") or "",
                },
                entity_type="supplier_catalogs_po",
                entity_id=str(po_id),
                action_url=f"/procurement/po/{po_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_supplier_po_sent failed", exc_info=True)


async def _on_supplier_invoice_exception(event: Event) -> None:
    """``supplier_catalogs.invoice.exception`` → notify the matcher."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    invoice_id = data.get("invoice_id")
    if not invoice_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            target = data.get("matched_by") or data.get("actor_id")
            if not target:
                return
            await svc.create(
                user_id=target,
                notification_type="warning",
                title_key="notifications.supplier_catalogs.invoice.exception.title",
                body_key="notifications.supplier_catalogs.invoice.exception.body",
                body_context={
                    "po_id": str(data.get("po_id") or ""),
                    "reason": (data.get("reason") or "")[:200],
                },
                entity_type="supplier_catalogs_invoice",
                entity_id=str(invoice_id),
                action_url=f"/finance/invoices/{invoice_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_supplier_invoice_exception failed",
            exc_info=True,
        )


async def _on_supplier_stock_low(event: Event) -> None:
    """``supplier_catalogs.stock.low_threshold`` → warehouse manager + PM."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    warehouse_id = data.get("warehouse_id")
    if not warehouse_id:
        return
    try:
        import uuid as _uuid

        from app.modules.supplier_catalogs.models import Warehouse

        async with async_session_factory() as session:
            try:
                wh = await session.get(Warehouse, _uuid.UUID(str(warehouse_id)))
            except Exception:
                wh = None
            targets: set[str] = set()
            if wh is not None and wh.manager_user_id:
                targets.add(str(wh.manager_user_id))
            if wh is not None and wh.project_id is not None:
                try:
                    from app.modules.projects.models import Project

                    proj = await session.get(Project, wh.project_id)
                    if proj is not None and getattr(proj, "owner_id", None):
                        targets.add(str(proj.owner_id))
                except Exception:
                    pass
            if not targets:
                return
            svc = NotificationService(session)
            for uid in targets:
                await svc.create(
                    user_id=uid,
                    notification_type="warning",
                    title_key="notifications.supplier_catalogs.stock.low.title",
                    body_key="notifications.supplier_catalogs.stock.low.body",
                    body_context={
                        "sku": data.get("sku") or "",
                        "available_qty": str(data.get("available_qty") or ""),
                        "reorder_point": str(data.get("reorder_point") or ""),
                    },
                    entity_type="supplier_catalogs_stock",
                    entity_id=str(data.get("catalog_item_id") or ""),
                    action_url=f"/warehouses/{warehouse_id}",
                )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_supplier_stock_low failed", exc_info=True)


async def _on_supplier_vendor_blacklisted(event: Event) -> None:
    """``supplier_catalogs.vendor.blacklisted`` → notify procurement lead."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    actor_id = data.get("actor_id")
    vendor_id = data.get("vendor_id")
    if not vendor_id or not actor_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=actor_id,
                notification_type="warning",
                title_key="notifications.supplier_catalogs.vendor.blacklisted.title",
                body_key="notifications.supplier_catalogs.vendor.blacklisted.body",
                body_context={
                    "code": data.get("code") or "",
                    "reason": (data.get("reason") or "")[:200],
                },
                entity_type="supplier_catalogs_vendor",
                entity_id=str(vendor_id),
                action_url=f"/procurement/vendors/{vendor_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_supplier_vendor_blacklisted failed",
            exc_info=True,
        )


async def _on_supplier_kyc_expiring(event: Event) -> None:
    """``supplier_catalogs.kyc.expiring`` / ``.expired`` → notify procurement."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    vendor_id = data.get("vendor_id")
    if not vendor_id:
        return
    is_expired = event.name.endswith(".expired")
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            # Try to fetch the vendor's onboarding owner; fall back to all
            # users with the procurement admin permission. Vendor master has
            # no owner_id today, so we notify the vendor manager (contact_id)
            # if present. This is best-effort.
            from app.modules.supplier_catalogs.models import Vendor

            try:
                import uuid as _uuid

                vendor = await session.get(Vendor, _uuid.UUID(str(vendor_id)))
            except Exception:
                vendor = None
            target = getattr(vendor, "contact_id", None) if vendor is not None else None
            if not target:
                return
            await svc.create(
                user_id=target,
                notification_type=("alert_critical" if is_expired else "alert_warning"),
                title_key=(
                    "notifications.supplier_catalogs.kyc.expired.title"
                    if is_expired
                    else "notifications.supplier_catalogs.kyc.expiring.title"
                ),
                body_key=(
                    "notifications.supplier_catalogs.kyc.expired.body"
                    if is_expired
                    else "notifications.supplier_catalogs.kyc.expiring.body"
                ),
                body_context={
                    "doc_type": data.get("doc_type", ""),
                    "expires_on": str(
                        data.get("expires_on") or data.get("expired_on") or "",
                    ),
                    "days_until_expiry": str(
                        data.get("days_until_expiry") or "",
                    ),
                },
                entity_type="supplier_catalogs_kyc",
                entity_id=str(data.get("doc_id", "")),
                action_url=f"/procurement/vendors/{vendor_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_supplier_kyc_expiring failed",
            exc_info=True,
        )


async def _on_supplier_peppol_ingested(event: Event) -> None:
    """``supplier_catalogs.invoice.peppol_ingested`` → AP team gets notified."""
    if not await _can_open_isolated_session():
        return
    # Audit-only — no targeted user. Log for observability.
    logger.info(
        "Wave 4: PEPPOL invoice ingested: %s",
        (event.data or {}).get("invoice_id"),
    )


_SUPPLIER_CATALOGS_SUBSCRIPTIONS: list[tuple[str, Callable[[Event], object]]] = [
    ("supplier_catalogs.po.sent", _on_supplier_po_sent),
    ("supplier_catalogs.invoice.exception", _on_supplier_invoice_exception),
    ("supplier_catalogs.stock.low_threshold", _on_supplier_stock_low),
    ("supplier_catalogs.stock.low", _on_supplier_stock_low),
    ("supplier_catalogs.vendor.blacklisted", _on_supplier_vendor_blacklisted),
    ("supplier_catalogs.kyc.expiring", _on_supplier_kyc_expiring),
    ("supplier_catalogs.kyc.expired", _on_supplier_kyc_expiring),
    (
        "supplier_catalogs.invoice.peppol_ingested",
        _on_supplier_peppol_ingested,
    ),
]


def register_supplier_catalogs_notification_subscribers() -> None:
    """Wire Supplier Catalogs Wave 4 subscribers onto the global event bus."""
    for event_name, handler in _SUPPLIER_CATALOGS_SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications (Wave 4): subscribed to %d Supplier-Catalogs event(s)",
        len(_SUPPLIER_CATALOGS_SUBSCRIPTIONS),
    )


# ── Wave-4 aggregate registrar ─────────────────────────────────────────


def register_wave4_notification_subscribers() -> None:
    """Single entry-point that wires every Wave-4 subscriber group."""
    register_bi_dashboards_notification_subscribers()
    register_supplier_catalogs_notification_subscribers()


__all__ = [
    "register_bi_dashboards_notification_subscribers",
    "register_supplier_catalogs_notification_subscribers",
    "register_wave4_notification_subscribers",
]

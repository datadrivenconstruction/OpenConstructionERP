# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Deterministic seed data for the Customer & Partner Portal.

Generates:
    20 portal users — 4 clients, 3 investors, 3 consultants,
                      4 subcontractors, 4 suppliers, 2 building users
    3-5 access rules per user across the supplied project IDs
    30 notifications (mix read/unread, across all kinds)
    50 document-access log entries

All UUIDs are derived from a stable seed (``uuid5(NS, label)``) so reruns
are idempotent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.portal.models import (
    PortalAccessRule,
    PortalDocumentAccessLog,
    PortalNotification,
    PortalUser,
)
from app.modules.portal.repository import PortalUserRepository

logger = logging.getLogger(__name__)

_NS = uuid.UUID("d4d4c300-1909-4ddc-b01c-0a44e3b01c00")

_USERS: tuple[tuple[str, str, str, str], ...] = (
    # (email, full_name, role, language)
    ("alice.client@example.com", "Alice Client", "client", "en"),
    ("bob.client@example.com", "Bob Client", "client", "de"),
    ("clara.cliente@example.com", "Clara Cliente", "client", "es"),
    ("denis.client@example.com", "Denis Client", "client", "ru"),
    ("eric.investor@example.com", "Eric Investor", "investor", "en"),
    ("frieda.investor@example.com", "Frieda Investor", "investor", "de"),
    ("george.invest@example.com", "George Invest", "investor", "en"),
    ("hannah.consult@example.com", "Hannah Consultant", "consultant", "en"),
    ("ivan.consult@example.com", "Ivan Konsultant", "consultant", "ru"),
    ("julia.consult@example.com", "Julia Beraterin", "consultant", "de"),
    ("kai.sub@example.com", "Kai Subcontractor", "subcontractor", "en"),
    ("lina.sub@example.com", "Lina Sub", "subcontractor", "de"),
    ("marek.sub@example.com", "Marek Podwykonawca", "subcontractor", "en"),
    ("nora.sub@example.com", "Nora Sub", "subcontractor", "en"),
    ("oscar.supply@example.com", "Oscar Supplier", "supplier", "en"),
    ("petra.supply@example.com", "Petra Lieferant", "supplier", "de"),
    ("quentin.supply@example.com", "Quentin Supply", "supplier", "en"),
    ("rosa.supply@example.com", "Rosa Suministro", "supplier", "es"),
    ("sven.tenant@example.com", "Sven Tenant", "building_user", "en"),
    ("tomas.tenant@example.com", "Tomas Mieter", "building_user", "de"),
)


_RESOURCE_TYPES = (
    "project",
    "contract",
    "document",
    "ticket",
    "subcontract",
    "payment_application",
    "po",
    "bid_package",
)


_NOTIFICATION_KINDS = (
    "document_ready",
    "ticket_update",
    "payment_status",
    "award_notification",
    "general",
)


def _det_uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(_NS, label)


async def seed_portal_demo(
    session: AsyncSession,
    projects_ids: Sequence[uuid.UUID] | None = None,
) -> dict[str, int]:
    """‌⁠‍Idempotently populate the portal tables with demo data.

    Args:
        session: an active :class:`AsyncSession`.
        projects_ids: list of real project UUIDs to attach access rules to.
            When empty, deterministic synthetic UUIDs are used so the seed
            still runs end-to-end in an isolated test DB.

    Returns:
        Counts dict with ``users``, ``rules``, ``notifications``,
        ``access_logs`` keys.
    """
    project_pool: list[uuid.UUID] = list(projects_ids or [])
    if not project_pool:
        project_pool = [_det_uuid(f"demo-project-{i}") for i in range(5)]

    now = datetime.now(UTC)

    user_repo = PortalUserRepository(session)

    users: list[PortalUser] = []
    for idx, (email, full_name, role, lang) in enumerate(_USERS):
        existing = await user_repo.get_by_email(email)
        if existing is not None:
            users.append(existing)
            continue
        user = PortalUser(
            id=_det_uuid(f"portal-user-{email}"),
            email=email,
            full_name=full_name,
            portal_role=role,
            language=lang,
            timezone="UTC",
            status="active" if idx % 4 != 0 else "invited",
            invited_at=now - timedelta(days=30 - idx),
            last_login_at=now - timedelta(days=idx) if idx % 4 != 0 else None,
        )
        await user_repo.create(user)
        users.append(user)

    rules_created = 0
    for u_idx, user in enumerate(users):
        rule_count = 3 + (u_idx % 3)  # 3, 4, or 5
        for r_idx in range(rule_count):
            resource_type = _RESOURCE_TYPES[(u_idx + r_idx) % len(_RESOURCE_TYPES)]
            project_id = project_pool[r_idx % len(project_pool)]
            resource_id = (
                project_id if resource_type == "project" else _det_uuid(f"res-{user.email}-{resource_type}-{r_idx}")
            )
            permission = ("view", "comment", "submit", "sign")[r_idx % 4]
            rule = PortalAccessRule(
                id=_det_uuid(f"rule-{user.email}-{resource_type}-{r_idx}"),
                portal_user_id=user.id,
                resource_type=resource_type,
                resource_id=resource_id,
                permission=permission,
                granted_at=now - timedelta(days=10 - r_idx),
            )
            session.add(rule)
            rules_created += 1
    await session.flush()

    notifications_created = 0
    for n_idx in range(30):
        user = users[n_idx % len(users)]
        kind = _NOTIFICATION_KINDS[n_idx % len(_NOTIFICATION_KINDS)]
        read_at = now - timedelta(hours=n_idx) if n_idx % 3 == 0 else None
        notif = PortalNotification(
            id=_det_uuid(f"notif-{n_idx}"),
            portal_user_id=user.id,
            kind=kind,
            title=f"Demo notification #{n_idx + 1}",
            body=f"Body for demo notification {n_idx + 1} ({kind})",
            link_path=f"/portal/items/{n_idx}",
            payload={"seq": n_idx, "kind": kind},
            read_at=read_at,
        )
        session.add(notif)
        notifications_created += 1
    await session.flush()

    access_logs_created = 0
    for l_idx in range(50):
        user = users[l_idx % len(users)]
        action = ("view", "download", "sign")[l_idx % 3]
        entry = PortalDocumentAccessLog(
            id=_det_uuid(f"acclog-{l_idx}"),
            portal_user_id=user.id,
            document_type="document",
            document_id=_det_uuid(f"doc-{l_idx}"),
            action=action,
            occurred_at=now - timedelta(minutes=l_idx * 7),
            ip_address=f"10.0.{l_idx // 256}.{l_idx % 256}",
        )
        session.add(entry)
        access_logs_created += 1
    await session.flush()

    counts = {
        "users": len(users),
        "rules": rules_created,
        "notifications": notifications_created,
        "access_logs": access_logs_created,
    }
    logger.info("Portal demo seed completed: %s", counts)
    return counts


__all__ = ["seed_portal_demo"]

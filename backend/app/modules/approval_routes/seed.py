# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tenant-wide approval-route presets (ISO 19650 review flows).

Most teams starting with routed sign-off do not want to build an approval
route from a blank form. This seeds a small library of ready-made, tenant-wide
presets that model the common review flows for a document or package issued
through the common data environment:

    - Issue for review    - one task-team reviewer checks the content.
    - Comment and return   - one approver accepts or returns it with comments.
    - Review and publish   - a reviewer checks, then an approver authorises it.

The presets are ordinary tenant-wide routes (``project_id IS NULL``) so any
project can start a workflow on them straight away, and each carries a stable
``system_key`` so this seed is idempotent (re-running never duplicates one) and
the API can flag a route as a read-only platform preset. Loaded best-effort on
module startup, mirroring the other auto-installed modules.

Target kind is ``submittal`` - a submittal is exactly a document or package
issued for review and approval, which is the review gate these flows describe.
The presets reference plain application roles (editor, manager) so they work
against the built-in role hierarchy without any extra configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes.models import Route, Step

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PresetStep:
    """A pure, DB-free description of one preset step."""

    ordinal: int
    approver_role: str
    mode: str
    required_approver_count: int | None
    sla_hours: int | None


@dataclass(frozen=True)
class _Preset:
    """A pure, DB-free description of one preset route."""

    system_key: str
    name: str
    target_kind: str
    steps: tuple[_PresetStep, ...]


# The preset library. Pure data so it can be validated without a database
# (see tests/unit/test_approval_route_presets.py, which also dry-runs each one
# through the simulator to prove it terminates at "approved").
PRESETS: tuple[_Preset, ...] = (
    _Preset(
        system_key="cde_issue_for_review",
        name="Issue for review",
        target_kind="submittal",
        steps=(
            _PresetStep(
                ordinal=1,
                approver_role="editor",
                mode="all",
                required_approver_count=1,
                sla_hours=48,
            ),
        ),
    ),
    _Preset(
        system_key="cde_comment_and_return",
        name="Comment and return",
        target_kind="submittal",
        steps=(
            _PresetStep(
                ordinal=1,
                approver_role="manager",
                mode="any",
                required_approver_count=None,
                sla_hours=72,
            ),
        ),
    ),
    _Preset(
        system_key="cde_review_and_publish",
        name="Review and publish",
        target_kind="submittal",
        steps=(
            _PresetStep(
                ordinal=1,
                approver_role="editor",
                mode="all",
                required_approver_count=1,
                sla_hours=48,
            ),
            _PresetStep(
                ordinal=2,
                approver_role="manager",
                mode="all",
                required_approver_count=1,
                sla_hours=72,
            ),
        ),
    ),
)


async def seed_approval_route_presets(session: AsyncSession) -> dict[str, int]:
    """Create any missing tenant-wide approval-route presets.

    Idempotent: presets already present (matched by ``system_key``) are left
    untouched, so this is safe to call on every startup. Returns a count of how
    many preset routes were inserted this call.

    Args:
        session: Active async SQLAlchemy session. The caller owns the commit.

    Returns:
        ``{"routes_created": n}`` where ``n`` is the number of presets inserted.
    """
    keys = [p.system_key for p in PRESETS]
    existing = set((await session.execute(select(Route.system_key).where(Route.system_key.in_(keys)))).scalars().all())

    created = 0
    for preset in PRESETS:
        if preset.system_key in existing:
            continue
        route = Route(
            project_id=None,
            name=preset.name,
            target_kind=preset.target_kind,
            is_active=True,
            created_by=None,
            system_key=preset.system_key,
        )
        session.add(route)
        await session.flush()  # assign route.id before adding steps
        for step in preset.steps:
            session.add(
                Step(
                    route_id=route.id,
                    ordinal=step.ordinal,
                    approver_role=step.approver_role,
                    approver_user_id=None,
                    mode=step.mode,
                    required_approver_count=step.required_approver_count,
                    sla_hours=step.sla_hours,
                )
            )
        created += 1

    if created:
        await session.flush()
        logger.info("Approval-route presets seeded: %d new", created)
    return {"routes_created": created}

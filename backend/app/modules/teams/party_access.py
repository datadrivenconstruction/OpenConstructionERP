# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Party visibility for the shared registers.

A project member bound to a party (a company on the project) is *external*:
in the six shared registers listed in :data:`PARTY_SCOPED_REGISTERS` they see
only the records their party originated or that were shared with it. Everyone
else is *internal* and sees everything, exactly as before parties existed:

* system admins and the project owner,
* members bound to no party,
* members of the host party, the party the project owner is bound to,
* system calls (``user_id is None``).

The helpers follow the contract of :mod:`app.modules.teams.access`:

1. they run AFTER ``verify_project_access`` and can only narrow what it
   allowed, never widen it,
2. a hidden record answers 404, not 403, so its id cannot be probed,
3. lookups fail closed: if the scope cannot be resolved, the caller is treated
   as external with no records.

Three shapes are offered so every read path can use the one that fits:

* :func:`party_read_clause` - a SQL clause for list, export and search
  queries. ``None`` means "do not filter".
* :func:`verify_party_record_access` - the by-id guard (404, or 403 on a write
  through a view-only share).
* :func:`party_hidden_ids` - the Python form for results that come back from
  somewhere other than SQL (the vector index).
"""

from __future__ import annotations

import importlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ACCESS_ORIGINATOR = "originator"
ACCESS_SHARED = "shared"
PERMISSION_VIEW = "view"
PERMISSION_CONTRIBUTE = "contribute"
PARTY_PERMISSIONS: frozenset[str] = frozenset({PERMISSION_VIEW, PERMISSION_CONTRIBUTE})

PARTY_ROLES: tuple[str, ...] = ("owner", "contractor", "subcontractor", "consultant", "supplier")


@dataclass(frozen=True)
class PartyRegister:
    """One shared register whose records carry party visibility."""

    key: str
    label: str
    module: str
    model_path: str

    def model(self) -> Any:
        """The SQLAlchemy model of the register's main record."""
        module_name, _, attr = self.model_path.rpartition(".")
        return getattr(importlib.import_module(module_name), attr)


PARTY_SCOPED_REGISTERS: tuple[PartyRegister, ...] = (
    PartyRegister("rfi", "Request for information", "oe_rfi", "app.modules.rfi.models.RFI"),
    PartyRegister(
        "interface",
        "Interface",
        "oe_interface_management",
        "app.modules.interface_management.models.InterfaceRecord",
    ),
    PartyRegister(
        "correspondence",
        "Correspondence item",
        "oe_correspondence",
        "app.modules.correspondence.models.Correspondence",
    ),
    PartyRegister("transmittal", "Transmittal", "oe_transmittals", "app.modules.transmittals.models.Transmittal"),
    PartyRegister("submittal", "Submittal", "oe_submittals", "app.modules.submittals.models.Submittal"),
    PartyRegister(
        "file_transmittal",
        "File transmittal",
        "oe_file_transmittals",
        "app.modules.file_transmittals.models.FileTransmittal",
    ),
)

_REGISTERS_BY_KEY: dict[str, PartyRegister] = {r.key: r for r in PARTY_SCOPED_REGISTERS}
PARTY_SCOPED_KEYS: frozenset[str] = frozenset(_REGISTERS_BY_KEY)


def get_party_register(key: str) -> PartyRegister | None:
    """The register entry for ``key``, or ``None`` for a kind parties do not scope."""
    return _REGISTERS_BY_KEY.get(key)


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


@dataclass(frozen=True)
class PartyScope:
    """How party visibility applies to one caller on one project.

    ``restricted`` False means internal: no filtering. When True, ``party_id``
    is the caller's party, or ``None`` when the scope could not be resolved
    (fail closed: nothing is visible).
    """

    restricted: bool
    party_id: uuid.UUID | None = None
    is_host: bool = False

    @property
    def internal(self) -> bool:
        return not self.restricted


INTERNAL_SCOPE = PartyScope(restricted=False)
_DENY_ALL_SCOPE = PartyScope(restricted=True, party_id=None)


async def _is_system_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    from app.modules.users.models import User

    role = (await session.execute(select(User.role).where(User.id == user_id))).scalar_one_or_none()
    return role == "admin"


async def resolve_party_scope(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | str | None,
) -> PartyScope:
    """Resolve whether ``user_id`` is external on ``project_id``, and as which party.

    Fails closed: any lookup error returns a restricted scope with no party,
    under which nothing in a shared register is visible.
    """
    if user_id is None:
        return INTERNAL_SCOPE
    uid = _as_uuid(user_id)
    if uid is None:
        return _DENY_ALL_SCOPE

    from app.modules.projects.models import Project
    from app.modules.teams.models import ProjectPartyMember

    try:
        binding = (
            await session.execute(
                select(ProjectPartyMember.party_id).where(
                    ProjectPartyMember.project_id == project_id,
                    ProjectPartyMember.user_id == uid,
                )
            )
        ).scalar_one_or_none()
        if binding is None:
            return INTERNAL_SCOPE
        owner_id = (
            await session.execute(select(Project.owner_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        if owner_id is not None and str(owner_id) == str(uid):
            return INTERNAL_SCOPE
        if await _is_system_admin(session, uid):
            return INTERNAL_SCOPE
        if owner_id is not None:
            host = (
                await session.execute(
                    select(ProjectPartyMember.id).where(
                        ProjectPartyMember.project_id == project_id,
                        ProjectPartyMember.party_id == binding,
                        ProjectPartyMember.user_id == owner_id,
                    )
                )
            ).scalar_one_or_none()
            if host is not None:
                return PartyScope(restricted=False, party_id=binding, is_host=True)
        return PartyScope(restricted=True, party_id=binding)
    except Exception:  # noqa: BLE001 - fail closed, never fail open
        logger.exception("party scope lookup failed for project %s; denying shared records", project_id)
        return _DENY_ALL_SCOPE


async def _has_any_binding(session: AsyncSession, uid: uuid.UUID) -> bool:
    from app.modules.teams.models import ProjectPartyMember

    row = (
        await session.execute(select(ProjectPartyMember.id).where(ProjectPartyMember.user_id == uid).limit(1))
    ).scalar_one_or_none()
    return row is not None


def _restricted_bindings_subquery(uid: uuid.UUID):
    """Bindings of ``uid`` that make them external: not owner, not host party."""
    from app.modules.projects.models import Project
    from app.modules.teams.models import ProjectPartyMember

    owner_binding = ProjectPartyMember.__table__.alias("owner_binding")
    return (
        select(ProjectPartyMember.project_id, ProjectPartyMember.party_id)
        .join(Project, Project.id == ProjectPartyMember.project_id)
        .where(
            ProjectPartyMember.user_id == uid,
            or_(Project.owner_id.is_(None), Project.owner_id != uid),
            ~exists(
                select(owner_binding.c.id).where(
                    owner_binding.c.party_id == ProjectPartyMember.party_id,
                    owner_binding.c.user_id == Project.owner_id,
                )
            ),
        )
        .subquery()
    )


async def party_read_clause(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | str | None,
    entity_type: str,
    id_column: Any,
    project_id_column: Any,
) -> Any | None:
    """SQL clause that keeps only rows of ``entity_type`` the caller may see.

    Works for single-project and cross-project queries alike: a row passes when
    the caller is not external on the row's project, or when the caller's party
    holds a row for it. Returns ``None`` when no filtering applies (system call,
    system admin, or a user bound to no party anywhere), so the common case adds
    nothing to the query.

    Use it with ``stmt.where(clause)``: it can only remove rows.
    """
    if entity_type not in PARTY_SCOPED_KEYS:
        raise ValueError(f"{entity_type!r} is not a party-scoped register")
    if user_id is None:
        return None
    uid = _as_uuid(user_id)
    if uid is None:
        # An identity we cannot resolve is external with no party.
        return id_column.is_(None)

    from app.modules.teams.models import PartyRecordAccess

    try:
        if not await _has_any_binding(session, uid):
            return None
        if await _is_system_admin(session, uid):
            return None
    except Exception:  # noqa: BLE001 - fail closed
        logger.exception("party clause lookup failed for user %s; hiding shared records", uid)
        return id_column.is_(None)

    restricted = _restricted_bindings_subquery(uid)
    restricted_projects = select(restricted.c.project_id)
    held = select(PartyRecordAccess.entity_id).where(
        PartyRecordAccess.entity_type == entity_type,
        PartyRecordAccess.party_id.in_(select(restricted.c.party_id)),
    )
    return or_(~project_id_column.in_(restricted_projects), id_column.in_(held))


async def _held_rows(
    session: AsyncSession,
    *,
    entity_type: str,
    party_id: uuid.UUID,
    entity_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """``{entity_id: permission}`` for the records ``party_id`` holds."""
    from app.modules.teams.models import PartyRecordAccess

    if not entity_ids:
        return {}
    rows = (
        await session.execute(
            select(PartyRecordAccess.entity_id, PartyRecordAccess.access, PartyRecordAccess.permission).where(
                PartyRecordAccess.entity_type == entity_type,
                PartyRecordAccess.party_id == party_id,
                PartyRecordAccess.entity_id.in_(entity_ids),
            )
        )
    ).all()
    out: dict[uuid.UUID, str] = {}
    for entity_id, access, permission in rows:
        out[entity_id] = PERMISSION_CONTRIBUTE if access == ACCESS_ORIGINATOR else permission
    return out


async def party_hidden_ids(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    entity_ids: list[uuid.UUID | str],
    user_id: uuid.UUID | str | None,
) -> set[str]:
    """The subset of ``entity_ids`` (as strings) the caller must not be shown.

    For results that do not come from a SQL query on the register (vector
    search hits). Fails closed: on error every candidate is hidden.
    """
    if not entity_ids:
        return set()
    as_str = [str(e) for e in entity_ids]
    try:
        scope = await resolve_party_scope(session, project_id, user_id)
        if scope.internal:
            return set()
        if scope.party_id is None:
            return set(as_str)
        parsed = [u for u in (_as_uuid(e) for e in as_str) if u is not None]
        held = await _held_rows(session, entity_type=entity_type, party_id=scope.party_id, entity_ids=parsed)
        held_str = {str(k) for k in held}
        return {e for e in as_str if str(_as_uuid(e) or e) not in held_str}
    except Exception:  # noqa: BLE001 - fail closed
        logger.exception("party_hidden_ids failed for %s in project %s", entity_type, project_id)
        return set(as_str)


async def verify_party_record_access(
    session: AsyncSession,
    *,
    entity_type: str,
    project_id: uuid.UUID,
    entity_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None,
    write: bool = False,
) -> None:
    """Raise 404 when the caller's party may not see this record.

    Call AFTER the route's ``verify_project_access``. With ``write=True`` a
    record the party holds only through a view share answers 403: the caller
    can already see it, so the stronger status discloses nothing.
    """
    if entity_type not in PARTY_SCOPED_KEYS:
        raise ValueError(f"{entity_type!r} is not a party-scoped register")
    scope = await resolve_party_scope(session, project_id, user_id)
    if scope.internal:
        return
    eid = _as_uuid(entity_id)
    if scope.party_id is None or eid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        held = await _held_rows(session, entity_type=entity_type, party_id=scope.party_id, entity_ids=[eid])
    except Exception:  # noqa: BLE001 - fail closed
        logger.exception("party record lookup failed for %s/%s", entity_type, eid)
        held = {}
    permission = held.get(eid)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if write and permission != PERMISSION_CONTRIBUTE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This record was shared with your company for viewing only",
        )


async def verify_record_access(
    session: AsyncSession,
    *,
    entity_type: str,
    project_id: uuid.UUID,
    entity_id: uuid.UUID | str,
    user_id: uuid.UUID | str | None,
    write: bool = False,
) -> None:
    """Project access plus party visibility for one record, in that order.

    The drop-in replacement for ``verify_project_access(record.project_id, ...)``
    on a by-id route of a shared register.
    """
    from app.dependencies import verify_project_access

    await verify_project_access(project_id, str(user_id or ""), session)
    await verify_party_record_access(
        session,
        entity_type=entity_type,
        project_id=project_id,
        entity_id=entity_id,
        user_id=user_id,
        write=write,
    )


async def stamp_originator(
    session: AsyncSession,
    *,
    entity_type: str,
    project_id: uuid.UUID,
    entity_id: uuid.UUID,
    user_id: uuid.UUID | str | None,
) -> uuid.UUID | None:
    """Record the creator's party as originator of a new record.

    Called from each register's create path in the same transaction as the
    insert. Stamps only when the creator is bound to a party (internal creators
    of an unbound project write nothing, so projects without parties gain no
    rows). Errors propagate on purpose: an external creator whose stamp failed
    would otherwise create a record their own company cannot open.

    Returns the originator party id, or ``None`` when nothing was written.
    """
    from app.modules.teams.models import PartyRecordAccess, ProjectPartyMember

    if entity_type not in PARTY_SCOPED_KEYS:
        raise ValueError(f"{entity_type!r} is not a party-scoped register")
    uid = _as_uuid(user_id)
    if uid is None:
        return None
    party_id = (
        await session.execute(
            select(ProjectPartyMember.party_id).where(
                ProjectPartyMember.project_id == project_id,
                ProjectPartyMember.user_id == uid,
            )
        )
    ).scalar_one_or_none()
    if party_id is None:
        return None
    existing = (
        await session.execute(
            select(PartyRecordAccess).where(
                and_(
                    PartyRecordAccess.entity_type == entity_type,
                    PartyRecordAccess.entity_id == entity_id,
                    PartyRecordAccess.access == ACCESS_ORIGINATOR,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.party_id
    session.add(
        PartyRecordAccess(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            party_id=party_id,
            access=ACCESS_ORIGINATOR,
            permission=PERMISSION_CONTRIBUTE,
            shared_by=uid,
        )
    )
    await session.flush()
    return party_id


async def visible_ids_filter(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    entity_ids: list[uuid.UUID],
    user_id: uuid.UUID | str | None,
) -> list[uuid.UUID]:
    """``entity_ids`` minus the ones the caller may not see, order kept.

    For batch endpoints: a hidden id is treated as if it did not exist.
    """
    hidden = await party_hidden_ids(
        session,
        project_id=project_id,
        entity_type=entity_type,
        entity_ids=list(entity_ids),
        user_id=user_id,
    )
    return [e for e in entity_ids if str(e) not in hidden]

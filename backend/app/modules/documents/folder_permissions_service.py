"""‌⁠‍Folder-permission service — grant / revoke / effective-permissions API.

Stateless functions mirroring :mod:`app.modules.documents.share_service`.

Public surface
--------------
* :func:`grant_permission` — owner mints a viewer/editor/owner grant.
  Maps unique-constraint violations to HTTP 409 so the UI can show a
  meaningful "already granted" message instead of a generic 500.
* :func:`revoke_permission` — owner hard-revokes by primary key
  (soft-flips ``revoked``). The grant survives so a future audit
  endpoint can replay history.
* :func:`list_permissions` — owner-only inventory for the modal.
* :func:`effective_permissions_for` — what a non-owner user can see
  on a given project. Returns a dict keyed by ``(scope_kind,
  scope_path)`` → role string. Includes wildcard (``scope_path is None``)
  grants. The router uses this to filter ``list_documents`` and to
  enforce read/write on ``get_document`` / ``delete_document``.
* :func:`restricted_scopes_for_project` — the set of
  ``(scope_kind, scope_path)`` tuples that have **any** non-revoked
  grant on the project. Used by the router to decide whether an
  unscoped folder is still "open to all members" or has become
  restricted.
* :func:`folder_access_for` — high-level convenience used by the
  document endpoints: given a user + project + ``(kind, path)`` it
  returns the effective role (or ``None`` for "no access"). Folds the
  "owner bypass", "unscoped folder is open" and "grant required"
  branches together so the routers stay simple.

Why a service module instead of a repository?
    The data shape is two queries deep (grants table joined to
    projects + users). Splitting into models / schemas / service keeps
    the router thin and the test surface small without adding a
    dedicated repository class — the queries are short enough.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.folder_permissions_models import (
    FOLDER_ROLE_RANK,
    FOLDER_ROLES,
    FolderPermission,
    role_satisfies,
)
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership

logger = logging.getLogger(__name__)


# ── Membership helper ────────────────────────────────────────────────────────


async def is_project_owner(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """‌⁠‍True when ``user_id`` is the project's ``owner_id``."""
    stmt = select(Project.owner_id).where(Project.id == project_id)
    owner_id = (await session.execute(stmt)).scalar_one_or_none()
    return owner_id is not None and str(owner_id) == str(user_id)


async def is_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """‌⁠‍True when ``user_id`` is a member of the project's default team
    (owner counts as a member by definition — convenient for callers
    that just want a binary "can this user even see the project?")."""
    if await is_project_owner(session, project_id, user_id):
        return True

    stmt = (
        select(TeamMembership.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            Team.project_id == project_id,
            TeamMembership.user_id == user_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


# ── Grant / revoke / list ────────────────────────────────────────────────────


async def grant_permission(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    scope_kind: str,
    scope_path: str | None,
    role: str,
    granted_by: uuid.UUID,
) -> FolderPermission:
    """Create a new grant. Raises 409 on duplicate (scope, user)."""
    if role not in FOLDER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {FOLDER_ROLES}",
        )

    # Normalise empty string → NULL so the unique constraint behaves
    # the way callers expect ("no path" is a single bucket).
    normalised_path = scope_path or None

    row = FolderPermission(
        project_id=project_id,
        scope_kind=scope_kind,
        scope_path=normalised_path,
        user_id=user_id,
        role=role,
        granted_by=granted_by,
        granted_at=datetime.now(tz=UTC),
        revoked=False,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Unique-constraint violation → 409. Anything else bubbles up
        # as a 500 (genuine programmer error / DB outage).
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already has a grant on this folder",
        ) from exc

    logger.info(
        "Granted folder permission project=%s scope=%s:%s user=%s role=%s by=%s",
        project_id,
        scope_kind,
        normalised_path or "*",
        user_id,
        role,
        granted_by,
    )
    return row


async def revoke_permission(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    permission_id: uuid.UUID,
) -> None:
    """Soft-revoke a grant by id. 404 when the grant belongs to a
    different project (defence against cross-project IDOR)."""
    stmt = select(FolderPermission).where(FolderPermission.id == permission_id)
    perm = (await session.execute(stmt)).scalar_one_or_none()
    if perm is None or perm.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )
    perm.revoked = True
    session.add(perm)
    await session.flush()
    logger.info(
        "Revoked folder permission %s project=%s",
        permission_id,
        project_id,
    )


async def list_permissions(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    scope_kind: str | None = None,
    scope_path: str | None = None,
    include_revoked: bool = False,
) -> list[FolderPermission]:
    """Return grants for a project, optionally narrowed to one scope."""
    conditions = [FolderPermission.project_id == project_id]
    if not include_revoked:
        conditions.append(FolderPermission.revoked.is_(False))
    if scope_kind is not None:
        conditions.append(FolderPermission.scope_kind == scope_kind)
        # Treat empty string as NULL — matches grant_permission().
        normalised_path = scope_path or None
        if normalised_path is None:
            conditions.append(FolderPermission.scope_path.is_(None))
        else:
            conditions.append(FolderPermission.scope_path == normalised_path)

    stmt = select(FolderPermission).where(and_(*conditions)).order_by(FolderPermission.granted_at.desc().nullslast())
    return list((await session.execute(stmt)).scalars().all())


# ── Effective access lookups (used by the document router) ───────────────────


async def effective_permissions_for(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[tuple[str, str | None], str]:
    """Map of ``(scope_kind, scope_path)`` → role for the user on this project.

    Only returns non-revoked grants. The router uses this map to:

    1. Filter the document list to folders the user can see.
    2. Decide whether ``get_document`` / ``delete_document`` should
       return the row or 404 it.
    """
    stmt = select(
        FolderPermission.scope_kind,
        FolderPermission.scope_path,
        FolderPermission.role,
    ).where(
        FolderPermission.project_id == project_id,
        FolderPermission.user_id == user_id,
        FolderPermission.revoked.is_(False),
    )
    rows = (await session.execute(stmt)).all()
    out: dict[tuple[str, str | None], str] = {}
    for scope_kind, scope_path, role in rows:
        key = (scope_kind, scope_path)
        # Multiple grants on the same scope shouldn't exist (unique
        # constraint), but if they do we prefer the strongest role —
        # keeps the contract safe under bugs / data import quirks.
        existing = out.get(key)
        if existing is None or FOLDER_ROLE_RANK.get(role, -1) > FOLDER_ROLE_RANK.get(existing, -1):
            out[key] = role
    return out


async def restricted_scopes_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> set[tuple[str, str | None]]:
    """Return every ``(scope_kind, scope_path)`` that has EVER had a
    grant on the project — revoked rows included.

    Once a folder has been scoped by the owner it remains "managed":
    revoking the last grant doesn't silently open it back up to every
    member. To reopen a folder the owner explicitly re-grants the
    members who should still see it. This matches the UX contract
    ("revoke = lose access") and avoids the surprising flip where
    revoking a single grant suddenly broadens visibility for
    everyone else on the project.
    """
    stmt = (
        select(FolderPermission.scope_kind, FolderPermission.scope_path)
        .where(FolderPermission.project_id == project_id)
        .distinct()
    )
    rows = (await session.execute(stmt)).all()
    return {(scope_kind, scope_path) for scope_kind, scope_path in rows}


async def folder_access_for(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    scope_kind: str,
    scope_path: str | None,
) -> str | None:
    """High-level "what role does this user effectively have here?"

    Returns:
        * ``"owner"`` when the user is the project owner (full bypass).
        * The grant's role string (``"viewer"`` / ``"editor"`` /
          ``"owner"``) when the user has a specific grant covering
          this scope.
        * ``"editor"`` (default member capability) when the scope has
          NO grants at all AND the user is a project member. This
          keeps existing folders unrestricted by default.
        * ``None`` when the user has no access — caller turns this
          into 404.

    The "default member capability" for unscoped folders intentionally
    grants editor — matches the pre-folder-permissions behaviour where
    any member with ``documents.update`` could upload / delete.
    """
    user_id_norm = uuid.UUID(str(user_id))

    if await is_project_owner(session, project_id, user_id_norm):
        return "owner"

    if not await is_project_member(session, project_id, user_id_norm):
        return None

    # Look for a grant covering EXACTLY this scope, then fall back to
    # the wildcard grant on the same kind. A grant on the kind itself
    # (``scope_path is None``) is an "all paths under this kind"
    # umbrella that loses to a more specific grant.
    normalised_path = scope_path or None
    grants = await effective_permissions_for(
        session,
        project_id=project_id,
        user_id=user_id_norm,
    )
    exact = grants.get((scope_kind, normalised_path))
    if exact is not None:
        return exact
    if normalised_path is not None:
        wildcard = grants.get((scope_kind, None))
        if wildcard is not None:
            return wildcard

    # No grant for this scope. If ANY grant exists on the scope's kind,
    # the folder is "restricted" and the user has no access.
    restricted = await restricted_scopes_for_project(session, project_id)
    # The folder is restricted if any grant matches the exact scope,
    # OR if the user is hitting a sub-path while a wildcard exists,
    # OR if the user is hitting the wildcard while a sub-path exists.
    if (scope_kind, normalised_path) in restricted:
        return None
    if normalised_path is not None and (scope_kind, None) in restricted:
        return None
    if normalised_path is None and any(sk == scope_kind for sk, _ in restricted):
        # A specific sub-path is restricted, but the user is asking
        # for the "all of kind" view. Treat the wildcard view as
        # readable (so they see un-restricted siblings) — the
        # per-document filter below removes the restricted rows.
        return "viewer"

    # No grant + folder is open to all members = default editor capability.
    return "editor"


def require_read(role: str | None) -> None:
    """Raise 404 unless ``role`` lets the user read the folder."""
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )


def can_write(role: str | None) -> bool:
    """Return True when ``role`` lets the user upload / delete files."""
    if role is None:
        return False
    return role_satisfies(role, "editor")


def can_admin(role: str | None) -> bool:
    """Return True when ``role`` lets the user manage permissions."""
    if role is None:
        return False
    return role_satisfies(role, "owner")


# Helper for routers that load the (kind, path) of a Document.
def kind_and_path_for_document(category: str | None) -> tuple[str, str | None]:
    """Map a stored ``Document.category`` to a folder ``(kind, path)``.

    For now ``scope_path`` is always ``None`` for top-level documents
    because the storage layer doesn't track sub-folders for the
    ``oe_documents_document`` table. The contract still allows
    sub-paths so future virtual-folder features (e.g. discipline-
    bucketed sheets) can use the same machinery without a model
    change.
    """
    # The frontend FileKind enum covers more variants than the legacy
    # Document.category column (drawing/contract/specification/photo/
    # correspondence/other). For now we map them through ``document``
    # as the umbrella kind so the OWNER-only management modal lists
    # one folder per FileKind. Sub-categories live in ``scope_path``.
    kind = "document"
    if category in {"drawing", "contract", "specification", "photo", "correspondence", "other"}:
        return kind, category
    return kind, None

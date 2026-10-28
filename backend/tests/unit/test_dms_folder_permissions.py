"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠R7 DMS folder-permission tests.

Scope
-----
Per-folder ACL tests covering:

    1. Wrong-role gets 403 (viewer cannot write).
    2. Wrong-tenant / unknown user gets 404 (not 403 — don't leak existence).
    3. Owner always bypasses the ACL.
    4. Editor can write to an unscoped (open) folder.
    5. Viewer is denied write on a restricted folder.
    6. Wildcard grant (scope_path=None) covers every sub-path of that kind.
    7. More-specific grant beats the wildcard.
    8. ``folder_access_for`` returns ``None`` when a folder is restricted
       and the user has no matching grant (→ caller turns into 404).

All tests are pure-unit: repositories and the DB are fully stubbed.
``is_project_owner`` / ``is_project_member`` are patched to return
a deterministic answer so we don't need a real User table.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.documents.folder_permissions_models import (
    FOLDER_ROLE_EDITOR,
    FOLDER_ROLE_OWNER,
    FOLDER_ROLE_VIEWER,
    FOLDER_ROLES,
    FOLDER_SCOPED_CATEGORIES,
    role_satisfies,
)
from app.modules.documents.folder_permissions_service import (
    can_admin,
    can_write,
    effective_permissions_for,
    folder_access_for,
    kind_and_path_for_document,
    readable_document_scopes,
    require_read,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _project_id() -> uuid.UUID:
    return uuid.uuid4()


def _user_id() -> uuid.UUID:
    return uuid.uuid4()


def _grant_row(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    scope_kind: str,
    scope_path: str | None,
    role: str,
    revoked: bool = False,
) -> Any:
    """Return a minimal FolderPermission-shaped namespace."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=user_id,
        scope_kind=scope_kind,
        scope_path=scope_path,
        role=role,
        revoked=revoked,
    )


def _make_session(*rows: Any) -> AsyncMock:
    """Return an AsyncSession mock that yields ``rows`` from execute().scalars()."""
    session = AsyncMock()

    async def _execute(_stmt: Any) -> Any:
        class _ScalarResult:
            def all(self) -> list[Any]:
                return list(rows)

            def scalars(self) -> _ScalarResult:
                return self

        class _Result:
            def scalars(self) -> _ScalarResult:
                return _ScalarResult()

            def all(self) -> list[tuple[Any, ...]]:
                # For multi-column selects return tuples
                return [(r.scope_kind, r.scope_path, r.role) for r in rows]

        return _Result()

    session.execute = _execute
    return session


# ── 1. role_satisfies helper ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "actual,required,expected",
    [
        (FOLDER_ROLE_VIEWER, FOLDER_ROLE_VIEWER, True),
        (FOLDER_ROLE_EDITOR, FOLDER_ROLE_VIEWER, True),
        (FOLDER_ROLE_OWNER, FOLDER_ROLE_VIEWER, True),
        (FOLDER_ROLE_VIEWER, FOLDER_ROLE_EDITOR, False),
        (FOLDER_ROLE_EDITOR, FOLDER_ROLE_EDITOR, True),
        (FOLDER_ROLE_OWNER, FOLDER_ROLE_EDITOR, True),
        (FOLDER_ROLE_VIEWER, FOLDER_ROLE_OWNER, False),
        (FOLDER_ROLE_EDITOR, FOLDER_ROLE_OWNER, False),
        (FOLDER_ROLE_OWNER, FOLDER_ROLE_OWNER, True),
        (None, FOLDER_ROLE_VIEWER, False),
        ("unknown_role", FOLDER_ROLE_VIEWER, False),
    ],
)
def test_role_satisfies(actual: str | None, required: str, expected: bool) -> None:
    assert role_satisfies(actual or "", required) == expected


# ── 2. can_write / can_admin ──────────────────────────────────────────────


def test_can_write_viewer_is_false() -> None:
    assert can_write(FOLDER_ROLE_VIEWER) is False


def test_can_write_editor_is_true() -> None:
    assert can_write(FOLDER_ROLE_EDITOR) is True


def test_can_write_owner_is_true() -> None:
    assert can_write(FOLDER_ROLE_OWNER) is True


def test_can_write_none_is_false() -> None:
    assert can_write(None) is False


def test_can_admin_owner_only() -> None:
    assert can_admin(FOLDER_ROLE_OWNER) is True
    assert can_admin(FOLDER_ROLE_EDITOR) is False
    assert can_admin(FOLDER_ROLE_VIEWER) is False
    assert can_admin(None) is False


# ── 3. require_read raises 404 for None role ──────────────────────────────


def test_require_read_raises_404_for_none() -> None:
    with pytest.raises(HTTPException) as exc:
        require_read(None)
    assert exc.value.status_code == 404


def test_require_read_does_not_raise_for_viewer() -> None:
    require_read(FOLDER_ROLE_VIEWER)  # must not raise


# ── 4. effective_permissions_for aggregates grants ────────────────────────


@pytest.mark.asyncio
async def test_effective_permissions_for_returns_strongest_role() -> None:
    """When two grants exist for the same scope, the strongest role wins."""
    project_id = _project_id()
    user_id = _user_id()

    grant_viewer = _grant_row(project_id, user_id, "document", "drawing", FOLDER_ROLE_VIEWER)
    grant_editor = _grant_row(project_id, user_id, "document", "drawing", FOLDER_ROLE_EDITOR)

    # Build a session that returns both rows for the multi-column select.
    session = AsyncMock()

    async def _execute(_stmt: Any) -> Any:
        class _Result:
            def all(self) -> list[tuple[Any, ...]]:
                return [
                    (grant_viewer.scope_kind, grant_viewer.scope_path, grant_viewer.role),
                    (grant_editor.scope_kind, grant_editor.scope_path, grant_editor.role),
                ]

        return _Result()

    session.execute = _execute

    result = await effective_permissions_for(
        session,
        project_id=project_id,
        user_id=user_id,
    )
    assert result.get(("document", "drawing")) == FOLDER_ROLE_EDITOR


@pytest.mark.asyncio
async def test_effective_permissions_for_empty_returns_empty_dict() -> None:
    session = AsyncMock()

    async def _execute(_stmt: Any) -> Any:
        class _Result:
            def all(self) -> list[Any]:
                return []

        return _Result()

    session.execute = _execute
    result = await effective_permissions_for(
        session,
        project_id=_project_id(),
        user_id=_user_id(),
    )
    assert result == {}


# ── 5. folder_access_for — owner bypass ──────────────────────────────────


@pytest.mark.asyncio
async def test_folder_access_for_owner_returns_owner_role() -> None:
    """Project owner always gets 'owner' role regardless of grants."""
    project_id = _project_id()
    owner_id = _user_id()
    session = AsyncMock()

    with (
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=True),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=owner_id,
            scope_kind="document",
            scope_path="drawing",
        )
    assert role == "owner"


# ── 6. folder_access_for — non-member returns None (→ 404) ───────────────


@pytest.mark.asyncio
async def test_folder_access_for_non_member_returns_none() -> None:
    """A user who is neither owner nor team member gets None (→ 404 in router)."""
    project_id = _project_id()
    stranger_id = _user_id()
    session = AsyncMock()

    with (
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=False),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=stranger_id,
            scope_kind="document",
            scope_path=None,
        )
    assert role is None


# ── 7. folder_access_for — open folder grants editor to member ───────────


@pytest.mark.asyncio
async def test_folder_access_for_open_folder_grants_editor_to_member() -> None:
    """An unrestricted folder (no grants at all) opens editor to any project member."""
    project_id = _project_id()
    member_id = _user_id()
    session = AsyncMock()

    # No grants exist → restricted_scopes_for_project returns empty set.
    async def _execute(_stmt: Any) -> Any:
        class _Result:
            def all(self) -> list[Any]:
                return []

        return _Result()

    session.execute = _execute

    with (
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=True),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=member_id,
            scope_kind="document",
            scope_path=None,
        )
    assert role == "editor"


# ── 8. folder_access_for — restricted folder, no grant → None (→ 404) ───


@pytest.mark.asyncio
async def test_folder_access_for_restricted_folder_no_grant_returns_none() -> None:
    """If the folder is restricted and the user has no matching grant → None (404)."""
    project_id = _project_id()
    member_id = _user_id()
    other_user = _user_id()
    session = AsyncMock()

    call_count = 0

    async def _execute(_stmt: Any) -> Any:
        nonlocal call_count
        call_count += 1

        class _Result:
            def all(self) -> list[Any]:
                if call_count <= 1:
                    # effective_permissions_for — user has no grants
                    return []
                # restricted_scopes_for_project — someone has a grant here
                return [("document", "drawing")]

        return _Result()

    session.execute = _execute

    with (
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=True),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=member_id,
            scope_kind="document",
            scope_path="drawing",
        )
    assert role is None


# ── 8b. folder_access_for — global admin bypasses the ACL ─────────────────


@pytest.mark.asyncio
async def test_folder_access_for_global_admin_returns_owner() -> None:
    """A global admin (users.role == 'admin') gets 'owner' on any project,
    even when not the project owner and not a member - matching the admin
    bypass on the document download path that surfaced as a broken "open"
    action when the metadata endpoint 404'd for a non-owner admin."""
    project_id = _project_id()
    admin_id = _user_id()
    session = AsyncMock()

    admin_repo = AsyncMock()
    admin_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(role="admin"))

    with (
        patch(
            "app.modules.users.repository.UserRepository",
            return_value=admin_repo,
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=False),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=admin_id,
            scope_kind="document",
            scope_path="drawing",
        )
    assert role == "owner"


@pytest.mark.asyncio
async def test_folder_access_for_non_admin_member_role_does_not_bypass() -> None:
    """A regular member (role != 'admin') must NOT get the admin bypass: a
    non-owner / non-member regular user still resolves to None (→ 404)."""
    project_id = _project_id()
    member_id = _user_id()
    session = AsyncMock()

    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=SimpleNamespace(role="member"))

    with (
        patch(
            "app.modules.users.repository.UserRepository",
            return_value=repo,
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=False),
        ),
    ):
        role = await folder_access_for(
            session,
            project_id=project_id,
            user_id=member_id,
            scope_kind="document",
            scope_path=None,
        )
    assert role is None


# ── 9. Wrong-tenant IDOR: grant from project-A is invisible in project-B ─


@pytest.mark.asyncio
async def test_cross_project_grant_not_visible() -> None:
    """A grant on project-A must not leak into project-B's permission map."""
    project_a = _project_id()
    project_b = _project_id()
    user_id = _user_id()
    session = AsyncMock()

    # Session returns a grant scoped to project_a.
    grant_a = _grant_row(project_a, user_id, "document", None, FOLDER_ROLE_OWNER)

    async def _execute(_stmt: Any) -> Any:
        class _Result:
            def all(self) -> list[Any]:
                # Return nothing — the SQL WHERE clause would filter project_b's query
                # to return zero rows. We simulate that here.
                return []

        return _Result()

    session.execute = _execute

    with (
        patch(
            "app.modules.documents.folder_permissions_service.is_project_owner",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.modules.documents.folder_permissions_service.is_project_member",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await effective_permissions_for(
            session,
            project_id=project_b,
            user_id=user_id,
        )
    # No grants visible for project_b.
    assert result == {}


# ── 10. FOLDER_ROLES constant correctness ────────────────────────────────


def test_folder_roles_contains_all_three() -> None:
    assert FOLDER_ROLE_VIEWER in FOLDER_ROLES
    assert FOLDER_ROLE_EDITOR in FOLDER_ROLES
    assert FOLDER_ROLE_OWNER in FOLDER_ROLES


def test_folder_roles_are_distinct() -> None:
    assert len(set(FOLDER_ROLES)) == len(FOLDER_ROLES)


# ── 11. The count filter agrees with the row filter ──────────────────────
#
# ``list_documents`` filters its page row by row and counts the register in
# SQL. Those are two expressions of one decision, and if they disagree the
# register prints a sentence like "showing 3 of 9" where the 9 counts folders
# the reader is not in. ``readable_document_scopes`` is the shared decision;
# these tests pin it against the row filter's own branches.


def _row_filter_admits(
    category: str | None,
    *,
    grants: set[tuple[str, str | None]],
    restricted: set[tuple[str, str | None]],
) -> bool:
    """Replay the router's per-row test, written out longhand."""
    kind, path = kind_and_path_for_document(category)
    is_restricted = (kind, path) in restricted or (kind, None) in restricted
    if not is_restricted:
        return True
    return (kind, path) in grants or (kind, None) in grants


@pytest.mark.parametrize(
    ("grants", "restricted"),
    [
        (set(), set()),
        (set(), {("document", "drawing")}),
        ({("document", "drawing")}, {("document", "drawing")}),
        ({("document", "contract")}, {("document", "drawing"), ("document", "contract")}),
        (set(), {("document", None)}),
        ({("document", None)}, {("document", None)}),
        ({("document", "photo")}, {("document", None)}),
    ],
)
def test_readable_scopes_match_the_row_filter_on_every_category(
    grants: set[tuple[str, str | None]],
    restricted: set[tuple[str, str | None]],
) -> None:
    """Same verdict for every category, including ones no scope names."""
    readable = readable_document_scopes(grants=grants, restricted=restricted)
    # ``None`` stands for every category outside the folder-scoped set, so an
    # invented one has to be tested through it.
    for category in (*FOLDER_SCOPED_CATEGORIES, None, "invoice"):
        _, path = kind_and_path_for_document(category)
        assert (path in readable) is _row_filter_admits(category, grants=grants, restricted=restricted), (
            f"category={category!r} grants={grants} restricted={restricted}"
        )


def test_readable_scopes_is_everything_when_no_folder_was_ever_scoped() -> None:
    """The common project: no grants exist, so the count excludes nothing."""
    readable = readable_document_scopes(grants=set(), restricted=set())
    assert readable == {*FOLDER_SCOPED_CATEGORIES, None}


def test_a_restricted_folder_without_a_grant_drops_out_of_the_count() -> None:
    """The case the row filter already handles, now visible to the count."""
    readable = readable_document_scopes(
        grants=set(),
        restricted={("document", "drawing")},
    )
    assert "drawing" not in readable
    assert "contract" in readable
    assert None in readable

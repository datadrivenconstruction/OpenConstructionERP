"""Baseline tests for :class:`TeamService`.

Scope:
    * Create a team within a project.
    * Add a member; verify the membership row exists and carries the
      requested role (the permission-inheritance signal the rest of the
      system reads off ``TeamMembership.role``).
    * Remove the member; verify the row is gone (revoking the inherited
      grant).
    * RBAC self-elevation guard: a non-owner caller cannot grant
      themselves an ELEVATED team role.

Repositories and session are stubbed so the suite doesn't need a live
database. RBAC dependencies (``verify_project_access``,
``_is_project_owner_or_admin``) are monkey-patched per-test so we
exercise the gate without standing up Project / User tables.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.teams.schemas import AddMemberRequest, TeamCreate
from app.modules.teams.service import TeamService

# ── Stubs ─────────────────────────────────────────────────────────────────


class _StubSession:
    """Async-session shim — supports the ``add/flush/expire_all`` surface
    the service touches via the repositories. Audit + event publish are
    no-ops so the test stays focused on team mechanics.
    """

    def __init__(self) -> None:
        self._added: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._added.append(obj)

    async def flush(self) -> None:
        pass

    async def execute(self, stmt: Any) -> SimpleNamespace:
        return SimpleNamespace(rowcount=0)

    def expire_all(self) -> None:
        pass


class _StubTeamRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get(self, team_id: uuid.UUID) -> Any:
        return self.rows.get(team_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = False,
    ) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def create(self, team: Any) -> Any:
        if getattr(team, "id", None) is None:
            team.id = uuid.uuid4()
        now = datetime.now(UTC)
        team.created_at = now
        team.updated_at = now
        team.is_active = True
        team.memberships = []
        self.rows[team.id] = team
        return team

    async def update_fields(self, team_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(team_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, team_id: uuid.UUID) -> None:
        self.rows.pop(team_id, None)


class _StubMembershipRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, uuid.UUID], Any] = {}

    async def list_for_team(self, team_id: uuid.UUID) -> list[Any]:
        return [m for (tid, _uid), m in self.rows.items() if tid == team_id]

    async def get_membership(
        self,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Any:
        return self.rows.get((team_id, user_id))

    async def add(self, membership: Any) -> Any:
        if getattr(membership, "id", None) is None:
            membership.id = uuid.uuid4()
        membership.created_at = datetime.now(UTC)
        self.rows[(membership.team_id, membership.user_id)] = membership
        return membership

    async def remove(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return self.rows.pop((team_id, user_id), None) is not None


def _make_service(
    *,
    project_access_ok: bool = True,
    is_owner_or_admin: bool = True,
) -> TeamService:
    """Build a TeamService wired to stubs.

    ``project_access_ok``  — fake ``verify_project_access`` outcome.
    ``is_owner_or_admin`` — fake elevation gate outcome.
    """
    svc = TeamService.__new__(TeamService)
    svc.session = _StubSession()
    svc.team_repo = _StubTeamRepo()
    svc.membership_repo = _StubMembershipRepo()
    svc.visibility_repo = SimpleNamespace()

    async def _assert(_project_id: uuid.UUID, _actor: Any) -> None:
        if not project_access_ok:
            raise HTTPException(status_code=404, detail="Project not found")

    async def _priv(_project_id: uuid.UUID, _actor: Any) -> bool:
        return is_owner_or_admin

    svc._assert_project_access = _assert  # type: ignore[assignment]
    svc._is_project_owner_or_admin = _priv  # type: ignore[assignment]

    # No-op audit + events so the focused test doesn't depend on the
    # global event bus or the audit-log table.
    async def _noop_audit(**_kw: Any) -> None: ...
    async def _noop_event(_name: str, _payload: dict[str, Any]) -> None: ...

    svc._record_audit = _noop_audit  # type: ignore[assignment]
    svc._publish_event = _noop_event  # type: ignore[assignment]
    return svc


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_lifecycle_member_role_inheritance() -> None:
    """End-to-end: create team → add member with a role → membership row
    carries that role → removing the member drops the inheritance signal.
    """
    svc = _make_service()
    project_id = uuid.uuid4()
    owner_actor = uuid.uuid4()  # plays the project owner / admin

    # 1. Create team.
    team = await svc.create_team(
        TeamCreate(project_id=project_id, name="Estimators"),
        actor_id=owner_actor,
    )
    assert team.project_id == project_id
    assert team.name == "Estimators"

    # 2. Add a member with the project_manager role — caller is owner so
    #    elevation is allowed.
    member_user = uuid.uuid4()
    membership = await svc.add_member(
        team.id,
        AddMemberRequest(user_id=member_user, role="project_manager"),
        actor_id=owner_actor,
    )
    assert membership.team_id == team.id
    assert membership.user_id == member_user

    # 3. The membership row IS the permission-inheritance signal: any
    #    downstream resolver reads role off this record. Confirm it is
    #    persisted and queryable.
    listed = await svc.list_members(team.id)
    assert len(listed) == 1
    assert listed[0].user_id == member_user
    assert listed[0].role == "project_manager"

    # 4. Remove the member — the inherited grant goes with the row.
    await svc.remove_member(team.id, member_user, actor_id=owner_actor)
    listed_after = await svc.list_members(team.id)
    assert listed_after == []

    # Trying to remove again is a 404 (no orphan membership left behind).
    with pytest.raises(HTTPException) as exc:
        await svc.remove_member(team.id, member_user, actor_id=owner_actor)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_member_blocks_self_elevation_into_owner_role() -> None:
    """A caller who passes verify_project_access but is NOT the project
    owner / system admin cannot grant ELEVATED roles. This is the
    self-elevation hole the RBAC fix closes.
    """
    svc = _make_service(project_access_ok=True, is_owner_or_admin=False)
    project_id = uuid.uuid4()
    caller = uuid.uuid4()

    # Seed a team via a privileged actor first (so create itself passes).
    svc_owner = _make_service()
    team = await svc_owner.create_team(
        TeamCreate(project_id=project_id, name="Core"),
        actor_id=uuid.uuid4(),
    )
    # Re-attach the team into our test service so add_member can find it.
    svc.team_repo.rows[team.id] = team

    with pytest.raises(HTTPException) as exc:
        await svc.add_member(
            team.id,
            AddMemberRequest(user_id=caller, role="owner"),
            actor_id=caller,
        )
    assert exc.value.status_code == 403

    # Sanity: the basic role IS allowed for the same caller.
    membership = await svc.add_member(
        team.id,
        AddMemberRequest(user_id=caller, role="member"),
        actor_id=caller,
    )
    assert membership.role == "member"

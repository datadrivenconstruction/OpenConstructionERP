"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for :class:`TeamService`'s two authorisation gates.

Scope, and the reason for the split: the behavioural coverage of this module -
what a restriction does, who may write one, what a stranger sees - lives in
``tests/unit/teams/`` against a real PostgreSQL session, because a gate is only
proved by the data it refuses. What is left here is the part that genuinely
does not need a database: how ``_assert_project_admin`` composes the access
check and the ownership check, and that ``add_member`` cannot be reached
without passing both.

Repositories and session are stubbed. ``_assert_project_access`` and
``_is_project_owner_or_admin`` are monkey-patched per test so the composition
can be driven through all four combinations without standing up Project and
User tables. ``_assert_project_admin`` itself is NOT stubbed - it is the thing
under test.
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
    """Async-session shim - supports the ``add/flush`` surface the service
    touches via the repositories. Audit + event publish are no-ops so the test
    stays focused on the gate.
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

    async def clear_default_flag(self, project_id: uuid.UUID, keep_team_id: uuid.UUID) -> None:
        for row in self.rows.values():
            if row.project_id == project_id and row.id != keep_team_id:
                row.is_default = False

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

    async def get_membership(self, team_id: uuid.UUID, user_id: uuid.UUID) -> Any:
        return self.rows.get((team_id, user_id))

    async def add(self, membership: Any) -> Any:
        if getattr(membership, "id", None) is None:
            membership.id = uuid.uuid4()
        membership.created_at = datetime.now(UTC)
        self.rows[(membership.team_id, membership.user_id)] = membership
        return membership

    async def set_role(self, team_id: uuid.UUID, user_id: uuid.UUID, role: str) -> bool:
        row = self.rows.get((team_id, user_id))
        if row is None:
            return False
        row.role = role
        return True

    async def remove(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return self.rows.pop((team_id, user_id), None) is not None


def _make_service(
    *,
    project_access_ok: bool = True,
    is_owner_or_admin: bool = True,
) -> TeamService:
    """Build a TeamService wired to stubs.

    ``project_access_ok``  - fake ``verify_project_access`` outcome.
    ``is_owner_or_admin``  - fake ownership outcome.

    ``_assert_project_admin`` is deliberately left real: it is what composes
    the two into the write gate, and it is the composition that has to hold.
    """
    svc = TeamService.__new__(TeamService)
    svc.session = _StubSession()
    svc.team_repo = _StubTeamRepo()
    svc.membership_repo = _StubMembershipRepo()
    svc.visibility_repo = SimpleNamespace()

    async def _assert(_project_id: uuid.UUID, actor: Any) -> None:
        if actor is None:
            return
        if not project_access_ok:
            raise HTTPException(status_code=404, detail="Project not found")

    async def _priv(_project_id: uuid.UUID, _actor: Any) -> bool:
        return is_owner_or_admin

    async def _addable(_user_id: uuid.UUID) -> None:
        """Stand in for the User lookup - the gate, not the user, is under test."""

    svc._assert_project_access = _assert  # type: ignore[assignment]
    svc._is_project_owner_or_admin = _priv  # type: ignore[assignment]
    svc._assert_user_addable = _addable  # type: ignore[assignment]

    # No-op audit + events so the focused test doesn't depend on the
    # global event bus or the audit-log table.
    async def _noop_audit(**_kw: Any) -> None: ...
    async def _noop_event(_name: str, _payload: dict[str, Any]) -> None: ...

    svc._record_audit = _noop_audit  # type: ignore[assignment]
    svc._publish_event = _noop_event  # type: ignore[assignment]
    return svc


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_lifecycle_for_a_project_owner() -> None:
    """The positive path: an owner creates a team, staffs it, and clears it.

    The membership row IS the permission-inheritance signal - every downstream
    resolver reads the role off it - so the lifecycle is asserted on the row,
    not on the call returning without raising.
    """
    svc = _make_service()
    project_id = uuid.uuid4()
    owner_actor = uuid.uuid4()

    team = await svc.create_team(
        TeamCreate(project_id=project_id, name="Estimators"),
        actor_id=owner_actor,
    )
    assert team.project_id == project_id
    assert team.name == "Estimators"

    member_user = uuid.uuid4()
    membership = await svc.add_member(
        team.id,
        AddMemberRequest(user_id=member_user, role="project_manager"),
        actor_id=owner_actor,
    )
    assert membership.team_id == team.id
    assert membership.user_id == member_user

    listed = await svc.list_members(team.id, actor_id=owner_actor)
    assert len(listed) == 1
    assert listed[0].role == "project_manager"

    await svc.remove_member(team.id, member_user, actor_id=owner_actor)
    assert await svc.list_members(team.id, actor_id=owner_actor) == []

    # Removing again is a 404 - no orphan membership left behind.
    with pytest.raises(HTTPException) as exc:
        await svc.remove_member(team.id, member_user, actor_id=owner_actor)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_write_gate_refuses_a_caller_who_only_has_project_access() -> None:
    """Project access is not enough to write a membership.

    A membership row is what ``verify_project_access`` reads to grant project
    access, so a caller able to write one can hand an outsider a project they
    could not see. This is the composition that closes it: access check passes,
    ownership check fails, gate refuses with 403 - and it refuses for a BASIC
    role, not only an elevated one.

    Swap ``_assert_project_admin`` back to ``_assert_project_access`` in
    ``add_member`` and this test fails.
    """
    svc = _make_service(project_access_ok=True, is_owner_or_admin=False)
    project_id = uuid.uuid4()
    caller = uuid.uuid4()

    owner_svc = _make_service()
    team = await owner_svc.create_team(
        TeamCreate(project_id=project_id, name="Core"),
        actor_id=uuid.uuid4(),
    )
    svc.team_repo.rows[team.id] = team

    for role in ("member", "owner"):
        with pytest.raises(HTTPException) as exc:
            await svc.add_member(
                team.id,
                AddMemberRequest(user_id=caller, role=role),
                actor_id=caller,
            )
        assert exc.value.status_code == 403, role

    # Nothing was written on the way to the refusal.
    assert svc.membership_repo.rows == {}


@pytest.mark.asyncio
async def test_write_gate_refuses_a_caller_who_cannot_see_the_project_with_404() -> None:
    """404 comes first, so a caller who cannot see the project learns nothing.

    The order matters: were the ownership check first, a stranger would get 403
    and learn the project exists.
    """
    svc = _make_service(project_access_ok=False, is_owner_or_admin=False)
    project_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        await svc.create_team(
            TeamCreate(project_id=project_id, name="Nope"),
            actor_id=uuid.uuid4(),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_role_change_takes_the_same_gate_as_an_add() -> None:
    """Otherwise an in-place promotion routes around the add-time check."""
    project_id = uuid.uuid4()
    owner_actor = uuid.uuid4()
    owner_svc = _make_service()
    team = await owner_svc.create_team(
        TeamCreate(project_id=project_id, name="Core"),
        actor_id=owner_actor,
    )
    member = uuid.uuid4()
    await owner_svc.add_member(
        team.id,
        AddMemberRequest(user_id=member, role="member"),
        actor_id=owner_actor,
    )

    # The owner may promote.
    promoted = await owner_svc.update_member_role(team.id, member, "owner", actor_id=owner_actor)
    assert promoted.role == "owner"

    # A non-owner with project access may not, even for a basic role.
    weak = _make_service(project_access_ok=True, is_owner_or_admin=False)
    weak.team_repo.rows[team.id] = team
    weak.membership_repo.rows = owner_svc.membership_repo.rows
    with pytest.raises(HTTPException) as exc:
        await weak.update_member_role(team.id, member, "viewer", actor_id=member)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_a_system_call_skips_both_gates() -> None:
    """``actor_id=None`` is reserved for seed scripts and background jobs.

    Kept explicit because it is the one path that bypasses everything above,
    and it must stay unreachable from HTTP - every route passes a real caller.
    """
    svc = _make_service(project_access_ok=False, is_owner_or_admin=False)
    project_id = uuid.uuid4()

    team = await svc.create_team(TeamCreate(project_id=project_id, name="Seeded"), actor_id=None)
    assert team.name == "Seeded"

    membership = await svc.add_member(
        team.id,
        AddMemberRequest(user_id=uuid.uuid4(), role="owner"),
        actor_id=None,
    )
    assert membership.role == "owner"

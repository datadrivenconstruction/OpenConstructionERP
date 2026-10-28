"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠SAFETY PRIMITIVE 1 - the mandatory scoper (pure-unit gates).

The cross-tenant data-isolation assertions need real rows in PostgreSQL, so they
live in ``test_security_scoper_db.py`` (gated on a bootable cluster). The tests
here prove the scoper's structural guarantees without a database:

    * a registration without a scoper is refused at registration time (which is
      module startup), so a misconfigured module fails the boot, not a request;
    * the scoper ANDs a project pin into the statement and never widens it;
    * a missing project_id is refused outright (no unscoped base statement);
    * a plain editor cannot grant a workspace share; a project owner can.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import uuid

import pytest

from app.modules.saved_views.entities import finance_entity
from app.modules.saved_views.errors import (
    RegistrationError,
    ScopeDenied,
    WhitelistError,
)
from app.modules.saved_views.scoper import ProjectMemberScoper, ScopeContext
from app.modules.saved_views.service import SavedViewService
from tests.unit.saved_views._fixtures import RecordingSession, SpySession


def _ctx(project_id=None, role="editor", is_admin=False) -> ScopeContext:
    return ScopeContext(
        user_id=uuid.uuid4(),
        role=role,
        project_id=project_id or uuid.uuid4(),
        workspace_slug=None,
        is_admin=is_admin,
    )


def test_registration_without_scoper_rejected():
    """register_queryable_entity with scoper=None raises RegistrationError."""
    from app.modules.projects.models import Project
    from app.modules.saved_views.registry import (
        FieldSpec,
        QueryableEntity,
        register_queryable_entity,
    )

    entity = QueryableEntity(
        entity_type="no_scoper_entity",
        model=Project,
        fields={"name": FieldSpec(name="name", column="name", kind="string")},
        scoper=None,  # type: ignore[arg-type]
        project_fk_column="id",
        default_sort=("name", "asc"),
    )
    with pytest.raises(RegistrationError):
        register_queryable_entity(entity)


@pytest.mark.asyncio
async def test_missing_project_id_refuses_unscoped_query():
    """A run with no resolvable project_id is refused (no unscoped base stmt)."""
    scoper = ProjectMemberScoper()
    from sqlalchemy import select

    from app.modules.finance.models import LedgerEntry

    ctx = ScopeContext(
        user_id=uuid.uuid4(),
        role="editor",
        project_id=None,
        workspace_slug=None,
        is_admin=False,
    )
    with pytest.raises(ScopeDenied):
        await scoper.scope(select(LedgerEntry), LedgerEntry, ctx, SpySession())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_scoper_ands_project_pin_into_statement():
    """The scoped statement carries a project_id == <pin> predicate.

    ``verify_project_access`` is patched to a pass so no DB is touched; the
    assertion is purely about the SQL the scoper produced.
    """
    from sqlalchemy import select

    from app.modules.finance.models import LedgerEntry

    pinned_project = uuid.uuid4()
    ctx = _ctx(project_id=pinned_project)

    # Register the ledger entity so the scoper can resolve its project_fk_column.
    from app.modules.saved_views.registry import entity_registry

    if entity_registry.get("ledger_entry") is None:
        finance_entity.register()

    async def _pass(project_id, user_id, session):  # noqa: ANN001
        return None

    import app.dependencies as deps_mod

    original = deps_mod.verify_project_access
    deps_mod.verify_project_access = _pass  # type: ignore[assignment]
    try:
        scoper = ProjectMemberScoper()
        stmt = await scoper.scope(select(LedgerEntry), LedgerEntry, ctx, SpySession())  # type: ignore[arg-type]
    finally:
        deps_mod.verify_project_access = original  # type: ignore[assignment]

    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert str(pinned_project) in compiled
    assert "project_id" in compiled.lower()


@pytest.mark.asyncio
async def test_share_scope_workspace_requires_owner():
    """A plain editor cannot create a workspace-shared view; an owner/admin can."""
    # Register the entity so save_view can bind the spec.
    from app.modules.saved_views.registry import entity_registry
    from app.modules.saved_views.schemas import SavedViewCreate

    if entity_registry.get("ledger_entry") is None:
        finance_entity.register()

    project_id = uuid.uuid4()
    payload = SavedViewCreate(
        entity_type="ledger_entry",
        name="Workspace view",
        project_id=project_id,
        share_scope="workspace",
    )

    # The refusal stays on SpySession: the assertion is not only that the editor
    # is refused, but that the refusal lands BEFORE any database round trip.
    editor_service = SavedViewService(SpySession())  # type: ignore[arg-type]
    with pytest.raises(WhitelistError):
        await editor_service.save_view(_ctx(project_id=project_id, role="editor"), payload)

    # A manager / project owner may grant it. This path is allowed, so it is
    # allowed to query: save_view checks the name against the unique index
    # before inserting. RecordingSession answers that probe with "no rows", i.e.
    # the name is free; SpySession cannot, because it refuses every statement by
    # design and that design is what makes the editor half above worth having.
    owner_ctx = _ctx(project_id=project_id, role="manager")
    owner_session = RecordingSession()
    owner_service = SavedViewService(owner_session)  # type: ignore[arg-type]
    view = await owner_service.save_view(owner_ctx, payload)
    assert view.share_scope == "workspace"
    # The name probe is the only statement this path may issue, and the row it
    # would insert reaches the session rather than the wire.
    assert len(owner_session.executed) == 1
    assert owner_session.added == [view]

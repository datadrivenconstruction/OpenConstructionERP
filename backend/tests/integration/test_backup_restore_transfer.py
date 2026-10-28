"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-machine transfer: export as one user, restore as another.

Regression for the restore that aborted on a second PC. The exporter's own
``users`` row travels in the backup with its password hash stripped, and its
email is already taken on the target machine, so re-inserting it failed the
NOT NULL password and the unique email and rolled the whole restore back with
a 500. Restore now skips the users table and repoints every ownership column to
the restoring user, so a backup taken on one machine lands cleanly under the
restoring account on another and the data is actually visible there.

These tests run the real ``restore_backup_data`` service against a
transaction-isolated PostgreSQL session.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.backup.service import (
    _BACKUP_TABLE_DEFS,
    RESTORE_SKIP_KEYS,
    RestoreError,
    _is_sensitive_field,
    build_scope_clause,
    get_backup_registry,
    get_backup_tables,
    reset_backup_registry,
    restore_backup_data,
    serialize_row,
)
from tests._pg import transactional_session

MACHINE_A_USER = uuid.uuid4()
MACHINE_B_USER = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


async def _export_scope(session, owner_id):
    """Mimic build_backup: per-table scoped rows, serialized, sensitive fields stripped."""
    tables = get_backup_tables()
    by_key = {k: cls for k, _t, cls in tables}
    data: dict[str, list[dict]] = {}
    for key, _t, cls in tables:
        clause = build_scope_clause(by_key, key, str(owner_id))
        rows = [] if clause is None else (await session.execute(select(cls).where(clause))).scalars().all()
        data[key] = [{k: v for k, v in serialize_row(r).items() if not _is_sensitive_field(k)} for r in rows]
    return data


@pytest_asyncio.fixture
async def session():
    """Two accounts on notionally different machines, each with its own password."""
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(User(id=MACHINE_A_USER, email="a@pc.io", hashed_password="secret-a", full_name="A"))
        s.add(User(id=MACHINE_B_USER, email="b@pc.io", hashed_password="secret-b", full_name="B"))
        await s.flush()
        yield s


@pytest.mark.asyncio
async def test_backup_transfers_to_the_restoring_user(session):
    """Export A's project graph, then restore it as B on a clean second machine."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    # Machine A builds a project graph and exports it.
    session.add(Project(id=PROJECT_ID, name="Tower", owner_id=MACHINE_A_USER, currency="EUR"))
    await session.flush()
    boq = BOQ(project_id=PROJECT_ID, name="BOQ-A")
    session.add(boq)
    await session.flush()
    for i in range(3):
        session.add(Position(boq_id=boq.id, ordinal=f"{i:03d}", description=f"pos {i}", unit="m3"))
    await session.flush()

    data = await _export_scope(session, MACHINE_A_USER)
    # The backup carries the exporter's own user row, password stripped.
    assert data["users"], "export should include the exporter's own user row"
    assert "hashed_password" not in data["users"][0]
    assert len(data["positions"]) == 3

    # Simulate the second machine: a fresh session that has never loaded A's
    # objects or seen A's data or account.
    session.expunge_all()
    await session.execute(Position.__table__.delete())
    await session.execute(BOQ.__table__.delete())
    await session.execute(Project.__table__.delete())
    await session.execute(User.__table__.delete().where(User.id == MACHINE_A_USER))
    await session.flush()

    # User B restores the backup. This used to abort with a 500 on the users insert.
    imported, skipped, _warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="replace",
    )

    # The project graph is back, now owned by the restoring user.
    proj = (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one()
    assert str(proj.owner_id) == str(MACHINE_B_USER)
    assert (await session.execute(select(func.count()).select_from(Position))).scalar_one() == 3

    # The exporter's account was NOT re-created: the users table is left alone.
    assert "users" in RESTORE_SKIP_KEYS
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 1
    only_user = (await session.execute(select(User))).scalar_one()
    assert str(only_user.id) == str(MACHINE_B_USER)
    assert only_user.hashed_password == "secret-b", "the restoring account keeps its own password"

    # Nothing failed: users reports 0 imported (skipped table), the graph imported cleanly.
    assert imported["users"] == 0
    assert imported["projects"] == 1
    assert imported["positions"] == 3
    assert skipped["projects"] == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_restore_leaves_other_users_untouched_and_repoints_ownership(session):
    """Restoring as B must not delete or duplicate any other account's rows."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    # A owns a project; B owns nothing yet.
    session.add(Project(id=PROJECT_ID, name="Bridge", owner_id=MACHINE_A_USER, currency="EUR"))
    await session.flush()
    data = await _export_scope(session, MACHINE_A_USER)

    # Both accounts still exist here (same-instance restore, e.g. moving a project
    # between two users). Fresh session, remove only A's project so no PK clash.
    session.expunge_all()
    await session.execute(Project.__table__.delete())
    await session.flush()

    await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="replace",
    )

    # Both users survive; the project is now B's.
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 2
    proj = (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one()
    assert str(proj.owner_id) == str(MACHINE_B_USER)


@pytest.mark.asyncio
async def test_merge_restore_keeps_the_restorers_own_ai_settings(session):
    """A's ai_settings must never collide with or overwrite B's, and no key leaks."""
    from app.modules.ai.models import AISettings

    session.add(AISettings(user_id=MACHINE_A_USER, preferred_model="a-model", anthropic_api_key="sk-a"))
    session.add(AISettings(user_id=MACHINE_B_USER, preferred_model="b-model", anthropic_api_key="sk-b"))
    await session.flush()

    data = await _export_scope(session, MACHINE_A_USER)
    assert data["ai_settings"], "export should include A's ai_settings row"
    # The exported row must not carry the API key in plain text.
    assert data["ai_settings"][0].get("anthropic_api_key") is None

    session.expunge_all()

    # B restores in MERGE mode. Repointing A's row to user_id=B would collide with
    # B's own unique row, but ai_settings is skipped, so there is no crash.
    imported, _skipped, _warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="merge",
    )

    assert imported["ai_settings"] == 0
    kept = (await session.execute(select(AISettings).where(AISettings.user_id == MACHINE_B_USER))).scalar_one()
    assert kept.preferred_model == "b-model"
    assert kept.anthropic_api_key == "sk-b", "the restoring account keeps its own AI keys"
    assert (await session.execute(select(func.count()).select_from(AISettings))).scalar_one() == 2


@pytest.mark.asyncio
async def test_one_colliding_row_does_not_sink_the_whole_transfer(session):
    """A single unique-code collision skips that row, it does not abort restore.

    ``Assembly.code`` is globally unique. If both machines happen to hold an
    assembly with the same code (each created independently, so different ids),
    the incoming row cannot be inserted. That must cost only the one assembly, a
    warning, not the entire transfer - otherwise the user's projects and BOQs
    would vanish because of one duplicate recipe code.
    """
    from app.modules.assemblies.models import Assembly
    from app.modules.projects.models import Project

    # B already owns an assembly with a code that A also used on its machine.
    session.add(Assembly(code="SHARED-01", name="B wall", unit="m3", owner_id=MACHINE_B_USER))
    await session.flush()

    # A's backup: a project plus an assembly that reuses that same global code
    # under a different id, exactly the independent-creation case.
    data = {
        "projects": [{"id": str(PROJECT_ID), "name": "Tower", "owner_id": str(MACHINE_A_USER), "currency": "EUR"}],
        "assemblies": [
            {
                "id": str(uuid.uuid4()),
                "code": "SHARED-01",
                "name": "A wall",
                "unit": "m3",
                "owner_id": str(MACHINE_A_USER),
            }
        ],
    }

    imported, skipped, warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="merge",
    )

    # The project imported even though the sibling assembly could not.
    assert imported["projects"] == 1
    assert imported["assemblies"] == 0
    assert skipped["assemblies"] == 1
    assert any("assembl" in w.lower() for w in warnings), "the skipped row is reported"

    proj = (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one()
    assert str(proj.owner_id) == str(MACHINE_B_USER)

    # The code stays unique: B's original row survives, A's was not inserted.
    rows = (await session.execute(select(Assembly).where(Assembly.code == "SHARED-01"))).scalars().all()
    assert len(rows) == 1
    assert str(rows[0].owner_id) == str(MACHINE_B_USER)


@pytest.mark.asyncio
async def test_restore_pins_ownership_to_the_caller_not_the_archive(session):
    """A crafted backup cannot inject a row owned by another account.

    Both the row's owner_id and the manifest created_by are attacker-controlled.
    Here A restores a backup whose project claims owner_id = B (a real other
    account that exists on this instance) with created_by left empty to defeat
    the value-based remap. Ownership must still be forced to A, the caller.
    """
    from app.modules.projects.models import Project

    data = {
        "projects": [{"id": str(PROJECT_ID), "name": "Injected", "owner_id": str(MACHINE_B_USER), "currency": "EUR"}]
    }

    imported, _skipped, _warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_A_USER),  # the caller
        manifest={},  # no created_by, so only forcing can pin ownership
        data=data,
        mode="merge",
    )

    assert imported["projects"] == 1
    proj = (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one()
    assert str(proj.owner_id) == str(MACHINE_A_USER), "ownership is pinned to the caller"
    assert str(proj.owner_id) != str(MACHINE_B_USER), "the archive's owner_id is not trusted"


@pytest.mark.asyncio
async def test_replace_refuses_to_clear_a_populated_account(session):
    """Replace into an account that already holds data is refused, not destructive.

    A project delete cascades in the database across dozens of project-scoped
    modules the backup does not carry (photos, BIM, takeoff, point clouds, diaries,
    schedule baselines). Clearing a populated account before import would destroy
    all of that with nothing to rebuild it. The guard turns that into a refusal
    (``RestoreError`` with ``stage == "guard"``) and changes nothing; merge is the
    non-destructive way in.
    """
    from app.modules.projects.models import Project

    # B already owns a project on this machine.
    existing_id = uuid.uuid4()
    session.add(Project(id=existing_id, name="B's existing work", owner_id=MACHINE_B_USER, currency="EUR"))
    await session.flush()

    # A's backup carries its own project.
    data = {"projects": [{"id": str(PROJECT_ID), "name": "Tower", "owner_id": str(MACHINE_A_USER), "currency": "EUR"}]}

    with pytest.raises(RestoreError) as excinfo:
        await restore_backup_data(
            session,
            user_id=str(MACHINE_B_USER),
            manifest={"created_by": str(MACHINE_A_USER)},
            data=data,
            mode="replace",
        )
    assert excinfo.value.stage == "guard", "a populated-account replace is a guard refusal, not a failure"

    # The guard fired before any write: B's own project is untouched and the
    # archive's project was never inserted.
    mine = (await session.execute(select(Project).where(Project.owner_id == MACHINE_B_USER))).scalars().all()
    assert len(mine) == 1
    assert mine[0].id == existing_id
    assert (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_replace_is_allowed_into_an_empty_account(session):
    """The guard only blocks populated accounts; an empty one still accepts replace."""
    from app.modules.projects.models import Project

    data = {"projects": [{"id": str(PROJECT_ID), "name": "Tower", "owner_id": str(MACHINE_A_USER), "currency": "EUR"}]}

    # B owns nothing, so replace proceeds and imports normally.
    imported, _skipped, _warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="replace",
    )

    assert imported["projects"] == 1
    proj = (await session.execute(select(Project).where(Project.id == PROJECT_ID))).scalar_one()
    assert str(proj.owner_id) == str(MACHINE_B_USER)


def test_registry_covers_far_more_than_the_curated_core() -> None:
    """v11.6.0: the backup scope is derived from the whole schema, not 19 tables.

    The old backup carried a curated 19-table core, so every user-owned table
    added since (contacts, notifications, HSE records, labor rates and so on) was
    silently dropped from a personal backup. The schema-driven registry closes
    that gap. This asserts the breadth, that the curated core is still covered,
    and that tables come out parents-before-children so a restore is FK-safe.
    """
    reset_backup_registry()
    tables = get_backup_tables()
    keys = [k for k, _t, _c in tables]

    # Far more than the historical core, and the export surface matches the registry.
    assert len(tables) > 100, f"expected full coverage, got only {len(tables)} tables"
    assert tables == get_backup_registry().table_defs

    # The curated core is a subset (nothing that used to be backed up is dropped).
    curated = {k for k, _t, _m, _c in _BACKUP_TABLE_DEFS}
    assert curated <= set(keys), f"curated keys missing: {sorted(curated - set(keys))}"

    # Tables that used to be dropped are now in scope.
    for expected_new in ("oe_contacts_contact", "oe_notifications_notification"):
        assert expected_new in keys, f"{expected_new} should now be covered"

    # Parents precede children: every "in" predicate's parent comes first, and the
    # users root leads. This is what makes the ordered insert / reversed clear safe.
    scope = get_backup_registry().scope
    position = {k: i for i, k in enumerate(keys)}
    assert keys[0] == "users"
    for key, preds in scope.items():
        for pred in preds:
            if pred[0] == "in":
                assert position[pred[2]] < position[key], (pred[2], "must precede", key)


@pytest.mark.asyncio
async def test_full_coverage_backs_up_a_previously_dropped_table(session):
    """A contact (outside the old 19-table core) now survives export and restore."""
    from app.modules.contacts.models import Contact

    # Machine A owns a contact. Under the old curated backup this row was dropped.
    session.add(Contact(contact_type="supplier", company_name="ACME Ltd", created_by=str(MACHINE_A_USER)))
    await session.flush()

    data = await _export_scope(session, MACHINE_A_USER)
    assert data.get("oe_contacts_contact"), "the contact must be included in the backup"

    # Second machine: the contact is gone, B restores the archive.
    session.expunge_all()
    await session.execute(Contact.__table__.delete())
    await session.flush()

    imported, _skipped, _warnings = await restore_backup_data(
        session,
        user_id=str(MACHINE_B_USER),
        manifest={"created_by": str(MACHINE_A_USER)},
        data=data,
        mode="merge",
    )

    assert imported.get("oe_contacts_contact") == 1
    restored = (await session.execute(select(Contact).where(Contact.company_name == "ACME Ltd"))).scalar_one()
    assert restored.created_by == str(MACHINE_B_USER), "ownership pinned to the restoring user"

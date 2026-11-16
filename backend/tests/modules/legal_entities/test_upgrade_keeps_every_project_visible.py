# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Upgrading an install that already has people and projects hides nothing from anyone.

The install is built at the revision before ``vle01`` (the full schema with the
revision undone), filled with an admin, owners, a team member, an outsider, two
companies from the earlier legal entities release and projects some of which
name a company. What every person sees is measured with the rule as it stood
before (admin: all; others: owned or on the team). Then the revision runs, and
the new rule must give every person exactly the same set. Adding the first
member to a company afterwards may only add projects to that person's set.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import Base
from app.dependencies import accessible_project_ids
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "vle01_legal_entity_members_and_identity.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vle01", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: Connection, direction: str) -> None:
    context = MigrationContext.configure(connection=connection, opts={"target_metadata": Base.metadata})
    with Operations.context(context):
        getattr(_load(), direction)()


def _columns(connection: Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(connection).get_columns(table)}


def _tables(connection: Connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


_PROJECT_COLS = (
    "id, name, description, region, classification_standard, currency, locale, validation_rule_sets, "
    "compliance_rule_packs, status, owner_id, legal_entity_id, fx_rates, custom_units, metadata, "
    "storage_uses_default, component_tax_enabled, component_tax_treatment, created_at, updated_at"
)


async def _seed_old_install(conn) -> dict[str, list[str]]:
    """Rows written as the release before the revision would: raw SQL, no new columns."""
    users = {name: str(uuid.uuid4()) for name in ("admin", "anna", "ben", "carla", "dmitri")}
    for name, uid in users.items():
        await conn.execute(
            sa.text(
                "INSERT INTO oe_users_user (id, email, hashed_password, full_name, role, locale, is_active, "
                "created_at, updated_at) VALUES (:id, :email, 'x', :name, :role, 'en', true, now(), now())"
            ),
            {
                "id": uid,
                "email": f"{name}-{uid[:6]}@example.com",
                "name": name,
                "role": "admin" if name == "admin" else "editor",
            },
        )
    entities = {code: str(uuid.uuid4()) for code in ("MAIN", "CIV")}
    for code, eid in entities.items():
        await conn.execute(
            sa.text(
                "INSERT INTO oe_legal_entities_entity (id, code, name, country_code, functional_currency, "
                "is_default, is_active, metadata, created_at, updated_at) "
                "VALUES (:id, :code, :code, 'GB', 'GBP', :d, true, '{}', now(), now())"
            ),
            {"id": eid, "code": code, "d": code == "MAIN"},
        )
    # 37 projects as in the worked example: anna owns most, ben some, a few name a company.
    projects: list[str] = []
    for i in range(37):
        pid = str(uuid.uuid4())
        owner = users["anna"] if i % 3 else users["ben"]
        entity = entities["CIV"] if i % 7 == 0 else (entities["MAIN"] if i % 5 == 0 else None)
        await conn.execute(
            sa.text(
                f"INSERT INTO oe_projects_project ({_PROJECT_COLS}) VALUES (:id, :name, '', '', 'din276', 'GBP', "
                "'en', '[]', '[]', :status, :owner, :entity, '[]', '[]', '{}', true, false, 'recoverable', "
                "now(), now())"
            ),
            {
                "id": pid,
                "name": f"Job {i}",
                "status": "archived" if i == 36 else "active",
                "owner": owner,
                "entity": entity,
            },
        )
        projects.append(pid)
    # carla is on the team of three of anna's projects.
    for pid in projects[1:4]:
        tid = str(uuid.uuid4())
        await conn.execute(
            sa.text(
                "INSERT INTO oe_teams_team (id, project_id, name, sort_order, is_default, is_active, metadata, "
                "created_at, updated_at) VALUES (:id, :p, 'Site', 0, false, true, '{}', now(), now())"
            ),
            {"id": tid, "p": pid},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO oe_teams_membership (id, team_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'member', now(), now())"
            ),
            {"id": str(uuid.uuid4()), "t": tid, "u": users["carla"]},
        )
    return {"users": list(users.values()), "admin": [users["admin"]], "projects": projects, "dmitri": [users["dmitri"]]}


async def _seen_before(conn, user_id: str, is_admin: bool) -> set[str]:
    """The rule before the revision: admins everything, others owned or on the team."""
    if is_admin:
        rows = await conn.execute(sa.text("SELECT id FROM oe_projects_project"))
    else:
        rows = await conn.execute(
            sa.text(
                "SELECT p.id FROM oe_projects_project p WHERE p.owner_id = :u OR p.id IN ("
                "SELECT t.project_id FROM oe_teams_team t JOIN oe_teams_membership m ON m.team_id = t.id "
                "WHERE m.user_id = :u)"
            ),
            {"u": user_id},
        )
    return {str(r[0]) for r in rows}


async def test_every_person_sees_after_the_upgrade_exactly_what_they_saw_before() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_run, "downgrade")
            assert "oe_legal_entities_member" not in await conn.run_sync(_tables)
            assert "legal_entity_branch_id" not in await conn.run_sync(_columns, "oe_projects_project")
            seeded = await _seed_old_install(conn)
            before = {uid: await _seen_before(conn, uid, uid in seeded["admin"]) for uid in seeded["users"]}
        assert any(before.values())

        async with engine.begin() as conn:
            await conn.run_sync(_run, "upgrade")
            assert "oe_legal_entities_member" in await conn.run_sync(_tables)
            assert {"legal_name", "address", "tax_ids", "invoice_prefix"} <= await conn.run_sync(
                _columns, "oe_legal_entities_entity"
            )
            # Running it again on an upgraded install is a no-op.
            await conn.run_sync(_run, "upgrade")

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            for uid in seeded["users"]:
                after = await accessible_project_ids(session, uid)
                if uid in seeded["admin"]:
                    assert after is None  # unfiltered, as before
                    continue
                assert {str(p) for p in after} == before[uid], f"user {uid} lost or gained projects on upgrade"

            # The first member of a company: their set only grows.
            dmitri = seeded["dmitri"][0]
            main_id = (
                await session.execute(sa.text("SELECT id FROM oe_legal_entities_entity WHERE code = 'MAIN'"))
            ).scalar_one()
            await session.execute(
                sa.text(
                    "INSERT INTO oe_legal_entities_member (id, legal_entity_id, user_id, role, created_at, updated_at)"
                    " VALUES (:id, :e, :u, 'member', now(), now())"
                ),
                {"id": str(uuid.uuid4()), "e": main_id, "u": dmitri},
            )
            grown = {str(p) for p in await accessible_project_ids(session, dmitri)}
            assert before[dmitri] <= grown
            assert len(grown) > len(before[dmitri])
            # Nobody else's view moved because of it.
            for uid in seeded["users"]:
                if uid in seeded["admin"] or uid == dmitri:
                    continue
                assert {str(p) for p in await accessible_project_ids(session, uid)} == before[uid]

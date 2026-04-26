# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for EAC v2 alias service (RFC 35 §6 EAC-2.1).

Drives the service layer (no HTTP) against an in-memory SQLite engine
so we exercise the SQLAlchemy mappings and the actual cascade rules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.eac.models  # noqa: F401 — register metadata
from app.database import Base
from app.modules.eac.aliases.schemas import (
    EacAliasSynonymCreate,
    EacParameterAliasCreate,
    EacParameterAliasUpdate,
)
from app.modules.eac.aliases.service import (
    AliasInUseError,
    create_alias,
    delete_alias,
    find_usages,
    list_aliases,
    take_snapshot,
    update_alias,
)
from app.modules.eac.models import EacRule


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Yield an isolated in-memory SQLite session per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _conn_record) -> None:  # type: ignore[no-untyped-def]
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:  # noqa: BLE001
            pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        try:
            yield sess
        finally:
            await sess.close()
    await engine.dispose()


def _alias_payload(name: str = "_TestLength") -> EacParameterAliasCreate:
    """Build a 3-synonym alias payload."""
    return EacParameterAliasCreate(
        scope="org",
        scope_id=None,
        name=name,
        description="Test alias",
        value_type_hint="number",
        default_unit="m",
        synonyms=[
            EacAliasSynonymCreate(pattern="Length", priority=10),
            EacAliasSynonymCreate(
                pattern="length_mm",
                priority=20,
                unit_multiplier=Decimal("0.001"),
            ),
            EacAliasSynonymCreate(pattern="Longueur", priority=30),
        ],
    )


# ── Create + read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_alias_with_synonyms(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    alias = await create_alias(session, _alias_payload(), tenant_id=tenant_id)

    assert alias.id is not None
    assert alias.name == "_TestLength"
    assert alias.tenant_id == tenant_id
    assert alias.is_built_in is False
    assert len(alias.synonyms) == 3
    patterns = {s.pattern for s in alias.synonyms}
    assert patterns == {"Length", "length_mm", "Longueur"}


# ── List + search ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_aliases_filters_by_scope(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()

    org_payload = _alias_payload("_OrgScopeAlias")
    org_payload.scope_id = org_id

    proj_payload = _alias_payload("_ProjScopeAlias")
    proj_payload.scope = "project"
    proj_payload.scope_id = proj_id

    await create_alias(session, org_payload, tenant_id=tenant_id)
    await create_alias(session, proj_payload, tenant_id=tenant_id)

    org_aliases = await list_aliases(session, scope="org", scope_id=org_id)
    proj_aliases = await list_aliases(session, scope="project", scope_id=proj_id)

    assert {a.name for a in org_aliases} == {"_OrgScopeAlias"}
    assert {a.name for a in proj_aliases} == {"_ProjScopeAlias"}


@pytest.mark.asyncio
async def test_list_aliases_search_by_synonym(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    payload = _alias_payload("_FindByText")
    await create_alias(session, payload, tenant_id=tenant_id)

    by_name = await list_aliases(session, q="findby")
    by_synonym = await list_aliases(session, q="length_mm")

    assert any(a.name == "_FindByText" for a in by_name)
    # Search by synonym pattern should also surface the alias.
    assert any(a.name == "_FindByText" for a in by_synonym)


# ── Update ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_alias_replaces_synonyms(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    alias = await create_alias(session, _alias_payload(), tenant_id=tenant_id)
    original_version = alias.version

    update = EacParameterAliasUpdate(
        description="updated",
        synonyms=[EacAliasSynonymCreate(pattern="OnlyOne", priority=10)],
    )
    updated = await update_alias(session, alias.id, update)

    assert updated.description == "updated"
    assert updated.version == original_version + 1
    assert len(updated.synonyms) == 1
    assert updated.synonyms[0].pattern == "OnlyOne"


# ── Delete (free) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_alias_when_unused(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    alias = await create_alias(session, _alias_payload(), tenant_id=tenant_id)

    await delete_alias(session, alias.id)

    leftover = await list_aliases(session, scope="org", scope_id=None)
    assert all(a.id != alias.id for a in leftover)


# ── Delete (in use) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_alias_blocked_by_referencing_rule(
    session: AsyncSession,
) -> None:
    tenant_id = uuid.uuid4()
    alias = await create_alias(session, _alias_payload(), tenant_id=tenant_id)

    rule = EacRule(
        name="rule-using-alias",
        output_mode="boolean",
        definition_json={
            "schema_version": "2.0",
            "name": "rule-using-alias",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Walls"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "alias", "alias_id": str(alias.id)},
                "constraint": {"operator": "exists"},
            },
        },
        tenant_id=tenant_id,
        is_active=True,
    )
    session.add(rule)
    await session.flush()

    usages = await find_usages(session, alias.id)
    assert len(usages) == 1
    assert usages[0].rule_name == "rule-using-alias"

    with pytest.raises(AliasInUseError) as excinfo:
        await delete_alias(session, alias.id)
    assert excinfo.value.alias_id == alias.id
    assert len(excinfo.value.usages) == 1


# ── Snapshot ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_take_snapshot_captures_aliases(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    org_id = uuid.uuid4()
    payload = _alias_payload("_SnapshotMe")
    payload.scope_id = org_id
    await create_alias(session, payload, tenant_id=tenant_id)

    snap = await take_snapshot(session, scope="org", scope_id=org_id)
    assert snap.id is not None
    assert "_SnapshotMe" in snap.aliases_json
    captured = snap.aliases_json["_SnapshotMe"]
    assert captured["value_type_hint"] == "number"
    assert len(captured["synonyms"]) == 3

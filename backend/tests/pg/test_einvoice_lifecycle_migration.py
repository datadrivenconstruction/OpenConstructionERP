# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision v3345 upgrades a database at the last release head (v3344) and downgrades cleanly.

The throwaway database is cloned from the model schema; the five new columns are dropped to
reproduce the v3344 shape, an old row is inserted, then the revision runs up, down, up. The
reflected result must equal what ``create_all`` builds so a fresh install and an upgraded one
cannot drift.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.einvoice_clearance.models import EInvoiceDocument, EInvoiceProfile
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
PROFILE = EInvoiceProfile.__tablename__
DOCUMENT = EInvoiceDocument.__tablename__
NEW = {PROFILE: ["mode"], DOCUMENT: ["document_kind", "previous_hash", "period"]}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v3345_einvoice_lifecycle")


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _cols(sync_conn, table: str) -> dict[str, tuple[str, bool, str | None]]:
    return {
        c["name"]: (str(c["type"]), c["nullable"], str(c.get("default")) if c.get("default") is not None else None)
        for c in sa.inspect(sync_conn).get_columns(table)
    }


def _drop_new(sync_conn) -> None:
    for table, names in NEW.items():
        for name in names:
            sync_conn.execute(sa.text(f'ALTER TABLE {table} DROP COLUMN IF EXISTS "{name}"'))


async def test_chain_is_one_revision_after_the_last_release_head() -> None:
    assert _rev.revision == "v3345_einvoice_lifecycle"
    assert _rev.down_revision == "v3344_user_secondary_calendar"
    children = [
        p.name
        for p in VERSIONS.glob("*.py")
        if re.search(r'^down_revision[^=]*=\s*"v3344_user_secondary_calendar"', p.read_text(encoding="utf-8"), re.M)
    ]
    assert children == ["v3345_einvoice_lifecycle.py"], "v3344 must have exactly one child (one head)"
    assert len(_rev.revision) <= 32


async def test_upgrade_from_v3344_keeps_old_rows_and_gives_them_export_defaults() -> None:
    async with isolated_engine() as engine:
        profile_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    f"INSERT INTO {PROFILE} (id, company_key, country, regime, platform, tax_registration_id, "
                    "network_participant_id, certificate_reference, adapter_key, sandbox, is_active, settings, notes, "
                    "created_at, updated_at) VALUES (:i, 'acme', 'MX', 'clearance', 'SAT', 'AAA010101AAA', '', '', "
                    "'reference', true, true, '{}', '', now(), now())"
                ),
                {"i": profile_id},
            )
            doc_cols = [c for c in await conn.run_sync(lambda c: _cols(c, DOCUMENT))]
            assert set(NEW[DOCUMENT]) <= set(doc_cols)
            await conn.run_sync(_drop_new)
            old = await conn.run_sync(lambda c: _cols(c, PROFILE))
            assert "mode" not in old
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            profile = await conn.run_sync(lambda c: _cols(c, PROFILE))
            document = await conn.run_sync(lambda c: _cols(c, DOCUMENT))
            row = (await conn.execute(sa.text(f"SELECT mode FROM {PROFILE} WHERE id = :i"), {"i": profile_id})).one()
        assert row.mode == ""
        for name in NEW[PROFILE]:
            assert profile[name][1] is False  # NOT NULL
        for name in NEW[DOCUMENT]:
            assert document[name][1] is False


async def test_new_document_columns_default_for_inserts_that_omit_them() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_drop_new)
            await conn.run_sync(_run, _rev.upgrade)
            defaults = {
                r.column_name: r.column_default
                for r in (
                    await conn.execute(
                        sa.text(
                            "SELECT column_name, column_default FROM information_schema.columns "
                            "WHERE table_name = :t AND column_name IN ('document_kind','previous_hash','period')"
                        ),
                        {"t": DOCUMENT},
                    )
                ).all()
            }
        assert "standard" in defaults["document_kind"]
        assert defaults["previous_hash"] is not None
        assert defaults["period"] is not None


async def test_upgrade_twice_is_a_no_op_and_down_up_round_trips() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = {t: await conn.run_sync(lambda c, t=t: _cols(c, t)) for t in (PROFILE, DOCUMENT)}
            await conn.run_sync(_drop_new)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            await conn.run_sync(_run, _rev.upgrade)  # idempotent
            first = {t: await conn.run_sync(lambda c, t=t: _cols(c, t)) for t in (PROFILE, DOCUMENT)}
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.downgrade)
            down = {t: await conn.run_sync(lambda c, t=t: _cols(c, t)) for t in (PROFILE, DOCUMENT)}
            await conn.run_sync(_run, _rev.downgrade)  # idempotent too
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            second = {t: await conn.run_sync(lambda c, t=t: _cols(c, t)) for t in (PROFILE, DOCUMENT)}
        for table, names in NEW.items():
            for name in names:
                assert name in first[table]
                assert name not in down[table]
            # nothing else was touched by the downgrade
            assert set(down[table]) == set(from_models[table]) - set(names)
        assert first == second
        # the upgraded schema agrees with a fresh install on name, type and nullability
        for table in from_models:
            assert {k: v[:2] for k, v in first[table].items()} == {k: v[:2] for k, v in from_models[table].items()}


async def test_upgrade_on_a_database_without_the_tables_is_a_no_op() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP TABLE IF EXISTS oe_einvoice_clearance_event CASCADE"))
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {DOCUMENT} CASCADE"))
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {PROFILE} CASCADE"))
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            await conn.run_sync(_run, _rev.downgrade)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v75 builds exactly the schema the quality concept models build, and undoes it.

The revision writes every column out and never reads the models, so the two can
drift; this is the test that catches it. The throwaway database starts with the
schema ``create_all`` built from the models. The revision is run down (tables
and link columns gone), then up from its own DDL, and the reflected result is
compared with the models' schema: columns with type and nullability, unique
constraints, foreign keys with their delete rule, and the declared indexes.

The seven link columns on existing tables are checked the same way, because an
installed database only ever receives them through this revision.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.quality_concept import models as qm
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

_MODELS = (
    qm.QualityConcept,
    qm.QualityConceptRevision,
    qm.AppliedStandard,
    qm.CertificationTarget,
    qm.CreditTarget,
    qm.ProofRequirement,
    qm.EvidenceLink,
    qm.CommissioningStageDef,
    qm.StageProgress,
    qm.AcceptanceUnit,
    qm.AcceptanceEffect,
    qm.PreservationSurvey,
    qm.ExpertReportPlan,
)
TABLES = [m.__tablename__ for m in _MODELS]
# Indexes the models declare. ``create_all`` adds performance indexes on top
# (``app.core.pg_optimizations``) that no revision reproduces, so only these are compared.
DECLARED_INDEXES = {m.__tablename__: {i.name for i in m.__table__.indexes} for m in _MODELS}


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rev = _load("v75_quality_concept")
COLUMNS = [(t, c) for t, c, _ in _rev._COLUMNS]


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _reflect(sync_conn) -> dict:
    inspector = sa.inspect(sync_conn)
    tables = set(inspector.get_table_names())
    out: dict = {"tables": tables, "links": {}}
    for table, column in COLUMNS:
        if table in tables:
            found = {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)}
            if column in found:
                out["links"][(table, column)] = found[column]
    for table in TABLES:
        if table not in tables:
            continue
        out[table] = {
            "columns": {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)},
            "indexes": {i["name"] for i in inspector.get_indexes(table)} & DECLARED_INDEXES[table],
            "unique": {
                (u["name"], tuple(u["column_names"])) for u in inspector.get_unique_constraints(table) if u.get("name")
            },
            "fks": {
                (
                    f["name"],
                    tuple(f["constrained_columns"]),
                    f["referred_table"],
                    (f.get("options") or {}).get("ondelete"),
                )
                for f in inspector.get_foreign_keys(table)
            },
        }
    return out


def test_the_revision_does_not_read_the_models() -> None:
    source = Path(_rev.__file__).read_text(encoding="utf-8")
    assert "app.modules" not in source
    assert "__table__" not in source


def test_the_revision_lists_every_model_table() -> None:
    assert [name for name, _create in _rev._TABLES] == TABLES


async def test_revision_reproduces_the_model_schema_down_and_up() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            from_models = await conn.run_sync(_reflect)
        assert set(TABLES) <= from_models["tables"]
        assert set(from_models["links"]) == set(COLUMNS)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.downgrade)
            down = await conn.run_sync(_reflect)
        async with engine.begin() as conn:
            await conn.run_sync(_run, _rev.upgrade)
            up = await conn.run_sync(_reflect)

    assert not set(TABLES) & down["tables"]
    assert down["links"] == {}
    assert up["links"] == from_models["links"]
    for table in TABLES:
        assert from_models[table]["indexes"] == DECLARED_INDEXES[table], table
        for key in ("columns", "indexes", "unique", "fks"):
            assert up[table][key] == from_models[table][key], (table, key)


async def test_revision_is_a_no_op_over_a_create_all_schema() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            before = await conn.run_sync(_reflect)
            await conn.run_sync(_run, _rev.upgrade)
            after = await conn.run_sync(_reflect)
    assert after == before

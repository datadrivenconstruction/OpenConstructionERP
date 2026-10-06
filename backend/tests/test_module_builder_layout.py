# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Installing over a kept table: what the plan adds, what it refuses.

The tables here are made from the real generated model, on SQLite in memory,
and the planner's own idea of the table is compared with that model column by
column for both dialects. The same behaviour on PostgreSQL, through a real
install, is in ``tests/pg/test_module_builder_v2_hardening.py``.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.dialects import postgresql, sqlite

from app.modules.module_builder import generator, layout, router, service
from app.modules.module_builder.links import LINK_TARGETS
from app.modules.module_builder.spec import ModuleSpec

ALL_TYPES = [
    {"name": "ref", "label": "Ref", "type": "text", "required": True},
    {"name": "notes", "label": "Notes", "type": "long_text"},
    {"name": "count", "label": "Count", "type": "integer"},
    {"name": "qty", "label": "Qty", "type": "number"},
    {"name": "amount", "label": "Amount", "type": "money"},
    {"name": "on_day", "label": "Day", "type": "date"},
    {"name": "at_time", "label": "Time", "type": "datetime"},
    {"name": "ok", "label": "OK", "type": "boolean"},
    {"name": "kind", "label": "Kind", "type": "select", "options": ["a", "b"]},
]
CONTRACT = {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}
STATUS = {"states": [{"code": "open", "label": "Open"}, {"code": "closed", "label": "Closed", "done": True}]}


def _spec(fields: list[dict], features: dict | None = None, *, scoped: bool = True) -> ModuleSpec:
    return ModuleSpec.model_validate(
        {
            "key": "layout_log",
            "display_name": "Layout log",
            "schema_version": 2,
            "entity": {"name": "item", "display_name": "Item", "project_scoped": scoped, "fields": fields},
            "rules": [{"code": "REF_REQUIRED", "message": "Needs a ref.", "kind": "required", "field": "ref"}],
            "features": features or {},
        }
    )


@contextmanager
def generated_table(spec: ModuleSpec, root: Path) -> Iterator[Table]:
    """The table the generated model declares, copied onto a private MetaData."""
    from app.core import module_runtime_root as rr
    from app.database import Base

    directory = root / f"r{len(list(root.iterdir())) if root.exists() else 0}"
    directory.mkdir(parents=True)
    generator.write(spec, directory)
    before = list(rr._package_path())
    rr.attach_runtime_root(directory)
    importlib.invalidate_caches()
    try:
        model = getattr(importlib.import_module(f"app.modules.{spec.key}.models"), spec.class_name)
        private = MetaData()
        for table in {"oe_projects_project", *(t.table for t in LINK_TARGETS.values())}:
            Table(table, private, Column("id", String(36), primary_key=True))
        yield model.__table__.to_metadata(private)
    finally:
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{spec.key}")]:
            del sys.modules[name]
        existing = Base.metadata.tables.get(spec.table_name)
        if existing is not None:
            Base.metadata.remove(existing)
        Base.registry._class_registry.pop(spec.class_name, None)
        importlib.invalidate_caches()


@pytest.fixture
def engine():
    database = create_engine("sqlite://")
    try:
        yield database
    finally:
        database.dispose()


def _make(engine: Any, table: Table, rows: int = 0) -> None:
    table.create(engine)
    with engine.begin() as connection:
        for n in range(rows):
            values: dict[str, Any] = {"id": f"00000000-0000-0000-0000-{n:012d}", "ref": f"R-{n}"}
            if "project_id" in table.c:
                values["project_id"] = "11111111-1111-1111-1111-111111111111"
            connection.execute(table.insert().values(**values))


def _prepare(engine: Any, spec: ModuleSpec) -> layout.Plan:
    with engine.begin() as connection:
        return layout.prepare(connection, spec)


def _columns(engine: Any, name: str) -> dict[str, dict]:
    return {c["name"]: c for c in inspect(engine).get_columns(name)}


class TestThePlannerKnowsTheGeneratedTable:
    """Its own list of columns would drift from the generator unnoticed; this pins it to the model."""

    @pytest.mark.parametrize("scoped", [True, False])
    def test_columns_and_indexes_match_the_model(self, tmp_path: Path, scoped: bool) -> None:
        spec = _spec([*ALL_TYPES, CONTRACT], {"status": STATUS}, scoped=scoped)
        with generated_table(spec, tmp_path) as table:
            expected = layout.expected_columns(spec)
            assert [c.name for c in expected] == [c.name for c in table.columns]
            for column in expected:
                real = table.c[column.name]
                for dialect in (postgresql.dialect(), sqlite.dialect()):
                    assert layout._ddl(column.type, dialect) == layout._ddl(real.type, dialect), column.name
                assert column.nullable == real.nullable, column.name
                targets = {fk.column.table.name for fk in real.foreign_keys}
                assert targets == ({column.references} if column.references else set()), column.name
                if column.name in {"status", "created_at", "updated_at"}:
                    assert real.server_default is not None and column.default is not None
            declared = {(ix.name, tuple(c.name for c in ix.columns)) for ix in table.indexes}
            assert declared == {(name, (column,)) for name, column in layout.expected_indexes(spec)}


class TestReinstallingOverAKeptTable:
    def test_the_same_spec_changes_nothing(self, engine, tmp_path: Path) -> None:
        """The control: without it, a planner that always refuses passes every test below."""
        spec = _spec([*ALL_TYPES, CONTRACT], {"status": STATUS})
        with generated_table(spec, tmp_path) as table:
            _make(engine, table, rows=2)
        plan = _prepare(engine, spec)
        assert plan.exists and plan.records == 2
        assert (plan.add, plan.relax, plan.indexes, plan.problems) == ([], [], [], [])

    def test_a_link_and_status_are_added_to_the_records_there(self, engine, tmp_path: Path) -> None:
        before, after = _spec(ALL_TYPES), _spec([*ALL_TYPES, CONTRACT], {"status": STATUS})
        with generated_table(before, tmp_path) as table:
            _make(engine, table, rows=2)
        plan = _prepare(engine, after)
        assert [c.name for c in plan.add] == ["contract", "status"]
        assert plan.problems == []
        columns = _columns(engine, after.table_name)
        assert columns["contract"]["nullable"] and not columns["status"]["nullable"]
        with engine.connect() as connection:
            assert connection.execute(text(f"SELECT DISTINCT status FROM {after.table_name}")).scalars().all() == [
                "open"
            ]
        indexes = {ix["name"] for ix in inspect(engine).get_indexes(after.table_name)}
        assert {f"ix_{after.table_name}_contract", f"ix_{after.table_name}_status"} <= indexes
        fks = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys(after.table_name)}
        assert LINK_TARGETS["contract"].table in fks
        # And the next install of the same spec finds nothing left to do.
        again = _prepare(engine, after)
        assert (again.add, again.indexes, again.problems) == ([], [], [])

    @pytest.mark.parametrize(
        ("change", "kind"),
        [
            ("removed", layout.REMOVED),
            ("retyped", layout.CHANGED),
            ("new_required", layout.NEW_REQUIRED),
            ("relinked", layout.CHANGED),
        ],
    )
    def test_what_would_lose_records_is_refused_and_nothing_changes(
        self, engine, tmp_path: Path, change: str, kind: str
    ) -> None:
        before = _spec([*ALL_TYPES, CONTRACT])
        fields = [dict(f) for f in [*ALL_TYPES, CONTRACT]]
        if change == "removed":
            fields = [f for f in fields if f["name"] != "notes"]
        elif change == "retyped":
            next(f for f in fields if f["name"] == "count")["type"] = "text"
        elif change == "new_required":
            fields.append({"name": "batch", "label": "Batch", "type": "text", "required": True})
        else:
            next(f for f in fields if f["name"] == "contract")["target"] = "contact"
        after = _spec(fields)
        with generated_table(before, tmp_path) as table:
            _make(engine, table, rows=3)
        shape = _columns(engine, before.table_name)

        with pytest.raises(layout.LayoutConflict) as refused:
            _prepare(engine, after)

        params = refused.value.params
        assert params["records"] == 3
        assert [p["problem"] for p in params["fields"]] == [kind]
        assert "This register already holds 3 records saved with a different layout" in str(refused.value)
        assert _columns(engine, before.table_name).keys() == shape.keys()
        with engine.connect() as connection:
            assert connection.execute(text(f"SELECT count(*) FROM {before.table_name}")).scalar_one() == 3

    def test_a_field_made_required_is_refused_only_while_records_leave_it_empty(self, engine, tmp_path: Path) -> None:
        before = _spec(ALL_TYPES)
        fields = [dict(f) for f in ALL_TYPES]
        next(f for f in fields if f["name"] == "count")["required"] = True
        after = _spec(fields)
        with generated_table(before, tmp_path) as table:
            _make(engine, table, rows=2)
        with pytest.raises(layout.LayoutConflict) as refused:
            _prepare(engine, after)
        assert refused.value.params["fields"] == [
            {"name": "count", "label": "Count", "problem": layout.NOW_REQUIRED, "empty": 2}
        ]
        with engine.begin() as connection:
            connection.execute(text(f"UPDATE {before.table_name} SET count = 1"))
        assert _prepare(engine, after).problems == []

    def test_an_empty_table_that_differs_is_made_again(self, engine, tmp_path: Path) -> None:
        before = _spec(ALL_TYPES)
        after = _spec([f for f in ALL_TYPES if f["name"] != "notes"])
        with generated_table(before, tmp_path) as table:
            _make(engine, table, rows=0)
        plan = _prepare(engine, after)
        assert plan.recreate
        assert not inspect(engine).has_table(after.table_name)

    def test_no_table_is_nothing_to_do(self, engine) -> None:
        plan = _prepare(engine, _spec(ALL_TYPES))
        assert not plan.exists and not plan.changes


class TestTheRefusalReachesTheScreen:
    async def _install(self, monkeypatch, refusal: service.InstallRefused) -> HTTPException:
        async def refuse(spec: Any, app: Any) -> Any:
            raise refusal

        monkeypatch.setattr(service, "install", refuse)
        monkeypatch.setattr(router.review_token, "verify", lambda *args: None)
        payload = SimpleNamespace(spec=_spec(ALL_TYPES), review_token="t")
        with pytest.raises(HTTPException) as raised:
            await router.install(payload, SimpleNamespace(app=None), "user")
        return raised.value

    async def test_a_layout_conflict_carries_its_code_and_params(self, monkeypatch) -> None:
        refusal = service.InstallRefused(
            "This register already holds 3 records ...", code=layout.LAYOUT_CONFLICT, params={"records": 3}
        )
        raised = await self._install(monkeypatch, refusal)
        assert raised.status_code == 409
        assert raised.detail == {
            "code": "layout_conflict",
            "message": "This register already holds 3 records ...",
            "params": {"records": 3},
        }

    async def test_other_refusals_keep_a_plain_string(self, monkeypatch) -> None:
        raised = await self._install(monkeypatch, service.InstallRefused("A module called 'x' is already installed."))
        assert raised.status_code == 409
        assert raised.detail == "A module called 'x' is already installed."

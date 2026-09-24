# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A heal statement the database refuses is collected, named and handed back as SQL.

The boot-time heal (``postgres_auto_migrate``) wraps every statement in its own
SAVEPOINT and catches whatever it raises, so one refusal cannot stop the rest.
That is the right shape, and it had one consequence nobody wrote down: a role
that may read and write rows but may not change the schema has every statement
refused one by one, the heal itself never raises, and the call site records
``schema_heal_failed: false``. Measured on a 17.8.3 database booted by 18.0 under
such a role: six WARNING lines in the boot log (``must be owner of table``), an
install reporting ``status: healthy`` and ``schema_matches_models: true``, and
every read of a progress claim answering 500 on the column that was never added.
The owner running the one ALTER, with no restart, turned all of them into 200.

So the refusals are now collected, the heal ends with a single ERROR line that
names them and carries the exact statements an owner has to run, and the
application records the list. ``/api/health`` publishes that the heal is
incomplete and how many statements it skipped, and nothing else: it is
unauthenticated, so it carries no table or column name, and it does not move
``status``, because the VPS watchdog reads that endpoint and a status that
changed under this condition would restart a server a restart cannot fix. The
names and the SQL go to the boot log and to the admin-only upgrade status.

The heal's collector is driven here against a fake connection whose DDL is
refused the way a real one is, rather than against a live cluster with a
restricted role, because the question is what the heal does with a refusal and
not whether PostgreSQL refuses: that was measured on the live drive above.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.exc import ProgrammingError

if TYPE_CHECKING:
    from fastapi import FastAPI

_TABLE = "oe_contracts_progress_claim"

#: The statement the 18.0 release needs on every 17.8.3 database, and the one an
#: owner is told to run. Same text the heal issues, terminated for pasting.
_GROSS_BASIS_SQL = f'ALTER TABLE "{_TABLE}" ADD COLUMN IF NOT EXISTS "gross_basis" VARCHAR(10);'
_INDEX_SQL = f'CREATE INDEX IF NOT EXISTS "ix_claim_status" ON "{_TABLE}" ("status");'
_RELAX_SQL = f'ALTER TABLE "{_TABLE}" ALTER COLUMN "note" DROP NOT NULL;'
_CHECK_SQL = (
    f"ALTER TABLE \"{_TABLE}\" ADD CONSTRAINT ck_claim_basis CHECK (gross_basis IN ('net', 'gross')) NOT VALID;"
)


def _model() -> SimpleNamespace:
    """A claim table with one of each statement kind the heal can be refused.

    A missing column (the 18.0 case), a missing index, a column the models now
    declare optional while the database still holds NOT NULL, and a missing
    check constraint, which goes through the heal's shared DDL runner rather than
    its own code path.
    """
    metadata = MetaData()
    Table(
        _TABLE,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("status", String(20), nullable=False),
        Column("note", String(50), nullable=True),
        Column("gross_basis", String(10), nullable=True),
        Index("ix_claim_status", "status"),
        CheckConstraint("gross_basis IN ('net', 'gross')", name="ck_claim_basis"),
    )
    return SimpleNamespace(metadata=metadata)


def _refusal(statement: str) -> ProgrammingError:
    """What a role without DDL rights gets back, built the way the driver stack builds it.

    asyncpg raises ``InsufficientPrivilegeError`` (sqlstate 42501). SQLAlchemy's
    asyncpg adapter re-raises it as its own ``ProgrammingError`` whose text is
    ``"<class ...>: message"``, carrying the sqlstate, ``from`` the driver error.
    The engine then wraps that in ``sqlalchemy.exc.ProgrammingError``, whose text
    runs over several lines with the statement and a documentation link. The live
    boot logged exactly this chain: ``(sqlalchemy.dialects.postgresql.asyncpg.
    ProgrammingError) <class 'asyncpg.exceptions.InsufficientPrivilegeError'>:
    must be owner of table oe_bim_quantity_map``.
    """
    import asyncpg

    driver = asyncpg.exceptions.PostgresError.new({"C": "42501", "M": f"must be owner of table {_TABLE}", "S": "ERROR"})
    adapted = AsyncAdapt_asyncpg_dbapi.ProgrammingError(f"{type(driver)}: {driver}")
    adapted.pgcode = adapted.sqlstate = driver.sqlstate
    adapted.__cause__ = driver
    wrapped = ProgrammingError(statement, None, adapted)
    wrapped.__cause__ = adapted
    return wrapped


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class _Savepoint:
    """``begin_nested()``: must let the statement's exception out, as the real one does.

    A savepoint that swallowed it would make every refused statement count as
    applied, and the test would pass while proving nothing.
    """

    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _Connection:
    def __init__(self, *, refuse_ddl: bool) -> None:
        self.refuse_ddl = refuse_ddl
        self.executed: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        self.executed.append(sql)
        if "pg_try_advisory_xact_lock" in sql:
            return _Result(True)
        if self.refuse_ddl and sql.startswith(("ALTER TABLE", "CREATE ")):
            raise _refusal(sql)
        return _Result(None)

    async def run_sync(self, fn: Any) -> Any:
        # Every inspector call goes through the patched ``inspect`` below, so
        # the synchronous connection handed to it is never looked at.
        return fn(object())

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()


class _Transaction:
    def __init__(self, conn: _Connection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Connection:
        return self._conn

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _Engine:
    dialect = postgresql.dialect()

    def __init__(self, conn: _Connection) -> None:
        self._conn = conn

    def begin(self) -> _Transaction:
        return _Transaction(self._conn)


class _Inspector:
    """The live schema of a database built before ``gross_basis`` existed."""

    def get_table_names(self) -> list[str]:
        return [_TABLE]

    def get_columns(self, table: str) -> list[dict[str, Any]]:
        return [
            {"name": "id", "nullable": False},
            {"name": "status", "nullable": False},
            {"name": "note", "nullable": False},
        ]

    def get_pk_constraint(self, table: str) -> dict[str, Any]:
        return {"constrained_columns": ["id"]}

    def get_indexes(self, table: str) -> list[dict[str, Any]]:
        return []

    def get_unique_constraints(self, table: str) -> list[dict[str, Any]]:
        return []

    def get_check_constraints(self, table: str) -> list[dict[str, Any]]:
        return []

    def get_foreign_keys(self, table: str) -> list[dict[str, Any]]:
        return []

    def get_sequence_names(self, schema: str | None = None) -> list[str]:
        return []


@pytest.fixture
def fake_inspector(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import postgres_migrator

    monkeypatch.setattr(postgres_migrator, "inspect", lambda _conn: _Inspector())


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.core.postgres_migrator" and r.levelno >= logging.ERROR]


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector")
async def test_every_refused_statement_is_collected_with_its_table_reason_and_sql(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.postgres_migrator import heal_is_incomplete, postgres_auto_migrate

    skipped: list = []
    with caplog.at_level(logging.INFO, logger="app.core.postgres_migrator"):
        repaired = await postgres_auto_migrate(_Engine(_Connection(refuse_ddl=True)), _model(), skipped=skipped)

    assert repaired == 0
    assert [(s.kind, s.table, s.name) for s in skipped] == [
        ("not_null", _TABLE, "note"),
        ("column", _TABLE, "gross_basis"),
        ("index", _TABLE, "ix_claim_status"),
        ("check", _TABLE, "ck_claim_basis"),
    ]
    for s in skipped:
        assert s.sqlstate == "42501"
        assert s.reason == f"must be owner of table {_TABLE}"
        assert s.error == "InsufficientPrivilegeError"
    assert [s.as_dict()["sql"] for s in skipped] == [_RELAX_SQL, _GROSS_BASIS_SQL, _INDEX_SQL, _CHECK_SQL]

    # The flag the application records from this list.
    assert heal_is_incomplete(skipped, raised=False) is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector")
async def test_the_heal_ends_with_one_error_line_carrying_the_owner_sql(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.postgres_migrator import postgres_auto_migrate

    with caplog.at_level(logging.INFO, logger="app.core.postgres_migrator"):
        # No list passed: the line must still be written, because ``init-db``
        # calls the heal without one and its operator needs the SQL as much.
        await postgres_auto_migrate(_Engine(_Connection(refuse_ddl=True)), _model())

    errors = _errors(caplog)
    assert len(errors) == 1, [r.getMessage() for r in errors]
    line = errors[0].getMessage()
    assert "\n" not in line, "the owner SQL must survive a log shipper that splits on newlines"
    for sql in (_GROSS_BASIS_SQL, _INDEX_SQL, _RELAX_SQL, _CHECK_SQL):
        assert sql in line
    assert f"column {_TABLE}.gross_basis" in line
    assert "must be owner" in line
    # The owner runs them in the order the heal tried them, which is the order
    # they depend on each other in: sequences, columns, indexes, constraints.
    assert line.index(_GROSS_BASIS_SQL) < line.index(_INDEX_SQL) < line.index(_CHECK_SQL)
    # Nothing of the multi-line SQLAlchemy text reaches it.
    assert "[SQL:" not in line
    assert "Background on this error" not in line


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector")
async def test_a_heal_the_database_accepts_collects_nothing_and_logs_no_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The twin, so the list above is known to come from the refusals."""
    from app.core.postgres_migrator import heal_is_incomplete, postgres_auto_migrate

    conn = _Connection(refuse_ddl=False)
    skipped: list = []
    with caplog.at_level(logging.INFO, logger="app.core.postgres_migrator"):
        repaired = await postgres_auto_migrate(_Engine(conn), _model(), skipped=skipped)

    assert repaired == 4
    assert skipped == []
    assert _errors(caplog) == []
    assert _GROSS_BASIS_SQL.rstrip(";") in conn.executed
    assert heal_is_incomplete(skipped, raised=False) is False


def test_a_heal_that_raised_is_incomplete_whatever_it_collected() -> None:
    from app.core.postgres_migrator import heal_is_incomplete

    assert heal_is_incomplete([], raised=True) is True


def test_the_local_table_speaks_for_the_real_claim_column() -> None:
    """The SQL asserted above is the real 18.0 statement, not one this file made up."""
    from app.modules.contracts.models import ProgressClaim

    table = ProgressClaim.__table__
    assert table.name == _TABLE
    column = table.c.gross_basis
    assert column.nullable is True
    assert column.server_default is None
    assert column.type.compile(dialect=postgresql.dialect()) == "VARCHAR(10)"


# ── What the application publishes about it ─────────────────────────────────


def _fresh_app() -> FastAPI:
    """An application whose startup never ran, so the state below is what it serves."""
    from app.main import create_app

    return create_app()


def _refused_statements(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Real records from the heal, not hand-written stand-ins.

    Run on a loop of its own so the tests below stay synchronous, like the other
    health tests: the fake engine never touches a database, and the test client
    that follows runs its own loop.
    """
    import asyncio

    from app.core import postgres_migrator

    monkeypatch.setattr(postgres_migrator, "inspect", lambda _conn: _Inspector())
    skipped: list = []
    asyncio.run(
        postgres_migrator.postgres_auto_migrate(_Engine(_Connection(refuse_ddl=True)), _model(), skipped=skipped)
    )
    return tuple(skipped)


def _health_text(app: FastAPI) -> tuple[dict, str]:
    from fastapi.testclient import TestClient

    # Not the context-manager form, which would run the lifespan and replace
    # the state under test.
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    return response.json(), response.text


def test_health_says_the_heal_is_incomplete_and_how_much_without_moving_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = _refused_statements(monkeypatch)

    clean = _fresh_app()
    clean.state.schema_heal_failed = False
    clean.state.schema_heal_incomplete = False
    clean.state.schema_heal_skipped = ()
    clean_payload, _ = _health_text(clean)

    app = _fresh_app()
    app.state.schema_heal_failed = False
    app.state.schema_heal_incomplete = True
    app.state.schema_heal_skipped = refused
    payload, _ = _health_text(app)

    assert payload["schema_heal_incomplete"] is True
    assert payload["schema_heal_skipped_count"] == len(refused) == 4
    assert clean_payload["schema_heal_incomplete"] is False
    assert clean_payload["schema_heal_skipped_count"] == 0
    # Liveness is untouched: the watchdog reads this endpoint, and nothing a
    # restart does can give this role the right to change the schema.
    assert payload["status"] == clean_payload["status"]
    assert payload["schema_heal_failed"] is False


def test_health_reports_unknown_where_the_heal_never_ran() -> None:
    payload, _ = _health_text(_fresh_app())

    assert payload["schema_heal_incomplete"] is None
    assert payload["schema_heal_skipped_count"] is None


def test_anonymous_health_carries_no_name_from_the_refused_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counts and verdicts only. The endpoint answers anybody who can reach the port."""
    refused = _refused_statements(monkeypatch)
    app = _fresh_app()
    app.state.schema_heal_failed = False
    app.state.schema_heal_incomplete = True
    app.state.schema_heal_skipped = refused

    payload, body = _health_text(app)

    assert payload["schema_heal_incomplete"] is True
    for fragment in (
        _TABLE,
        "gross_basis",
        "ix_claim_status",
        "ck_claim_basis",
        "ALTER TABLE",
        "CREATE INDEX",
        "42501",
        "must be owner",
        "InsufficientPrivilege",
    ):
        assert fragment not in body, f"the public health payload publishes {fragment!r}"


def test_the_admin_upgrade_status_lists_what_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    refused = _refused_statements(monkeypatch)
    app = _fresh_app()
    app.state.schema_heal_incomplete = True
    app.state.schema_heal_skipped = refused

    # Called directly: the route is a closure over this app, and what is under
    # test is what it returns once the admin check has let the caller through.
    handler = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/system/upgrade/status" and "GET" in getattr(route, "methods", ())
    )
    body = asyncio.run(handler())

    assert body["status"] == "idle"
    assert body["schema_heal_incomplete"] is True
    listed = body["schema_heal_skipped"]
    assert [item["sql"] for item in listed] == [_RELAX_SQL, _GROSS_BASIS_SQL, _INDEX_SQL, _CHECK_SQL]
    assert listed[1] == {
        "kind": "column",
        "table": _TABLE,
        "name": "gross_basis",
        "sql": _GROSS_BASIS_SQL,
        "error": "InsufficientPrivilegeError",
        "reason": f"must be owner of table {_TABLE}",
        "sqlstate": "42501",
    }


def test_the_admin_upgrade_status_still_refuses_an_anonymous_caller() -> None:
    from fastapi.testclient import TestClient

    response = TestClient(_fresh_app()).get("/api/system/upgrade/status")

    assert response.status_code in (401, 403)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The SQL view generator and the ``bi`` command line without a database."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from app.cli import _build_parser
from app.modules.bi_feed import sqlview
from app.modules.bi_feed.feeds import FEEDS, build_catalogue


class _FakeConn:
    """Just enough of a Connection to reach the guards in front of any DDL."""

    def __init__(self, dialect: str, version_num: int = 160000) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.version_num = version_num
        self.statements: list[str] = []

    def execute(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        self.statements.append(sql)
        return SimpleNamespace(scalar=lambda: self.version_num if "server_version_num" in sql else None)


def test_view_columns_are_the_feed_columns_in_order() -> None:
    for feed in build_catalogue().values():
        sql = sqlview.view_sql(feed)
        aliases = re.findall(r" AS (\w+)(?:,|\s*\nFROM|\s+FROM)", sql)
        assert aliases == [c.name for c in feed.columns], feed.id


def test_view_sql_has_no_bound_parameters_and_casts_numbers_safely() -> None:
    sql = sqlview.view_sql(build_catalogue()["boq_positions"])
    assert "%(" not in sql and "$1" not in sql
    assert "NUMERIC(38, 6)" in sql and "CASE WHEN" in sql


def test_grants_cover_exactly_the_columns_the_view_reads() -> None:
    grants = sqlview.base_columns(build_catalogue()["boq_positions"])
    assert set(grants) == {"oe_boq_position", "oe_boq_boq", "oe_projects_project"}
    assert grants["oe_projects_project"] == ["currency", "id"]
    assert "hashed_password" not in {c for cols in grants.values() for c in cols}


def test_no_grant_ever_touches_the_user_tables() -> None:
    for feed in build_catalogue().values():
        assert not [t for t in sqlview.base_columns(feed) if t.startswith("oe_users_")], feed.id


def test_enable_needs_postgres() -> None:
    with pytest.raises(sqlview.BiSqlError) as info:
        sqlview.enable(_FakeConn("sqlite"))  # type: ignore[arg-type]
    assert info.value.code == "BI_NEEDS_POSTGRES"


def test_enable_refuses_an_old_server() -> None:
    conn = _FakeConn("postgresql", 140000)
    with pytest.raises(sqlview.BiSqlError) as info:
        sqlview.enable(conn)  # type: ignore[arg-type]
    assert info.value.code == "BI_PG_TOO_OLD"
    assert not any("CREATE" in s for s in conn.statements)


def test_enable_refuses_without_row_level_security_and_changes_nothing() -> None:
    conn = _FakeConn("postgresql")
    with pytest.raises(sqlview.BiSqlError) as info:
        sqlview.enable(conn, single_tenant=False)  # type: ignore[arg-type]
    assert info.value.code == "BI_RLS_REQUIRED"
    assert not any("CREATE" in s for s in conn.statements)


def test_rls_alone_is_not_enough_while_feed_tables_have_no_tenant_column(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.rls.rls_enabled", lambda: True)
    assert sqlview.tenant_isolation_ready(build_catalogue()) is False


def test_status_on_a_non_postgres_database_is_disabled() -> None:
    assert sqlview.status(_FakeConn("sqlite"))["enabled"] is False  # type: ignore[arg-type]


def test_command_line_declares_bi_actions() -> None:
    parser = _build_parser()
    assert parser.parse_args(["bi", "enable", "--single-tenant"]).single_tenant is True
    assert parser.parse_args(["bi", "enable"]).single_tenant is False
    assert parser.parse_args(["bi", "disable"]).bi_action == "disable"
    assert parser.parse_args(["bi", "status"]).bi_action == "status"


def test_feed_ids_are_valid_postgres_identifiers() -> None:
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", feed_id) for feed_id in FEEDS)

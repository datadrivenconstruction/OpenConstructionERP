# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Opt-in PostgreSQL schema ``oe_bi``: one view per feed and a read-only login role.

Created by the CLI (``bi enable``), never by a migration, so it is off by
default and cannot interfere with an upgrade. Every view is generated from the
same :class:`~app.modules.bi_feed.feeds.ResolvedFeed` as the file feeds, so the
column names are identical. The views are ``security_invoker``: the reader's own
privileges apply to the base tables, and the reader is granted SELECT on exactly
the columns the views use and nothing else.

The role password is returned to the caller once and is never stored or logged.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Column, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.sql import visitors

from app.modules.bi_feed.feeds import SQL_ROLE, SQL_SCHEMA, ResolvedFeed, build_catalogue

logger = logging.getLogger(__name__)

MIN_PG_VERSION_NUM = 150000  # security_invoker views
TENANT_COLUMN = "tenant_id"


class BiSqlError(Exception):
    """The SQL schema cannot be changed; ``code`` is stable for scripts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EnableResult:
    """What ``bi enable`` did. ``password`` is set only when the role was created in this run."""

    views: list[str] = field(default_factory=list)
    role_created: bool = False
    password: str | None = None
    warnings: list[str] = field(default_factory=list)


def _q(identifier: str) -> str:
    """Quote an identifier. Only names from the allow-list and the model metadata reach here."""
    return '"' + identifier.replace('"', '""') + '"'


def view_sql(feed: ResolvedFeed) -> str:
    """The SELECT behind ``oe_bi.<feed id>``, rendered for PostgreSQL."""
    return str(feed.select().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def base_columns(feed: ResolvedFeed) -> dict[str, list[str]]:
    """``{table: [columns]}`` the feed's view reads, joins included."""
    used: dict[str, set[str]] = {}
    for element in visitors.iterate(feed.select()):
        table = getattr(element, "table", None)
        if isinstance(element, Column) and table is not None and getattr(table, "name", None):
            used.setdefault(table.name, set()).add(element.name)
    return {table: sorted(columns) for table, columns in used.items()}


def tenant_isolation_ready(catalogue: dict[str, ResolvedFeed]) -> bool:
    """True when row-level security is on and every feed's base tables carry a tenant column."""
    from app.core.rls import rls_enabled

    if not rls_enabled():
        return False
    return all(
        TENANT_COLUMN in {c.name for c in feed.entity.__table__.columns}
        and all(TENANT_COLUMN in {c.name for c in m.__table__.columns} for m in feed.joined.values())
        for feed in catalogue.values()
    )


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar()


def _require_postgres(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        raise BiSqlError("BI_NEEDS_POSTGRES", "needs PostgreSQL")


def enable(conn: Connection, *, single_tenant: bool = False) -> EnableResult:
    """Create the schema, views and reader role in the caller's transaction. Idempotent."""
    _require_postgres(conn)
    if int(_scalar(conn, "SHOW server_version_num")) < MIN_PG_VERSION_NUM:
        raise BiSqlError("BI_PG_TOO_OLD", "SQL access needs PostgreSQL 15 or newer (security_invoker views)")
    catalogue = build_catalogue()
    if not single_tenant and not tenant_isolation_ready(catalogue):
        raise BiSqlError(
            "BI_RLS_REQUIRED",
            "Row-level security does not cover every feed table. Pass --single-tenant only if this "
            "instance serves one organisation.",
        )
    result = EnableResult()
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_q(SQL_SCHEMA)}"))
    exists = bool(_scalar(conn, "SELECT 1 FROM pg_roles WHERE rolname = :r", r=SQL_ROLE))
    if not exists:
        # token_urlsafe emits only [A-Za-z0-9_-], so the literal needs no escaping.
        password = secrets.token_urlsafe(24)
        conn.execute(
            text(
                f"CREATE ROLE {_q(SQL_ROLE)} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS "
                f"PASSWORD '{password}'"
            )
        )
        result.role_created, result.password = True, password
    conn.execute(text(f"ALTER ROLE {_q(SQL_ROLE)} SET search_path = {_q(SQL_SCHEMA)}"))
    conn.execute(text(f"REVOKE ALL ON SCHEMA public FROM {_q(SQL_ROLE)}"))
    conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_q(SQL_ROLE)}"))
    conn.execute(text(f"GRANT USAGE ON SCHEMA {_q(SQL_SCHEMA)} TO {_q(SQL_ROLE)}"))
    for feed in catalogue.values():
        name = f"{_q(SQL_SCHEMA)}.{_q(feed.id)}"
        sql = f"CREATE OR REPLACE VIEW {name} WITH (security_invoker = true) AS {view_sql(feed)}"
        savepoint = conn.begin_nested()
        try:
            conn.execute(text(sql))
            savepoint.commit()
        except Exception:
            # The column list changed since the last enable; a view cannot be replaced across that.
            savepoint.rollback()
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
            conn.execute(text(sql))
        conn.execute(text(f"GRANT SELECT ON {name} TO {_q(SQL_ROLE)}"))
        for table, columns in base_columns(feed).items():
            cols = ", ".join(_q(c) for c in columns)
            conn.execute(text(f"GRANT SELECT ({cols}) ON public.{_q(table)} TO {_q(SQL_ROLE)}"))
        result.views.append(feed.id)
    if _scalar(conn, "SELECT has_schema_privilege(:r, 'public', 'CREATE')", r=SQL_ROLE):
        result.warnings.append("The public schema still grants CREATE to PUBLIC on this server; revoke it for safety.")
    return result


def disable(conn: Connection) -> bool:
    """Drop the schema and the role. Returns whether anything was there."""
    _require_postgres(conn)
    had_schema = bool(_scalar(conn, "SELECT 1 FROM pg_namespace WHERE nspname = :s", s=SQL_SCHEMA))
    had_role = bool(_scalar(conn, "SELECT 1 FROM pg_roles WHERE rolname = :r", r=SQL_ROLE))
    conn.execute(text(f"DROP SCHEMA IF EXISTS {_q(SQL_SCHEMA)} CASCADE"))
    if had_role:
        conn.execute(text(f"DROP OWNED BY {_q(SQL_ROLE)}"))
        conn.execute(text(f"DROP ROLE {_q(SQL_ROLE)}"))
    return had_schema or had_role


def status(conn: Connection) -> dict[str, Any]:
    """``{enabled, schema, role, views}``; never raises on a non-PostgreSQL database."""
    if conn.dialect.name != "postgresql":
        return {"enabled": False, "schema": SQL_SCHEMA, "role": SQL_ROLE, "views": []}
    has_schema = bool(_scalar(conn, "SELECT 1 FROM pg_namespace WHERE nspname = :s", s=SQL_SCHEMA))
    has_role = bool(_scalar(conn, "SELECT 1 FROM pg_roles WHERE rolname = :r", r=SQL_ROLE))
    views = (
        [
            row[0]
            for row in conn.execute(
                text("SELECT viewname FROM pg_views WHERE schemaname = :s ORDER BY viewname"), {"s": SQL_SCHEMA}
            )
        ]
        if has_schema
        else []
    )
    return {"enabled": has_schema and has_role, "schema": SQL_SCHEMA, "role": SQL_ROLE, "views": views}


def view_columns(conn: Connection) -> dict[str, list[str]]:
    """``{view: [column names in order]}`` as PostgreSQL reports them (for the parity rule)."""
    rows = conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = :s ORDER BY table_name, ordinal_position"
        ),
        {"s": SQL_SCHEMA},
    )
    out: dict[str, list[str]] = {}
    for table, column in rows:
        out.setdefault(table, []).append(column)
    return out

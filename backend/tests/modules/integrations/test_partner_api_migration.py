# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The partner API revision: columns up and down, settled history, idempotent webhook copy.

Runs the revision's own upgrade() and downgrade() against hand-built tables in
the shape the previous revision left, on in-memory SQLite (batch operations).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

REVISION_FILE = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "vpar01_partner_api_keys_webhooks.py"

OLD_SCHEMA = [
    "CREATE TABLE oe_users_user (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255), role VARCHAR(50), created_at DATETIME)",
    """CREATE TABLE oe_users_api_key (
        id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) REFERENCES oe_users_user(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL, key_hash VARCHAR(255) NOT NULL, key_prefix VARCHAR(12) NOT NULL,
        description TEXT NOT NULL DEFAULT '', is_active BOOLEAN NOT NULL DEFAULT 1, expires_at DATETIME,
        last_used_at DATETIME, permissions JSON NOT NULL DEFAULT '[]', created_at DATETIME, updated_at DATETIME)""",
    """CREATE TABLE oe_integrations_webhook (
        id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, project_id VARCHAR(36), name VARCHAR(255) NOT NULL,
        url VARCHAR(1000) NOT NULL, secret VARCHAR(255), events JSON NOT NULL DEFAULT '[]',
        is_active BOOLEAN NOT NULL DEFAULT 1, last_triggered_at VARCHAR(40), last_status_code INTEGER,
        failure_count INTEGER NOT NULL DEFAULT 0, metadata JSON NOT NULL DEFAULT '{}',
        created_at DATETIME, updated_at DATETIME)""",
    """CREATE TABLE oe_integrations_delivery (
        id VARCHAR(36) PRIMARY KEY, webhook_id VARCHAR(36) NOT NULL, event_type VARCHAR(100) NOT NULL,
        payload JSON NOT NULL DEFAULT '{}', status_code INTEGER, response_body TEXT, duration_ms INTEGER,
        created_at DATETIME, updated_at DATETIME)""",
    """CREATE TABLE oe_notification_webhook_target (
        id VARCHAR(36) PRIMARY KEY, name VARCHAR(120) NOT NULL, url VARCHAR(2048) NOT NULL,
        event_filter VARCHAR(1024) NOT NULL DEFAULT '*', secret VARCHAR(255), active BOOLEAN NOT NULL DEFAULT 1)""",
]

SEED = [
    "INSERT INTO oe_users_user VALUES ('u1', 'a@example.com', 'admin', '2026-01-01')",
    "INSERT INTO oe_users_api_key (id, user_id, name, key_hash, key_prefix) VALUES ('k1', 'u1', 'old', 'h', 'oe_abc')",
    "INSERT INTO oe_integrations_webhook (id, user_id, name, url, events) "
    "VALUES ('w1', 'u1', 'w', 'https://x.example.com', '[]')",
    "INSERT INTO oe_integrations_delivery (id, webhook_id, event_type, status_code) VALUES ('d1', 'w1', 'a.b', 204)",
    "INSERT INTO oe_integrations_delivery (id, webhook_id, event_type, status_code) VALUES ('d2', 'w1', 'a.b', 500)",
    "INSERT INTO oe_notification_webhook_target (id, name, url, event_filter, secret) "
    "VALUES ('t1', 'ERP feed', 'https://erp.example.com/in', 'rfi.created, task.assigned', 'sek')",
]

KEY_NEW = {"rate_limit_per_min", "allowed_cidrs", "request_count", "rotated_from_id"}
DELIVERY_NEW = {"attempt", "next_retry_at", "status", "last_error"}


def _revision():
    spec = importlib.util.spec_from_file_location("vpar01", REVISION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        for ddl in [*OLD_SCHEMA, *SEED]:
            c.exec_driver_sql(ddl)
        yield c
    engine.dispose()


def _run(conn, fn):
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        fn()


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _count(conn, sql):
    return conn.exec_driver_sql(sql).scalar()


def test_revision_follows_the_previous_head():
    rev = _revision()
    assert rev.down_revision == "vcap01_capital_plan"
    assert rev.revision == "vpar01_partner_api_keys_webhooks"


def test_upgrade_adds_columns_with_safe_defaults_and_settles_history(conn):
    _run(conn, _revision().upgrade)
    assert _cols(conn, "oe_users_api_key") >= KEY_NEW
    assert _cols(conn, "oe_integrations_delivery") >= DELIVERY_NEW

    key = conn.exec_driver_sql(
        "SELECT rate_limit_per_min, allowed_cidrs, request_count, rotated_from_id FROM oe_users_api_key"
    ).one()
    assert key[0] is None
    assert json.loads(key[1]) == []
    assert (key[2], key[3]) == (0, None)

    rows = dict(conn.exec_driver_sql("SELECT id, status FROM oe_integrations_delivery").fetchall())
    assert rows == {"d1": "delivered", "d2": "dead"}  # nothing pending: the worker finds no old row
    assert _count(conn, "SELECT COUNT(*) FROM oe_integrations_delivery WHERE next_retry_at IS NOT NULL") == 0
    indexes = {i["name"] for i in sa.inspect(conn).get_indexes("oe_integrations_delivery")}
    assert "ix_oe_integrations_delivery_next_retry_at" in indexes


def test_rotation_link_is_a_foreign_key_that_nulls_on_delete(conn):
    _run(conn, _revision().upgrade)
    fks = sa.inspect(conn).get_foreign_keys("oe_users_api_key")
    self_fk = next(f for f in fks if f["referred_table"] == "oe_users_api_key")
    assert self_fk["constrained_columns"] == ["rotated_from_id"]
    assert self_fk["options"].get("ondelete") == "SET NULL"


def test_upgrade_twice_changes_nothing_more(conn):
    rev = _revision()
    _run(conn, rev.upgrade)
    _run(conn, rev.upgrade)
    assert _count(conn, "SELECT COUNT(*) FROM oe_integrations_webhook WHERE name = 'ERP feed'") == 1
    assert _count(conn, "SELECT COUNT(*) FROM oe_users_api_key") == 1


def test_old_webhook_targets_are_copied_once_inactive_and_flagged(conn):
    rev = _revision()
    _run(conn, rev.upgrade)
    _run(conn, rev.upgrade)
    row = conn.exec_driver_sql(
        "SELECT user_id, url, secret, events, is_active, metadata FROM oe_integrations_webhook WHERE name = 'ERP feed'"
    ).one()
    assert row[0] == "u1"  # first admin
    assert (row[1], row[2]) == ("https://erp.example.com/in", "sek")
    assert json.loads(row[3]) == ["rfi.created", "task.assigned"]
    assert not row[4]  # nothing starts sending on its own
    meta = json.loads(row[5])
    assert meta["migrated_from"] == "oe_notification_webhook_target:t1"
    assert meta["needs_review"] is True
    # the old table is left as it was
    assert _count(conn, "SELECT COUNT(*) FROM oe_notification_webhook_target") == 1


def test_no_admin_means_no_copy(conn):
    conn.exec_driver_sql("UPDATE oe_users_user SET role = 'editor'")
    _run(conn, _revision().upgrade)
    assert _count(conn, "SELECT COUNT(*) FROM oe_integrations_webhook") == 1


def test_downgrade_removes_only_what_upgrade_added(conn):
    rev = _revision()
    _run(conn, rev.upgrade)
    _run(conn, rev.downgrade)
    assert not (KEY_NEW & _cols(conn, "oe_users_api_key"))
    assert not (DELIVERY_NEW & _cols(conn, "oe_integrations_delivery"))
    assert {"id", "user_id", "name", "key_hash", "permissions"} <= _cols(conn, "oe_users_api_key")
    assert _count(conn, "SELECT COUNT(*) FROM oe_users_api_key") == 1
    assert _count(conn, "SELECT COUNT(*) FROM oe_integrations_delivery") == 2
    # and it can go up again
    _run(conn, rev.upgrade)
    assert _cols(conn, "oe_users_api_key") >= KEY_NEW

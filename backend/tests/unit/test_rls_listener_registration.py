# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Listener setup cannot silently disable requested tenant enforcement."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mode", ["import", "install", "success"])
def test_database_import_requires_listener_only_when_enforced(tmp_path, mode, enabled):
    _probe(tmp_path, mode, enabled)


def test_listener_failure_with_unreadable_settings_cannot_continue(tmp_path):
    _probe(tmp_path, "settings", False)


def _probe(tmp_path, mode, enabled):
    env = os.environ.copy()
    for name, value in {
        "DATABASE_URL": "postgresql+asyncpg://probe:probe@127.0.0.1:9/unused",
        "DATABASE_SYNC_URL": "postgresql+psycopg2://probe:probe@127.0.0.1:9/unused",
        "DATA_DIR": str(tmp_path),
        "JWT_SECRET": secrets.token_hex(32),
        "APP_ENV": "development",
        "RLS_ENFORCE": str(enabled).lower(),
    }.items():
        env[name] = value
        env[f"OE_{name}"] = value
    env["OE_CLI_DATA_DIR"] = str(tmp_path)
    env["OE_RUNTIME_MODULES_DIR"] = str(tmp_path / "modules")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("_rls_listener_import_probe.py")), mode, str(enabled).lower()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "RLS_LISTENER_IMPORT_OK" in result.stdout


def test_failed_registration_can_retry_without_stacking_listeners(monkeypatch):
    from app.core import rls

    class PrivateSession(Session):
        pass

    original = event.listens_for
    callbacks = []
    attempts = []

    def register(target, name):
        attempts.append((target, name))
        if len(attempts) == 1:
            raise RuntimeError("injected listener registration failure")

        def decorate(callback):
            callbacks.append(callback)
            return original(target, name)(callback)

        return decorate

    monkeypatch.setattr(event, "listens_for", register)
    monkeypatch.setattr(rls, "rls_enabled", lambda: True)
    token = rls.set_request_tenant("private-tenant")
    emitted = []

    class Connection:
        def exec_driver_sql(self, sql):
            emitted.append(sql)

        def execute(self, sql, parameters):
            emitted.append((str(sql), parameters))

    try:
        with pytest.raises(RuntimeError, match="injected listener"):
            rls.install(PrivateSession)
        rls.install(PrivateSession)
        rls.install(PrivateSession)
        assert len(attempts) == 2
        assert len(callbacks) == 1
        assert event.contains(PrivateSession, "after_begin", callbacks[0])
        callbacks[0](None, None, Connection())
        assert emitted == [
            'SET LOCAL ROLE "oe_app"',
            ("SELECT set_config(:name, :val, true)", {"name": "app.current_tenant", "val": "private-tenant"}),
        ]
    finally:
        rls.reset_request_tenant(token)
        for callback in callbacks:
            event.remove(PrivateSession, "after_begin", callback)
        rls._installed.discard(id(PrivateSession))

"""Role attributes are cluster-wide: never use the application/test database here."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def _private_cluster_path() -> Path:
    # Match tests/conftest.py's cluster placement. Windows initdb cannot use
    # the runneradmin profile's pytest temp tree reliably ("File exists").
    # Keep a separate cluster: roles are cluster-wide, not database-local.
    root = Path(tempfile.gettempdir())
    for name in ("OE_TEST_PG_ROOT", "RUNNER_TEMP"):
        candidate = os.environ.get(name, "").strip()
        if candidate and Path(candidate).is_dir():
            root = Path(candidate)
            break
    # Name, but do not pre-create, the data directory: let initdb own its
    # permissions, exactly as the shared test-cluster launcher does.
    return root.resolve() / f"oe-rls-private-{secrets.token_hex(8)}"


@pytest.mark.parametrize("case", ["override", "runner", "missing_override", "system"])
def test_private_cluster_uses_an_accessible_scratch_root(tmp_path, monkeypatch, case):
    roots = {name: tmp_path / name for name in ("override", "runner", "system")}
    for root in roots.values():
        root.mkdir()
    monkeypatch.delenv("OE_TEST_PG_ROOT", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(roots["system"]))
    if case != "system":
        monkeypatch.setenv("RUNNER_TEMP", str(roots["runner"]))
    if case == "override":
        monkeypatch.setenv("OE_TEST_PG_ROOT", f" {roots['override']} ")
    elif case == "missing_override":
        monkeypatch.setenv("OE_TEST_PG_ROOT", str(tmp_path / "missing"))
    path = _private_cluster_path()
    assert path.parent == roots["runner" if case == "missing_override" else case]
    assert not path.exists(), "initdb must create its own private data directory"
    assert _private_cluster_path() != path, "parallel runs must not share cluster-wide roles"


@pytest.fixture(scope="module")
def private_cluster():
    import pixeltable_pgserver

    data_dir = _private_cluster_path()
    assert not data_dir.exists(), "never reuse or clean up a pre-existing cluster"
    # get_server defaults to stop-only. This uniquely owned cluster is outside
    # pytest's temp tree, so explicitly remove its data after stopping it.
    server = pixeltable_pgserver.get_server(str(data_dir), cleanup_mode="delete")
    try:
        yield make_url(server.get_uri())
    finally:
        server.cleanup()


@pytest.fixture
def role_database(private_cluster):
    engine = create_engine(private_cluster.set(drivername="postgresql+psycopg2"))
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP ROLE IF EXISTS oe_app"))
            conn.execute(text("DROP ROLE IF EXISTS rls_unprivileged"))
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("attributes", ["SUPERUSER NOBYPASSRLS", "NOSUPERUSER BYPASSRLS"])
async def test_enabled_rejects_a_role_that_bypasses_policies(private_cluster, role_database, monkeypatch, attributes):
    from app.core import rls_setup

    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: True)
    with role_database.begin() as conn:
        conn.execute(text(f"CREATE ROLE oe_app NOLOGIN {attributes}"))
    engine = create_async_engine(private_cluster.set(drivername="postgresql+asyncpg"), poolclass=NullPool)
    try:
        with pytest.raises(rls_setup.RLSConfigurationError, match="SUPERUSER|BYPASSRLS"):
            await rls_setup.verify_rls_role(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_never_opens_a_connection(monkeypatch):
    from app.core import rls_setup

    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: False)

    class NoDatabase:
        def begin(self):
            pytest.fail("disabled RLS must not open a connection")

    assert await rls_setup.verify_rls_role(NoDatabase()) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("role_exists", [False, True])
async def test_enabled_rejects_missing_or_unassumable_role(private_cluster, role_database, monkeypatch, role_exists):
    from app.core import rls_setup

    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: True)
    with role_database.begin() as conn:
        conn.execute(text("CREATE ROLE rls_unprivileged LOGIN NOSUPERUSER NOBYPASSRLS"))
        if role_exists:
            conn.execute(text("CREATE ROLE oe_app NOLOGIN NOSUPERUSER NOBYPASSRLS"))
    engine = create_async_engine(
        private_cluster.set(drivername="postgresql+asyncpg", username="rls_unprivileged"), poolclass=NullPool
    )
    try:
        with pytest.raises(rls_setup.RLSConfigurationError, match="oe_app") as error:
            await rls_setup.verify_rls_role(engine)
        if role_exists:
            # A failed connection/authentication must not masquerade as the
            # missing SET ROLE permission this fixture is intended to prove.
            assert error.value.__cause__.orig.sqlstate == "42501"
        else:
            assert "does not exist" in str(error.value)
            assert error.value.__cause__ is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enabled_accepts_safe_role_and_resets_pooled_connection(private_cluster, role_database, monkeypatch):
    from app.core import rls_setup

    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: True)
    with role_database.begin() as conn:
        conn.execute(text("CREATE ROLE oe_app NOLOGIN NOSUPERUSER NOBYPASSRLS"))
    engine = create_async_engine(private_cluster.set(drivername="postgresql+asyncpg"), pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            original = (await conn.execute(text("SELECT current_user"))).scalar_one()
        assert await rls_setup.verify_rls_role(engine) is True
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar_one() == original
    finally:
        await engine.dispose()


def test_registered_startup_propagates_role_failure_even_after_provision_failure(private_cluster, tmp_path):
    """Run the actual startup wrapper in another process, with all data isolated."""
    env = os.environ.copy()
    for name, value in {
        "DATABASE_URL": private_cluster.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
        "DATABASE_SYNC_URL": private_cluster.set(drivername="postgresql+psycopg2").render_as_string(
            hide_password=False
        ),
        "DATA_DIR": str(tmp_path),
        "JWT_SECRET": "private-startup-regression-secret-at-least-32-bytes",
        "APP_ENV": "development",
        "RLS_ENFORCE": "true",
    }.items():
        env[name] = value
        env[f"OE_{name}"] = value
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["OE_CLI_DATA_DIR"] = str(tmp_path)
    probe = Path(__file__).with_name("_rls_startup_probe.py")
    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=240
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    assert "RLS_STARTUP_PROPAGATION_OK cases=2" in result.stdout

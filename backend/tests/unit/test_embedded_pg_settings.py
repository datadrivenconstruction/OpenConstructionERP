"""The embedded cluster gets the lock headroom the platform's schema needs.

PostgreSQL sizes its lock table as ``max_locks_per_transaction`` times
``max_connections`` and shares it across the whole cluster. Creating or
reflecting this platform's schema locks well over a thousand objects, so with
the default of 64 a few connections doing that at once run the pool dry and the
statement fails with "out of shared memory" -- which reads like a memory problem
and is really a configuration one.

These tests drive the config writer against a temporary directory, so they need
no cluster and cannot disturb the session's own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import embedded_pg

BASE_CONF = "# -----------------------------\n# PostgreSQL configuration file\nport = 5432\n"


@pytest.fixture
def pgdata(tmp_path: Path) -> Path:
    (tmp_path / "postgresql.conf").write_text(BASE_CONF, encoding="utf-8")
    return tmp_path


def read(pgdata: Path) -> str:
    return (pgdata / "postgresql.conf").read_text(encoding="utf-8")


def test_the_setting_is_written_into_the_config(pgdata: Path) -> None:
    assert embedded_pg._apply_server_settings(pgdata) is True

    assert "max_locks_per_transaction = 512" in read(pgdata)


def test_the_existing_config_is_kept(pgdata: Path) -> None:
    embedded_pg._apply_server_settings(pgdata)

    assert "port = 5432" in read(pgdata)


def test_reapplying_leaves_one_block(pgdata: Path) -> None:
    """Boot runs this every time, so appending would grow the file without end."""
    embedded_pg._apply_server_settings(pgdata)
    first = read(pgdata)

    assert embedded_pg._apply_server_settings(pgdata) is False
    assert read(pgdata) == first
    assert first.count("max_locks_per_transaction") == 1


def test_a_changed_setting_replaces_the_old_value(pgdata: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise a raised value would sit under the old one and lose the race."""
    embedded_pg._apply_server_settings(pgdata)
    monkeypatch.setattr(embedded_pg, "_SERVER_SETTINGS", (("max_locks_per_transaction", "1024"),))

    assert embedded_pg._apply_server_settings(pgdata) is True

    conf = read(pgdata)
    assert "max_locks_per_transaction = 1024" in conf
    assert "512" not in conf


def test_a_truncated_block_is_repaired(pgdata: Path) -> None:
    """An interrupted write can leave the opening marker with no closing one."""
    (pgdata / "postgresql.conf").write_text(
        BASE_CONF + "\n" + embedded_pg._SETTINGS_BEGIN + "\nmax_locks_per_transaction = 64\n",
        encoding="utf-8",
    )

    assert embedded_pg._apply_server_settings(pgdata) is True

    conf = read(pgdata)
    assert conf.count(embedded_pg._SETTINGS_BEGIN) == 1
    assert conf.count(embedded_pg._SETTINGS_END) == 1
    assert "max_locks_per_transaction = 512" in conf
    assert "max_locks_per_transaction = 64" not in conf


def test_a_missing_cluster_is_not_an_error(tmp_path: Path) -> None:
    """Pre-init can decline (running as root, no binary), and boot must go on."""
    assert embedded_pg._apply_server_settings(tmp_path / "nope") is False


def test_the_cluster_is_pre_initialised_on_every_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings have nowhere to go until a cluster exists.

    ``get_server()`` runs initdb and starts the postmaster in one call, so if we
    let it create the cluster there is no moment at which we can write
    ``postgresql.conf`` before the postmaster reads it. ``max_locks_per_transaction``
    needs a restart to take effect, so a config written after that first start
    would not apply until the second boot -- and the first boot on a fresh
    machine is precisely the case this exists to serve. Skipping the pre-init on
    POSIX made the whole fix a no-op for ``make quickstart`` on Linux.
    """
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_pgexec(command: str, args: tuple[str, ...]) -> None:
        calls.append((command, args))
        (tmp_path / "PG_VERSION").write_text("16\n", encoding="utf-8")
        (tmp_path / "postgresql.conf").write_text(BASE_CONF, encoding="utf-8")

    monkeypatch.setattr(embedded_pg, "_safe_pgexec", fake_pgexec)

    assert embedded_pg._pre_initialize_cluster(tmp_path) is True

    assert [command for command, _ in calls] == ["initdb", "initdb"]
    assert "--version" in calls[0][1]
    assert "--locale=C" in calls[1][1]
    # The point of the whole exercise: a config to write, before any postmaster.
    assert embedded_pg._apply_server_settings(tmp_path) is True
    assert "max_locks_per_transaction = 512" in read(tmp_path)


def test_an_initialised_cluster_is_left_alone(tmp_path: Path) -> None:
    """Second and later boots must not re-run initdb over live data."""
    (tmp_path / "PG_VERSION").write_text("16\n", encoding="utf-8")

    assert embedded_pg._pre_initialize_cluster(tmp_path) is False

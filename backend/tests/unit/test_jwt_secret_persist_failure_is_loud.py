# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A JWT secret that cannot be persisted or read back must be loud, never destructive.

Every session the browser holds is signed with this secret. When the
auto-provisioned secret changes across a restart, every open tab gets a 401
from ``/auth/refresh`` and signs out, so the operator has to be told why, and
a secret file that merely failed to read must not be overwritten: that would
turn a transient permission problem into a permanent loss of every session.
"""

from __future__ import annotations

import logging
import os
import pathlib
from collections.abc import Iterator

import pytest

from app.config import _ensure_persistent_jwt_secret

_MANAGED = ("JWT_SECRET", "OE_JWT_SECRET", "APP_ENV", "OE_APP_ENV", "OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")


@pytest.fixture(autouse=True)
def _isolated_env() -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in _MANAGED}
    for name in _MANAGED:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_unwritable_data_dir_warns_that_sessions_end_on_restart(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A regular file where the data dir should be: mkdir fails like a read-only volume.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    os.environ["APP_ENV"] = "production"
    os.environ["OE_DATA_DIR"] = str(blocker)
    with caplog.at_level(logging.WARNING, logger="openestimate.config"):
        _ensure_persistent_jwt_secret()
    assert os.environ["JWT_SECRET"]
    assert any("per-process" in m and "restart" in m for m in _warnings(caplog))


def test_unreadable_secret_file_is_not_overwritten(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / ".jwt-secret"
    existing = "persisted-" + "y" * 40
    secret_file.write_text(existing, encoding="utf-8")
    real_read = pathlib.Path.read_text

    def failing_read(self: pathlib.Path, *args: object, **kwargs: object) -> str:
        if self.name == ".jwt-secret":
            raise PermissionError(13, "Permission denied")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", failing_read)
    os.environ["APP_ENV"] = "production"
    os.environ["OE_DATA_DIR"] = str(tmp_path)
    with caplog.at_level(logging.WARNING, logger="openestimate.config"):
        _ensure_persistent_jwt_secret()
    monkeypatch.undo()

    # The stored secret survives, so the next boot that can read it restores every session.
    assert secret_file.read_text(encoding="utf-8") == existing
    assert any("could not be read" in m and str(secret_file) in m for m in _warnings(caplog))


def test_dev_unreadable_secret_file_is_not_overwritten(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The development path (docker-compose.quickstart.yml runs APP_ENV=development) has the same shape.
    from app.config import load_or_create_dev_jwt_secret

    secret_file = tmp_path / ".jwt-secret"
    existing = "persisted-" + "z" * 40
    secret_file.write_text(existing, encoding="utf-8")
    real_read = pathlib.Path.read_text

    def failing_read(self: pathlib.Path, *args: object, **kwargs: object) -> str:
        if self.name == ".jwt-secret":
            raise PermissionError(13, "Permission denied")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pathlib.Path, "read_text", failing_read)
    os.environ["OE_DATA_DIR"] = str(tmp_path)
    with caplog.at_level(logging.WARNING, logger="openestimate.config"):
        secret, _path, source = load_or_create_dev_jwt_secret(legacy_paths=())
    monkeypatch.undo()

    assert source == "ephemeral"
    assert secret != existing
    assert secret_file.read_text(encoding="utf-8") == existing
    assert any("could not be read" in m for m in _warnings(caplog))

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A build we ship must not sign tokens with a secret that is in the repository.

The desktop sidecar is started by the CLI, and ``cli.py`` sets
``APP_ENV=development`` and ``JWT_SECRET=openestimate-local-dev-key`` with no
branch for a frozen build. The auto-provisioner that exists precisely to stop a
zero-config deployment from keeping that literal returned on its first line for
anything calling itself development, so it never ran inside an installed copy
of the app. Every one of them signed with the same key, and that key is in the
public repository - which is the reason it is in ``_JWT_KNOWN_WEAK_SECRETS`` in
the first place, as the comment above that set says.

The environment is deliberately left as development. Promoting the frozen build
to production would also fix this, and would also switch off the passwordless
demo sign-in and turn the takeoff privacy badge from "never leaves your
computer" into "processed on your server", which on a desktop is the less true
of the two.

The third test is the control and matters as much as the first: a source
checkout in development must still boot on the bundled default with no
ceremony, because that is what makes ``docker compose up`` work with no .env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.config import (
    _JWT_KNOWN_WEAK_SECRETS,
    _JWT_SECRET_MIN_LENGTH,
    _ensure_persistent_jwt_secret,
)

DEV_DEFAULT = "openestimate-local-dev-key"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """A clean environment whose data dir is a temporary one.

    ``OE_DATA_DIR`` is honoured by ``_jwt_secret_persist_dir``, so the secret
    lands under tmp_path rather than in the developer's own ~/.openestimate.
    """
    for name in ("APP_ENV", "OE_APP_ENV", "JWT_SECRET", "OE_JWT_SECRET", "OE_DESKTOP", "DATA_DIR", "OE_CLI_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    monkeypatch.delattr(sys, "frozen", raising=False)
    return monkeypatch


def _as_the_cli_leaves_it(env: pytest.MonkeyPatch) -> None:
    """Exactly what ``cli.py`` puts in the environment before the app starts."""
    env.setenv("APP_ENV", "development")
    env.setenv("JWT_SECRET", DEV_DEFAULT)


def test_a_desktop_build_gets_its_own_secret(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _as_the_cli_leaves_it(env)
    env.setenv("OE_DESKTOP", "1")

    _ensure_persistent_jwt_secret()

    secret = os.environ["JWT_SECRET"]
    assert secret != DEV_DEFAULT, "the installed app is still signing with the key in the public repository"
    assert secret not in _JWT_KNOWN_WEAK_SECRETS
    assert len(secret) >= _JWT_SECRET_MIN_LENGTH
    assert (tmp_path / ".jwt-secret").is_file(), "the secret was not persisted, so it changes on every launch"


def test_a_frozen_build_gets_one_without_the_launcher_saying_so(env: pytest.MonkeyPatch) -> None:
    """``sys.frozen`` is the artifact's own signal and has to be enough.

    ``OE_DESKTOP`` comes from the launcher. Anything that runs the sidecar
    directly - the release gate does, and so does a user debugging their own
    install - has only this one.
    """
    _as_the_cli_leaves_it(env)
    env.setattr(sys, "frozen", True, raising=False)

    _ensure_persistent_jwt_secret()

    assert os.environ["JWT_SECRET"] != DEV_DEFAULT


def test_a_source_checkout_in_development_is_left_alone(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The control. Zero-config local development must keep working."""
    _as_the_cli_leaves_it(env)

    _ensure_persistent_jwt_secret()

    assert os.environ["JWT_SECRET"] == DEV_DEFAULT
    assert not (tmp_path / ".jwt-secret").exists(), "development wrote a secret file it does not need"


def test_the_desktop_secret_survives_a_restart(env: pytest.MonkeyPatch) -> None:
    """Two launches, one secret, or every restart signs everyone out."""
    _as_the_cli_leaves_it(env)
    env.setenv("OE_DESKTOP", "1")

    _ensure_persistent_jwt_secret()
    first = os.environ["JWT_SECRET"]

    env.setenv("JWT_SECRET", DEV_DEFAULT)  # a fresh process, as the CLI leaves it again
    _ensure_persistent_jwt_secret()

    assert os.environ["JWT_SECRET"] == first


def test_a_secret_the_operator_chose_is_never_overwritten(env: pytest.MonkeyPatch) -> None:
    """Desktop or not, a real value belongs to whoever set it."""
    chosen = "an-operator-chose-this-one-and-it-is-long-enough"
    env.setenv("APP_ENV", "development")
    env.setenv("OE_DESKTOP", "1")
    env.setenv("JWT_SECRET", chosen)

    _ensure_persistent_jwt_secret()

    assert os.environ["JWT_SECRET"] == chosen

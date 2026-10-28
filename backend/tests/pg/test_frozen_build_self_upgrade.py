# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A frozen desktop build must refuse to pip-upgrade itself (issue #403).

The reporter clicked "Apply update" in the Windows app on 9.4.0 and got an
argparse usage dump ending ``invalid choice: 'pip'``. That output is this
application's own CLI answering: in the PyInstaller sidecar ``sys.executable``
is the frozen binary, so ``[sys.executable, "-m", "pip", "install", ...]``
re-enters the app instead of reaching an interpreter.

These tests need neither a database nor an authenticated client, but they live
in the PG lane because that is the lane CI actually runs. Their whole job is to
be present on the gate: the defect is invisible to every test that runs under a
normal interpreter, because under one ``sys.frozen`` is simply absent and the
guarded branch is never taken.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from app.core.self_upgrade import FROZEN_REFUSAL, RELEASES_URL, is_frozen_build

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend to be a PyInstaller bundle.

    ``raising=False`` because ``sys.frozen`` does not exist at all under a real
    interpreter; PyInstaller sets it on the module at runtime. ``monkeypatch``
    deletes it again afterwards, so nothing leaks into the rest of the session.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn any attempt to spawn a process into a failure.

    Two jobs. It asserts the thing actually under test - a frozen build must
    stop before the pip command exists - and it keeps a regression contained: if
    a guard is ever removed, these tests fail instead of running a real
    ``pip install --upgrade`` against whatever environment the suite is in.
    """

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a frozen build must not spawn a process: {args!r}")

    for name in ("run", "check_call", "check_output", "Popen"):
        monkeypatch.setattr(subprocess, name, _explode)


def test_a_normal_interpreter_is_not_a_frozen_build() -> None:
    """The guard must stay inert everywhere the pip route genuinely works.

    Worth asserting on its own: a guard that returned True broadly would break
    the Windows installer builds, which are desktop yet run a real ``python.exe``
    from a private venv and upgrade themselves correctly.
    """
    assert is_frozen_build() is False


def test_frozen_build_is_detected(frozen: None) -> None:
    assert is_frozen_build() is True


def test_the_refusal_names_the_route_that_works() -> None:
    """The message is the whole remedy, so pin what it has to contain.

    A user who reaches this text has already tried the button and has no other
    source of instruction, so it must carry the installer link and say that
    their data survives. Without the reassurance people postpone the upgrade.
    """
    assert RELEASES_URL in FROZEN_REFUSAL
    assert "installer" in FROZEN_REFUSAL.lower()
    assert "projects and settings stay" in FROZEN_REFUSAL


def test_cli_upgrade_refuses_and_never_shells_out(
    frozen: None, no_subprocess: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """``openconstructionerp upgrade`` stops before building the pip command.

    The subprocess trap is the defect itself, so failing the test on any
    execution attempt is the assertion that matters. Checking only the printed
    text would still pass if the guard ran after the command had been launched.
    """
    from app.cli import cmd_upgrade

    with pytest.raises(SystemExit) as exc:
        cmd_upgrade(argparse.Namespace(version=None))

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert RELEASES_URL in out
    assert "pip" in out.lower(), "the user has to learn why the pip route is unavailable"


def test_upgrade_route_refuses_before_touching_pip(frozen: None, no_subprocess: None) -> None:
    """The API route the desktop panel calls answers 409, not an installer log.

    Reached through the registered handler rather than over HTTP so the test
    needs no admin session: the auth gate in front of it is already covered by
    ``tests/integration/test_system_upgrade_auth.py``, and what is under test
    here is only what the body does once a caller is past it.
    """
    from fastapi import HTTPException

    handler = _route_handler("/api/system/upgrade", "POST")

    with pytest.raises(HTTPException) as exc:
        _run(handler())

    assert exc.value.status_code == 409
    assert exc.value.detail == FROZEN_REFUSAL


def _route_handler(path: str, method: str) -> Callable:
    """Pull one endpoint function out of a freshly built app.

    ``create_app`` defines these routes as closures, so there is no importable
    symbol to call directly and no dependency object stable enough to override.
    """
    from app.main import create_app

    for route in create_app().routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
            return route.endpoint
    raise AssertionError(f"{method} {path} is not registered")


def _run(coro: object) -> object:
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]

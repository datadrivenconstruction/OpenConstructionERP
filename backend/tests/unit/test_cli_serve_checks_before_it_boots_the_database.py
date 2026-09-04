# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``serve`` must answer the cheap questions before it does the expensive thing.

``cmd_serve`` used to call ``_setup_env`` first and run its blocking pre-flight
afterwards. ``_setup_env`` boots the embedded PostgreSQL cluster, and on a first
run that means an initdb: measured at about twenty seconds and forty megabytes
under the data directory. Both of the conditions the pre-flight is there to
catch make that work pointless, and one of them made the pre-flight itself
unreachable:

* A busy port. Port 8080 is the single most likely thing to be already taken on
  a machine we have never seen, and detecting it costs microseconds. Ordered the
  old way, a first-time user paid the whole initdb and was then told to pass
  ``--port``.
* An unwritable data directory. ``check_data_dir`` renders a sentence naming
  ``--data-dir``, but ``_setup_env`` opens with an unguarded
  ``data_dir.mkdir(parents=True, exist_ok=True)``. Running it first meant the
  ``mkdir`` raised first, so the user got a pathlib traceback and the check that
  exists to explain this never printed at all.

The tests below pin the ordering rather than the symptom. A test that only
asserted "a busy port exits 1" passes with the old ordering too - it just takes
twenty seconds longer and leaves a cluster behind it - so it would not have
caught the defect and would not catch its return.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from app import cli


class _SetupEnvReached(RuntimeError):
    """Raised by the ``_setup_env`` stub so execution stops there.

    Lets a test observe that ``_setup_env`` was reached, and in what order,
    without going on to build settings, print a banner and start uvicorn.
    """


def _serve_args(tmp_path: Path, port: int = 8080) -> argparse.Namespace:
    """A parsed command line equivalent to a bare ``openconstructionerp serve``."""
    return argparse.Namespace(
        host="127.0.0.1",
        port=port,
        data_dir=str(tmp_path / "data"),
        quiet=True,
        open=False,
        no_demo=False,
        demo=False,
    )


def _blocking_port_check(*_args: object, **_kwargs: object) -> cli.Check:
    """A ``check_port_free`` that reports the port taken."""
    return cli.Check("Port available", "error", "port is already in use", "Stop the other process")


def test_a_blocking_check_stops_serve_before_the_database_is_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failing pre-flight check must abort without booting embedded PostgreSQL."""
    calls: list[str] = []

    def _setup_env(*_args: object, **_kwargs: object) -> None:
        calls.append("setup_env")
        raise _SetupEnvReached

    monkeypatch.setattr(cli, "check_port_free", _blocking_port_check)
    monkeypatch.setattr(cli, "_setup_env", _setup_env)

    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_serve(_serve_args(tmp_path))

    assert excinfo.value.code == 1
    assert calls == [], "serve booted the database before it noticed the port was taken"

    # The reason has to reach the user, not just the exit code.
    out = capsys.readouterr().out
    assert "pre-flight checks failed" in out
    assert "Port available" in out


def test_the_data_dir_check_speaks_before_setup_env_can_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unwritable data dir gets the check's sentence, not a pathlib traceback.

    ``_setup_env`` is stubbed to raise the way its real ``mkdir`` would, so the
    test fails if anything ever calls it ahead of the pre-flight again.
    """

    def _setup_env(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(3, "The system cannot find the path specified")

    def _unwritable(data_dir: Path) -> cli.Check:
        return cli.Check(
            "Data directory",
            "error",
            f"cannot write to {data_dir}: denied",
            "Use --data-dir to pick a writable path",
        )

    monkeypatch.setattr(cli, "check_data_dir", _unwritable)
    monkeypatch.setattr(cli, "_setup_env", _setup_env)

    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_serve(_serve_args(tmp_path))

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Data directory" in out
    assert "--data-dir" in out


def test_preflight_runs_before_setup_env_on_the_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing wrong, the order is still pre-flight first.

    The two tests above both work through a failing check, so on their own they
    leave open the reading that the pre-flight is merely an early-exit guard
    bolted on somewhere. This one records the order when every check passes,
    which is the invariant the other two depend on.
    """
    calls: list[str] = []

    def _preflight(*_args: object, **_kwargs: object) -> None:
        calls.append("preflight")

    def _setup_env(*_args: object, **_kwargs: object) -> None:
        calls.append("setup_env")
        raise _SetupEnvReached

    monkeypatch.setattr(cli, "_run_fatal_preflight", _preflight)
    monkeypatch.setattr(cli, "_setup_env", _setup_env)

    with pytest.raises(_SetupEnvReached):
        cli.cmd_serve(_serve_args(tmp_path))

    assert calls == ["preflight", "setup_env"]

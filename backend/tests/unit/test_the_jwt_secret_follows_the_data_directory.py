"""The development JWT secret lives in the data directory, not in the home folder.

``openconstructionerp serve --data-dir X`` resolves every path through the
data directory: the embedded cluster, the uploads, the demo credentials. The
one thing that did not follow was the JWT signing secret. ``main.py`` computed
its own location, ``~/.openestimate/.jwt-secret``, while ``app.config`` already
had the resolver that honours ``OE_DATA_DIR``, ``DATA_DIR`` and
``OE_CLI_DATA_DIR``. Measured on a fresh 17.0.2 install started with
``--data-dir Q:\\data-a``: the boot log said "loaded persisted dev secret from
C:\\Users\\<user>\\.openestimate\\.jwt-secret" and the data directory held no
secret at all. Two instances on one machine therefore signed with one key, and
a data directory copied to another machine arrived without its secret.

These tests import only ``app.config`` and point ``Path.home`` at a temporary
folder, so nothing here reads or writes the real home directory.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

from app.config import _JWT_SECRET_MIN_LENGTH, load_or_create_dev_jwt_secret

_MANAGED = ("OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR")

# Long enough to sign with, so a file holding it is a secret worth adopting.
_LEGACY_SECRET = "legacy-" + "k" * 40


@pytest.fixture(autouse=True)
def _isolated_env() -> Iterator[None]:
    """Clear the data-dir overrides for each test and put them back after."""
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


@pytest.fixture
def home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A throwaway home directory, so the real one is never touched."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda _cls: fake_home))
    return fake_home


def _run_from(data_dir: pathlib.Path) -> tuple[str, pathlib.Path, str]:
    """One boot's worth of secret resolution, as the CLI would set it up."""
    os.environ["OE_CLI_DATA_DIR"] = str(data_dir)
    return load_or_create_dev_jwt_secret()


def test_the_secret_is_created_in_the_data_directory_not_under_home(home: pathlib.Path, tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data-a"

    secret, path, source = _run_from(data_dir)

    assert source == "generated"
    assert path == data_dir / ".jwt-secret"
    assert path.read_text(encoding="utf-8") == secret
    assert len(secret.encode("utf-8")) >= _JWT_SECRET_MIN_LENGTH
    # The two places the old code wrote to or read from stay untouched.
    assert not (home / ".openestimate").exists()
    assert not (home / ".openestimator").exists()


def test_two_data_directories_get_two_secrets_and_each_survives_a_restart(
    home: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The defect was one key for every data directory on the machine."""
    first_a, path_a, _ = _run_from(tmp_path / "data-a")
    first_b, path_b, _ = _run_from(tmp_path / "data-b")

    assert path_a != path_b
    assert first_a != first_b

    # A restart of each instance reads its own secret back, unchanged.
    again_a, _, source_a = _run_from(tmp_path / "data-a")
    again_b, _, source_b = _run_from(tmp_path / "data-b")
    assert (again_a, source_a) == (first_a, "loaded")
    assert (again_b, source_b) == (first_b, "loaded")
    assert path_a.read_text(encoding="utf-8") == first_a
    assert path_b.read_text(encoding="utf-8") == first_b


def test_a_secret_under_the_pre_rename_home_folder_is_adopted_once_and_only_read(
    home: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    legacy = home / ".openestimator" / ".jwt-secret"
    legacy.parent.mkdir()
    legacy.write_text(_LEGACY_SECRET, encoding="utf-8")
    legacy_stamp = legacy.stat().st_mtime_ns
    data_dir = tmp_path / "data-c"

    secret, path, source = _run_from(data_dir)

    assert (secret, source) == (_LEGACY_SECRET, "adopted")
    assert path == data_dir / ".jwt-secret"
    assert path.read_text(encoding="utf-8") == _LEGACY_SECRET
    # The legacy file is a read-only source: same bytes, same mtime.
    assert legacy.read_text(encoding="utf-8") == _LEGACY_SECRET
    assert legacy.stat().st_mtime_ns == legacy_stamp

    # The next boot is self-contained and no longer looks at the home folder.
    legacy.unlink()
    again, _, source_again = _run_from(data_dir)
    assert (again, source_again) == (_LEGACY_SECRET, "loaded")


def test_a_legacy_secret_too_short_to_sign_with_is_not_adopted(home: pathlib.Path, tmp_path: pathlib.Path) -> None:
    legacy = home / ".openestimator" / ".jwt-secret"
    legacy.parent.mkdir()
    legacy.write_text("short", encoding="utf-8")

    secret, _, source = _run_from(tmp_path / "data-d")

    assert source == "generated"
    assert secret != "short"
    assert len(secret.encode("utf-8")) >= _JWT_SECRET_MIN_LENGTH


def test_a_default_install_keeps_its_secret_where_it_always_was(home: pathlib.Path) -> None:
    """No override means the CLI's default data directory, so nobody is logged out by this change."""
    _, path, _ = load_or_create_dev_jwt_secret()

    assert path == home / ".openestimate" / ".jwt-secret"
    assert path.is_file()


def test_an_unwritable_data_directory_yields_a_per_process_secret(home: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Persistence failing must degrade to a random secret, never to the published default."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where the data directory should be", encoding="utf-8")

    secret, path, source = _run_from(blocker / "data-e")

    assert source == "ephemeral"
    assert path == blocker / "data-e" / ".jwt-secret"
    assert not path.exists()
    assert len(secret.encode("utf-8")) >= _JWT_SECRET_MIN_LENGTH

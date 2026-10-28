"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The bundled PostgreSQL runs from an ASCII path wherever the app is installed.

Since the desktop backend became a onedir folder, ``pginstall`` sits inside the
install directory. Installed under a path with non-ASCII characters on a
hosted runner, initdb could not re-execute itself ("could not re-execute with restricted
token", "program postgres is needed by initdb but was not found") and the app
never started, so 18.5.0 refused such folders in the installer. The backend now
copies the binaries to an ASCII location and points pixeltable-pgserver at the
copy, which lets the installer accept any folder again.

The tests build a fake ``pginstall`` under non-ASCII paths in several scripts and check where
every binding the library and this module read ends up pointing, and that a
copy under ProgramData, where every local user may create folders, is never
reused and never left writable by others.
"""

from __future__ import annotations

from pathlib import Path

import pixeltable_pgserver.pgexec as pg_pgexec
import pixeltable_pgserver.postgres_server as pg_server
import pixeltable_pgserver.utils as pg_utils
import pytest

from app.core import embedded_pg

_FILES = {
    "bin/postgres.exe": b"MZ postgres",
    "bin/initdb.exe": b"MZ initdb",
    "lib/postgresql/vector.dll": b"MZ vector",
    "share/postgresql/postgres.bki": b"bki",
}
_BINDINGS = (pg_utils, pg_server, pg_pgexec)

#: Install folders in several scripts, each with a space, as people name them.
_NON_ASCII_FOLDERS = {
    "cyrillic": "Тестовая папка",
    "cjk": "测试 文件夹",
    "accented-latin": "Dossier d'essai é",
    "arabic": "مجلد الاختبار",
    "greek": "Φάκελος δοκιμής",
}
#: A user profile whose own path is not ASCII.
_NON_ASCII_PROFILE = "Пользователь 用户"


def _pginstall(root: Path) -> Path:
    install = root / "pginstall"
    for rel, data in _FILES.items():
        target = install / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return install


def _reset(install: Path) -> None:
    for module in _BINDINGS:
        module.POSTGRES_BIN_PATH = install / "bin"


@pytest.fixture(params=sorted(_NON_ASCII_FOLDERS), ids=sorted(_NON_ASCII_FOLDERS))
def install(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    install = _pginstall(tmp_path / _NON_ASCII_FOLDERS[request.param] / "server")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    (tmp_path / "ProgramData").mkdir()
    monkeypatch.setattr(embedded_pg, "bundled_binaries_must_be_ascii", lambda: True)
    for module in _BINDINGS:
        monkeypatch.setattr(module, "POSTGRES_BIN_PATH", install / "bin")
    return install


def test_a_non_ascii_install_runs_postgres_from_a_copy_in_local_app_data(install: Path, tmp_path: Path) -> None:
    bin_dir = embedded_pg.relocate_bundled_binaries()

    assert bin_dir is not None
    assert str(bin_dir).isascii()
    assert bin_dir.is_relative_to(tmp_path / "Local" / "OpenConstructionERP" / "pginstall")
    for rel, data in _FILES.items():
        assert (bin_dir.parent / rel).read_bytes() == data
    # Every binding the library reads, plus the one this module reads per call.
    for module in _BINDINGS:
        assert bin_dir == module.POSTGRES_BIN_PATH
    assert embedded_pg._bundled_install_dir() == bin_dir.parent
    # The original stays where the installer put it, and ProgramData is untouched.
    assert (install / "bin" / "postgres.exe").is_file()
    assert not any((tmp_path / "ProgramData").iterdir())


def test_the_private_copy_is_reused_and_replaced_when_the_install_changes(install: Path) -> None:
    first = embedded_pg.relocate_bundled_binaries()
    assert first is not None
    marker = first / "left-by-a-previous-start"
    marker.write_bytes(b"")

    _reset(install)
    assert embedded_pg.relocate_bundled_binaries() == first
    assert marker.exists(), "an unchanged install was copied a second time"

    # An upgrade ships a different file: a new copy, and the old one is tidied.
    (install / "lib" / "postgresql" / "vector.dll").write_bytes(b"MZ vector 0.9")
    _reset(install)
    upgraded = embedded_pg.relocate_bundled_binaries()
    assert upgraded is not None
    assert upgraded != first
    assert (upgraded.parent / "lib" / "postgresql" / "vector.dll").read_bytes() == b"MZ vector 0.9"
    assert not first.parent.exists()


def test_staging_left_by_a_dead_start_is_removed_and_a_live_ones_is_not(
    install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "Local" / "OpenConstructionERP" / "pginstall"
    dead = home / ".0123456789abcdef.111.tmp"
    live = home / ".0123456789abcdef.222.tmp"
    for staging in (dead, live):
        staging.mkdir(parents=True)
    monkeypatch.setattr(embedded_pg, "_pid_alive", lambda pid: pid == 222)

    assert embedded_pg.relocate_bundled_binaries() is not None
    assert not dead.exists()
    assert live.exists()


def test_a_non_ascii_profile_gets_a_fresh_private_copy_under_program_data(
    install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / _NON_ASCII_PROFILE / "Local"))
    locked: list[Path] = []

    def lock(directory: Path) -> bool:
        # Locked while still empty, before any binary is copied into it.
        assert not any(directory.iterdir())
        locked.append(directory)
        return True

    monkeypatch.setattr(embedded_pg, "_restrict_to_current_user", lock)

    first = embedded_pg.relocate_bundled_binaries()
    assert first is not None
    assert str(first).isascii()
    assert first.parent.parent.parent == tmp_path / "ProgramData"
    assert locked == [first.parent.parent]
    assert (first / "postgres.exe").read_bytes() == _FILES["bin/postgres.exe"]

    # Nothing under ProgramData is trusted twice: the next start copies anew
    # into another directory and tidies the previous one.
    _reset(install)
    second = embedded_pg.relocate_bundled_binaries()
    assert second is not None
    assert second.parent.parent != first.parent.parent
    assert not first.parent.parent.exists()


def test_a_copy_that_cannot_be_made_private_is_not_used(
    install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / _NON_ASCII_PROFILE / "Local"))
    monkeypatch.setattr(embedded_pg, "_restrict_to_current_user", lambda _d: False)

    assert embedded_pg.relocate_bundled_binaries() is None
    assert install / "bin" == pg_utils.POSTGRES_BIN_PATH
    assert not any((tmp_path / "ProgramData").iterdir())


def test_an_ascii_install_is_left_where_it_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _pginstall(tmp_path / "Program Files" / "server")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(embedded_pg, "bundled_binaries_must_be_ascii", lambda: True)
    monkeypatch.setattr(pg_utils, "POSTGRES_BIN_PATH", install / "bin")

    assert str(tmp_path).isascii()
    assert embedded_pg.relocate_bundled_binaries() is None
    assert install / "bin" == pg_utils.POSTGRES_BIN_PATH
    assert not (tmp_path / "Local").exists()


def test_other_platforms_never_copy(install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_pg, "bundled_binaries_must_be_ascii", lambda: False)

    assert embedded_pg.relocate_bundled_binaries() is None
    assert install / "bin" == pg_utils.POSTGRES_BIN_PATH
    assert not (tmp_path / "Local").exists()


def test_a_failed_copy_keeps_the_original_and_leaves_no_half_tree(
    install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full_disk(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(embedded_pg.shutil, "copytree", full_disk)

    assert embedded_pg.relocate_bundled_binaries() is None
    assert install / "bin" == pg_utils.POSTGRES_BIN_PATH
    home = tmp_path / "Local" / "OpenConstructionERP" / "pginstall"
    assert not home.exists() or not any(home.iterdir())


def test_no_ascii_place_at_all_leaves_the_binaries_alone(
    install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / _NON_ASCII_PROFILE / "Local"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "Données 数据"))

    assert embedded_pg.relocate_bundled_binaries() is None
    assert install / "bin" == pg_utils.POSTGRES_BIN_PATH

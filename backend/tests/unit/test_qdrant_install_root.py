# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where the embedded vector service installs itself.

``app.core.storage.resolve_data_dir`` is documented as the single source of
truth for writable state, and every other component defers to it. The vector
supervisor did not: it took the account's home directory instead.

In a container those are different places. The image points ``OE_DATA_DIR`` at
a mounted volume while the home of the unprivileged account it runs as sits
inside the image, so the downloaded binary and its storage did not survive
recreating the container. Updating therefore looked like the service had
uninstalled itself and was asking to be installed again, which is what issue
#391 reported. Mounting a volume over the home path to make it persist fails
differently: Docker creates a volume for a path the image does not contain as
root-owned, and the unprivileged app cannot write into it.

The migration case matters as much as the fix. An operator who already has a
working install in the old location must keep it rather than be asked to
download the binary a second time.
"""

from __future__ import annotations

from pathlib import Path

from app.core.storage import resolve_data_dir
from app.modules.match_elements import qdrant_supervisor


def _redirect_home(monkeypatch, home: Path) -> None:
    """Point ``Path.home()`` at a throwaway directory for one test."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))


def test_the_install_root_follows_the_platform_data_dir(tmp_path, monkeypatch) -> None:
    """A configured data dir wins, so the install lands on the mounted volume."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    _redirect_home(monkeypatch, home)
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)

    assert qdrant_supervisor._resolve_qdrant_home() == data / "qdrant"


def test_an_existing_install_in_the_old_location_is_kept(tmp_path, monkeypatch) -> None:
    """Upgrading must not orphan a binary the operator already downloaded.

    Without this the fix would reproduce the very symptom it exists to remove:
    a service that was working before the update reporting itself as not
    installed afterwards.
    """
    home = tmp_path / "home"
    data = tmp_path / "data"
    legacy = home / ".openestimator" / "qdrant"
    legacy.mkdir(parents=True)
    (legacy / qdrant_supervisor._binary_name()).write_bytes(b"not really a binary")
    data.mkdir()
    _redirect_home(monkeypatch, home)
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)

    assert qdrant_supervisor._resolve_qdrant_home() == legacy


def test_the_new_location_wins_once_it_holds_a_binary(tmp_path, monkeypatch) -> None:
    """A stale empty directory in the old location must not pin the install.

    Only a real binary there counts. A leftover directory is not a reason to
    keep writing outside the volume.
    """
    home = tmp_path / "home"
    data = tmp_path / "data"
    legacy = home / ".openestimator" / "qdrant"
    legacy.mkdir(parents=True)
    resolved = data / "qdrant"
    resolved.mkdir(parents=True)
    (resolved / qdrant_supervisor._binary_name()).write_bytes(b"not really a binary")
    _redirect_home(monkeypatch, home)
    monkeypatch.setenv("OE_DATA_DIR", str(data))
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)

    assert qdrant_supervisor._resolve_qdrant_home() == resolved


def test_an_unconfigured_install_still_follows_the_platform(tmp_path, monkeypatch) -> None:
    """No environment variable is not a reason to go back to the home directory.

    Absent a legacy install there is nothing to migrate, so the resolver has to
    land wherever the rest of the platform writes: ``<repo>/data`` from a source
    checkout, ``~/.openestimate`` from an installed wheel. Note that neither of
    those is the old ``~/.openestimator`` this module used to pick - the two
    names differ by one letter and were never the same directory, which is part
    of why the divergence went unnoticed for so long.
    """
    home = tmp_path / "home"
    home.mkdir()
    _redirect_home(monkeypatch, home)
    monkeypatch.delenv("OE_DATA_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)

    resolved = qdrant_supervisor._resolve_qdrant_home()

    assert resolved == resolve_data_dir() / "qdrant"
    assert resolved != home / ".openestimator" / "qdrant"

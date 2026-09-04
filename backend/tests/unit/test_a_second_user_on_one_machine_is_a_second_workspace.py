"""One machine can hold two workspaces, and ``/api/health`` has to say which.

The desktop installer is per-machine, so one Windows box runs one copy of the
application for every account on it. Loopback is not per-session there: a
backend one user started is reachable, on 127.0.0.1, by every other user logged
into the same machine. The launcher probes a fixed list of loopback ports and
attaches to whatever answers ``/api/health`` as our version with no blocking
fault, and the frontend then bootstraps a desktop session against whatever it
was pointed at. Every one of those steps behaved as designed, and the result was
the second user signed into the first user's account, reading the first user's
data.

Nothing in that health body distinguished the two. ``version`` matched, because
it is the same install. ``instance_id`` is a fresh uuid4 per process
(``app.main:45``), so it is different for every backend including restarts of
the same one, which makes it useless as an identity: a launcher cannot tell "a
different account's backend" from "my own backend, restarted" by looking at it.

So the backend publishes a second field. It is the identity of the *data
directory*, not of the process: written once into the active data dir and read
back thereafter, so it survives a restart and differs exactly when the data
differs. That is the property the launcher needs, and the whole of it.

Two constraints on the value are asserted below as hard as its presence is.
``/api/health`` is unauthenticated - it answers anybody who can reach the port,
which on a server deployment is not only the person at the keyboard - so the id
must be opaque: never a path, never a user name, nothing that maps the machine
it came from. And it must be stable across restarts, since a value that changed
on every boot would send the launcher off to start a second backend against the
data directory the first one is already using.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

#: Where the identity lives inside the data directory. Pinned here rather than
#: imported: it is the contract between the backend that writes it and the
#: launcher that reads it (``desktop/src-tauri/src/main.rs``), and a rename on
#: one side only is precisely the failure this file exists to catch. The
#: launcher cannot import a Python constant, so the name is checked, not shared.
WORKSPACE_ID_FILENAME = "workspace_id.json"


def _health_payload(data_dir: Path, monkeypatch: MonkeyPatch) -> dict[str, Any]:
    """Ask ``/api/health`` the way the launcher does, from a given data dir.

    ``OE_CLI_DATA_DIR`` is what the CLI exports for the data directory it was
    told to serve (``app.cli:346``), and it is what the backend's own state
    resolution reads first, so setting it here is how a test says "this process
    is the install living in that folder".

    The application is built fresh for each call and the lifespan is
    deliberately not run: a restart is what is being modelled, and the id has to
    come back the same across two of them without any startup step having
    prepared it.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("OE_CLI_DATA_DIR", str(data_dir))
    app = create_app()
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    return response.json()


def test_the_health_body_names_the_workspace_it_serves(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The field the launcher's refusal is built on.

    Asserted first and on its own, because everything else here is a property
    *of* the value. Without the field there is nothing for a second user's
    launcher to compare against, and it attaches on version alone.
    """
    payload = _health_payload(tmp_path, monkeypatch)

    assert "workspace_id" in payload, "the health body carries no workspace identity to compare"
    workspace_id = payload["workspace_id"]
    assert isinstance(workspace_id, str)
    assert workspace_id, "an empty workspace id would compare equal between two accounts"


def test_the_identity_is_written_into_the_data_directory(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """It is the data directory's identity, so it is stored with the data.

    The launcher resolves the same directory and reads the same file, which is
    the entire mechanism: two processes agree because they are reading one file,
    not because they compute the same thing twice.
    """
    workspace_id = _health_payload(tmp_path, monkeypatch)["workspace_id"]

    path = tmp_path / WORKSPACE_ID_FILENAME
    assert path.exists(), f"nothing at {path} for the launcher to read"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["workspace_id"] == workspace_id


def test_the_identity_survives_a_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A second run of the same install answers with the same id.

    This is the property ``instance_id`` does not have and is the reason a
    second field was added rather than that one reused, so it is asserted
    across a genuine second interpreter rather than a second ``create_app()``.
    The distinction is not pedantry: ``_INSTANCE_ID`` is module level, computed
    once per interpreter, so two applications built in one process already share
    it, and any identity held in a module global or a cache would pass an
    in-process comparison while failing the only case the launcher cares about -
    the user closing the desktop app and opening it again.

    The child is pointed at the same source tree this process imported, and says
    which file it loaded so the assertion cannot be satisfied by a copy of the
    package installed in site-packages.
    """
    import subprocess
    import sys

    import app.main

    served = _health_payload(tmp_path, monkeypatch)["workspace_id"]

    # The directory the ``app`` package is imported from, which is ``backend``:
    # main.py is ``backend/app/main.py``, so its second parent is the one that
    # has to be on the child's path. Passed as PYTHONPATH *and* as the working
    # directory so the child resolves the same package wherever pytest was
    # started from - a copy of this package installed into site-packages is the
    # thing being guarded against, and cwd is not a defence against it.
    tree_root = Path(app.main.__file__).parents[1]
    env = dict(os.environ)
    env["OE_CLI_DATA_DIR"] = str(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join([str(tree_root), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    program = "import app.main as m; print(m.__file__); print(m._resolve_workspace_id())"

    completed = subprocess.run(  # noqa: S603 - our own interpreter, fixed argv
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tree_root),
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    loaded_from, restarted = (line.strip() for line in completed.stdout.strip().splitlines()[-2:])

    assert Path(loaded_from) == Path(app.main.__file__), "the second interpreter read a different copy of the code"
    assert restarted == served, "a restart of the same installation presents a different identity"


def test_two_data_directories_are_two_workspaces(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The defect itself, in the only terms the launcher can see it.

    Two accounts on one machine are two data directories under two home
    folders. If these two ids came back equal the launcher would attach across
    them and be right to, so nothing else in this change matters if this fails.
    """
    first_dir = tmp_path / "account-a"
    second_dir = tmp_path / "account-b"
    first_dir.mkdir()
    second_dir.mkdir()

    first = _health_payload(first_dir, monkeypatch)["workspace_id"]
    second = _health_payload(second_dir, monkeypatch)["workspace_id"]

    assert first != second, "two separate installs present one identity; a launcher cannot tell them apart"


def test_the_identity_describes_nobody(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Opaque, because this endpoint answers strangers.

    Not a style rule. On a deployment whose port is reachable, the body of an
    unauthenticated probe is readable by anyone who can reach it, so an id
    derived from the path or the account name would publish the operating
    system user of the machine and the layout of its disk. A random value
    identifies the workspace to the one caller that needs to compare it and
    tells everybody else nothing.
    """
    import getpass

    data_dir = tmp_path / "a-recognisable-folder-name"
    data_dir.mkdir()
    workspace_id = _health_payload(data_dir, monkeypatch)["workspace_id"]

    assert "a-recognisable-folder-name" not in workspace_id
    for separator in ("/", "\\", ":"):
        assert separator not in workspace_id, f"the id carries {separator!r} and reads like a path"
    try:
        account = getpass.getuser()
    except Exception:  # noqa: BLE001 - no account name to compare against is not a failure
        account = ""
    if account:
        assert account.lower() not in workspace_id.lower()


@pytest.mark.parametrize("attempt", [1, 2])
def test_an_existing_identity_is_read_and_never_replaced(
    tmp_path: Path, monkeypatch: MonkeyPatch, attempt: int
) -> None:
    """Whoever got there first wins, including when that was not this process.

    The launcher writes this file too, when it starts before any backend has.
    A backend that overwrote what it found would hand its own launcher a
    different id than the one that launcher is holding, and the pair would
    refuse to attach to each other. Run twice so the second pass meets a file
    this test's own first pass did not write.
    """
    planted = "00112233445566778899aabbccddeeff"
    (tmp_path / WORKSPACE_ID_FILENAME).write_text(
        json.dumps({"workspace_id": planted}),
        encoding="utf-8",
    )

    payload = _health_payload(tmp_path, monkeypatch)

    assert payload["workspace_id"] == planted, f"attempt {attempt}: the backend replaced an identity already on disk"

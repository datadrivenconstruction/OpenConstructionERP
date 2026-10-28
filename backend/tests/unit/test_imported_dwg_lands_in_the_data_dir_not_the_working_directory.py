# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One DWG root, and the project importer used to spell it a second way.

``dwg_takeoff`` writes and serves drawings under ``_dwg_data_base()``, which
defers to :func:`app.core.storage.resolve_data_dir`. Its docstring records why:
the body it replaced defaulted to ``<cwd>/data``, "never a member of
``safe_data_roots()`` and sensitive to the process CWD", which is what broke
drawings marked ready on standalone, Docker and macOS deployments.

Three declarations in :mod:`app.modules.projects` still carried that replaced
body - ``DATA_DIR`` or ``<cwd>/data``. Two are in ``bundle_import``: the
directory an imported drawing is extracted to, and the ``file_path`` written
into the database for it. The third is the root ``file_manager_service``
reports to a user asking where their files are. So a bundle import put the
drawing somewhere the module that serves it does not look, recorded that
location permanently, and then confirmed it.

Both assertions below run from a working directory that is NOT the repository
root, and the important ones run from two different ones: a single foreign
directory cannot distinguish an anchored path from a differently broken one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.storage import is_within_safe_root, resolve_data_dir
from app.modules.projects import bundle_import
from app.modules.projects.file_manager_service import resolve_storage_locations

ARC = "attachments/dwg/11111111-1111-1111-1111-111111111111/plan.dwg"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def two_foreign_directories(tmp_path: Path) -> tuple[Path, Path]:
    """A desktop install's program directory, and a service's state directory."""
    started_from = tmp_path / "program files" / "OpenConstructionERP"
    service_cwd = tmp_path / "var" / "lib" / "openestimate"
    started_from.mkdir(parents=True)
    service_cwd.mkdir(parents=True)
    return started_from, service_cwd


def test_an_imported_drawing_lands_in_the_same_place_from_two_foreign_directories(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    first, second = two_foreign_directories

    monkeypatch.chdir(first)
    from_first = bundle_import._target_path_for_attachment(ARC, PROJECT_ID, {})
    monkeypatch.chdir(second)
    from_second = bundle_import._target_path_for_attachment(ARC, PROJECT_ID, {})

    assert from_first == from_second, (
        f"an imported drawing lands in two different places depending on the working directory: "
        f"{from_first} from {first}, {from_second} from {second}"
    )
    assert Path(from_first) == resolve_data_dir() / "dwg_uploads" / "plan.dwg"


def test_an_imported_drawing_lands_where_the_download_route_may_serve_it(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    """This is the consequence, not a restatement of the previous assertion.

    ``safe_data_roots()`` never contains the working directory, so a drawing
    extracted below it is refused by the download gate however correct the
    database row looks.
    """
    monkeypatch.chdir(two_foreign_directories[0])

    target = bundle_import._target_path_for_attachment(ARC, PROJECT_ID, {})

    assert target is not None
    assert is_within_safe_root(Path(target)), f"the download route may not serve {target}"


def test_an_imported_drawing_follows_a_data_dir_the_operator_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, two_foreign_directories: tuple[Path, Path]
) -> None:
    """An anchor of its own that happens to agree today is not the same thing.

    The replaced body honoured ``DATA_DIR`` but not ``OE_DATA_DIR`` and not
    ``OE_CLI_DATA_DIR``, which is the variable the desktop build exports.
    """
    declared = tmp_path / "mounted disk" / "openestimate-data"
    monkeypatch.setenv("OE_DATA_DIR", str(declared))
    monkeypatch.chdir(two_foreign_directories[1])

    target = bundle_import._target_path_for_attachment(ARC, PROJECT_ID, {})

    assert target is not None
    assert Path(target) == declared / "dwg_uploads" / "plan.dwg"


def test_the_row_written_to_the_database_records_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    """The rewritten ``file_path`` is persisted, so a wrong value is not transient."""
    first, second = two_foreign_directories

    monkeypatch.chdir(first)
    from_first = bundle_import._rewrite_paths_for_target(
        "dwg_drawings", [{"file_path": "/srv/source-host/data/dwg_uploads/plan.dwg"}], PROJECT_ID, {}
    )[0]["file_path"]
    monkeypatch.chdir(second)
    from_second = bundle_import._rewrite_paths_for_target(
        "dwg_drawings", [{"file_path": "/srv/source-host/data/dwg_uploads/plan.dwg"}], PROJECT_ID, {}
    )[0]["file_path"]

    assert from_first == from_second, (
        f"the database would record two different locations for the same import: {from_first} / {from_second}"
    )
    assert Path(from_first) == resolve_data_dir() / "dwg_uploads" / "plan.dwg"


def test_the_file_manager_reports_the_root_the_drawings_are_actually_in(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    """This function exists to tell a user where their files are.

    Reporting a directory derived from the working directory answers a question
    about the process rather than about the files, and it is wrong in the one
    situation a user asks: when the files are not where they expected.
    """
    first, second = two_foreign_directories

    monkeypatch.chdir(first)
    from_first = resolve_storage_locations(PROJECT_ID, "Demo project").dwg_root
    monkeypatch.chdir(second)
    from_second = resolve_storage_locations(PROJECT_ID, "Demo project").dwg_root

    assert from_first == from_second, (
        f"the file manager names two different DWG roots depending on the working directory: "
        f"{from_first} from {first}, {from_second} from {second}"
    )
    # The reported root has to be the root the importer actually writes to.
    target = bundle_import._target_path_for_attachment(ARC, PROJECT_ID, {})
    assert target is not None
    assert Path(from_first or "") == Path(target).parent

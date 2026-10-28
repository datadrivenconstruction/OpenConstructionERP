# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The catalog export must name the same two files from any working directory.

``app.scripts.export_full_catalog`` used to build both its input and its output
path on ``os.getcwd()``, so the same command read and wrote a different tree
depending on where the operator happened to stand. Run from ``backend/`` it
worked; run from the repository root the read failed; run from a directory two
levels under a sibling checkout the read succeeded and the export landed in
somebody else's tree.

Every assertion here therefore runs from a working directory that is NOT the
repository root, and the important ones run from TWO such directories: a single
foreign directory cannot tell an anchored path from a differently broken one,
because both are simply "not where I am standing".

The resolvers are called directly rather than through :func:`main`, on purpose.
``main`` needs a private parquet tree that does not exist on CI, and it
overwrites version-controlled files under ``data/catalog`` - a test must not do
either. What is under test is where the paths point, and that is the resolvers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.scripts import export_full_catalog as export


@pytest.fixture
def two_foreign_directories(tmp_path: Path) -> tuple[Path, Path]:
    """Two directories that are neither the repository root nor each other.

    The names are the shapes this actually breaks under: a desktop install
    started from its program directory, and a service started by an init system
    whose working directory is its state directory.
    """
    started_from = tmp_path / "program files" / "OpenConstructionERP"
    service_cwd = tmp_path / "var" / "lib" / "openestimate"
    started_from.mkdir(parents=True)
    service_cwd.mkdir(parents=True)
    return started_from, service_cwd


def test_the_output_directory_is_identical_from_two_foreign_working_directories(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    first, second = two_foreign_directories

    monkeypatch.chdir(first)
    from_first = export._catalog_output_dir()
    monkeypatch.chdir(second)
    from_second = export._catalog_output_dir()

    assert from_first.is_absolute(), f"the export would write to a relative path: {from_first}"
    assert from_first == from_second, (
        f"the export writes to two different places depending on the working directory: "
        f"{from_first} from {first}, {from_second} from {second}"
    )
    # Not merely "elsewhere" - specifically not below either directory we stood
    # in, which is what a surviving cwd-relative segment would produce.
    for cwd in (first, second):
        assert cwd not in from_first.parents, f"the export followed the working directory into {cwd}"


def test_the_output_directory_answers_to_the_declared_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, two_foreign_directories: tuple[Path, Path]
) -> None:
    """It must go through the platform's data-dir declaration, not a private copy of it.

    An anchor of its own that happens to agree today would drift the first time
    an operator points ``OE_DATA_DIR`` at a persistent disk.
    """
    declared = tmp_path / "mounted disk" / "openestimate-data"
    monkeypatch.setenv("OE_DATA_DIR", str(declared))
    monkeypatch.chdir(two_foreign_directories[0])

    assert export._catalog_output_dir() == declared / "catalog"


def test_the_output_directory_is_the_checkouts_own_data_dir(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    """Anchoring must not move the export for the one workflow that exists.

    The expected directory is derived here from the storage package's own
    location rather than by calling ``resolve_data_dir()``, because comparing
    the resolver against itself passes wherever either of them points.
    """
    import app.core.storage as storage

    package = Path(storage.__file__).resolve()
    if {"site-packages", "dist-packages"} & {part.lower() for part in package.parts}:
        pytest.skip("installed wheel: the data dir is the persistent per-user one by design")

    monkeypatch.delenv("OE_DATA_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)
    monkeypatch.chdir(two_foreign_directories[1])

    # app/core/storage.py -> parents[3] is the checkout root.
    assert export._catalog_output_dir() == package.parents[3] / "data" / "catalog"


def test_the_source_parquet_is_identical_from_two_foreign_working_directories(
    monkeypatch: pytest.MonkeyPatch, two_foreign_directories: tuple[Path, Path]
) -> None:
    first, second = two_foreign_directories

    monkeypatch.delenv("CWICR_TOOLKIT_ROOT", raising=False)
    monkeypatch.chdir(first)
    from_first = export._source_parquet_path()
    monkeypatch.chdir(second)
    from_second = export._source_parquet_path()

    assert from_first.is_absolute(), f"the export would read from a relative path: {from_first}"
    assert from_first == from_second, (
        f"the export reads two different files depending on the working directory: "
        f"{from_first} from {first}, {from_second} from {second}"
    )
    assert from_first.name.endswith(".parquet")


def test_the_source_parquet_answers_to_its_declared_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, two_foreign_directories: tuple[Path, Path]
) -> None:
    """The toolkit tree is not part of the product, so it needs a way to be named."""
    toolkit = tmp_path / "DDC_Toolkit"
    monkeypatch.setenv("CWICR_TOOLKIT_ROOT", str(toolkit))
    monkeypatch.chdir(two_foreign_directories[0])

    resolved = export._source_parquet_path()

    assert toolkit in resolved.parents, f"the declared toolkit root was ignored: {resolved}"


# ── The defect must not be able to come back ──────────────────────────────


_WORKING_DIRECTORY_CALLS = {"os.getcwd", "Path.cwd", "getcwd", "cwd"}


def working_directory_anchors(source: str) -> list[int]:
    """Return the line numbers where a path is anchored on the working directory.

    A regular expression over lines is not enough here: the original defect was
    an ``os.path.join`` whose first argument sat on a line of its own, four
    lines above the segment that made it a path. This reads the syntax instead.
    """
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            dotted = f"{ast.unparse(func.value)}.{func.attr}"
        elif isinstance(func, ast.Name):
            dotted = func.id
        else:
            continue
        if dotted in _WORKING_DIRECTORY_CALLS:
            found.append(node.lineno)
    return found


def test_no_path_in_the_export_is_anchored_on_the_working_directory() -> None:
    source = Path(export.__file__).read_text(encoding="utf-8")

    anchors = working_directory_anchors(source)

    assert anchors == [], f"{Path(export.__file__).name} anchors a path on the working directory at lines {anchors}"


def test_the_working_directory_scan_can_actually_fail() -> None:
    """Negative control: a scan that silently stops walking would pass vacuously.

    The synthetic defect is spelled the way the real one was - the call sits in
    the first argument of a multi-line ``os.path.join`` - so a scanner that only
    inspects the line it is standing on does not survive this.
    """
    planted = (
        "import os\n"
        "def main():\n"
        "    out = os.path.join(\n"
        "        os.getcwd(),\n"
        '        "..",\n'
        '        "data",\n'
        "    )\n"
        "    return out\n"
    )

    assert working_directory_anchors(planted) == [4]

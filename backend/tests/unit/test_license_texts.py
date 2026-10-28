"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The bundled licence texts, and the two layouts they have to be found in.

``app/core/licenses`` reaches every published artefact and, until the route
these tests cover, nothing in the backend could read it. What is checked here
is the locating, because that is the part with a branch no checkout exercises:
in a source tree the first candidate always answers, so a green run from the
repo says nothing at all about the frozen desktop build, which is the only
deployment the endpoint exists for.

None of this is a test of a real frozen bundle. It cannot be run from here.
What it does instead is hold the two halves of the frozen claim against each
other: the destination this module hardcodes, and the destination
``desktop/pyinstaller.spec`` actually ships to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.license_texts import (
    KNOWN_LICENSE_FILES,
    LicenseTextsUnavailable,
    license_dir,
    license_dir_for,
    list_license_texts,
    read_license_text,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = _REPO_ROOT / "desktop" / "pyinstaller.spec"


def test_known_files_and_directory_agree_both_ways() -> None:
    """A text added without a line here, or a line without a file, both fail.

    Two directions on purpose. Only checking that every known name exists lets
    a new text arrive unlisted, which weakens the content check that decides
    whether a candidate directory is ours.
    """
    on_disk = {p.name for p in license_dir().iterdir() if p.is_file() and not p.name.startswith(".")}
    assert set(KNOWN_LICENSE_FILES) == on_disk


def test_listing_names_every_file_present() -> None:
    listed = {item.name for item in list_license_texts()}
    on_disk = {p.name for p in license_dir().iterdir() if p.is_file() and not p.name.startswith(".")}
    assert listed == on_disk
    assert listed, "the directory is tracked in git and cannot legitimately be empty"


def test_each_text_reads_back_byte_for_byte() -> None:
    directory = license_dir()
    for item in list_license_texts():
        served = read_license_text(item.name)
        assert served is not None
        assert served == (directory / item.name).read_text(encoding="utf-8", errors="replace")
        assert item.size_bytes == (directory / item.name).stat().st_size


def test_title_comes_from_the_document_itself() -> None:
    """The title is lifted from the file, so a new text needs no table edited."""
    titles = {item.name: item.title for item in list_license_texts()}
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in titles["LICENSE_LGPL_3_0"]
    assert "GNU GENERAL PUBLIC LICENSE" in titles["LICENSE_GPL_3_0"]


def test_a_name_outside_the_listing_is_refused() -> None:
    """Direct calls, which is where a traversing name reaches this code on every OS.

    Over HTTP a forward slash is decoded into a path separator and the router
    declines the request before the handler sees it, so the slash forms below
    are only exercised here.
    """
    assert read_license_text("nonsense") is None
    assert read_license_text("../NOTICE") is None
    assert read_license_text("../../../NOTICE") is None
    assert read_license_text("..\\..\\..\\NOTICE") is None
    assert read_license_text(str(_REPO_ROOT / "NOTICE")) is None
    assert (_REPO_ROOT / "NOTICE").is_file(), "the names refused above have to name something real"


def test_a_directory_that_only_has_the_name_does_not_answer(tmp_path: Path) -> None:
    """Candidates are accepted on content, not on being called ``licenses``."""
    fake_module = tmp_path / "license_texts.py"
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses" / "README").write_text("not a licence", encoding="utf-8")
    with pytest.raises(LicenseTextsUnavailable):
        license_dir_for(fake_module, None)


def test_the_frozen_candidate_is_found_under_meipass(tmp_path: Path) -> None:
    """The branch a checkout can never reach: first candidate absent, _MEIPASS holds it.

    Synthetic, and deliberately so. It proves the resolver looks where the
    spec ships to; it does not prove a built bundle contains the files.
    """
    frozen = tmp_path / "meipass"
    bundled = frozen / "app" / "core" / "licenses"
    bundled.mkdir(parents=True)
    (bundled / KNOWN_LICENSE_FILES[0]).write_text("text", encoding="utf-8")

    elsewhere = tmp_path / "not_the_source_tree" / "license_texts.py"
    elsewhere.parent.mkdir(parents=True)

    assert license_dir_for(elsewhere, str(frozen)) == bundled

    # Negative control: without _MEIPASS the same layout is unfindable, so the
    # assertion above is about the frozen candidate and not about tmp_path
    # happening to be reachable some other way.
    with pytest.raises(LicenseTextsUnavailable):
        license_dir_for(elsewhere, None)


def test_the_spec_ships_the_app_tree_to_the_destination_we_resolve() -> None:
    """Hold the hardcoded ``_MEIPASS/app/core`` against the spec's own datas entry.

    The resolver's frozen candidate is only right for as long as
    ``pyinstaller.spec`` keeps shipping ``backend/app`` to ``app``. Change that
    destination and every licence becomes unreadable in the desktop build with
    nothing to read about it, so the pair is checked rather than assumed.
    """
    spec = _SPEC.read_text(encoding="utf-8")
    assert re.search(r'datas\.append\(\(str\(BACKEND\s*/\s*"app"\),\s*"app"\)\)', spec), (
        "pyinstaller.spec no longer ships backend/app to the bundle destination 'app'; "
        "app/core/license_texts.py resolves sys._MEIPASS/app/core/licenses and has to follow"
    )


def test_a_missing_directory_raises_rather_than_returning_nothing() -> None:
    """An empty list would read as "this build carries no licences", which is a lie."""
    missing = Path(__file__).resolve().parent / "no_such_place" / "license_texts.py"
    with pytest.raises(LicenseTextsUnavailable) as excinfo:
        license_dir_for(missing, None)
    # The message has to name where it looked, or a packaging fault is
    # unactionable for whoever reads the log.
    assert "no_such_place" in str(excinfo.value)

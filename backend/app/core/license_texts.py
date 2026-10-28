# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locate and read the licence texts that ship inside the application.

``app/core/licenses`` holds the verbatim texts of the licences our bundled
third-party libraries are under: LGPL-3.0 and LGPL-2.1 for the libraries
NOTICE lists, GPL-3.0 because LGPL-3.0 is written as additional permissions on
top of it and asks for both, and the OpenSSL, SSLeay, HarfBuzz and PostgreSQL
texts for the native binaries that arrive inside other packages' wheels.

They were committed there because that directory was measured to reach every
published artefact: the whole ``app`` tree is staged as data by
``desktop/pyinstaller.spec`` and force-included in the wheel. What was missing
is any way to read them from the running product. Nothing in the backend
imported this directory at all, so the texts travelled with every install and
no user could see one. That matters most in the desktop build with no network,
where a link to gnu.org is a link to nothing, and that is exactly the
deployment where someone is most likely to be looking for them.

Locating the directory
----------------------
Two candidates, tried in order and both validated by content rather than by
name. The first is the directory beside this module, which is right in a
checkout and after ``pip install`` because the data sits inside the package.
The second is ``app/core/licenses`` under ``sys._MEIPASS``, which is where the
frozen desktop build extracts it; that one is listed explicitly rather than
relied upon through ``__file__``, because a module inside a PyInstaller
archive has no file on disk and the value of its ``__file__`` is a detail of
the bundler rather than a promise.

The ``app/`` in that second candidate is not a guess. ``desktop/pyinstaller.spec``
ships ``backend/app`` to the bundle destination ``app``, so everything inside
``backend/app/core`` arrives under ``sys._MEIPASS/app/core``.
``tests/unit/test_license_texts.py`` reads that entry back out of the spec, so
the day somebody changes the destination this stops being true in a test
rather than in a desktop build nobody can read a licence from.

No third candidate walks upwards. Reaching a directory by counting parents is
the arithmetic that ``app/core/match_service/data_paths.py`` exists to replace,
and it has been wrong here three times before in this codebase. What is
borrowed from that module is the shape rather than the code: explicit
candidates instead of a parent count, each accepted on content rather than on
its name, and resolved per call rather than frozen at import. Its own helper
does not fit, because it locates data sitting NEXT TO the ``app`` package and
these texts sit inside it.

Failing loudly
--------------
A missing directory raises :class:`LicenseTextsUnavailable` rather than
returning an empty list. An empty list is indistinguishable from a build that
carries no licences, and a caller that renders it shows a licence panel with
nothing in it, which is worse than an error because it reads as a statement
that there is nothing to show.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DIR_NAME = "licenses"

#: Every licence text tracked in the source tree. Public so a test can assert
#: this tuple and the directory agree in both directions: a text added to the
#: tree without a line here, or a line here without a file, are both the kind
#: of drift that makes the shape check weaker without anyone noticing.
KNOWN_LICENSE_FILES: tuple[str, ...] = (
    "LICENSE_GPL_3_0",
    "LICENSE_HARFBUZZ",
    "LICENSE_LGPL_2_1",
    "LICENSE_LGPL_3_0",
    "LICENSE_OPENSSL",
    "LICENSE_OPENSSL_SSLEAY",
    "LICENSE_POSTGRESQL",
)

#: Longest title we will lift out of a document's own first line.
_MAX_TITLE = 120


class LicenseTextsUnavailable(RuntimeError):
    """The bundled licence directory could not be found in this installation."""


@dataclass(frozen=True)
class LicenseText:
    """One licence text, as the API describes it.

    Attributes:
        name: The file name, which is the identifier a caller asks for. It is
            also what the panel shows, so that a text added later needs no
            change anywhere else.
        title: The document's own first non-empty line, trimmed. Taken from
            the file rather than from a table of our own, because a table has
            to be edited for every new text and this does not.
        size_bytes: Length of the file on disk, so a caller can warn before
            opening thirty-five kilobytes of GPL on a phone.
    """

    name: str
    title: str
    size_bytes: int


def _candidate_dirs(module_file: Path, meipass: str | None) -> list[Path]:
    """Return the places this directory can be, most likely first.

    Args:
        module_file: This module's ``__file__``. The licence texts sit beside
            it in a checkout and after ``pip install``.
        meipass: ``sys._MEIPASS`` when running frozen, else ``None``.
    """
    candidates = [Path(module_file).resolve().parent / _DIR_NAME]
    if meipass:
        candidates.append(Path(meipass) / "app" / "core" / _DIR_NAME)
    return candidates


def _looks_like_ours(directory: Path) -> bool:
    """True when ``directory`` holds at least one licence text we know of.

    Checked by content rather than by name so that a directory which merely
    happens to be called ``licenses`` cannot answer for the real one.
    """
    return directory.is_dir() and any((directory / name).is_file() for name in KNOWN_LICENSE_FILES)


def license_dir_for(module_file: Path, meipass: str | None) -> Path:
    """Locate the licence directory for a given install layout.

    The seam exists for the same reason the one in
    ``app/core/match_service/data_paths.py`` does: the frozen layout is the
    only one that has ever been wrong, and a test run from a checkout passes
    whatever the frozen branch does, because the first candidate answers
    first. Pointing this at a synthetic ``_MEIPASS`` is the only way to cover
    it from here. Production callers want :func:`license_dir`.

    Args:
        module_file: This module's ``__file__``.
        meipass: ``sys._MEIPASS`` when running frozen, else ``None``.

    Returns:
        The resolved directory.

    Raises:
        LicenseTextsUnavailable: No candidate held any known licence text.
    """
    tried = _candidate_dirs(module_file, meipass)
    for candidate in tried:
        if _looks_like_ours(candidate):
            return candidate
    logger.error("bundled licence texts not found, looked in: %s", ", ".join(str(p) for p in tried))
    raise LicenseTextsUnavailable(
        "The bundled licence texts are not present in this installation. Looked in: " + ", ".join(str(p) for p in tried)
    )


def license_dir() -> Path:
    """Return the directory holding the bundled licence texts.

    Resolved per call rather than once at import, so a test that builds a
    layout and a process that is reloaded both see the truth rather than
    whatever the first import happened to find.

    Raises:
        LicenseTextsUnavailable: No candidate held any known licence text.
    """
    return license_dir_for(Path(__file__), getattr(sys, "_MEIPASS", None))


def _title_of(path: Path) -> str:
    """Return the document's first non-empty line, trimmed and capped."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    return stripped[:_MAX_TITLE]
    except OSError:
        logger.warning("could not read a title from %s", path)
    return path.name


def list_license_texts() -> list[LicenseText]:
    """Return every licence text in the bundle, sorted by name.

    Enumerated from the directory rather than from :data:`KNOWN_LICENSE_FILES`,
    so a text committed later is served without anyone editing this module or
    the panel that reads it.

    Raises:
        LicenseTextsUnavailable: The directory could not be located.
    """
    directory = license_dir()
    texts = [
        LicenseText(name=entry.name, title=_title_of(entry), size_bytes=entry.stat().st_size)
        for entry in sorted(directory.iterdir())
        if entry.is_file() and not entry.name.startswith(".")
    ]
    return texts


def read_license_text(name: str) -> str | None:
    """Return the full text of one licence, or ``None`` when there is no such file.

    The path opened is taken from a listing of the directory and never built
    from ``name``, so there is no traversal question to answer: a request for
    ``../../NOTICE`` matches no entry in the listing and gets ``None`` for the
    same reason ``nonsense`` does.

    Args:
        name: The file name as :func:`list_license_texts` reported it.

    Raises:
        LicenseTextsUnavailable: The directory could not be located.
    """
    directory = license_dir()
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.name == name:
            return entry.read_text(encoding="utf-8", errors="replace")
    return None

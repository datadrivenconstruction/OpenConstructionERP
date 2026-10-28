"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locate the match service's tuning data in a checkout, a wheel and a bundle.

``data/match`` holds four small files that tune matching without a code
deploy: two JSON profiles read by ``config.py`` and two YAML overlays read by
``region_language.py`` and ``boosts/region.py``. All four are optional by
design and every reader falls back to hardcoded constants when they are
absent, which is exactly what makes locating them worth its own module. The
fallback is silent and produces plausible results, so a resolver pointing at
the wrong directory raises nothing, logs nothing at warning level and changes
only the quality of the answers.

The three readers used to reach the repo root by counting fixed parent
directories, and counting only ever works in a source checkout. After ``pip
install`` the same count lands in the virtualenv's ``Lib``; in a frozen
desktop bundle it lands above ``sys._MEIPASS``. Neither holds the data, so
every packaged install has run on the hardcoded baseline for the whole life of
the feature and said so nowhere. This is the third time the same arithmetic
has been fixed in this codebase, after ``app/core/partner_pack/discovery.py``
and ``app/modules/catalog/router.py``.

It is replaced here rather than corrected, because a corrected count is still
a count and the next reader added at a different depth gets it wrong again.
Two of the three readers sat at one depth and the third at another, which is
how one of them kept a wrong constant while looking exactly like the others.
The depth is derivable instead: a module's dotted name states how many
directories separate its file from the top-level package, so
``app.core.match_service.config`` is three below ``app`` and
``app.core.match_service.boosts.region`` is four, whatever the tree above
``app`` looks like.

Two candidate roots are then tried, because a checkout puts the package one
level deeper than an install does. ``site-packages/app`` has the data directly
beside it, which is where ``backend/pyproject.toml`` force-includes it and
where ``desktop/pyinstaller.spec`` freezes it; ``backend/app`` has ``backend``
above it and the data at the repo root above that. Each candidate is checked
for content rather than for its name, so a directory that merely happens to be
called ``match`` cannot answer for the real one.

Resolved per call rather than once at import. An import-time constant freezes
whatever the process saw first, which is wrong for a test that builds a layout
and for any caller that reloads, and it was its own separate defect in the
catalogue fix.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_SUBPATH = ("data", "match")

# A candidate directory must hold at least one of these to be ours. Names
# rather than a count, so an install that ships a subset still resolves, and
# public so a test can assert this list and the tracked directory agree in
# both directions: a tuning file added without a line here would make the
# shape check weaker without anyone noticing.
KNOWN_DATA_FILES: tuple[str, ...] = (
    "encoder_profiles.json",
    "lex_thresholds.json",
    "region_groups.yaml",
    "region_language.yaml",
)


def _package_dir_of(module_file: Path, module_name: str) -> Path | None:
    """Return the top-level package directory ``module_name`` is installed under.

    Args:
        module_file: The calling module's ``__file__``.
        module_name: The calling module's dotted ``__name__``.

    Returns:
        The directory named by the first component of ``module_name``, or
        ``None`` when the name carries no package at all or the file is not
        nested deeply enough to satisfy it. A module run as ``__main__`` is
        the ordinary way to reach both of those.
    """
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    try:
        return module_file.resolve().parents[len(parts) - 2]
    except IndexError:
        return None


def _holds_match_data(candidate: Path) -> bool:
    """Return True when ``candidate`` actually holds tuning data, not just the name."""
    return candidate.is_dir() and any((candidate / name).is_file() for name in KNOWN_DATA_FILES)


def match_data_dir_for(module_file: Path, module_name: str) -> Path | None:
    """Locate ``data/match`` relative to where ``module_name`` is installed.

    The seam exists so a test can point the resolver at a synthetic install
    layout, which is the only way to cover the case that has been broken all
    along: in a source checkout the old arithmetic and this function agree,
    so a test run from the repo passes either way. Production callers want
    :func:`match_data_dir`.

    Args:
        module_file: The calling module's ``__file__``.
        module_name: The calling module's dotted ``__name__``.

    Returns:
        The data directory, or ``None`` when neither candidate root holds any
        known file.
    """
    package_dir = _package_dir_of(module_file, module_name)
    if package_dir is None:
        return None

    install_root = package_dir.parent
    candidates = [install_root.joinpath(*_DATA_SUBPATH), install_root.parent.joinpath(*_DATA_SUBPATH)]
    for candidate in candidates:
        if _holds_match_data(candidate):
            return candidate

    logger.debug(
        "MATCH data: no tuning data found, tried %s - readers fall back to hardcoded constants",
        " and ".join(str(candidate) for candidate in candidates),
    )
    return None


def match_data_dir() -> Path | None:
    """Return this install's tuning data directory, or ``None`` when it is absent."""
    return match_data_dir_for(Path(__file__), __name__)


def match_data_file(name: str) -> Path | None:
    """Return the path to one tuning file, or ``None`` when it is not shipped.

    Args:
        name: A file name inside ``data/match``, such as ``"lex_thresholds.json"``.

    Returns:
        The file path, or ``None`` when either the directory or the file is
        missing. ``None`` means "not shipped" and callers fall back to their
        hardcoded constants; that is a supported state for a minimal install
        and not an error.
    """
    directory = match_data_dir()
    if directory is None:
        return None

    path = directory / name
    if not path.is_file():
        logger.debug("MATCH data: %s is not in %s - falling back to hardcoded constants", name, directory)
        return None
    return path

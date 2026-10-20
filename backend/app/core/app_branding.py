# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persisted white-label branding (workspace logo / company name).

The in-app branding editor used to keep the customisation in the browser's
localStorage only, so it never followed the workspace: a teammate opening the
app from another browser, or an invited user landing on the login page, saw the
default OpenConstructionERP brand instead of the workspace's own (issue #272).

This stores the workspace branding once on the server, in a small JSON file in
the data dir::

    <data-dir>/app_branding.json   ->   {"mode": "logo", "logo_data_url": "...", "company_name": "",
                                         "appearance": {"accent": "teal", "density": "compact",
                                                        "menu": {"view": "compact", "color": "accent"}}}

so every browser and every invited user sees the same brand. A PUBLIC endpoint
reads it (the login page has no token yet) and an admin-only endpoint writes it.

stdlib-only and modelled on :mod:`app.core.demo_seed` so it stays cheap to
import and reuses the same data-dir resolution.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.demo_seed import resolve_data_dir

logger = logging.getLogger(__name__)

#: File name of the persisted branding, relative to the data dir.
BRANDING_FILENAME = "app_branding.json"

#: The three branding modes the frontend understands.
VALID_MODES = ("default", "logo", "text")

#: Company-name cap - mirrors the frontend input limit.
MAX_COMPANY_NAME = 60

#: A 2 MB raw logo (the frontend upload cap) base64-expands to ~2.7 MB; allow a
#: little above that so a valid upload is never rejected, but bound it so a
#: hostile payload cannot bloat the file or the public response without limit.
MAX_LOGO_DATA_URL_CHARS = 4 * 1024 * 1024

#: Allowed values of the workspace UI appearance default, one tuple per axis.
#: Mirrors ``frontend/src/stores/useAppearanceStore.ts``; the first value of
#: each tuple is the platform default.
APPEARANCE_OPTIONS: dict[str, tuple[str, ...]] = {
    "accent": ("blue", "teal", "violet", "emerald", "amber", "graphite", "crimson"),
    "font": ("system", "inter", "ibm-plex-sans", "source-sans-3"),
    "density": ("comfortable", "compact"),
    "radius": ("standard", "sharp", "round"),
}

#: Allowed values of the workspace menu look (``appearance.menu``), one tuple
#: per axis. Mirrors ``frontend/src/shared/lib/menuAppearance.ts``. Per-item
#: icon overrides are personal and never stored here.
MENU_OPTIONS: dict[str, tuple[str, ...]] = {
    "view": ("classic", "compact", "comfortable", "rail", "floating"),
    "active": ("bar", "pill", "tint"),
    "headers": ("caps", "divider", "none"),
    "stroke": ("light", "regular", "bold"),
    "container": ("none", "tile", "circle"),
    "color": ("mono", "accent", "sections"),
    "icons": ("shown", "hidden"),
}

#: Shape returned when nothing has been customised.
DEFAULT_BRANDING: dict[str, Any] = {
    "mode": "default",
    "logo_data_url": None,
    "logo_png_data_url": None,
    "company_name": "",
    "appearance": None,
}


def _pick(data: dict[str, Any], options: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {axis: data[axis] for axis, allowed in options.items() if data.get(axis) in allowed}


def sanitise_menu(data: Any) -> dict[str, str] | None:
    """Keep only known menu axes with allowed values; ``None`` when nothing is left."""
    if not isinstance(data, dict):
        return None
    return _pick(data, MENU_OPTIONS) or None


def sanitise_appearance(data: Any) -> dict[str, Any] | None:
    """Keep only known axes with allowed values; ``None`` when nothing is left.

    An axis left out means "platform default" for that axis, so a workspace can
    pin the accent alone and leave the rest to each user's device. The menu
    look rides along under ``menu`` with the same rule.
    """
    if not isinstance(data, dict):
        return None
    clean: dict[str, Any] = _pick(data, APPEARANCE_OPTIONS)
    menu = sanitise_menu(data.get("menu"))
    if menu:
        clean["menu"] = menu
    return clean or None


def branding_path(data_dir: Path | None = None) -> Path:
    """Return the path of the persisted branding file."""
    base = Path(data_dir).expanduser() if data_dir is not None else resolve_data_dir()
    return base / BRANDING_FILENAME


def sanitise(data: Any) -> dict[str, Any]:
    """Coerce arbitrary stored / submitted data into a safe branding dict.

    Defends both the read path (a hand-edited or corrupt file) and the write
    path (an API payload): the logo must be an ``image/*`` data URL within the
    size cap, the name is trimmed and capped, and ``mode`` is reconciled with
    the payload so the three fields can never disagree (a logo wins; ``text``
    needs a name, otherwise it falls back to ``default``).
    """
    if not isinstance(data, dict):
        return dict(DEFAULT_BRANDING)

    logo = data.get("logo_data_url")
    if not (isinstance(logo, str) and logo.startswith("data:image/") and len(logo) <= MAX_LOGO_DATA_URL_CHARS):
        logo = None

    # PDFs print an SVG logo from the PNG the browser rasterised it to.
    png = data.get("logo_png_data_url")
    if not (
        logo
        and logo.startswith("data:image/svg+xml")
        and isinstance(png, str)
        and png.startswith("data:image/png;base64,")
        and len(png) <= MAX_LOGO_DATA_URL_CHARS
    ):
        png = None

    name = data.get("company_name")
    name = name.strip()[:MAX_COMPANY_NAME] if isinstance(name, str) else ""

    mode = data.get("mode")
    if mode not in VALID_MODES:
        mode = "default"
    # Reconcile mode with the actual content so the trio is always consistent.
    if logo:
        mode = "logo"
    elif mode == "logo":  # claimed a logo but none survived validation
        mode = "text" if name else "default"
    elif mode == "text" and not name:
        mode = "default"

    return {
        "mode": mode,
        "logo_data_url": logo,
        "logo_png_data_url": png,
        "company_name": name,
        "appearance": sanitise_appearance(data.get("appearance")),
    }


#: Process-local cache of the parsed branding, keyed by file path. A PDF export
#: reads the branding several times per page (header logo + footer brand +
#: document metadata) and the logo data URL can be megabytes, so re-reading and
#: re-parsing the file every time is wasteful.
#:
#: The stamp is modification time *and* size, and both writers drop the entry
#: outright. Modification time alone is not enough: Windows hands two writes in
#: the same clock tick a byte-for-byte identical ``st_mtime_ns``, measured at
#: 139 collisions in 200 consecutive pairs, so a save landing in the same tick
#: as the one before it would leave this cache serving the previous logo and
#: company name to every export until some later save happened to move the
#: clock.
_branding_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def _forget_branding(data_dir: Path | None) -> None:
    """Drop any cached parse of the branding file.

    Called by both writers. A writer knows the content changed; leaving that
    knowledge to the clock is what the stamp above exists to survive.
    """
    _branding_cache.pop(str(branding_path(data_dir)), None)


def read_branding(data_dir: Path | None = None) -> dict[str, Any]:
    """Return the stored branding, or defaults when none/corrupt.

    Cached per file path and invalidated by modification time, so repeated reads
    within a single PDF export (or across requests) avoid re-parsing a possibly
    multi-megabyte logo data URL while still reflecting an admin update promptly.
    A fresh ``dict`` is returned each call so callers can never mutate the cache.
    """
    path = branding_path(data_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _branding_cache.pop(key, None)
        return dict(DEFAULT_BRANDING)
    except OSError as exc:
        logger.warning("Could not stat branding at %s: %s", path, exc)
        return dict(DEFAULT_BRANDING)
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _branding_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _branding_cache.pop(key, None)
        return dict(DEFAULT_BRANDING)
    except OSError as exc:
        logger.warning("Could not read branding at %s: %s", path, exc)
        return dict(DEFAULT_BRANDING)
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring corrupt branding file at %s", path)
        return dict(DEFAULT_BRANDING)
    clean = sanitise(data)
    _branding_cache[key] = (stamp, dict(clean))
    return dict(clean)


def write_branding(payload: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """Persist (sanitised) branding and return what was stored.

    Best-effort write: a failed write still returns the sanitised payload so the
    caller's response stays consistent, but the change won't survive a restart.
    A payload that sanitises to the default clears any custom branding instead of
    writing an empty marker file.
    """
    clean = sanitise(payload)
    if clean == DEFAULT_BRANDING:
        return reset_branding(data_dir)
    path = branding_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist branding at %s: %s", path, exc)
    # Unconditionally, including after a failed write: the file is then
    # unchanged and forgetting it costs one re-read.
    _forget_branding(data_dir)
    return clean


def reset_branding(data_dir: Path | None = None) -> dict[str, Any]:
    """Clear any custom branding (remove the file). Returns the defaults."""
    path = branding_path(data_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove branding at %s: %s", path, exc)
    _forget_branding(data_dir)
    return dict(DEFAULT_BRANDING)

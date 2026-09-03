# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persisted white-label branding (workspace logo / company name).

The in-app branding editor used to keep the customisation in the browser's
localStorage only, so it never followed the workspace: a teammate opening the
app from another browser, or an invited user landing on the login page, saw the
default OpenConstructionERP brand instead of the workspace's own (issue #272).

This stores the workspace branding once on the server, in a small JSON file in
the data dir::

    <data-dir>/app_branding.json   ->   {"mode": "logo", "logo_data_url": "...", "company_name": ""}

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

#: Organisation-field caps.
MAX_ORG_NAME = 80
MAX_REFERENCE_PREFIX = 8
MAX_MAIL_DOMAINS = 300

#: Shape returned when nothing has been customised.
DEFAULT_BRANDING: dict[str, Any] = {
    "mode": "default",
    "logo_data_url": None,
    "company_name": "",
    # ── Organisation profile ─────────────────────────────────────────
    # The company facts other modules used to hard-code. Kept here so
    # the CODE stays generic and each workspace supplies its own:
    #   org_name         - full legal/trading name (email footers, PM org)
    #   reference_prefix - the house token on minted references
    #                      (<PREFIX>-RFI-24188-0001); A-Z/0-9 only
    #   own_mail_domains - comma-separated; inbound mail FROM these
    #                      domains is "somebody internal", not a reply
    "org_name": "",
    "reference_prefix": "",
    "own_mail_domains": "",
}


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

    org_name = data.get("org_name")
    org_name = org_name.strip()[:MAX_ORG_NAME] if isinstance(org_name, str) else ""

    # The prefix lands inside minted references and an inbound-matching
    # regex, so it tightens hard: A-Z/0-9 only, uppercased, bounded.
    prefix = data.get("reference_prefix")
    prefix = prefix.strip().upper() if isinstance(prefix, str) else ""
    prefix = "".join(c for c in prefix if c.isalnum())[:MAX_REFERENCE_PREFIX]

    domains = data.get("own_mail_domains")
    if isinstance(domains, str):
        parts = []
        for raw_part in domains.lower().split(","):
            part = raw_part.strip().lstrip("@")
            # A domain, not an essay: letters/digits/dots/hyphens with a dot.
            if part and "." in part and all(c.isalnum() or c in ".-" for c in part):
                parts.append(part)
        domains = ",".join(parts)[:MAX_MAIL_DOMAINS]
    else:
        domains = ""

    return {
        "mode": mode,
        "logo_data_url": logo,
        "company_name": name,
        "org_name": org_name,
        "reference_prefix": prefix,
        "own_mail_domains": domains,
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


def merge_branding(update: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """Persist ``update`` merged over what is stored.

    The admin editor sends just what changed (its docstring promises so),
    and a raw ``write_branding`` of a partial payload would sanitise the
    missing fields to their defaults - wiping the stored logo the moment
    someone saved the organisation tab. Merge first, sanitise after.
    """
    merged = {**read_branding(data_dir), **(update if isinstance(update, dict) else {})}
    return write_branding(merged, data_dir)


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


# ── Organisation accessors ─────────────────────────────────────────────
# One resolution rule for every module that needs a company fact:
# the workspace's stored branding wins, an environment variable covers
# headless/scripted deployments, and the fallback is neutral - the code
# itself never carries a company.

import os as _os


def org_reference_prefix(data_dir: Path | None = None) -> str:
    """The house token on minted references (<PREFIX>-RFI-...)."""
    stored = read_branding(data_dir).get("reference_prefix") or ""
    return stored or _os.environ.get("OE_REGISTER_HOUSE", "").strip().upper() or "REG"


def org_display_name(data_dir: Path | None = None) -> str:
    """The organisation's name for email footers and mail headers."""
    branding = read_branding(data_dir)
    stored = branding.get("org_name") or branding.get("company_name") or ""
    return stored or _os.environ.get("OE_PM_ORG", "").strip() or "Projects Team"


def org_mail_domains(data_dir: Path | None = None) -> list[str]:
    """Domains that count as 'our own' for inbound mail. May be empty -
    then nothing is treated as internal until the workspace says so."""
    stored = read_branding(data_dir).get("own_mail_domains") or ""
    raw = stored or _os.environ.get("OE_OUTLOOK_OWN_DOMAINS", "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persisted company profile - the letterhead printed on generated documents.

Some firms cannot send an RFI, a transmittal or a certificate without their
formal letterhead on it: the registered name, the address, the licence or
registration numbers, and the logo their lawyers approved. The workspace
already has a logo, but it is the wrong one for that job.
:mod:`app.core.app_branding` is the *app* brand - what the sidebar and the
login page show - and it is served by a PUBLIC endpoint, because the login page
reads it before anyone signs in. A registered address and a tax identifier have
no business on an anonymous endpoint, and the sidebar mark is often a cropped
or simplified version of the formal logo anyway.

So the company profile is a separate record in its own file::

    <data-dir>/company_profile.json

read only by signed-in users and written only by admins. Keeping it in its own
file, rather than as extra keys in the branding file, is what keeps it off the
public branding response: that endpoint serialises whatever the branding module
returns, and a field that is never in that file can never leak through it.

**Why every field is free text.** Letterheads are not a form the platform gets
to design. Address order differs by country (house number before or after the
street, postcode before or after the city, a state line or none), and the
identifiers a firm must print are jurisdiction-specific: a contractor licence
and an EIN in one place, a VAT number and a commercial register entry in
another. Any label this module printed for them would be a translation of
somebody else's legal term. The firm writes the lines exactly as they appear on
its paper and the PDF prints them verbatim.

**Nothing here raises.** Same contract as :mod:`app.core.pdf_appearance`: a
profile that cannot be read, or that a hand edit filled with nonsense, loses the
offending field and nothing else. A document a customer is waiting for must not
be lost to a malformed phone number.

stdlib-only and modelled on :mod:`app.core.pdf_appearance`, reusing the same
data-dir resolution, so it stays cheap to import and needs no migration.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.core.app_branding import MAX_LOGO_DATA_URL_CHARS
from app.core.demo_seed import resolve_data_dir

logger = logging.getLogger(__name__)

#: File name of the persisted profile, relative to the data dir.
COMPANY_PROFILE_FILENAME = "company_profile.json"

#: Image types the document logo may be. Raster types a PDF layer can embed,
#: plus SVG because formal logos are very often delivered as vector artwork.
#: The logo pattern below is built from this tuple and the options endpoint
#: serves it, so the upload form and the sanitiser cannot disagree.
LOGO_IMAGE_TYPES = ("png", "jpeg", "webp", "svg+xml")

#: Per-field caps for the single-line fields. Sized to what fits on one
#: letterhead line at the smallest page size, with room for the longest
#: registered company names seen in practice.
MAX_LEGAL_NAME = 120
MAX_REGISTRATION_LINE = 160
MAX_PHONE = 40
MAX_EMAIL = 120
MAX_WEBSITE = 120

#: The address block. Three lines covers street, city line and country in
#: every format we have seen; more than that pushes the document title down
#: the first page.
MAX_ADDRESS_LINES = 3
MAX_ADDRESS_CHARS = 240

#: ``data:image/<type>;base64,`` for the accepted types. Only the prefix is
#: checked, the body is not: a strict base64 alphabet would reject real uploads
#: that carry line wrapping or the URL-safe alphabet, and
#: :mod:`app.core.app_branding` deliberately stops at the prefix too.
_LOGO_PREFIX = re.compile(
    r"data:image/(?:" + "|".join(re.escape(kind) for kind in LOGO_IMAGE_TYPES) + r");base64,",
)

_PNG_PREFIX = "data:image/png;base64,"

#: Runs of whitespace, collapsed to one space inside a line.
_SPACES = re.compile(r"\s+")

#: The shape returned when nothing is set. Every value is ``""``, never
#: ``None``: consumers test fields for truthiness and concatenate them into
#: lines, and one shape for "unset" is one less branch in each of them.
DEFAULT_COMPANY_PROFILE: dict[str, str] = {
    "document_logo_data_url": "",
    "document_logo_png_data_url": "",
    "legal_name": "",
    "address": "",
    "registration_line": "",
    "phone": "",
    "email": "",
    "website": "",
}

#: The single-line fields and their caps.
_LINE_CAPS: dict[str, int] = {
    "legal_name": MAX_LEGAL_NAME,
    "registration_line": MAX_REGISTRATION_LINE,
    "phone": MAX_PHONE,
    "email": MAX_EMAIL,
    "website": MAX_WEBSITE,
}


def company_profile_path(data_dir: Path | None = None) -> Path:
    """Return the path of the persisted company profile file."""
    base = Path(data_dir).expanduser() if data_dir is not None else resolve_data_dir()
    return base / COMPANY_PROFILE_FILENAME


def _clean_line(value: str) -> str:
    """One printable line: control and line-break characters become spaces.

    They become spaces rather than vanishing so that "Acme\\nBuilders" pasted
    from a spreadsheet cell reads "Acme Builders", not "AcmeBuilders". A NUL
    or an escape sequence has no business on a letterhead either way.

    Format characters (``Cf``) are deliberately kept. The zero-width
    non-joiner is one of them and it is part of how names are spelled in
    Persian, Urdu and Hindi, all of which the platform ships; stripping the
    category would misspell a real firm's registered name.
    """
    kept = "".join(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch for ch in value)
    return _SPACES.sub(" ", kept).strip()


def _line(value: Any, cap: int) -> str:
    """A single-line field, cleaned and capped, or ``""`` when not a string."""
    if not isinstance(value, str):
        return ""
    return _clean_line(value)[:cap].rstrip()


def _address(value: Any) -> str:
    """The address block: up to three non-empty lines, as the firm wrote them.

    ``splitlines`` rather than ``split("\\n")`` because a browser textarea
    submits ``\\r\\n``. Lines past the third are dropped rather than merged
    into it: the form stops at three, so a fourth only arrives by hand edit,
    and merging would print a line the firm never wrote.
    """
    if not isinstance(value, str):
        return ""
    lines = [line for line in (_clean_line(raw) for raw in value.splitlines()) if line]
    return "\n".join(lines[:MAX_ADDRESS_LINES])[:MAX_ADDRESS_CHARS].rstrip()


def _logo(value: Any) -> str:
    """An accepted image data URL within the size cap, or ``""``."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > MAX_LOGO_DATA_URL_CHARS:
        return ""
    match = _LOGO_PREFIX.match(value)
    if match is None or match.end() == len(value):
        return ""
    return value


def svg_companion_png(logo: str, value: Any) -> str:
    """The PNG the browser rasterised an SVG ``logo`` to, or ``""``.

    PDFs are drawn from this PNG: the server does not rasterise SVG. It is
    kept only next to an SVG logo, so replacing the logo with a raster one
    cannot leave a stale picture behind for the documents.
    """
    if not (isinstance(value, str) and logo.startswith("data:image/svg+xml")):
        return ""
    value = value.strip()
    if len(value) > MAX_LOGO_DATA_URL_CHARS or not value.startswith(_PNG_PREFIX) or value == _PNG_PREFIX:
        return ""
    return value


def sanitise(data: Any) -> dict[str, str]:
    """Coerce arbitrary stored / submitted data into a safe company profile.

    Defends both the read path (a hand-edited or corrupt file) and the write
    path (an API payload). Every field is judged on its own, so one bad value
    costs only that value: a firm that sends an unsupported logo keeps its
    legal name and address. Over-long text is trimmed rather than refused,
    matching :mod:`app.core.pdf_appearance`.
    """
    if not isinstance(data, dict):
        return dict(DEFAULT_COMPANY_PROFILE)
    logo = _logo(data.get("document_logo_data_url"))
    clean = {
        "document_logo_data_url": logo,
        "document_logo_png_data_url": svg_companion_png(logo, data.get("document_logo_png_data_url")),
        "address": _address(data.get("address")),
    }
    for field, cap in _LINE_CAPS.items():
        clean[field] = _line(data.get(field), cap)
    return {field: clean[field] for field in DEFAULT_COMPANY_PROFILE}


def has_letterhead(profile: Any) -> bool:
    """Whether a document should carry a letterhead at all.

    The PDF layer draws the letterhead only when this is true, so a workspace
    that never filled the profile in keeps byte-identical documents after the
    upgrade.

    Only the legal name or the logo switches it on. An address, a phone
    number or a registration line on their own do not: a block of contact
    details with no name above it does not say whose they are. The settings
    form should say so next to the name field, because a firm that fills in
    everything except the name will otherwise see no letterhead and no reason.
    """
    if not isinstance(profile, dict):
        return False
    return any(
        isinstance(profile.get(field), str) and profile[field].strip()
        for field in ("legal_name", "document_logo_data_url")
    )


#: Process-local cache of the parsed profile, keyed by file path - the same
#: arrangement :mod:`app.core.pdf_appearance` uses, and needed more here: the
#: logo data URL can run to megabytes, and an export reads the profile for the
#: letterhead of every page.
#:
#: The stamp is modification time *and* size, and every writer drops the entry
#: outright, for the reason :mod:`app.core.pdf_appearance` records: Windows
#: gives two writes in the same clock tick an identical ``st_mtime_ns``, and
#: the PUT endpoint reads, merges and writes back, so a stale read would be
#: persisted and silently revert the save it shadowed.
_profile_cache: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}


def _forget_profile(data_dir: Path | None) -> None:
    """Drop any cached parse of the profile file.

    Called by every writer. A writer knows the content changed; leaving that
    knowledge to the clock is what the stamp above exists to survive.
    """
    _profile_cache.pop(str(company_profile_path(data_dir)), None)


def read_company_profile(data_dir: Path | None = None) -> dict[str, str]:
    """Return the stored company profile, or defaults when none/corrupt.

    A fresh ``dict`` is returned each call so callers can never mutate the
    cache. Never raises: every failure path logs and falls back.
    """
    path = company_profile_path(data_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _profile_cache.pop(key, None)
        return dict(DEFAULT_COMPANY_PROFILE)
    except OSError as exc:
        logger.warning("Could not stat company profile at %s: %s", path, exc)
        return dict(DEFAULT_COMPANY_PROFILE)
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _profile_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _profile_cache.pop(key, None)
        return dict(DEFAULT_COMPANY_PROFILE)
    except OSError as exc:
        logger.warning("Could not read company profile at %s: %s", path, exc)
        return dict(DEFAULT_COMPANY_PROFILE)
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring corrupt company profile file at %s", path)
        return dict(DEFAULT_COMPANY_PROFILE)
    clean = sanitise(data)
    _profile_cache[key] = (stamp, dict(clean))
    return dict(clean)


def write_company_profile(payload: Any, data_dir: Path | None = None) -> dict[str, str]:
    """Persist (sanitised) company profile and return what was stored.

    Best-effort write, mirroring :func:`app.core.pdf_appearance.write_appearance`:
    a failed write still returns the sanitised payload so the caller's response
    stays consistent. A payload that sanitises to all-empty removes the file
    instead of writing a record of nothing.
    """
    clean = sanitise(payload)
    if clean == DEFAULT_COMPANY_PROFILE:
        return reset_company_profile(data_dir)
    path = company_profile_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist company profile at %s: %s", path, exc)
    # Unconditionally, including after a failed write: the file is then
    # unchanged and forgetting it costs one re-read.
    _forget_profile(data_dir)
    return clean


def reset_company_profile(data_dir: Path | None = None) -> dict[str, str]:
    """Clear the company profile (remove the file). Returns the defaults."""
    path = company_profile_path(data_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove company profile at %s: %s", path, exc)
    _forget_profile(data_dir)
    return dict(DEFAULT_COMPANY_PROFILE)

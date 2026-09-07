# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persisted document appearance - how a generated PDF looks.

:mod:`app.core.pdf_branding` made *who* the document belongs to configurable
(the workspace logo and company name). It left the *look* hard-coded, and said
so: "Deferred follow-up (out of scope for this MVP, by design): a configurable
template engine - per-workspace margins / fonts / colours / header layout /
footer text". This module is that follow-up.

It stores the look once on the server, in a small JSON file next to the
branding one::

    <data-dir>/pdf_appearance.json

so every export from every browser produces the same document, and a workspace
that has set its own accent colour keeps it after a restart.

**What is configurable, and why exactly this set.** Every value here is one a
single shared layer can honour, so turning a knob changes every PDF the
platform generates rather than the handful of generators someone remembered to
wire:

* ``accent_color`` / ``footer_color`` - drawn by
  :func:`app.core.pdf_branding.branded_header_footer`.
* ``base_font_size`` - the body size the generator builds its styles from.
* ``logo_align`` - which side of the header the logo sits on.
* ``footer_text`` - replaces the default "Generated ..." line when set.
* ``show_page_numbers`` - some workspaces file these documents inside a larger
  bundle that carries its own pagination.
* ``page_size`` / ``margin_mm`` - read by the generator when it builds its
  document template.

**The typeface is deliberately NOT configurable, and this is the interesting
decision in the module.** The obvious knob to add here is a font family, and
the obvious way to offer it is reportlab's base-14 (Helvetica / Times /
Courier), which needs no font file. Those faces are Latin-1 only. This platform
prints in 40-odd locales and :mod:`app.core.pdf_fonts` exists precisely because
of that: it bundles DejaVu Sans for Cyrillic and Greek, references Adobe CID
packs for Chinese and Korean, and embeds Noto for Thai and Devanagari, then
funnels every face request through :func:`app.core.pdf_fonts.pdf_font` so a
generator asking for "Helvetica" gets the Unicode face instead.

Letting a workspace pick Times would route around all of that and print tofu on
every Russian contract and every Chinese receipt - a setting that looks
cosmetic and silently breaks half the product's locales, against principle #2.
Offering a *Unicode* serif or mono instead would mean bundling two more faces,
and the repository ships exactly one sans family on purpose.

So the size is configurable and the face is not. Anyone adding a family here
later needs a bundled Unicode face per option, not a base-14 name.

**Nothing here raises.** This mirrors the never-break contract of
:mod:`app.core.pdf_branding` and :mod:`app.core.pdf_stamp`: an appearance that
cannot be read, or that a hand edit filled with nonsense, falls back to the
platform default rather than failing an export. A document a customer is
waiting for must not be lost to a bad colour string.

stdlib-only and modelled on :mod:`app.core.app_branding`, reusing the same
data-dir resolution, so it stays cheap to import and needs no migration.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.demo_seed import resolve_data_dir
from app.core.paper_size import PAPER_SIZES as _PAPER_SIZES

logger = logging.getLogger(__name__)

#: File name of the persisted appearance, relative to the data dir.
APPEARANCE_FILENAME = "pdf_appearance.json"

#: Page sizes offered, in points, as reportlab spells them. A4 is the default
#: because the platform ships metric first; Letter and Legal cover the US.
#:
#: The dimensions are taken from :data:`app.core.paper_size.PAPER_SIZES` rather
#: than written again here. That module resolves the per-user Settings
#: preference and this one is the per-workspace appearance, so the two settings
#: are separate on purpose - but "A4" has to measure the same in both, and two
#: literal copies of the same three pairs is how it stops doing so. The
#: selection is still this module's own: A3 exists there and is deliberately
#: not offered here, because the workspace appearance is a look and a drawing
#: size is not part of one.
PAGE_SIZES: dict[str, tuple[float, float]] = {name: _PAPER_SIZES[name] for name in ("A4", "LETTER", "LEGAL")}

#: Where the header logo sits. The default is ``left`` because that is where
#: :func:`app.core.pdf_branding.branded_header_footer` has always drawn it, and
#: an upgrade must not silently move every workspace's logo across the page.
#: Note the sibling helper ``branded_header_logo`` defaults to ``right`` for its
#: own callers and is deliberately left alone: it exists for generators that
#: draw their own left-aligned title, so honouring this setting there would
#: push the logo underneath that title.
LOGO_ALIGNMENTS = ("left", "center", "right")

#: Body text bounds. Below 7pt a printed contract stops being readable; above
#: 14pt the tables in these documents no longer fit their columns.
MIN_FONT_SIZE = 7
MAX_FONT_SIZE = 14

#: Page margin bounds in millimetres. Below 8mm most office printers clip; above
#: 40mm the content column is too narrow for the wider tables.
MIN_MARGIN_MM = 8
MAX_MARGIN_MM = 40

#: Custom footer cap. Long enough for a company line with a registration number,
#: short enough to stay on one footer line at the smallest page size.
MAX_FOOTER_TEXT = 120

#: ``#rgb`` and ``#rrggbb``, the two forms the colour input emits.
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: The platform look, and the shape returned when nothing is customised.
#:
#: Every value is the one its consumer already hard-coded, so a workspace that
#: never opens the settings page sees byte-identical documents after the
#: upgrade: the two colours are :mod:`app.core.pdf_branding`'s former module
#: constants, and the size and margin are what
#: :mod:`app.modules.property_dev.document_templates` used (10pt body,
#: ``PAGE_MARGIN_MM = 25``). Changing a default here silently restyles every
#: document in every deployment, so treat these as fixed points.
DEFAULT_APPEARANCE: dict[str, Any] = {
    "accent_color": "#1a1a2e",
    "footer_color": "#999999",
    "base_font_size": 10,
    "page_size": "A4",
    "margin_mm": 25,
    "logo_align": "left",
    "footer_text": "",
    "show_page_numbers": True,
}


def appearance_path(data_dir: Path | None = None) -> Path:
    """Return the path of the persisted appearance file."""
    base = Path(data_dir).expanduser() if data_dir is not None else resolve_data_dir()
    return base / APPEARANCE_FILENAME


def _colour(value: Any, fallback: str) -> str:
    """A hex colour, or ``fallback`` when it is not one."""
    if isinstance(value, str) and _HEX_COLOR.match(value.strip()):
        return value.strip().lower()
    return fallback


def _bounded_int(value: Any, low: int, high: int, fallback: int) -> int:
    """An int clamped into ``[low, high]``, or ``fallback`` when not a number.

    ``bool`` is rejected before ``int`` because ``isinstance(True, int)`` is
    true in Python, and a JSON ``true`` arriving in a size field is a client
    bug, not a request for 1pt type.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return fallback
    return max(low, min(high, int(value)))


def sanitise(data: Any) -> dict[str, Any]:
    """Coerce arbitrary stored / submitted data into a safe appearance dict.

    Defends both the read path (a hand-edited or corrupt file) and the write
    path (an API payload). Every field falls back to its platform default
    independently, so one bad value costs only that value: a workspace that
    sends a valid accent colour and a nonsense page size keeps its colour.
    """
    if not isinstance(data, dict):
        return dict(DEFAULT_APPEARANCE)

    size_name = data.get("page_size")
    size_name = size_name.strip().upper() if isinstance(size_name, str) else ""
    if size_name not in PAGE_SIZES:
        size_name = DEFAULT_APPEARANCE["page_size"]

    align = data.get("logo_align")
    align = align.strip().lower() if isinstance(align, str) else ""
    if align not in LOGO_ALIGNMENTS:
        align = DEFAULT_APPEARANCE["logo_align"]

    footer = data.get("footer_text")
    footer = footer.strip()[:MAX_FOOTER_TEXT] if isinstance(footer, str) else ""

    numbers = data.get("show_page_numbers")
    if not isinstance(numbers, bool):
        numbers = DEFAULT_APPEARANCE["show_page_numbers"]

    return {
        "accent_color": _colour(data.get("accent_color"), DEFAULT_APPEARANCE["accent_color"]),
        "footer_color": _colour(data.get("footer_color"), DEFAULT_APPEARANCE["footer_color"]),
        "base_font_size": _bounded_int(
            data.get("base_font_size"), MIN_FONT_SIZE, MAX_FONT_SIZE, DEFAULT_APPEARANCE["base_font_size"]
        ),
        "page_size": size_name,
        "margin_mm": _bounded_int(data.get("margin_mm"), MIN_MARGIN_MM, MAX_MARGIN_MM, DEFAULT_APPEARANCE["margin_mm"]),
        "logo_align": align,
        "footer_text": footer,
        "show_page_numbers": numbers,
    }


#: Process-local cache of the parsed appearance, keyed by file path - the same
#: arrangement :mod:`app.core.app_branding` uses, and for the same reason: a
#: single export reads these values once per page for the header and again for
#: the footer.
#:
#: The stamp is modification time *and* size, and every writer drops the entry
#: outright. Modification time alone is not enough: Windows hands two writes in
#: the same clock tick a byte-for-byte identical ``st_mtime_ns``, measured at
#: 139 collisions in 200 consecutive pairs, so a save that lands in the same
#: tick as the one before it leaves a cache keyed on time alone convinced the
#: file never changed. That is not only a stale render - the PUT endpoint reads
#: this, merges the admin's fields over it and writes the result back, so a
#: stale read is persisted and silently reverts whatever the shadowed save had
#: changed.
_appearance_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def _forget_appearance(data_dir: Path | None) -> None:
    """Drop any cached parse of the appearance file.

    Called by every writer. A writer knows the content changed; leaving that
    knowledge to the clock is what the stamp above exists to survive.
    """
    _appearance_cache.pop(str(appearance_path(data_dir)), None)


def read_appearance(data_dir: Path | None = None) -> dict[str, Any]:
    """Return the stored appearance, or defaults when none/corrupt.

    A fresh ``dict`` is returned each call so callers can never mutate the
    cache. Never raises: every failure path logs and falls back.
    """
    path = appearance_path(data_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _appearance_cache.pop(key, None)
        return dict(DEFAULT_APPEARANCE)
    except OSError as exc:
        logger.warning("Could not stat document appearance at %s: %s", path, exc)
        return dict(DEFAULT_APPEARANCE)
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _appearance_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _appearance_cache.pop(key, None)
        return dict(DEFAULT_APPEARANCE)
    except OSError as exc:
        logger.warning("Could not read document appearance at %s: %s", path, exc)
        return dict(DEFAULT_APPEARANCE)
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring corrupt document appearance file at %s", path)
        return dict(DEFAULT_APPEARANCE)
    clean = sanitise(data)
    _appearance_cache[key] = (stamp, dict(clean))
    return dict(clean)


def write_appearance(payload: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """Persist (sanitised) appearance and return what was stored.

    Best-effort write, mirroring :func:`app.core.app_branding.write_branding`: a
    failed write still returns the sanitised payload so the caller's response
    stays consistent. A payload that sanitises to the platform default removes
    the file instead of writing a marker that says "same as default".
    """
    clean = sanitise(payload)
    if clean == DEFAULT_APPEARANCE:
        return reset_appearance(data_dir)
    path = appearance_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist document appearance at %s: %s", path, exc)
    # Unconditionally, including after a failed write: the file is then
    # unchanged and forgetting it costs one re-read.
    _forget_appearance(data_dir)
    return clean


def reset_appearance(data_dir: Path | None = None) -> dict[str, Any]:
    """Clear any custom appearance (remove the file). Returns the defaults."""
    path = appearance_path(data_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove document appearance at %s: %s", path, exc)
    _forget_appearance(data_dir)
    return dict(DEFAULT_APPEARANCE)


def resolve_page_size(appearance: dict[str, Any] | None = None) -> tuple[float, float]:
    """Return the (width, height) in points for the configured page size."""
    data = appearance if isinstance(appearance, dict) else read_appearance()
    name = data.get("page_size")
    if name not in PAGE_SIZES:
        name = DEFAULT_APPEARANCE["page_size"]
    return PAGE_SIZES[name]

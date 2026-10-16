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
* ``watermark_text`` - a word such as DRAFT or CONFIDENTIAL printed faintly
  across every page, drawn by the same page furniture as the footer. Empty by
  default, so nothing changes until a workspace types one.
* ``page_size`` / ``margin_mm`` - read by the generator when it builds its
  document template.
* ``show_letterhead`` - whether the company letterhead
  (:func:`app.core.pdf_branding.branded_letterhead`) heads the first page. On
  by default, which changes nothing for a workspace that has not filled in the
  company profile, because there is then no letterhead to draw; a firm that
  prints on pre-printed letterhead paper turns it off.

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

**Per document type.** On top of the workspace look, a document type (the RFI,
the pay application, the punch list, ...) can carry its own override, stored in
the same file under ``overrides``. :data:`DOCUMENT_TYPES` lists the types and,
for each, the fields its generator actually honours: a field the generator
never reads is not offered, because a setting that changes nothing reads as a
broken control. :func:`resolve_appearance` answers "how does this type look"
as the workspace look with the type's override laid over it; with no override
stored it returns exactly what :func:`read_appearance` does, so every document
prints as it did before overrides existed.

**Sections per document type.** A type whose generator prints optional parts
(the purchase order's terms, the invoice's payment history, a signature
block) lists them in :attr:`DocumentType.sections`, and a workspace may hide
any of them. The hidden ones are stored in the same file under
``hidden_sections``, apart from the look, because they say what a document
contains rather than how it looks; :func:`resolve_sections` is what a
generator asks. Every section prints until it is hidden.

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
import math
import re
from dataclasses import dataclass
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

#: Watermark cap. A watermark is one or two words read across the page at a
#: glance; a sentence there would have to be set too small to read as one.
MAX_WATERMARK_TEXT = 40

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
    "show_letterhead": True,
    "watermark_text": "",
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
    bug, not a request for 1pt type. So are NaN and the infinities, which
    Python's JSON parser accepts from a hand-edited file and ``int()`` refuses
    with an exception, which would break the never-raises contract.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return fallback
    if isinstance(value, float) and not math.isfinite(value):
        return fallback
    return max(low, min(high, int(value)))


def _clean_field(field: str, value: Any) -> Any:
    """``value`` as the sanitiser keeps it, or ``None`` when it is not usable.

    The one definition of a legal value per field, shared by :func:`sanitise`
    (an unusable value falls back to the platform default) and
    :func:`sanitise_override` (an unusable value is dropped, so the type
    inherits the workspace value instead). ``None`` is a safe marker because no
    field legally holds it.
    """
    # The empty-string and zero fallbacks below can never be legal values (no
    # colour is empty and both bounds start above zero), so ``or None`` only
    # ever turns a fallback into the marker.
    if field in ("accent_color", "footer_color"):
        return _colour(value, "") or None
    if field == "base_font_size":
        return _bounded_int(value, MIN_FONT_SIZE, MAX_FONT_SIZE, 0) or None
    if field == "margin_mm":
        return _bounded_int(value, MIN_MARGIN_MM, MAX_MARGIN_MM, 0) or None
    if field == "page_size":
        name = value.strip().upper() if isinstance(value, str) else ""
        return name if name in PAGE_SIZES else None
    if field == "logo_align":
        align = value.strip().lower() if isinstance(value, str) else ""
        return align if align in LOGO_ALIGNMENTS else None
    if field == "footer_text":
        return value.strip()[:MAX_FOOTER_TEXT] if isinstance(value, str) else None
    if field == "watermark_text":
        # Whitespace collapses because the mark is drawn as one line, and a
        # newline typed into the field would otherwise print as a gap.
        return " ".join(value.split())[:MAX_WATERMARK_TEXT] if isinstance(value, str) else None
    if field in ("show_page_numbers", "show_letterhead"):
        return value if isinstance(value, bool) else None
    return None


def sanitise(data: Any) -> dict[str, Any]:
    """Coerce arbitrary stored / submitted data into a safe appearance dict.

    Defends both the read path (a hand-edited or corrupt file) and the write
    path (an API payload). Every field falls back to its platform default
    independently, so one bad value costs only that value: a workspace that
    sends a valid accent colour and a nonsense page size keeps its colour.

    Only the workspace fields are returned; per-type overrides are sanitised
    by :func:`sanitise_overrides`.
    """
    if not isinstance(data, dict):
        return dict(DEFAULT_APPEARANCE)
    clean: dict[str, Any] = {}
    for field, default in DEFAULT_APPEARANCE.items():
        value = _clean_field(field, data.get(field))
        clean[field] = default if value is None else value
    return clean


# -- Document types ------------------------------------------------------------


#: A sheet whose size is the reader's own Settings paper preference
#: (:mod:`app.core.paper_size`) rather than a fixed one.
USER_PAPER = "user"


@dataclass(frozen=True)
class DocumentSheet:
    """The sheet a type's generator lays its form out on, for the sample page.

    Copied from the generator's own document template, so the sample puts the
    letterhead where the document puts it. ``test_pdf_document_type_overrides``
    renders both and compares where the logo and the firm's name land, which
    is what catches a generator whose layout moved without this entry.

    Attributes:
        page_size: A key of :data:`app.core.paper_size.PAPER_SIZES`, or
            :data:`USER_PAPER`.
        landscape: Whether the sheet is turned.
        margins_mm: ``(left, right, top, bottom)`` as the generator passes them
            to its template.
        frame_padding_pt: The padding inside the margins. Six points for a
            ``SimpleDocTemplate``, whose frame keeps reportlab's default.
    """

    page_size: str
    landscape: bool
    margins_mm: tuple[float, float, float, float]
    frame_padding_pt: float


#: A ``SimpleDocTemplate`` frame's padding, reportlab's default.
_SIMPLE_DOC_PADDING = 6.0


@dataclass(frozen=True)
class DocumentType:
    """A kind of generated document that may carry its own look.

    Attributes:
        key: Stable identifier, stored in the file and passed by the generator.
        label: English name, for the sample title and as the UI's fallback.
        label_key: i18n key the settings page translates the name with.
        fields: The appearance fields this type's generator honours, in the
            order the settings page offers them. Empty for a reserved type,
            whose generator does not read the appearance yet.
        sheet: The sheet the generator prints on, or ``None`` for a reserved
            type.
        default_footer_line: Whether the generator's footer prints the brand
            and the date when no footer line is saved. A generator whose footer
            carries only what the workspace saved sets this ``False`` so the
            settings sample shows the blank footer the document really prints.
        sections: The parts of the document a workspace may leave out, in the
            order the settings page offers them. Every one prints until it is
            hidden, so a workspace that never opens the settings gets the whole
            document. Empty for a type whose generator prints a fixed form.
    """

    key: str
    label: str
    label_key: str
    fields: tuple[str, ...]
    sheet: DocumentSheet | None = None
    default_footer_line: bool = True
    sections: tuple[str, ...] = ()

    @property
    def configurable(self) -> bool:
        """Whether the type has any field an override could set."""
        return bool(self.fields)


#: Read by :func:`app.core.pdf_branding.branded_letterhead`, which every wired
#: generator prints on page one: the switch, the side the logo sits on, and
#: the colour of the company name in the letterhead. Only the letterhead reads
#: them, so they take effect once the company profile has a legal name or a
#: logo and change nothing before that; the header logo these generators draw
#: without a letterhead always sits top right.
_LETTERHEAD_FIELDS = ("show_letterhead", "logo_align", "accent_color")

#: Read only by a generator that draws a footer from the appearance: the RFI,
#: the meeting minutes, the daily diary and the record forms of
#: :func:`app.core.register_export.build_record_pdf`. The other four print no
#: footer. The watermark belongs here because it is drawn by the same page
#: callback as the footer, so exactly the generators with a footer carry it.
_FOOTER_FIELDS = ("footer_text", "footer_color", "show_page_numbers", "watermark_text")

#: The sheet of :func:`app.core.register_export.build_record_pdf`: portrait A4,
#: 20 mm at the sides and 18 mm top and bottom, an unpadded frame.
_RECORD_FORM_SHEET = DocumentSheet("A4", False, (20.0, 20.0, 18.0, 18.0), 0.0)

#: Every document type, wired or reserved. Page size, margins and body size
#: are offered for none of them on purpose: each of these generators lays out
#: a fixed form on a fixed sheet (the RFI is always A4, the pay application
#: always landscape Letter, the transmittal follows the user's paper setting),
#: so those knobs would change nothing. Wiring a reserved type means passing
#: its key where the generator reads the letterhead or the appearance, then
#: listing the fields it now honours here.
DOCUMENT_TYPES: dict[str, DocumentType] = {
    kind.key: kind
    for kind in (
        DocumentType(
            "rfi",
            "Request for information",
            "settings.document_templates.types.rfi",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            # app.modules.rfi.pdf_export: A4, its own unpadded frame.
            DocumentSheet("A4", False, (20.0, 20.0, 18.0, 18.0), 0.0),
        ),
        DocumentType(
            "pay_application",
            "Payment application (G702/G703)",
            "settings.document_templates.types.pay_application",
            _LETTERHEAD_FIELDS,
            # app.modules.contracts.aia_pdf. The top margin is the 18 mm a form
            # with a letterhead or a logo gets; one with neither starts at 14.
            DocumentSheet("LETTER", True, (14.0, 14.0, 18.0, 14.0), _SIMPLE_DOC_PADDING),
        ),
        DocumentType(
            "closeout_cover",
            "Closeout package cover",
            "settings.document_templates.types.closeout_cover",
            _LETTERHEAD_FIELDS,
            DocumentSheet("A4", False, (20.0, 20.0, 18.0, 18.0), _SIMPLE_DOC_PADDING),
        ),
        DocumentType(
            "punch_list",
            "Punch list",
            "settings.document_templates.types.punch_list",
            _LETTERHEAD_FIELDS,
            DocumentSheet("A4", False, (18.0, 18.0, 18.0, 18.0), _SIMPLE_DOC_PADDING),
        ),
        DocumentType(
            "transmittal",
            "Transmittal cover sheet",
            "settings.document_templates.types.transmittal",
            _LETTERHEAD_FIELDS,
            # Three quarters of an inch on every side, on the sender's paper.
            DocumentSheet(USER_PAPER, False, (19.05, 19.05, 19.05, 19.05), _SIMPLE_DOC_PADDING),
        ),
        DocumentType("submittal", "Submittal", "settings.document_templates.types.submittal", ()),
        DocumentType("change_order", "Change order", "settings.document_templates.types.change_order", ()),
        DocumentType(
            "meeting_minutes",
            "Meeting minutes",
            "settings.document_templates.types.meeting_minutes",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            # app.modules.meetings.pdf and the export in meetings.router: A4,
            # a padded frame 20 mm in from every edge.
            DocumentSheet("A4", False, (20.0, 20.0, 20.0, 20.0), _SIMPLE_DOC_PADDING),
            # Minutes are circulated to attendees who were in the room, so the
            # footer stays empty unless the workspace puts something in it.
            default_footer_line=False,
        ),
        DocumentType(
            "daily_report",
            "Daily report",
            "settings.document_templates.types.daily_report",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            # app.modules.daily_diary.pdf_export: A4, a padded frame.
            DocumentSheet("A4", False, (20.0, 20.0, 22.0, 18.0), _SIMPLE_DOC_PADDING),
        ),
        # The procurement and finance records, printed as record forms by
        # app.modules.procurement.pdf_export and app.modules.finance.pdf_export.
        DocumentType(
            "purchase_order",
            "Purchase order",
            "settings.document_templates.types.purchase_order",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            _RECORD_FORM_SHEET,
            sections=("line_items", "totals", "terms", "supplier_confirmation", "notes", "signatures"),
        ),
        DocumentType(
            "goods_receipt",
            "Goods receipt",
            "settings.document_templates.types.goods_receipt",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            _RECORD_FORM_SHEET,
            sections=("line_items", "rejections", "notes", "signatures"),
        ),
        DocumentType(
            "invoice",
            "Invoice",
            "settings.document_templates.types.invoice",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            _RECORD_FORM_SHEET,
            sections=("line_items", "totals", "payments", "notes", "signatures"),
        ),
        DocumentType(
            "payment",
            "Payment",
            "settings.document_templates.types.payment",
            _LETTERHEAD_FIELDS + _FOOTER_FIELDS,
            _RECORD_FORM_SHEET,
            sections=("invoice", "withholding", "signatures"),
        ),
    )
}


def sanitise_override(doc_type: str, data: Any) -> dict[str, Any]:
    """Coerce one type's override into the fields that type honours.

    Unlike :func:`sanitise`, which must return a complete look, an override is
    sparse: a field it does not carry is inherited from the workspace. So an
    unusable value is dropped rather than replaced with the platform default,
    which would silently pin the type to a look the workspace never chose. A
    field the type does not honour is dropped too, and an unknown or reserved
    type yields ``{}``.
    """
    kind = DOCUMENT_TYPES.get(doc_type) if isinstance(doc_type, str) else None
    if kind is None or not isinstance(data, dict):
        return {}
    clean: dict[str, Any] = {}
    for field in kind.fields:
        if field in data:
            value = _clean_field(field, data[field])
            if value is not None:
                clean[field] = value
    return clean


def sanitise_overrides(data: Any) -> dict[str, dict[str, Any]]:
    """Coerce a stored overrides map, type by type and field by field.

    Unknown types and overrides left empty are dropped. The result is ordered
    as :data:`DOCUMENT_TYPES` is, so the file's content does not depend on the
    order the admin saved in.
    """
    if not isinstance(data, dict):
        return {}
    clean: dict[str, dict[str, Any]] = {}
    for key in DOCUMENT_TYPES:
        override = sanitise_override(key, data.get(key))
        if override:
            clean[key] = override
    return clean


# -- Sections ------------------------------------------------------------------


def sanitise_hidden_sections(doc_type: str, data: Any) -> list[str]:
    """Coerce one type's hidden sections into the sections that type has.

    A name the type does not offer is dropped, duplicates collapse, and the
    result follows the order of :attr:`DocumentType.sections`, so the stored
    file does not depend on the order the admin clicked in. An unknown type
    yields ``[]``.
    """
    kind = DOCUMENT_TYPES.get(doc_type) if isinstance(doc_type, str) else None
    if kind is None or not isinstance(data, list | tuple):
        return []
    named = {item for item in data if isinstance(item, str)}
    return [section for section in kind.sections if section in named]


def sanitise_hidden_map(data: Any) -> dict[str, list[str]]:
    """Coerce a stored ``{doc_type: [hidden section, ...]}`` map, type by type.

    Unknown types and empty lists are dropped; the result is ordered as
    :data:`DOCUMENT_TYPES` is.
    """
    if not isinstance(data, dict):
        return {}
    clean: dict[str, list[str]] = {}
    for key in DOCUMENT_TYPES:
        hidden = sanitise_hidden_sections(key, data.get(key))
        if hidden:
            clean[key] = hidden
    return clean


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
#:
#: The entry holds every part of the file, the workspace look, the per-type
#: overrides and the per-type hidden sections, because every writer rewrites
#: the whole file and each must carry the others' parts through unchanged.
_Stored = tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[str]]]
_appearance_cache: dict[
    str, tuple[tuple[int, int], dict[str, Any], dict[str, dict[str, Any]], dict[str, list[str]]]
] = {}


def _forget_appearance(data_dir: Path | None) -> None:
    """Drop any cached parse of the appearance file.

    Called by every writer. A writer knows the content changed; leaving that
    knowledge to the clock is what the stamp above exists to survive.
    """
    _appearance_cache.pop(str(appearance_path(data_dir)), None)


def _copy_overrides(overrides: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """A copy two levels deep, so no caller can mutate the cache through it."""
    return {key: dict(value) for key, value in overrides.items()}


def _copy_hidden(hidden: dict[str, list[str]]) -> dict[str, list[str]]:
    """A copy two levels deep, so no caller can mutate the cache through it."""
    return {key: list(value) for key, value in hidden.items()}


def _read_stored(data_dir: Path | None) -> _Stored:
    """Return ``(workspace look, overrides, hidden sections)`` as stored, or defaults when none/corrupt.

    Fresh copies each call. Never raises: every failure path logs and falls
    back to the platform default with no overrides.
    """
    path = appearance_path(data_dir)
    key = str(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        _appearance_cache.pop(key, None)
        return dict(DEFAULT_APPEARANCE), {}, {}
    except OSError as exc:
        logger.warning("Could not stat document appearance at %s: %s", path, exc)
        return dict(DEFAULT_APPEARANCE), {}, {}
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _appearance_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1]), _copy_overrides(cached[2]), _copy_hidden(cached[3])
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _appearance_cache.pop(key, None)
        return dict(DEFAULT_APPEARANCE), {}, {}
    except OSError as exc:
        logger.warning("Could not read document appearance at %s: %s", path, exc)
        return dict(DEFAULT_APPEARANCE), {}, {}
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring corrupt document appearance file at %s", path)
        return dict(DEFAULT_APPEARANCE), {}, {}
    clean = sanitise(data)
    overrides = sanitise_overrides(data.get("overrides")) if isinstance(data, dict) else {}
    hidden = sanitise_hidden_map(data.get("hidden_sections")) if isinstance(data, dict) else {}
    _appearance_cache[key] = (stamp, dict(clean), _copy_overrides(overrides), _copy_hidden(hidden))
    return dict(clean), overrides, hidden


def read_appearance(data_dir: Path | None = None) -> dict[str, Any]:
    """Return the stored workspace appearance, or defaults when none/corrupt.

    The workspace look only, never a type's override: this is what the
    workspace settings form edits. A fresh ``dict`` is returned each call so
    callers can never mutate the cache. Never raises: every failure path logs
    and falls back.
    """
    return _read_stored(data_dir)[0]


def read_overrides(data_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return the stored per-type overrides, ``{doc_type: {field: value}}``.

    Only types that override something appear. Never raises.
    """
    return _read_stored(data_dir)[1]


def resolve_appearance(doc_type: str | None, data_dir: Path | None = None) -> dict[str, Any]:
    """Return the look a document of ``doc_type`` is drawn with.

    The workspace look with the type's override laid over it, field by field.
    With no override for the type, and for ``None``, this is exactly
    :func:`read_appearance`. An unknown type gets the workspace look and a
    warning, because it means a generator passed a key the registry does not
    have and its override could never apply. Never raises.
    """
    appearance, overrides, _hidden = _read_stored(data_dir)
    if doc_type is None:
        return appearance
    if doc_type not in DOCUMENT_TYPES:
        logger.warning("Unknown document type %r; drawing it with the workspace appearance", doc_type)
        return appearance
    appearance.update(overrides.get(doc_type, {}))
    return appearance


def _store(
    workspace: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
    hidden: dict[str, list[str]],
    data_dir: Path | None,
) -> None:
    """Write every part of the file, or remove it when none says anything.

    The workspace look is written only when it differs from the platform
    default, and then in full, as it always was; with no overrides the file is
    byte for byte what it was before overrides existed. A file that carries
    only overrides leaves the workspace fields out, so the workspace keeps
    following the platform default rather than freezing today's into the file.
    Hidden sections are written under their own key, and only when a type
    hides something, so the file of a workspace that hides nothing is what it
    was before sections existed. Best effort: a failed write is logged, never raised.
    """
    path = appearance_path(data_dir)
    record: dict[str, Any] = dict(workspace) if workspace != DEFAULT_APPEARANCE else {}
    if overrides:
        record["overrides"] = overrides
    if hidden:
        record["hidden_sections"] = hidden
    try:
        if record:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not persist document appearance at %s: %s", path, exc)
    # Unconditionally, including after a failed write: the file is then
    # unchanged and forgetting it costs one re-read.
    _forget_appearance(data_dir)


def write_appearance(payload: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """Persist (sanitised) workspace appearance and return what was stored.

    Best-effort write, mirroring :func:`app.core.app_branding.write_branding`: a
    failed write still returns the sanitised payload so the caller's response
    stays consistent. A payload that sanitises to the platform default is not
    written as a marker that says "same as default"; the file is removed, or
    keeps only the per-type overrides, which a workspace save never touches.
    """
    clean = sanitise(payload)
    _workspace, overrides, hidden = _read_stored(data_dir)
    _store(clean, overrides, hidden, data_dir)
    return clean


def reset_appearance(data_dir: Path | None = None) -> dict[str, Any]:
    """Clear the custom workspace appearance. Returns the defaults.

    Per-type overrides survive: they are set on their own page, one type at a
    time, and resetting the workspace look is not a request to undo them. The
    file is removed when there are none.
    """
    _workspace, overrides, hidden = _read_stored(data_dir)
    _store(dict(DEFAULT_APPEARANCE), overrides, hidden, data_dir)
    return dict(DEFAULT_APPEARANCE)


def write_override(doc_type: str, payload: Any, data_dir: Path | None = None) -> dict[str, Any]:
    """Replace ``doc_type``'s override with (sanitised) ``payload``; return what was stored.

    Replaces rather than merges: a field left out of ``payload`` goes back to
    inheriting the workspace value, which is how one field of an override is
    cleared. An override that sanitises to nothing removes the type's entry. An
    unknown or reserved type stores nothing and returns ``{}``.
    """
    clean = sanitise_override(doc_type, payload)
    if doc_type not in DOCUMENT_TYPES:
        return clean
    workspace, overrides, hidden = _read_stored(data_dir)
    if clean:
        overrides[doc_type] = clean
    else:
        overrides.pop(doc_type, None)
    _store(workspace, sanitise_overrides(overrides), hidden, data_dir)
    return clean


def reset_override(doc_type: str, data_dir: Path | None = None) -> None:
    """Remove ``doc_type``'s override, so the type follows the workspace look again."""
    write_override(doc_type, {}, data_dir)


def read_hidden_sections(doc_type: str, data_dir: Path | None = None) -> list[str]:
    """Return the sections ``doc_type`` leaves out, in the type's order. Never raises."""
    return list(_read_stored(data_dir)[2].get(doc_type, []))


def resolve_sections(doc_type: str, data_dir: Path | None = None) -> dict[str, bool]:
    """Return ``{section: printed}`` for every section ``doc_type`` offers.

    What a generator asks before it draws a section. A section is printed
    unless the workspace hid it, so an empty file prints the whole document.
    Never raises; an unknown type has no sections.
    """
    kind = DOCUMENT_TYPES.get(doc_type)
    if kind is None:
        return {}
    hidden = set(read_hidden_sections(doc_type, data_dir))
    return {section: section not in hidden for section in kind.sections}


def write_hidden_sections(doc_type: str, payload: Any, data_dir: Path | None = None) -> list[str]:
    """Replace the sections ``doc_type`` leaves out; return what was stored.

    Replaces rather than merges, like :func:`write_override`: a section left
    out of ``payload`` prints again. An unknown type stores nothing.
    """
    clean = sanitise_hidden_sections(doc_type, payload)
    if doc_type not in DOCUMENT_TYPES:
        return clean
    workspace, overrides, hidden = _read_stored(data_dir)
    if clean:
        hidden[doc_type] = clean
    else:
        hidden.pop(doc_type, None)
    _store(workspace, overrides, sanitise_hidden_map(hidden), data_dir)
    return clean


def resolve_page_size(appearance: dict[str, Any] | None = None) -> tuple[float, float]:
    """Return the (width, height) in points for the configured page size."""
    data = appearance if isinstance(appearance, dict) else read_appearance()
    name = data.get("page_size")
    if name not in PAGE_SIZES:
        name = DEFAULT_APPEARANCE["page_size"]
    return PAGE_SIZES[name]

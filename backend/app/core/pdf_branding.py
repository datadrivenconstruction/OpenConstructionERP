# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared company branding for every reportlab-generated PDF (issue #284).

Every PDF generator in the platform used to hard-code the literal
``"OpenConstructionERP"`` brand string, the ``#1a1a2e`` accent and the
author / creator document metadata. A workspace that white-labels the app
(see :mod:`app.core.app_branding` - the persisted logo / company name set by
the admin) therefore still printed the default brand on every exported
estimate, diary and invoice, which defeated the customisation (issue #284
follow-up to #272).

This module is the one place that turns the persisted branding into PDF
output, so wiring a generator is a 3-8 line swap rather than a copy of the
header / footer / metadata logic into each module:

* :func:`branded_header_footer` - an ``onPage(canvas, doc)`` callback that
  draws the workspace brand (the uploaded logo rasterised from its base64
  data URL, else the company name, else the default text) in the page header
  and a ``Generated ...`` line plus a page number in the footer. Geometry is
  read from the live ``doc`` (pagesize / margins) so it preserves whatever
  layout the calling generator already uses.
* :func:`branded_cover_brand` - the brand string for a cover-page title
  (logo cover art is out of scope for this MVP; the cover shows the name).
* :func:`branded_doc_metadata` - the ``author`` / ``creator`` / ``subject`` /
  ``producer`` / ``keywords`` to stamp on the ``DocTemplate`` so the file's
  document properties also carry the workspace brand.
* :func:`branded_letterhead` - the firm's formal letterhead (logo, registered
  name, address, registration line, contact line) as a flowable for the top of
  page one, built from :mod:`app.core.company_profile`. ``None`` when the
  profile is empty or the appearance turns it off, so a generator can insert
  it unconditionally.
* :func:`branded_footer` - the footer half of :func:`branded_header_footer`,
  for a page whose header is a letterhead.

**Which logo.** The company profile carries a *document* logo, the formal one a
firm's letters go out under, separate from the app logo in the sidebar (which
is often a cropped or simplified mark). Wherever this module draws a logo it
prefers the document logo and falls back to the app logo, and a document logo
that cannot be decoded falls back too rather than leaving the header empty. A
workspace with no document logo therefore sees exactly what it saw before.
Formal logos often arrive as SVG, which reportlab cannot read, so an SVG logo
is rasterised through PyMuPDF (a base dependency) before it is drawn.

Everything degrades gracefully and NEVER raises (mirrors the never-break
contract of :mod:`app.core.pdf_stamp`): a logo that fails to decode falls
back to the company name, an empty company name falls back to the default
brand, and any failure reading the persisted branding falls back to the
default too. A failed brand draw must never break a PDF export.

Deferred follow-up (out of scope for this MVP, by design): a configurable
template engine - per-workspace margins / fonts / colours / header layout /
footer text - and rendering the logo as cover-page art. Today the accent
colour and geometry stay the platform defaults; only the brand identity
(logo / name) and document metadata follow the workspace.
"""

from __future__ import annotations

import functools
import html
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: The brand shown when no workspace branding is set (or it cannot be read).
DEFAULT_BRAND = "OpenConstructionERP"

#: Footer text colour and header brand colour - the platform default accent.
#: Kept module-level (not configurable in this MVP) so every PDF stays
#: visually consistent; a future template engine may make these per-workspace.
_FOOTER_COLOR = "#999999"
_HEADER_COLOR = "#1a1a2e"

#: Header logo box (points). The logo is scaled to fit inside this box while
#: keeping its aspect ratio; a wordmark therefore stays legible and a square
#: mark never overflows the header band.
_LOGO_MAX_W = 130.0
_LOGO_MAX_H = 22.0


def _read_branding() -> dict[str, Any]:
    """Return the persisted workspace branding, or defaults, never raising.

    Imported lazily so this module stays import-safe (and unit-testable
    without the app package) and so any failure reading the branding - a
    missing dependency, a corrupt file, anything - degrades to the default
    brand instead of breaking a PDF export.
    """
    try:
        from app.core.app_branding import read_branding

        data = read_branding()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - degrade, never break PDF output
        logger.debug("Could not read workspace branding; using default", exc_info=True)
        return {}


def _read_appearance(doc_type: str | None = None) -> dict[str, Any]:
    """Return the persisted document appearance, or defaults, never raising.

    Same lazy-import, degrade-never-break contract as :func:`_read_branding`.
    A workspace that has customised nothing, and a workspace whose appearance
    file cannot be read, both land on the platform defaults - which are the
    values this module used to hold as constants, so neither sees a change.

    With ``doc_type`` the type's override is laid over the workspace look (see
    :func:`app.core.pdf_appearance.resolve_appearance`); without one, or with
    no override stored for it, the result is the workspace look unchanged.
    """
    try:
        from app.core.pdf_appearance import DEFAULT_APPEARANCE, resolve_appearance

        data = resolve_appearance(doc_type)
        return data if isinstance(data, dict) else dict(DEFAULT_APPEARANCE)
    except Exception:  # noqa: BLE001 - degrade, never break PDF output
        logger.debug("Could not read document appearance; using platform default", exc_info=True)
        return {}


def branded_appearance(doc_type: str | None = None) -> dict[str, Any]:
    """Return the persisted document appearance for a generator's own drawing.

    For generators that draw their own footer (the RFI form translates its
    footer, the shared one does not) but must still honour the workspace's
    footer line, footer colour and page-number switch. The result may be empty
    when the appearance cannot be read, so read it with ``.get`` and the
    platform default. Never raises.

    Args:
        doc_type: The generator's key in
            :data:`app.core.pdf_appearance.DOCUMENT_TYPES`, so the type's own
            override applies. ``None`` reads the workspace look alone.
    """
    return _read_appearance(doc_type)


def _read_company_profile() -> dict[str, Any]:
    """Return the persisted company profile, or ``{}``, never raising.

    Same lazy-import, degrade-never-break contract as :func:`_read_branding`:
    a profile that cannot be read costs the letterhead and the document logo,
    never the document.
    """
    try:
        from app.core.company_profile import read_company_profile

        data = read_company_profile()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - degrade, never break PDF output
        logger.debug("Could not read company profile; no letterhead", exc_info=True)
        return {}


def _letterhead_profile() -> dict[str, Any] | None:
    """Return the company profile when it calls for a letterhead, else ``None``.

    :func:`app.core.company_profile.has_letterhead` is the one definition of
    "enough to print" (a legal name or a logo; contact details alone say
    nothing about whose they are), so this asks it rather than re-deciding.
    """
    try:
        from app.core.company_profile import has_letterhead

        profile = _read_company_profile()
        return profile if has_letterhead(profile) else None
    except Exception:  # noqa: BLE001 - degrade, never break PDF output
        logger.debug("Could not decide on a letterhead; none drawn", exc_info=True)
        return None


def _logo_candidates(branding: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """The logos to try, best first: the document logo, then the app logo.

    Both are offered so a document logo that fails to decode still leaves the
    app logo in the header instead of nothing.
    """
    candidates: list[str] = []
    for value in (profile.get("document_logo_data_url"), branding.get("logo_data_url")):
        if isinstance(value, str) and value and value not in candidates:
            candidates.append(value)
    return candidates


#: Longest side, in pixels, an SVG logo is rasterised to. The letterhead box is
#: 60 mm wide, about 710 px at 300 dpi, so this prints sharp at that size, and a
#: hostile SVG declaring a page the size of a building still costs one bounded
#: pixmap rather than gigabytes.
_SVG_RASTER_PX = 1200.0


@functools.lru_cache(maxsize=2)
def _rasterise_svg(svg: bytes) -> bytes | None:
    """Render SVG bytes to a transparent PNG, or ``None`` when that fails.

    Safe to run on an uploaded file because MuPDF, given an SVG as a stream,
    ignores every external image reference (checked with ``file://`` URIs,
    absolute paths and relative names): an SVG cannot pull a file off the
    server into a PDF.

    The bound is on the pixmap, not on the zoom. An SVG says how large its page
    is in its own opening tag, a 146-byte file can claim a hundred thousand
    units, and the pixels asked for grow with the square of that number, so a
    zoom with a floor under it is not a bound at all: at the old floor of 0.05
    such a file was rasterised to 5000 x 5000 px, 95 MiB of RGBA, and took
    thirty seconds on a six-page export. The zoom is whatever puts the longest
    side on :data:`_SVG_RASTER_PX`, and the result is checked in pixels before
    it is asked for, because the zoom is a ratio and the pixmap is the cost.

    Cached because the header logo is drawn on every page of a long export and
    the same one or two logos are rasterised each time. Never raises.
    """
    try:
        import pymupdf

        with pymupdf.open(stream=svg, filetype="svg") as svg_doc:
            page = svg_doc[0]
            width, height = float(page.rect.width), float(page.rect.height)
            longest = max(width, height)
            if longest <= 0:
                return None
            zoom = min(16.0, _SVG_RASTER_PX / longest)
            # Belt and braces: whatever the ratio worked out to, the pixmap
            # itself is what costs the memory, so it is what gets checked.
            asked = max(width * zoom, height * zoom)
            if asked > _SVG_RASTER_PX:
                zoom *= _SVG_RASTER_PX / asked
            if zoom <= 0:
                return None
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
            return pixmap.tobytes("png")
    except Exception:  # noqa: BLE001 - an undrawable logo falls back, never raises
        logger.debug("Could not rasterise SVG logo", exc_info=True)
        return None


#: How many pixels of logo are kept per point it is drawn at. Three is 216 dpi,
#: sharp on any office printer, and it is the smallest factor that leaves the
#: logos firms actually upload untouched: a 360 x 120 wordmark drawn 170 pt wide
#: is already close to twice its drawn size, and shrinking that would be a
#: change with no benefit. What it does cut is the over-resolved kind - a
#: 4000 px designer export, a 1000 px photograph, an SVG rasterised to 1200 px -
#: each of which was going into every page of every PDF at full resolution.
_LOGO_PIXELS_PER_POINT = 3.0


@functools.lru_cache(maxsize=2)
def _logo_raster_for_pdf(raw: bytes) -> bytes:
    """``raw``, re-encoded no larger than a PDF ever draws it. Never raises.

    Cached for the reason :func:`_rasterise_svg` is: the header band redraws
    the logo on every page, so on a six-page estimate an uncached shrink
    decoded and resampled the same picture six times.

    The letterhead box is the largest any generator draws a logo in, so one
    raster at that size serves the letterhead and the smaller header band
    alike, and the document keeps carrying a single image resource rather than
    one per box.

    The caller works out the rectangle to draw in *before* calling this, from
    the size the logo arrived at, and passes that rectangle explicitly: a
    thumbnail lands on whole pixels and its aspect moves by a fraction, which
    would otherwise show up as the letterhead shifting under an unrelated
    change. Returns ``raw`` unchanged when it is already small enough, when
    Pillow is absent, or when anything at all goes wrong - an unshrunk logo is
    a slow document, a raised exception is no document.
    """
    try:
        from io import BytesIO

        from PIL import Image as PILImage

        max_w = _LETTERHEAD_LOGO_MAX_W * _LOGO_PIXELS_PER_POINT
        max_h = _LETTERHEAD_LOGO_MAX_H * _LOGO_PIXELS_PER_POINT
        with PILImage.open(BytesIO(raw)) as source:
            if source.width <= max_w and source.height <= max_h:
                return raw
            source.load()
            image = source.convert("RGBA")
        image.thumbnail((int(max_w), int(max_h)))
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001 - a logo that will not shrink is drawn as it came
        logger.debug("Could not shrink a logo for the PDF; drawing it at full size", exc_info=True)
        return raw


def _logo_image_bytes(data_url: Any) -> bytes | None:
    """Decode a ``data:image/...;base64,`` URL to bytes reportlab can read.

    Raster types come back as decoded; SVG is rasterised first because
    reportlab's image reader cannot read it. Returns ``None`` for anything that
    is not an image data URL. A body that decodes but is not a readable image
    is the caller's to catch: it fails in the image reader.
    """
    if not (isinstance(data_url, str) and data_url.startswith("data:image/") and "base64," in data_url):
        return None
    import base64

    header, b64 = data_url.split("base64,", 1)
    raw = base64.b64decode(b64, validate=False)
    if not raw:
        return None
    if header.startswith("data:image/svg"):
        return _rasterise_svg(raw)
    return raw


def _app_company_name(branding: dict[str, Any]) -> str:
    """The app branding's own company name, trimmed, or ``""``."""
    name = branding.get("company_name")
    return name.strip() if isinstance(name, str) else ""


def _company_name(branding: dict[str, Any] | None = None) -> str:
    """Return the name a document is branded with.

    The app branding's company name, else the company profile's legal name,
    else the default brand. The legal name is in the chain because a firm that
    filled in its formal letterhead but never gave the app a display name
    otherwise printed the platform's name in the footer and the document
    properties of its own formal documents. It comes second because the app
    name is the one the workspace chose for its documents first, and changing
    what an already-branded workspace prints is not this fallback's job.

    Everything that prints a brand name (the footer line, the text brand in
    the header band, the cover title and the document metadata) comes through
    here, so they cannot disagree. The profile is only read when the app name
    is empty, so a workspace without a profile prints what it always did.
    """
    data = branding if branding is not None else _read_branding()
    name = _app_company_name(data)
    if name:
        return name
    legal_name = _read_company_profile().get("legal_name")
    if isinstance(legal_name, str) and legal_name.strip():
        return legal_name.strip()
    return DEFAULT_BRAND


def branded_cover_brand() -> str:
    """Return the brand string for a cover-page title.

    The uploaded logo is not rendered as cover art in this MVP (deferred to a
    future template engine); the cover shows the workspace company name, else
    the company profile's legal name, else the default brand. Never raises.
    """
    return _company_name()


def branded_doc_metadata() -> dict[str, str]:
    """Return reportlab ``DocTemplate`` metadata derived from the brand.

    Brand-aware so a white-labelled workspace never leaks the platform name into
    a file's document properties (issue #284 follow-up):

    * a workspace with its own company name attributes every field to that name;
    * a workspace with no app company name but a legal name in its company
      profile attributes every field to the legal name;
    * a logo-only workspace (custom logo, no name) stays brand-neutral rather
      than printing the platform default in the metadata;
    * an un-customised workspace keeps the platform credit so default exports
      stay attributable.

    Never raises - a branding read failure yields the default-brand metadata.
    """
    branding = _read_branding()
    name = _company_name(branding)
    # A legal name reached through the fallback brands the metadata whatever
    # the app branding mode says: the mode describes the app shell, and a firm
    # whose formal documents carry its letterhead must not be credited to the
    # platform in their properties. An app name keeps the mode check it always
    # had, so no workspace without a profile sees its metadata move.
    named_by_profile = not _app_company_name(branding) and name != DEFAULT_BRAND
    if name != DEFAULT_BRAND and (branding.get("mode") in ("logo", "text") or named_by_profile):
        return {
            "author": name,
            "creator": name,
            "subject": f"Generated by {name}",
            "producer": name,
            "keywords": name,
        }
    if branding.get("mode") == "logo":
        # Logo-only white-label with no company name: describe by function, do
        # not fall back to the platform brand in the metadata.
        neutral = "Construction cost management"
        return {
            "author": neutral,
            "creator": neutral,
            "subject": f"Generated by a {neutral.lower()} platform",
            "producer": neutral,
            "keywords": "",
        }
    return {
        "author": DEFAULT_BRAND,
        "creator": DEFAULT_BRAND,
        "subject": f"Generated by {DEFAULT_BRAND}",
        "producer": f"{DEFAULT_BRAND} / reportlab - datadrivenconstruction.io",
        "keywords": f"{DEFAULT_BRAND},DataDrivenConstruction",
    }


def _draw_logo(
    canvas: Any,
    branding: dict[str, Any],
    *,
    top_y: float,
    x: float | None = None,
    right_x: float | None = None,
    center_x: float | None = None,
) -> bool:
    """Try to draw the workspace logo in the header. Return True on success.

    Rasterises the ``logo_data_url`` (a base64 ``data:image/...`` URL) via
    reportlab's ``ImageReader`` and draws it scaled to fit the header logo
    box, top-aligned at ``top_y`` and left-aligned at ``x``. Any decode /
    draw failure returns ``False`` so the caller falls back to the text brand;
    it never raises.
    """
    logo = branding.get("logo_data_url")
    if not (isinstance(logo, str) and logo.startswith("data:image/") and "base64," in logo):
        return False
    try:
        from io import BytesIO

        from reportlab.lib.utils import ImageReader

        raw = _logo_image_bytes(logo)
        if not raw:
            return False
        reader = ImageReader(BytesIO(raw))
        iw, ih = reader.getSize()
        if not iw or not ih:
            return False
        # Scale to fit the logo box while preserving aspect ratio. Worked out
        # from the size the logo arrived at, before it is shrunk, so the box it
        # lands in is the same whether or not it needed shrinking.
        scale = min(_LOGO_MAX_W / float(iw), _LOGO_MAX_H / float(ih), 1.0)
        draw_w = float(iw) * scale
        draw_h = float(ih) * scale
        small = _logo_raster_for_pdf(raw)
        if small is not raw:
            reader = ImageReader(BytesIO(small))
        # Left-aligned at ``x`` by default; right-aligned so the logo's right edge
        # sits at ``right_x``; or centred on ``center_x``. The caller cannot work
        # out the centred origin itself because the drawn width is only known
        # here, after the aspect-preserving scale has been applied.
        if center_x is not None:
            draw_x = center_x - draw_w / 2.0
        elif right_x is not None:
            draw_x = right_x - draw_w
        else:
            draw_x = x if x is not None else 0.0
        canvas.drawImage(
            reader,
            draw_x,
            top_y - draw_h,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
        return True
    except Exception:  # noqa: BLE001 - fall back to the text brand, never raise
        logger.debug("Could not rasterise workspace logo for PDF header", exc_info=True)
        return False


def _draw_workspace_logo(canvas: Any, branding: dict[str, Any], profile: dict[str, Any], **geometry: Any) -> bool:
    """Draw the best logo that decodes (document logo, then app logo).

    ``geometry`` is passed through to :func:`_draw_logo`. Returns whether any
    logo was drawn; never raises.
    """
    for data_url in _logo_candidates(branding, profile):
        if _draw_logo(canvas, {"logo_data_url": data_url}, **geometry):
            return True
    return False


def branded_header_footer(canvas: Any, doc: Any) -> None:
    """``onPage(canvas, doc)`` callback drawing the brand header and footer.

    Reads the persisted branding once per call and draws:

    * a header band with the workspace logo (the company profile's document
      logo when set, else the app logo, rasterised from its base64 data URL)
      or, failing that, the company name / default brand as text, plus a thin
      rule under it;
    * a footer with ``<brand>  |  Generated: <date>`` on the left and
      ``Page X`` / ``Page X of Y`` (when the doc tracks ``page_count``) on the
      right.

    Geometry is taken from the live ``doc`` (``pagesize`` and the four
    margins), so the brand lands consistently regardless of which generator's
    layout is in use. Never raises - a failure to draw the brand must not
    break the PDF, so the whole body is guarded.
    """
    _draw_page_furniture(canvas, doc, header=True, caller="branded_header_footer")


def branded_footer(canvas: Any, doc: Any) -> None:
    """``onPage(canvas, doc)`` callback drawing only the brand footer.

    For the first page of a document that opens with :func:`branded_letterhead`:
    the letterhead already carries the logo and the firm's name, so the header
    band on top of it would print the logo twice. Later pages go back to
    :func:`branded_header_footer`. Never raises.
    """
    _draw_page_furniture(canvas, doc, header=False, caller="branded_footer")


def _draw_page_furniture(
    canvas: Any,
    doc: Any,
    *,
    header: bool,
    caller: str,
    doc_type: str | None = None,
    default_line: bool = True,
) -> None:
    """The body of :func:`branded_header_footer`, with the header optional.

    ``doc_type`` selects the type's override of the appearance, as
    :func:`branded_letterhead` does. ``default_line`` is whether the footer
    prints the brand and the date when the workspace has saved no footer line
    of its own; a generator whose footer carries only what is saved passes
    ``False`` so its sample does not promise a line the document never prints.
    """
    try:
        from reportlab.lib import colors

        from app.core.pdf_fonts import BODY_FONT, pdf_fit_line, pdf_room_beside

        branding = _read_branding()
        appearance = _read_appearance(doc_type)

        page_w, page_h = _page_size(doc, canvas)
        left = float(getattr(doc, "leftMargin", 56.0) or 56.0)
        right_margin = float(getattr(doc, "rightMargin", 56.0) or 56.0)
        right_x = page_w - right_margin

        canvas.saveState()

        if header:
            _draw_header_band(canvas, branding, appearance, page_h=page_h, left=left, right_x=right_x)

        # -- Footer: brand + generated date (left), page number (right). --
        page_text = ""
        if appearance.get("show_page_numbers", True):
            if getattr(doc, "page_count", 0) > 0:
                page_text = f"Page {doc.page} of {doc.page_count}"
            else:
                page_text = f"Page {getattr(doc, 'page', 1)}"
        custom_footer = (appearance.get("footer_text") or "").strip()
        suffix = ""
        if custom_footer:
            # A workspace that sets its own footer line means it: the generated
            # date is dropped rather than appended, because these documents are
            # filed by customers and an unexpected date in the footer of a
            # signed contract is a support ticket.
            footer_left = custom_footer[:160]
        elif default_line:
            generated = datetime.now(tz=UTC).strftime("%Y-%m-%d")
            footer_left = _company_name(branding)[:160]
            suffix = f"  |  Generated: {generated}"
        else:
            footer_left = ""
        face, size = BODY_FONT, 7.0
        if footer_left:
            # The line shares its baseline with the page number, so it is fitted
            # into the room left beside it, in the face that will draw it: a
            # legal name is twice as long as the workspace name this footer was
            # written for, and a Chinese one twice as wide per character.
            footer_left, face, size = pdf_fit_line(
                footer_left,
                pdf_room_beside(right_x - left, page_text),
                suffix=suffix,
                base=BODY_FONT,
            )
        canvas.setFont(face, size)
        canvas.setFillColor(colors.HexColor(appearance.get("footer_color") or _FOOTER_COLOR))
        if footer_left:
            canvas.drawString(left, 10.0 * MM, footer_left)
        if page_text:
            if (face, size) != (BODY_FONT, 7.0):
                canvas.setFont(BODY_FONT, 7)
            canvas.drawRightString(right_x, 10.0 * MM, page_text)

        canvas.restoreState()
    except Exception:  # noqa: BLE001 - brand draw must never break a PDF export
        logger.debug("%s draw failed; page left unbranded", caller, exc_info=True)
        # Best-effort: balance the graphics state if we managed to save it.
        try:
            canvas.restoreState()
        except Exception:  # noqa: BLE001
            pass


def _draw_header_band(
    canvas: Any,
    branding: dict[str, Any],
    appearance: dict[str, Any],
    *,
    page_h: float,
    left: float,
    right_x: float,
) -> None:
    """The header band: logo or brand text, with a thin rule under it.

    Raises like any canvas call; :func:`_draw_page_furniture` guards it.
    """
    from reportlab.lib import colors

    from app.core.pdf_fonts import BOLD_FONT, pdf_fit_line

    profile = _read_company_profile()
    header_baseline = page_h - 15.0 * MM
    logo_top = page_h - 8.0 * MM
    align = appearance.get("logo_align") or "left"
    if align == "right":
        drew_logo = _draw_workspace_logo(canvas, branding, profile, right_x=right_x, top_y=logo_top)
    elif align == "center":
        drew_logo = _draw_workspace_logo(canvas, branding, profile, center_x=(left + right_x) / 2.0, top_y=logo_top)
    else:
        drew_logo = _draw_workspace_logo(canvas, branding, profile, x=left, top_y=logo_top)
    if not drew_logo:
        # The text brand follows the same alignment, so a workspace that has
        # not uploaded a logo still sees the setting take effect rather than
        # a control that appears to do nothing.
        # The name is drawn in the face that can carry it and shrunk to the band,
        # so a Chinese legal name is readable rather than a row of boxes running
        # past the margin. base keeps the weight: the ladder only goes bold when
        # it is told the face it starts from is a bold one.
        name, face, size = pdf_fit_line(_company_name(branding)[:80], right_x - left, size=9.0, base=BOLD_FONT)
        canvas.setFont(face, size)
        canvas.setFillColor(colors.HexColor(appearance.get("accent_color") or _HEADER_COLOR))
        if align == "right":
            canvas.drawRightString(right_x, header_baseline, name)
        elif align == "center":
            canvas.drawCentredString((left + right_x) / 2.0, header_baseline, name)
        else:
            canvas.drawString(left, header_baseline, name)
    canvas.setStrokeColor(colors.HexColor("#cccccc"))
    canvas.setLineWidth(0.5)
    line_y = page_h - 17.0 * MM
    canvas.line(left, line_y, right_x, line_y)


# One millimetre in points - reportlab's unit, inlined so this module needs no
# import-time reportlab dependency (the lazy imports above keep it import-safe).
MM = 72.0 / 25.4


def _page_size(doc: Any, canvas: Any = None) -> tuple[float, float]:
    """Return the (width, height) of the page being drawn, in points, A4 as fallback.

    The canvas is asked first. A document can change sheet from one page
    template to the next (a portrait summary followed by landscape lists),
    and ``doc.pagesize`` keeps the size the document was opened with, so
    furniture positioned from it lands above a landscape sheet, off the
    paper, with nothing raised. reportlab sets the canvas to the template's
    size before it calls ``onPage``, so the canvas is the page in hand.
    """
    for size in (getattr(canvas, "_pagesize", None), getattr(doc, "pagesize", None)):
        try:
            # A real page size only: a stand-in canvas answers any attribute
            # with something that is not one.
            if isinstance(size, (tuple, list)) and len(size) >= 2:
                return float(size[0]), float(size[1])
        except (TypeError, ValueError, IndexError):
            continue
    # A4 in points.
    return 595.2755905511812, 841.8897637795277


def branded_header_logo(canvas: Any, doc: Any, *, align: str = "right") -> bool:
    """Draw ONLY the uploaded workspace logo in a top corner of the header.

    For generators that already render their own header text (e.g. the project
    and document name) and only need the white-label logo to appear when one is
    configured. The company profile's document logo wins over the app logo when
    both are set. Draws nothing and returns ``False`` when no logo is set, so a
    name-only or default workspace is unaffected. Right-aligned by default so it
    clears a left-aligned header title; pass ``align="left"`` otherwise.
    Geometry is read from the live ``doc``. Never raises - a failed logo draw
    must not break the PDF export.
    """
    try:
        branding = _read_branding()
        profile = _read_company_profile()
        if not _logo_candidates(branding, profile):
            return False
        page_w, page_h = _page_size(doc, canvas)
        top_y = page_h - 8.0 * MM
        if align == "left":
            left = float(getattr(doc, "leftMargin", 56.0) or 56.0)
            return _draw_workspace_logo(canvas, branding, profile, x=left, top_y=top_y)
        right_margin = float(getattr(doc, "rightMargin", 56.0) or 56.0)
        return _draw_workspace_logo(canvas, branding, profile, right_x=page_w - right_margin, top_y=top_y)
    except Exception:  # noqa: BLE001 - a header logo must never break a PDF export
        logger.debug("branded_header_logo skipped (draw failed)", exc_info=True)
        return False


# -- Letterhead ----------------------------------------------------------------

#: Letterhead logo box (points). Larger than the header box because on a
#: letterhead the logo is the point, and 60 x 20 mm holds a wide wordmark and a
#: square mark alike without pushing the document title far down the page.
_LETTERHEAD_LOGO_MAX_W = 60.0 * MM
_LETTERHEAD_LOGO_MAX_H = 20.0 * MM
#: Centred, the logo sits above the block instead of beside it, so every
#: millimetre of it is added to the letterhead's height. Measured on the RFI
#: form: at the full 20 mm, with the address on three lines, a centred
#: letterhead pushed the signature block of an ordinary one-page RFI onto a
#: second page. A shorter box and the address on one line keep it on one.
_LETTERHEAD_STACKED_LOGO_MAX_H = 15.0 * MM
#: Space between the logo and the company block when they sit side by side.
_LETTERHEAD_GAP = 6.0 * MM
#: The company details under the name, and the rule under the letterhead. The
#: same greys the RFI form and the header band already print with.
_LETTERHEAD_MUTED = "#666666"
_LETTERHEAD_RULE = "#cccccc"


def branded_letterhead(width: float, doc_type: str | None = None) -> Any | None:
    """Return the firm's letterhead as a flowable for the top of page one.

    ``None`` unless the company profile calls for one (a legal name or a
    document logo, see :func:`app.core.company_profile.has_letterhead`) and the
    document appearance has ``show_letterhead`` on, so a generator can insert
    the result unconditionally and a workspace that never filled the profile in
    prints exactly what it printed before.

    The letterhead is the document logo, fitted into about 60 x 20 mm with its
    aspect kept, beside a company block: the legal name in bold, the address
    lines, the registration line and one contact line (phone, email and
    website, whichever are set), with a thin rule under the whole. The logo
    follows ``logo_align``: on the left the block sits right-aligned opposite
    it, on the right the block sits on the left, centred puts the logo above a
    centred block. Without a logo the block alone takes the logo's place.

    Every string is escaped before reportlab's paragraph parser sees it and
    gets its face per line from :func:`app.core.pdf_fonts.pdf_style_for_text`,
    so a Cyrillic name above a Latin address draws both, and a Thai name is
    shaped. Never raises: any failure returns ``None`` and the document goes out
    without a letterhead rather than not at all.

    Args:
        width: The frame width the letterhead spans, in points.
        doc_type: The generator's key in
            :data:`app.core.pdf_appearance.DOCUMENT_TYPES`, so the type's own
            override of the switch, the logo side and the name colour applies.
            ``None`` reads the workspace look alone.

    Returns:
        A reportlab flowable, or ``None``.
    """
    try:
        profile = _letterhead_profile()
        if profile is None:
            return None
        appearance = _read_appearance(doc_type)
        if not appearance.get("show_letterhead", True):
            return None
        return _build_letterhead(float(width), profile, _read_branding(), appearance)
    except Exception:  # noqa: BLE001 - a letterhead must never break a PDF export
        logger.debug("Letterhead skipped (build failed)", exc_info=True)
        return None


def _letterhead_logo(branding: dict[str, Any], profile: dict[str, Any], *, max_h: float) -> Any | None:
    """The best logo that decodes, as an Image fitted to the letterhead box."""
    from io import BytesIO

    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image

    for data_url in _logo_candidates(branding, profile):
        try:
            raw = _logo_image_bytes(data_url)
            if not raw:
                continue
            reader = ImageReader(BytesIO(raw))
            iw, ih = reader.getSize()
            if not iw or not ih:
                continue
            # Decode the pixels here rather than at draw time. A PNG whose
            # header reads but whose body is truncated would otherwise fail
            # inside the generator's doc.build, where nothing in this module
            # can catch it and the whole export would be lost.
            reader.getRGBData()
            # Never upscaled, like the header logo: a raster stretched past one
            # pixel per point prints soft. An SVG is rasterised large, so it
            # always fills the box. Worked out before the logo is shrunk, and
            # passed explicitly, so the box is the same either way.
            scale = min(_LETTERHEAD_LOGO_MAX_W / float(iw), max_h / float(ih), 1.0)
            return Image(
                BytesIO(_logo_raster_for_pdf(raw)),
                width=float(iw) * scale,
                height=float(ih) * scale,
                mask="auto",
            )
        except Exception:  # noqa: BLE001 - try the next logo, never raise
            logger.debug("Could not decode a logo for the letterhead", exc_info=True)
    return None


def _profile_text(profile: dict[str, Any], field: str) -> str:
    value = profile.get(field)
    return value.strip() if isinstance(value, str) else ""


def _build_letterhead(
    width: float,
    profile: dict[str, Any],
    branding: dict[str, Any],
    appearance: dict[str, Any],
) -> Any | None:
    """Lay the letterhead out. Raises; :func:`branded_letterhead` guards it."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text

    align = appearance.get("logo_align")
    if align not in ("left", "center", "right"):
        align = "left"
    logo_max_h = _LETTERHEAD_STACKED_LOGO_MAX_H if align == "center" else _LETTERHEAD_LOGO_MAX_H
    logo = _letterhead_logo(branding, profile, max_h=logo_max_h)
    stacked = logo is not None and align == "center"

    # Opposite the logo when there is one; where the logo would have been when
    # there is not, the way the header band's text brand follows the setting.
    if logo is None:
        text_align = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}[align]
    else:
        text_align = {"left": TA_RIGHT, "center": TA_CENTER, "right": TA_LEFT}[align]
    name_style = ParagraphStyle(
        "LetterheadName",
        fontName=BOLD_FONT,
        fontSize=9,
        leading=11.5,
        textColor=colors.HexColor(appearance.get("accent_color") or _HEADER_COLOR),
        alignment=text_align,
    )
    detail_style = ParagraphStyle(
        "LetterheadDetail",
        fontName=BODY_FONT,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor(_LETTERHEAD_MUTED),
        alignment=text_align,
    )

    def _line(text: str, style: ParagraphStyle) -> Paragraph:
        return Paragraph(html.escape(text, quote=True), pdf_style_for_text(style, text))

    block: list[Any] = []
    legal_name = _profile_text(profile, "legal_name")
    if legal_name:
        block.append(_line(legal_name, name_style))
    address = [line.strip() for line in _profile_text(profile, "address").split("\n") if line.strip()]
    if stacked and address:
        # Under a centred logo the address runs on one line, the way centred
        # letterheads set it; see _LETTERHEAD_STACKED_LOGO_MAX_H for why.
        block.append(_line(" · ".join(address), detail_style))
    else:
        block.extend(_line(line, detail_style) for line in address)
    registration = _profile_text(profile, "registration_line")
    if registration:
        block.append(_line(registration, detail_style))
    contact = " · ".join(
        part for part in (_profile_text(profile, key) for key in ("phone", "email", "website")) if part
    )
    if contact:
        block.append(_line(contact, detail_style))

    if logo is None and not block:
        return None

    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if logo is None or not block:
        rows: list[list[Any]] = [[block or [logo]]]
        col_widths = [width]
        commands.append(("ALIGN", (0, 0), (0, 0), align.upper()))
    elif stacked:
        rows = [[[logo]], [block]]
        col_widths = [width]
        commands.append(("ALIGN", (0, 0), (-1, -1), "CENTER"))
        commands.append(("BOTTOMPADDING", (0, 0), (0, 0), 2.0 * MM))
    else:
        # The logo column is as wide as the logo plus the gap, so the block
        # gets every point the logo does not use; a narrow block would wrap a
        # long registration line into a tower.
        logo_col = min(float(logo.drawWidth) + _LETTERHEAD_GAP, width / 2.0)
        if align == "right":
            rows = [[block, [logo]]]
            col_widths = [width - logo_col, logo_col]
            commands.append(("ALIGN", (1, 0), (1, 0), "RIGHT"))
        else:
            rows = [[[logo], block]]
            col_widths = [logo_col, width - logo_col]
            commands.append(("ALIGN", (0, 0), (0, 0), "LEFT"))
    commands.append(("BOTTOMPADDING", (0, -1), (-1, -1), 3.0 * MM))
    commands.append(("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor(_LETTERHEAD_RULE)))
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", spaceAfter=5.0 * MM)
    table.setStyle(TableStyle(commands))
    return table


# -- Settings preview ------------------------------------------------------------

#: Placeholder body of the sample document. Neutral on purpose: the page is
#: about the look, so nothing in it may read as a real project's content.
_SAMPLE_TITLE = "Sample document"
_SAMPLE_PARAGRAPHS = (
    "This sample shows the letterhead, footer, colours, text size and page size currently saved for this "
    "workspace, drawn by the same code that draws the exported documents.",
    "The text on this page is only a placeholder. Nothing in it is taken from a project, and generating it "
    "changes nothing in the workspace.",
)
#: The same for a document type's sample, which is drawn on the type's own
#: sheet rather than the workspace page size.
_TYPED_SAMPLE_PARAGRAPHS = (
    "This sample shows the letterhead and footer this kind of document is printed with, on the sheet it is "
    "printed on, drawn by the same code that draws the exported documents.",
    _SAMPLE_PARAGRAPHS[1],
)


def _sample_sheet(
    sheet: Any, paper: tuple[float, float] | None
) -> tuple[tuple[float, float], tuple[float, float, float, float], float]:
    """A type's sheet as ``(page size, (left, right, top, bottom) margins, frame padding)`` in points."""
    from app.core.paper_size import DEFAULT_PAPER_SIZE, PAPER_SIZES
    from app.core.pdf_appearance import USER_PAPER

    if sheet.page_size == USER_PAPER:
        width, height = paper or PAPER_SIZES[DEFAULT_PAPER_SIZE]
    else:
        width, height = PAPER_SIZES[sheet.page_size]
    size = (max(width, height), min(width, height)) if sheet.landscape else (width, height)
    left, right, top, bottom = (value * MM for value in sheet.margins_mm)
    return size, (left, right, top, bottom), float(sheet.frame_padding_pt)


def render_sample_pdf(doc_type: str | None = None, *, paper: tuple[float, float] | None = None) -> bytes:
    """Render a one-page sample document with the saved look, for the settings page.

    The settings page can only promise "this is how your documents will look"
    by showing a page the server drew, so this is built from the same pieces a
    generator uses: the letterhead, :func:`branded_footer` under it on the first
    page (:func:`branded_header_footer` when there is no letterhead), the saved
    page size and margin, and the body size and accent colour.

    The margin is widened where it would run the body into the header band
    (17 mm from the top edge) or the footer (10 mm from the bottom), which a
    narrow saved margin otherwise does.

    With ``doc_type`` the sample is drawn with that type's override laid over
    the workspace look, titled with the type's name, and with the page
    furniture the type's generator actually prints, so no setting moves the
    preview without moving the document:

    * the header is :func:`branded_header_logo` (the logo alone, top right,
      left off page one under a letterhead), never the header band, because no
      wired generator draws the band; the band honours ``logo_align`` and
      ``accent_color``, which would have moved the preview of a workspace with
      no letterhead while its documents stayed put;
    * the title keeps the platform colour, because a generator's accent colour
      reaches only the company name in its letterhead;
    * the footer is drawn only for a type that prints one (the fields list
      says so), and is the shared footer, not the RFI's own translated one;
    * the page is the type's own sheet
      (:class:`app.core.pdf_appearance.DocumentSheet`): its paper, orientation,
      margins and frame padding, so the letterhead lands where the document
      puts it. The workspace page size and margin apply to neither.

    Args:
        doc_type: A key of :data:`app.core.pdf_appearance.DOCUMENT_TYPES`, or
            ``None`` for the workspace look alone.
        paper: ``(width, height)`` in points of the reader's paper preference,
            for a type printed on the sender's paper (the transmittal). A4 when
            not given.

    Returns:
        The PDF as bytes, starting with ``b"%PDF"``.
    """
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph

    from app.core.pdf_appearance import DEFAULT_APPEARANCE, DOCUMENT_TYPES, resolve_page_size
    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, pdf_style_for_text, register_pdf_fonts

    register_pdf_fonts()
    kind = DOCUMENT_TYPES.get(doc_type) if doc_type is not None else None
    if kind is not None and kind.sheet is None:
        kind = None
    title = f"{_SAMPLE_TITLE}: {kind.label}" if kind is not None else _SAMPLE_TITLE
    appearance = _read_appearance(doc_type)
    base_size = float(appearance.get("base_font_size") or DEFAULT_APPEARANCE["base_font_size"])
    meta = branded_doc_metadata()
    if kind is not None:
        page_size, (left, right, top, bottom), padding = _sample_sheet(kind.sheet, paper)
    else:
        page_size = resolve_page_size(appearance)
        margin = float(appearance.get("margin_mm") or DEFAULT_APPEARANCE["margin_mm"]) * MM
        left, right, top, bottom = margin, margin, max(margin, 22.0 * MM), max(margin, 18.0 * MM)
        padding = 0.0

    buffer = BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=left,
        rightMargin=right,
        topMargin=top,
        bottomMargin=bottom,
        title=title,
        author=meta["author"],
        subject=title,
        creator=meta["creator"],
        producer=meta["producer"],
        keywords=meta["keywords"],
    )

    title_style = ParagraphStyle(
        "SampleTitle",
        fontName=BOLD_FONT,
        fontSize=base_size * 1.6,
        leading=base_size * 2.0,
        textColor=colors.HexColor(
            _HEADER_COLOR if kind is not None else appearance.get("accent_color") or _HEADER_COLOR
        ),
        spaceAfter=base_size * 0.8,
    )
    body_style = ParagraphStyle(
        "SampleBody",
        fontName=BODY_FONT,
        fontSize=base_size,
        leading=base_size * 1.4,
        spaceAfter=base_size * 0.8,
    )

    story: list[Any] = []
    letterhead = branded_letterhead(doc.width - 2 * padding, doc_type=doc_type)
    if letterhead is not None:
        story.append(letterhead)
    story.append(Paragraph(html.escape(title), pdf_style_for_text(title_style, title)))
    paragraphs = _TYPED_SAMPLE_PARAGRAPHS if kind is not None else _SAMPLE_PARAGRAPHS
    story.extend(Paragraph(html.escape(text), body_style) for text in paragraphs)

    def _frame(frame_id: str) -> Frame:
        # The workspace sample has no inner padding, so the letterhead and its
        # rule line up with the header rule, which is drawn from margin to
        # margin. A type's sample keeps its generator's padding instead.
        return Frame(
            doc.leftMargin,
            doc.bottomMargin,
            doc.width,
            doc.height,
            leftPadding=padding,
            rightPadding=padding,
            topPadding=padding,
            bottomPadding=padding,
            id=frame_id,
        )

    first_page: Any = branded_footer if letterhead is not None else branded_header_footer
    later_pages: Any = branded_header_footer
    if kind is not None:
        prints_footer = "footer_text" in kind.fields

        def _typed_page(canvas: Any, page_doc: Any) -> None:
            if prints_footer:
                _draw_page_furniture(
                    canvas,
                    page_doc,
                    header=False,
                    caller="render_sample_pdf",
                    doc_type=doc_type,
                    default_line=kind.default_footer_line,
                )
            if not (letterhead is not None and page_doc.page == 1):
                branded_header_logo(canvas, page_doc)

        first_page = later_pages = _typed_page

    doc.addPageTemplates(
        [
            PageTemplate(id="first", frames=[_frame("first")], onPage=first_page, autoNextPageTemplate="later"),
            PageTemplate(id="later", frames=[_frame("later")], onPage=later_pages),
        ]
    )
    doc.build(story)
    return buffer.getvalue()


__all__ = [
    "DEFAULT_BRAND",
    "branded_appearance",
    "branded_cover_brand",
    "branded_doc_metadata",
    "branded_footer",
    "branded_header_footer",
    "branded_header_logo",
    "branded_letterhead",
    "render_sample_pdf",
]

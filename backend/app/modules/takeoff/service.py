"""‌⁠‍Takeoff business logic."""

import io
import logging
import math
import os
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.repository import MeasurementRepository, TakeoffRepository
from app.modules.takeoff.schemas import (
    PointSchema,
    TakeoffMeasurementCreate,
    TakeoffMeasurementUpdate,
)

logger = logging.getLogger(__name__)


# ── PDF stability gates (Indian-user ticket, v3.0.x) ────────────────────────


def _is_encrypted_pdf(content: bytes) -> bool:
    """Detect password-protected PDFs by sniffing the trailer block.

    PDF encryption flags live in the trailer dictionary as:
    * ``/Encrypt N N R``  - indirect reference form (most generators)
    * ``/Encrypt <<``     - inline dict form (rare but valid)

    We scan only the LAST 8 KB of the file (where trailers live) to
    avoid false positives from "/Encrypt" appearing inside content
    streams earlier in the file.  Empty or sub-8KB files are treated
    as not encrypted (the upstream gate already rejects zero-byte
    uploads).

    Improved (D-TKC-ENC01): the previous pattern only matched the
    indirect-reference form ``/Encrypt <digit>``.  Some generators emit
    an inline encryption dictionary ``/Encrypt <<`` instead. We now
    match both forms so password-protected PDFs from Acrobat/LibreOffice
    using either syntax are correctly rejected before the expensive
    pdfplumber parse attempt.
    """
    if not content:
        return False
    tail = content[-8192:] if len(content) > 8192 else content
    # Match both: /Encrypt N N R  AND  /Encrypt <<
    return bool(re.search(rb"/Encrypt\s+(?:\d|<<)", tail))


def _max_upload_bytes() -> int:
    """Effective per-upload byte cap from ``OE_TAKEOFF_MAX_UPLOAD_MB``.

    Returns 0 ("unlimited") when the env var is missing, empty,
    unparseable, zero, or negative - matches the product policy
    (v2.9.12) of NOT capping uploads by default. Operators on
    constrained deployments can opt in via the env var.
    """
    raw = os.environ.get("OE_TAKEOFF_MAX_UPLOAD_MB", "").strip()
    if not raw:
        return 0
    try:
        mb = int(raw)
    except (ValueError, TypeError):
        return 0
    if mb <= 0:
        return 0
    return mb * 1024 * 1024


def _ocr_dpi() -> int:
    """OCR rendering DPI for scanned PDFs. Defaults 200, clamped 72-600."""
    raw = os.environ.get("OE_TAKEOFF_OCR_DPI", "").strip()
    if not raw:
        return 200
    try:
        dpi = int(raw)
    except (ValueError, TypeError):
        return 200
    return max(72, min(600, dpi))


def _ocr_langs() -> list[str]:
    """Languages fed to PaddleOCR - defaults cover Indian + Arabic scripts.

    English, Hindi (Devanagari), Tamil, Telugu, Arabic by default.
    Operators on locale-specific deployments can override via
    ``OE_TAKEOFF_OCR_LANGS=en,hi,zh``.
    """
    raw = os.environ.get("OE_TAKEOFF_OCR_LANGS", "").strip()
    if not raw:
        return ["en", "hi", "ta", "te", "ar"]
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def _parse_indian_number(value: Any) -> float:
    """Parse Indian / US / EU / imperial number strings, never raises.

    Handles:

    * Indian lakh/crore grouping: ``1,00,000`` -> 100000
    * US/UK thousand-grouping: ``1,500.50`` -> 1500.5
    * German/EU thousands-dot + decimal-comma: ``1.500,50`` -> 1500.5
    * Decimal-comma alone: ``12,5`` -> 12.5
    * Trailing unit suffixes: ``1500mm`` -> 1500
    * Imperial feet-inches: ``5'-6"`` -> 5.5
    * Empty / None / pure-text -> 0.0

    Returns 0.0 (never raises) so one bad cell does not kill the
    whole row in ``extract_tables``.
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    # Imperial feet-inches: 5'-6" -> 5.5
    fi = re.match(r"^([\-+]?\d+)\s*'\s*-?\s*(\d+)\s*\"?$", text)
    if fi:
        feet = int(fi.group(1))
        inches = int(fi.group(2))
        sign = -1 if feet < 0 else 1
        return sign * (abs(feet) + inches / 12.0)

    # Strip trailing unit suffix to expose the numeric core. Units may
    # carry digits themselves (m2, m3, ft2) so we allow that in the
    # match group. The regex is intentionally permissive - anything
    # after the first run of digits/separators is treated as a unit
    # suffix and discarded for the purpose of *number* parsing.
    m = re.match(r"^([\-+]?[\d.,]+)\s*([a-zA-Z²³.\d\s]*)$", text)
    numeric_part = m.group(1).strip() if m else text

    # EU style: thousands-dot + decimal-comma (1.500,50)
    if re.fullmatch(r"[\-+]?\d{1,3}(\.\d{3})+,\d+", numeric_part):
        return float(numeric_part.replace(".", "").replace(",", "."))

    # Indian style: 1,23,45,678 - 2-digit groups give it away.
    if re.fullmatch(r"[\-+]?\d{1,3}(,\d{2})+,\d{3}", numeric_part):
        return float(numeric_part.replace(",", ""))

    # US/UK style: thousands-comma + decimal-dot
    if re.fullmatch(r"[\-+]?\d{1,3}(,\d{3})+(\.\d+)?", numeric_part):
        return float(numeric_part.replace(",", ""))

    # Decimal-comma alone (12,5)
    if re.fullmatch(r"[\-+]?\d+,\d+", numeric_part):
        return float(numeric_part.replace(",", "."))

    # Plain int / float
    try:
        return float(numeric_part)
    except ValueError:
        pass

    # Last-resort: pull the first digit run from the raw string.
    fallback = re.search(r"[\-+]?\d+(\.\d+)?", text)
    if fallback:
        try:
            return float(fallback.group(0))
        except ValueError:
            return 0.0
    return 0.0


# Unit alias map. Keys are case-folded, dot-stripped, whitespace-collapsed.
_UNIT_ALIASES: dict[str, str] = {
    # Length
    "m": "m",
    "rmt": "m",
    "rm": "m",
    "runningmetre": "m",
    "runningmeter": "m",
    "lm": "m",
    "ml": "m",
    "mm": "mm",
    "cm": "cm",
    # Area
    "m2": "m2",
    "sqm": "m2",
    "sq m": "m2",
    "squaremetre": "m2",
    "squaremeter": "m2",
    "sft": "sft",
    "sqft": "sft",
    "sq ft": "sft",
    "squarefeet": "sft",
    "squarefoot": "sft",
    # Volume
    "m3": "m3",
    "cum": "m3",
    "cu m": "m3",
    "cubicmetre": "m3",
    "cubicmeter": "m3",
    "cft": "cft",
    "cuft": "cft",
    "cu ft": "cft",
    "cubicfeet": "cft",
    # Weight
    "kg": "kg",
    "g": "g",
    "t": "t",
    "mt": "t",
    "tonne": "t",
    "ton": "t",
    # Count
    "pcs": "pcs",
    "pc": "pcs",
    "nos": "pcs",
    "no": "pcs",
    "number": "pcs",
    "qty": "pcs",
    "ea": "pcs",
    # Lump sum
    "lsum": "lsum",
    "ls": "lsum",
    "lumpsum": "lsum",
}


# Header keyword → semantic role. Used by ``_map_table_columns`` to
# locate the description / quantity / unit columns by their header text
# instead of fixed positions (D-TKC-014). Covers EN / DE / FR / ES so a
# GAEB/DIN, NRM or MasterFormat table is read correctly regardless of
# column order.
_HEADER_QTY_KEYWORDS = (
    "quantity",
    "qty",
    "menge",
    "anzahl",
    "quantite",
    "quantité",
    "cantidad",
    "amount",
    "mass",
    "masse",
)
_HEADER_UNIT_KEYWORDS = (
    "unit",
    "uom",
    "einheit",
    "einh",
    "me",  # GAEB "Mengeneinheit"
    "unite",
    "unité",
    "unidad",
)
_HEADER_DESC_KEYWORDS = (
    "description",
    "desc",
    "bezeichnung",
    "beschreibung",
    "text",
    "leistung",
    "designation",
    "désignation",
    "descripcion",
    "descripción",
    "item",
    "position",
)


def _map_table_columns(headers: list[str]) -> dict[str, int | None]:
    """Resolve which column index holds description / quantity / unit.

    Matches the header row by keyword (D-TKC-014). Falls back to the
    historical positional assumption (col0=desc, col1=qty, col2=unit)
    ONLY for roles a header keyword could not locate, so a table whose
    columns are ordered ``[Pos | Unit | Qty | Description]`` is read
    correctly instead of mis-reading qty/unit.
    """

    def _find(keywords: tuple[str, ...]) -> int | None:
        for i, h in enumerate(headers):
            hl = h.lower().strip()
            if any(kw == hl for kw in keywords):
                return i
        # Substring pass (e.g. "total quantity", "unit of measure").
        for i, h in enumerate(headers):
            hl = h.lower().strip()
            if any(kw in hl for kw in keywords):
                return i
        return None

    desc_i = _find(_HEADER_DESC_KEYWORDS)
    qty_i = _find(_HEADER_QTY_KEYWORDS)
    unit_i = _find(_HEADER_UNIT_KEYWORDS)

    n = len(headers)
    if desc_i is None:
        desc_i = 0 if n > 0 else None
    if qty_i is None:
        qty_i = 1 if n > 1 else None
    if unit_i is None:
        unit_i = 2 if n > 2 else None
    return {"description": desc_i, "quantity": qty_i, "unit": unit_i}


def _normalize_unit(raw: Any) -> str:
    """Map an arbitrary unit string to the canonical BOQ form.

    Returns ``"pcs"`` for empty / ``None`` input. Unknown units pass
    through lowercased - rejecting a real-world unit would be worse
    UX than letting the user edit post-import.
    """
    if raw is None:
        return "pcs"
    text = str(raw).strip()
    if not text:
        return "pcs"
    key = re.sub(r"\s+", " ", text.lower().replace(".", "")).strip()
    if key in _UNIT_ALIASES:
        return _UNIT_ALIASES[key]
    nospace = key.replace(" ", "")
    if nospace in _UNIT_ALIASES:
        return _UNIT_ALIASES[nospace]
    return key


# ── Audit B8: server-side measurement recompute ─────────────────────────────


def _points_to_xy(points: list[Any]) -> list[tuple[float, float]]:
    """Normalise a points list into ``[(x, y), ...]`` floats.

    Accepts both Pydantic ``PointSchema`` and raw dicts (the bulk-create
    path passes the former, restored DB rows pass the latter). Bad
    entries are dropped silently - geometry just falls back to whatever
    is salvageable rather than rejecting the whole measurement.
    """
    out: list[tuple[float, float]] = []
    for p in points or []:
        try:
            if isinstance(p, PointSchema):
                out.append((float(p.x), float(p.y)))
            elif isinstance(p, dict):
                out.append((float(p["x"]), float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    """Polygon area via the shoelace formula, in **pixel-squared** units.

    The first point is treated as the polygon's start and the boundary
    is closed back to it automatically (so the caller can pass either
    open or closed vertex lists).
    """
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _polyline_length(pts: list[tuple[float, float]]) -> float:
    """Sum of euclidean distances between consecutive points, in pixels."""
    n = len(pts)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(1, n):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        total += math.hypot(dx, dy)
    return total


def recompute_measurement_value(
    *,
    measurement_type: str | None,
    points: list[Any] | None,
    scale_pixels_per_unit: float | None,
    count_value: int | None,
    client_value: float | None,
) -> float | None:
    """Recompute ``measurement_value`` server-side from raw geometry.

    Audit B8 - was a cost-integrity hole. The client used to send both
    the raw ``points`` array AND the derived ``measurement_value``, so
    a malicious or buggy client could draw a tiny rectangle and claim
    9999 m² (which then flowed straight into BOQ totals via link-to-BOQ).
    We now derive ``measurement_value`` from (points × scale) on the
    server. The client's ``client_value`` is only used as a fallback
    for measurement types where we can't reconstruct geometry
    (``count``, ``text``, ``arrow``, ``highlight``, ``cloud``,
    ``rectangle``) or when ``scale_pixels_per_unit`` is missing.

    Returns:
        Server-derived value when computable, otherwise the
        ``client_value`` echo so external annotation flows aren't
        broken. ``None`` if nothing is recoverable.
    """
    mtype = (measurement_type or "").strip().lower()
    xy = _points_to_xy(points or [])
    scale = scale_pixels_per_unit or 0.0

    # Count types ignore points; trust the explicit count_value field.
    if mtype == "count":
        if count_value is not None and count_value >= 0:
            return float(count_value)
        return client_value

    # Annotation types don't carry a measurement value at all - but if
    # the client sent one we preserve it (e.g. for "text" labels that
    # carry a numeric tag for downstream reporting).
    if mtype in {"cloud", "arrow", "text", "rectangle", "highlight"}:
        return client_value

    # Geometry-driven types require a scale and at least 2 points to be
    # meaningfully recomputable.
    if scale <= 0 or len(xy) < 2:
        return client_value

    if mtype == "distance":
        # Linear measure: total polyline length. For two-point
        # distance this collapses to a straight-line euclidean.
        return _polyline_length(xy) / scale

    if mtype == "polyline":
        # Same math as distance - explicit alias so the client can
        # signal intent ("walking path" vs "wall length").
        return _polyline_length(xy) / scale

    if mtype == "area":
        # 2D polygon area. Scale is pixels per linear unit, so divide
        # by scale² to convert pixel² to unit².
        return _shoelace_area(xy) / (scale * scale)

    if mtype == "volume":
        # Volume on a takeoff page is always area × depth. We
        # recompute the base area here and leave depth multiplication
        # to the caller (it lives in a separate field).
        return _shoelace_area(xy) / (scale * scale)

    # Unknown type - preserve client value rather than nulling it out.
    return client_value


def recompute_volume_value(
    *,
    measurement_type: str | None,
    points: list[Any] | None,
    scale_pixels_per_unit: float | None,
    depth: float | None,
    client_volume: float | None,
) -> float | None:
    """Recompute a ``volume`` measurement's ``volume`` column server-side.

    Audit B8 closed the client-trust hole for ``measurement_value`` but
    left it open for ``volume``: ``recompute_measurement_value`` only
    returns the *base area* for the ``volume`` type (depth multiplication
    is intentionally deferred to here), while ``_pick_takeoff_value`` reads
    the dedicated ``volume`` column when pushing a quantity into a BOQ
    position. Persisting the raw client ``volume`` therefore let a client
    draw a tiny shape yet claim an arbitrary volume that flowed straight
    into BOQ money math - the exact integrity gap B8 was meant to close.

    We derive ``volume = base_area * depth`` from the same (points × scale)
    geometry the area recompute uses, with a non-negative ``depth``. The
    client value is only trusted as a fallback when the volume cannot be
    reconstructed (non-volume type, missing/invalid scale, fewer than three
    points, or a missing/invalid depth) so external annotation flows and
    legacy rows are not broken. A negative client volume is clamped to
    ``None`` rather than poisoning a BOQ total.

    Args:
        measurement_type: The measurement ``type`` (only ``volume`` is
            recomputed; any other type echoes ``client_volume``).
        points: Raw polygon vertices (``PointSchema`` or dicts).
        scale_pixels_per_unit: Pixels per linear unit for this page.
        depth: Extrusion depth in the same linear unit as the area.
        client_volume: The volume the client sent (fallback only).

    Returns:
        Server-derived ``base_area * depth`` when computable, otherwise the
        sanitised ``client_volume`` echo, or ``None`` when nothing usable.
    """
    if (measurement_type or "").strip().lower() != "volume":
        return client_volume

    xy = _points_to_xy(points or [])
    scale = scale_pixels_per_unit or 0.0

    # Need a valid scale, a closed polygon (>= 3 points), and a sane depth
    # to reconstruct the volume; otherwise fall back to the client echo.
    if scale > 0 and len(xy) >= 3 and depth is not None and depth >= 0:
        base_area = _shoelace_area(xy) / (scale * scale)
        return base_area * float(depth)

    # Not recomputable - trust the client value but never let a negative
    # volume through into a BOQ quantity.
    if client_volume is not None and client_volume < 0:
        return None
    return client_volume


def _pick_takeoff_value(measurement: Any) -> float | None:
    """Pick the scalar value to push into a BOQ position's ``quantity``.

    Dispatches on the measurement ``type`` to read the right column:

    * ``volume`` - prefer the dedicated ``volume`` column (area × depth);
      fall back to ``measurement_value`` for legacy rows that predate the
      volume column.
    * ``count`` - read ``count_value``. ``0`` is a valid count (e.g. "no
      doors on this sheet") and round-trips as ``0.0`` rather than the
      ``None`` no-op.
    * everything else (``distance`` / ``area`` / ``polyline`` / default) -
      read the canonical ``measurement_value`` scalar.

    Every read is coerced through :func:`float` inside a try/except so a
    string-typed column (``Numeric`` round-trips as ``Decimal`` but a
    sloppy fixture or a garbage value should not crash the link flow).
    Returns ``None`` when the relevant column is empty or unparseable so
    the caller treats the push as a no-op and never zeroes the existing
    BOQ quantity.
    """
    mtype = (getattr(measurement, "type", None) or "").strip().lower()

    if mtype == "volume":
        volume = getattr(measurement, "volume", None)
        if volume is not None:
            try:
                return float(volume)
            except (ValueError, TypeError):
                return None
        # Legacy volume rows without a ``volume`` column fall through to
        # the measurement_value scalar below.
    elif mtype == "count":
        count = getattr(measurement, "count_value", None)
        if count is None:
            return None
        try:
            return float(count)
        except (ValueError, TypeError):
            return None

    value = getattr(measurement, "measurement_value", None)
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# Dimension groups for the push_quantity compatibility guard. A measurement
# value is only a valid BOQ quantity when its dimension (length / area /
# volume / count) matches the target position's unit; otherwise an m2 takeoff
# pushed onto a per-m3 position would silently produce a wrong total.
_UNIT_DIMENSION: dict[str, str] = {
    "m": "length",
    "lm": "length",
    "ml": "length",
    "m2": "area",
    "m3": "volume",
    "kg": "mass",
    "t": "mass",
    "pcs": "count",
    "ea": "count",
    "stk": "count",
    "lsum": "lsum",
    "h": "time",
}

# Measurement ``type`` to dimension. The geometric type is the authoritative
# dimension of a takeoff value; ``measurement_unit`` is only a fallback.
_MEASUREMENT_TYPE_DIMENSION: dict[str, str] = {
    "distance": "length",
    "polyline": "length",
    "area": "area",
    "volume": "volume",
    "count": "count",
}


def _unit_dimension(unit: str | None) -> str | None:
    """Map a unit code to its dimension group, or ``None`` when unknown.

    Folds superscripts (``m²`` -> ``m2``) and case so the comparison works
    on the spellings the BOQ and takeoff editors actually store.
    """
    if not unit:
        return None
    cleaned = unit.strip().lower().replace("²", "2").replace("³", "3")
    cleaned = cleaned.replace("^", "").replace("**", "")
    return _UNIT_DIMENSION.get(cleaned)


def _measurement_dimension(measurement: Any) -> str | None:
    """Dimension of a takeoff measurement from its ``type``, then unit.

    Returns ``None`` when neither the type nor the unit maps to a known
    dimension so the push guard can stay conservative and allow it.
    """
    mtype = (getattr(measurement, "type", None) or "").strip().lower()
    dim = _MEASUREMENT_TYPE_DIMENSION.get(mtype)
    if dim is not None:
        return dim
    return _unit_dimension(getattr(measurement, "measurement_unit", None))


# Directory where uploaded PDF files are stored on disk
_TAKEOFF_DOCUMENTS_DIR = Path.home() / ".openestimator" / "takeoff_documents"


def _describe_pdf_input(content: bytes, *, filename: str | None = None) -> str:
    """‌⁠‍Build a short server-side diagnostic string for a PDF blob.

    Includes size, the ``%PDF-`` magic header presence, and a filename
    extension guess.  Kept free of any filesystem paths so the return
    value is safe to log (but we never surface it to API callers).
    """
    size = len(content) if content is not None else 0
    has_magic = bool(content and content[:5] == b"%PDF-")
    ext = Path(filename).suffix.lower() if filename else ""
    name_hint = filename or "<anonymous>"
    return f"filename={name_hint!r} size={size}B ext={ext!r} has_pdf_magic={has_magic}"


def _extract_pdf_pages(content: bytes, *, filename: str | None = None) -> list[dict]:
    """‌⁠‍Extract text and tables from each page of a PDF.

    Returns a list of dicts: [{ page: 1, text: "...", tables: [...] }, ...]

    Parsing failures are logged with the input fingerprint (size, magic
    bytes, filename hint) so a production incident can be triaged
    without needing access to the uploaded bytes themselves.  We return
    an empty list on total failure - the caller still persists the
    document row so the user can re-upload without losing ownership.
    """
    pages: list[dict] = []
    input_fp = _describe_pdf_input(content, filename=filename)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = ""
                page_tables: list[list[list[str]]] = []

                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        cleaned = [[str(cell or "") for cell in row] for row in table]
                        page_tables.append(cleaned)
                        for row in cleaned:
                            page_text += "\t".join(row) + "\n"
                else:
                    text = page.extract_text()
                    if text:
                        page_text = text

                pages.append(
                    {
                        "page": i,
                        "text": page_text.strip(),
                        "tables": page_tables,
                    }
                )
    except Exception:
        # First-pass parser failed - log it with the full stack and fall
        # back to pymupdf.  We log at WARNING (not EXCEPTION) because a
        # fallback is about to be attempted; the real red line is only
        # drawn if both parsers fail.
        logger.warning(
            "takeoff.pdf_extract pdfplumber failed (%s) - falling back to pymupdf",
            input_fp,
            exc_info=True,
        )
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            for i, page in enumerate(doc, start=1):
                text = page.get_text()
                pages.append({"page": i, "text": text.strip(), "tables": []})
            doc.close()
        except Exception:
            logger.exception(
                "takeoff.pdf_extract both pdfplumber and pymupdf failed (%s) - document will have no extracted pages",
                input_fp,
            )

    return pages


def validate_page_for_document(doc: Any, page: int) -> None:
    """Reject ``page`` if it is outside the 1-indexed range for ``doc``.

    Pages are 1-indexed; ``doc.pages`` is the total page count. Valid
    range is therefore ``[1, doc.pages]``. Raises :class:`HTTPException`
    (422) when ``page < 1`` or ``page > doc.pages``. A document with
    ``pages == 0`` (parse failure) rejects any page request.

    This is the service-level guard for direct callers; Pydantic schema
    validation (``ge=1``) catches the negative-page case earlier on the
    request edge.
    """
    from fastapi import HTTPException  # local import - avoid cycle

    pages = int(getattr(doc, "pages", 0) or 0)
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail=f"page must be >= 1 (got {page})",
        )
    if pages < 1:
        raise HTTPException(
            status_code=422,
            detail="page out of range - document has 0 pages",
        )
    if page > pages:
        raise HTTPException(
            status_code=422,
            detail=f"page {page} is out of range (document has {pages} pages)",
        )


def _count_pdf_pages(content: bytes, *, filename: str | None = None) -> int:
    """Count the number of pages in a PDF.

    Mirrors :func:`_extract_pdf_pages` - pdfplumber first, pymupdf as a
    fallback, zero on double-failure.  Both failure paths log the input
    fingerprint so operators can correlate the log line with whatever
    the caller uploaded without leaking the bytes themselves.
    """
    input_fp = _describe_pdf_input(content, filename=filename)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return len(pdf.pages)
    except Exception:
        logger.warning(
            "takeoff.pdf_count pdfplumber failed (%s) - falling back to pymupdf",
            input_fp,
            exc_info=True,
        )
        try:
            import pymupdf

            doc = pymupdf.open(stream=content, filetype="pdf")
            count = len(doc)
            doc.close()
            return count
        except Exception:
            logger.exception(
                "takeoff.pdf_count both pdfplumber and pymupdf failed (%s) - reporting zero pages",
                input_fp,
            )
            return 0


# ── Revision compare (Item 17) ──────────────────────────────────────────────


def _measurement_compare_key(m: Any) -> str:
    """Stable match key for a measurement across two takeoff documents.

    Prefers ``metadata.compare_key`` (a key an importer can stamp so the
    same logical measurement matches across re-uploads), otherwise falls
    back to the natural tuple ``(page, type, group_name, annotation)``.
    Two distinct measurements that happen to share that tuple still match
    - which is the correct behaviour for a single logical takeoff item
    that was re-measured on the new revision.
    """
    meta = getattr(m, "metadata_", None) or {}
    if isinstance(meta, dict):
        ck = meta.get("compare_key")
        if ck:
            return f"ck:{str(ck).strip()}"
    page = getattr(m, "page", None)
    mtype = (getattr(m, "type", None) or "").strip().lower()
    group = (getattr(m, "group_name", None) or "").strip().lower()
    annotation = (getattr(m, "annotation", None) or "").strip().lower()
    return f"nat:{page}|{mtype}|{group}|{annotation}"


def _measure_to_float(value: Any) -> float | None:
    """Coerce a ``Decimal``/number measurement to ``float`` or ``None``."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError, InvalidOperation):
        return None


def _compute_cost_impact(
    *,
    old_value: float | None,
    new_value: float | None,
    unit_rate: str | int | float | Decimal | None,
) -> str | None:
    """Signed money delta ``(new - old) * unit_rate`` as a Decimal string.

    Returns ``None`` when the impact cannot be computed (either value
    missing, or the rate is unparseable / zero). Quantised to 2dp with
    commercial rounding (ROUND_HALF_UP), expressed in the project base
    currency - a BOQ position's ``unit_rate`` is already stored in base,
    so no currency blending occurs.
    """
    if old_value is None or new_value is None:
        return None
    try:
        rate = Decimal(str(unit_rate).strip()) if unit_rate not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not rate.is_finite() or rate == 0:
        return None
    try:
        delta = Decimal(repr(float(new_value))) - Decimal(repr(float(old_value)))
    except (InvalidOperation, ValueError, TypeError):
        return None
    impact = (delta * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(impact)


def _build_pdf_revision_narrative(
    *,
    measurement_tally: dict[str, Any],
    changed_linked_count: int,
) -> str:
    """Plain-text description of a PDF revision delta for a draft variation.

    Built only from the deterministic summary tally (no AI), so the
    estimator sees what moved before confirming the variation.
    """

    def _n(key: str) -> int:
        try:
            return int(measurement_tally.get(key, 0) or 0)
        except (ValueError, TypeError):
            return 0

    return (
        "Auto-generated from a PDF takeoff revision compare. "
        f"{_n('added')} measurements added, {_n('removed')} removed, "
        f"{_n('modified')} changed; "
        f"{changed_linked_count} priced (linked-to-BOQ) measurement values changed. "
        "Review and confirm before submitting this variation."
    )


class TakeoffService:
    """Business logic for takeoff operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TakeoffRepository(session)
        self.measurement_repo = MeasurementRepository(session)

    async def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        size_bytes: int,
        owner_id: str,
        project_id: str | None = None,
    ) -> TakeoffDocument:
        """Upload and process a PDF document for takeoff.

        Pre-parser gates (Indian-user ticket, v3.0.x):

        1. 0-byte uploads → 400 (don't hand garbage to pdfplumber).
        2. Optional ``OE_TAKEOFF_MAX_UPLOAD_MB`` cap → 413 with the
           env-var name in the message so the user/operator can act.
        3. Password-protected PDFs → 400 with a hint about Acrobat/qpdf.

        Scanned PDFs (no embedded text layer) are persisted with
        ``status="needs_ocr"`` instead of erroring - the user sees the
        upload in the list and the operator gets a one-line log hint
        telling them to install the ``[cv]`` extra to enable OCR.

        If both pdfplumber and pymupdf fail the document is still
        persisted (with 0 pages and empty text); the structured error
        line + input fingerprint goes to the server log.
        """
        # Gate 1: zero-byte upload.
        if not content or size_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Uploaded file is empty. Please re-export the PDF and try again."),
            )

        # Gate 2: optional operator-configured size cap.
        cap = _max_upload_bytes()
        if cap > 0 and len(content) > cap:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"PDF file is too large ({len(content) / 1024 / 1024:.1f} MB). "
                    f"This deployment caps takeoff uploads at "
                    f"{cap // 1024 // 1024} MB; raise the limit by setting "
                    f"OE_TAKEOFF_MAX_UPLOAD_MB on the server."
                ),
            )

        # Gate 3: password-protected PDFs. Catch BEFORE the parser
        # because pdfplumber will spin for a long time on these and
        # then return an opaque error.
        if _is_encrypted_pdf(content):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This PDF is password-protected. Remove the password "
                    "first (Acrobat > File > Properties > Security > "
                    "No Security, or `qpdf --decrypt input.pdf output.pdf`) "
                    "and upload the unprotected file."
                ),
            )

        # Count pages (failure-safe: logs internally and returns 0)
        page_count = _count_pdf_pages(content, filename=filename)

        # Extract text from each page (failure-safe: logs internally)
        page_data = _extract_pdf_pages(content, filename=filename)
        full_text = "\n\n".join(p["text"] for p in page_data if p["text"])

        # Scanned-PDF path: every page returns empty text. We persist
        # the doc with ``needs_ocr`` so the user still sees it in the
        # list and can either install [cv] (PaddleOCR) or share the
        # source CAD with us. The OCR install hint is logged for the
        # operator - not raised - because the upload should still
        # succeed in this case.
        is_scanned = bool(page_data) and not full_text.strip()
        if is_scanned:
            try:
                import paddleocr  # noqa: F401

                paddle_available = True
            except Exception:
                paddle_available = False
            if not paddle_available:
                logger.info(
                    "takeoff.upload_document: scanned PDF with no text layer; "
                    "install [cv] extra (paddleocr) to enable OCR fallback "
                    "(filename=%r, pages=%d)",
                    filename,
                    page_count,
                )

        if page_count == 0 and not page_data:
            # Both parsers failed - neither _count_pdf_pages nor
            # _extract_pdf_pages raised (they log + swallow by design),
            # but the user uploaded something unreadable.  Tell the
            # caller in generic terms; the real diagnostic is already
            # in the server log.
            logger.warning(
                "takeoff.upload_document produced zero pages and empty text for "
                "filename=%r size=%dB - rejecting upload",
                filename,
                size_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to parse PDF document. Please check the file and try again.",
            )

        # Save the PDF file to disk so it can be retrieved later for viewing
        _TAKEOFF_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4()
        file_path = _TAKEOFF_DOCUMENTS_DIR / f"{doc_id}.pdf"
        file_path.write_bytes(content)

        # Scanned PDFs without OCR get a distinct status so the UI
        # can surface a "needs OCR" affordance instead of silently
        # presenting an empty extracted-text panel.
        doc_status = "needs_ocr" if is_scanned else "uploaded"

        doc = TakeoffDocument(
            id=doc_id,
            filename=filename,
            pages=page_count,
            size_bytes=size_bytes,
            content_type="application/pdf",
            status=doc_status,
            owner_id=uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
            extracted_text=full_text,
            page_data=page_data,
            file_path=str(file_path),
        )

        return await self.repo.create(doc)

    async def get_document(self, doc_id: str) -> TakeoffDocument | None:
        return await self.repo.get_by_id(uuid.UUID(doc_id))

    async def list_documents(
        self,
        owner_id: str,
        project_id: str | None = None,
    ) -> list[TakeoffDocument]:
        return await self.repo.list_for_user(
            uuid.UUID(owner_id),
            project_id=uuid.UUID(project_id) if project_id else None,
        )

    async def extract_tables(self, doc_id: str) -> dict:
        """Extract table data from an already-uploaded document."""
        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            return {"elements": [], "summary": {"total_elements": 0, "categories": {}}}

        elements = []
        idx = 0
        for page in doc.page_data or []:
            for table in page.get("tables", []):
                if len(table) < 2:
                    continue
                # D-TKC-014 - map columns by their header semantics
                # instead of fixed indices, so a table ordered
                # ``[Pos | Unit | Qty | Description]`` is read
                # correctly (the v1.9.0 code computed ``headers`` then
                # ignored it and always used col0/col1/col2).
                headers = [str(h).lower().strip() for h in table[0]]
                col_map = _map_table_columns(headers)
                desc_i = col_map["description"]
                qty_i = col_map["quantity"]
                unit_i = col_map["unit"]

                def _cell(row: list, i: int | None) -> str:
                    if i is None or i >= len(row):
                        return ""
                    return str(row[i])

                for row in table[1:]:
                    if not any(str(cell).strip() for cell in row):
                        continue
                    desc = _cell(row, desc_i)
                    qty_str = _cell(row, qty_i)
                    unit = _cell(row, unit_i) or "pcs"

                    # D-TKC-032 - a blank / unparseable quantity must
                    # NOT silently become 1.0 (the v1.9.0 behaviour
                    # fabricated a quantity of 1 that flowed straight
                    # into the BOQ on "select-all → add"). An empty or
                    # non-numeric cell now yields 0.0 and a low
                    # confidence so the estimator must confirm it.
                    qty = _parse_indian_number(qty_str)

                    idx += 1
                    clean_desc = desc.strip()
                    # Canonicalise the unit alias (Nos → pcs, RMt → m,
                    # SqM → m2, MT → t, …) so downstream BOQ logic
                    # sees one unit per concept regardless of how the
                    # source PDF spelled it.
                    clean_unit = _normalize_unit(unit) if unit else "pcs"

                    # Compute confidence based on data quality
                    has_real_qty = qty_str.strip() != "" and qty > 0
                    has_description = bool(clean_desc) and clean_desc.lower() not in (
                        "item",
                        "position",
                        "pos",
                        "n/a",
                        "-",
                        "",
                    )

                    if not has_description:
                        confidence = 0.4
                    elif not has_real_qty:
                        confidence = 0.5
                    elif has_description and has_real_qty and clean_unit:
                        confidence = 0.85
                    else:
                        confidence = 0.6

                    # Audit D4 - formula-injection defence.
                    #
                    # ``clean_desc`` and ``clean_unit`` come from PDF
                    # table extraction (pdfplumber / pymupdf), which
                    # faithfully preserves whatever the source document
                    # contained. An attacker who supplied the PDF can
                    # plant ``=cmd|'/c calc'!A1`` or HYPERLINK-style
                    # payloads in those cells. Without this guard those
                    # strings later flow into BOQ exports (Excel / CSV)
                    # and execute when a downstream user opens the file.
                    #
                    # We neutralise at the extraction boundary - the
                    # earliest point the data enters our system - so
                    # every downstream consumer (BOQ, takeoff, AI
                    # enrichment, AG-Grid editing) sees a safe string.
                    # The leading apostrophe is rendered invisibly by
                    # spreadsheet apps but blocks formula evaluation.
                    from app.core.csv_safety import neutralise_formula  # noqa: PLC0415

                    elements.append(
                        {
                            "id": f"ext_{idx}",
                            "category": "general",
                            "description": neutralise_formula(clean_desc or f"Item {idx}"),
                            "quantity": qty,
                            "unit": neutralise_formula(clean_unit),
                            "confidence": confidence,
                        }
                    )

        # D-TKC-019 - aggregate PER (category, unit). The v1.9.0 code
        # lumped every row into one "general" bucket, took the unit
        # from only the FIRST element, and summed quantities across
        # heterogeneous units (m + m² + pcs) under that single arbitrary
        # unit - a dimensionally meaningless total. We now key the
        # bucket on (category, unit) so each unit is totalled
        # separately and never cross-summed.
        categories: dict = {}
        for el in elements:
            cat = el["category"]
            unit = el["unit"]
            bucket_key = f"{cat}|{unit}"
            if bucket_key not in categories:
                categories[bucket_key] = {
                    "category": cat,
                    "count": 0,
                    "total_quantity": 0,
                    "unit": unit,
                }
            categories[bucket_key]["count"] += 1
            categories[bucket_key]["total_quantity"] += el["quantity"]

        return {
            "elements": elements,
            "summary": {"total_elements": len(elements), "categories": categories},
        }

    async def delete_document(self, doc_id: str) -> None:
        """Delete a takeoff document and its stored PDF file."""
        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is not None and doc.file_path:
            try:
                file_path = Path(doc.file_path)
                if file_path.exists():
                    file_path.unlink()
                    logger.info("Removed takeoff PDF file: %s", file_path)
            except Exception:
                logger.warning("Failed to remove takeoff PDF file: %s", doc.file_path)
        await self.repo.delete(uuid.UUID(doc_id))

    # ── Measurement CRUD ─────────────────────────────────────────────────

    async def create_measurement(
        self,
        data: TakeoffMeasurementCreate,
        *,
        created_by: str = "",
    ) -> TakeoffMeasurement:
        """Create a single takeoff measurement.

        Audit B8 - server-side recompute of ``measurement_value`` from
        the raw geometry. See ``recompute_measurement_value`` for the
        threat model: prevents client-supplied measurement_value from
        diverging from the actual drawn shape.
        """
        recomputed = recompute_measurement_value(
            measurement_type=data.type,
            points=data.points,
            scale_pixels_per_unit=data.scale_pixels_per_unit,
            count_value=data.count_value,
            client_value=data.measurement_value,
        )
        # B8 - derive the volume column server-side (area × depth) so the
        # client-sent value can't bypass the geometry recompute when it is
        # pushed into a BOQ quantity via ``_pick_takeoff_value``.
        recomputed_volume = recompute_volume_value(
            measurement_type=data.type,
            points=data.points,
            scale_pixels_per_unit=data.scale_pixels_per_unit,
            depth=data.depth,
            client_volume=data.volume,
        )
        measurement = TakeoffMeasurement(
            project_id=data.project_id,
            document_id=data.document_id,
            page=data.page,
            type=data.type,
            group_name=data.group_name,
            group_color=data.group_color,
            annotation=data.annotation,
            points=[p.model_dump() for p in data.points],
            measurement_value=recomputed,
            measurement_unit=data.measurement_unit,
            depth=data.depth,
            volume=recomputed_volume,
            perimeter=data.perimeter,
            count_value=data.count_value,
            scale_pixels_per_unit=data.scale_pixels_per_unit,
            linked_boq_position_id=data.linked_boq_position_id,
            metadata_=data.metadata,
            created_by=created_by,
        )
        measurement = await self.measurement_repo.create(measurement)
        logger.info(
            "Measurement created: %s type=%s project=%s value=%s (client=%s)",
            measurement.id,
            data.type,
            data.project_id,
            recomputed,
            data.measurement_value,
        )
        return measurement

    async def get_measurement(self, measurement_id: uuid.UUID) -> TakeoffMeasurement:
        """Get a measurement by ID. Raises 404 if not found."""
        item = await self.measurement_repo.get_by_id(measurement_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Measurement not found",
            )
        return item

    async def list_measurements(
        self,
        project_id: uuid.UUID,
        *,
        document_id: str | None = None,
        page: int | None = None,
        group_name: str | None = None,
        measurement_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[TakeoffMeasurement]:
        """List measurements for a project with filters."""
        return await self.measurement_repo.list_for_project(
            project_id,
            document_id=document_id,
            page=page,
            group_name=group_name,
            measurement_type=measurement_type,
            offset=offset,
            limit=limit,
        )

    async def recognize_candidates(
        self,
        doc_id: str,
        page: int,
        scale_pixels_per_unit: float | None,
    ) -> dict[str, Any]:
        """Detect candidate measurements from a PDF page's vector layer.

        Offline, deterministic complement to ``analyze_document`` (which
        sends text to an LLM): reads the stored PDF off disk, harvests the
        page's vector drawings with PyMuPDF ``page.get_drawings()`` and runs
        the pure :mod:`app.modules.takeoff.recognize` detectors. Nothing is
        persisted - the candidates carry a confidence and a reason and are
        confirmed by the user on the canvas (CLAUDE.md rule 7).

        Returns ``{candidates, page, source, notes}``. Honest failure modes:
        PyMuPDF absent -> a 400 pointing at the optional ``cv`` extra; no
        vector layer (a scanned/raster PDF) -> an empty candidate set with
        ``notes='no_vector_layer'`` rather than fabricated geometry, with a
        pointer to the online ``analyze`` path.
        """
        from app.modules.takeoff import recognize as _recognize

        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Takeoff document not found")
        validate_page_for_document(doc, page)

        file_path = Path(doc.file_path) if doc.file_path else _TAKEOFF_DOCUMENTS_DIR / f"{doc_id}.pdf"
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail="The stored PDF for this document is no longer on disk. Re-upload it to recognize.",
            )

        try:
            import pymupdf  # noqa: PLC0415 - lazy: optional 'cv' extra, absent on default installs
        except ImportError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vector recognition needs PyMuPDF, which is part of the optional 'cv' "
                    "extra. Install it with `pip install openconstructionerp[cv]`, or use the "
                    "online AI analysis instead."
                ),
            ) from exc

        # Render DPI for the raster fallback. The raster detector's morphology
        # kernel is tuned in absolute pixels for ~150 DPI, so keep this in sync
        # with app.modules.takeoff.raster_recognize.
        raster_dpi = 150
        raster_payload: tuple[bytes, int, int, int] | None = None
        page_w_pt = page_h_pt = 0.0
        try:
            content = file_path.read_bytes()
            pdf = pymupdf.open(stream=content, filetype="pdf")
            try:
                pg = pdf[page - 1]
                drawings = pg.get_drawings()
                page_w_pt = float(pg.rect.width)
                page_h_pt = float(pg.rect.height)
                # No vector layer => scanned/raster page. Rasterise it so the
                # OpenCV-based detector can still find rooms and walls.
                if not drawings:
                    try:
                        pix = pg.get_pixmap(dpi=raster_dpi, alpha=False)
                        raster_payload = (pix.samples, pix.h, pix.w, pix.n)
                    except Exception:
                        logger.exception("takeoff.recognize raster render failed for doc %s page %s", doc_id, page)
                        raster_payload = None
            finally:
                pdf.close()
        except HTTPException:
            raise
        except Exception:
            logger.exception("takeoff.recognize failed to read page for doc %s page %s", doc_id, page)
            raise HTTPException(
                status_code=422,
                detail="Could not read this page. The PDF may be corrupt or password-protected.",
            ) from None

        # Vector layer present -> deterministic vector detector.
        if drawings:
            candidates = _recognize.recognize_candidates(drawings, scale_pixels_per_unit)
            return {
                "candidates": candidates,
                "page": page,
                "source": "vector_recognize",
                "notes": None if candidates else "no_features",
            }

        # Scanned / raster page -> OpenCV room + wall detection (cv extra).
        if raster_payload is not None:
            try:
                import numpy as np  # noqa: PLC0415 - lazy: optional 'cv' extra

                from app.modules.takeoff import raster_recognize as _raster  # noqa: PLC0415

                samples, height, width, channels = raster_payload
                arr = np.frombuffer(samples, dtype=np.uint8).reshape(height, width, channels)
                # PyMuPDF pixmaps are RGB(A); OpenCV wants contiguous BGR.
                if channels >= 3:
                    image_bgr = np.ascontiguousarray(arr[:, :, 2::-1])
                else:
                    image_bgr = arr.reshape(height, width)
                candidates = _raster.recognize_raster(image_bgr, page_w_pt, page_h_pt, scale_pixels_per_unit)
                return {
                    "candidates": candidates,
                    "page": page,
                    "source": "raster_recognize",
                    "notes": None if candidates else "raster_no_features",
                }
            except ImportError:
                # OpenCV / numpy (the 'cv' extra) is not installed - degrade
                # honestly instead of pretending nothing was found.
                return {
                    "candidates": [],
                    "page": page,
                    "source": "raster_recognize",
                    "notes": "raster_no_cv",
                }
            except Exception:
                logger.exception("takeoff.recognize raster detection failed for doc %s page %s", doc_id, page)

        return {
            "candidates": [],
            "page": page,
            "source": "vector_recognize",
            "notes": "no_vector_layer",
        }

    async def update_measurement(
        self,
        measurement_id: uuid.UUID,
        data: TakeoffMeasurementUpdate,
        *,
        existing: TakeoffMeasurement | None = None,
    ) -> TakeoffMeasurement:
        """Update measurement fields.

        Audit B8 - recompute ``measurement_value`` whenever any input
        that feeds into the calculation changes (points, scale, type,
        count_value). We merge "current row state" with "patch fields"
        before calling the recompute so partial updates work correctly
        (e.g. caller bumps just ``scale_pixels_per_unit`` without
        re-sending the whole points array).

        Round-6 audit (2026-05-22) - the router has already loaded the
        row for the IDOR check via ``verify_project_access``. Re-fetching
        here doubles the query count on every PATCH and shows up as a
        sustained 2× SELECT load when a user is bulk-editing measurements
        on a large takeoff. Accept the pre-fetched row via ``existing``
        and skip the redundant lookup. The legacy id-only path stays
        available for any caller (CLI scripts, tests) that doesn't have
        the row handy.
        """
        if existing is None:
            item = await self.get_measurement(measurement_id)
        else:
            item = existing

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "points" in fields and fields["points"] is not None:
            fields["points"] = [p.model_dump() for p in data.points]  # type: ignore[union-attr]

        # Recompute measurement_value if any geometry-relevant field
        # is touched. We need the *effective post-update* state, so
        # we merge patch over current.
        recompute_triggers = {"points", "scale_pixels_per_unit", "type", "count_value", "measurement_value"}
        if recompute_triggers & fields.keys():
            effective_type = fields.get("type") if "type" in fields else item.type
            effective_points = fields.get("points") if "points" in fields else (item.points or [])
            effective_scale = (
                fields.get("scale_pixels_per_unit") if "scale_pixels_per_unit" in fields else item.scale_pixels_per_unit
            )
            effective_count = fields.get("count_value") if "count_value" in fields else item.count_value
            client_value = fields.get("measurement_value", item.measurement_value)
            recomputed = recompute_measurement_value(
                measurement_type=effective_type,
                points=effective_points,
                scale_pixels_per_unit=effective_scale,
                count_value=effective_count,
                client_value=client_value,
            )
            fields["measurement_value"] = recomputed

        # Recompute the ``perimeter`` column server-side on any geometry
        # change (issue #194 - in-canvas reshape). A reshape that changes
        # the vertices must not leave a stale perimeter on the row, and the
        # client perimeter cannot be trusted any more than the area can be.
        # Polyline length / closed-polygon perimeter are both reconstructed
        # from points x scale, mirroring the create-time derivation.
        perimeter_triggers = {"points", "scale_pixels_per_unit", "type"}
        if perimeter_triggers & fields.keys():
            effective_type = (fields.get("type") if "type" in fields else item.type) or ""
            effective_points = fields.get("points") if "points" in fields else (item.points or [])
            effective_scale = (
                fields.get("scale_pixels_per_unit") if "scale_pixels_per_unit" in fields else item.scale_pixels_per_unit
            )
            mtype = effective_type.strip().lower()
            xy = _points_to_xy(effective_points or [])
            scale_ppu = effective_scale or 0.0
            if scale_ppu > 0 and len(xy) >= 2:
                if mtype in {"area", "volume", "cloud"}:
                    # Closed boundary: include the wrap edge back to the start.
                    fields["perimeter"] = _polyline_length([*xy, xy[0]]) / scale_ppu
                elif mtype in {"distance", "polyline"}:
                    fields["perimeter"] = _polyline_length(xy) / scale_ppu

        # B8 - recompute the volume column (area × depth) server-side
        # whenever any input that feeds it is touched, so a PATCH cannot be
        # used to slip an arbitrary client volume into a BOQ quantity. This
        # runs independently of the measurement_value block above because a
        # ``depth``/``volume`` patch alone must still re-derive the volume.
        volume_triggers = {"points", "scale_pixels_per_unit", "type", "depth", "volume"}
        if volume_triggers & fields.keys():
            effective_type = fields.get("type") if "type" in fields else item.type
            effective_points = fields.get("points") if "points" in fields else (item.points or [])
            effective_scale = (
                fields.get("scale_pixels_per_unit") if "scale_pixels_per_unit" in fields else item.scale_pixels_per_unit
            )
            # A client sending ``depth: null`` would otherwise null the
            # effective depth, force ``recompute_volume_value`` into its
            # client-trust fallback, and slip an arbitrary ``volume`` into a
            # BOQ quantity. Treat a ``None`` depth as "not provided" and fall
            # back to the stored value so server volume validation still runs.
            effective_depth = fields.get("depth") if fields.get("depth") is not None else item.depth
            client_volume = fields.get("volume", item.volume)
            fields["volume"] = recompute_volume_value(
                measurement_type=effective_type,
                points=effective_points,
                scale_pixels_per_unit=effective_scale,
                depth=effective_depth,
                client_volume=client_volume,
            )

        if not fields:
            return item

        await self.measurement_repo.update_fields(measurement_id, **fields)
        await self.session.refresh(item)

        logger.info("Measurement updated: %s (fields=%s)", measurement_id, list(fields.keys()))
        return item

    async def delete_measurement(
        self,
        measurement_id: uuid.UUID,
        *,
        existing: TakeoffMeasurement | None = None,
    ) -> None:
        """Delete a measurement.

        Round-6 audit (2026-05-22) - accept a pre-fetched row from the
        router's IDOR check to avoid the duplicate ``get_by_id`` query.
        """
        if existing is None:
            await self.get_measurement(measurement_id)  # Raises 404 if not found
        await self.measurement_repo.delete(measurement_id)
        logger.info("Measurement deleted: %s", measurement_id)

    async def bulk_create_measurements(
        self,
        items: list[TakeoffMeasurementCreate],
        *,
        created_by: str = "",
    ) -> list[TakeoffMeasurement]:
        """Bulk create measurements (e.g. importing from localStorage).

        Audit B8 - recompute ``measurement_value`` for every row so
        the localStorage→server import path can't be used to bypass
        the per-row create guard.
        """
        measurements = [
            TakeoffMeasurement(
                project_id=data.project_id,
                document_id=data.document_id,
                page=data.page,
                type=data.type,
                group_name=data.group_name,
                group_color=data.group_color,
                annotation=data.annotation,
                points=[p.model_dump() for p in data.points],
                measurement_value=recompute_measurement_value(
                    measurement_type=data.type,
                    points=data.points,
                    scale_pixels_per_unit=data.scale_pixels_per_unit,
                    count_value=data.count_value,
                    client_value=data.measurement_value,
                ),
                measurement_unit=data.measurement_unit,
                depth=data.depth,
                # B8 - recompute the volume column server-side so the
                # localStorage→server import can't bypass the geometry check.
                volume=recompute_volume_value(
                    measurement_type=data.type,
                    points=data.points,
                    scale_pixels_per_unit=data.scale_pixels_per_unit,
                    depth=data.depth,
                    client_volume=data.volume,
                ),
                perimeter=data.perimeter,
                count_value=data.count_value,
                scale_pixels_per_unit=data.scale_pixels_per_unit,
                linked_boq_position_id=data.linked_boq_position_id,
                metadata_=data.metadata,
                created_by=created_by,
            )
            for data in items
        ]
        result = await self.measurement_repo.create_bulk(measurements)
        logger.info("Bulk created %d measurements (server-side recomputed)", len(result))
        return result

    async def get_measurement_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's measurements."""
        items = await self.measurement_repo.all_for_project(project_id)

        by_type: dict[str, int] = {}
        by_group: dict[str, int] = {}
        by_page: dict[int, int] = {}

        for item in items:
            by_type[item.type] = by_type.get(item.type, 0) + 1
            by_group[item.group_name] = by_group.get(item.group_name, 0) + 1
            by_page[item.page] = by_page.get(item.page, 0) + 1

        return {
            "total_measurements": len(items),
            "by_type": by_type,
            "by_group": by_group,
            "by_page": by_page,
        }

    async def export_measurements(
        self,
        project_id: uuid.UUID,
        *,
        fmt: str = "csv",
    ) -> list[dict[str, Any]]:
        """Export measurements for a project as a list of dicts.

        The caller (router) is responsible for converting to the requested
        format (CSV, JSON, etc.).
        """
        items = await self.measurement_repo.all_for_project(project_id)
        rows: list[dict[str, Any]] = []
        for m in items:
            rows.append(
                {
                    "id": str(m.id),
                    "project_id": str(m.project_id),
                    "document_id": m.document_id or "",
                    "page": m.page,
                    "type": m.type,
                    "group_name": m.group_name,
                    "group_color": m.group_color,
                    "annotation": m.annotation or "",
                    "measurement_value": m.measurement_value,
                    "measurement_unit": m.measurement_unit,
                    "depth": m.depth,
                    "volume": m.volume,
                    "perimeter": m.perimeter,
                    "count_value": m.count_value,
                    "scale_pixels_per_unit": m.scale_pixels_per_unit,
                    "linked_boq_position_id": m.linked_boq_position_id or "",
                    "created_by": m.created_by,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
            )
        return rows

    async def link_measurement_to_boq(
        self,
        measurement_id: uuid.UUID,
        boq_position_id: str,
        *,
        existing: TakeoffMeasurement | None = None,
        push_quantity: bool = False,
    ) -> TakeoffMeasurement:
        """Link a measurement to a BOQ position.

        Round-6 audit (2026-05-22) - accept a pre-fetched row from the
        router's IDOR check to avoid the duplicate ``get_by_id`` query.

        Estimation-cluster wave (2026-05-28) - opt-in ``push_quantity``.
        When true, the measurement's measured value (per
        :func:`_pick_takeoff_value`) is copied into the target BOQ
        position's ``quantity`` and the position total is recomputed.
        A measurement with no usable value leaves the quantity untouched.
        """
        item = existing if existing is not None else await self.get_measurement(measurement_id)
        # IDOR guard: the target BOQ position must live in the SAME project as
        # the measurement. The router only verified access to the measurement's
        # project, so without this a caller could link to - and, with
        # push_quantity, overwrite the quantity of - a position in a project
        # they cannot access.
        await self._assert_position_in_project(boq_position_id, item.project_id)
        await self.measurement_repo.update_fields(measurement_id, linked_boq_position_id=boq_position_id)
        await self.session.refresh(item)
        logger.info(
            "Measurement %s linked to BOQ position %s",
            measurement_id,
            boq_position_id,
        )
        if push_quantity:
            await self._push_quantity_to_position(boq_position_id, item)
        return item

    async def _assert_position_in_project(self, boq_position_id: str, project_id: Any) -> None:
        """Raise 404 unless the BOQ position belongs to ``project_id``.

        IDOR defence for the takeoff→BOQ link: prevents linking/pushing a
        measurement onto a BOQ position in a project the caller cannot access.
        """
        from app.modules.boq.service import BOQService  # noqa: PLC0415 - avoid import cycle

        try:
            position_uuid = uuid.UUID(str(boq_position_id))
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="boq_position_id is not a valid UUID",
            ) from exc
        boq_service = BOQService(self.session)
        position = await boq_service.position_repo.get_by_id(position_uuid)
        if position is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ position not found")
        boq = await boq_service.get_boq(position.boq_id)
        if str(boq.project_id) != str(project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ position not found in this project",
            )

    async def _push_quantity_to_position(self, boq_position_id: str, measurement: Any) -> None:
        """Copy a measurement's value into a BOQ position's quantity.

        Reuses the BOQ module's established total-recompute path so the
        money math stays in one place. A ``None`` picked value (empty or
        garbage measurement) is a no-op - we never zero an existing BOQ
        quantity from a measurement that carries no usable number.
        """
        value = _pick_takeoff_value(measurement)
        if value is None:
            logger.info(
                "push_quantity: measurement %s has no usable value - leaving BOQ position %s untouched",
                getattr(measurement, "id", "?"),
                boq_position_id,
            )
            return

        from app.modules.boq.service import BOQService  # noqa: PLC0415 - avoid import cycle

        try:
            position_uuid = uuid.UUID(str(boq_position_id))
        except (ValueError, AttributeError):
            logger.warning("push_quantity: BOQ position id %r is not a UUID - skipping", boq_position_id)
            return

        boq_service = BOQService(self.session)
        position = await boq_service.position_repo.get_by_id(position_uuid)
        if position is None:
            logger.warning("push_quantity: BOQ position %s not found - skipping", boq_position_id)
            return

        # Dimensional compatibility guard. Copying the scalar straight into the
        # quantity and recomputing the total only makes sense when the
        # measurement and the position measure the same thing. An m2 takeoff
        # pushed onto a per-m3 position would otherwise silently yield a wrong
        # total, so refuse the push on a real dimension mismatch and leave the
        # existing BOQ quantity untouched. Unknown units on either side stay
        # permissive (no dimension to compare) so custom/legacy units are not
        # blocked.
        measurement_dim = _measurement_dimension(measurement)
        position_dim = _unit_dimension(getattr(position, "unit", None))
        if measurement_dim is not None and position_dim is not None and measurement_dim != position_dim:
            logger.warning(
                "push_quantity: measurement %s dimension %s is incompatible with BOQ position %s "
                "unit %r (%s) - refusing to overwrite the quantity",
                getattr(measurement, "id", "?"),
                measurement_dim,
                boq_position_id,
                getattr(position, "unit", None),
                position_dim,
            )
            return

        await boq_service.position_repo.update_fields(position.id, quantity=str(value))
        await self.session.refresh(position)
        await boq_service._recompute_position_total(position)  # noqa: SLF001 - reuse the canonical recompute path
        logger.info("push_quantity: BOQ position %s quantity set to %s", boq_position_id, value)

    # ── Revision compare (Item 17) ───────────────────────────────────────

    async def compare_documents(
        self,
        project_id: uuid.UUID,
        from_document_id: str,
        to_document_id: str,
    ) -> dict[str, Any]:
        """Compare the measurements of two takeoff documents in one project.

        PDF takeoffs have no version table, so a revision compare is run
        between two uploaded documents (the user uploads revision A and
        revision B as separate PDFs). Measurements are matched by
        :func:`_measurement_compare_key` and classified
        added / removed / modified / unchanged. A linked-to-BOQ
        measurement whose value changed carries a money cost impact in
        the project's base currency.

        Both document ids must reference documents the project owns; an
        empty result set is returned rather than an error when a document
        has no measurements (a freshly uploaded, not-yet-measured PDF).
        """
        from_measurements = await self.measurement_repo.list_for_project(
            project_id,
            document_id=from_document_id,
            limit=500,
        )
        to_measurements = await self.measurement_repo.list_for_project(
            project_id,
            document_id=to_document_id,
            limit=500,
        )

        from_by_key = {_measurement_compare_key(m): m for m in from_measurements}
        to_by_key = {_measurement_compare_key(m): m for m in to_measurements}

        rate_cache: dict[str, tuple[str | None, str | None]] = {}

        async def _rate_and_currency(position_id: str | None) -> tuple[str | None, str | None]:
            if not position_id:
                return None, None
            if position_id in rate_cache:
                return rate_cache[position_id]
            result = await self._resolve_position_rate(position_id, project_id)
            rate_cache[position_id] = result
            return result

        rows: list[dict[str, Any]] = []
        for key in sorted(set(from_by_key) | set(to_by_key)):
            old_m = from_by_key.get(key)
            new_m = to_by_key.get(key)

            if old_m is not None and new_m is None:
                rows.append(
                    {
                        "change_type": "removed",
                        "measurement_id": str(old_m.id),
                        "type": old_m.type,
                        "group_name": old_m.group_name,
                        "page": old_m.page,
                        "label": old_m.annotation,
                        "old_value": _measure_to_float(_pick_takeoff_value(old_m)),
                        "new_value": None,
                        "measurement_unit": old_m.measurement_unit,
                        "linked_boq_position_id": old_m.linked_boq_position_id,
                        "cost_impact": None,
                        "cost_currency": None,
                    }
                )
                continue

            if old_m is None and new_m is not None:
                rows.append(
                    {
                        "change_type": "added",
                        "measurement_id": str(new_m.id),
                        "type": new_m.type,
                        "group_name": new_m.group_name,
                        "page": new_m.page,
                        "label": new_m.annotation,
                        "old_value": None,
                        "new_value": _measure_to_float(_pick_takeoff_value(new_m)),
                        "measurement_unit": new_m.measurement_unit,
                        "linked_boq_position_id": new_m.linked_boq_position_id,
                        "cost_impact": None,
                        "cost_currency": None,
                    }
                )
                continue

            assert old_m is not None and new_m is not None  # noqa: S101
            old_val = _measure_to_float(_pick_takeoff_value(old_m))
            new_val = _measure_to_float(_pick_takeoff_value(new_m))
            changed = old_val != new_val
            position_id = new_m.linked_boq_position_id or old_m.linked_boq_position_id
            cost_impact: str | None = None
            cost_currency: str | None = None
            if changed and position_id:
                rate, cost_currency = await _rate_and_currency(position_id)
                cost_impact = _compute_cost_impact(
                    old_value=old_val,
                    new_value=new_val,
                    unit_rate=rate,
                )
            rows.append(
                {
                    "change_type": "modified" if changed else "unchanged",
                    "measurement_id": str(new_m.id),
                    "type": new_m.type,
                    "group_name": new_m.group_name,
                    "page": new_m.page,
                    "label": new_m.annotation,
                    "old_value": old_val,
                    "new_value": new_val,
                    "measurement_unit": new_m.measurement_unit or old_m.measurement_unit,
                    "linked_boq_position_id": position_id,
                    "cost_impact": cost_impact,
                    "cost_currency": cost_currency if cost_impact is not None else None,
                }
            )

        def _tally(diff_rows: list[dict[str, Any]]) -> dict[str, int]:
            tally = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}
            for row in diff_rows:
                tally[row["change_type"]] = tally.get(row["change_type"], 0) + 1
            return tally

        net_impact = Decimal("0")
        cost_currency_out: str | None = None
        has_cost = False
        for row in rows:
            if row.get("cost_impact") is not None:
                has_cost = True
                cost_currency_out = row.get("cost_currency") or cost_currency_out
                try:
                    net_impact += Decimal(str(row["cost_impact"]))
                except (InvalidOperation, ValueError, TypeError):
                    continue

        summary = {
            "measurements": _tally(rows),
            "net_cost_impact": str(net_impact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if has_cost else None,
            "cost_currency": cost_currency_out,
            "from_measurement_count": len(from_measurements),
            "to_measurement_count": len(to_measurements),
        }

        return {
            "project_id": project_id,
            "from_document_id": from_document_id,
            "to_document_id": to_document_id,
            "measurement_rows": rows,
            "summary": summary,
        }

    async def _resolve_position_rate(
        self,
        position_id: str,
        project_id: uuid.UUID,
    ) -> tuple[str | None, str | None]:
        """Resolve ``(unit_rate, base_currency)`` for a BOQ position.

        The position must belong to ``project_id`` (a foreign-project
        position is treated as "no rate" so a compare never prices a
        measurement against another tenant's estimate). Best-effort: any
        lookup failure returns ``(None, None)`` so the compare degrades to
        "no cost shown" rather than a 500.
        """
        try:
            position_uuid = uuid.UUID(str(position_id))
        except (ValueError, TypeError, AttributeError):
            return None, None

        try:
            from app.modules.boq.service import BOQService  # noqa: PLC0415 - avoid import cycle

            boq_service = BOQService(self.session)
            position = await boq_service.position_repo.get_by_id(position_uuid)
            if position is None:
                return None, None
            boq = await boq_service.get_boq(position.boq_id)
            if str(boq.project_id) != str(project_id):
                return None, None
            base_currency = await boq_service._resolve_project_currency(position.boq_id)  # noqa: SLF001
            return str(position.unit_rate), (base_currency or None)
        except HTTPException:
            return None, None
        except Exception:  # noqa: BLE001 - pricing is advisory, never break the compare
            logger.debug("Cost-impact rate lookup failed for position %s", position_id, exc_info=True)
            return None, None

    async def create_variation_from_documents(
        self,
        project_id: uuid.UUID,
        from_document_id: str,
        to_document_id: str,
        *,
        title: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Turn a PDF revision delta into a draft VariationRequest.

        Mirrors the DWG handoff: the deterministic
        :meth:`compare_documents` is the single source of truth (no
        recompute of the diff math), and the result is shaped into a
        *draft* VariationRequest (never submitted/approved - a human
        confirms it in the variations module). Provenance is stamped into
        ``metadata.source = "pdf_revision_compare"``.

        Returns ``{variation_request_id, code, estimated_cost_impact,
        currency}``.
        """
        diff = await self.compare_documents(project_id, from_document_id, to_document_id)
        summary = diff.get("summary") or {}
        measurement_tally = summary.get("measurements") or {}
        net_impact_raw = summary.get("net_cost_impact")
        currency = summary.get("cost_currency") or ""

        rows = diff.get("measurement_rows", [])
        changed_measurement_ids = [row["measurement_id"] for row in rows if row.get("change_type") == "modified"]
        changed_linked_count = len(
            [row for row in rows if row.get("change_type") == "modified" and row.get("linked_boq_position_id")]
        )

        try:
            estimated_cost_impact = Decimal(str(net_impact_raw)) if net_impact_raw not in (None, "") else Decimal("0")
        except (InvalidOperation, ValueError, TypeError):
            estimated_cost_impact = Decimal("0")

        resolved_title = title or "Drawing revision (PDF takeoff)"
        description = _build_pdf_revision_narrative(
            measurement_tally=measurement_tally,
            changed_linked_count=changed_linked_count,
        )

        # Lazy import (mirrors the BOQService import) so the takeoff module
        # load never depends on the variations module at import time.
        from app.modules.variations.schemas import VariationRequestCreate
        from app.modules.variations.service import VariationsService

        vr_create = VariationRequestCreate(
            project_id=project_id,
            title=resolved_title[:500],
            description=description[:20000],
            classification="scope_change",
            estimated_cost_impact=estimated_cost_impact,
            estimated_schedule_days=0,
            currency=currency[:10],
            status="draft",
            metadata={
                "source": "pdf_revision_compare",
                "from_document_id": str(from_document_id),
                "to_document_id": str(to_document_id),
                "changed_measurement_ids": changed_measurement_ids,
                "net_cost_impact": str(estimated_cost_impact),
            },
        )
        variations_service = VariationsService(self.session)
        vr = await variations_service.create_request(vr_create, user_id=user_id)

        return {
            "variation_request_id": vr.id,
            "code": vr.code,
            "estimated_cost_impact": str(estimated_cost_impact),
            "currency": currency,
        }

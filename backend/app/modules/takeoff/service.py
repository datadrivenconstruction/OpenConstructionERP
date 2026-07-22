# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff business logic."""

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.takeoff.models import AiTakeoffRun, TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.repository import (
    AiTakeoffRunRepository,
    MeasurementRepository,
    TakeoffRepository,
)
from app.modules.takeoff.schemas import (
    PointSchema,
    TakeoffMeasurementCreate,
    TakeoffMeasurementUpdate,
)

logger = logging.getLogger(__name__)


# ── Vision-LLM plan-read cost cap (issue #194) ──────────────────────────────


def _takeoff_ai_max_cost_usd() -> float:
    """Read the per-user rolling plan-read cost cap from env (default 2.00 USD).

    Mirrors the proven ``EVAL_AI_MAX_COST_USD`` cap reader: an invalid value
    logs a warning and falls back to the default rather than crashing the run.
    """
    raw = os.environ.get("TAKEOFF_AI_MAX_COST_USD", "2.00")
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid TAKEOFF_AI_MAX_COST_USD=%r - defaulting to 2.00", raw)
        return 2.00


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


_DEFAULT_MAX_UPLOAD_MB = 200


def _max_upload_bytes() -> int:
    """Effective per-upload byte cap in bytes.

    Defaults to 200 MB. ``OE_TAKEOFF_MAX_UPLOAD_MB`` overrides it with a
    positive integer number of megabytes; an unset, empty, zero, negative or
    unparseable value means "use the 200 MB default" (it does NOT mean
    unlimited).

    There is deliberately no "unlimited" setting anymore. The takeoff upload
    parses arbitrary user PDFs, and an unbounded upload can drive the parser
    past host RAM and OOM-kill the container (the incident this cap closes).
    Operators who genuinely need larger uploads raise the number explicitly.
    """
    raw = os.environ.get("OE_TAKEOFF_MAX_UPLOAD_MB", "").strip()
    if not raw:
        return _DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    try:
        mb = int(raw)
    except (ValueError, TypeError):
        return _DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    if mb <= 0:
        return _DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
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

    A deduction (opening / void) carries a positive gross area but only
    has meaning as a subtraction inside its group's net-area rollup. It is
    never a standalone BOQ quantity, so we refuse to push it - otherwise a
    void could silently overwrite a position with the area of the hole.
    """
    if bool(getattr(measurement, "is_deduction", False)):
        return None

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


# Sub-directory (under the unified data root) where uploaded PDF files live.
_TAKEOFF_DOCUMENTS_SUBDIR = "takeoff_documents"


def _takeoff_documents_dir() -> Path:
    """Return the active directory where takeoff PDFs are WRITTEN.

    Anchored under :func:`app.core.storage.resolve_data_dir` so it honours
    ``OE_DATA_DIR`` / ``DATA_DIR`` / ``OE_CLI_DATA_DIR`` (and the persistent
    per-user home for wheel installs) exactly like the storage backend and the
    BIM hub. The old code hard-coded ``~/.openestimator/takeoff_documents`` -
    the WRONG brand namespace, ignoring every env override - so on a container
    or external-Postgres redeploy the PDF bytes were lost while the document
    row stayed present (download 404 "PDF file not found on disk").

    Resolved lazily, PER CALL (not at import time), so a test monkeypatch or an
    operator setting ``OE_DATA_DIR`` after import takes effect, and so this
    module is not import-coupled to ``app.config``/Postgres.
    """
    from app.core.storage import resolve_data_dir

    return resolve_data_dir() / _TAKEOFF_DOCUMENTS_SUBDIR


def _find_existing_takeoff_pdf(doc_id: str) -> Path | None:
    """Resolve ``{doc_id}.pdf`` to an existing file, READ-ONLY back-compat.

    The active data root is tried first; if the PDF is not there we probe every
    other platform-owned data root (:func:`app.core.storage.safe_data_roots`)
    AND the legacy ``~/.openestimator`` brand-namespace path that pre-8.6.1
    builds physically wrote to. This is what lets a PDF written under a DIFFERENT
    data-dir resolution still be served instead of 404'ing.

    Reads fall back; WRITES never do (uploads always go to
    :func:`_takeoff_documents_dir`). The filename is a server-generated UUID, so
    there is no path-traversal surface here, but containment against the
    platform-owned roots is still verified by the router via
    :func:`app.core.storage.is_within_safe_root`. Returns ``None`` when the PDF
    exists nowhere.
    """
    from app.core.storage import safe_data_roots

    name = f"{doc_id}.pdf"
    candidates: list[Path] = [_takeoff_documents_dir() / name]
    for root in safe_data_roots():
        candidates.append(root / _TAKEOFF_DOCUMENTS_SUBDIR / name)
    # Legacy brand-namespace path some pre-8.6.1 installs wrote to directly.
    candidates.append(Path.home() / ".openestimator" / _TAKEOFF_DOCUMENTS_SUBDIR / name)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def _describe_pdf_input(content: bytes, *, filename: str | None = None) -> str:
    """Build a short server-side diagnostic string for a PDF blob.

    Includes size, the ``%PDF-`` magic header presence, and a filename
    extension guess.  Kept free of any filesystem paths so the return
    value is safe to log (but we never surface it to API callers).
    """
    size = len(content) if content is not None else 0
    has_magic = bool(content and content[:5] == b"%PDF-")
    ext = Path(filename).suffix.lower() if filename else ""
    name_hint = filename or "<anonymous>"
    return f"filename={name_hint!r} size={size}B ext={ext!r} has_pdf_magic={has_magic}"


@contextlib.contextmanager
def _spool_bytes_to_temp(content: bytes, *, suffix: str = ".pdf") -> Iterator[Path]:
    """Write ``content`` to a temporary file and yield its path.

    The shared PDF parser (:mod:`app.modules.takeoff.pdf_extract_worker`)
    operates on a filesystem path so the exact same code runs both in-process
    (the delegators below) and out-of-process (the isolated upload path).
    This helper bridges the byte-oriented in-process callers to that
    path-oriented parser. The temp file is always removed on exit.
    """
    fd, name = tempfile.mkstemp(prefix="oce-pdfparse-", suffix=suffix)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content or b"")
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _extract_pdf_pages(content: bytes, *, filename: str | None = None) -> list[dict]:
    """Extract text and tables from each page of a PDF (in-process).

    Thin delegator to
    :func:`app.modules.takeoff.pdf_extract_worker.extract_pdf_data` so there
    is a single parser implementation shared with the isolated upload path
    (the worker carries the vector-density guard that stops a dense CAD sheet
    from OOM-ing during ``extract_tables``). Kept for direct callers and
    tests; returns an empty list on total failure, matching the historical
    failure-safe contract.

    Returns a list of dicts: ``[{page, text, tables, has_text}, ...]``.
    """
    from app.modules.takeoff import pdf_extract_worker

    try:
        with _spool_bytes_to_temp(content) as tmp:
            result = pdf_extract_worker.extract_pdf_data(str(tmp), None, filename=filename)
    except Exception:
        logger.exception(
            "takeoff.pdf_extract delegation failed (%s) - returning no pages",
            _describe_pdf_input(content, filename=filename),
        )
        return []
    pages = result.get("pages")
    return pages if isinstance(pages, list) else []


def no_text_layer_info(doc: Any) -> tuple[int, list[int]]:
    """Read the per-page text-layer audit for a takeoff document.

    Returns ``(count, page_numbers)`` where ``page_numbers`` is the list of
    1-based pages that came back with no text layer (likely scanned drawings
    that need OCR). Both default to ``0`` / ``[]`` so a document uploaded
    before this audit existed - or one stored without the metadata - reads as
    "no missing text layer" instead of erroring. The count is recomputed from
    ``page_data`` (the source of truth) when present so a re-extracted document
    stays accurate even if the stored count drifts.
    """
    page_data = getattr(doc, "page_data", None) or []
    if page_data:
        missing = [
            int(p.get("page", idx + 1))
            for idx, p in enumerate(page_data)
            if isinstance(p, dict)
            and not (p.get("has_text") if "has_text" in p else bool(str(p.get("text", "")).strip()))
        ]
        if missing:
            return len(missing), missing
    # Fall back to the stored metadata snapshot (e.g. page_data trimmed off a
    # list response, or all pages had text so the loop above found nothing).
    meta = getattr(doc, "metadata_", None) or {}
    if isinstance(meta, dict):
        stored_list = meta.get("pages_without_text_list")
        if isinstance(stored_list, list) and stored_list:
            nums = [int(n) for n in stored_list if isinstance(n, int | float)]
            return len(nums), nums
        stored_count = meta.get("pages_without_text")
        if isinstance(stored_count, int | float) and stored_count > 0:
            return int(stored_count), []
    return 0, []


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
    """Count the number of pages in a PDF (in-process).

    Thin delegator to
    :func:`app.modules.takeoff.pdf_extract_worker.count_pdf_pages`, sharing the
    single parser implementation. Returns 0 on double-failure, matching the
    historical failure-safe contract.
    """
    from app.modules.takeoff import pdf_extract_worker

    try:
        with _spool_bytes_to_temp(content) as tmp:
            return pdf_extract_worker.count_pdf_pages(str(tmp), filename=filename)
    except Exception:
        logger.exception(
            "takeoff.pdf_count delegation failed (%s) - reporting zero pages",
            _describe_pdf_input(content, filename=filename),
        )
        return 0


# ── Isolated PDF parsing (P0: never OOM-kill the API process) ────────────────

_PARSE_MAX_PAGES = 300
_PARSE_TIMEOUT_S = 120


def _parse_max_pages() -> int:
    """Max pages the isolated parser extracts. Env ``OE_TAKEOFF_MAX_PAGES``.

    Defaults to 300, clamped to ``[1, 5000]``. The cap bounds the work (and
    the JSON payload) for a pathological 10k-page upload; the true page count
    is still reported so the UI shows the real total.
    """
    raw = os.environ.get("OE_TAKEOFF_MAX_PAGES", "").strip()
    if not raw:
        return _PARSE_MAX_PAGES
    try:
        n = int(raw)
    except (ValueError, TypeError):
        return _PARSE_MAX_PAGES
    return max(1, min(5000, n))


def _parse_timeout_s() -> float:
    """Wall-clock timeout for the isolated parser. Env ``OE_TAKEOFF_PARSE_TIMEOUT_S``.

    Defaults to 120 s, clamped to ``[10, 1800]``. A parse that blows past this
    (a hostile PDF built to spin) is killed and the upload degrades gracefully
    instead of tying up a worker forever.
    """
    raw = os.environ.get("OE_TAKEOFF_PARSE_TIMEOUT_S", "").strip()
    if not raw:
        return float(_PARSE_TIMEOUT_S)
    try:
        secs = float(raw)
    except (ValueError, TypeError):
        return float(_PARSE_TIMEOUT_S)
    return max(10.0, min(1800.0, secs))


def _backend_root() -> Path:
    """Absolute path to the ``backend`` root (the directory that holds ``app``).

    ``service.py`` lives at ``backend/app/modules/takeoff/service.py`` so the
    backend root is four parents up. Used to launch the worker with ``-m`` in
    both the source tree and a wheel install.
    """
    return Path(__file__).resolve().parents[3]


def _pdf_worker_command(pdf_path: Path, max_pages: int) -> list[str]:
    """Build the ``python -m ...`` argv for the isolated parser."""
    return [
        sys.executable,
        "-m",
        "app.modules.takeoff.pdf_extract_worker",
        str(pdf_path),
        str(max_pages),
    ]


def _pdf_worker_env() -> dict[str, str]:
    """Environment for the worker subprocess with the backend root on PYTHONPATH."""
    env = dict(os.environ)
    root = str(_backend_root())
    prev = env.get("PYTHONPATH", "")
    if prev:
        env["PYTHONPATH"] = root + os.pathsep + prev
    else:
        env["PYTHONPATH"] = root
    return env


def _run_pdf_worker(
    pdf_path: Path,
    *,
    max_pages: int,
    timeout_s: float,
) -> subprocess.CompletedProcess:
    """Run the isolated parser synchronously (call off the event loop)."""
    return subprocess.run(
        _pdf_worker_command(pdf_path, max_pages),
        capture_output=True,
        timeout=timeout_s,
        cwd=str(_backend_root()),
        env=_pdf_worker_env(),
        check=False,
    )


def _use_in_process_pdf_parser() -> bool:
    """Whether to parse PDFs in-process instead of via a child interpreter.

    The isolated parser is launched with ``sys.executable -m
    app.modules.takeoff.pdf_extract_worker``. That only works when
    ``sys.executable`` is a real Python interpreter that honours ``-m``. In the
    PyInstaller one-file desktop build the backend runs as a frozen binary
    sidecar, so ``sys.executable`` is that binary (``sys.frozen`` is set) and
    ``-m`` is not honoured - the tokens reach the app's own CLI, it exits
    non-zero, and every upload would degrade to zero pages. There we parse
    in-process, exactly as the pre-subprocess desktop build did. The memory
    isolation this trades away only ever protected the single-PID server
    container, not a single-user desktop machine.
    """
    if getattr(sys, "frozen", False):
        return True
    return os.environ.get("OE_DESKTOP", "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_pdf_in_process(
    pdf_path: Path,
    *,
    filename: str | None,
    max_pages: int,
) -> tuple[int, list[dict], bool] | None:
    """Parse a PDF in the current process (frozen / desktop fallback).

    Mirrors the result contract of :func:`_parse_pdf_isolated`: returns
    ``(page_count, page_data, truncated)`` for any completed parse - including
    the unreadable-document ``(0, [], False)`` case - and ``None`` only when the
    parser raised outright. Runs the same
    :func:`app.modules.takeoff.pdf_extract_worker.extract_pdf_data` path, and
    therefore the same vector-density guard, as the child process, without the
    POSIX address-space cap that is meaningless on a single-user desktop.
    """
    from app.modules.takeoff import pdf_extract_worker

    try:
        result = pdf_extract_worker.extract_pdf_data(str(pdf_path), max_pages, filename=filename)
    except Exception:
        logger.warning(
            "takeoff.pdf in-process parse failed (filename=%r) - degrading upload",
            filename,
            exc_info=True,
        )
        return None
    page_count = int(result.get("page_count", 0) or 0)
    pages = result.get("pages") or []
    if not isinstance(pages, list):
        pages = []
    truncated = bool(result.get("truncated", False))
    return page_count, pages, truncated


async def _parse_pdf_isolated(
    pdf_path: Path,
    *,
    filename: str | None = None,
    max_pages: int | None = None,
    timeout_s: float | None = None,
) -> tuple[int, list[dict], bool] | None:
    """Parse a PDF in a memory-capped child process, off the event loop.

    Returns ``(page_count, page_data, truncated)`` on a clean run - including
    the "unreadable document" case, which comes back as ``(0, [], False)`` so
    the caller can apply its definitive parse-failure handling. Returns
    ``None`` when the parse could not complete at all: a timeout, a crash /
    OOM (non-zero exit), unreadable worker output, or a launch failure. The
    caller treats ``None`` as "degrade and still persist the upload" rather
    than a hard error.

    This never raises for a parse problem and never runs a PDF parser in the
    API process, so no PDF - however large, dense or malformed - can take the
    server down.
    """
    max_pages = max_pages if max_pages is not None else _parse_max_pages()
    timeout_s = timeout_s if timeout_s is not None else _parse_timeout_s()

    # The frozen desktop build cannot spawn ``sys.executable -m ...``; parse in
    # the current process there (same parser, same density guard) so takeoff
    # uploads keep working instead of degrading to zero pages.
    if _use_in_process_pdf_parser():
        return await asyncio.to_thread(
            _parse_pdf_in_process,
            pdf_path,
            filename=filename,
            max_pages=max_pages,
        )

    try:
        proc = await asyncio.to_thread(
            _run_pdf_worker,
            pdf_path,
            max_pages=max_pages,
            timeout_s=timeout_s,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "takeoff.pdf_worker timed out after %ss (filename=%r) - degrading upload",
            timeout_s,
            filename,
        )
        return None
    except Exception:
        # Launch failure (interpreter / module missing, OS refusal, ...).
        logger.warning(
            "takeoff.pdf_worker could not run (filename=%r) - degrading upload",
            filename,
            exc_info=True,
        )
        return None

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", "replace")[:500]
        logger.warning(
            "takeoff.pdf_worker exited %s (filename=%r) - degrading upload. stderr=%s",
            proc.returncode,
            filename,
            stderr,
        )
        return None

    try:
        data = json.loads(proc.stdout or b"")
    except (ValueError, TypeError):
        logger.warning(
            "takeoff.pdf_worker returned unparseable output (filename=%r) - degrading upload",
            filename,
            exc_info=True,
        )
        return None

    page_count = int(data.get("page_count", 0) or 0)
    pages = data.get("pages") or []
    if not isinstance(pages, list):
        pages = []
    truncated = bool(data.get("truncated", False))
    return page_count, pages, truncated


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
        self.plan_read_repo = AiTakeoffRunRepository(session)

    async def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        size_bytes: int,
        owner_id: str,
        project_id: str | None = None,
        source_document_id: str | None = None,
    ) -> TakeoffDocument:
        """Upload and process a PDF document for takeoff.

        Pre-parser gates:

        1. 0-byte uploads → 400 (don't hand garbage to the parser).
        2. Size cap (``_max_upload_bytes``, 200 MB default, overridable via
           ``OE_TAKEOFF_MAX_UPLOAD_MB``) → 413 with the env-var name in the
           message so the user/operator can act.
        3. Password-protected PDFs → 400 with a hint about Acrobat/qpdf.

        The bytes are written to disk BEFORE parsing, then parsing runs in an
        isolated, wall-clock-bounded, memory-capped child process
        (:func:`_parse_pdf_isolated`). A huge, vector-dense or malformed PDF
        can crash or OOM that child, but it can never OOM-kill the API worker
        (the container-down P0 this closes).

        Outcomes:

        * Clean parse → document persisted with the extracted pages.
        * Scanned PDF (no text layer) → persisted with ``status="needs_ocr"``
          plus a one-line log hint about the ``[cv]`` extra for OCR.
        * Degraded parse (child timed out / crashed / OOM / worker missing) →
          document still persisted, with 0 pages, empty text and a
          ``parse_degraded`` metadata flag, so the user keeps their upload.
        * Definitive parse failure (child ran fine but neither parser could
          read a single page) → the written bytes are removed and a generic
          400 is returned; the diagnostic stays server-side.
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

        # Persist the uploaded bytes to disk FIRST, before any parsing, so the
        # document is never lost to a parser problem. The parse then runs in an
        # isolated, memory-capped child process (``_parse_pdf_isolated``): a
        # huge, vector-dense or malformed PDF can crash or OOM that child, but
        # it can never take down the API worker (the P0 this fix closes).
        documents_dir = _takeoff_documents_dir()
        documents_dir.mkdir(parents=True, exist_ok=True)
        doc_id = uuid.uuid4()
        file_path = documents_dir / f"{doc_id}.pdf"
        file_path.write_bytes(content)

        parse_degraded = False
        parse_truncated = False
        parsed = await _parse_pdf_isolated(file_path, filename=filename)
        if parsed is None:
            # The isolated parser could not complete (timeout / crash / OOM /
            # missing worker). Keep the upload so the user does not lose their
            # file, just with no extracted pages until it is re-processed.
            parse_degraded = True
            page_count = 0
            page_data: list[dict] = []
            logger.warning(
                "takeoff.upload_document: isolated PDF parse degraded for "
                "filename=%r size=%dB - persisting document with no extracted pages",
                filename,
                size_bytes,
            )
        else:
            page_count, page_data, parse_truncated = parsed

        full_text = "\n\n".join(p["text"] for p in page_data if p.get("text"))

        # Per-page text-layer audit. A page is an OCR candidate when it has no
        # text layer (scanned/raster drawing). We read the per-page ``has_text``
        # flag set by ``_extract_pdf_pages`` and fall back to the page text when
        # the flag is absent (older rows / a stubbed extractor), so a mixed PDF
        # (some text pages, some scanned) keeps the page-level signal instead of
        # being collapsed to a single all-or-nothing verdict.
        pages_without_text: list[int] = [
            int(p.get("page", idx + 1))
            for idx, p in enumerate(page_data)
            if not (p.get("has_text") if "has_text" in p else bool(str(p.get("text", "")).strip()))
        ]
        no_text_count = len(pages_without_text)

        # Fully-scanned path: EVERY page returns empty text. We persist the doc
        # with ``needs_ocr`` so the user still sees it in the list and can either
        # install [cv] (PaddleOCR) or share the source CAD with us.
        is_scanned = bool(page_data) and not full_text.strip()
        # Mixed path: at least one (but not every) content page lacks a text
        # layer. The document still parses, but those pages would otherwise be
        # silently treated as empty - so we surface the count to the user.
        is_partial_no_text = no_text_count > 0 and not is_scanned
        if is_scanned or is_partial_no_text:
            try:
                import paddleocr  # noqa: F401

                paddle_available = True
            except Exception:
                paddle_available = False
            if not paddle_available:
                logger.info(
                    "takeoff.upload_document: %d of %d page(s) have no text layer; "
                    "install [cv] extra (paddleocr) to enable OCR fallback "
                    "(filename=%r, scanned=%s)",
                    no_text_count,
                    page_count,
                    filename,
                    is_scanned,
                )

        if not parse_degraded and page_count == 0 and not page_data:
            # The isolated parser ran cleanly but neither pdfplumber nor pymupdf
            # could read a single page - the file is genuinely unreadable. This
            # is the ONLY definitive parse-failure case and it keeps the
            # historical 400. A DEGRADED parse (worker timeout / crash / OOM) is
            # NOT this case: it was persisted above so the user keeps the upload.
            # Remove the bytes we wrote before rejecting so nothing is orphaned.
            with contextlib.suppress(OSError):
                file_path.unlink()
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

        # Scanned PDFs without OCR get a distinct status so the UI
        # can surface a "needs OCR" affordance instead of silently
        # presenting an empty extracted-text panel.
        doc_status = "needs_ocr" if is_scanned else "uploaded"

        # Persist the per-page text-layer audit so the count survives the
        # round-trip and a mixed (partly-scanned) document is not silently
        # treated as empty. ``status`` stays ``needs_ocr`` only for the
        # fully-scanned case, but the count + page list is stored either way
        # so the API and UI can flag the OCR-candidate pages.
        doc_metadata: dict[str, Any] = {
            "pages_without_text": no_text_count,
            "pages_without_text_list": pages_without_text,
        }
        if parse_degraded:
            # Surfaced so the UI / an operator can offer a re-process action and
            # so support can tell "empty because degraded" from "empty because
            # scanned". The bytes are on disk; only the extraction is missing.
            doc_metadata["parse_degraded"] = True
        if parse_truncated:
            doc_metadata["parse_truncated"] = True
            doc_metadata["parse_page_limit"] = _parse_max_pages()

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
            metadata_=doc_metadata,
            source_document_id=source_document_id,
        )

        try:
            return await self.repo.create(doc)
        except IntegrityError:
            # A concurrent from-source open won the (project_id,
            # source_document_id) unique index (issue #369). The PDF bytes this
            # losing insert wrote to disk above are orphaned by the coming
            # rollback, so remove them, then re-raise for the caller to resolve
            # to the winning row. Only the from-source path passes a
            # source_document_id and can trip this; a direct upload has a NULL
            # source id and never collides.
            with contextlib.suppress(OSError):
                file_path.unlink()
            raise

    async def get_or_create_takeoff_from_source(
        self,
        *,
        source_document_id: str,
        source_project_id: str,
        filename: str,
        content: bytes,
        size_bytes: int,
        owner_id: str,
    ) -> TakeoffDocument:
        """Find-or-create a takeoff document for a Project-Files document.

        Opening a Project-Files PDF in takeoff needs a real ``TakeoffDocument``
        row: takeoff persists page_scales, extracted_text, analysis and every
        measurement FKs to it, none of which a documents-module row can hold.

        Idempotent: if a takeoff document already exists for this source id in
        the project it is returned unchanged (no duplicate, no re-parse).
        Otherwise the source PDF bytes run through the hardened, isolated upload
        path (the same size/page-capped, memory-isolated parse and graceful
        degradation as a normal upload) and the new row is stamped with
        ``source_document_id`` so the next open reuses it.
        """
        project_uuid = uuid.UUID(source_project_id)
        existing = await self.repo.get_by_source_document_id(source_document_id, project_id=project_uuid)
        if existing is not None:
            return existing
        try:
            return await self.upload_document(
                filename=filename,
                content=content,
                size_bytes=size_bytes,
                owner_id=owner_id,
                project_id=source_project_id,
                source_document_id=source_document_id,
            )
        except IntegrityError:
            # Lost the find-or-create race: a concurrent request created the
            # takeoff document for this source first and the unique index
            # rejected our insert (issue #369). Roll our failed transaction back
            # and return the winner, so both callers converge on one row and no
            # measurement is ever stranded on a duplicate. If the re-lookup
            # still finds nothing the violation was something else, so re-raise
            # it untouched.
            await self.session.rollback()
            existing = await self.repo.get_by_source_document_id(source_document_id, project_id=project_uuid)
            if existing is not None:
                return existing
            raise

    async def get_document(self, doc_id: str) -> TakeoffDocument | None:
        return await self.repo.get_by_id(uuid.UUID(doc_id))

    async def set_document_page_scales(self, doc_id: str, page_scales: dict) -> TakeoffDocument | None:
        """Persist the document-level per-page scale calibration (issue #334).

        The document ``page_scales`` column is the authoritative, durable source
        of truth for each sheet's drawing scale (the browser localStorage copy
        is only an offline cache and the per-measurement ``scale_pixels_per_unit``
        is capture provenance). Stored verbatim in the frontend ``PageScales``
        shape so a reload / a second device restores the exact calibration.

        Returns the refreshed row, or ``None`` when the document does not exist.
        """
        did = uuid.UUID(doc_id)
        doc = await self.repo.get_by_id(did)
        if doc is None:
            return None
        await self.repo.update_fields(did, page_scales=page_scales)
        return await self.repo.get_by_id(did)

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

    async def _validate_document_id(
        self,
        document_id: str | None,
        project_id: uuid.UUID,
    ) -> None:
        """Validate a measurement's ``document_id`` (issue #238).

        Measurement identity must be ``project_id`` + a stable document
        UUID, never the PDF filename. Two same-named PDFs would otherwise
        share a measurement namespace. This is the server-side half of the
        fix (defence-in-depth); the frontend already sends the document UUID.

        ``document_id`` is a *polymorphic* reference - it can point at a
        takeoff-uploaded PDF (``oe_takeoff_document``) or a Project Files
        document opened for measuring (``oe_documents_document``) - so we
        keep the column as a plain ``String`` and validate here instead of
        adding a single hard FK that would reject half the valid ids.

        Rules:
        * ``None`` / empty -> allowed (legacy rows carry filenames, and a
          freshly dropped local file has no server UUID yet).
        * non-empty but not a UUID -> 422 (a filename slipped through).
        * a UUID that matches no document *in this project* (either table)
          -> 404, indistinguishable from "project not found" so a foreign
          document id can't be used as an existence oracle.
        """
        if not document_id:
            return

        try:
            doc_uuid = uuid.UUID(str(document_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "document_id must be a document UUID, not a filename. "
                    "Re-open the drawing from Project Files or the takeoff "
                    "filmstrip so the stable id is sent."
                ),
            ) from exc

        # First table: takeoff-uploaded PDFs. Reuse the existing repo.
        takeoff_doc = await self.repo.get_by_id(doc_uuid)
        if takeoff_doc is not None and takeoff_doc.project_id == project_id:
            return

        # Second table: a Project Files document opened for measuring. Query
        # the model directly via the session so the takeoff module doesn't
        # take a hard dependency on the documents service/repository.
        from app.modules.documents.models import Document  # noqa: PLC0415

        project_doc = await self.session.get(Document, doc_uuid)
        if project_doc is not None and project_doc.project_id == project_id:
            return

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found in this project",
        )

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

        Issue #238 - ``document_id`` is validated as a stable document UUID
        belonging to this project (or left null) so measurement identity is
        never keyed on a PDF filename.
        """
        await self._validate_document_id(data.document_id, data.project_id)
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
            # A deduction only makes sense for an area; never tag a distance /
            # count / annotation as a void so the rollup can't subtract a
            # length from an area.
            is_deduction=bool(data.is_deduction) and data.type == "area",
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

    async def detect_scale_from_text(self, doc_id: str) -> dict[str, Any]:
        """Detect an explicit drawing scale from a document's text layer.

        Tier-1, AI-free: scans the per-page ``text`` already extracted into
        ``TakeoffDocument.page_data`` for the explicit scale note the architect
        typed in the title block ("SCALE 1:100", '1/4" = 1\'-0"') via the pure
        :mod:`app.modules.takeoff.scale_detect` parser, and returns the best
        candidate plus the full ranked list. Nothing is persisted or applied -
        the user confirms the offered scale in the calibration dialog (CLAUDE.md
        rule 7).

        Returns ``{best, candidates, source}`` where ``best`` is ``None`` when
        the drawing carries no explicit scale note (an honest empty result, not
        a fabricated guess). A 404 is raised when the document does not exist;
        the caller has already gated tenant access (Audit B5).
        """
        from app.modules.takeoff import scale_detect as _scale_detect

        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Takeoff document not found")

        best, ranked = _scale_detect.detect_best_scale(doc.page_data or [])

        def _as_dict(c: _scale_detect.ScaleCandidate) -> dict[str, Any]:
            return {
                "ratio": c.ratio,
                "label": c.label,
                "confidence": c.confidence,
                "page": c.page,
                "evidence": c.evidence,
                "source": c.source,
                "detail": c.detail,
            }

        return {
            "best": _as_dict(best) if best is not None else None,
            "candidates": [_as_dict(c) for c in ranked],
            "source": "text_layer",
        }

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

        # Read-only back-compat resolution: probe the active root and every
        # platform-owned data root (and the legacy ~/.openestimator path) so a
        # PDF written under a different data-dir resolution is still found,
        # before falling back to the persisted path.
        file_path = _find_existing_takeoff_pdf(doc_id)
        if file_path is None and doc.file_path:
            candidate = Path(doc.file_path)
            if candidate.exists():
                file_path = candidate
        if file_path is None:
            raise HTTPException(
                status_code=404,
                detail="The stored PDF for this document is no longer on disk. Re-upload it to recognize.",
            )

        try:
            import pymupdf  # noqa: PLC0415 - base dep; lazy-imported so a broken wheel degrades to a clear 400
        except ImportError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vector recognition could not load its PDF reader (PyMuPDF). It ships with "
                    "the platform, so this usually means a broken install. Reinstall "
                    "openconstructionerp, or use the online AI analysis instead."
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

    async def find_similar_symbols(
        self,
        doc_id: str,
        page: int,
        seed_x: float,
        seed_y: float,
    ) -> dict[str, Any]:
        """Find every symbol on a page matching the one under ``(seed_x, seed_y)``.

        Seeded "count by example": the user clicks one symbol on the vector PDF
        page and this returns the centroids of all near-identical symbols so
        they can confirm them as a single count measurement. Vector-only and
        DB-free - nothing is persisted (CLAUDE.md rule 7). A scanned/raster
        page (no vector layer) returns an empty hit set with
        ``note='no_vector_layer'`` rather than fabricated geometry.
        """
        from app.modules.takeoff import recognize as _recognize

        doc = await self.repo.get_by_id(uuid.UUID(doc_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Takeoff document not found")
        validate_page_for_document(doc, page)

        # Same read-only back-compat resolution as recognize_candidates.
        file_path = _find_existing_takeoff_pdf(doc_id)
        if file_path is None and doc.file_path:
            candidate = Path(doc.file_path)
            if candidate.exists():
                file_path = candidate
        if file_path is None:
            raise HTTPException(
                status_code=404,
                detail="The stored PDF for this document is no longer on disk. Re-upload it to search.",
            )

        try:
            import pymupdf  # noqa: PLC0415 - base dep; lazy-imported so a broken wheel degrades to a clear 400
        except ImportError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Symbol search could not load its PDF reader (PyMuPDF). It ships with "
                    "the platform, so this usually means a broken install. Reinstall "
                    "openconstructionerp."
                ),
            ) from exc

        try:
            content = file_path.read_bytes()
            pdf = pymupdf.open(stream=content, filetype="pdf")
            try:
                pg = pdf[page - 1]
                drawings = pg.get_drawings()
            finally:
                pdf.close()
        except HTTPException:
            raise
        except Exception:
            logger.exception("takeoff.similar_symbols failed to read page for doc %s page %s", doc_id, page)
            raise HTTPException(
                status_code=422,
                detail="Could not read this page. The PDF may be corrupt or password-protected.",
            ) from None

        result = _recognize.find_similar_symbols(drawings, seed_x, seed_y)
        result["page"] = page
        return result

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
        # Issue #238 - if the patch reassigns document_id, validate the new id
        # is a stable document UUID in this measurement's project (or null).
        # The project is the row's own project_id, not a client-supplied one,
        # so a PATCH can't repoint a measurement at a foreign tenant's doc.
        if "document_id" in fields:
            await self._validate_document_id(fields["document_id"], item.project_id)
        if "metadata" in fields:
            # MERGE incoming metadata over the stored value rather than
            # replacing the whole JSON column. A blind overwrite drops
            # server-stamped keys (ai_takeoff_run_id, verdict, compare_key)
            # that the client never echoes back. Mirrors the metadata-merge
            # pattern used elsewhere (e.g. boq add_custom_column):
            # new = {**existing, **incoming}. ``update_fields`` persists this
            # fresh dict via an explicit UPDATE ... VALUES, so no in-place
            # ORM mutation / flag_modified is needed here.
            incoming_meta = fields.pop("metadata") or {}
            existing_meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
            fields["metadata_"] = {**existing_meta, **incoming_meta}
        if "points" in fields and fields["points"] is not None:
            fields["points"] = [p.model_dump() for p in data.points]  # type: ignore[union-attr]

        # A deduction (opening / void) only makes sense for an area. If the
        # patch tries to flag a non-area measurement as a deduction, drop the
        # flag so the rollup can't subtract a length / count from an area.
        # The effective type is the patched type when present, else current.
        if "is_deduction" in fields and fields["is_deduction"]:
            effective_type_for_deduction = fields.get("type") if "type" in fields else item.type
            if effective_type_for_deduction != "area":
                fields["is_deduction"] = False

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

        Issue #238 - validate each distinct ``(project_id, document_id)``
        pair once (a bulk import is usually one document, so this is a single
        check) so the localStorage import can't smuggle in a filename-keyed
        or foreign-project document id.
        """
        seen_pairs: set[tuple[uuid.UUID, str | None]] = set()
        for data in items:
            pair = (data.project_id, data.document_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            await self._validate_document_id(data.document_id, data.project_id)

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
                is_deduction=bool(data.is_deduction) and data.type == "area",
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
                    "is_deduction": bool(m.is_deduction),
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
            # The BOQ update path commits, which expires ``item``; the
            # router then serializes it synchronously (Pydantic), where a
            # lazy attribute refresh raises MissingGreenlet. Reload the
            # row inside the async context before handing it back.
            await self.session.refresh(item)
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

        # Restate the measured value in the position's own unit before storing
        # it (GitHub #319). The measurement is metric-canonical (m / m2 / m3);
        # a position priced per cubic yard or roofing square must receive the
        # quantity converted into that unit or its unit_rate silently mis-prices
        # the line. convert_between returns None when the two units cannot be
        # reconciled (a magnitude mismatch the coarse dimension guard above did
        # not catch, e.g. m3 vs an unknown volume unit), in which case we refuse
        # rather than write a wrong number. A same-unit or unknown-unit link
        # passes the value through untouched.
        from app.core.unit_conversion import convert_between  # noqa: PLC0415

        measurement_unit = getattr(measurement, "measurement_unit", None)
        position_unit = getattr(position, "unit", None)
        converted = convert_between(value, measurement_unit, position_unit)
        if converted is None:
            logger.warning(
                "push_quantity: cannot convert measurement %s (%s) into BOQ position %s unit %r "
                "- refusing to overwrite the quantity",
                getattr(measurement, "id", "?"),
                measurement_unit,
                boq_position_id,
                position_unit,
            )
            return
        if converted != Decimal(str(value)):
            value = converted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

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

    # ── Vision-LLM plan reading (issue #194) ───────────────────────────────
    #
    # An ADDITIONAL, higher-quality suggestion source alongside the offline
    # OpenCV "Recognize" tool, never a replacement. Bring-your-own-key, hard
    # cost-capped, and human-confirmed: every model output is a proposal with a
    # real confidence; only an explicit accept writes a billed measurement, and
    # the server recomputes the number from points x scale (B8).

    async def _resolve_plan_read_provider(
        self,
        user_id: str,
    ) -> tuple[str, str, str | None, str]:
        """Resolve the confirming user's vision provider / key / model.

        Returns ``(provider, api_key, model_override, effective_model)``. The
        BYO-key plumbing (``resolve_provider_key_model``) is reused unchanged.

        Raises:
            HTTPException(400): No AI key configured, or the resolved
                provider/model is not vision-capable. Never a silent fallback
                to a text-only call (that would fabricate geometry).
        """
        from app.modules.ai.ai_client import default_model_for, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository
        from app.modules.takeoff.plan_read import VISION_PROVIDERS, is_vision_capable

        settings = await AISettingsRepository(self.session).get_by_user_id(uuid.UUID(user_id))
        try:
            provider, api_key, model_override = resolve_provider_key_model(settings)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No AI provider configured. Please add an API key in Settings > AI.",
            ) from exc

        effective_model = model_override or default_model_for(provider)
        if not is_vision_capable(provider, effective_model):
            providers = ", ".join(sorted(VISION_PROVIDERS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your AI provider/model does not support image analysis. Pick a "
                    f"vision-capable provider ({providers}) in Settings > AI - for "
                    "example Anthropic Claude, OpenAI GPT-4.1, or Gemini."
                ),
            )
        return provider, api_key, model_override, effective_model

    async def plan_read_meta(self, user_id: str) -> dict[str, Any]:
        """Thresholds, vision availability, caps, and rolling spend for the UI.

        Never raises on a missing key - it reports ``vision_available=False``
        with a reason so the takeoff viewer can degrade gracefully (hide /
        disable the "Read plan with AI" action) while the offline Recognize
        button keeps working.
        """
        from app.modules.takeoff.plan_read import VISION_PROVIDERS
        from app.modules.takeoff.schemas import (
            MAX_PLAN_POLYGON_VERTICES,
            TAKEOFF_CONFIDENCE_HIGH_THRESHOLD,
            TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD,
        )

        vision_available = False
        provider: str | None = None
        effective_model: str | None = None
        reason: str | None = None
        try:
            provider, _key, _override, effective_model = await self._resolve_plan_read_provider(user_id)
            vision_available = True
        except HTTPException as exc:
            reason = str(exc.detail)

        rolling = await self.plan_read_repo.rolling_spend_usd(uuid.UUID(user_id))
        return {
            "confidence_high_threshold": TAKEOFF_CONFIDENCE_HIGH_THRESHOLD,
            "confidence_medium_threshold": TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD,
            "vision_providers": sorted(VISION_PROVIDERS),
            "max_polygon_vertices": MAX_PLAN_POLYGON_VERTICES,
            "max_cost_usd": _takeoff_ai_max_cost_usd(),
            "rolling_spend_usd": round(rolling, 4),
            "modes": ["scale", "rooms", "symbols", "full"],
            "vision_available": vision_available,
            "provider": provider,
            "model_used": effective_model,
            "reason": reason,
        }

    async def plan_read_start(
        self,
        *,
        project_id: uuid.UUID,
        document_id: str,
        page: int,
        mode: str,
        scale_pixels_per_unit: float | None,
        do_cost_match: bool,
        user_id: str,
    ) -> AiTakeoffRun:
        """Validate, cost-gate, create, and schedule a plan-read run.

        Resolves the user's vision key (400 on no key / non-vision model),
        validates the page is in range, applies the pre-flight cost cap (refuse
        BEFORE calling the provider when the rolling spend plus this call's
        estimate would exceed ``TAKEOFF_AI_MAX_COST_USD``), creates the run row,
        and schedules the in-process reading coroutine. Returns the queued run.
        """
        from app.core.ai.pricing import estimate_cost_usd

        provider, _api_key, _override, effective_model = await self._resolve_plan_read_provider(user_id)

        doc = await self.repo.get_by_id(uuid.UUID(document_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Takeoff document not found")
        validate_page_for_document(doc, page)

        # Pre-flight cost gate. A conservative token estimate (image tokens plus
        # the capped output) priced at the resolved model; refuse before any
        # spend when the rolling window plus this estimate would exceed the cap.
        cap = _takeoff_ai_max_cost_usd()
        rolling = await self.plan_read_repo.rolling_spend_usd(uuid.UUID(user_id))
        preflight_tokens = _PLAN_READ_PREFLIGHT_TOKENS
        this_call = float(estimate_cost_usd(effective_model, preflight_tokens))
        if rolling + this_call > cap:
            run = await self.plan_read_repo.create(
                AiTakeoffRun(
                    project_id=project_id,
                    document_id=document_id,
                    page=page,
                    mode=mode,
                    user_id=uuid.UUID(user_id),
                    created_by=user_id,
                    status="failed",
                    provider=provider,
                    model_used=effective_model,
                    scale_pixels_per_unit=scale_pixels_per_unit,
                    do_cost_match=do_cost_match,
                    failure_reason="cost_cap",
                    validation_report={
                        "cost_cap_usd": cap,
                        "rolling_spend_usd": round(rolling, 4),
                        "estimated_call_usd": round(this_call, 4),
                    },
                )
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This run would exceed your AI spend cap of ${cap:.2f}. You have "
                    f"already spent ${rolling:.2f} on plan reading recently. Raise "
                    "TAKEOFF_AI_MAX_COST_USD or wait for the window to roll over. "
                    f"(run {run.id})"
                ),
            )

        run = await self.plan_read_repo.create(
            AiTakeoffRun(
                project_id=project_id,
                document_id=document_id,
                page=page,
                mode=mode,
                user_id=uuid.UUID(user_id),
                created_by=user_id,
                status="queued",
                provider=provider,
                model_used=effective_model,
                scale_pixels_per_unit=scale_pixels_per_unit,
                do_cost_match=do_cost_match,
            )
        )
        await self.session.commit()
        self._schedule_plan_read(run.id, user_id=user_id)
        return run

    def _schedule_plan_read(self, run_id: uuid.UUID, *, user_id: str) -> None:
        """Detach the reading coroutine on its own DB session.

        Mirrors the event-bus / job-runner pattern: the background task owns a
        fresh ``AsyncSession`` so it never touches the request session after the
        response is sent. Tests call ``_run_plan_read`` directly with a stub,
        so this thin scheduler is the only un-unit-tested seam.
        """
        import asyncio

        async def _runner() -> None:
            from app.database import async_session_factory

            async with async_session_factory() as bg_session:
                svc = TakeoffService(bg_session)
                try:
                    await svc._run_plan_read(run_id, user_id=user_id)
                    await bg_session.commit()
                except Exception:
                    logger.exception("plan_read background run %s failed", run_id)
                    await bg_session.rollback()

        try:
            asyncio.create_task(_runner())  # noqa: RUF006 - detached background job
        except RuntimeError:
            logger.warning("plan_read run %s: no running loop to schedule on", run_id)

    async def _run_plan_read(self, run_id: uuid.UUID, *, user_id: str) -> None:
        """Execute one plan-read run: rasterize, read, validate, persist.

        FSM: ``queued -> rasterizing -> reading -> validating -> review`` (or
        ``failed``). The vision call is the only network step; everything else
        is deterministic. Proposals are persisted as ``review_status='proposed'``
        rows so the viewer's existing list / render / accept paths handle them.
        Zero rooms reaches ``review`` with ``proposal_count=0`` (honest empty),
        never ``failed``.
        """
        import time as _time

        from app.core.ai.pricing import estimate_cost_usd
        from app.modules.ai.ai_client import call_ai, extract_json
        from app.modules.ai.prompts import (
            PLAN_READ_ROOMS_INSTRUCTION,
            PLAN_READ_SCALE_INSTRUCTION,
            PLAN_READ_SYMBOLS_INSTRUCTION,
            PLAN_READ_VISION_PROMPT,
            PLAN_READ_VISION_SYSTEM_PROMPT,
            fence_user_content,
        )
        from app.modules.takeoff import plan_read as _pr

        run = await self.plan_read_repo.get_by_id(run_id)
        if run is None:
            logger.warning("plan_read run %s vanished before execution", run_id)
            return

        provider, api_key, model_override, effective_model = await self._resolve_plan_read_provider(user_id)
        start = _time.monotonic()
        await self.plan_read_repo.update_fields(run_id, status="rasterizing")

        # ── rasterize ──────────────────────────────────────────────────────
        try:
            doc = await self.repo.get_by_id(uuid.UUID(run.document_id))
            if doc is None:
                await self._fail_plan_read(run_id, "document_missing", start)
                return
            # Read-only back-compat resolution (see recognize path): find the
            # PDF across every platform-owned data root before falling back to
            # the persisted path, so a redeployed volume still resolves.
            file_path = _find_existing_takeoff_pdf(run.document_id)
            if file_path is None and doc.file_path:
                candidate = Path(doc.file_path)
                if candidate.exists():
                    file_path = candidate
            if file_path is None:
                await self._fail_plan_read(run_id, "pdf_not_on_disk", start)
                return
            content = file_path.read_bytes()
            png, media_type, dpi, page_w_pt, page_h_pt = _pr.rasterize_page(content, run.page)
        except ImportError:
            await self._fail_plan_read(run_id, "pymupdf_missing", start)
            return
        except Exception:
            logger.exception("plan_read run %s rasterize failed", run_id)
            await self._fail_plan_read(run_id, "rasterize_failed", start)
            return

        # ── read (the single network call) ─────────────────────────────────
        await self.plan_read_repo.update_fields(run_id, status="reading")
        # Scale is always read (every mode benefits from a scale handshake); the
        # heavier room / symbol blocks are added only when the mode asks for
        # them, so the cheapest mode is the cheapest call.
        instructions: list[str] = [PLAN_READ_SCALE_INSTRUCTION]
        if run.mode in ("rooms", "full"):
            instructions.append(PLAN_READ_ROOMS_INSTRUCTION)
        if run.mode in ("symbols", "full"):
            instructions.append(PLAN_READ_SYMBOLS_INSTRUCTION)
        # A free-form discipline hint would be fenced via fence_user_content
        # before reaching the model (the image itself cannot be fenced). v1
        # carries no hint, so the fenced block is empty.
        discipline_hint = fence_user_content("", max_len=500)
        prompt = PLAN_READ_VISION_PROMPT.format(
            mode_instructions="\n\n".join(instructions),
            discipline_hint=discipline_hint,
        )
        import base64

        try:
            raw_response, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=PLAN_READ_VISION_SYSTEM_PROMPT,
                prompt=prompt,
                image_base64=base64.b64encode(png).decode("utf-8"),
                image_media_type=media_type,
                max_tokens=_PLAN_READ_MAX_TOKENS,
                model=model_override,
            )
        except ValueError as exc:
            low = str(exc).lower()
            reason = "rate_limited" if "rate limit" in low else "provider_error"
            logger.warning("plan_read run %s provider error: %s", run_id, exc)
            await self._fail_plan_read(run_id, reason, start, provider=provider, model=effective_model)
            return
        except Exception:
            logger.exception("plan_read run %s unexpected provider failure", run_id)
            await self._fail_plan_read(run_id, "provider_unavailable", start, provider=provider, model=effective_model)
            return

        # ── validate ───────────────────────────────────────────────────────
        await self.plan_read_repo.update_fields(run_id, status="validating")
        parsed = extract_json(raw_response)
        result, dropped = _pr.parse_plan_read_response(
            parsed,
            page=run.page,
            page_width_pt=page_w_pt,
            page_height_pt=page_h_pt,
        )

        scale_ratio = run.scale_pixels_per_unit
        if result.scale is not None and scale_ratio is None:
            scale_ratio = _pr.scale_ratio_from_plan_scale(result.scale, page_w_pt, page_h_pt)

        proposals = self._build_plan_read_proposals(
            run=run,
            result=result,
            page_w_pt=page_w_pt,
            page_h_pt=page_h_pt,
            scale_ratio=scale_ratio,
            user_id=user_id,
        )
        if proposals:
            await self.measurement_repo.create_bulk(proposals)

        duration_ms = int((_time.monotonic() - start) * 1000)
        cost = float(estimate_cost_usd(effective_model, int(tokens or 0)))
        validation_report = {
            "dropped_items": dropped,
            "rooms_proposed": len(result.rooms),
            "symbols_proposed": len(result.symbols),
            "scale_detected": result.scale is not None,
            "scale_ratio_px_per_unit": scale_ratio,
            "image_dpi": dpi,
        }
        await self.plan_read_repo.update_fields(
            run_id,
            status="review",
            provider=provider,
            model_used=effective_model,
            total_tokens=int(tokens or 0),
            cost_usd_estimate=cost,
            duration_ms=duration_ms,
            proposal_count=len(proposals),
            validation_report=validation_report,
        )

    def _build_plan_read_proposals(
        self,
        *,
        run: AiTakeoffRun,
        result: Any,
        page_w_pt: float,
        page_h_pt: float,
        scale_ratio: float | None,
        user_id: str,
    ) -> list[TakeoffMeasurement]:
        """Turn a validated ``PlanReadResult`` into ``proposed`` measurements.

        Rooms become ``area`` proposals whose value is the SERVER's shoelace
        recompute (never the model's claimed area). A self-intersecting room is
        flagged and capped to the low band. Symbol classes become ``count``
        proposals whose points are the centroids. Every proposal carries
        ``source='ai_plan_read'``, ``review_status='proposed'``, the model
        confidence, and the run id in ``metadata_`` so accept and the review
        list can find it. Nothing here is billed until a human accepts it.
        """
        from app.modules.takeoff import plan_read as _pr
        from app.modules.takeoff.schemas import (
            TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD,
        )

        out: list[TakeoffMeasurement] = []
        run_meta_base = {"ai_takeoff_run_id": str(run.id), "page_width_pt": page_w_pt, "page_height_pt": page_h_pt}

        for room in result.rooms:
            pdf_points = _pr.norm_polygon_to_pdf_points(room.polygon, page_w_pt, page_h_pt)
            self_intersects = _pr.polygon_self_intersects(pdf_points)
            confidence = (
                round(min(room.confidence, TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD - 0.01), 2)
                if self_intersects
                else round(room.confidence, 2)
            )
            area_pt2 = _pr.shoelace_area(pdf_points)
            value: float | None = None
            if scale_ratio and scale_ratio > 0:
                value = area_pt2 / (scale_ratio * scale_ratio)
            meta = {
                **run_meta_base,
                "room_name": room.name,
                "self_intersects": self_intersects,
                "verdict": "error" if self_intersects else "ok",
            }
            out.append(
                TakeoffMeasurement(
                    project_id=run.project_id,
                    document_id=run.document_id,
                    page=run.page,
                    type="area",
                    group_name="AI plan read",
                    group_color="#8B5CF6",
                    annotation=room.name or None,
                    points=[{"x": p[0], "y": p[1]} for p in pdf_points],
                    measurement_value=value,
                    measurement_unit="m2",
                    scale_pixels_per_unit=scale_ratio,
                    source="ai_plan_read",
                    confidence=confidence,
                    review_status="proposed",
                    metadata_=meta,
                    created_by=user_id,
                )
            )

        for symbol in result.symbols:
            centers = _pr.norm_polygon_to_pdf_points(symbol.centers, page_w_pt, page_h_pt)
            out.append(
                TakeoffMeasurement(
                    project_id=run.project_id,
                    document_id=run.document_id,
                    page=run.page,
                    type="count",
                    group_name="AI plan read",
                    group_color="#8B5CF6",
                    annotation=symbol.element_class or None,
                    points=[{"x": p[0], "y": p[1]} for p in centers],
                    measurement_value=float(len(centers)),
                    count_value=len(centers),
                    measurement_unit="pcs",
                    source="ai_plan_read",
                    confidence=round(symbol.confidence, 2),
                    review_status="proposed",
                    metadata_={**run_meta_base, "element_class": symbol.element_class, "verdict": "ok"},
                    created_by=user_id,
                )
            )
        return out

    async def _fail_plan_read(
        self,
        run_id: uuid.UUID,
        reason: str,
        start: float,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Mark a run ``failed`` with a reason and the elapsed duration."""
        import time as _time

        fields: dict[str, Any] = {
            "status": "failed",
            "failure_reason": reason,
            "duration_ms": int((_time.monotonic() - start) * 1000),
        }
        if provider is not None:
            fields["provider"] = provider
        if model is not None:
            fields["model_used"] = model
        await self.plan_read_repo.update_fields(run_id, **fields)

    async def get_plan_read_run(self, run_id: uuid.UUID) -> AiTakeoffRun | None:
        """Fetch a plan-read run by id (for polling)."""
        return await self.plan_read_repo.get_by_id(run_id)

    async def list_plan_read_proposals(self, run_id: uuid.UUID) -> list[TakeoffMeasurement]:
        """List the ``proposed`` measurements minted by a run."""
        return await self.measurement_repo.list_proposals_for_run(run_id)

    async def accept_plan_read(
        self,
        run_id: uuid.UUID,
        *,
        measurement_ids: list[str] | None,
        min_confidence: float | None,
    ) -> dict[str, Any]:
        """Confirm selected / above-threshold proposals into billed measurements.

        Selection is by explicit ``measurement_ids`` or a ``min_confidence``
        threshold (or all proposals when neither is given). A proposal carrying
        a self-intersection ERROR verdict is BLOCKED (the user must redraw it
        first), counted in ``blocked``. Low confidence is a warning, not a
        block - it is accepted when explicitly selected or above the threshold.
        On confirm the row flips to ``review_status='confirmed'``; the geometry
        and value are left intact (the server already owns the shoelace number).
        """
        proposals = await self.measurement_repo.list_proposals_for_run(run_id)
        wanted = {str(m) for m in measurement_ids} if measurement_ids else None

        confirmed_ids: list[str] = []
        skipped = 0
        blocked = 0
        for prop in proposals:
            mid = str(prop.id)
            if wanted is not None and mid not in wanted:
                skipped += 1
                continue
            conf = prop.confidence if prop.confidence is not None else 0.0
            if min_confidence is not None and conf < min_confidence:
                skipped += 1
                continue
            verdict = (prop.metadata_ or {}).get("verdict") if isinstance(prop.metadata_, dict) else None
            if verdict == "error":
                blocked += 1
                continue
            # The DB write is identical for every confirmed row; flip the row to
            # confirmed via the repository, which keeps the ORM identity cache
            # coherent and matches the access pattern the unit tests mock.
            await self.measurement_repo.update_fields(prop.id, review_status="confirmed")
            confirmed_ids.append(mid)

        if confirmed_ids:
            run = await self.plan_read_repo.get_by_id(run_id)
            if run is not None:
                await self.plan_read_repo.update_fields(
                    run_id,
                    accepted_count=int(run.accepted_count or 0) + len(confirmed_ids),
                    status="applied",
                )
        return {
            "confirmed": len(confirmed_ids),
            "skipped": skipped,
            "blocked": blocked,
            "measurement_ids": confirmed_ids,
        }


# Conservative pre-flight token estimate for one 2000px page vision call
# (image tokens + the capped output). Used only by the pre-flight cost gate;
# the real token count from the provider replaces it after the call.
_PLAN_READ_PREFLIGHT_TOKENS = 4000
# Output is geometry and short labels, not prose - a small cap keeps cost down.
_PLAN_READ_MAX_TOKENS = 2048

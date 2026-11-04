# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure helpers for the vision-LLM plan-reading path (issue #194).

This module is the deterministic, DB-free half of the vision plan reader. It
owns every number the model is NOT trusted to produce: the page rasterization
geometry, the normalized-to-PDF-point mapping, the scale-ratio derivation and
its plausibility belt, the shoelace area recompute, and the self-intersection
test. The vision model only PROPOSES (a scale reference, room polygons, symbol
centroids); this module turns those proposals into checked geometry, and the
service layer turns checked geometry into human-confirmed measurements.

Nothing here calls a network or an AI provider. The PDF reader is a base
dependency, but :func:`rasterize_page` imports it lazily so the rest of the module
unit-tests with no dependency at all and a broken wheel surfaces as a clear
error from one function rather than an import-time failure.

Coordinate contract (matches the image, the canvas, and the PDF-point space):
normalized ``[0, 1]``, origin top-left, ``x`` increases right, ``y`` increases
down. No vertical flip - :mod:`app.core.pdf_reader` pages already use a
top-left origin via ``page.rect``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ── Vision capability ────────────────────────────────────────────────────────

#: Providers whose ``call_ai`` dispatch path actually attaches ``image_base64``
#: to the request (the multimodal-capable transports). A provider outside this
#: set cannot read a drawing image, so the plan-read run refuses rather than
#: silently degrading to a text-only call that would fabricate geometry.
VISION_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "gemini", "openrouter"})

#: Model-name fragments that mark a known text-only model even on an otherwise
#: vision-capable provider. Kept deliberately small and conservative: when in
#: doubt we treat a model as vision-capable (the provider's own 400 is the
#: final backstop) rather than block a legitimate model we have not heard of.
_TEXT_ONLY_MODEL_FRAGMENTS: tuple[str, ...] = (
    "gpt-3.5",
    "text-embedding",
    "embedding",
    "tts",
    "whisper",
    "moderation",
)


def is_vision_capable(provider: str | None, model: str | None = None) -> bool:
    """Return True when ``provider`` (and ``model``) can analyse an image.

    The provider must be in :data:`VISION_PROVIDERS`. When a ``model`` id is
    given, an obvious text-only / non-multimodal model fragment downgrades the
    answer to False so the service can return an actionable 400 before spending
    a token. Unknown models on a vision provider are treated as capable.

    Args:
        provider: Resolved provider slug (e.g. ``"anthropic"``).
        model: Optional resolved model id. When omitted only the provider is
            checked.

    Returns:
        True when the resolved provider/model pair can read a drawing image.
    """
    if not provider or provider.lower() not in VISION_PROVIDERS:
        return False
    if model:
        low = model.lower()
        if any(frag in low for frag in _TEXT_ONLY_MODEL_FRAGMENTS):
            return False
    return True


# ── Page rasterization ───────────────────────────────────────────────────────

# Target long-edge pixel size for the single vision image. Big enough to keep
# dimension text and thin walls legible, small enough to stay under provider
# image limits in one call (no tiling in v1).
DEFAULT_TARGET_LONG_EDGE_PX = 2000
# Re-render at this smaller long edge when the first PNG is over the byte guard.
FALLBACK_TARGET_LONG_EDGE_PX = 1500
# PNG byte budget. Anthropic caps image payloads near ~5 MB; staying under 6 MB
# (with the fallback re-render below it) keeps every provider happy.
_PNG_BYTE_GUARD = 6 * 1024 * 1024
# DPI clamp - below 72 the text is unreadable, above 300 the page balloons.
_MIN_DPI = 72
_MAX_DPI = 300
_POINTS_PER_INCH = 72.0


def clamp_dpi(long_edge_pt: float, target_long_edge_px: int) -> int:
    """Pick a render DPI that maps ``long_edge_pt`` to ~``target_long_edge_px``.

    A0/A1 sheets downscale to a single in-limit image; small A4 detail upscales
    so dimension text is legible. The normalized-coordinate mapping later uses
    ``page.rect`` points (DPI-invariant), so this only affects image fidelity,
    never alignment.

    Args:
        long_edge_pt: The page's longer edge in PDF points.
        target_long_edge_px: Desired pixel length of that edge.

    Returns:
        An integer DPI clamped to ``[72, 300]``.
    """
    if long_edge_pt <= 0:
        return _MIN_DPI
    raw = round(target_long_edge_px * _POINTS_PER_INCH / long_edge_pt)
    return max(_MIN_DPI, min(_MAX_DPI, int(raw)))


def rasterize_page(
    content: bytes,
    page: int,
    *,
    target_long_edge_px: int = DEFAULT_TARGET_LONG_EDGE_PX,
) -> tuple[bytes, str, int, float, float]:
    """Render one PDF page to a single in-limit PNG for a vision call.

    Renders through :mod:`app.core.pdf_reader`. PNG is used over JPEG because
    JPEG smears thin walls and dimension text. If the first render is over the byte guard the
    page is re-rendered at the smaller fallback long edge.

    Args:
        content: Raw PDF bytes.
        page: 1-indexed page number.
        target_long_edge_px: Desired long-edge pixel size for the first render.

    Returns:
        ``(png_bytes, media_type, dpi, page_width_pt, page_height_pt)``. The
        page dimensions are PDF points (DPI-invariant) for the normalized
        coordinate mapping.

    Raises:
        ImportError: The PDF reader (pypdfium2) is unimportable. It ships with
            the platform, so this means a broken install.
        ValueError: The page is out of range or the PDF cannot be opened.
    """
    from app.core import pdf_reader  # noqa: PLC0415 - lazy so a broken wheel degrades to a clear error here

    try:
        pdf = pdf_reader.open_pdf(content)
    except pdf_reader.PdfReaderError as exc:
        raise ValueError(f"cannot open PDF: {exc}") from exc
    try:
        if page < 1 or page > pdf.page_count:
            msg = f"page {page} out of range (document has {pdf.page_count} pages)"
            raise ValueError(msg)
        pg = pdf[page - 1]
        page_w_pt = float(pg.rect.width)
        page_h_pt = float(pg.rect.height)
        long_edge_pt = max(page_w_pt, page_h_pt)

        dpi = clamp_dpi(long_edge_pt, target_long_edge_px)
        png = pg.render(dpi=dpi).png()
        if len(png) > _PNG_BYTE_GUARD and target_long_edge_px > FALLBACK_TARGET_LONG_EDGE_PX:
            dpi = clamp_dpi(long_edge_pt, FALLBACK_TARGET_LONG_EDGE_PX)
            png = pg.render(dpi=dpi).png()
        return png, "image/png", dpi, page_w_pt, page_h_pt
    finally:
        pdf.close()


# ── Normalized <-> PDF point mapping ─────────────────────────────────────────

Point = tuple[float, float]


def norm_to_pdf_point(
    nx: float,
    ny: float,
    page_width_pt: float,
    page_height_pt: float,
) -> Point:
    """Map one normalized ``[0, 1]`` point to PDF points on the page.

    The normalized origin is top-left with ``y`` down, matching ``page.rect``,
    so no flip is applied. Inputs are clamped to ``[0, 1]`` defensively even
    though the schema already bounds them, so a rounding overshoot can never
    push a vertex off the page.

    Args:
        nx: Normalized x in ``[0, 1]``.
        ny: Normalized y in ``[0, 1]``.
        page_width_pt: Page width in PDF points.
        page_height_pt: Page height in PDF points.

    Returns:
        ``(x_pt, y_pt)`` in PDF points.
    """
    cx = min(1.0, max(0.0, nx))
    cy = min(1.0, max(0.0, ny))
    return (cx * page_width_pt, cy * page_height_pt)


def norm_polygon_to_pdf_points(
    polygon: list[Any],
    page_width_pt: float,
    page_height_pt: float,
) -> list[Point]:
    """Map a normalized polygon to a list of PDF-point tuples.

    Each vertex is read defensively as a ``NormPoint`` schema object, a mapping
    with ``x``/``y``, or an ``(x, y)`` pair, so the same helper serves both the
    validated schema path and a plain-tuple test fixture.

    Args:
        polygon: Ordered normalized vertices.
        page_width_pt: Page width in PDF points.
        page_height_pt: Page height in PDF points.

    Returns:
        Ordered PDF-point tuples.
    """
    out: list[Point] = []
    for vertex in polygon:
        nx, ny = _read_xy(vertex)
        out.append(norm_to_pdf_point(nx, ny, page_width_pt, page_height_pt))
    return out


def _read_xy(obj: Any) -> tuple[float, float]:
    """Best-effort ``(x, y)`` from a schema object, mapping, or pair."""
    if hasattr(obj, "x") and hasattr(obj, "y"):
        return float(obj.x), float(obj.y)
    if isinstance(obj, dict):
        return float(obj["x"]), float(obj["y"])
    if isinstance(obj, (list, tuple)) and len(obj) >= 2:
        return float(obj[0]), float(obj[1])
    msg = f"cannot read x/y from {obj!r}"
    raise ValueError(msg)


# ── Geometry (shoelace area, self-intersection) ──────────────────────────────


def shoelace_area(points: list[Point]) -> float:
    """Polygon area in squared PDF points (boundary auto-closed).

    This is the single source of truth for a room's area: the model's own
    area claim is never trusted (Audit B8). Returns ``0.0`` for a degenerate
    (fewer than 3 vertices) polygon.
    """
    n = len(points)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_self_intersects(points: list[Point]) -> bool:
    """True when the closed polygon's edges cross (non-simple polygon).

    Parity twin of the offline ``recognize._segments_self_intersect`` and the
    frontend ``isSelfIntersecting`` so the server and the canvas agree on what
    counts as a bad trace. A self-intersecting room is capped to the low band
    regardless of the model's self-score (geometry honesty overrides model
    optimism) and is blocked from accept until redrawn.
    """
    n = len(points)
    if n < 4:
        return False

    def _ccw(a: Point, b: Point, c: Point) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
        return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)

    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            # Skip adjacent edges (they legitimately share a vertex) and the
            # wrap-around pair that closes the ring.
            if j == i or (i == 0 and j == n - 1) or j == i + 1:
                continue
            if _cross(*edges[i], *edges[j]):
                return True
    return False


# ── Scale derivation and plausibility ────────────────────────────────────────

# Convert the model's real-world reference value into metres before deriving
# the ratio so the plausibility belt always reasons in one unit.
_UNIT_TO_METRES: dict[str, float] = {
    "m": 1.0,
    "mm": 0.001,
    "ft": 0.3048,
    "in": 0.0254,
}

# The whole page must imply a real-world span inside this belt. Below ~0.5 m the
# sheet would be a postage stamp; above ~5000 m it would be a city block on one
# A1 - both signal a hallucinated ratio (the classic "1px = 1000m").
_MIN_PAGE_SPAN_M = 0.5
_MAX_PAGE_SPAN_M = 5000.0

# An ``inferred`` scale (read from a typical door width, not a real dimension
# string or scale bar) can never read as more than this confidence: it is a
# last-resort guess and must never out-rank a measured reference.
INFERRED_SCALE_MAX_CONFIDENCE = 0.7


def unit_to_metres(value: float, unit: str | None) -> float:
    """Convert ``value`` in ``unit`` to metres; unknown unit assumes metres."""
    factor = _UNIT_TO_METRES.get((unit or "m").lower(), 1.0)
    return value * factor


def derive_scale_ratio(
    ref_p1_pdf: Point,
    ref_p2_pdf: Point,
    ref_real_value: float,
    ref_unit: str | None,
) -> float | None:
    """Derive ``pixels_per_unit`` (PDF points per metre) from a scale reference.

    The reference is two PDF-point endpoints that the model says span a known
    real-world distance (e.g. a 4.10 m dimension string). The ratio is the
    pixel distance between the endpoints divided by the real distance in metres.

    Args:
        ref_p1_pdf: First reference endpoint in PDF points.
        ref_p2_pdf: Second reference endpoint in PDF points.
        ref_real_value: The reference's real-world length.
        ref_unit: The reference's unit (``m``/``mm``/``ft``/``in``).

    Returns:
        PDF points per metre, or ``None`` when the reference is degenerate
        (zero pixel span or non-positive real value).
    """
    real_m = unit_to_metres(ref_real_value, ref_unit)
    if real_m <= 0:
        return None
    px = math.hypot(ref_p2_pdf[0] - ref_p1_pdf[0], ref_p2_pdf[1] - ref_p1_pdf[1])
    if px <= 0:
        return None
    return px / real_m


def scale_is_plausible(
    ratio_px_per_m: float,
    page_width_pt: float,
    page_height_pt: float,
) -> bool:
    """Reject a scale ratio that implies an absurd real-world page span.

    The page's longer edge, divided by the ratio, is the real-world span the
    scale implies. A ratio that turns an A1 sheet into less than ~0.5 m or more
    than ~5000 m across is a hallucination, not a reading. This is the belt that
    catches a model returning ``1px = 1000m``.

    Args:
        ratio_px_per_m: Candidate PDF-points-per-metre ratio.
        page_width_pt: Page width in PDF points.
        page_height_pt: Page height in PDF points.

    Returns:
        True when the implied page span is inside ``[0.5 m, 5000 m]``.
    """
    if ratio_px_per_m <= 0:
        return False
    long_edge_pt = max(page_width_pt, page_height_pt)
    if long_edge_pt <= 0:
        return False
    span_m = long_edge_pt / ratio_px_per_m
    return _MIN_PAGE_SPAN_M <= span_m <= _MAX_PAGE_SPAN_M


def clamp_inferred_confidence(source: str | None, confidence: float) -> float:
    """Cap an ``inferred`` scale's confidence to the floor so it never reads high.

    Args:
        source: The scale source (``dimension_string``/``scale_bar``/``inferred``).
        confidence: The model's self-scored confidence in ``[0, 1]``.

    Returns:
        ``confidence`` unchanged for a measured source, or capped to
        :data:`INFERRED_SCALE_MAX_CONFIDENCE` for an inferred one.
    """
    if source == "inferred":
        return min(confidence, INFERRED_SCALE_MAX_CONFIDENCE)
    return confidence


# ── Structured-output validation ─────────────────────────────────────────────
#
# The model returns free-form JSON. These helpers turn it into a validated
# ``PlanReadResult`` by routing each room / symbol / scale through the Pydantic
# schema and DROPPING any single malformed or out-of-bounds item rather than
# failing the whole call (mirrors the AI module's ``_validate_items``). A
# rejected item is counted so the run's validation report stays honest.


def parse_plan_read_response(
    parsed: Any,
    *,
    page: int,
    page_width_pt: float,
    page_height_pt: float,
) -> tuple[Any, list[str]]:
    """Validate raw model JSON into a ``PlanReadResult``, dropping bad items.

    Lazily imports the schema (the module stays import-light for callers that
    only need the geometry helpers). Each room / symbol / scale is validated
    independently; an item that fails schema validation, references an
    off-image coordinate, or (for scale) fails the plausibility belt is
    DROPPED and its reason recorded, rather than poisoning the whole response.

    Args:
        parsed: The JSON object already extracted from the model's text.
        page: 1-indexed page the run targeted.
        page_width_pt: Page width in PDF points (for scale plausibility).
        page_height_pt: Page height in PDF points (for scale plausibility).

    Returns:
        ``(PlanReadResult, dropped_reasons)``. ``dropped_reasons`` is a list of
        short machine-readable strings naming each rejected item.
    """
    from pydantic import ValidationError

    from app.modules.takeoff.schemas import (
        PlanReadResult,
        PlanRoom,
        PlanScale,
        PlanSymbol,
    )

    dropped: list[str] = []
    if not isinstance(parsed, dict):
        return (
            PlanReadResult(page=page, page_width_pt=page_width_pt, page_height_pt=page_height_pt),
            ["response_not_an_object"],
        )

    # ── scale ──────────────────────────────────────────────────────────────
    scale_obj: Any = None
    raw_scale = parsed.get("scale")
    if isinstance(raw_scale, dict):
        try:
            candidate = PlanScale.model_validate(_normalize_scale_dict(raw_scale))
        except ValidationError:
            dropped.append("scale:schema")
        else:
            scale_obj = _accept_or_reject_scale(candidate, page_width_pt, page_height_pt, dropped)

    # ── rooms ──────────────────────────────────────────────────────────────
    rooms: list[Any] = []
    for raw_room in _as_list(parsed.get("rooms")):
        if not isinstance(raw_room, dict):
            dropped.append("room:schema")
            continue
        polygon = _normalize_points(raw_room.get("polygon"))
        if _has_off_page_point(polygon):
            dropped.append("room:out_of_page")
            continue
        normalized = {**raw_room, "polygon": polygon}
        try:
            room = PlanRoom.model_validate(normalized)
        except ValidationError:
            dropped.append("room:schema")
            continue
        rooms.append(room)

    # ── symbols ────────────────────────────────────────────────────────────
    symbols: list[Any] = []
    for raw_symbol in _as_list(parsed.get("symbols")):
        if not isinstance(raw_symbol, dict):
            dropped.append("symbol:schema")
            continue
        centers = _normalize_points(raw_symbol.get("centers"))
        if isinstance(centers, list):
            # One stray centre must not take the whole class down with it.
            kept = [c for c in centers if not _has_off_page_point([c])]
            if len(kept) != len(centers):
                dropped.extend(["symbol:center_out_of_page"] * (len(centers) - len(kept)))
                centers = kept
        normalized = {**raw_symbol, "centers": centers}
        try:
            symbol = PlanSymbol.model_validate(normalized)
        except ValidationError:
            dropped.append("symbol:schema")
            continue
        symbols.append(symbol)

    result = PlanReadResult(
        page=page,
        scale=scale_obj,
        rooms=rooms,
        symbols=symbols,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
    )
    return result, dropped


def _accept_or_reject_scale(
    candidate: Any,
    page_width_pt: float,
    page_height_pt: float,
    dropped: list[str],
) -> Any | None:
    """Apply the scale plausibility belt and the inferred-confidence floor.

    Returns the (possibly confidence-clamped) scale, or ``None`` (recording a
    drop reason) when the derived ratio is implausible. A scale with no
    endpoints / no real value is kept as-is (it is a "no evidence" honest null
    or a partial the user can ignore) but never produces a ratio.
    """
    ref = candidate.ref_pixels
    real = candidate.ref_real_value
    if ref is not None and real is not None and real > 0:
        p1 = norm_to_pdf_point(ref[0].x, ref[0].y, page_width_pt, page_height_pt)
        p2 = norm_to_pdf_point(ref[1].x, ref[1].y, page_width_pt, page_height_pt)
        ratio = derive_scale_ratio(p1, p2, real, candidate.ref_unit or candidate.unit)
        if ratio is None or not scale_is_plausible(ratio, page_width_pt, page_height_pt):
            dropped.append("scale:implausible")
            return None
    clamped = clamp_inferred_confidence(candidate.source, candidate.confidence)
    if clamped != candidate.confidence:
        candidate = candidate.model_copy(update={"confidence": clamped})
    return candidate


def scale_ratio_from_plan_scale(
    scale: Any,
    page_width_pt: float,
    page_height_pt: float,
) -> float | None:
    """Derive the PDF-points-per-metre ratio for an accepted ``PlanScale``.

    Returns ``None`` when the scale carries no usable reference (an honest
    "no evidence" result), so the caller offers no auto-scale.
    """
    ref = getattr(scale, "ref_pixels", None)
    real = getattr(scale, "ref_real_value", None)
    if ref is None or real is None or real <= 0:
        return None
    p1 = norm_to_pdf_point(ref[0].x, ref[0].y, page_width_pt, page_height_pt)
    p2 = norm_to_pdf_point(ref[1].x, ref[1].y, page_width_pt, page_height_pt)
    return derive_scale_ratio(p1, p2, real, getattr(scale, "ref_unit", None) or getattr(scale, "unit", None))


def resolve_scale_ratio(
    calibrated_ratio: float | None,
    detected_scale: Any,
    page_width_pt: float,
    page_height_pt: float,
) -> tuple[float | None, str | None]:
    """Pick the ratio the proposals are measured in, plausibility belt included.

    A calibration the user drew on the canvas outranks anything the model read,
    which is the human-confirm order we want. What it lacked is the belt: a
    calibration arrives with only a "> 0" check on it, while a model-derived
    scale has already been through ``scale_is_plausible`` inside
    ``parse_plan_read_response``. The ratio is squared into every room area, so
    a calibration off by a factor of a thousand (mm entered where metres were
    meant) turns every quantity into nonsense that still reads like a number.

    An implausible calibration is dropped rather than replaced. Falling back to
    the model's scale would quietly measure the drawing at a ratio the user
    never chose; leaving the values empty says plainly that the scale has to be
    set again, and empty values are already the normal no-scale outcome.

    Args:
        calibrated_ratio: The run's ``scale_pixels_per_unit``, when the user set one.
        detected_scale: The parsed ``PlanScale``, or ``None`` when nothing was read.
        page_width_pt: Page width in PDF points.
        page_height_pt: Page height in PDF points.

    Returns:
        ``(ratio, drop_reason)``. The ratio is ``None`` when no usable scale
        survives; ``drop_reason`` names a discarded calibration for the run
        report and is ``None`` when nothing was thrown away.
    """
    if calibrated_ratio is not None:
        if scale_is_plausible(calibrated_ratio, page_width_pt, page_height_pt):
            return calibrated_ratio, None
        return None, "scale:implausible_calibration"
    if detected_scale is not None:
        return scale_ratio_from_plan_scale(detected_scale, page_width_pt, page_height_pt), None
    return None, None


def _normalize_scale_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw scale dict into the shape ``PlanScale`` expects.

    The model may return ``ref_pixels`` as a list of ``[x, y]`` pairs; convert
    those to ``{"x": .., "y": ..}`` mappings so the ``NormPoint`` schema parses
    them. A non-2-endpoint list is dropped to ``None`` so schema validation
    rejects only genuinely malformed scales.
    """
    out = dict(raw)
    ref = raw.get("ref_pixels")
    if isinstance(ref, (list, tuple)) and len(ref) == 2 and all(isinstance(p, dict) for p in ref):
        pass  # already ``{"x", "y"}`` mappings
    elif isinstance(ref, (list, tuple)) and len(ref) == 2:
        try:
            out["ref_pixels"] = [
                {"x": float(ref[0][0]), "y": float(ref[0][1])},
                {"x": float(ref[1][0]), "y": float(ref[1][1])},
            ]
        except (TypeError, ValueError, IndexError, KeyError):
            out["ref_pixels"] = None
    elif ref is not None and not (isinstance(ref, (list, tuple))):
        out["ref_pixels"] = None
    return out


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def _normalize_points(raw: Any) -> Any:
    """Coerce a list of ``[x, y]`` pairs into ``{"x": .., "y": ..}`` mappings.

    The model emits polygon / centroid vertices as ``[x, y]`` arrays; the
    ``NormPoint`` schema expects mappings. A vertex already shaped as a mapping
    (or anything we cannot read) is passed through so schema validation makes
    the final accept / reject decision (and counts the drop).
    """
    if not isinstance(raw, list):
        return raw
    out: list[Any] = []
    for pt in raw:
        if isinstance(pt, dict):
            out.append(pt)
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                out.append({"x": float(pt[0]), "y": float(pt[1])})
            except (TypeError, ValueError):
                out.append(pt)
        else:
            out.append(pt)
    return out


def _has_off_page_point(points: Any) -> bool:
    """True when a normalized point list holds a finite vertex off the page.

    Non-numeric and non-finite vertices are left to schema validation, which
    rejects them under its own reason; this only names the off-page case so the
    validation report tells a hallucinated coordinate from a malformed one.
    """
    if not isinstance(points, list):
        return False
    for pt in points:
        if not isinstance(pt, dict):
            continue
        x, y = pt.get("x"), pt.get("y")
        if not _is_real(x) or not _is_real(y):
            continue
        if math.isfinite(x) and math.isfinite(y) and not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return True
    return False


def _is_real(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ── Model-output repair before validation ────────────────────────────────────

#: A vertex this far past the page edge is a rounding overshoot and is clamped
#: onto the edge; anything further out is a coordinate the model invented.
COORD_OVERSHOOT = 0.015


def _point_pair(pt: Any) -> tuple[float, float] | None:
    if isinstance(pt, dict):
        x, y = pt.get("x"), pt.get("y")
    elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
        x, y = pt[0], pt[1]
    else:
        return None
    if not _is_real(x) or not _is_real(y):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return float(x), float(y)


def _model_point_lists(parsed: dict[str, Any]) -> list[list[Any]]:
    lists: list[list[Any]] = []
    scale = parsed.get("scale")
    if isinstance(scale, dict) and isinstance(scale.get("ref_pixels"), list):
        lists.append(scale["ref_pixels"])
    for key, name in (("rooms", "polygon"), ("symbols", "centers")):
        for item in _as_list(parsed.get(key)):
            if isinstance(item, dict) and isinstance(item.get(name), list):
                lists.append(item[name])
    return lists


def prepare_model_json(
    parsed: Any,
    *,
    image_width_px: float | None = None,
    image_height_px: float | None = None,
) -> tuple[Any, list[str]]:
    """Bring the model's coordinates into the normalized contract.

    Vision models regularly answer in image pixels or in percent although the
    prompt asks for ``[0, 1]``. When most coordinates of the response sit in one
    of those spaces the whole response is rescaled; a response that is mostly
    normalized keeps its few stray values, which validation then drops. Tiny
    overshoots past an edge are clamped onto it.

    Args:
        parsed: JSON object extracted from the model's text.
        image_width_px: Width of the image the model saw, in pixels.
        image_height_px: Height of the image the model saw, in pixels.

    Returns:
        ``(parsed, repairs)``: a rewritten copy of the object and the list of
        repairs applied (empty when nothing changed).
    """
    if not isinstance(parsed, dict):
        return parsed, []
    lists = _model_point_lists(parsed)
    values = [pair for lst in lists for pair in (_point_pair(p) for p in lst) if pair is not None]
    if not values:
        return parsed, []

    big = [v for v in values if max(abs(v[0]), abs(v[1])) > 1.0 + COORD_OVERSHOOT]
    mode = "normalized"
    if len(big) * 2 > len(values):
        max_x = max(v[0] for v in values)
        max_y = max(v[1] for v in values)
        top = max(max_x, max_y)
        if (
            image_width_px
            and image_height_px
            and top > 100.0 * (1.0 + COORD_OVERSHOOT)
            and max_x <= image_width_px * (1.0 + COORD_OVERSHOOT)
            and max_y <= image_height_px * (1.0 + COORD_OVERSHOOT)
        ):
            mode = "pixel"
        elif top <= 100.0 * (1.0 + COORD_OVERSHOOT):
            mode = "percent"

    repairs: list[str] = []
    if mode != "normalized":
        repairs.append(f"coords:{mode}_space")
    clamped = 0

    def fix(pt: Any) -> Any:
        nonlocal clamped
        pair = _point_pair(pt)
        if pair is None:
            return pt
        x, y = pair
        if mode == "pixel":
            x, y = x / float(image_width_px or 1), y / float(image_height_px or 1)
        elif mode == "percent":
            x, y = x / 100.0, y / 100.0
        cx = _clamp_overshoot(x)
        cy = _clamp_overshoot(y)
        if (cx, cy) != (x, y):
            clamped += 1
        return {"x": cx, "y": cy}

    out = dict(parsed)
    scale = parsed.get("scale")
    if isinstance(scale, dict) and isinstance(scale.get("ref_pixels"), list):
        out["scale"] = {**scale, "ref_pixels": [fix(p) for p in scale["ref_pixels"]]}
    for key, name in (("rooms", "polygon"), ("symbols", "centers")):
        items = parsed.get(key)
        if not isinstance(items, list):
            continue
        out[key] = [
            {**item, name: [fix(p) for p in item[name]]}
            if isinstance(item, dict) and isinstance(item.get(name), list)
            else item
            for item in items
        ]
    if clamped:
        repairs.append("coords:clamped_overshoot")
    return out, repairs


def _clamp_overshoot(v: float) -> float:
    if -COORD_OVERSHOOT <= v < 0.0:
        return 0.0
    if 1.0 < v <= 1.0 + COORD_OVERSHOOT:
        return 1.0
    return v


# ── Vector layer of the page ─────────────────────────────────────────────────
#
# A PDF exported from CAD carries the walls as exact vector paths. The model's
# polygons are a few percent off at best; snapping them onto those paths turns a
# rough trace into the drawing's own geometry, and the share of a polygon's
# perimeter that lies on a wall is the evidence its confidence is built from.

#: Above this many painted paths the page is a hatch- or survey-heavy sheet;
#: the refinement steps aside rather than spend the memory on it.
MAX_VECTOR_PATHS = 40_000
#: Segments shorter than this share of the page's long edge are glyph-sized
#: noise (arrow heads, hatch dashes); a wall's end cap is longer.
_MIN_SEGMENT_SHARE = 0.0015
#: Weight given to the edges of a filled path: a solid wall poche is the
#: strongest wall evidence a PDF can carry.
_FILLED_EDGE_WEIGHT = 2.0


@dataclass(frozen=True)
class VectorLayer:
    """The parts of a page's vector layer the plan-read checks consume.

    ``segments`` are straight pieces ``(x1, y1, x2, y2, weight)`` in PDF points;
    ``weight`` is the stroke width, or a strong constant for the edges of a
    filled path. ``ink`` holds sample points of every painted path (segments and
    curves) so a proposed symbol can be checked for something drawn under it.
    ``words`` are ``(x0, y0, x1, y1, text)`` boxes from the text layer.
    """

    page_width_pt: float
    page_height_pt: float
    segments: list[tuple[float, float, float, float, float]] = field(default_factory=list)
    ink: list[Point] = field(default_factory=list)
    words: list[tuple[float, float, float, float, str]] = field(default_factory=list)
    #: Outlines of dark filled paths (solid wall fills, columns), as closed rings.
    fills: list[list[Point]] = field(default_factory=list)
    #: Derived structures (wall index, raster) built once per page.
    cache: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def text(self) -> str:
        """Page text rebuilt from the word boxes, one space between words."""
        return " ".join(w[4] for w in self.words)

    def has_walls(self) -> bool:
        """True when the page has enough straight geometry to snap onto."""
        return len(self.segments) >= 8


def vector_layer_from_drawings(
    drawings: list[dict[str, Any]],
    words: list[Any],
    page_width_pt: float,
    page_height_pt: float,
) -> VectorLayer:
    """Build a :class:`VectorLayer` from ``PdfPage.drawings()`` dictionaries."""
    long_edge = max(page_width_pt, page_height_pt)
    min_len = _MIN_SEGMENT_SHARE * long_edge
    segments: list[tuple[float, float, float, float, float]] = []
    ink: list[Point] = []

    def add(p1: Any, p2: Any, weight: float) -> None:
        x1, y1, x2, y2 = float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1])
        ink.append((x1, y1))
        ink.append((x2, y2))
        length = math.hypot(x2 - x1, y2 - y1)
        if length >= min_len:
            segments.append((x1, y1, x2, y2, weight))
            # Interior samples so a long wall still counts as ink mid-span.
            steps = int(length // (min_len * 4))
            for k in range(1, steps):
                t = k / steps
                ink.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))

    fills: list[list[Point]] = []
    for path in drawings:
        fill = path.get("fill")
        stroke_w = float(path.get("width") or 0.0) if path.get("color") is not None else 0.0
        filled = fill is not None and _is_dark(fill)
        weight = max(stroke_w, _FILLED_EDGE_WEIGHT if filled else 0.0, 0.05)
        ring: list[Point] = []
        for item in path.get("items") or ():
            op = item[0]
            if op == "l":
                add(item[1], item[2], weight)
                start = (float(item[1][0]), float(item[1][1]))
                if ring and math.dist(ring[-1], start) > 1e-3:
                    if filled and len(ring) >= 3:
                        fills.append(ring)
                    ring = []
                if not ring:
                    ring.append(start)
                ring.append((float(item[2][0]), float(item[2][1])))
                continue
            if op == "re":
                r = item[1]
                corners = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
            elif op == "qu":
                q = item[1]
                corners = [q[0], q[1], q[3], q[2]]  # ul, ur, lr, ll
            else:
                if op == "c":
                    for p in item[1:5]:
                        ink.append((float(p[0]), float(p[1])))
                continue
            for i in range(4):
                add(corners[i], corners[(i + 1) % 4], weight)
            if filled:
                fills.append([(float(c[0]), float(c[1])) for c in corners])
        if filled and len(ring) >= 3:
            fills.append(ring)
    return VectorLayer(
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        segments=segments,
        ink=ink,
        fills=fills,
        words=[(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in words],
    )


def _is_dark(color: Any) -> bool:
    """True for a fill that reads as ink rather than as a white mask."""
    try:
        comps = [float(c) for c in color]
    except TypeError:
        return False
    if not comps:
        return False
    return sum(comps) / len(comps) < 0.85


def extract_vector_layer(content: bytes, page: int) -> VectorLayer | None:
    """Read the vector layer of one PDF page, or ``None`` when there is none.

    Returns ``None`` for a scanned page, a rotated page (the vector layer is on
    the unrotated page while the model saw the rotated render), a page too heavy
    to walk, or any reader failure: the refinement then runs on the model's
    geometry alone and says so through lower confidence.
    """
    try:
        from app.core import pdf_reader  # noqa: PLC0415 - lazy, same as rasterize_page

        pdf = pdf_reader.open_pdf(content)
    except Exception:  # noqa: BLE001 - any reader failure means "no vector layer"
        return None
    try:
        if page < 1 or page > pdf.page_count:
            return None
        pg = pdf[page - 1]
        if getattr(pg, "rotation", 0):
            return None
        drawings = pg.drawings()
        if len(drawings) > MAX_VECTOR_PATHS:
            return None
        words = pg.words()
        return vector_layer_from_drawings(drawings, words, float(pg.rect.width), float(pg.rect.height))
    except Exception:  # noqa: BLE001
        return None
    finally:
        pdf.close()


# ── Polygon helpers ──────────────────────────────────────────────────────────


def signed_area(points: list[Point]) -> float:
    """Shoelace area with its sign: positive when the interior is on the left."""
    n = len(points)
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def polygon_perimeter(points: list[Point]) -> float:
    """Closed-ring perimeter in the points' own unit."""
    n = len(points)
    if n < 2:
        return 0.0
    return sum(math.dist(points[i], points[(i + 1) % n]) for i in range(n))


def point_in_polygon(x: float, y: float, points: list[Point]) -> bool:
    """Even-odd point-in-polygon test."""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def polygon_iou(a: list[Point], b: list[Point], *, grid: int = 96) -> float:
    """Intersection over union of two simple polygons, sampled on a grid.

    Sampling keeps this dependency-free; at the default resolution the error is
    well under one percent of the union, far finer than any decision taken on
    it (duplicate at 0.6, a correct room at 0.85).
    """
    inter, union = _overlap_counts(a, b, grid)
    return inter / union if union else 0.0


def polygon_containment(inner: list[Point], outer: list[Point], *, grid: int = 64) -> float:
    """Share of ``inner``'s area that lies inside ``outer`` (sampled)."""
    if len(inner) < 3 or len(outer) < 3:
        return 0.0
    import numpy as np  # noqa: PLC0415 - base dependency, imported where used

    x0, y0, x1, y1 = _bbox(inner)
    xs = x0 + (np.arange(grid) + 0.5) * (x1 - x0) / grid
    ys = y0 + (np.arange(grid) + 0.5) * (y1 - y0) / grid
    gx, gy = np.meshgrid(xs, ys)
    in_i = _mask(gx, gy, inner, np)
    total = in_i.sum()
    if total == 0:
        return 0.0
    return float(np.logical_and(in_i, _mask(gx, gy, outer, np)).sum() / total)


def _overlap_counts(a: list[Point], b: list[Point], grid: int) -> tuple[float, float]:
    if len(a) < 3 or len(b) < 3:
        return 0.0, 0.0
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
        return 0.0, 1.0
    x0, y0, x1, y1 = min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1)
    import numpy as np  # noqa: PLC0415 - base dependency, imported where used

    xs = x0 + (np.arange(grid) + 0.5) * (x1 - x0) / grid
    ys = y0 + (np.arange(grid) + 0.5) * (y1 - y0) / grid
    gx, gy = np.meshgrid(xs, ys)
    in_a = _mask(gx, gy, a, np)
    in_b = _mask(gx, gy, b, np)
    return float(np.logical_and(in_a, in_b).sum()), float(np.logical_or(in_a, in_b).sum())


def _mask(gx: Any, gy: Any, poly: list[Point], np: Any) -> Any:
    inside = np.zeros(gx.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if yi != yj:
            cond = (yi > gy) != (yj > gy)
            xcross = (xj - xi) * (gy - yi) / (yj - yi) + xi
            inside ^= cond & (gx < xcross)
        j = i
    return inside


def _bbox(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _dp_simplify(points: list[Point], eps: float) -> list[Point]:
    """Douglas-Peucker on an open chain."""
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    dmax, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        d = _point_line_distance(points[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax <= eps:
        return [a, b]
    left = _dp_simplify(points[: idx + 1], eps)
    right = _dp_simplify(points[idx:], eps)
    return left[:-1] + right


def _point_line_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.dist(p, a)
    return abs(dx * (a[1] - p[1]) - dy * (a[0] - p[0])) / length


def clean_ring(points: list[Point], eps: float) -> list[Point]:
    """Drop repeated, closing and near-collinear vertices from a traced ring.

    Models pad an edge with jittered extra vertices and often repeat the first
    vertex at the end. Douglas-Peucker on the ring (split at the vertex farthest
    from the first one so both halves keep their corners) removes them without
    touching a real corner deeper than ``eps``.
    """
    pts: list[Point] = []
    for p in points:
        if not pts or math.dist(p, pts[-1]) > 1e-9:
            pts.append(p)
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= 1e-9:
        pts.pop()
    if len(pts) < 4 or eps <= 0:
        return pts
    far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
    first = _dp_simplify(pts[: far + 1], eps)
    second = _dp_simplify([*pts[far:], pts[0]], eps)
    ring = first[:-1] + second[:-1]
    return ring if len(ring) >= 3 else pts


def _drop_collinear(pts: list[Point], eps: float) -> list[Point]:
    """Remove any vertex lying within ``eps`` of the line through its neighbours."""
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            prev_pt, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            if _point_line_distance(cur, prev_pt, nxt) <= eps:
                pts = pts[:i] + pts[i + 1 :]
                changed = True
                break
    return pts


# ── Snapping a traced ring onto the vector walls ─────────────────────────────

#: Two directions closer than this are parallel for snapping purposes.
_PARALLEL_SIN = math.sin(math.radians(4.0))
_HIT_PARALLEL_SIN = math.sin(math.radians(25.0))
#: Consecutive snapped lines closer to parallel than this cannot meet in a corner.
_CORNER_SIN = math.sin(math.radians(20.0))
#: An edge needs at least this share of its length on one wall line to snap.
SNAP_MIN_COVERAGE = 0.25


@dataclass
class _WallIndex:
    """Wall-like segments of a vector layer, held as arrays for fast queries."""

    arr: Any  # (N, 5) x1, y1, x2, y2, strength in [0, 1]
    count: int


def _empty_wall_index() -> _WallIndex:
    import numpy as np  # noqa: PLC0415

    return _WallIndex(arr=np.zeros((0, 5)), count=0)


def _wall_index(vector: VectorLayer) -> _WallIndex:
    """Keep the segments heavy enough to be walls and score their strength.

    The wall weight is the length-weighted 80th percentile of all stroke weights;
    segments under 45 percent of it (hatching, furniture, dimension lines on a
    drawing with real lineweights) are left out. On a drawing exported with one
    uniform lineweight nothing is left out and the geometry alone decides.
    """
    import numpy as np  # noqa: PLC0415 - base dependency, imported where used

    if not vector.segments:
        return _WallIndex(arr=np.zeros((0, 5)), count=0)
    segs = np.asarray(vector.segments, dtype=float)
    lengths = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    weights = segs[:, 4]
    order = np.argsort(weights)
    cum = np.cumsum(lengths[order])
    wall_w = float(weights[order][np.searchsorted(cum, 0.8 * cum[-1])])
    keep = weights >= 0.45 * wall_w
    out = segs[keep].copy()
    out[:, 4] = np.minimum(1.0, out[:, 4] / max(wall_w, 1e-9))
    return _WallIndex(arr=out, count=int(keep.sum()))


@dataclass
class _EdgeSnap:
    line: tuple[float, float, float, float] | None  # px, py, dx, dy of the chosen wall face
    coverage: float
    rho: float | None


def _snap_edge(
    a: Point,
    b: Point,
    in_sign: float,
    walls: _WallIndex,
    *,
    tol: float,
    max_wall: float,
    min_wall: float,
    hits: Any = None,
    hit_tol: float = 0.0,
    hit_samples: int = 0,
) -> _EdgeSnap:
    """Pick the wall line edge ``a-b`` belongs on.

    With ``hits`` (points where walks out of the room met a wall line) the line
    most of them landed on wins, the outermost when a counter front competes;
    without them geometry decides: the inner face of a wall pair, best covered
    and nearest.
    """
    import numpy as np  # noqa: PLC0415 - base dependency, imported where used

    length = math.dist(a, b)
    if length <= 1e-9 or (walls.count == 0 and not (hits is not None and len(hits))):
        return _EdgeSnap(line=None, coverage=0.0, rho=None)
    dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    nx, ny = -dy, dx
    rho_e = nx * a[0] + ny * a[1]
    s = walls.arr
    sx, sy = s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]
    sl = np.hypot(sx, sy)
    cross = np.abs(dx * sy - dy * sx) / np.maximum(sl, 1e-12)
    rho_s = nx * (s[:, 0] + s[:, 2]) / 2 + ny * (s[:, 1] + s[:, 3]) / 2
    window = tol + max_wall
    t1 = dx * (s[:, 0] - a[0]) + dy * (s[:, 1] - a[1])
    t2 = dx * (s[:, 2] - a[0]) + dy * (s[:, 3] - a[1])
    lo = np.maximum(np.minimum(t1, t2), 0.0)
    hi = np.minimum(np.maximum(t1, t2), length)
    # Hits pin the face down, so a trace tilted by its jitter may still find it.
    parallel = _HIT_PARALLEL_SIN if hits is not None and len(hits) else _PARALLEL_SIN
    sel = (cross <= parallel) & (np.abs(rho_s - rho_e) <= window) & (hi - lo > 0)
    idx = np.nonzero(sel)[0]

    # Cluster the candidate segments into wall lines by offset.
    clusters: list[dict[str, Any]] = []
    for k in idx[np.argsort(rho_s[idx])]:
        r = float(rho_s[k])
        if clusters and r - clusters[-1]["rho_max"] <= max(0.6, min_wall * 0.5):
            c = clusters[-1]
        else:
            c = {"rho_sum": 0.0, "w_sum": 0.0, "rho_max": r, "iv": [], "best": k, "strength": 0.0}
            clusters.append(c)
        seg_len = float(sl[k])
        c["rho_sum"] += r * seg_len
        c["w_sum"] += seg_len
        c["rho_max"] = r
        c["iv"].append((float(lo[k]), float(hi[k])))
        c["strength"] = max(c["strength"], float(s[k, 4]))
        if seg_len > float(sl[c["best"]]):
            c["best"] = k
    for c in clusters:
        c["rho"] = c["rho_sum"] / c["w_sum"]
        c["cov"] = _union_length(c["iv"]) / length
        c["inward"] = (c["rho"] - rho_e) * in_sign

    def on_line(best: dict[str, Any]) -> _EdgeSnap:
        k = best["best"]
        ux, uy = float(sx[k]) / float(sl[k]), float(sy[k]) / float(sl[k])
        if ux * dx + uy * dy < 0:
            ux, uy = -ux, -uy
        # Along the cluster's longest segment itself: a tilted trace must not
        # shift or tilt the face it lands on.
        line = (float(s[k, 0]), float(s[k, 1]), ux, uy)
        return _EdgeSnap(line=line, coverage=min(1.0, best["cov"]) * best["strength"], rho=best["rho"])

    if hits is not None and len(hits):
        hp = np.asarray(hits, dtype=float)
        voted = []
        for c in clusters:
            k = c["best"]
            ux, uy = float(sx[k]) / float(sl[k]), float(sy[k]) / float(sl[k])
            d = np.abs((hp[:, 0] - s[k, 0]) * uy - (hp[:, 1] - s[k, 1]) * ux)
            votes = int((d <= hit_tol).sum())
            if votes >= 2:
                voted.append((votes, -c["inward"], c))
        if voted:
            need = max(2, 0.25 * len(hp))
            agreed = [v for v in voted if v[0] >= need] or [max(voted, key=lambda v: v[0])]
            return on_line(max(agreed, key=lambda v: v[1])[2])
        if len(hp) >= 3:
            # No drawn line takes the hits (a filled wall's curved face): the
            # face is where the walks stopped.
            centre = hp.mean(axis=0)
            _u, _sv, vt = np.linalg.svd(hp - centre)
            ux, uy = float(vt[0, 0]), float(vt[0, 1])
            if ux * dx + uy * dy < 0:
                ux, uy = -ux, -uy
            if abs(ux * dy - uy * dx) <= _HIT_PARALLEL_SIN:
                # No drawn line confirms it, so it counts for less than one.
                share = min(1.0, len(hp) / max(1.0, hit_samples))
                return _EdgeSnap(line=(float(centre[0]), float(centre[1]), ux, uy), coverage=0.6 * share, rho=None)
    strong = [c for c in clusters if c["cov"] >= SNAP_MIN_COVERAGE]
    if not strong:
        return _EdgeSnap(line=None, coverage=0.0, rho=None)

    def has_partner(c: dict[str, Any], *, outward: bool) -> bool:
        for o in strong:
            if o is c:
                continue
            gap = (c["inward"] - o["inward"]) if outward else (o["inward"] - c["inward"])
            if min_wall <= gap <= max_wall:
                return True
        return False

    # The outer face of a wall pair is never the room's boundary: the room
    # lies on the inner side of the inner face.
    options = [c for c in strong if has_partner(c, outward=True) or not has_partner(c, outward=False)]
    options = [c for c in options if abs(c["rho"] - rho_e) <= window]
    if not options:
        return _EdgeSnap(line=None, coverage=0.0, rho=None)
    return on_line(max(options, key=lambda c: c["cov"] * c["strength"] - 0.6 * abs(c["rho"] - rho_e) / window))


def _union_length(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    cur_lo = cur_hi = None
    for lo, hi in sorted(intervals):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                total += cur_hi - cur_lo  # type: ignore[operator]
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        total += cur_hi - cur_lo  # type: ignore[operator]
    return total


def _intersect(l1: tuple[float, float, float, float], l2: tuple[float, float, float, float]) -> Point | None:
    p1x, p1y, d1x, d1y = l1
    p2x, p2y, d2x, d2y = l2
    den = d1x * d2y - d1y * d2x
    if abs(den) < _CORNER_SIN:
        return None
    t = ((p2x - p1x) * d2y - (p2y - p1y) * d2x) / den
    return (p1x + d1x * t, p1y + d1y * t)


def _project(p: Point, line: tuple[float, float, float, float]) -> Point:
    px, py, dx, dy = line
    t = (p[0] - px) * dx + (p[1] - py) * dy
    return (px + dx * t, py + dy * t)


def _align_to_axis(ex: float, ey: float, axis: float | None) -> tuple[float, float]:
    if axis is None:
        return ex, ey
    best = None
    for k in range(4):
        th = axis + k * math.pi / 2
        ux, uy = math.cos(th), math.sin(th)
        dot = ux * ex + uy * ey
        if best is None or dot > best[0]:
            best = (dot, ux, uy)
    if best[0] >= math.cos(math.radians(25.0)):  # type: ignore[index]
        return best[1], best[2]  # type: ignore[index]
    return ex, ey


@dataclass
class RingSnap:
    """Outcome of snapping one traced ring onto the vector walls."""

    points: list[Point]
    support: float  # perimeter share on a wall line, weighted by wall strength
    snapped: bool  # the snapped geometry passed its own checks and was adopted
    edges_snapped: int
    crosses_wall: bool = False  # a wall runs through the ring's core: two rooms read as one


def snap_ring_to_walls(
    points: list[Point],
    walls: _WallIndex,
    *,
    tol: float,
    max_wall: float,
    min_wall: float,
    raster: WallRaster | None = None,
) -> RingSnap:
    """Move each edge of a traced ring onto the wall face it follows.

    Each edge looks for parallel wall lines within ``tol + max_wall`` of it,
    discards the outer face of any wall pair, and adopts the best-covered,
    nearest remaining face. Corners are rebuilt as intersections of adjacent
    snapped lines. The snapped ring is adopted only when it stays simple, keeps
    its area within a plausible band and moves no vertex absurdly far; otherwise
    the model's ring is kept and only the support figure is reported.
    """
    n = len(points)
    sa = signed_area(points)
    if n < 3 or sa == 0:
        return RingSnap(points=points, support=0.0, snapped=False, edges_snapped=0)
    in_sign = 1.0 if sa > 0 else -1.0
    x0, y0, x1, y1 = _bbox(points)
    start = min(tol + max_wall, 0.3 * min(x1 - x0, y1 - y0))
    region = raster.room_region(points, grow=tol + max_wall, shrink=tol + max_wall) if raster is not None else None
    snaps = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        hits = None
        n_walks = 0
        if region is not None:
            length = math.dist(a, b) or 1.0
            ex, ey = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            # Walk square to the plan's wall grid, not to a trace tilted by jitter.
            ex, ey = _align_to_axis(ex, ey, raster.axis)  # type: ignore[union-attr]
            nx, ny = -ey, ex
            # Outward is against the inward normal.
            found, share = region.face_hits(a, b, -in_sign * nx, -in_sign * ny, start=start, reach=tol + max_wall)
            if share >= 0.3:
                hits = found
                n_walks = round(len(found) / share)
        snaps.append(
            _snap_edge(
                a,
                b,
                in_sign,
                walls,
                tol=tol,
                max_wall=max_wall,
                min_wall=min_wall,
                hits=hits,
                hit_tol=2.0 * raster.cell if raster is not None else 0.0,
                hit_samples=n_walks,
            )
        )
    lengths = [math.dist(points[i], points[(i + 1) % n]) for i in range(n)]
    perim = sum(lengths) or 1.0
    support = sum(s.coverage * length for s, length in zip(snaps, lengths, strict=True)) / perim
    edges_snapped = sum(1 for s in snaps if s.line is not None)
    if edges_snapped == 0:
        return RingSnap(points=points, support=support, snapped=False, edges_snapped=0)

    lines: list[tuple[float, float, float, float]] = []
    for i, s in enumerate(snaps):
        if s.line is not None:
            lines.append(s.line)
        else:
            a, b = points[i], points[(i + 1) % n]
            length = lengths[i] or 1.0
            lines.append((a[0], a[1], (b[0] - a[0]) / length, (b[1] - a[1]) / length))

    out: list[Point] = []
    for i in range(n):
        prev_line, line = lines[i - 1], lines[i]
        corner = _intersect(prev_line, line)
        if corner is None:
            same_wall = (
                snaps[i - 1].rho is not None
                and snaps[i].rho is not None
                and abs(snaps[i - 1].rho - snaps[i].rho) <= 1.0  # type: ignore[operator]
            )
            if same_wall:
                continue
            p1, p2 = _project(points[i], prev_line), _project(points[i], line)
            corner = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        out.append(corner)

    if len(out) < 3 or polygon_self_intersects(out):
        return RingSnap(points=points, support=support, snapped=False, edges_snapped=edges_snapped)
    ratio = shoelace_area(out) / (abs(sa) or 1.0)
    reach = 1.5 * (tol + max_wall)
    moved = max(min(math.dist(p, q) for q in points) for p in out)
    if not 0.5 <= ratio <= 1.6 or moved > reach:
        return RingSnap(points=points, support=support, snapped=False, edges_snapped=edges_snapped)
    crosses = region is not None and region.wall_through(out, depth=2 * max_wall)
    return RingSnap(points=out, support=support, snapped=True, edges_snapped=edges_snapped, crosses_wall=crosses)


#: Grid resolution of the wall raster: cells along the page's long edge.
RASTER_CELLS = 2400
#: Enclosed pockets inside a ring that make it a hatched floor, not a wall cavity.
HATCH_MIN_TILES = 6


class WallRaster:
    """Wall lines burnt into a grid, to find the face at which a room really ends.

    Snapping by geometry alone cannot tell a wall's inner face from its outer
    face, a counter front or a hatch line. The raster answers that by walking
    from inside the traced room outwards until the room's free space ends.
    """

    def __init__(
        self, walls: _WallIndex, width_pt: float, height_pt: float, fills: list[list[Point]] | None = None
    ) -> None:
        import cv2  # noqa: PLC0415 - base dependency, heavy import kept off module load
        import numpy as np  # noqa: PLC0415

        self.cell = max(width_pt, height_pt) / RASTER_CELLS
        self.grid = np.zeros((int(height_pt / self.cell) + 3, int(width_pt / self.cell) + 3), np.uint8)
        if walls.count:
            ends = np.round(walls.arr[:, :4] / self.cell).astype(np.int32).reshape(-1, 2, 2)
            cv2.polylines(self.grid, list(ends), False, 1, 1, cv2.LINE_8)
        if fills:
            cv2.fillPoly(self.grid, [np.round(np.asarray(f) / self.cell).astype(np.int32) for f in fills], 1)
        self._network: Any = None
        # Main wall direction (radians, mod pi/2): plans are mostly orthogonal.
        self.axis: float | None = None
        if walls.count:
            a = walls.arr
            ang = np.mod(np.arctan2(a[:, 3] - a[:, 1], a[:, 2] - a[:, 0]), math.pi / 2)
            hist, edges = np.histogram(
                ang, bins=90, range=(0, math.pi / 2), weights=np.hypot(a[:, 2] - a[:, 0], a[:, 3] - a[:, 1])
            )
            k = int(np.argmax(hist))
            self.axis = float((edges[k] + edges[k + 1]) / 2)

    def network_of(self, ring: list[Point]) -> int:
        """Id of the connected wall network the ring's edges run along (0: none).

        Rooms of one building share one network; a frame or a title block is
        drawn apart from it, so a ring traced there lands on another network.
        """
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        if self._network is None:
            # Wall pieces split by openings or drawn as separate fills touch only
            # nearly; a gap of a few tenths of a percent of the sheet joins them.
            k = 2 * max(2, RASTER_CELLS // 400) + 1
            joined = cv2.dilate(self.grid, np.ones((k, k), np.uint8))
            _n, self._network = cv2.connectedComponents(joined, connectivity=8)
        labels = self._network
        h, w = labels.shape
        votes: dict[int, int] = {}
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            for t in np.linspace(0.1, 0.9, 9):
                x = round((a[0] + (b[0] - a[0]) * t) / self.cell)
                y = round((a[1] + (b[1] - a[1]) * t) / self.cell)
                if 0 <= x < w and 0 <= y < h and labels[y, x]:
                    votes[int(labels[y, x])] = votes.get(int(labels[y, x]), 0) + 1
        return max(votes, key=lambda k: votes[k]) if votes else 0

    def frame_networks(self) -> set[int]:
        """Networks spanning nearly the whole sheet: the frame and its title block."""
        import numpy as np  # noqa: PLC0415

        if self._network is None:
            self.network_of([(0.0, 0.0)] * 3)
        if "frames" not in self.__dict__:
            h, w = self._network.shape
            ys, xs = np.nonzero(self._network)
            labels = self._network[ys, xs]
            out: set[int] = set()
            for n in np.unique(labels):
                sel = labels == n
                if np.ptp(xs[sel]) >= 0.9 * w and np.ptp(ys[sel]) >= 0.9 * h:
                    out.add(int(n))
            self.__dict__["frames"] = out
        return self.__dict__["frames"]

    def near_wall(self, p: Point, reach: float) -> bool:
        """Whether a building wall (not the sheet frame) passes within ``reach`` of ``p``."""
        import numpy as np  # noqa: PLC0415

        frames = self.frame_networks()
        r = max(1, round(reach / self.cell))
        x, y = round(p[0] / self.cell), round(p[1] / self.cell)
        h, w = self._network.shape
        if not (0 <= x < w and 0 <= y < h):
            return False
        window = self._network[max(0, y - r) : y + r + 1, max(0, x - r) : x + r + 1]
        found = np.unique(window)
        return any(int(n) and int(n) not in frames for n in found)

    @classmethod
    def from_image(cls, png: bytes, width_pt: float, height_pt: float) -> WallRaster | None:
        """Raster of a scanned sheet: its dark pixels stand in for drawn lines."""
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            return None
        out = cls(_empty_wall_index(), width_pt, height_pt)
        h, w = out.grid.shape
        dark = (img < 110).astype(np.uint8) * 255
        scaled = cv2.resize(
            dark, (round(width_pt / out.cell), round(height_pt / out.cell)), interpolation=cv2.INTER_AREA
        )
        out.grid[: scaled.shape[0], : scaled.shape[1]] = (scaled[:h, :w] >= 64).astype(np.uint8)
        return out

    def room_region(self, ring: list[Point], *, grow: float, shrink: float) -> _Region | None:
        """Free space of the traced room, clipped to the ring grown by ``grow``.

        A free component belongs to the room when it reaches the ring shrunk by
        ``shrink``; the shrink is deep so that a ring traced over a wall cannot
        claim the cavity of an outlined wall. Enclosed furniture is filled in.
        """
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        c = self.cell
        x0, y0, x1, y1 = _bbox(ring)
        pad = grow + 3 * c
        i0, j0 = max(0, int((x0 - pad) / c)), max(0, int((y0 - pad) / c))
        i1 = min(self.grid.shape[1], int((x1 + pad) / c) + 2)
        j1 = min(self.grid.shape[0], int((y1 + pad) / c) + 2)
        if i1 - i0 < 3 or j1 - j0 < 3:
            return None
        sub = self.grid[j0:j1, i0:i1]
        poly = np.round(np.asarray(ring) / c - [i0, j0]).astype(np.int32)
        inside = np.zeros(sub.shape, np.uint8)
        cv2.fillPoly(inside, [poly], 1)
        g = max(1, round(grow / c))
        grown = cv2.dilate(inside, np.ones((2 * g + 1, 2 * g + 1), np.uint8))
        seed = inside
        for depth in (shrink, shrink / 2, shrink / 4):
            s = max(1, round(depth / c))
            eroded = cv2.erode(inside, np.ones((2 * s + 1, 2 * s + 1), np.uint8))
            if eroded.any():
                seed = eroded
                break
        free = ((sub == 0) & (grown > 0)).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
        if n <= 1:
            return None
        keep = np.bincount(labels[(seed > 0) & (free > 0)], minlength=n) > 0
        # Tiles of a hatched floor are walled off from the seed but lie inside
        # the ring. They come by the dozen; a lone compact pocket is more often a
        # stretch of wall cavity, which must stay outside.
        total = stats[:, cv2.CC_STAT_AREA]
        within = np.bincount(labels[inside > 0], minlength=n)
        bw, bh = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
        is_compact = np.minimum(bw, bh) >= 0.5 * np.maximum(bw, bh)
        compact = [int(k) for k in np.nonzero(~keep & (within >= 0.3 * total) & is_compact)[0] if k]
        tiles = [k for k in compact if within[k] >= 0.9 * total[k]]
        if len(tiles) >= HATCH_MIN_TILES:
            # Tiles the trace cuts through at the room's edge belong too.
            size = float(np.median(total[tiles]))
            keep[[k for k in compact if 0.2 * size <= total[k] <= 1.5 * size]] = True
            keep[tiles] = True
        keep[0] = False
        region = keep[labels].astype(np.uint8)
        if not region.any():
            return None
        region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        # Fill furniture islands, but not a wall piece the room's space flowed
        # around through openings: an island sits well inside the ring.
        filled = region.copy()
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(filled, contours, -1, 1, thickness=-1)
        holes = ((filled > 0) & (region == 0)).astype(np.uint8)
        if holes.any():
            nh, hl = cv2.connectedComponents(holes, connectivity=8)
            t = max(1, round(shrink / (2 * c)))
            core = cv2.erode(inside, np.ones((2 * t + 1, 2 * t + 1), np.uint8))
            island = np.bincount(hl[core > 0], minlength=nh) >= 0.9 * np.bincount(hl.ravel(), minlength=nh)
            island[0] = False
            region = (region | island[hl]).astype(np.uint8)
        return _Region(region=region, wall=sub, grown=grown, i0=i0, j0=j0, cell=c)


@dataclass
class _Region:
    region: Any
    wall: Any
    grown: Any
    i0: int
    j0: int
    cell: float

    def wall_through(self, ring: list[Point], *, depth: float) -> bool:
        """Whether something walled off from the room spans the ring's core.

        The core is the ring shrunk by ``depth``. Furniture is filled in and
        hatching is part of the room, so what remains blocked deep inside and
        runs across most of the core is a wall: the ring covers two rooms, or an
        L-shaped room traced as its bounding box.
        """
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        c = self.cell
        poly = np.round(np.asarray(ring) / c - [self.i0, self.j0]).astype(np.int32)
        core = np.zeros(self.region.shape, np.uint8)
        cv2.fillPoly(core, [poly], 1)
        d = max(1, round(depth / c))
        core = cv2.erode(core, np.ones((2 * d + 1, 2 * d + 1), np.uint8))
        if not core.any():
            return False
        blocked = ((core > 0) & (self.region == 0)).astype(np.uint8)
        if not blocked.any():
            return False
        ys, xs = np.nonzero(core)
        span_x, span_y = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        n, labels, stats, _ = cv2.connectedComponentsWithStats(blocked, connectivity=8)
        for k in range(1, n):
            w, h = stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]
            if w >= 0.6 * span_x or h >= 0.6 * span_y:
                return True
        return False

    def face_hits(
        self, a: Point, b: Point, out_x: float, out_y: float, *, start: float, reach: float
    ) -> tuple[list[Point], float]:
        """Points where walks out of the room across edge ``a-b`` meet a wall line.

        Samples the middle of the edge and walks each sample outwards from
        ``start`` inside the room until the room's space ends. A walk that ends
        on a wall line yields a hit; one that ends in open space (a door, an
        open-plan boundary) does not. Returns ``(hits, share of walks that hit)``.
        """
        import numpy as np  # noqa: PLC0415

        c = self.cell
        n_samples = max(5, min(41, int(math.dist(a, b) / (4 * c))))
        u = np.linspace(0.08, 0.92, n_samples)
        bx = a[0] + (b[0] - a[0]) * u
        by = a[1] + (b[1] - a[1]) * u
        steps = np.arange(-start, reach + c, c / 2)
        px = bx[:, None] + out_x * steps[None, :]
        py = by[:, None] + out_y * steps[None, :]
        ix = np.round(px / c).astype(int) - self.i0
        iy = np.round(py / c).astype(int) - self.j0
        h, w = self.region.shape
        ok = (ix >= 0) & (iy >= 0) & (ix < w) & (iy < h)
        ixc, iyc = np.clip(ix, 0, w - 1), np.clip(iy, 0, h - 1)
        reg = (self.region[iyc, ixc] > 0) & ok
        wall = (self.wall[iyc, ixc] > 0) & ok
        hits: list[Point] = []
        for k in range(n_samples):
            if not reg[k, 0]:
                continue
            out = np.nonzero(~reg[k])[0]
            if out.size == 0:
                continue
            stop = int(out[0])
            ahead = wall[k, stop : stop + 4]
            if ahead.any():
                m = min(stop + int(np.argmax(ahead)), len(steps) - 1)
                hits.append((float(px[k, m]), float(py[k, m])))
        return hits, len(hits) / n_samples


# ── Scale evidence from the sheet itself ─────────────────────────────────────

_POINTS_PER_METRE = _POINTS_PER_INCH / 0.0254
_DIM_NUMBER_RE = re.compile(r"^(\d{1,6})(?:[.,](\d{1,3}))?$")
_FT_IN_RE = re.compile(r"^(\d{1,4})'(?:\s*-?\s*(\d{1,2}(?:\.\d+)?)\"?)?$")
#: Ratios within this relative distance are the same scale.
_SCALE_AGREE = 0.02


def length_text_options(text: str) -> list[float]:
    """Possible real lengths in metres a dimension text can stand for.

    ``4.10`` / ``4,10`` read as metres; a bare integer as millimetres or
    centimetres (the drawing's other dimensions decide which); ``12'-6"`` as
    feet and inches. Text that is not a length returns an empty list.
    """
    t = text.strip().replace("’", "'").replace("′", "'").replace("”", '"').replace("″", '"')
    m = _FT_IN_RE.match(t)
    if m:
        feet = float(m.group(1))
        inches = float(m.group(2) or 0.0)
        return [feet * 0.3048 + inches * 0.0254]
    m = _DIM_NUMBER_RE.match(t)
    if not m:
        return []
    if m.group(2) is not None:
        value = float(f"{m.group(1)}.{m.group(2)}")
        return [value] if value > 0 else []
    value = float(m.group(1))
    if value < 10:
        return []
    return [value / 1000.0, value / 100.0]


def dimension_scale(vector: VectorLayer) -> tuple[float, int] | None:
    """Scale (PDF points per metre) read from the sheet's own dimension lines.

    Every text that reads as a length is paired with the nearest parallel line
    it is written along; the line's length over the text's value is one scale
    vote. The largest group of agreeing votes wins, which also settles whether
    bare integers are millimetres or centimetres. Two agreeing dimensions are
    the minimum; a lone number next to a line is not evidence.

    Returns:
        ``(ratio, votes)`` or ``None`` when no two dimensions agree.
    """
    if not vector.words or not vector.segments:
        return None
    import numpy as np  # noqa: PLC0415 - base dependency, imported where used

    segs = np.asarray(vector.segments, dtype=float)
    sx, sy = segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]
    sl = np.hypot(sx, sy)
    horiz = np.abs(sy) <= 0.02 * sl
    vert = np.abs(sx) <= 0.02 * sl
    votes: list[tuple[float, float]] = []  # (ratio, value in metres)
    for x0, y0, x1, y1, text in vector.words:
        options = length_text_options(text)
        if not options:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        if w >= h * 0.8:
            th = h
            lo_x, hi_x = np.minimum(segs[:, 0], segs[:, 2]), np.maximum(segs[:, 0], segs[:, 2])
            ok = horiz & (lo_x <= cx) & (hi_x >= cx)
            dist = np.abs((segs[:, 1] + segs[:, 3]) / 2 - cy)
        else:
            th = w
            lo_y, hi_y = np.minimum(segs[:, 1], segs[:, 3]), np.maximum(segs[:, 1], segs[:, 3])
            ok = vert & (lo_y <= cy) & (hi_y >= cy)
            dist = np.abs((segs[:, 0] + segs[:, 2]) / 2 - cx)
        ok &= (dist <= 2.5 * th) & (sl >= 3 * th)
        idx = np.nonzero(ok)[0]
        if idx.size == 0:
            continue
        k = idx[np.argmin(dist[idx])]
        votes.extend((float(sl[k]) / v, v) for v in options)
    if len(votes) < 2:
        return None
    votes.sort()
    groups: list[list[tuple[float, float]]] = []
    for i, (r, _v) in enumerate(votes):
        groups.append([u for u in votes[i:] if u[0] <= r * (1 + _SCALE_AGREE)])

    def rank(group: list[tuple[float, float]]) -> tuple[int, int]:
        # Bare integers agree as millimetres and as centimetres alike; the
        # reading whose lengths look like rooms and buildings wins the tie.
        values = sorted(v for _r, v in group)
        typical = 0.5 <= values[len(values) // 2] <= 30.0
        return len(group), int(typical)

    top = max(len(g) for g in groups)
    contenders = [g for g in groups if len(g) >= max(2, 0.6 * top)]
    if not contenders:
        return None
    best = max(contenders, key=lambda g: (rank(g)[1], rank(g)[0]))
    ratio = float(np.median([r for r, _v in best]))
    if not scale_is_plausible(ratio, vector.page_width_pt, vector.page_height_pt):
        return None
    return ratio, len(best)


def declared_scale(vector: VectorLayer) -> float | None:
    """Scale (PDF points per metre) from a ``1:N`` note on the sheet, if any."""
    text = vector.text
    if not text:
        return None
    try:
        from app.modules.takeoff.scale_detect import detect_best_scale  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    best, _ranked = detect_best_scale([{"page": 1, "text": text}])
    if best is None or not best.ratio:
        return None
    ratio = _POINTS_PER_METRE / float(best.ratio)
    if not scale_is_plausible(ratio, vector.page_width_pt, vector.page_height_pt):
        return None
    return ratio


def _value_on_sheet(vector: VectorLayer, metres: float) -> bool:
    for w in vector.words:
        for v in length_text_options(w[4]):
            if abs(v - metres) <= 0.005 * metres + 1e-9:
                return True
    return False


def _snap_reference(vector: VectorLayer, p1: Point, p2: Point) -> float | None:
    """Length of the drawn line whose ends match the model's reference ends."""
    reach = 0.015 * max(vector.page_width_pt, vector.page_height_pt)
    best: tuple[float, float] | None = None
    for x1, y1, x2, y2, _w in vector.segments:
        d = min(
            max(math.dist(p1, (x1, y1)), math.dist(p2, (x2, y2))),
            max(math.dist(p1, (x2, y2)), math.dist(p2, (x1, y1))),
        )
        if d <= reach and (best is None or d < best[0]):
            best = (d, math.hypot(x2 - x1, y2 - y1))
    return best[1] if best else None


@dataclass
class ScaleDecision:
    """The scale the proposals are measured in, with its evidence."""

    ratio: float | None
    confidence: float
    source: str | None  # inherited | page_text | vision_read
    flags: list[str] = field(default_factory=list)


def _agree(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(a, b)


def decide_scale(
    calibrated_ratio: float | None,
    model_scale: Any,
    vector: VectorLayer | None,
    page_width_pt: float,
    page_height_pt: float,
) -> ScaleDecision:
    """Pick the scale from the user's calibration, the sheet and the model.

    Order of trust: a plausible user calibration; the sheet's own dimension
    lines; a ``1:N`` note on the sheet; the model's reference. The model's
    reading is checked against the sheet: its endpoints are snapped onto the
    drawn dimension line when there is one, and a value that appears nowhere in
    the sheet's text marks the reading as unsupported. Disagreements are kept as
    flags and lower the confidence; they never silently pick a side.
    """
    flags: list[str] = []
    if calibrated_ratio is not None:
        if scale_is_plausible(calibrated_ratio, page_width_pt, page_height_pt):
            return ScaleDecision(ratio=calibrated_ratio, confidence=1.0, source="inherited")
        flags.append("scale:implausible_calibration")
        return ScaleDecision(ratio=None, confidence=0.0, source=None, flags=flags)

    model_ratio: float | None = None
    model_conf = 0.0
    verified = False
    if model_scale is not None:
        model_ratio = scale_ratio_from_plan_scale(model_scale, page_width_pt, page_height_pt)
        model_conf = float(getattr(model_scale, "confidence", 0.0) or 0.0)
        if model_ratio is not None and vector is not None and vector.words:
            real_m = unit_to_metres(
                float(model_scale.ref_real_value),
                getattr(model_scale, "ref_unit", None) or getattr(model_scale, "unit", None),
            )
            ref = model_scale.ref_pixels
            p1 = norm_to_pdf_point(ref[0].x, ref[0].y, page_width_pt, page_height_pt)
            p2 = norm_to_pdf_point(ref[1].x, ref[1].y, page_width_pt, page_height_pt)
            if _value_on_sheet(vector, real_m):
                verified = True
                drawn = _snap_reference(vector, p1, p2)
                if drawn is not None and _agree(drawn / real_m, model_ratio, 0.15):
                    model_ratio = drawn / real_m
                    flags.append("scale:reference_snapped")
            else:
                flags.append("scale:value_not_on_sheet")

    dim = decl = None
    if vector is not None:
        if "scale" not in vector.cache:
            vector.cache["scale"] = (dimension_scale(vector), declared_scale(vector))
        dim, decl = vector.cache["scale"]

    if dim is not None:
        ratio, votes = dim
        conf = 0.9 if votes >= 3 else 0.8
        if decl is not None and _agree(decl, ratio, _SCALE_AGREE):
            conf = 0.97
        if model_ratio is not None:
            if _agree(model_ratio, ratio, 0.06):
                conf = max(conf, 0.95)
            else:
                flags.append("scale:model_disagrees_with_sheet")
        return ScaleDecision(ratio=ratio, confidence=conf, source="page_text", flags=flags)

    if decl is not None:
        if model_ratio is not None and _agree(model_ratio, decl, 0.08):
            return ScaleDecision(ratio=decl, confidence=0.92, source="page_text", flags=flags)
        if model_ratio is not None and verified:
            flags.append("scale:note_disagrees_with_dimension")
            return ScaleDecision(ratio=model_ratio, confidence=0.5, source="vision_read", flags=flags)
        if model_ratio is not None:
            flags.append("scale:model_disagrees_with_sheet")
        return ScaleDecision(ratio=decl, confidence=0.8, source="page_text", flags=flags)

    if model_ratio is None:
        return ScaleDecision(ratio=None, confidence=0.0, source=None, flags=flags)
    if "scale:value_not_on_sheet" in flags:
        conf = min(model_conf, 0.35)
    elif verified:
        conf = min(model_conf, 0.85 if "scale:reference_snapped" in flags else 0.7)
    else:
        # A raster page: nothing on the sheet can confirm the reading.
        conf = min(model_conf, 0.6)
    if getattr(model_scale, "source", None) == "inferred":
        conf = min(conf, INFERRED_SCALE_MAX_CONFIDENCE)
    return ScaleDecision(ratio=model_ratio, confidence=conf, source="vision_read", flags=flags)


# ── Refinement: the deterministic belt between the model and a proposal ──────

#: Rooms whose overlap exceeds this IoU are the same room proposed twice.
DUPLICATE_IOU = 0.6
#: A room whose area lies this much inside a bigger room overlaps it.
_CONTAINED_SHARE = 0.8
#: Share of a room's perimeter on drawn walls below which, on a page that has
#: walls, the room is not on the drawing at all.
MIN_WALL_SUPPORT = 0.2
#: Ceiling for geometry the page cannot confirm (raster pages).
UNVERIFIED_ROOM_MAX_CONFIDENCE = 0.55
_AREA_LABEL_RE = re.compile(r"(\d{1,5}(?:[.,]\d{1,3})?)\s*(m²|m2|qm|sqm|sq\.?\s?m)\b", re.IGNORECASE)
_SQFT_LABEL_RE = re.compile(r"(\d{1,6}(?:[.,]\d{1,2})?)\s*(sf|sq\.?\s?ft|ft²|ft2)\b", re.IGNORECASE)
_SQFT_TO_M2 = 0.09290304


@dataclass
class RefinedRoom:
    """A room after the belt: geometry in PDF points plus its evidence."""

    name: str
    points: list[Point]
    model_confidence: float
    confidence: float
    verdict: str  # ok | warning | error
    flags: list[str] = field(default_factory=list)
    wall_support: float | None = None
    snapped: bool = False
    area_label_m2: float | None = None


@dataclass
class RefinedSymbol:
    """A symbol class after the belt: deduplicated centres in PDF points."""

    element_class: str
    centers: list[Point]
    confidence: float
    flags: list[str] = field(default_factory=list)


@dataclass
class PlanRefinement:
    """Everything the service persists from one plan-read call."""

    scale: ScaleDecision
    rooms: list[RefinedRoom] = field(default_factory=list)
    symbols: list[RefinedSymbol] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def _label_lines(vector: VectorLayer) -> list[tuple[float, float, str]]:
    """Group words into text lines: ``(cx, cy, text)`` per line."""
    lines: list[list[tuple[float, float, float, float, str]]] = []
    for w in sorted(vector.words, key=lambda w: (w[0], w[1])):
        cy = (w[1] + w[3]) / 2
        h = max(w[3] - w[1], 1e-6)
        for ln in lines:
            last = ln[-1]
            if abs((last[1] + last[3]) / 2 - cy) <= 0.4 * h and -0.2 * h <= w[0] - last[2] <= 1.5 * h:
                ln.append(w)
                break
        else:
            lines.append([w])
    out = []
    for ln in lines:
        x0 = min(w[0] for w in ln)
        x1 = max(w[2] for w in ln)
        y0 = min(w[1] for w in ln)
        y1 = max(w[3] for w in ln)
        out.append(((x0 + x1) / 2, (y0 + y1) / 2, " ".join(w[4] for w in ln)))
    return out


def _area_label(text: str) -> float | None:
    m = _AREA_LABEL_RE.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    m = _SQFT_LABEL_RE.search(text)
    if m:
        return float(m.group(1).replace(",", "")) * _SQFT_TO_M2
    return None


def _canonical_class(name: str) -> str:
    s = re.sub(r"\s+", " ", (name or "").strip().lower())
    if len(s) > 3 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def refine_plan_read(
    result: Any,
    *,
    page_width_pt: float,
    page_height_pt: float,
    vector: VectorLayer | None = None,
    calibrated_ratio: float | None = None,
) -> PlanRefinement:
    """Check every proposal of a validated ``PlanReadResult`` against the page.

    The steps, all deterministic: decide the scale from calibration, sheet and
    model; clean each ring (repeated, closing and collinear vertices); drop
    degenerate rings; snap rings onto the vector walls and measure how much of
    each perimeter the drawing supports; drop rings the drawing does not support
    at all; drop duplicates; flag rooms that overlap another or sit apart from
    the plan; compare with an area printed inside the room; merge symbol classes
    that differ only in spelling; drop repeated centres and centres with nothing
    drawn under them. Confidence is rebuilt from that evidence, so a high number
    means the page confirmed the geometry, not that the model sounded sure.
    """
    long_edge = max(page_width_pt, page_height_pt)
    dropped: list[str] = []
    scale = decide_scale(calibrated_ratio, getattr(result, "scale", None), vector, page_width_pt, page_height_pt)
    ratio = scale.ratio
    has_walls = vector is not None and vector.has_walls()
    walls = raster = None
    if has_walls:
        if "walls" not in vector.cache:  # type: ignore[union-attr]
            vector.cache["walls"] = w = _wall_index(vector)  # type: ignore[union-attr]
            vector.cache["raster"] = WallRaster(w, page_width_pt, page_height_pt, vector.fills)  # type: ignore[union-attr]
        walls, raster = vector.cache["walls"], vector.cache["raster"]  # type: ignore[union-attr]
    elif vector is not None and "image_raster" in vector.cache:
        # A scanned sheet: no drawn lines, but its dark pixels still bound rooms.
        raster = vector.cache["image_raster"]
        walls = vector.cache["image_walls"]

    tol = SNAP_TOL_SHARE * long_edge
    if ratio:
        max_wall = min(0.55 * ratio, 0.02 * long_edge)
        min_wall = 0.04 * ratio
        min_room_pt2 = 0.5 * ratio * ratio
        dup_r = 0.45 * ratio
        ink_r = 0.5 * ratio
    else:
        max_wall = 0.012 * long_edge
        min_wall = 0.001 * long_edge
        min_room_pt2 = 2e-4 * page_width_pt * page_height_pt
        dup_r = 0.008 * long_edge
        ink_r = 0.012 * long_edge
    max_wall = max(max_wall, 2 * min_wall)
    simplify_eps = SIMPLIFY_EPS_SHARE * long_edge

    rooms: list[RefinedRoom] = []
    for room in getattr(result, "rooms", []) or []:
        raw = norm_polygon_to_pdf_points(room.polygon, page_width_pt, page_height_pt)
        pts = _drop_collinear(clean_ring(raw, simplify_eps), simplify_eps)
        model_conf = float(room.confidence)
        # A bowtie's lobes cancel in the shoelace sum: test crossing before area.
        crossed = len(pts) >= 4 and polygon_self_intersects(pts) and _bbox_area(pts) >= min_room_pt2
        if not crossed and (len(pts) < 3 or shoelace_area(pts) < min_room_pt2):
            dropped.append("room:degenerate")
            continue
        flags: list[str] = []
        if crossed:
            capped = round(min(model_conf, 0.6 - 0.01), 2)
            rooms.append(
                RefinedRoom(
                    name=room.name,
                    points=pts,
                    model_confidence=model_conf,
                    confidence=capped,
                    verdict="error",
                    flags=["room:self_intersects"],
                )
            )
            continue
        support: float | None = None
        snapped = False
        if walls is not None:
            snap = snap_ring_to_walls(pts, walls, tol=tol, max_wall=max_wall, min_wall=min_wall, raster=raster)
            support = snap.support
            if snap.snapped:
                pts, snapped = snap.points, True
            if snap.crosses_wall:
                flags.append("room:crosses_wall")
            if support < MIN_WALL_SUPPORT:
                dropped.append("room:no_wall_evidence")
                continue
        rooms.append(
            RefinedRoom(
                name=room.name,
                points=pts,
                model_confidence=model_conf,
                confidence=model_conf,
                verdict="ok",
                flags=flags,
                wall_support=support,
                snapped=snapped,
            )
        )

    rooms = _drop_duplicate_rooms(rooms, dropped)
    _flag_overlaps_and_isolation(rooms, gap=3 * max_wall + tol, raster=raster)
    if vector is not None and vector.words:
        _read_area_labels(rooms, vector)
    for r in rooms:
        if r.verdict != "error":
            r.confidence = _room_confidence(r, scale, ratio, scanned=walls is not None and walls.count == 0)
            if r.flags and r.verdict == "ok":
                r.verdict = "warning"

    on_wall = None
    if raster is not None:
        # An opening's centre lies in the wall's gap, up to half a wide window
        # away from the nearest drawn wall.
        reach = 1.0 * ratio if ratio else 0.02 * long_edge

        def on_wall(p: Point) -> bool:
            return raster.near_wall(p, reach)  # type: ignore[union-attr]

    symbols = _refine_symbols(result, vector, page_width_pt, page_height_pt, dup_r, ink_r, dropped, on_wall)
    return PlanRefinement(scale=scale, rooms=rooms, symbols=symbols, dropped=dropped)


#: Snap search reach as a share of the page's long edge (model trace jitter).
SNAP_TOL_SHARE = 0.015
#: Vertices closer than this share of the long edge to their neighbours' line
#: are jitter on a straight wall, not corners.
SIMPLIFY_EPS_SHARE = 0.004


def _drop_duplicate_rooms(rooms: list[RefinedRoom], dropped: list[str]) -> list[RefinedRoom]:
    kept: list[RefinedRoom] = []
    for r in sorted(rooms, key=lambda r: (r.verdict == "error", -(r.wall_support or 0.0), -r.model_confidence)):
        dup = next((k for k in kept if polygon_iou(r.points, k.points) >= DUPLICATE_IOU), None)
        if dup is not None:
            if not dup.name and r.name:
                dup.name = r.name
            dropped.append("room:duplicate")
            continue
        kept.append(r)
    return kept


def _bbox_area(pts: list[Point]) -> float:
    b = _bbox(pts)
    return (b[2] - b[0]) * (b[3] - b[1])


def _flag_overlaps_and_isolation(rooms: list[RefinedRoom], *, gap: float, raster: WallRaster | None = None) -> None:
    """Flag rings that swallow another ring and rings apart from the building.

    Returns the id of the building's wall network when the page has one.
    """
    for i, r in enumerate(rooms):
        for j, o in enumerate(rooms):
            if i == j or shoelace_area(r.points) > shoelace_area(o.points):
                continue
            # The larger ring swallowed a room another ring traces on its own:
            # two rooms read as one, or a trace over the wrong walls.
            if polygon_containment(r.points, o.points) >= _CONTAINED_SHARE and "room:overlaps" not in o.flags:
                o.flags.append("room:overlaps")
    if raster is not None:
        nets = [raster.network_of(r.points) for r in rooms]
        frames = raster.frame_networks()
        for r, net in zip(rooms, nets, strict=True):
            if net in frames:
                r.flags.append("room:isolated")
    if len(rooms) < 3:
        return
    # Apart from every other room by more than a missed room could explain.
    shorts = sorted(min(b[2] - b[0], b[3] - b[1]) for b in (_bbox(r.points) for r in rooms))
    gap = max(gap, 1.5 * shorts[len(shorts) // 2])
    boxes = [_bbox(r.points) for r in rooms]
    parent = list(range(len(rooms)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a, b = boxes[i], boxes[j]
            if a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                parent[find(i)] = find(j)
    groups: dict[int, int] = {}
    for i in range(len(rooms)):
        groups[find(i)] = groups.get(find(i), 0) + 1
    main = max(groups, key=lambda g: groups[g])
    for i, r in enumerate(rooms):
        if find(i) != main and "room:isolated" not in r.flags:
            r.flags.append("room:isolated")


def _read_area_labels(rooms: list[RefinedRoom], vector: VectorLayer) -> None:
    lines = _label_lines(vector)
    for r in rooms:
        labels = [(t, _area_label(t)) for cx, cy, t in lines if point_in_polygon(cx, cy, r.points)]
        values = [v for _t, v in labels if v is not None]
        if len(values) == 1:
            r.area_label_m2 = values[0]
        if not r.name:
            names = [t for t, v in labels if v is None and re.search(r"[^\W\d_]{2,}", t)]
            if names:
                r.name = names[0][:200]


def _room_confidence(r: RefinedRoom, scale: ScaleDecision, ratio: float | None, *, scanned: bool = False) -> float:
    """Confidence from what the page confirmed; the model's own score barely counts.

    Calibrated on the training split of the plan benchmark: a ring snapped onto
    drawn walls with a fifth or more of its perimeter on them is right almost
    always; a ring snapped onto a scan's dark pixels is right about a third of
    the time; an unsnapped ring is not verified at all.
    """
    if r.wall_support is None:
        geom = min(r.model_confidence, UNVERIFIED_ROOM_MAX_CONFIDENCE)
    elif not r.snapped:
        geom = min(r.model_confidence, 0.4)
    elif scanned:
        geom = 0.3 + 0.2 * min(1.0, r.wall_support)
    else:
        geom = 0.6 + 0.37 * min(1.0, max(0.0, r.wall_support - MIN_WALL_SUPPORT) / 0.3)
    if r.area_label_m2 and ratio:
        area = shoelace_area(r.points) / (ratio * ratio)
        rel = abs(area - r.area_label_m2) / r.area_label_m2
        if rel <= 0.025:
            geom = max(geom, 0.95)
        elif rel > 0.08:
            r.flags.append("room:area_label_mismatch")
            geom = min(geom, 0.45)
    if "room:overlaps" in r.flags:
        geom = min(geom, 0.5)
    if "room:crosses_wall" in r.flags:
        geom = min(geom, 0.4)
    if "room:isolated" in r.flags:
        geom = min(geom, 0.3)
    conf = min(geom, scale.confidence) if ratio else geom
    return round(max(0.0, min(1.0, conf)), 2)


def _refine_symbols(
    result: Any,
    vector: VectorLayer | None,
    page_width_pt: float,
    page_height_pt: float,
    dup_r: float,
    ink_r: float,
    dropped: list[str],
    on_wall: Any = None,
) -> list[RefinedSymbol]:
    merged: dict[str, RefinedSymbol] = {}
    confs: dict[str, list[float]] = {}
    for sym in getattr(result, "symbols", []) or []:
        key = _canonical_class(sym.element_class)
        centers = norm_polygon_to_pdf_points(sym.centers, page_width_pt, page_height_pt)
        if key in merged:
            merged[key].centers.extend(centers)
            merged[key].flags.append("symbol:classes_merged")
        else:
            merged[key] = RefinedSymbol(element_class=sym.element_class, centers=list(centers), confidence=0.0)
        confs.setdefault(key, []).append(float(sym.confidence))

    ink_cells: set[tuple[int, int]] | None = None
    if vector is not None and vector.ink:
        ink_cells = {(int(x // ink_r), int(y // ink_r)) for x, y in vector.ink}

    out: list[RefinedSymbol] = []
    for key, sym in merged.items():
        kept: list[Point] = []
        dups = 0
        no_ink = 0
        # Doors and windows sit in walls: one far from the building's walls is
        # drawn on nothing that could be an opening.
        in_wall = on_wall is not None and any(w in key for w in ("door", "window", "opening"))
        for c in sym.centers:
            if any(math.dist(c, k) <= dup_r for k in kept):
                dups += 1
                continue
            if in_wall and not on_wall(c):
                no_ink += 1
                continue
            if ink_cells is not None and not _near_ink(c, ink_cells, ink_r):
                no_ink += 1
                continue
            kept.append(c)
        dropped.extend(["symbol:duplicate_center"] * dups)
        dropped.extend(["symbol:no_ink"] * no_ink)
        if not kept:
            continue
        conf = min(1.0, max(confs[key]))
        if ink_cells is None:
            conf = min(conf, 0.6)
        total = len(sym.centers)
        if total and (dups + no_ink) / total > 0.25:
            conf = min(conf, 0.5)
        flags = sym.flags
        if dups:
            flags.append("symbol:duplicates_removed")
        if no_ink:
            flags.append("symbol:unsupported_removed")
        out.append(RefinedSymbol(element_class=sym.element_class, centers=kept, confidence=round(conf, 2), flags=flags))
    return out


def _near_ink(c: Point, cells: set[tuple[int, int]], r: float) -> bool:
    cx, cy = int(c[0] // r), int(c[1] // r)
    return any((cx + dx, cy + dy) in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def check_plan_read(
    parsed: Any,
    *,
    page: int,
    page_width_pt: float,
    page_height_pt: float,
    image_px: tuple[float, float] | None = None,
    vector: VectorLayer | None = None,
    calibrated_ratio: float | None = None,
    image_png: bytes | None = None,
) -> tuple[Any, PlanRefinement, list[str]]:
    """Run the whole deterministic belt on one model answer.

    Coordinate repair, schema validation with per-item drops, then
    :func:`refine_plan_read`. The service persists exactly what this returns and
    the accuracy benchmark scores exactly the same call.

    Returns:
        ``(PlanReadResult, PlanRefinement, repairs)``. Every item dropped on the
        way is named in ``refinement.dropped``.
    """
    repaired, repairs = prepare_model_json(
        parsed,
        image_width_px=image_px[0] if image_px else None,
        image_height_px=image_px[1] if image_px else None,
    )
    result, dropped = parse_plan_read_response(
        repaired,
        page=page,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
    )
    if image_png is not None and (vector is None or not vector.has_walls()):
        vector = vector or VectorLayer(page_width_pt=page_width_pt, page_height_pt=page_height_pt)
        if "image_raster" not in vector.cache:
            image_raster = WallRaster.from_image(image_png, page_width_pt, page_height_pt)
            if image_raster is not None:
                vector.cache["image_raster"] = image_raster
                vector.cache["image_walls"] = _empty_wall_index()
    refinement = refine_plan_read(
        result,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        vector=vector,
        calibrated_ratio=calibrated_ratio,
    )
    refinement.dropped[:0] = dropped
    return result, refinement, repairs

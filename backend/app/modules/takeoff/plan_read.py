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
        normalized = {**raw_room, "polygon": _normalize_points(raw_room.get("polygon"))}
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
        normalized = {**raw_symbol, "centers": _normalize_points(raw_symbol.get("centers"))}
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
    if isinstance(ref, (list, tuple)) and len(ref) == 2:
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

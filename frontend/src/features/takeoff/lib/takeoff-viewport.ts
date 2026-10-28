// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure viewport math for the PDF takeoff viewer.
 *
 * Split out from `TakeoffViewerModule` so the zoom / fit / pan / ortho
 * geometry can be unit tested without mounting React or pdf.js. Everything
 * here is dependency-free and side-effect-free: callers pass in plain
 * numbers (page + viewport dimensions, scroll offsets, cursor position) and
 * receive plain numbers back, then apply them to the live DOM.
 *
 * COORDINATE CONTRACT (must match the viewer):
 *   - Stored measurement points are in PDF user units (1 pt = 1/72 inch).
 *   - The canvas CSS box is `pageWidthPdfUnits * zoom` wide, so a pointer in
 *     PDF units is `(clientX - rect.left) / zoom` and a PDF-unit length on
 *     screen is `lengthPdfUnits * zoom`. No devicePixelRatio ever enters
 *     this space (the overlay CSS box already divides it out).
 *   - `zoom` is a unitless multiplier; 1.0 renders the page at its native
 *     PDF point size. The viewer clamps zoom to [ZOOM_MIN, ZOOM_MAX].
 */

import {
  pixelDistance,
  toRealDistance,
  type ScaleConfig,
} from '@/modules/pdf-takeoff/data/scale-helpers';
import type { Point } from './takeoff-types';

/* ── Zoom bounds ─────────────────────────────────────────────────────────
 * Mirrors the inline clamps already used by the viewer's wheel handler,
 * pinch handler and zoom-in/out buttons so every zoom path shares one
 * definition rather than three copies of `0.25` / `4`. */

/** Minimum canvas zoom (25%). */
export const ZOOM_MIN = 0.25;
/** Maximum canvas zoom (400%). */
export const ZOOM_MAX = 4;

/** Clamp a raw zoom to the supported range and quantize to whole percent.
 *  Quantizing to 2 decimals keeps the percent readout (`{(zoom*100)}%`)
 *  stable and avoids float drift accumulating across repeated wheel ticks. */
export function clampZoom(raw: number): number {
  if (!Number.isFinite(raw)) return 1;
  const bounded = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, raw));
  return Math.round(bounded * 100) / 100;
}

/* ── Fit-to-viewport ─────────────────────────────────────────────────────
 * The viewer renders one page into a scroll container. A "fit" computes the
 * zoom at which the page's PDF-unit dimensions map onto the container's CSS
 * pixel dimensions for a chosen mode. Because the canvas CSS width is
 * `pageWidth * zoom`, the fit zoom is simply `viewport / page` along the
 * constraining axis. */

export type FitMode = 'width' | 'page';

/** Padding (CSS px) reserved on each side so a fitted page is not flush
 *  against the scroll-container border. Subtracted from the available
 *  viewport before the ratio is taken. */
export const FIT_PADDING_PX = 16;

/** Lower bound for a *fit* zoom. Fitting the whole page is a "show me
 *  everything" action, so unlike the manual wheel / button floor (`ZOOM_MIN`,
 *  25%) it may legitimately need a smaller zoom to frame a large-format sheet
 *  (A0 / E-size, whose PDF-point dimensions run into the thousands) inside a
 *  modest or split-pane viewport. Flooring a fit at `ZOOM_MIN` would clip such
 *  a sheet, defeating the point of fit-to-page. This absolute floor only
 *  guards against pathological (near-zero) ratios and sits well below any real
 *  sheet's fit. Manual zoom still floors at `ZOOM_MIN`, so the first wheel /
 *  button zoom after a sub-25% fit snaps back into the working range. */
export const FIT_ZOOM_MIN = 0.02;

/** Clamp a fit zoom to `[FIT_ZOOM_MIN, ZOOM_MAX]` (note: the lower bound is the
 *  fit floor, NOT the manual `ZOOM_MIN`) and quantize to whole percent so the
 *  percent readout stays stable. */
function clampFitZoom(raw: number): number {
  if (!Number.isFinite(raw)) return 1;
  const bounded = Math.max(FIT_ZOOM_MIN, Math.min(ZOOM_MAX, raw));
  return Math.round(bounded * 100) / 100;
}

/**
 * Zoom that fits the page into the viewport for the given mode.
 *
 *   - `width`: the page width fills the viewport width (vertical scroll for
 *     tall sheets). This is the estimator's default reading posture.
 *   - `page`: the whole page is visible (the tighter of width / height fit),
 *     so nothing is clipped.
 *
 * Returns a fit-clamped zoom: bounded above by `ZOOM_MAX` and below by
 * `FIT_ZOOM_MIN` (not the manual `ZOOM_MIN`), so a large sheet can be framed
 * whole even below 25%. Degenerate inputs (non-positive page or viewport
 * dimensions) fall back to 1.0 rather than producing Infinity / 0.
 */
export function computeFitZoom(
  pageWidth: number,
  pageHeight: number,
  viewportWidth: number,
  viewportHeight: number,
  mode: FitMode,
): number {
  const availW = viewportWidth - FIT_PADDING_PX * 2;
  const availH = viewportHeight - FIT_PADDING_PX * 2;
  if (pageWidth <= 0 || pageHeight <= 0 || availW <= 0 || availH <= 0) {
    return 1;
  }
  const widthZoom = availW / pageWidth;
  if (mode === 'width') return clampFitZoom(widthZoom);
  const heightZoom = availH / pageHeight;
  // Whole page: constrain by whichever axis runs out of room first.
  return clampFitZoom(Math.min(widthZoom, heightZoom));
}

/* ── Axis-aligned bounding box (for zoom-to-selection) ──────────────────── */

export interface BoundingBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * Axis-aligned bounding box of a set of points, in PDF units, or `null`
 * when there are no points. Used to frame the selected measurement(s).
 */
export function boundingBoxOfPoints(points: Point[]): BoundingBox | null {
  if (points.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

/** Merge several bounding boxes (e.g. one per selected measurement) into the
 *  box that encloses all of them, or `null` when the list is empty. */
export function mergeBoundingBoxes(boxes: BoundingBox[]): BoundingBox | null {
  if (boxes.length === 0) return null;
  let { minX, minY, maxX, maxY } = boxes[0]!;
  for (let i = 1; i < boxes.length; i++) {
    const b = boxes[i]!;
    if (b.minX < minX) minX = b.minX;
    if (b.minY < minY) minY = b.minY;
    if (b.maxX > maxX) maxX = b.maxX;
    if (b.maxY > maxY) maxY = b.maxY;
  }
  return { minX, minY, maxX, maxY };
}

export interface ZoomToBoxResult {
  /** Clamped zoom at which the box (plus margin) fits the viewport. */
  zoom: number;
  /** Scroll offsets (CSS px) that center the box in the viewport at the
   *  returned zoom. Apply to `container.scrollLeft` / `scrollTop` after the
   *  canvas has re-laid-out at the new zoom. Never negative. */
  scrollLeft: number;
  scrollTop: number;
}

/**
 * Zoom + scroll that frames a PDF-unit bounding box inside the viewport.
 *
 * The box is grown by `marginFraction` on every side so the selection is not
 * jammed against the edge, then the fit zoom is the smaller of the two axis
 * ratios (so the whole box is visible). Scroll offsets center the box's
 * midpoint: at zoom `z`, a PDF-unit coordinate maps to `coord * z` CSS px, so
 * centering the box midpoint means scrolling to `mid * z - viewport / 2`.
 *
 * A zero-area box (a single count dot, a text pin) still yields a sensible
 * result: it falls back to `fallbackZoom` and just centers on the point.
 */
export function computeZoomToBox(
  box: BoundingBox,
  viewportWidth: number,
  viewportHeight: number,
  options?: { marginFraction?: number; fallbackZoom?: number },
): ZoomToBoxResult {
  const marginFraction = options?.marginFraction ?? 0.15;
  const fallbackZoom = options?.fallbackZoom ?? 1;

  const boxW = box.maxX - box.minX;
  const boxH = box.maxY - box.minY;
  const midX = (box.minX + box.maxX) / 2;
  const midY = (box.minY + box.maxY) / 2;

  let zoom: number;
  if (boxW <= 0 && boxH <= 0) {
    // Degenerate (single point): keep the current-ish scale, just recenter.
    zoom = clampZoom(fallbackZoom);
  } else {
    // Grow the box by the margin on both sides before measuring the ratio.
    const paddedW = boxW * (1 + marginFraction * 2);
    const paddedH = boxH * (1 + marginFraction * 2);
    const zw = paddedW > 0 ? viewportWidth / paddedW : Infinity;
    const zh = paddedH > 0 ? viewportHeight / paddedH : Infinity;
    const raw = Math.min(zw, zh);
    zoom = clampZoom(Number.isFinite(raw) ? raw : fallbackZoom);
  }

  // Center the box midpoint in the viewport. Clamp at 0 so we never request
  // a negative scroll (the browser would clamp it anyway, but keeping the
  // contract explicit makes the helper testable).
  const scrollLeft = Math.max(0, midX * zoom - viewportWidth / 2);
  const scrollTop = Math.max(0, midY * zoom - viewportHeight / 2);
  return { zoom, scrollLeft, scrollTop };
}

/* ── Zoom-at-cursor (re-anchor scroll) ──────────────────────────────────── */

/**
 * New scroll offsets that keep the world point under the cursor stationary
 * while the zoom changes from `prevZoom` to `nextZoom`.
 *
 * `cursorX/Y` are the cursor position RELATIVE to the scroll container's
 * top-left (i.e. `clientX - rect.left`). The world offset under the cursor is
 * `scroll + cursor`; it scales by `nextZoom / prevZoom`, so the new scroll is
 * `(scroll + cursor) * ratio - cursor`. This is the same maths the viewer's
 * wheel handler already performs inline - centralized here so it can be
 * tested and reused by the pinch handler.
 *
 * Returns the previous scroll unchanged when the zoom does not move.
 */
export function zoomAtCursorScroll(
  prevZoom: number,
  nextZoom: number,
  scrollLeft: number,
  scrollTop: number,
  cursorX: number,
  cursorY: number,
): { scrollLeft: number; scrollTop: number } {
  if (prevZoom <= 0 || nextZoom === prevZoom) {
    return { scrollLeft, scrollTop };
  }
  const ratio = nextZoom / prevZoom;
  return {
    scrollLeft: Math.max(0, (scrollLeft + cursorX) * ratio - cursorX),
    scrollTop: Math.max(0, (scrollTop + cursorY) * ratio - cursorY),
  };
}

/** Multiply a zoom by a wheel step and clamp. `deltaY < 0` (wheel up /
 *  scroll away from the user) zooms in. Matches the existing 1.1 factor. */
export function wheelZoomStep(prevZoom: number, deltaY: number): number {
  const factor = deltaY < 0 ? 1.1 : 1 / 1.1;
  return clampZoom(prevZoom * factor);
}

/* ── Ortho / angle lock ──────────────────────────────────────────────────
 * While drawing, holding the lock constrains the in-progress segment from
 * `anchor` to the cursor onto the nearest 0 / 45 / 90 degree direction. Pure
 * geometry in PDF units; the viewer feeds the snapped point into the same
 * create path an un-snapped click would use. */

/** Directions the ortho lock snaps to, in radians: every 45 degrees. */
const ORTHO_STEP_RAD = Math.PI / 4;

/**
 * Snap `cursor` so the segment `anchor -> cursor` lies on the nearest
 * multiple of 45 degrees, preserving the segment length along that axis.
 *
 * The point is projected onto the snapped direction (length = original
 * distance * cos(angle error)) rather than merely rounded, so a near-45
 * drag produces a clean diagonal whose endpoint sits exactly on the ray.
 * Returns `anchor` unchanged for a zero-length segment.
 */
export function orthoSnap(anchor: Point, cursor: Point): Point {
  const dx = cursor.x - anchor.x;
  const dy = cursor.y - anchor.y;
  const len = Math.hypot(dx, dy);
  if (len === 0) return { x: anchor.x, y: anchor.y };
  const angle = Math.atan2(dy, dx);
  const snapped = Math.round(angle / ORTHO_STEP_RAD) * ORTHO_STEP_RAD;
  // Project the original length onto the snapped direction. Using the raw
  // length (not its axis component) keeps a 90-degree snap from shrinking a
  // mostly-horizontal drag to nothing.
  return {
    x: anchor.x + Math.cos(snapped) * len,
    y: anchor.y + Math.sin(snapped) * len,
  };
}

/**
 * Ortho-snap a vertex that is being dragged on an existing measurement.
 *
 * The draw path has a single anchor (the previously placed point). An existing
 * vertex instead has one or two neighbours to square against: an endpoint of an
 * open run has one neighbour, an interior vertex has two, and every vertex of a
 * closed shape (area / volume / cloud) has two with wraparound. Each neighbour
 * is used as an `orthoSnap` anchor and the candidate closest to the raw cursor
 * wins, so the edge the user is nearest to aligning is the one that squares up.
 *
 * `orthoSnap` preserves length along the snapped axis, so squaring an edge does
 * not silently shorten it. Returns `cursor` unchanged for degenerate input
 * (fewer than two points, or `vertexIndex` out of range), matching the draw
 * path's "no anchor, no snap".
 */
export function orthoSnapVertexDrag(
  points: Point[],
  vertexIndex: number,
  cursor: Point,
  closed: boolean,
): Point {
  const n = points.length;
  if (n < 2 || vertexIndex < 0 || vertexIndex >= n) return cursor;

  const neighbours: Point[] = [];
  const prev =
    vertexIndex > 0 ? points[vertexIndex - 1]! : closed ? points[n - 1]! : null;
  const next =
    vertexIndex < n - 1 ? points[vertexIndex + 1]! : closed ? points[0]! : null;
  if (prev) neighbours.push(prev);
  if (next) neighbours.push(next);
  if (neighbours.length === 0) return cursor;

  let best = cursor;
  let bestDist = Infinity;
  for (const anchor of neighbours) {
    const cand = orthoSnap(anchor, cursor);
    const d = Math.hypot(cand.x - cursor.x, cand.y - cursor.y);
    if (d < bestDist) {
      bestDist = d;
      best = cand;
    }
  }
  return best;
}

/* ── Duplicate trailing vertex (double-click finish) ─────────────────────
 * A double-click that closes a shape fires two `click` events before the
 * `dblclick`, so the last placed vertex is a near-duplicate of the one before
 * it. Stored points are zoom-normalised (PDF units), so the "same click" test
 * is applied in SCREEN space (distance * zoom), not point space. */

/** Screen-space distance (px) under which a finishing double-click's trailing
 *  vertex is treated as a duplicate of the previous one and dropped. */
export const DUP_VERTEX_SCREEN_PX = 6;

/**
 * Drop a trailing vertex that sits within `screenRadiusPx` screen pixels of the
 * vertex before it, so a double-click that closes a shape leaves no zero-length
 * tail (polyline) or sliver edge (area / volume). Returns the array unchanged
 * when the last two points are meaningfully apart, or when there are fewer than
 * two points. Pure: never mutates the input.
 */
export function dropTrailingDuplicateVertex(
  points: Point[],
  zoom: number,
  screenRadiusPx: number = DUP_VERTEX_SCREEN_PX,
): Point[] {
  if (points.length < 2) return points;
  const last = points[points.length - 1]!;
  const prev = points[points.length - 2]!;
  const screenDist = Math.hypot(last.x - prev.x, last.y - prev.y) * zoom;
  return screenDist < screenRadiusPx ? points.slice(0, -1) : points;
}

/* ── Snap to existing vertices (opt-in draw aid) ─────────────────────────
 * While drawing, an opt-in snap pulls the in-progress point onto the nearest
 * vertex of an already-drawn measurement so a new shape connects exactly to an
 * existing corner. The catch radius is measured in SCREEN space so it feels the
 * same at every zoom level. */

/** Default screen-space radius (px) within which the in-progress draw point
 *  snaps onto an existing measurement vertex. */
export const VERTEX_SNAP_SCREEN_PX = 10;

/**
 * Nearest vertex to `cursor` within `screenRadiusPx` screen pixels, or `null`
 * when none is in range. `cursor` and `vertices` are in PDF units; the radius
 * is converted to PDF units via `zoom` so the catch distance is constant on
 * screen. Returns a fresh point (a copy of the matched vertex) so callers can
 * store it without aliasing the source geometry. Pure + side-effect-free.
 */
export function snapToVertex(
  cursor: Point,
  vertices: readonly Point[],
  zoom: number,
  screenRadiusPx: number = VERTEX_SNAP_SCREEN_PX,
): Point | null {
  if (!(zoom > 0) || !(screenRadiusPx > 0)) return null;
  const radiusPdf = screenRadiusPx / zoom;
  let best: Point | null = null;
  let bestDist = Infinity;
  for (const v of vertices) {
    const d = Math.hypot(v.x - cursor.x, v.y - cursor.y);
    if (d <= radiusPdf && d < bestDist) {
      bestDist = d;
      best = { x: v.x, y: v.y };
    }
  }
  return best;
}

/* ── Live drawing readout ────────────────────────────────────────────────
 * The HUD shown while a measure tool is active reports the cursor position
 * and the running length of the segment / polyline being drawn, in the
 * page's calibrated units. These mirror the create-time maths in the viewer
 * (pixelDistance -> toRealDistance) so the readout and the committed
 * measurement never disagree. */

export interface DrawReadout {
  /** Cursor position in PDF units (rounded for display stability). */
  cursor: Point;
  /** Length of the segment from the last placed point to the cursor, in real
   *  units, or `null` when there is no anchor yet or the page is uncalibrated. */
  segment: number | null;
  /** Cumulative length of all placed segments plus the live segment to the
   *  cursor, in real units, or `null` when the page is uncalibrated. */
  total: number | null;
  /** Unit label for `segment` / `total` (e.g. "m"); empty when uncalibrated. */
  unit: string;
}

/** Round a coordinate to 1 decimal PDF unit for a stable HUD readout. */
function roundCoord(v: number): number {
  return Math.round(v * 10) / 10;
}

/**
 * Build the live readout for a draw-in-progress.
 *
 * `placed` are the points already clicked (PDF units), `cursor` is the live
 * pointer (PDF units, already ortho-snapped by the caller if the lock is on).
 * Length is `null` when the page has no usable scale (`pixelsPerUnit <= 0`),
 * so the HUD shows coordinates only rather than a misleading `0 m`.
 */
export function computeDrawReadout(
  placed: Point[],
  cursor: Point,
  scale: ScaleConfig,
): DrawReadout {
  const calibrated = scale.pixelsPerUnit > 0;
  const unit = calibrated ? scale.unitLabel : '';

  const anchor = placed.length > 0 ? placed[placed.length - 1]! : null;
  let segmentPx: number | null = null;
  if (anchor) {
    segmentPx = pixelDistance(anchor.x, anchor.y, cursor.x, cursor.y);
  }

  // Cumulative length: placed polyline edges + the live segment to cursor.
  let totalPx = 0;
  for (let i = 0; i < placed.length - 1; i++) {
    const a = placed[i]!;
    const b = placed[i + 1]!;
    totalPx += pixelDistance(a.x, a.y, b.x, b.y);
  }
  if (segmentPx != null) totalPx += segmentPx;

  return {
    cursor: { x: roundCoord(cursor.x), y: roundCoord(cursor.y) },
    segment:
      calibrated && segmentPx != null ? toRealDistance(segmentPx, scale) : null,
    total: calibrated && placed.length > 0 ? toRealDistance(totalPx, scale) : null,
    unit,
  };
}

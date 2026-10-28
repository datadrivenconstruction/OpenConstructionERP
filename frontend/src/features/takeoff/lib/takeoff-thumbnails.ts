// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the PDF takeoff page-thumbnails sidebar.
 *
 * Split out from `TakeoffViewerModule` so the render-scale maths, the
 * nearest-first render ordering and the LRU cache cap can be unit tested
 * without mounting React or pdf.js. Everything here is dependency-free and
 * side-effect-free: callers pass plain numbers / plain objects and receive
 * plain values back, then drive the live pdf.js render + DOM themselves.
 *
 * Thumbnails are rendered into throwaway offscreen canvases (never the live
 * `canvasRef` / `overlayRef`) at devicePixelRatio 1 (retina thumbs waste
 * memory for no readable gain), so this module only needs the page width in
 * PDF user units to pick the pdf.js `scale`.
 */

/** Target thumbnail width in CSS px. A page is rendered at the pdf.js scale
 *  that makes the bitmap roughly this wide so the strip stays compact. */
export const THUMB_MAX_WIDTH = 120;

/** Default number of rendered thumbnails kept in memory. A 300-page set at a
 *  ~120px PNG dataURL each is real memory, so the cache is capped and the
 *  pages furthest from the current view are evicted first. */
export const THUMB_CACHE_MAX = 60;

/**
 * pdf.js `scale` to pass to `page.getViewport({ scale })` so the rendered
 * bitmap is about `maxWidthPx` CSS px wide.
 *
 * `page.getViewport({ scale: 1 }).width` is the page width in PDF user units
 * (1 pt = 1/72 inch); the rendered bitmap width is `pageWidthPt * scale`, so
 * the scale that hits the target width is `maxWidthPx / pageWidthPt`. A
 * non-positive or non-finite page width (a not-yet-measured page) falls back
 * to a small fixed scale rather than producing 0 / Infinity.
 */
export function computeThumbScale(pageWidthPt: number, maxWidthPx: number): number {
  if (!Number.isFinite(pageWidthPt) || pageWidthPt <= 0) return 0.2;
  if (!Number.isFinite(maxWidthPx) || maxWidthPx <= 0) return 0.2;
  return maxWidthPx / pageWidthPt;
}

/**
 * Page numbers (1-indexed) ordered so the current page and its neighbours
 * render first, then the rest fan out. Rendering the visible neighbourhood
 * before far pages keeps navigation feeling instant on a large set.
 *
 * Example: `pagesNearestFirst(5, 9)` -> `[5, 6, 4, 7, 3, 8, 2, 9, 1]` (each
 * distance band lists the page after the current one before the page before
 * it). Degenerate inputs (no pages, current out of range) are clamped so the
 * result is always a valid permutation of `1..totalPages`.
 */
export function pagesNearestFirst(currentPage: number, totalPages: number): number[] {
  if (!Number.isFinite(totalPages) || totalPages <= 0) return [];
  const total = Math.floor(totalPages);
  const start = Math.min(Math.max(1, Math.floor(currentPage) || 1), total);
  const order: number[] = [start];
  for (let d = 1; d < total; d++) {
    const lo = start - d;
    const hi = start + d;
    if (hi <= total) order.push(hi);
    if (lo >= 1) order.push(lo);
    if (order.length >= total) break;
  }
  return order;
}

/**
 * Cap a page-number -> dataURL thumbnail map at `max` entries, evicting the
 * pages furthest from `keepNear` (the current page) first so the visible
 * neighbourhood survives. Returns the same object reference when it is
 * already within the cap (no allocation on the common path); otherwise a new
 * trimmed object. Pure: never mutates the input.
 *
 * Distance ties keep the lower page number (deterministic for tests).
 */
export function capThumbCache(
  thumbs: Record<number, string>,
  keepNear: number,
  max: number = THUMB_CACHE_MAX,
): Record<number, string> {
  const keys = Object.keys(thumbs);
  if (keys.length <= max) return thumbs;
  const pages = keys.map((k) => Number(k));
  pages.sort((a, b) => {
    const da = Math.abs(a - keepNear);
    const db = Math.abs(b - keepNear);
    if (da !== db) return da - db; // nearest first
    return a - b; // stable tie-break
  });
  const kept = pages.slice(0, max);
  const next: Record<number, string> = {};
  for (const p of kept) {
    const v = thumbs[p];
    if (v !== undefined) next[p] = v;
  }
  return next;
}

/**
 * Count of measurements per 1-indexed page, for the per-thumbnail badge and
 * the page-jump dropdown. Pure reduce over the measurement list; pages with
 * no measurements are simply absent from the map (callers treat missing as
 * 0). Only the `page` field is read, so any object carrying a numeric `page`
 * works (keeps the helper decoupled from the full Measurement type).
 */
export function countMeasurementsByPage(
  measurements: ReadonlyArray<{ page: number }>,
): Record<number, number> {
  const counts: Record<number, number> = {};
  for (const m of measurements) {
    const p = m.page;
    if (!Number.isFinite(p) || p <= 0) continue;
    counts[p] = (counts[p] ?? 0) + 1;
  }
  return counts;
}

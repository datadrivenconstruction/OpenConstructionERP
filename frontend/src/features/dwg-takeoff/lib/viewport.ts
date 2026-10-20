// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Viewport math utilities for the DXF canvas viewer.
 *
 * All coordinates follow the convention:
 *   screen = canvas pixel coordinates (top-left origin, Y down)
 *   world  = DXF model-space coordinates (bottom-left origin, Y up)
 */

import type { DxfEntity } from '../api';

export interface ViewportState {
  offsetX: number;
  offsetY: number;
  scale: number;
}

export interface Extents {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * World-space bounding box of every entity, used to fit the drawing on load.
 *
 * Annotation is deliberately excluded, and that exclusion is the whole design.
 * A glyph's drawn size depends on the scale, and the scale depends on this
 * box, so letting text in closes a loop with no stable answer - the frame and
 * the font chase each other. Bounding one end alone does not open the loop, it
 * only moves the disagreement: bounding the box while the renderer drew
 * unbounded put a 30720px glyph over an otherwise correctly framed drawing.
 * Fitting to geometry cuts the dependency, which is what frees `textFontSize`
 * to clamp text to a readable band on legibility grounds alone. It is also
 * what makes the drawing fill the view, which is the complaint in #426.
 *
 * Two consequences, accepted rather than overlooked. A label near the edge can
 * extend past the fitted view - ordinary in CAD viewers, and the price of the
 * geometry filling the screen. And a drawing that is *only* annotation has no
 * geometry to fit, so there, and only there, the text estimate is the content.
 *
 * Block definition members (`e.block`) are skipped for a different reason: they
 * are not placed anywhere. Their coordinates are in their block's own space, so
 * fitting to them frames a drawing nobody is looking at. Pass the output of
 * `expandBlockReferences` alongside the entities to have block content counted
 * where it actually sits.
 */
/** Feed the box of a counter-clockwise arc (angles in radians) to `expand`:
 *  its end points plus every axis extreme the sweep passes through. */
export function arcExtents(
  centre: { x: number; y: number },
  radius: number,
  startAngle: number,
  endAngle: number,
  expand: (x: number, y: number) => void,
): void {
  const TAU = Math.PI * 2;
  const sa = ((startAngle % TAU) + TAU) % TAU;
  let sweep = ((endAngle % TAU) + TAU) % TAU - sa;
  if (sweep <= 0) sweep += TAU;
  const at = (a: number) => expand(centre.x + radius * Math.cos(a), centre.y + radius * Math.sin(a));
  at(sa);
  at(sa + sweep);
  for (let k = 0; k < 8; k++) {
    const axis = (k * Math.PI) / 2;
    if (axis > sa && axis < sa + sweep) at(axis);
  }
}

/** Parameter sweep of an ELLIPSE in (0, 2*PI]. Equal start and end (also both
 *  absent, as older rows store them) mean the whole ellipse. */
export function ellipseSweep(e: { start_angle?: number; end_angle?: number }): { start: number; sweep: number } {
  const TAU = Math.PI * 2;
  const start = e.start_angle ?? 0;
  let sweep = ((((e.end_angle ?? start) - start) % TAU) + TAU) % TAU;
  if (sweep < 1e-9) sweep = TAU;
  return { start, sweep };
}

/** Point of an ellipse at parameter `t` (world space). */
export function ellipsePoint(
  c: { x: number; y: number },
  a: number,
  b: number,
  rotation: number,
  t: number,
): { x: number; y: number } {
  const ca = Math.cos(rotation);
  const sa = Math.sin(rotation);
  const x = a * Math.cos(t);
  const y = b * Math.sin(t);
  return { x: c.x + x * ca - y * sa, y: c.y + x * sa + y * ca };
}

export function computeExtents(entities: DxfEntity[]): Extents {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  const expand = (x: number, y: number) => {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  };

  for (const e of entities) {
    if (e.type === 'TEXT' || e.block) continue;
    if (e.type === 'ARC' && e.start && e.radius && e.start_angle != null && e.end_angle != null) {
      // An ARC's `start` is its centre. A flat arc (radius 50 km, sweep 0.1 deg)
      // is drawn as a short curve; its centre and full circle are nowhere near it.
      arcExtents(e.start, e.radius, e.start_angle, e.end_angle, expand);
      continue;
    }
    if (e.start) expand(e.start.x, e.start.y);
    if (e.end) expand(e.end.x, e.end.y);
    if (e.vertices) {
      for (const v of e.vertices) expand(v.x, v.y);
    }
    if (e.start && e.radius) {
      expand(e.start.x - e.radius, e.start.y - e.radius);
      expand(e.start.x + e.radius, e.start.y + e.radius);
    }
    if (e.type === 'ELLIPSE' && e.start) {
      const r = Math.max(e.major_radius ?? 0, e.minor_radius ?? 0, e.radius ?? 0);
      const { start, sweep } = ellipseSweep(e);
      if (r > 0 && e.major_radius != null && e.minor_radius != null && sweep < Math.PI * 2) {
        // An elliptical arc spans its curve, not the whole ellipse.
        for (let k = 0; k <= 32; k++) {
          const p = ellipsePoint(e.start, e.major_radius, e.minor_radius, e.rotation ?? 0, start + (sweep * k) / 32);
          expand(p.x, p.y);
        }
      } else if (r > 0) {
        expand(e.start.x - r, e.start.y - r);
        expand(e.start.x + r, e.start.y + r);
      }
    }
  }

  if (isFinite(minX)) return { minX, minY, maxX, maxY };

  // Nothing but annotation. Fitting to the geometry would be fitting to
  // nothing, so here the estimate is all the content there is.
  for (const e of entities) {
    const box = textExtents(e);
    if (box) {
      expand(box.minX, box.minY);
      expand(box.maxX, box.maxY);
    }
  }

  if (isFinite(minX)) return { minX, minY, maxX, maxY };
  return { minX: 0, minY: 0, maxX: 100, maxY: 100 };
}

/**
 * Estimated world-space box of one TEXT/MTEXT entity, or null if it draws
 * nothing. Reached only by the text-only fallback above.
 *
 * The estimate is rough and cannot be otherwise: `0.6 * height` per character
 * is an average advance width, wrong in both directions for any proportional
 * font, and the real width is only knowable by measuring against the font the
 * canvas will actually use. That is tolerable here precisely because this is
 * the fallback - it frames a drawing that would otherwise have no box at all,
 * and being 20% out on such a file costs nothing. It would not be tolerable as
 * an input to the normal fit, which is one more reason the normal fit does not
 * use it. Multi-line strings are as wide as their longest line and stack
 * *downwards*, matching how `renderText` lays them out; the box turns with
 * `rotation`, since a half-turn string runs to the left of its insertion
 * point; justification is ignored because the renderer ignores it too.
 */
function textExtents(e: DxfEntity): Extents | null {
  if (e.type !== 'TEXT' || !e.start || !e.text) return null;
  const h = e.height ?? 2.5;
  const lines = e.text.split('\n');
  const longest = lines.reduce((m, line) => Math.max(m, line.length), 0);
  const width = h * longest * 0.6;
  const up = h;
  const down = (lines.length - 1) * h * 1.25; // matches renderText's line step

  // Advance direction and the perpendicular ascender, in world units.
  const rot = e.rotation ?? 0;
  const cos = Math.cos(rot);
  const sin = Math.sin(rot);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const along of [0, width]) {
    for (const across of [up, -down]) {
      const x = e.start.x + along * cos - across * sin;
      const y = e.start.y + along * sin + across * cos;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  return { minX, minY, maxX, maxY };
}

/** Convert screen (canvas) coordinates to DXF world coordinates. */
export function screenToWorld(
  sx: number,
  sy: number,
  vp: ViewportState,
): { x: number; y: number } {
  return {
    x: (sx - vp.offsetX) / vp.scale,
    y: -(sy - vp.offsetY) / vp.scale,
  };
}

/** Convert DXF world coordinates to screen (canvas) coordinates. */
export function worldToScreen(
  wx: number,
  wy: number,
  vp: ViewportState,
): { x: number; y: number } {
  return {
    x: wx * vp.scale + vp.offsetX,
    y: -wy * vp.scale + vp.offsetY,
  };
}

/** Compute a viewport that fits the given extents into the canvas with padding. */
export function zoomToFit(
  extents: Extents,
  canvasWidth: number,
  canvasHeight: number,
  padding = 16,
): ViewportState {
  const dw = extents.maxX - extents.minX || 1;
  const dh = extents.maxY - extents.minY || 1;

  const availW = canvasWidth - padding * 2;
  const availH = canvasHeight - padding * 2;

  const scale = Math.min(availW / dw, availH / dh);

  const cx = (extents.minX + extents.maxX) / 2;
  const cy = (extents.minY + extents.maxY) / 2;

  return {
    offsetX: canvasWidth / 2 - cx * scale,
    offsetY: canvasHeight / 2 + cy * scale,
    scale,
  };
}

/** Apply a zoom factor centered at a screen point. */
export function applyZoom(
  vp: ViewportState,
  factor: number,
  centerX: number,
  centerY: number,
): ViewportState {
  const newScale = vp.scale * factor;
  return {
    scale: newScale,
    offsetX: centerX - (centerX - vp.offsetX) * (newScale / vp.scale),
    offsetY: centerY - (centerY - vp.offsetY) * (newScale / vp.scale),
  };
}

/** Apply a pan delta (in screen pixels). */
export function applyPan(vp: ViewportState, dx: number, dy: number): ViewportState {
  return {
    ...vp,
    offsetX: vp.offsetX + dx,
    offsetY: vp.offsetY + dy,
  };
}

/** A plan smaller than 1 m or larger than 100 km across almost always means the
 *  file declares the wrong unit (a metre drawing stored as millimetres). */
export function isImplausibleSpan(span: { w: number; h: number }): boolean {
  const largest = Math.max(span.w, span.h);
  return largest > 0 && (largest < 1 || largest > 100_000);
}

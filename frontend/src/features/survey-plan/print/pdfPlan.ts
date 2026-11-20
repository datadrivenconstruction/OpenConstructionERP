// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The print-ready plan: vector PDF at a true scale. Layout and geometry are
 * pure functions (tested); `renderPlanPdf` draws them with jsPDF. The page is
 * the drawing frame on the left and the title column on the right (title
 * block, legend, north arrow, scale bar), the same frame the backend uses to
 * fit the scale (survey_core/plan_export.py).
 */

import type { jsPDF } from 'jspdf';
import type { GridXY, GridXYZ, PlanFeature } from '../types';
import type { PlanConventions } from '../units/conventions';
import { LINEAR_SYMBOL, METRES_PER, formatCoord, axisLabelFor } from '../units/linear';
import { formatAngle } from '../units/angles';
import { drawTitleBlock, type TitleBlockData } from './titleBlock';

export const PAPERS = {
  A4: [297, 210],
  A3: [420, 297],
  A2: [594, 420],
  A1: [841, 594],
  ANSI_A: [279.4, 215.9],
  ANSI_B: [431.8, 279.4],
  ANSI_C: [558.8, 431.8],
  ANSI_D: [863.6, 558.8],
} as const satisfies Record<string, readonly [number, number]>;
export type PaperId = keyof typeof PAPERS;
export const SCALES = [100, 200, 250, 500, 1000, 1250, 2000, 2500, 5000, 10000] as const;

export const MARGIN_MM = 20;
export const TITLE_MM = 60;
const PT_MM = 25.4 / 72;

export interface Rect { x: number; y: number; w: number; h: number }

export interface PageLayout {
  width: number;
  height: number;
  frame: Rect;
  title: Rect;
}

export function pageLayout(paper: PaperId, orientation: 'landscape' | 'portrait' = 'landscape'): PageLayout {
  const [a, b] = PAPERS[paper] ?? PAPERS.A3;
  const [width, height] = orientation === 'landscape' ? [a, b] : [b, a];
  const frame = { x: MARGIN_MM, y: MARGIN_MM, w: width - 2 * MARGIN_MM - TITLE_MM, h: height - 2 * MARGIN_MM };
  return { width, height, frame, title: { x: frame.x + frame.w, y: frame.y, w: TITLE_MM, h: frame.h } };
}

/** The largest standard scale at which an extent (metres) fits the frame. */
export function fitScale(extent: [number, number], frame: Rect): number {
  for (const s of SCALES) if ((extent[0] * 1000) / s <= frame.w && (extent[1] * 1000) / s <= frame.h) return s;
  return SCALES[SCALES.length - 1]!;
}

/** Grid metres to paper millimetres (y down) for a frame centred on `centre`. */
export interface View { centre: GridXY; scale: number; frame: Rect }

export function toPaper(p: GridXYZ, v: View): [number, number] {
  const k = 1000 / v.scale;
  return [v.frame.x + v.frame.w / 2 + (p[0] - v.centre[0]) * k, v.frame.y + v.frame.h / 2 - (p[1] - v.centre[1]) * k];
}

export function viewExtent(v: View): [number, number, number, number] {
  const hw = (v.frame.w / 2) * (v.scale / 1000), hh = (v.frame.h / 2) * (v.scale / 1000);
  return [v.centre[0] - hw, v.centre[1] - hh, v.centre[0] + hw, v.centre[1] + hh];
}

// ── Scale bar ─────────────────────────────────────────────────────────────

export interface ScaleBar {
  /** Ground length of one segment in the project unit. */
  step: number;
  segments: number;
  unit: string;
  /** Paper length of one segment and of the bar, mm. */
  segmentMm: number;
  lengthMm: number;
}

/** A 1-2-5 stepped bar with `segments` parts, as long as fits in `maxMm`, in the project linear unit. */
export function scaleBar(scale: number, maxMm: number, conv: Pick<PlanConventions, 'linearUnit'>, segments = 4): ScaleBar {
  const perUnit = METRES_PER[conv.linearUnit];
  const mmPerUnit = (perUnit * 1000) / scale;
  const target = maxMm / segments / mmPerUnit;
  let step = 1;
  for (let exp = -3; exp <= 6; exp++) {
    for (const m of [1, 2, 5]) {
      const c = m * 10 ** exp;
      if (c <= target + 1e-9) step = c;
    }
  }
  const segmentMm = step * mmPerUnit;
  return { step, segments, unit: LINEAR_SYMBOL[conv.linearUnit], segmentMm, lengthMm: segmentMm * segments };
}

// ── Coordinate grid ───────────────────────────────────────────────────────

/** A grid step that gives 4..10 lines across the frame (50 m and 100 m at the usual site scales). */
export function gridStepFor(v: View): number {
  const [x0, , x1] = viewExtent(v);
  const span = x1 - x0;
  for (const s of [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]) if (span / s <= 10) return s;
  return 10000;
}

export function gridLines(v: View, step: number): { e: number[]; n: number[] } {
  const [x0, y0, x1, y1] = viewExtent(v);
  const e: number[] = [], n: number[] = [];
  for (let x = Math.ceil(x0 / step) * step; x <= x1; x += step) e.push(x);
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) n.push(y);
  return { e, n };
}

// ── Clipping ──────────────────────────────────────────────────────────────

/** Liang-Barsky clip of a segment to a rectangle; null when outside. */
export function clipSegment(a: [number, number], b: [number, number], r: Rect): [[number, number], [number, number]] | null {
  let t0 = 0, t1 = 1;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const tests: Array<[number, number]> = [[-dx, a[0] - r.x], [dx, r.x + r.w - a[0]], [-dy, a[1] - r.y], [dy, r.y + r.h - a[1]]];
  for (const [p, q] of tests) {
    if (p === 0) {
      if (q < 0) return null;
    } else {
      const t = q / p;
      if (p < 0) t0 = Math.max(t0, t);
      else t1 = Math.min(t1, t);
      if (t0 > t1) return null;
    }
  }
  return [[a[0] + t0 * dx, a[1] + t0 * dy], [a[0] + t1 * dx, a[1] + t1 * dy]];
}

/** Sutherland-Hodgman clip of a polygon to a rectangle. */
export function clipPolygon(ring: Array<[number, number]>, r: Rect): Array<[number, number]> {
  const edges: Array<(p: [number, number]) => number> = [
    (p) => p[0] - r.x, (p) => r.x + r.w - p[0], (p) => p[1] - r.y, (p) => r.y + r.h - p[1],
  ];
  let out = ring;
  for (const side of edges) {
    if (!out.length) break;
    const input = out;
    out = [];
    for (let i = 0; i < input.length; i++) {
      const cur = input[i]!, prev = input[(i + input.length - 1) % input.length]!;
      const dc = side(cur), dp = side(prev);
      if (dc >= 0) {
        if (dp < 0) out.push(lerp(prev, cur, dp / (dp - dc)));
        out.push(cur);
      } else if (dp >= 0) {
        out.push(lerp(prev, cur, dp / (dp - dc)));
      }
    }
  }
  return out;
}

const lerp = (a: [number, number], b: [number, number], t: number): [number, number] => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

// ── Labels ────────────────────────────────────────────────────────────────

export interface LabelCandidate {
  text: string;
  /** Anchor on paper, mm. */
  x: number;
  y: number;
  sizePt: number;
  priority: number;
}

export interface PlacedLabel extends LabelCandidate {
  box: Rect;
  /** Baseline-left of the text. */
  tx: number;
  ty: number;
}

export function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Text width in mm; jsPDF's metric when a document is given, else a Helvetica estimate. */
export type Measure = (text: string, sizePt: number) => number;
export const estimateWidth: Measure = (text, sizePt) => text.length * sizePt * PT_MM * 0.52;

/**
 * Greedy placement by priority: each label tries eight positions round its
 * anchor and is dropped if every one collides with a placed label, an
 * obstacle (title column, scale bar) or leaves the frame. Printed labels never overlap.
 */
export function placeLabels(cands: readonly LabelCandidate[], frame: Rect, obstacles: readonly Rect[] = [], measure: Measure = estimateWidth): PlacedLabel[] {
  const placed: PlacedLabel[] = [];
  const order = [...cands].sort((a, b) => b.priority - a.priority);
  for (const c of order) {
    const w = measure(c.text, c.sizePt), h = c.sizePt * PT_MM;
    const g = 0.8;
    const spots: Array<[number, number]> = [
      [c.x + g, c.y - g - h], [c.x - g - w, c.y - g - h], [c.x + g, c.y + g], [c.x - g - w, c.y + g],
      [c.x - w / 2, c.y - g - h], [c.x - w / 2, c.y + g], [c.x + g, c.y - h / 2], [c.x - g - w, c.y - h / 2],
    ];
    for (const [x, y] of spots) {
      const box = { x, y, w, h };
      const inFrame = x >= frame.x && y >= frame.y && x + w <= frame.x + frame.w && y + h <= frame.y + frame.h;
      if (!inFrame || obstacles.some((o) => overlaps(o, box)) || placed.some((p) => overlaps(p.box, box))) continue;
      placed.push({ ...c, box, tx: x, ty: y + h * 0.8 });
      break;
    }
  }
  return placed;
}

// ── Print model ───────────────────────────────────────────────────────────

export interface PrintLayer {
  id: string;
  title: string;
  /** CSS colour (hex or rgb()) from the map palette. */
  colour: string;
  features: PlanFeature[];
  lineMm?: number;
  dashed?: boolean;
  /** Fill polygons with a light tint of the colour. */
  fill?: boolean;
  labelPriority?: number;
  /** Legend glyph. */
  legend?: 'line' | 'swatch' | 'point';
}

export interface PlanPrintSpec {
  paper: PaperId;
  orientation: 'landscape' | 'portrait';
  scale: number;
  centre: GridXY;
  layers: PrintLayer[];
  title: TitleBlockData;
  conventions: PlanConventions;
  /** Degrees from true north to grid north at the plan centre; null on a local grid. */
  convergenceDeg: number | null;
  /** A raster under the vector layers (shaded relief), placed by its grid bounds. */
  relief?: { dataUrl: string; bounds: [number, number, number, number] } | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function rgb(css: string): [number, number, number] {
  const s = css.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (hex) {
    const h = hex[1]!.length === 3 ? hex[1]!.split('').map((c) => c + c).join('') : hex[1]!;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(s);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [60, 60, 60];
}

const tintOf = (c: [number, number, number], k = 0.85): [number, number, number] => [c[0] + (255 - c[0]) * k, c[1] + (255 - c[1]) * k, c[2] + (255 - c[2]) * k];

/** Text that Helvetica cannot draw goes through a canvas image so names in any script print. */
function needsRaster(text: string): boolean {
  return /[^\u0000-ÿ]/.test(text);
}

export function drawText(doc: jsPDF, text: string, x: number, y: number, sizePt: number, opts: { align?: 'left' | 'right' | 'center'; bold?: boolean } = {}): void {
  if (!text) return;
  if (!needsRaster(text) || typeof document === 'undefined') {
    doc.setFont('helvetica', opts.bold ? 'bold' : 'normal');
    doc.setFontSize(sizePt);
    doc.text(text, x, y, { align: opts.align ?? 'left', baseline: 'alphabetic' });
    return;
  }
  const px = 4 * sizePt;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const font = `${opts.bold ? '600 ' : ''}${px}px sans-serif`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + 2;
  canvas.width = w;
  canvas.height = Math.ceil(px * 1.3);
  ctx.font = font;
  ctx.fillStyle = '#1d1d1f';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, 1, px);
  const mmH = (canvas.height / px) * sizePt * PT_MM;
  const mmW = (w / canvas.height) * mmH;
  const left = opts.align === 'right' ? x - mmW : opts.align === 'center' ? x - mmW / 2 : x;
  doc.addImage(canvas.toDataURL('image/png'), 'PNG', left, y - sizePt * PT_MM, mmW, mmH);
}

function strokePath(doc: jsPDF, pts: Array<[number, number]>, closed: boolean, frame: Rect): void {
  const n = pts.length;
  const last = closed ? n : n - 1;
  for (let i = 0; i < last; i++) {
    const seg = clipSegment(pts[i]!, pts[(i + 1) % n]!, frame);
    if (seg) doc.line(seg[0][0], seg[0][1], seg[1][0], seg[1][1]);
  }
}

function fillPolygon(doc: jsPDF, pts: Array<[number, number]>): void {
  if (pts.length < 3) return;
  const [x0, y0] = pts[0]!;
  const deltas = pts.slice(1).map((p, i) => [p[0] - pts[i]![0], p[1] - pts[i]![1]]);
  doc.lines(deltas, x0, y0, [1, 1], 'F', true);
}

/** Label text and priority of a feature, or null. */
function labelOf(f: PlanFeature): string | null {
  const l = f.properties.label;
  return l == null || l === '' ? null : String(l);
}

/** Anchor of a feature's label: the point itself, a polygon's box centre, a line's middle vertex. */
function anchorOf(f: PlanFeature): GridXYZ | null {
  const g = f.geometry;
  if (g.type === 'Point') return g.coordinates;
  const pts = g.type === 'Polygon' ? g.coordinates[0] ?? [] : g.coordinates;
  if (!pts.length) return null;
  if (g.type === 'LineString') return pts[Math.floor(pts.length / 2)]!;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of pts) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

/** Draw the whole plan on a fresh page of `doc`. Returns the labels that made it, for tests and the preview. */
export function drawPlan(doc: jsPDF, spec: PlanPrintSpec): { placed: PlacedLabel[]; dropped: number; bar: ScaleBar } {
  const page = pageLayout(spec.paper, spec.orientation);
  const view: View = { centre: spec.centre, scale: spec.scale, frame: page.frame };
  const conv = spec.conventions;
  const ink = rgb('#1d1d1f');

  if (spec.relief) {
    const [e0, n0, e1, n1] = spec.relief.bounds;
    const [x0, y0] = toPaper([e0, n1], view);
    const [x1, y1] = toPaper([e1, n0], view);
    doc.saveGraphicsState();
    doc.rect(page.frame.x, page.frame.y, page.frame.w, page.frame.h, null);
    doc.clip();
    doc.discardPath();
    doc.addImage(spec.relief.dataUrl, 'PNG', x0, y0, x1 - x0, y1 - y0);
    doc.restoreGraphicsState();
  }

  // Coordinate grid: hairlines with labelled ticks on the frame edge.
  const step = gridStepFor(view);
  const grid = gridLines(view, step);
  const axes = axisLabelFor(conv.axis);
  doc.setDrawColor(200, 200, 200);
  doc.setLineWidth(0.1);
  for (const e of grid.e) {
    const [x] = toPaper([e, 0], view);
    doc.line(x, page.frame.y, x, page.frame.y + page.frame.h);
    drawText(doc, `${axes.e} ${formatCoord(e, { ...conv, precision: 'mm' }).replace(/[.,]0+(?=\D*$)/, '')}`, x + 0.6, page.frame.y + 2.4, 5);
  }
  for (const n of grid.n) {
    const [, y] = toPaper([0, n], view);
    doc.line(page.frame.x, y, page.frame.x + page.frame.w, y);
    drawText(doc, `${axes.n} ${formatCoord(n, { ...conv, precision: 'mm' }).replace(/[.,]0+(?=\D*$)/, '')}`, page.frame.x + 0.8, y - 0.6, 5);
  }

  // Layers, bottom up.
  const cands: LabelCandidate[] = [];
  for (const layer of spec.layers) {
    const c = rgb(layer.colour);
    doc.setDrawColor(c[0], c[1], c[2]);
    doc.setLineWidth(layer.lineMm ?? 0.25);
    doc.setLineDashPattern(layer.dashed ? [1.5, 1] : [], 0);
    for (const f of layer.features) {
      const g = f.geometry;
      if (g.type === 'Point') {
        const [x, y] = toPaper(g.coordinates, view);
        if (x < page.frame.x || x > page.frame.x + page.frame.w || y < page.frame.y || y > page.frame.y + page.frame.h) continue;
        doc.setFillColor(c[0], c[1], c[2]);
        doc.circle(x, y, 0.5, 'F');
      } else if (g.type === 'LineString') {
        strokePath(doc, g.coordinates.map((p) => toPaper(p, view)), false, page.frame);
      } else {
        const ring = (g.coordinates[0] ?? []).map((p) => toPaper(p, view));
        if (layer.fill) {
          const t = tintOf(c);
          doc.setFillColor(t[0], t[1], t[2]);
          fillPolygon(doc, clipPolygon(ring, page.frame));
        }
        strokePath(doc, ring, true, page.frame);
      }
      const text = labelOf(f);
      const at = text ? anchorOf(f) : null;
      if (text && at) {
        const [x, y] = toPaper(at, view);
        cands.push({ text, x, y, sizePt: g.type === 'Polygon' ? 7 : 6, priority: layer.labelPriority ?? 40 });
      }
    }
  }
  doc.setLineDashPattern([], 0);

  const placed = placeLabels(cands, page.frame);
  doc.setTextColor(ink[0], ink[1], ink[2]);
  for (const l of placed) drawText(doc, l.text, l.tx, l.ty, l.sizePt);

  // Neat line of the frame.
  doc.setDrawColor(ink[0], ink[1], ink[2]);
  doc.setLineWidth(0.5);
  doc.rect(page.frame.x, page.frame.y, page.frame.w, page.frame.h, 'S');

  // Title column: title block on top, legend, north arrow and scale bar at the foot.
  const col = page.title;
  const used = drawTitleBlock(doc, col, spec.title, spec.t, spec.scale);
  const legendTop = col.y + used + 4;
  drawLegend(doc, { x: col.x + 3, y: legendTop, w: col.w - 6, h: 0 }, spec.layers, spec.t);
  const bar = scaleBar(spec.scale, col.w - 12, conv);
  drawScaleBar(doc, col.x + 4, col.y + col.h - 8, bar, spec.t);
  drawNorthArrow(doc, col.x + col.w / 2, col.y + col.h - 34, spec.convergenceDeg, conv, spec.t);
  doc.setLineWidth(0.5);
  doc.rect(col.x, col.y, col.w, col.h, 'S');
  return { placed, dropped: cands.length - placed.length, bar };
}

function drawLegend(doc: jsPDF, r: Rect, layers: readonly PrintLayer[], t: PlanPrintSpec['t']): void {
  drawText(doc, t('plan.print.legend', { defaultValue: 'Legend' }), r.x, r.y + 3, 8, { bold: true });
  let y = r.y + 8;
  for (const l of layers) {
    if (!l.features.length) continue;
    const c = rgb(l.colour);
    doc.setDrawColor(c[0], c[1], c[2]);
    doc.setFillColor(...tintOf(c, l.legend === 'swatch' ? 0.6 : 0));
    doc.setLineWidth(l.lineMm ?? 0.25);
    doc.setLineDashPattern(l.dashed ? [1.5, 1] : [], 0);
    if (l.legend === 'swatch') doc.rect(r.x, y - 2.4, 6, 3, 'FD');
    else if (l.legend === 'point') doc.circle(r.x + 3, y - 1, 0.7, 'F');
    else doc.line(r.x, y - 1, r.x + 6, y - 1);
    doc.setLineDashPattern([], 0);
    doc.setTextColor(29, 29, 31);
    drawText(doc, l.title, r.x + 8, y, 6.5);
    y += 4.5;
  }
}

function drawScaleBar(doc: jsPDF, x: number, y: number, bar: ScaleBar, t: PlanPrintSpec['t']): void {
  doc.setDrawColor(29, 29, 31);
  doc.setLineWidth(0.2);
  for (let i = 0; i < bar.segments; i++) {
    const sx = x + i * bar.segmentMm;
    if (i % 2 === 0) doc.setFillColor(29, 29, 31);
    else doc.setFillColor(255, 255, 255);
    doc.rect(sx, y, bar.segmentMm, 1.5, 'FD');
  }
  doc.setTextColor(29, 29, 31);
  for (let i = 0; i <= bar.segments; i++) {
    const v = Number((i * bar.step).toPrecision(6));
    drawText(doc, i === bar.segments ? `${v} ${bar.unit}` : String(v), x + i * bar.segmentMm, y - 1, 5.5, { align: i === 0 ? 'left' : 'center' });
  }
  drawText(doc, t('plan.print.scale_bar', { defaultValue: 'Scale bar' }), x, y + 5, 5.5);
}

/**
 * Grid north points up the sheet. With a projected CRS a thin line shows true
 * north, turned by the convergence, and the note states it in the project angle unit.
 */
function drawNorthArrow(doc: jsPDF, cx: number, cy: number, gamma: number | null, conv: PlanConventions, t: PlanPrintSpec['t']): void {
  doc.setDrawColor(29, 29, 31);
  doc.setFillColor(29, 29, 31);
  doc.setLineWidth(0.3);
  doc.triangle(cx, cy - 9, cx - 3, cy + 3, cx, cy, 'F');
  doc.triangle(cx, cy - 9, cx + 3, cy + 3, cx, cy, 'S');
  drawText(doc, t('plan.print.grid_north_short', { defaultValue: 'GN' }), cx, cy - 10.5, 7, { align: 'center', bold: true });
  if (gamma != null && Number.isFinite(gamma)) {
    // True north lies gamma degrees anticlockwise of grid north when gamma is positive.
    const a = (-gamma * Math.PI) / 180;
    const len = 8;
    doc.setLineWidth(0.15);
    doc.line(cx, cy, cx + Math.sin(a) * len, cy - Math.cos(a) * len);
    const side = gamma >= 0
      ? t('plan.print.west', { defaultValue: 'west' })
      : t('plan.print.east', { defaultValue: 'east' });
    drawText(doc, t('plan.print.convergence_note', {
      defaultValue: 'True north {{angle}} {{side}} of grid north',
      angle: formatAngle(Math.abs(gamma), conv.angleUnit, conv.angleDecimals),
      side,
    }), cx, cy + 7, 5.5, { align: 'center' });
  } else {
    drawText(doc, t('plan.print.local_grid_note', { defaultValue: 'Local grid: north is the grid north of the site' }), cx, cy + 7, 5.5, { align: 'center' });
  }
}

/** Builds the PDF and returns it as a Blob. jsPDF loads on demand. */
export async function renderPlanPdf(spec: PlanPrintSpec): Promise<{ blob: Blob; dropped: number }> {
  const { jsPDF } = await import('jspdf');
  const page = pageLayout(spec.paper, spec.orientation);
  const doc = new jsPDF({ unit: 'mm', format: [page.width, page.height], orientation: spec.orientation, compress: true });
  const res = drawPlan(doc, spec);
  return { blob: doc.output('blob'), dropped: res.dropped };
}

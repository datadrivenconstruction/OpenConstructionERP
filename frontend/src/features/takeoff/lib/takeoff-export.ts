// OpenConstructionERP — DataDrivenConstruction (DDC)
// CAD2DATA Pipeline · PDF Takeoff Module · Export helpers
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
/**
 * Client-side export helpers for the PDF takeoff viewer.
 *
 * Two flavours are exposed:
 *   - `buildTakeoffPdf` — rasterises each annotated PDF page (via the
 *     existing PDF.js doc + a shared canvas overlay renderer) into a
 *     downloadable jsPDF document with baked annotations + a summary
 *     page at the end.
 *   - `buildTakeoffWorkbook` — produces a 2-sheet exceljs workbook
 *     ("Measurements" + "Summary") with group-coloured subtotal rows.
 *
 * Both flavours respect visibility — only measurements whose group is
 * **not** in `hiddenGroups` and whose id is **not** in
 * `hiddenMeasurements` are baked into the PDF, matching the live canvas
 * overlay's filter rule in `TakeoffViewerModule.tsx`. Visibility is a
 * view concern: it never touches the CSV/XLSX/BOQ data exports.
 *
 * The renderer in `renderMeasurementsOnCanvas` is a verbatim port of
 * the inline overlay-drawing logic in `TakeoffViewerModule.tsx`
 * (`useEffect` around line 561) — keeping the visual fidelity 1:1.
 * Any future tweak to the live overlay rendering should be mirrored
 * here so the exported PDF matches what the user sees on screen.
 */

import type { jsPDF as JsPDF } from 'jspdf';
import type * as ExcelJS from 'exceljs';
import type * as PdfJsLib from 'pdfjs-dist';
import type { Measurement } from './takeoff-types';
import { groupBands, sortByPaintOrder } from './takeoff-order';
import type { ScaleConfig } from '../../../modules/pdf-takeoff/data/scale-helpers';
import {
  pixelDistance,
  toRealDistance,
} from '../../../modules/pdf-takeoff/data/scale-helpers';
import { ANNOTATION_TYPES } from './takeoff-groups';
import { effectiveQuantity, effectiveUnit, isWallMeasurement, reportingType } from './takeoff-quantity';
import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import {
  convertQuantity,
  formatQuantity,
  measurementLabel,
} from './takeoff-display-units';

/** Shared empty id set so a caller that hides no individual measurement
 *  (every existing caller, and every test) behaves exactly as before. */
const NO_HIDDEN_MEASUREMENTS: ReadonlySet<string> = new Set<string>();

/* ── Public types ────────────────────────────────────────────────── */

export interface ExportContext {
  /** Project display name for the filename + workbook header. */
  projectName: string;
  /** Today's date (override-able for tests). Defaults to current day. */
  exportDate?: Date;
  /** User's measurement system. Stored quantities are metric-canonical
   *  (D-TKC-016); when `imperial`, values + units are converted (m -> ft,
   *  m² -> ft², m³ -> ft³) at the export boundary. Defaults to `metric`
   *  (pass-through), so omitting it leaves the export byte-for-byte as
   *  before this seam existed. */
  measurementSystem?: MeasurementSystem;
}

export interface PdfExportContext extends ExportContext {
  /** Loaded PDF.js document — pages will be rendered to image. */
  pdfDoc: PdfJsLib.PDFDocumentProxy;
  /** All measurements (annotations + numeric). */
  measurements: Measurement[];
  /** Groups hidden in the UI — excluded from the bake. */
  hiddenGroups: ReadonlySet<string>;
  /** Individual measurements hidden in the UI (by id) — excluded from the
   *  bake, alongside hiddenGroups (issue #359). Optional: omit for the
   *  pre-existing group-only behaviour. View concern, not a data concern. */
  hiddenMeasurements?: ReadonlySet<string>;
  /** Calibrated scale (defines unit suffix on labels). */
  scale: ScaleConfig;
  /** Group → color map (matches `MEASUREMENT_GROUPS` in the viewer). */
  groupColorMap: Readonly<Record<string, string>>;
  /** Rendering scale for the rasterised PDF page (default 1.5). */
  renderScale?: number;
  /** JPEG quality 0..1 (default 0.85). */
  jpegQuality?: number;
}

export interface ExcelExportContext extends ExportContext {
  measurements: Measurement[];
  /** Used to surface the calibrated unit on subtotal rows. */
  scale: ScaleConfig;
  /** Group → color map (used for header row tint). */
  groupColorMap: Readonly<Record<string, string>>;
}

/** Predicate: is this measurement type an annotation (non-numeric)? */
export const isAnnotationType = (type: string): boolean =>
  ANNOTATION_TYPES.has(type);

/** Human wording for a stored scale provenance, for the exported sheet.
 *
 * The rest of the workbook is written in English regardless of UI locale, so
 * this deliberately does not go through i18n. A row with no recorded source,
 * or one carrying a value added server-side ahead of this client, reads
 * "Unknown" rather than as an empty cell: a blank looks like a column that
 * failed to populate, while "Unknown" is a statement about the measurement. */
export function scaleSourceLabel(source: string | undefined | null): string {
  switch (source) {
    case 'manual_calibration':
      return 'Calibrated on this sheet';
    case 'preset':
      return 'Document scale';
    case 'inherited':
      return "Inherited from the sheet's scale";
    case 'page_text':
      return 'Read from the drawing text';
    case 'recovered_text':
      return 'Recovered from the sheet by OCR';
    case 'vision_read':
      return 'Read from the drawing by the model';
    default:
      return 'Unknown';
  }
}

/* ── Filename ────────────────────────────────────────────────────── */

/**
 * Build a deterministic, filesystem-safe export filename.
 *
 * `takeoff-{slug(projectName)}-{YYYY-MM-DD}.{ext}` — slug strips/replaces
 * non-alphanumeric characters with `_`, collapses repeats, and trims
 * leading/trailing separators. Empty project name falls back to
 * "untitled" so the filename remains predictable.
 */
export function buildExportFilename(
  projectName: string,
  ext: 'pdf' | 'xlsx',
  date: Date = new Date(),
): string {
  // Preserve unicode letters (Cyrillic, CJK, accented Latin) by skipping
  // NFKD decomposition — `São Paulo` should slug to `são_paulo`, not
  // `sa_o_paulo`.  Filesystems on all three OS targets (Win/macOS/Linux)
  // accept UTF-8 letters in filenames; trim only ASCII punctuation +
  // whitespace via the Unicode property escapes.
  const slug = (projectName || 'untitled')
    .replace(/[^\p{L}\p{N}]+/gu, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
    .toLowerCase() || 'untitled';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `takeoff-${slug}-${yyyy}-${mm}-${dd}.${ext}`;
}

/* ── Summary ─────────────────────────────────────────────────────── */

export interface GroupTypeTotal {
  group: string;
  type: string;
  count: number;
  /** Sum of `value` across this (group, type) bucket. */
  total: number;
  /** Most common unit string in this bucket. */
  unit: string;
  /** Hex color for the group. */
  color: string;
}

/**
 * Aggregate measurements by (group, type) — drives the PDF summary
 * page and Excel "Summary" sheet pivot.  Annotation types are still
 * counted, but their `total` is reported as 0 (no numeric value).
 */
export function summariseByGroupType(
  measurements: Measurement[],
  groupColorMap: Readonly<Record<string, string>>,
  fallbackColor: string = '#3B82F6',
): GroupTypeTotal[] {
  const byKey = new Map<
    string,
    { group: string; type: string; count: number; total: number; units: Record<string, number> }
  >();
  for (const m of measurements) {
    const group = m.group || 'General';
    // A wall reports area, so it totals under `area` rather than as a length.
    const type = reportingType(m);
    const key = `${group}::${type}`;
    const existing = byKey.get(key) ?? {
      group,
      type,
      count: 0,
      total: 0,
      units: {} as Record<string, number>,
    };
    existing.count += 1;
    if (!isAnnotationType(m.type)) {
      // Effective quantity folds slope / wastage / typical-multiplier and the
      // opening-deduction sign, so the exported (group, type) total is the NET
      // reported figure, matching the legend and ledger.
      existing.total += effectiveQuantity(m);
      const unit = effectiveUnit(m);
      if (unit) existing.units[unit] = (existing.units[unit] ?? 0) + 1;
    }
    byKey.set(key, existing);
  }
  const rows: GroupTypeTotal[] = [];
  for (const { group, type, count, total, units } of byKey.values()) {
    const unitEntries = Object.entries(units);
    unitEntries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const unit = unitEntries[0]?.[0] ?? '';
    rows.push({
      group,
      type,
      count,
      total,
      unit,
      color: groupColorMap[group] ?? fallbackColor,
    });
  }
  rows.sort((a, b) => a.group.localeCompare(b.group) || a.type.localeCompare(b.type));
  return rows;
}

/* ── Canvas measurement renderer (export-side) ───────────────────── */

/**
 * Render measurements onto a 2D canvas context.
 *
 * This is a pure mirror of the live overlay rendering in
 * `TakeoffViewerModule.tsx` (search for "Draw overlay"), extracted so the
 * PDF exporter can produce a frame that visually matches what the user
 * sees on screen.  Caller is responsible for clearing/sizing the canvas
 * before calling.
 *
 * Coordinates are translated as `x * dpr * zoom` — same as the live
 * overlay.  Annotations are drawn over the page raster, with measurement
 * value labels and group-coloured annotation chips.
 */
export function renderMeasurementsOnCanvas(
  ctx: CanvasRenderingContext2D,
  measurements: Measurement[],
  options: {
    pageNumber: number;
    dpr: number;
    zoom: number;
    scale: ScaleConfig;
    groupColorMap: Readonly<Record<string, string>>;
    hiddenGroups: ReadonlySet<string>;
    /** Individual measurements hidden by id (issue #359). Defaults to none. */
    hiddenMeasurements?: ReadonlySet<string>;
    /** Measurement system for the baked value labels. Defaults to metric
     *  (uses the stored metric labels verbatim). */
    measurementSystem?: MeasurementSystem;
  },
): void {
  const { pageNumber, dpr, zoom, scale, groupColorMap, hiddenGroups } = options;
  const hiddenMeasurements = options.hiddenMeasurements ?? NO_HIDDEN_MEASUREMENTS;
  const system: MeasurementSystem = options.measurementSystem ?? 'metric';
  ctx.lineWidth = 2 * dpr;
  ctx.font = `${12 * dpr}px sans-serif`;

  const drawLabel = (text: string, lx: number, ly: number, color: string): void => {
    const fontSize = 11 * dpr;
    ctx.font = `bold ${fontSize}px sans-serif`;
    const metrics = ctx.measureText(text);
    const padX = 4 * dpr;
    const padY = 2 * dpr;
    const boxW = metrics.width + padX * 2;
    const boxH = fontSize + padY * 2;
    const bx = lx - padX;
    const by = ly - fontSize - padY;
    ctx.globalAlpha = 0.85;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(bx, by, boxW, boxH);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1 * dpr;
    ctx.strokeRect(bx, by, boxW, boxH);
    ctx.fillStyle = color;
    ctx.fillText(text, lx, ly - padY);
    ctx.lineWidth = 2 * dpr;
  };

  // Paint in the same z-order the on-screen canvas uses (issue #379) so the
  // exported PDF matches the screen: an explicit `order` decides which shape
  // draws on top; un-ordered rows keep array (creation) order. Banded by group
  // like the canvas (issue #394); the bands are derived from the full
  // measurement list rather than the page subset, because the band map is per
  // document and deriving it per page would give the same group a different
  // band on every sheet.
  const visible = sortByPaintOrder(measurements, groupBands(measurements)).filter(
    (m) =>
      m.page === pageNumber &&
      !hiddenGroups.has(m.group) &&
      !hiddenMeasurements.has(m.id) &&
      !(isAnnotationType(m.type) && hiddenGroups.has('__annotations__')),
  );

  for (const m of visible) {
    // A per-measurement colour (set via the properties swatch) wins over the
    // group default so a recoloured measurement exports in its chosen colour
    // (issue #299); annotation markups already resolve `m.color` below.
    const color = m.color || groupColorMap[m.group] || '#3B82F6';
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    // Per-measurement stroke width (issue #312); defaults to the 2px hairline
    // so the export matches the on-screen canvas. Scales with zoom (issue #321)
    // to stay in document space, keeping the export a mirror of the overlay.
    ctx.lineWidth = (m.strokeWidth ?? 2) * dpr * zoom;

    if (m.type === 'distance' && m.points.length === 2) {
      const p0 = m.points[0]!;
      const p1 = m.points[1]!;
      ctx.beginPath();
      ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
      ctx.lineTo(p1.x * dpr * zoom, p1.y * dpr * zoom);
      // Per-measurement line opacity (issue #332); unset = fully opaque so the
      // export is unchanged for a line that never got a stroke-opacity.
      ctx.globalAlpha = m.strokeAlpha ?? 1;
      ctx.stroke();
      ctx.globalAlpha = 1;
      const mx = ((p0.x + p1.x) / 2) * dpr * zoom;
      const my = ((p0.y + p1.y) / 2) * dpr * zoom - 8 * dpr;
      ctx.font = `${12 * dpr}px sans-serif`;
      ctx.fillText(measurementLabel(m, scale, system), mx, my);
      drawLabel(m.annotation, mx, my - 14 * dpr, color);
      continue;
    }

    if (m.type === 'polyline' && m.points.length >= 2) {
      const p0 = m.points[0]!;
      ctx.beginPath();
      ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
      for (let i = 1; i < m.points.length; i++) {
        const pt = m.points[i]!;
        ctx.lineTo(pt.x * dpr * zoom, pt.y * dpr * zoom);
      }
      // Per-measurement line opacity (issue #332); reset to opaque after so the
      // per-segment labels + vertex dots below are unaffected.
      ctx.globalAlpha = m.strokeAlpha ?? 1;
      ctx.stroke();
      ctx.globalAlpha = 1;
      for (let i = 0; i < m.points.length - 1; i++) {
        const pa = m.points[i]!;
        const pb = m.points[i + 1]!;
        const segDist = pixelDistance(pa.x, pa.y, pb.x, pb.y);
        const segReal = toRealDistance(segDist, scale);
        const smx = ((pa.x + pb.x) / 2) * dpr * zoom;
        const smy = ((pa.y + pb.y) / 2) * dpr * zoom - 6 * dpr;
        ctx.font = `${10 * dpr}px sans-serif`;
        ctx.fillText(formatQuantity(segReal, 'm', system), smx, smy);
      }
      for (const p of m.points) {
        ctx.beginPath();
        ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 3 * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
      const fp = m.points[0]!;
      const totalLx = fp.x * dpr * zoom;
      const totalLy = fp.y * dpr * zoom - 12 * dpr;
      ctx.font = `${12 * dpr}px sans-serif`;
      ctx.fillText(measurementLabel(m, scale, system), totalLx, totalLy);
      drawLabel(m.annotation, totalLx, totalLy - 14 * dpr, color);
      continue;
    }

    if ((m.type === 'area' || m.type === 'volume') && m.points.length >= 3) {
      const firstPt = m.points[0]!;
      ctx.beginPath();
      ctx.moveTo(firstPt.x * dpr * zoom, firstPt.y * dpr * zoom);
      for (let i = 1; i < m.points.length; i++) {
        const pt = m.points[i]!;
        ctx.lineTo(pt.x * dpr * zoom, pt.y * dpr * zoom);
      }
      ctx.closePath();
      ctx.globalAlpha = m.fillAlpha ?? 0.15;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.stroke();
      const cx =
        (m.points.reduce((s, p) => s + p.x, 0) / m.points.length) * dpr * zoom;
      const cy =
        (m.points.reduce((s, p) => s + p.y, 0) / m.points.length) * dpr * zoom;
      ctx.font = `${12 * dpr}px sans-serif`;
      ctx.fillText(measurementLabel(m, scale, system), cx, cy);
      drawLabel(m.annotation, cx, cy - 14 * dpr, color);
      continue;
    }

    if (m.type === 'count') {
      for (const p of m.points) {
        ctx.beginPath();
        ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 8 * dpr, 0, Math.PI * 2);
        ctx.globalAlpha = m.fillAlpha ?? 0.3;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.stroke();
      }
      if (m.points.length > 0) {
        const fp = m.points[0]!;
        drawLabel(
          `${m.annotation} (${m.points.length})`,
          fp.x * dpr * zoom + 12 * dpr,
          fp.y * dpr * zoom - 4 * dpr,
          color,
        );
      }
      continue;
    }

    /* ── Annotation markup ────────────────────────────────────── */
    const annoColor = m.color || color;

    if (m.type === 'cloud' && m.points.length >= 3) {
      ctx.strokeStyle = annoColor;
      ctx.lineWidth = 2.5 * dpr;
      ctx.beginPath();
      const pts = m.points;
      for (let i = 0; i < pts.length; i++) {
        const pA = pts[i]!;
        const pB = pts[(i + 1) % pts.length]!;
        const ax = pA.x * dpr * zoom;
        const ay = pA.y * dpr * zoom;
        const bx = pB.x * dpr * zoom;
        const by = pB.y * dpr * zoom;
        const segLen = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
        const arcCount = Math.max(2, Math.round(segLen / (18 * dpr)));
        for (let j = 0; j < arcCount; j++) {
          const t0 = j / arcCount;
          const t1 = (j + 1) / arcCount;
          const x0 = ax + (bx - ax) * t0;
          const y0 = ay + (by - ay) * t0;
          const x1 = ax + (bx - ax) * t1;
          const y1 = ay + (by - ay) * t1;
          const cpx = (x0 + x1) / 2;
          const cpy = (y0 + y1) / 2;
          const dx = x1 - x0;
          const dy = y1 - y0;
          const bumpSize = 6 * dpr;
          const centX =
            (pts.reduce((s, p) => s + p.x, 0) / pts.length) * dpr * zoom;
          const centY =
            (pts.reduce((s, p) => s + p.y, 0) / pts.length) * dpr * zoom;
          const midToCentX = centX - cpx;
          const midToCentY = centY - cpy;
          const perpX = -dy;
          const perpY = dx;
          const dot = perpX * midToCentX + perpY * midToCentY;
          const sign = dot > 0 ? -1 : 1;
          const len = Math.sqrt(perpX * perpX + perpY * perpY) || 1;
          const offX = ((sign * perpX) / len) * bumpSize;
          const offY = ((sign * perpY) / len) * bumpSize;
          ctx.moveTo(x0, y0);
          ctx.quadraticCurveTo(cpx + offX, cpy + offY, x1, y1);
        }
      }
      ctx.stroke();
      ctx.lineWidth = 2 * dpr;
      ctx.fillStyle = annoColor;
      ctx.globalAlpha = 0.06;
      ctx.beginPath();
      ctx.moveTo(pts[0]!.x * dpr * zoom, pts[0]!.y * dpr * zoom);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i]!.x * dpr * zoom, pts[i]!.y * dpr * zoom);
      }
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1;
      const centroidX =
        (pts.reduce((s, p) => s + p.x, 0) / pts.length) * dpr * zoom;
      const centroidY =
        (pts.reduce((s, p) => s + p.y, 0) / pts.length) * dpr * zoom;
      drawLabel(m.annotation, centroidX, centroidY, annoColor);
      continue;
    }

    if (m.type === 'arrow' && m.points.length === 2) {
      const p0 = m.points[0]!;
      const p1 = m.points[1]!;
      const x0 = p0.x * dpr * zoom;
      const y0 = p0.y * dpr * zoom;
      const x1 = p1.x * dpr * zoom;
      const y1 = p1.y * dpr * zoom;
      ctx.strokeStyle = annoColor;
      ctx.lineWidth = 2.5 * dpr;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
      const angle = Math.atan2(y1 - y0, x1 - x0);
      const headLen = 12 * dpr;
      ctx.fillStyle = annoColor;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(
        x1 - headLen * Math.cos(angle - Math.PI / 6),
        y1 - headLen * Math.sin(angle - Math.PI / 6),
      );
      ctx.lineTo(
        x1 - headLen * Math.cos(angle + Math.PI / 6),
        y1 - headLen * Math.sin(angle + Math.PI / 6),
      );
      ctx.closePath();
      ctx.fill();
      ctx.lineWidth = 2 * dpr;
      drawLabel(m.annotation, x0 + 8 * dpr, y0 - 8 * dpr, annoColor);
      continue;
    }

    if (m.type === 'text' && m.points.length >= 1) {
      const p = m.points[0]!;
      const tx = p.x * dpr * zoom;
      const ty = p.y * dpr * zoom;
      const textContent = m.text || m.annotation;
      const fontSize = 14 * dpr;
      ctx.font = `bold ${fontSize}px sans-serif`;
      ctx.fillStyle = annoColor;
      ctx.fillText(textContent, tx, ty);
      continue;
    }

    if (m.type === 'rectangle' && m.points.length === 2) {
      const p0 = m.points[0]!;
      const p1 = m.points[1]!;
      const rx = Math.min(p0.x, p1.x) * dpr * zoom;
      const ry = Math.min(p0.y, p1.y) * dpr * zoom;
      const rw = Math.abs(p1.x - p0.x) * dpr * zoom;
      const rh = Math.abs(p1.y - p0.y) * dpr * zoom;
      ctx.strokeStyle = annoColor;
      ctx.lineWidth = 2.5 * dpr;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.lineWidth = 2 * dpr;
      drawLabel(m.annotation, rx, ry - 4 * dpr, annoColor);
      continue;
    }

    if (m.type === 'highlight' && m.points.length === 2) {
      const p0 = m.points[0]!;
      const p1 = m.points[1]!;
      const rx = Math.min(p0.x, p1.x) * dpr * zoom;
      const ry = Math.min(p0.y, p1.y) * dpr * zoom;
      const rw = Math.abs(p1.x - p0.x) * dpr * zoom;
      const rh = Math.abs(p1.y - p0.y) * dpr * zoom;
      ctx.fillStyle = annoColor;
      ctx.globalAlpha = 0.25;
      ctx.fillRect(rx, ry, rw, rh);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = annoColor;
      ctx.lineWidth = 1 * dpr;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.lineWidth = 2 * dpr;
      drawLabel(m.annotation, rx, ry - 4 * dpr, annoColor);
      continue;
    }
  }
}

/* ── PDF builder ─────────────────────────────────────────────────── */

/**
 * Determine which pages contain at least one **visible** measurement
 * (any group not hidden).  Only these pages are baked into the PDF —
 * un-annotated pages are skipped to keep the file small.
 */
export function selectAnnotatedPages(
  measurements: Measurement[],
  hiddenGroups: ReadonlySet<string>,
  hiddenMeasurements: ReadonlySet<string> = NO_HIDDEN_MEASUREMENTS,
): number[] {
  const pages = new Set<number>();
  for (const m of measurements) {
    if (hiddenGroups.has(m.group)) continue;
    if (hiddenMeasurements.has(m.id)) continue;
    if (isAnnotationType(m.type) && hiddenGroups.has('__annotations__')) continue;
    pages.add(m.page);
  }
  return Array.from(pages).sort((a, b) => a - b);
}

/**
 * Build a PDF with baked-in annotations using jsPDF.
 *
 * For each annotated page, the PDF page raster is rendered to an
 * offscreen canvas at `renderScale` × the page's native size, the
 * overlay measurements are drawn on top using the same path as the
 * live viewer, the result is JPEG-encoded, and the image is added as
 * a jsPDF page sized + oriented to match the source page.  After all
 * pages, a final A4 summary page lists per-group counts and totals.
 *
 * jsPDF is imported lazily so the ~150 KB bundle isn't pulled into
 * the main viewer chunk on cold start.
 */
export async function buildTakeoffPdf(ctx: PdfExportContext): Promise<JsPDF> {
  const { default: JsPdfCtor } = await import('jspdf');
  const renderScale = ctx.renderScale ?? 1.5;
  const jpegQuality = ctx.jpegQuality ?? 0.85;
  const hiddenMeasurements = ctx.hiddenMeasurements ?? NO_HIDDEN_MEASUREMENTS;
  const pageNumbers = selectAnnotatedPages(ctx.measurements, ctx.hiddenGroups, hiddenMeasurements);

  // Honour the constructor signature; defaults overridden per page below.
  const pdf = new JsPdfCtor({ orientation: 'portrait', unit: 'pt', format: 'a4' });
  let firstPage = true;

  for (const pageNum of pageNumbers) {
    const page = await ctx.pdfDoc.getPage(pageNum);
    const viewport = page.getViewport({ scale: renderScale });
    const width = Math.ceil(viewport.width);
    const height = Math.ceil(viewport.height);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const canvasCtx = canvas.getContext('2d');
    if (!canvasCtx) throw new Error('Failed to acquire 2D context for PDF export');

    // Render the PDF page itself.
    await page.render({ canvas, viewport }).promise;

    // Bake the annotations on top — `zoom = renderScale`, `dpr = 1`
    // because we're authoring on a fresh canvas without device pixel
    // ratio scaling.
    renderMeasurementsOnCanvas(canvasCtx, ctx.measurements, {
      pageNumber: pageNum,
      dpr: 1,
      zoom: renderScale,
      scale: ctx.scale,
      groupColorMap: ctx.groupColorMap,
      hiddenGroups: ctx.hiddenGroups,
      hiddenMeasurements,
      measurementSystem: ctx.measurementSystem,
    });

    const imageData = canvas.toDataURL('image/jpeg', jpegQuality);
    const orientation: 'portrait' | 'landscape' = width > height ? 'landscape' : 'portrait';
    // Page dimensions in pt (1 pt = 1/72 in). We assume the rendered
    // viewport is already in CSS pixels at renderScale; convert by
    // dividing back to base px and treating 1 base px ≈ 1 pt for
    // visual fidelity (PDF-takeoff-tool-style 1:1 scaling).
    const pageWidth = width / renderScale;
    const pageHeight = height / renderScale;
    if (firstPage) {
      pdf.deletePage(1);
      firstPage = false;
    }
    pdf.addPage([pageWidth, pageHeight], orientation);
    pdf.addImage(imageData, 'JPEG', 0, 0, pageWidth, pageHeight, undefined, 'FAST');
  }

  // ── Summary page (always A4 portrait) ─────────────────────────
  if (firstPage) {
    // No annotated pages — keep the auto-generated first page for the summary.
    firstPage = false;
  } else {
    pdf.addPage('a4', 'portrait');
  }
  renderPdfSummary(pdf, ctx);

  return pdf;
}

/** Render the summary page (one-shot, A4 portrait, called by `buildTakeoffPdf`). */
function renderPdfSummary(pdf: JsPDF, ctx: PdfExportContext): void {
  const margin = 48;
  pdf.setFont('helvetica', 'bold');
  pdf.setFontSize(18);
  pdf.text('Takeoff Summary', margin, margin + 8);
  pdf.setFont('helvetica', 'normal');
  pdf.setFontSize(10);
  pdf.text(
    `Project: ${ctx.projectName || 'Untitled'}`,
    margin,
    margin + 28,
  );
  pdf.text(
    `Exported: ${(ctx.exportDate ?? new Date()).toISOString().slice(0, 10)}`,
    margin,
    margin + 42,
  );

  const hiddenMeasurements = ctx.hiddenMeasurements ?? NO_HIDDEN_MEASUREMENTS;
  const visibleMeasurements = ctx.measurements.filter(
    (m) =>
      !ctx.hiddenGroups.has(m.group) &&
      !hiddenMeasurements.has(m.id) &&
      !(isAnnotationType(m.type) && ctx.hiddenGroups.has('__annotations__')),
  );
  const rows = summariseByGroupType(visibleMeasurements, ctx.groupColorMap);

  // Table header
  let y = margin + 72;
  pdf.setFont('helvetica', 'bold');
  pdf.setFontSize(11);
  pdf.text('Group', margin, y);
  pdf.text('Type', margin + 130, y);
  pdf.text('Count', margin + 240, y);
  pdf.text('Total', margin + 300, y);
  pdf.text('Unit', margin + 400, y);
  y += 6;
  pdf.setDrawColor(180);
  pdf.line(margin, y, margin + 480, y);
  y += 14;

  const system: MeasurementSystem = ctx.measurementSystem ?? 'metric';
  pdf.setFont('helvetica', 'normal');
  pdf.setFontSize(10);
  for (const r of rows) {
    if (y > 770) {
      pdf.addPage('a4', 'portrait');
      y = margin;
    }
    // Group colour swatch.
    const rgb = hexToRgb(r.color);
    pdf.setFillColor(rgb.r, rgb.g, rgb.b);
    pdf.rect(margin - 14, y - 9, 8, 8, 'F');
    // Convert the canonical-metric total + unit to the export system.
    const disp = convertQuantity(r.total, r.unit, system);
    pdf.text(r.group, margin, y);
    pdf.text(r.type, margin + 130, y);
    pdf.text(String(r.count), margin + 240, y);
    pdf.text(
      isAnnotationType(r.type) ? '—' : formatNumberShort(disp.value),
      margin + 300,
      y,
    );
    pdf.text(disp.unit || '—', margin + 400, y);
    y += 16;
  }
}

/** Convert `#RRGGBB` to `{r, g, b}` channels. Returns black on parse failure. */
function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return { r: 0, g: 0, b: 0 };
  const v = parseInt(m[1]!, 16);
  return { r: (v >> 16) & 0xff, g: (v >> 8) & 0xff, b: v & 0xff };
}

/** Compact numeric formatter matching the legend's precision rules. */
function formatNumberShort(n: number): string {
  if (!Number.isFinite(n)) return '0';
  const precision = Math.abs(n) >= 100 ? 1 : Math.abs(n) >= 1 ? 2 : 3;
  return n.toFixed(precision);
}

/* ── Excel builder ───────────────────────────────────────────────── */

/**
 * Excel column layout for the "Measurements" sheet.  Order is
 * load-bearing — tests assert against it.
 */
export const EXCEL_COLUMNS = [
  { key: 'group', header: 'Group', width: 18 },
  { key: 'type', header: 'Type', width: 14 },
  { key: 'annotation', header: 'Annotation', width: 32 },
  { key: 'page', header: 'Page', width: 8 },
  { key: 'value', header: 'Value', width: 14 },
  { key: 'unit', header: 'Unit', width: 8 },
  { key: 'linkedBoq', header: 'Linked BOQ Position', width: 24 },
  // Where each row's ratio came from. A quantity is only as trustworthy as the
  // scale behind it, and this is the column that lets a reviewer sort a sheet
  // by provenance instead of taking every number on equal footing.
  { key: 'scaleSource', header: 'Scale From', width: 22 },
] as const;

/**
 * Build a takeoff workbook with two sheets:
 *   - Measurements — one row per measurement, grouped + subtotalled.
 *   - Summary — pivot by group × type.
 *
 * exceljs is imported lazily.
 */
export async function buildTakeoffWorkbook(
  ctx: ExcelExportContext,
): Promise<ExcelJS.Workbook> {
  const ExcelJsMod = await import('exceljs');
  const ExcelJsCtor = (ExcelJsMod.Workbook ?? ExcelJsMod.default.Workbook) as typeof ExcelJS.Workbook;
  const wb = new ExcelJsCtor();
  wb.creator = 'OpenConstructionERP';
  wb.created = ctx.exportDate ?? new Date();
  // Stored quantities are metric-canonical (D-TKC-016); convert values +
  // units to the user's system at the export boundary. Metric is a
  // pass-through, so the sheet is unchanged when no/`metric` system is set.
  const system: MeasurementSystem = ctx.measurementSystem ?? 'metric';

  /* ── Measurements sheet ────────────────────────────────────── */
  const ws = wb.addWorksheet('Measurements');
  ws.columns = EXCEL_COLUMNS.map((c) => ({
    header: c.header,
    key: c.key,
    width: c.width,
  }));
  const headerRow = ws.getRow(1);
  headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  headerRow.fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF1F2937' },
  };
  headerRow.alignment = { vertical: 'middle' };

  // Group measurements by group name so subtotal rows live with their data.
  // Walk the paint-order projection (issue #395), the same one the canvas, the
  // hit-test, the sidebar and the annotated PDF use, so a takeoff the user
  // rearranged exports in the order they arranged it. The projection is taken
  // once over the whole list rather than per group: sortByPaintOrder falls back
  // to the array index for rows with no explicit key, and only the global index
  // reproduces what the canvas paints - bucketing first would restart that
  // fallback inside every group and reorder rows whose explicit key was chosen
  // relative to another group's rows. The group sections themselves stay
  // alphabetical (sorted just below); only the rows within a section move.
  const byGroup = new Map<string, Measurement[]>();
  for (const m of sortByPaintOrder(ctx.measurements, groupBands(ctx.measurements))) {
    const g = m.group || 'General';
    const list = byGroup.get(g) ?? [];
    list.push(m);
    byGroup.set(g, list);
  }
  const sortedGroups = Array.from(byGroup.keys()).sort((a, b) => a.localeCompare(b));

  for (const groupName of sortedGroups) {
    const groupMs = byGroup.get(groupName)!;
    const color = (ctx.groupColorMap[groupName] ?? '#3B82F6').replace('#', 'FF');

    // Group header row.
    const headerRowVals = ws.addRow({
      group: groupName,
      type: '',
      annotation: `${groupMs.length} item(s)`,
      page: '',
      value: '',
      unit: '',
      linkedBoq: '',
      scaleSource: '',
    });
    headerRowVals.font = { bold: true, color: { argb: 'FFFFFFFF' } };
    headerRowVals.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: color },
    };

    // Data rows. A deduction (opening / void) prints its value negative and
    // flags the type so the sheet reconciles with the net subtotal below.
    for (const m of groupMs) {
      const isAnno = isAnnotationType(m.type);
      // Reported (effective) quantity: slope / wastage / multiplier + the
      // deduction sign, so the sheet reconciles with the net subtotal below.
      const signed = effectiveQuantity(m);
      const disp = convertQuantity(signed, effectiveUnit(m) || '', system);
      const cellValue = isAnno ? '' : disp.value;
      ws.addRow({
        group: groupName,
        type: m.isDeduction
          ? `${m.type} (deduction)`
          : isWallMeasurement(m)
            ? `${m.type} (wall)`
            : m.type,
        annotation: m.annotation,
        page: m.page,
        value: cellValue,
        unit: isAnno ? m.unit : disp.unit,
        linkedBoq: m.linkedPositionOrdinal ?? '',
        // Annotations carry no quantity, so no scale stands behind them.
        // Everything else reports its provenance, and a row that never
        // recorded one reports that plainly rather than reading as blank.
        scaleSource: isAnno ? '' : scaleSourceLabel(m.scaleSource),
      });
    }

    // Subtotal rows by type (numeric only).
    const subtotalTypes: Array<'distance' | 'polyline' | 'area' | 'volume' | 'count'> = [
      'distance',
      'polyline',
      'area',
      'volume',
      'count',
    ];
    for (const t of subtotalTypes) {
      // Bucket by the REPORTED type: a wall's m² belongs with the areas.
      const subset = groupMs.filter((m) => reportingType(m) === t);
      if (subset.length === 0) continue;
      // Sum the reported (effective) quantities so the subtotal folds slope /
      // wastage / multiplier and nets out deductions (gross - openings).
      const total = subset.reduce((s, m) => s + effectiveQuantity(m), 0);
      const metricUnit = effectiveUnit(subset[0]!);
      // Counts are unitless tallies (kept as pcs, integer); length / area /
      // volume subtotals convert to the export measurement system.
      const disp = convertQuantity(total, metricUnit, system);
      const subtotalRow = ws.addRow({
        group: `${groupName} - Subtotal`,
        type: t,
        annotation: `Total ${t}`,
        page: '',
        value: t === 'count' ? Math.round(total) : Number(disp.value.toFixed(3)),
        unit: t === 'count' ? 'pcs' : disp.unit,
        linkedBoq: '',
        scaleSource: '',
      });
      subtotalRow.font = { bold: true };
      subtotalRow.fill = {
        type: 'pattern',
        pattern: 'solid',
        fgColor: { argb: 'FFF3F4F6' },
      };
    }
  }

  // Freeze the header so subtotal scrolling stays anchored.
  ws.views = [{ state: 'frozen', xSplit: 0, ySplit: 1 }];

  /* ── Summary sheet ────────────────────────────────────────── */
  const summary = wb.addWorksheet('Summary');
  summary.columns = [
    { header: 'Group', key: 'group', width: 18 },
    { header: 'Type', key: 'type', width: 14 },
    { header: 'Count', key: 'count', width: 10 },
    { header: 'Total', key: 'total', width: 14 },
    { header: 'Unit', key: 'unit', width: 8 },
  ];
  const sumHeader = summary.getRow(1);
  sumHeader.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  sumHeader.fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF1F2937' },
  };

  const aggregated = summariseByGroupType(ctx.measurements, ctx.groupColorMap);
  for (const r of aggregated) {
    const disp = convertQuantity(r.total, r.unit, system);
    const row = summary.addRow({
      group: r.group,
      type: r.type,
      count: r.count,
      total: isAnnotationType(r.type) ? null : Number(disp.value.toFixed(3)),
      unit: (isAnnotationType(r.type) ? r.unit : disp.unit) || '—',
    });
    const color = r.color.replace('#', 'FF');
    row.getCell('group').fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: color },
    };
    row.getCell('group').font = { color: { argb: 'FFFFFFFF' }, bold: true };
  }

  // Grand total row.
  const grandTotalRow = summary.addRow({
    group: 'TOTAL',
    type: '',
    count: aggregated.reduce((s, r) => s + r.count, 0),
    total: null,
    unit: '',
  });
  grandTotalRow.font = { bold: true };
  grandTotalRow.fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FFE5E7EB' },
  };

  summary.views = [{ state: 'frozen', xSplit: 0, ySplit: 1 }];

  return wb;
}

/* ── Browser download helper ─────────────────────────────────────── */

/**
 * Trigger a browser download for a Blob with the supplied filename.
 *
 * Wrapped so tests can replace it (it touches `document.createElement`
 * and `URL.createObjectURL`, both of which are jsdom-friendly but flaky
 * to spy on inside async test harnesses).
 */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Defer revoke so the download fires under all browsers.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

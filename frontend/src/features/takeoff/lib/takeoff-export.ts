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
 * Both flavours respect group visibility — only measurements whose
 * group is **not** in `hiddenGroups` are baked / exported, matching the
 * live canvas overlay's filter rule in `TakeoffViewerModule.tsx`.
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
import type { ScaleConfig } from '../../../modules/pdf-takeoff/data/scale-helpers';
import {
  pixelDistance,
  toRealDistance,
  formatMeasurement,
} from '../../../modules/pdf-takeoff/data/scale-helpers';
import { ANNOTATION_TYPES } from './takeoff-groups';

/* ── Public types ────────────────────────────────────────────────── */

export interface ExportContext {
  /** Project display name for the filename + workbook header. */
  projectName: string;
  /** Today's date (override-able for tests). Defaults to current day. */
  exportDate?: Date;
}

export interface PdfExportContext extends ExportContext {
  /** Loaded PDF.js document — pages will be rendered to image. */
  pdfDoc: PdfJsLib.PDFDocumentProxy;
  /** All measurements (annotations + numeric). */
  measurements: Measurement[];
  /** Groups hidden in the UI — excluded from the bake. */
  hiddenGroups: ReadonlySet<string>;
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
    const key = `${group}::${m.type}`;
    const existing = byKey.get(key) ?? {
      group,
      type: m.type,
      count: 0,
      total: 0,
      units: {} as Record<string, number>,
    };
    existing.count += 1;
    if (!isAnnotationType(m.type)) {
      existing.total += m.value;
      if (m.unit) existing.units[m.unit] = (existing.units[m.unit] ?? 0) + 1;
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
  },
): void {
  const { pageNumber, dpr, zoom, scale, groupColorMap, hiddenGroups } = options;
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

  const visible = measurements.filter(
    (m) =>
      m.page === pageNumber &&
      !hiddenGroups.has(m.group) &&
      !(isAnnotationType(m.type) && hiddenGroups.has('__annotations__')),
  );

  for (const m of visible) {
    const color = groupColorMap[m.group] || '#3B82F6';
    ctx.strokeStyle = color;
    ctx.fillStyle = color;

    if (m.type === 'distance' && m.points.length === 2) {
      const p0 = m.points[0]!;
      const p1 = m.points[1]!;
      ctx.beginPath();
      ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
      ctx.lineTo(p1.x * dpr * zoom, p1.y * dpr * zoom);
      ctx.stroke();
      const mx = ((p0.x + p1.x) / 2) * dpr * zoom;
      const my = ((p0.y + p1.y) / 2) * dpr * zoom - 8 * dpr;
      ctx.font = `${12 * dpr}px sans-serif`;
      ctx.fillText(m.label, mx, my);
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
      ctx.stroke();
      for (let i = 0; i < m.points.length - 1; i++) {
        const pa = m.points[i]!;
        const pb = m.points[i + 1]!;
        const segDist = pixelDistance(pa.x, pa.y, pb.x, pb.y);
        const segReal = toRealDistance(segDist, scale);
        const smx = ((pa.x + pb.x) / 2) * dpr * zoom;
        const smy = ((pa.y + pb.y) / 2) * dpr * zoom - 6 * dpr;
        ctx.font = `${10 * dpr}px sans-serif`;
        ctx.fillText(formatMeasurement(segReal, scale.unitLabel), smx, smy);
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
      ctx.fillText(m.label, totalLx, totalLy);
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
      ctx.globalAlpha = 0.15;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.stroke();
      const cx =
        (m.points.reduce((s, p) => s + p.x, 0) / m.points.length) * dpr * zoom;
      const cy =
        (m.points.reduce((s, p) => s + p.y, 0) / m.points.length) * dpr * zoom;
      ctx.font = `${12 * dpr}px sans-serif`;
      ctx.fillText(m.label, cx, cy);
      drawLabel(m.annotation, cx, cy - 14 * dpr, color);
      continue;
    }

    if (m.type === 'count') {
      for (const p of m.points) {
        ctx.beginPath();
        ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 8 * dpr, 0, Math.PI * 2);
        ctx.globalAlpha = 0.3;
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
): number[] {
  const pages = new Set<number>();
  for (const m of measurements) {
    if (hiddenGroups.has(m.group)) continue;
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
  const pageNumbers = selectAnnotatedPages(ctx.measurements, ctx.hiddenGroups);

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
    await page.render({ canvasContext: canvasCtx, viewport }).promise;

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

  const visibleMeasurements = ctx.measurements.filter(
    (m) =>
      !ctx.hiddenGroups.has(m.group) &&
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
    pdf.text(r.group, margin, y);
    pdf.text(r.type, margin + 130, y);
    pdf.text(String(r.count), margin + 240, y);
    pdf.text(
      isAnnotationType(r.type) ? '—' : formatNumberShort(r.total),
      margin + 300,
      y,
    );
    pdf.text(r.unit || '—', margin + 400, y);
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
  const byGroup = new Map<string, Measurement[]>();
  for (const m of ctx.measurements) {
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
    });
    headerRowVals.font = { bold: true, color: { argb: 'FFFFFFFF' } };
    headerRowVals.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: color },
    };

    // Data rows.
    for (const m of groupMs) {
      ws.addRow({
        group: groupName,
        type: m.type,
        annotation: m.annotation,
        page: m.page,
        value: isAnnotationType(m.type) ? '' : m.value,
        unit: m.unit,
        linkedBoq: m.linkedPositionOrdinal ?? '',
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
      const subset = groupMs.filter((m) => m.type === t);
      if (subset.length === 0) continue;
      const total = subset.reduce((s, m) => s + m.value, 0);
      const unit = subset[0]!.unit;
      const subtotalRow = ws.addRow({
        group: `${groupName} - Subtotal`,
        type: t,
        annotation: `Total ${t}`,
        page: '',
        value: t === 'count' ? Math.round(total) : Number(total.toFixed(3)),
        unit: t === 'count' ? 'pcs' : unit,
        linkedBoq: '',
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
    const row = summary.addRow({
      group: r.group,
      type: r.type,
      count: r.count,
      total: isAnnotationType(r.type) ? null : Number(r.total.toFixed(3)),
      unit: r.unit || '—',
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

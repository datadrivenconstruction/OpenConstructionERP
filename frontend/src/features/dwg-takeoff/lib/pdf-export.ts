/**
 * Lightweight PDF export helper for the DWG Takeoff viewer.
 *
 * Captures the current canvas pixels as PNG and embeds them inside an
 * A4-landscape jsPDF document, with a header that records the drawing
 * filename, export date, and active drawing scale. Kept in its own file
 * so the page component stays focused on state + layout and so the
 * (already-installed) `jspdf` dependency is only imported by code paths
 * that actually need it.
 */

import jsPDF from 'jspdf';

/** Options accepted by {@link exportCanvasToPdf}. */
export interface PdfExportOptions {
  /** The DXF viewer canvas element to snapshot. Required. */
  canvas: HTMLCanvasElement;
  /** Filename of the source drawing — used in the header + download name. */
  filename?: string | null;
  /** Drawing scale denominator (e.g. 50 for a 1:50 plan). Defaults to 1. */
  scale?: number;
  /** Explicit download filename (without extension). If omitted, derived
   *  from `filename` + YYYYMMDD date. */
  downloadName?: string;
}

/** Format a Date as YYYYMMDD for filenames. */
function ymdStamp(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}${m}${dd}`;
}

/** Format a Date for display in the header ("18 Apr 2026"). */
function headerDate(d: Date = new Date()): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    }).format(d);
  } catch {
    return d.toDateString();
  }
}

/** Strip common drawing extensions from a basename. */
function stripExt(name: string): string {
  return name.replace(/\.(dxf|dwg|rvt|ifc|pdf)$/i, '');
}

/**
 * Snapshot the given canvas and download it as a single-page A4-landscape
 * PDF with a header bar. The embedded image is scaled to fit within a
 * 10 mm margin while preserving aspect ratio.
 *
 * Safe to call from any React event handler — no framework dependencies
 * beyond the already-installed `jspdf`. Throws on an obviously broken
 * canvas (zero dimensions) so the caller can surface a friendly toast.
 */
export function exportCanvasToPdf(opts: PdfExportOptions): void {
  const { canvas, filename, scale = 1, downloadName } = opts;

  if (canvas.width === 0 || canvas.height === 0) {
    throw new Error('Canvas is empty — nothing to export.');
  }

  const dataUrl = canvas.toDataURL('image/png');

  // A4 landscape: 297 × 210 mm. 10 mm margin on every side.
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 10;

  // ── Header ────────────────────────────────────────────────────────
  const headerY = margin;
  const headerHeight = 12;
  const displayName = filename ? stripExt(filename) : 'Drawing';

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.text(displayName, margin, headerY + 6);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(90, 90, 90);
  const metaParts = [`Scale 1:${scale}`, headerDate()];
  const metaStr = metaParts.join('    ');
  const metaWidth = doc.getTextWidth(metaStr);
  doc.text(metaStr, pageWidth - margin - metaWidth, headerY + 6);

  // Thin underline between header and image
  doc.setDrawColor(200, 200, 200);
  doc.setLineWidth(0.2);
  doc.line(margin, headerY + headerHeight, pageWidth - margin, headerY + headerHeight);
  doc.setTextColor(0, 0, 0);

  // ── Image (fit inside remaining area preserving aspect ratio) ─────
  const availWidth = pageWidth - margin * 2;
  const availHeight = pageHeight - margin * 2 - headerHeight - 2;
  const imgRatio = canvas.width / canvas.height;
  const avRatio = availWidth / availHeight;

  let imgW: number;
  let imgH: number;
  if (imgRatio > avRatio) {
    imgW = availWidth;
    imgH = availWidth / imgRatio;
  } else {
    imgH = availHeight;
    imgW = availHeight * imgRatio;
  }
  const imgX = (pageWidth - imgW) / 2;
  const imgY = headerY + headerHeight + 2;

  doc.addImage(dataUrl, 'PNG', imgX, imgY, imgW, imgH);

  // ── Download ──────────────────────────────────────────────────────
  const base = downloadName
    ?? `${stripExt(filename || 'drawing')}-${ymdStamp()}`;
  doc.save(`${base}.pdf`);
}

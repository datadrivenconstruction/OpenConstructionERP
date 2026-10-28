// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Load and rasterise one sheet of a PDF revision in the browser.
 *
 * Uses the platform's pdf.js wrapper (the same worker and asset roots as the
 * takeoff viewer), so a compare adds no server-side rendering dependency.
 */

import { fetchWithAuth } from '@/shared/lib/api';
import { closePdf, openPdf, type PDFDocumentProxy } from '@/shared/lib/pdfjs';
import type { TextItem } from './textDiff';

export interface RenderedSheet {
  /** Page size in PDF units (scale 1, rotation applied). */
  widthPt: number;
  heightPt: number;
  /** Pixels per PDF unit of the raster. */
  scale: number;
  canvas: HTMLCanvasElement;
  rgba: Uint8ClampedArray;
  text: TextItem[];
  pageCount: number;
}

/** URL the takeoff module serves a document's PDF bytes from. */
export function takeoffPdfUrl(documentId: string): string {
  return `/api/v1/takeoff/documents/${encodeURIComponent(documentId)}/download/`;
}

export async function loadPdf(url: string): Promise<PDFDocumentProxy> {
  const res = await fetchWithAuth(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const bytes = await res.arrayBuffer();
  return openPdf(bytes).promise;
}

interface PdfTextItem {
  str?: string;
  transform?: number[];
  width?: number;
  height?: number;
}

/**
 * Render page `pageNumber` so that its longer side is about `targetPx`
 * pixels (or at an explicit `scale`), and read its text layer.
 */
export async function renderSheet(
  doc: PDFDocumentProxy,
  pageNumber: number,
  opts: { targetPx?: number; scale?: number } = {},
): Promise<RenderedSheet> {
  const page = await doc.getPage(Math.min(Math.max(1, pageNumber), doc.numPages));
  const base = page.getViewport({ scale: 1 });
  const scale = opts.scale ?? (opts.targetPx ?? 2400) / Math.max(base.width, base.height);
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('canvas unavailable');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvas, viewport }).promise;
  const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

  const text: TextItem[] = [];
  try {
    const content = await page.getTextContent();
    for (const raw of content.items as PdfTextItem[]) {
      if (!raw.str || !raw.transform) continue;
      const [, , c, d, e, f] = raw.transform as [number, number, number, number, number, number];
      const [vx, vy] = base.convertToViewportPoint(e, f) as [number, number];
      const h = raw.height || Math.hypot(c, d);
      text.push({ str: raw.str, x: vx, y: vy - h, w: raw.width ?? 0, h });
    }
  } catch {
    // A sheet without a usable text layer (a scan) still compares by pixels.
  }
  page.cleanup();
  return {
    widthPt: base.width,
    heightPt: base.height,
    scale,
    canvas,
    rgba,
    text,
    pageCount: doc.numPages,
  };
}

export { closePdf };

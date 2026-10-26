// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Load and rasterise the old and new sheet of a compare, plus canvas helpers. */

import { useEffect, useState } from 'react';

import { closePdf, loadPdf, renderSheet, takeoffPdfUrl, type RenderedSheet } from './pdfSheet';
import { overlayRgba, type PixelDiff } from './raster';
import type { SheetRaster } from './sheetDiff';

export interface SheetPairState {
  old: RenderedSheet | null;
  new: RenderedSheet | null;
  loading: boolean;
  error: string | null;
}

/** Longer side of the raster a compare runs on: fine enough for 1 mm on A1, light enough for a laptop. */
export const RASTER_PX = 2400;

export function useSheetPair(
  oldDocId: string | null,
  newDocId: string | null,
  oldPage: number,
  newPage: number,
): SheetPairState {
  const [state, setState] = useState<SheetPairState>({ old: null, new: null, loading: false, error: null });

  useEffect(() => {
    if (!oldDocId || !newDocId) {
      setState({ old: null, new: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    const docs: Array<Awaited<ReturnType<typeof loadPdf>>> = [];
    (async () => {
      try {
        const [oldDoc, newDoc] = await Promise.all([loadPdf(takeoffPdfUrl(oldDocId)), loadPdf(takeoffPdfUrl(newDocId))]);
        docs.push(oldDoc, newDoc);
        const newSheet = await renderSheet(newDoc, newPage, { targetPx: RASTER_PX });
        // Same pixels per unit on both sides, so a re-plot at another paper size keeps its true scale.
        const oldSheet = await renderSheet(oldDoc, oldPage, { scale: newSheet.scale });
        if (!cancelled) setState({ old: oldSheet, new: newSheet, loading: false, error: null });
      } catch (err) {
        if (!cancelled) setState({ old: null, new: null, loading: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
    return () => {
      cancelled = true;
      docs.forEach((d) => closePdf(d));
    };
  }, [oldDocId, newDocId, oldPage, newPage]);

  return state;
}

export function asRaster(sheet: RenderedSheet): SheetRaster {
  return {
    width: sheet.canvas.width,
    height: sheet.canvas.height,
    rgba: sheet.rgba,
    scale: sheet.scale,
    widthPt: sheet.widthPt,
    heightPt: sheet.heightPt,
    text: sheet.text,
  };
}

export function overlayCanvas(diff: PixelDiff): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = diff.width;
  canvas.height = diff.height;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const img = ctx.createImageData(diff.width, diff.height);
    img.data.set(overlayRgba(diff));
    ctx.putImageData(img, 0, 0);
  }
  return canvas;
}

/** JPEG thumbnail of a region of the overlay (box in raster pixels), at most `size` px wide. */
export function regionThumbnail(
  source: HTMLCanvasElement,
  box: { x: number; y: number; w: number; h: number },
  size = 160,
): string | null {
  const pad = Math.max(box.w, box.h) * 0.25 + 8;
  const sx = Math.max(0, box.x - pad);
  const sy = Math.max(0, box.y - pad);
  const sw = Math.min(source.width - sx, box.w + 2 * pad);
  const sh = Math.min(source.height - sy, box.h + 2 * pad);
  if (sw <= 0 || sh <= 0) return null;
  const k = Math.min(1, size / Math.max(sw, sh));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(sw * k));
  canvas.height = Math.max(1, Math.round(sh * k));
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  try {
    return canvas.toDataURL('image/jpeg', 0.72);
  } catch {
    return null;
  }
}

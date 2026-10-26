// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet compare viewer: colour overlay or side by side, pan and zoom synced.
 *
 * Both panes share one view (zoom and pan in pixels of the new sheet's
 * raster), so dragging or zooming one moves the other in step. The old sheet
 * is drawn through the alignment, so the same wall sits at the same place in
 * both panes. In pick mode (manual two-point alignment) the old pane shows the
 * sheet as it is, unaligned, and clicks report sheet pixels.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react';

import { applyAffine, invertAffine, type Affine, type Pt } from '../lib/transform';
import type { ChangeKind } from '../api';

export interface ViewerRegion {
  id: string;
  seq: number;
  kind: ChangeKind;
  /** Box in pixels of the new sheet's raster. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export type ViewerMode = 'overlay' | 'side';

export interface CompareViewerProps {
  mode: ViewerMode;
  newCanvas: HTMLCanvasElement;
  oldCanvas: HTMLCanvasElement;
  /** Old raster pixel -> new raster pixel. */
  oldToNew: Affine;
  /** Old raster pixel -> new raster pixel before alignment (resolution only), used while picking. */
  oldToNewUnaligned: Affine;
  overlayCanvas: HTMLCanvasElement | null;
  regions: ViewerRegion[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Which sheet the next click picks an alignment mark on. */
  pickSide?: 'old' | 'new' | null;
  /** Picked mark, in pixels of the clicked sheet's own raster. */
  onPick?: (side: 'old' | 'new', pt: Pt) => void;
  marks?: { old: Pt[]; new: Pt[] };
}

interface View {
  zoom: number;
  panX: number;
  panY: number;
}

const KIND_STROKE: Record<ChangeKind, string> = {
  added: '#2563eb',
  removed: '#dc2626',
  modified: '#d97706',
  text: '#7c3aed',
};

function drawPane(
  canvas: HTMLCanvasElement | null,
  view: View,
  paint: (ctx: CanvasRenderingContext2D) => void,
): void {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const { clientWidth: w, clientHeight: h } = canvas;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = '#f1f5f9';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(view.zoom * dpr, 0, 0, view.zoom * dpr, view.panX * dpr, view.panY * dpr);
  ctx.imageSmoothingEnabled = view.zoom < 1;
  paint(ctx);
}

export function CompareViewer({
  mode,
  newCanvas,
  oldCanvas,
  oldToNew,
  oldToNewUnaligned,
  overlayCanvas,
  regions,
  selectedId,
  onSelect,
  pickSide = null,
  onPick,
  marks,
}: CompareViewerProps) {
  const { t } = useTranslation();
  const wrapRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLCanvasElement>(null);
  const rightRef = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState<View>({ zoom: 0.25, panX: 0, panY: 0 });
  const drag = useRef<{ x: number; y: number; panX: number; panY: number; moved: boolean } | null>(null);

  const fit = useCallback(() => {
    const pane = leftRef.current;
    if (!pane) return;
    const w = pane.clientWidth || 600;
    const h = pane.clientHeight || 400;
    const zoom = Math.min(w / newCanvas.width, h / newCanvas.height) * 0.96;
    setView({ zoom, panX: (w - newCanvas.width * zoom) / 2, panY: (h - newCanvas.height * zoom) / 2 });
  }, [newCanvas]);

  useEffect(() => {
    fit();
  }, [fit, mode]);

  // Centre the selected region when it changes from the list.
  useEffect(() => {
    const r = regions.find((x) => x.id === selectedId);
    const pane = leftRef.current;
    if (!r || !pane) return;
    setView((v) => {
      const zoom = Math.max(v.zoom, Math.min(2, (pane.clientWidth * 0.4) / Math.max(r.w, r.h, 1)));
      return {
        zoom,
        panX: pane.clientWidth / 2 - (r.x + r.w / 2) * zoom,
        panY: pane.clientHeight / 2 - (r.y + r.h / 2) * zoom,
      };
    });
  }, [selectedId, regions]);

  const paintRegions = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      for (const r of regions) {
        const selected = r.id === selectedId;
        ctx.lineWidth = (selected ? 3 : 1.5) / view.zoom;
        ctx.strokeStyle = KIND_STROKE[r.kind];
        ctx.setLineDash(selected ? [] : [6 / view.zoom, 4 / view.zoom]);
        const pad = 4 / view.zoom;
        ctx.strokeRect(r.x - pad, r.y - pad, r.w + 2 * pad, r.h + 2 * pad);
        ctx.setLineDash([]);
        ctx.fillStyle = KIND_STROKE[r.kind];
        ctx.font = `${12 / view.zoom}px sans-serif`;
        ctx.fillText(String(r.seq), r.x - pad, r.y - pad - 2 / view.zoom);
      }
    },
    [regions, selectedId, view.zoom],
  );

  const paintMarks = useCallback(
    (ctx: CanvasRenderingContext2D, pts: Pt[], colour: string) => {
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2 / view.zoom;
      pts.forEach(([x, y], i) => {
        const r = 10 / view.zoom;
        ctx.beginPath();
        ctx.moveTo(x - r, y);
        ctx.lineTo(x + r, y);
        ctx.moveTo(x, y - r);
        ctx.lineTo(x, y + r);
        ctx.stroke();
        ctx.fillStyle = colour;
        ctx.font = `${12 / view.zoom}px sans-serif`;
        ctx.fillText(String(i + 1), x + r, y - r);
      });
    },
    [view.zoom],
  );

  useEffect(() => {
    const oldMatrix = pickSide === 'old' ? oldToNewUnaligned : oldToNew;
    const paintOld = (ctx: CanvasRenderingContext2D) => {
      ctx.save();
      ctx.transform(...oldMatrix);
      ctx.drawImage(oldCanvas, 0, 0);
      ctx.restore();
    };
    if (mode === 'overlay') {
      drawPane(leftRef.current, view, (ctx) => {
        if (overlayCanvas) ctx.drawImage(overlayCanvas, 0, 0);
        else {
          ctx.globalAlpha = 0.5;
          paintOld(ctx);
          ctx.drawImage(newCanvas, 0, 0);
          ctx.globalAlpha = 1;
        }
        paintRegions(ctx);
      });
      return;
    }
    drawPane(leftRef.current, view, (ctx) => {
      paintOld(ctx);
      if (pickSide !== 'old') paintRegions(ctx);
      if (marks) paintMarks(ctx, marks.old.map(([x, y]) => applyAffine(oldMatrix, x, y)), '#dc2626');
    });
    drawPane(rightRef.current, view, (ctx) => {
      ctx.drawImage(newCanvas, 0, 0);
      paintRegions(ctx);
      if (marks) paintMarks(ctx, marks.new, '#2563eb');
    });
  }, [mode, view, newCanvas, oldCanvas, oldToNew, oldToNewUnaligned, overlayCanvas, paintRegions, paintMarks, pickSide, marks]);

  useEffect(() => {
    const onResize = () => setView((v) => ({ ...v }));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toSheet = (e: React.MouseEvent<HTMLCanvasElement>): Pt => {
    const rect = e.currentTarget.getBoundingClientRect();
    return [(e.clientX - rect.left - view.panX) / view.zoom, (e.clientY - rect.top - view.panY) / view.zoom];
  };

  const onWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    setView((v) => {
      const zoom = Math.min(16, Math.max(0.02, v.zoom * factor));
      return { zoom, panX: mx - ((mx - v.panX) * zoom) / v.zoom, panY: my - ((my - v.panY) * zoom) / v.zoom };
    });
  };

  const onDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    drag.current = { x: e.clientX, y: e.clientY, panX: view.panX, panY: view.panY, moved: false };
  };
  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.moved) setView((v) => ({ ...v, panX: d.panX + dx, panY: d.panY + dy }));
  };
  const onUp = (side: 'old' | 'new') => (e: React.MouseEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) return;
    const [x, y] = toSheet(e);
    if (pickSide && onPick) {
      if (pickSide !== side && mode === 'side') return;
      if (side === 'old') {
        const inv = invertAffine(oldToNewUnaligned);
        if (inv) onPick('old', applyAffine(inv, x, y));
      } else onPick('new', [x, y]);
      return;
    }
    const hit = regions
      .filter((r) => x >= r.x - 6 && x <= r.x + r.w + 6 && y >= r.y - 6 && y <= r.y + r.h + 6)
      .sort((a, b) => a.w * a.h - b.w * b.h)[0];
    if (hit) onSelect(hit.id);
  };

  const zoomBy = (f: number) =>
    setView((v) => {
      const pane = leftRef.current;
      const cx = (pane?.clientWidth ?? 0) / 2;
      const cy = (pane?.clientHeight ?? 0) / 2;
      const zoom = Math.min(16, Math.max(0.02, v.zoom * f));
      return { zoom, panX: cx - ((cx - v.panX) * zoom) / v.zoom, panY: cy - ((cy - v.panY) * zoom) / v.zoom };
    });

  const paneClass = clsx(
    'h-full w-full rounded-md border border-border bg-surface-secondary',
    pickSide ? 'cursor-crosshair' : 'cursor-grab',
  );

  return (
    <div ref={wrapRef} className="relative flex h-[62vh] min-h-[360px] flex-col gap-2" data-testid="drawing-compare-viewer">
      <div className={clsx('grid flex-1 gap-2', mode === 'side' ? 'grid-cols-2' : 'grid-cols-1')}>
        <div className="relative min-h-0">
          {mode === 'side' && (
            <span className="absolute left-2 top-2 z-10 rounded bg-red-600/90 px-1.5 py-0.5 text-2xs font-semibold text-white">
              {t('drawing_compare.viewer_old', { defaultValue: 'Older revision' })}
            </span>
          )}
          <canvas
            ref={leftRef}
            className={paneClass}
            onWheel={onWheel}
            onMouseDown={onDown}
            onMouseMove={onMove}
            onMouseUp={onUp(mode === 'side' ? 'old' : pickSide === 'old' ? 'old' : 'new')}
            onMouseLeave={() => {
              drag.current = null;
            }}
            aria-label={t('drawing_compare.viewer_aria', { defaultValue: 'Revision compare view' })}
          />
        </div>
        {mode === 'side' && (
          <div className="relative min-h-0">
            <span className="absolute left-2 top-2 z-10 rounded bg-blue-600/90 px-1.5 py-0.5 text-2xs font-semibold text-white">
              {t('drawing_compare.viewer_new', { defaultValue: 'Newer revision' })}
            </span>
            <canvas
              ref={rightRef}
              className={paneClass}
              onWheel={onWheel}
              onMouseDown={onDown}
              onMouseMove={onMove}
              onMouseUp={onUp('new')}
              onMouseLeave={() => {
                drag.current = null;
              }}
            />
          </div>
        )}
      </div>
      <div className="absolute bottom-3 right-3 flex gap-1">
        <button type="button" onClick={() => zoomBy(1.25)} className="rounded border border-border bg-surface-primary p-1.5" aria-label={t('drawing_compare.zoom_in', { defaultValue: 'Zoom in' })}>
          <ZoomIn size={14} />
        </button>
        <button type="button" onClick={() => zoomBy(0.8)} className="rounded border border-border bg-surface-primary p-1.5" aria-label={t('drawing_compare.zoom_out', { defaultValue: 'Zoom out' })}>
          <ZoomOut size={14} />
        </button>
        <button type="button" onClick={fit} className="rounded border border-border bg-surface-primary p-1.5" aria-label={t('drawing_compare.zoom_fit', { defaultValue: 'Fit to view' })}>
          <Maximize2 size={14} />
        </button>
      </div>
      {mode === 'overlay' && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-content-secondary">
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-red-600" />{t('drawing_compare.legend_old', { defaultValue: 'Only in the older revision' })}</span>
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-blue-600" />{t('drawing_compare.legend_new', { defaultValue: 'Only in the newer revision' })}</span>
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-gray-400" />{t('drawing_compare.legend_same', { defaultValue: 'Unchanged' })}</span>
        </div>
      )}
    </div>
  );
}

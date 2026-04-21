/**
 * Horizontal thumbnail strip at the bottom of the DWG viewer.
 *
 * DXFs commonly ship with a Model space plus one or more paper-space
 * layouts — "A-100 Floor Plan", "A-101 Sections", etc. A plain text tab
 * bar (the pre-existing top-of-viewer switcher) makes it hard to eyeball
 * which layout has content and which is empty. The strip renders each
 * layout's bounding box as a miniature black-line sketch so the user can
 * "see" which sheet holds the geometry they care about.
 *
 * The strip is hidden when the drawing has a single layout (no point
 * occupying viewport real estate for a one-item chooser). Thumbnails
 * are redrawn whenever ``entities`` or ``layouts`` change — cheap
 * because we only touch lines/polylines/arcs and skip anything without
 * geometry, and because layouts are typically small (<1000 entities
 * each at the scale of paper-space sheets).
 */

import { useEffect, useRef } from 'react';
import clsx from 'clsx';
import type { DxfEntity } from '../api';

interface Props {
  layouts: string[];
  entities: DxfEntity[];
  activeLayout: string | null;
  onLayoutChange: (layout: string) => void;
  /** Optional: count hints keyed by layout name. Avoids recomputing on
   *  every render when the parent already has them. If omitted, the
   *  strip derives counts from ``entities`` itself. */
  entityCountByLayout?: Record<string, number>;
}

const THUMB_W = 100;
const THUMB_H = 70;

export function SheetStrip({
  layouts,
  entities,
  activeLayout,
  onLayoutChange,
  entityCountByLayout,
}: Props) {
  // Hide on single-layout drawings (and never render the container).
  if (layouts.length <= 1) return null;

  // Group entities per layout once — downstream renderers reach into
  // the map by name rather than filtering the whole array per thumb.
  const byLayout = new Map<string, DxfEntity[]>();
  for (const e of entities) {
    const key = e.layout ?? '__default__';
    const arr = byLayout.get(key);
    if (arr) arr.push(e);
    else byLayout.set(key, [e]);
  }

  return (
    <div
      data-testid="dwg-sheet-strip"
      className="flex items-center gap-2 border-t border-border bg-surface px-3 py-2 overflow-x-auto flex-shrink-0"
    >
      {layouts.map((layout) => {
        const layoutEnts = byLayout.get(layout) ?? [];
        const count = entityCountByLayout?.[layout] ?? layoutEnts.length;
        const isActive = layout === activeLayout;
        return (
          <button
            key={layout}
            type="button"
            onClick={() => onLayoutChange(layout)}
            data-testid={`dwg-sheet-strip-item-${layout}`}
            data-active={isActive ? 'true' : 'false'}
            className={clsx(
              'group flex flex-col items-center gap-1 rounded-md border p-1 transition-colors flex-shrink-0',
              isActive
                ? 'border-oe-blue bg-oe-blue/10'
                : 'border-border hover:border-oe-blue/50 hover:bg-surface-secondary',
            )}
          >
            <SheetThumb entities={layoutEnts} />
            <div className="flex w-full items-center justify-between gap-2 px-0.5">
              <span
                className={clsx(
                  'max-w-[110px] truncate text-[10px] font-medium',
                  isActive ? 'text-oe-blue' : 'text-foreground',
                )}
                title={layout}
              >
                {layout}
              </span>
              <span className="text-[9px] text-muted-foreground tabular-nums">
                {count}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** Tiny canvas that renders the entities' line segments, fitted into the
 *  thumbnail box. We intentionally ignore fills, text, hatches, and
 *  styling — the whole point is a high-level "is there content here"
 *  glance, not a faithful rendering. */
function SheetThumb({ entities }: { entities: DxfEntity[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = THUMB_W * dpr;
    canvas.height = THUMB_H * dpr;
    canvas.style.width = `${THUMB_W}px`;
    canvas.style.height = `${THUMB_H}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, THUMB_W, THUMB_H);

    // Compute bbox from any entity with coordinates.
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
      if (e.start) expand(e.start.x, e.start.y);
      if (e.end) expand(e.end.x, e.end.y);
      if (e.vertices) {
        for (const v of e.vertices) expand(v.x, v.y);
      }
      if (e.start && typeof e.radius === 'number') {
        expand(e.start.x - e.radius, e.start.y - e.radius);
        expand(e.start.x + e.radius, e.start.y + e.radius);
      }
    }

    if (!isFinite(minX) || maxX === minX || maxY === minY) {
      // Empty or degenerate — show a small dashed placeholder so the
      // thumbnail isn't visually blank, but don't try to render geometry.
      ctx.strokeStyle = '#cbd5e1';
      ctx.setLineDash([3, 3]);
      ctx.strokeRect(4, 4, THUMB_W - 8, THUMB_H - 8);
      ctx.setLineDash([]);
      return;
    }

    const padding = 4;
    const w = maxX - minX;
    const h = maxY - minY;
    const scale = Math.min(
      (THUMB_W - padding * 2) / w,
      (THUMB_H - padding * 2) / h,
    );
    // Center the drawing and flip Y (DXF Y axis grows upwards; canvas downwards).
    const offsetX = padding + (THUMB_W - padding * 2 - w * scale) / 2;
    const offsetY = padding + (THUMB_H - padding * 2 - h * scale) / 2;
    const project = (x: number, y: number): [number, number] => [
      offsetX + (x - minX) * scale,
      // Flip Y into canvas space so arch floor plans don't render upside
      // down relative to how the user saw them in the full viewer.
      THUMB_H - (offsetY + (y - minY) * scale),
    ];

    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    for (const e of entities) {
      switch (e.type) {
        case 'LINE': {
          if (!e.start || !e.end) break;
          const [ax, ay] = project(e.start.x, e.start.y);
          const [bx, by] = project(e.end.x, e.end.y);
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          break;
        }
        case 'LWPOLYLINE': {
          if (!e.vertices || e.vertices.length < 2) break;
          const [x0, y0] = project(e.vertices[0]!.x, e.vertices[0]!.y);
          ctx.moveTo(x0, y0);
          for (let i = 1; i < e.vertices.length; i++) {
            const [x, y] = project(e.vertices[i]!.x, e.vertices[i]!.y);
            ctx.lineTo(x, y);
          }
          if (e.closed) {
            ctx.lineTo(x0, y0);
          }
          break;
        }
        case 'ARC':
        case 'CIRCLE': {
          if (!e.start || typeof e.radius !== 'number') break;
          const [cx, cy] = project(e.start.x, e.start.y);
          const r = e.radius * scale;
          if (r <= 0.3) break;
          ctx.moveTo(cx + r, cy);
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          break;
        }
      }
    }
    ctx.stroke();
  }, [entities]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="dwg-sheet-strip-canvas"
      className="rounded border border-slate-200 bg-white dark:bg-slate-900"
    />
  );
}

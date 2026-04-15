/**
 * Canvas2D-based DXF entity renderer with pan, zoom, selection, and annotation overlay.
 */

import { useRef, useEffect, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DxfEntity, DwgAnnotation } from '../api';
import type { ViewportState, Extents } from '../lib/viewport';
import { zoomToFit, applyZoom, applyPan, screenToWorld, worldToScreen } from '../lib/viewport';
import { renderEntities } from '../lib/dxf-renderer';
import { renderAnnotations } from './AnnotationOverlay';
import type { DwgTool } from './ToolPalette';
import {
  calculateDistance,
  calculateArea,
  pointToSegmentDistance,
  getSegmentLengths,
  segmentMidpoint,
  formatMeasurement,
} from '../lib/measurement';

interface Props {
  entities: DxfEntity[];
  annotations: DwgAnnotation[];
  visibleLayers: Set<string>;
  activeTool: DwgTool;
  activeColor: string;
  selectedEntityId: string | null;
  selectedAnnotationId: string | null;
  onSelectEntity: (id: string | null) => void;
  onSelectAnnotation: (id: string | null) => void;
  onAnnotationCreated: (ann: {
    type: DwgAnnotation['type'];
    points: { x: number; y: number }[];
    text?: string;
    measurement_value?: number;
    measurement_unit?: string;
  }) => void;
}

function computeExtents(entities: DxfEntity[]): Extents {
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
    if (e.start && e.radius) {
      expand(e.start.x - e.radius, e.start.y - e.radius);
      expand(e.start.x + e.radius, e.start.y + e.radius);
    }
    if (e.type === 'ELLIPSE' && e.start) {
      const r = Math.max(e.major_radius ?? 0, e.minor_radius ?? 0, e.radius ?? 0);
      if (r > 0) {
        expand(e.start.x - r, e.start.y - r);
        expand(e.start.x + r, e.start.y + r);
      }
    }
    // TEXT/MTEXT: use insertion point + estimated text width
    if ((e.type === 'TEXT') && e.start && e.text) {
      const h = e.height ?? 2.5;
      const estimatedWidth = h * e.text.length * 0.6;
      expand(e.start.x + estimatedWidth, e.start.y + h);
    }
  }

  if (!isFinite(minX)) return { minX: 0, minY: 0, maxX: 100, maxY: 100 };
  return { minX, minY, maxX, maxY };
}

export function DxfViewer({
  entities,
  annotations,
  visibleLayers,
  activeTool,
  activeColor,
  selectedEntityId,
  selectedAnnotationId,
  onSelectEntity,
  onSelectAnnotation,
  onAnnotationCreated,
}: Props) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const vpRef = useRef<ViewportState>({ offsetX: 0, offsetY: 0, scale: 1 });
  const rafRef = useRef<number>(0);
  const isPanningRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });
  const drawPointsRef = useRef<{ x: number; y: number }[]>([]);
  const activeToolRef = useRef(activeTool);
  activeToolRef.current = activeTool;
  const activeColorRef = useRef(activeColor);
  activeColorRef.current = activeColor;
  const selectedEntityIdRef = useRef(selectedEntityId);
  selectedEntityIdRef.current = selectedEntityId;
  const selectedAnnotationIdRef = useRef(selectedAnnotationId);
  selectedAnnotationIdRef.current = selectedAnnotationId;
  const [, forceRender] = useState(0);
  /** Last computed drawing extents — kept to re-fit on resize. */
  const extentsRef = useRef<Extents | null>(null);
  /** Whether the viewport has been fitted at least once (prevents redundant fits). */
  const fittedRef = useRef(false);

  // Clear in-progress draw points when tool changes
  useEffect(() => {
    drawPointsRef.current = [];
  }, [activeTool]);

  // Recompute extents when entities change, then fit
  useEffect(() => {
    if (entities.length === 0) {
      extentsRef.current = null;
      fittedRef.current = false;
      return;
    }
    const ext = computeExtents(entities);
    extentsRef.current = ext;
    // Fit immediately if the container already has a known size
    const container = containerRef.current;
    if (container) {
      const rect = container.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        vpRef.current = zoomToFit(ext, rect.width, rect.height, 24);
        fittedRef.current = true;
        forceRender((n) => n + 1);
      }
    }
  }, [entities]);

  // Handle canvas resize + initial sizing + re-fit on resize
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const syncSize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;

      // Re-fit viewport to new canvas size (use CSS dimensions, not device pixels)
      const ext = extentsRef.current;
      if (ext) {
        vpRef.current = zoomToFit(ext, rect.width, rect.height, 24);
        fittedRef.current = true;
      }
      forceRender((n) => n + 1);
    };

    const ro = new ResizeObserver(syncSize);
    ro.observe(container);
    // Fire once immediately so the canvas gets sized before the first paint
    syncSize();
    return () => ro.disconnect();
  }, []);

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Background
      ctx.fillStyle = '#1a1a2e';
      ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr);

      // Adaptive grid (major + minor lines)
      const vp = vpRef.current;
      const cw = canvas.width / dpr;
      const ch = canvas.height / dpr;

      // Compute grid step so that grid lines are ~50-500px apart
      const rawStep = 50 / vp.scale;
      const exponent = Math.floor(Math.log10(rawStep));
      const minorStep = Math.pow(10, exponent);
      const majorStep = minorStep * 10;
      const minorPx = minorStep * vp.scale;
      const majorPx = majorStep * vp.scale;

      // Draw minor grid if spacing > 8px
      if (minorPx > 8) {
        ctx.strokeStyle = 'rgba(255,255,255,0.03)';
        ctx.lineWidth = 1;
        const startX = Math.floor(-vp.offsetX / minorPx) * minorPx + vp.offsetX;
        const startY = Math.floor(-vp.offsetY / minorPx) * minorPx + vp.offsetY;
        ctx.beginPath();
        for (let x = startX; x < cw; x += minorPx) {
          ctx.moveTo(x, 0);
          ctx.lineTo(x, ch);
        }
        for (let y = startY; y < ch; y += minorPx) {
          ctx.moveTo(0, y);
          ctx.lineTo(cw, y);
        }
        ctx.stroke();
      }

      // Draw major grid if spacing > 8px
      if (majorPx > 8) {
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 1;
        const startX = Math.floor(-vp.offsetX / majorPx) * majorPx + vp.offsetX;
        const startY = Math.floor(-vp.offsetY / majorPx) * majorPx + vp.offsetY;
        ctx.beginPath();
        for (let x = startX; x < cw; x += majorPx) {
          ctx.moveTo(x, 0);
          ctx.lineTo(x, ch);
        }
        for (let y = startY; y < ch; y += majorPx) {
          ctx.moveTo(0, y);
          ctx.lineTo(cw, y);
        }
        ctx.stroke();
      }

      renderEntities(ctx, entities, vp, visibleLayers, selectedEntityIdRef.current, cw, ch);
      renderAnnotations(ctx, annotations, vp, selectedAnnotationIdRef.current);

      // Draw polyline measurements overlay for selected entity
      const selId = selectedEntityIdRef.current;
      if (selId) {
        const selEnt = entities.find((e) => e.id === selId);
        if (selEnt?.type === 'LWPOLYLINE' && selEnt.vertices && selEnt.vertices.length >= 2) {
          renderPolylineMeasurements(ctx, selEnt, vp);
        }
      }

      // Draw in-progress annotation points
      const pts = drawPointsRef.current;
      const curTool = activeToolRef.current;
      const curColor = activeColorRef.current;
      if (pts.length > 0 && curTool !== 'select' && curTool !== 'pan') {
        ctx.strokeStyle = curColor;
        ctx.fillStyle = curColor;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        const screenPts = pts.map((p) => ({
          x: p.x * vp.scale + vp.offsetX,
          y: -p.y * vp.scale + vp.offsetY,
        }));
        const sp0 = screenPts[0]!;
        ctx.beginPath();
        ctx.moveTo(sp0.x, sp0.y);
        for (let i = 1; i < screenPts.length; i++) {
          ctx.lineTo(screenPts[i]!.x, screenPts[i]!.y);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        for (const sp of screenPts) {
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entities, annotations, visibleLayers]);

  // Wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    vpRef.current = applyZoom(vpRef.current, factor, cx, cy);
  }, []);

  // Mouse down
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      if (activeTool === 'pan' || e.button === 1) {
        isPanningRef.current = true;
        lastMouseRef.current = { x: e.clientX, y: e.clientY };
        return;
      }

      if (activeTool === 'select') {
        // Hit test entities — tests points, segments, and circles
        const world = screenToWorld(sx, sy, vpRef.current);
        let closest: string | null = null;
        let closestDist = 10 / vpRef.current.scale; // 10px tolerance in world units

        for (const ent of entities) {
          if (!visibleLayers.has(ent.layer)) continue;
          let d = Infinity;

          // LWPOLYLINE — test every segment
          if (ent.type === 'LWPOLYLINE' && ent.vertices && ent.vertices.length >= 2) {
            for (let i = 0; i < ent.vertices.length - 1; i++) {
              const sd = pointToSegmentDistance(world, ent.vertices[i]!, ent.vertices[i + 1]!);
              if (sd < d) d = sd;
            }
            // Closing segment
            if (ent.closed && ent.vertices.length >= 3) {
              const sd = pointToSegmentDistance(world, ent.vertices[ent.vertices.length - 1]!, ent.vertices[0]!);
              if (sd < d) d = sd;
            }
          }
          // LINE — test segment
          else if (ent.type === 'LINE' && ent.start && ent.end) {
            d = pointToSegmentDistance(world, ent.start, ent.end);
          }
          // CIRCLE — test distance to circumference
          else if (ent.type === 'CIRCLE' && ent.start && ent.radius) {
            const toCenter = calculateDistance(world, ent.start);
            d = Math.abs(toCenter - ent.radius);
          }
          // ARC — test distance to arc
          else if (ent.type === 'ARC' && ent.start && ent.radius) {
            const toCenter = calculateDistance(world, ent.start);
            d = Math.abs(toCenter - ent.radius);
          }
          // Fallback — test start point
          else if (ent.start) {
            d = calculateDistance(world, ent.start);
          }

          if (d < closestDist) {
            closestDist = d;
            closest = ent.id;
          }
        }
        onSelectEntity(closest);
        onSelectAnnotation(null);
        return;
      }

      // Annotation tools: record point in world coords
      const world = screenToWorld(sx, sy, vpRef.current);
      const pts = [...drawPointsRef.current, world];
      drawPointsRef.current = pts;

      // For two-point tools, finalize on second click
      if (
        (activeTool === 'distance' || activeTool === 'arrow' || activeTool === 'rectangle') &&
        pts.length === 2
      ) {
        const annType =
          activeTool === 'distance' ? 'distance' : activeTool === 'arrow' ? 'arrow' : 'rectangle';
        const payload: Parameters<Props['onAnnotationCreated']>[0] = {
          type: annType,
          points: pts,
        };
        if (activeTool === 'distance') {
          payload.measurement_value = calculateDistance(pts[0]!, pts[1]!);
          payload.measurement_unit = 'm';
        }
        onAnnotationCreated(payload);
        drawPointsRef.current = [];
      }

      // Text pin: single click
      if (activeTool === 'text_pin' && pts.length === 1) {
        const label = window.prompt(t('dwg_takeoff.enter_label', 'Enter label:'));
        if (label) {
          onAnnotationCreated({ type: 'text_pin', points: pts, text: label });
        }
        drawPointsRef.current = [];
      }
    },
    [activeTool, entities, visibleLayers, onSelectEntity, onSelectAnnotation, onAnnotationCreated],
  );

  // Mouse move (pan)
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanningRef.current) {
      const dx = e.clientX - lastMouseRef.current.x;
      const dy = e.clientY - lastMouseRef.current.y;
      vpRef.current = applyPan(vpRef.current, dx, dy);
      lastMouseRef.current = { x: e.clientX, y: e.clientY };
    }
  }, []);

  // Mouse up
  const handleMouseUp = useCallback(() => {
    isPanningRef.current = false;
  }, []);

  // Double-click to finish area polygon
  const handleDoubleClick = useCallback(() => {
    if (activeTool === 'area' && drawPointsRef.current.length >= 3) {
      const pts = drawPointsRef.current;
      onAnnotationCreated({
        type: 'area',
        points: pts,
        measurement_value: calculateArea(pts),
        measurement_unit: 'm\u00B2',
      });
      drawPointsRef.current = [];
    }
  }, [activeTool, onAnnotationCreated]);

  /** Reset viewport to fit all drawing content. */
  const handleFitAll = useCallback(() => {
    const container = containerRef.current;
    const ext = extentsRef.current;
    if (!container || !ext) return;
    const rect = container.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      vpRef.current = zoomToFit(ext, rect.width, rect.height, 24);
      forceRender((n) => n + 1);
    }
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden bg-[#1a1a2e]"
      style={{ cursor: activeTool === 'pan' ? 'grab' : activeTool === 'select' ? 'default' : 'crosshair' }}
    >
      <canvas
        ref={canvasRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onDoubleClick={handleDoubleClick}
        className="h-full w-full"
      />
      {/* Fit-all button (bottom-right overlay) */}
      {extentsRef.current && (
        <button
          onClick={handleFitAll}
          className="absolute bottom-3 right-3 h-8 px-2.5 rounded-lg
                     bg-white/10 hover:bg-white/20 backdrop-blur-sm
                     text-white/70 hover:text-white text-xs font-medium
                     flex items-center gap-1.5 transition-colors
                     border border-white/10"
          title={t('dwg_takeoff.fit_all', { defaultValue: 'Fit to drawing bounds' })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
          </svg>
          {t('dwg_takeoff.fit', { defaultValue: 'Fit' })}
        </button>
      )}
    </div>
  );
}

/* ── Polyline measurement overlay (rendered on canvas) ───────────── */

function renderPolylineMeasurements(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  const verts = entity.vertices!;
  const closed = !!entity.closed;
  const segments = getSegmentLengths(verts, closed);
  const perimeter = segments.reduce((a, b) => a + b, 0);
  const area = closed ? calculateArea(verts) : 0;

  ctx.save();

  // ── Vertex dots (cyan) ──
  ctx.fillStyle = '#06b6d4';
  for (const v of verts) {
    const sp = worldToScreen(v.x, v.y, vp);
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Segment length labels ──
  const fontSize = Math.max(9, Math.min(12, 10 / vp.scale * 100));
  ctx.font = `600 ${fontSize}px ui-monospace, monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const allVerts = closed ? [...verts, verts[0]!] : verts;
  for (let i = 0; i < allVerts.length - 1; i++) {
    const a = allVerts[i]!;
    const b = allVerts[i + 1]!;
    const mid = segmentMidpoint(a, b);
    const sp = worldToScreen(mid.x, mid.y, vp);
    const len = segments[i]!;
    const label = formatMeasurement(len, 'm');

    // Background pill
    const tw = ctx.measureText(label).width + 10;
    const th = fontSize + 6;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
    roundRect(ctx, sp.x - tw / 2, sp.y - th / 2, tw, th, 4);
    ctx.fill();

    // Text
    ctx.fillStyle = '#fbbf24'; // amber
    ctx.fillText(label, sp.x, sp.y);
  }

  // ── Perimeter label (top-right of bounding box) ──
  const bbox = verts.reduce(
    (acc, v) => ({
      minX: Math.min(acc.minX, v.x), minY: Math.min(acc.minY, v.y),
      maxX: Math.max(acc.maxX, v.x), maxY: Math.max(acc.maxY, v.y),
    }),
    { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity },
  );
  const topRight = worldToScreen(bbox.maxX, bbox.maxY, vp);

  // Perimeter badge
  const perimLabel = `P = ${formatMeasurement(perimeter, 'm')}`;
  ctx.font = `700 ${fontSize + 1}px ui-sans-serif, sans-serif`;
  const ptw = ctx.measureText(perimLabel).width + 14;
  const pth = fontSize + 10;
  const px = topRight.x + 8;
  const py = topRight.y - 4;
  ctx.fillStyle = 'rgba(16, 185, 129, 0.9)'; // emerald
  roundRect(ctx, px, py, ptw, pth, 5);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.textAlign = 'left';
  ctx.fillText(perimLabel, px + 7, py + pth / 2);

  // Area badge (below perimeter, only for closed polylines)
  if (closed && area > 0) {
    const areaLabel = `A = ${formatMeasurement(area, 'm²')}`;
    const atw = ctx.measureText(areaLabel).width + 14;
    const ath = fontSize + 10;
    const ay = py + pth + 4;
    ctx.fillStyle = 'rgba(59, 130, 246, 0.9)'; // blue
    roundRect(ctx, px, ay, atw, ath, 5);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.fillText(areaLabel, px + 7, ay + ath / 2);

    // Semi-transparent area fill on the polygon itself
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = '#3b82f6';
    ctx.beginPath();
    const sp0 = worldToScreen(verts[0]!.x, verts[0]!.y, vp);
    ctx.moveTo(sp0.x, sp0.y);
    for (let i = 1; i < verts.length; i++) {
      const sp = worldToScreen(verts[i]!.x, verts[i]!.y, vp);
      ctx.lineTo(sp.x, sp.y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  ctx.restore();
}

/** Canvas2D rounded rectangle helper. */
function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

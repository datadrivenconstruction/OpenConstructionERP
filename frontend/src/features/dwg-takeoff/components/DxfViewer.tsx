/**
 * Canvas2D-based DXF entity renderer with pan, zoom, selection, and annotation overlay.
 */

import { useRef, useEffect, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
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
  pointInPolygon,
  getSegmentLengths,
  segmentMidpoint,
  formatMeasurement,
  polygonCentroid,
} from '../lib/measurement';

/* ── Text Pin popup types & constants ─────────────────────────────────── */

interface TextPinPopupState {
  worldPt: { x: number; y: number };
  screenPt: { x: number; y: number };
}

const TEXT_PIN_COLORS = [
  '#000000',
  '#ffffff',
  '#ef4444',
  '#f59e0b',
  '#22c55e',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
];

const FONT_SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32];

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
    color?: string;
    fontSize?: number;
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
  const [textPinPopup, setTextPinPopup] = useState<TextPinPopupState | null>(null);
  /** Last computed drawing extents — kept to re-fit on resize. */
  const extentsRef = useRef<Extents | null>(null);
  /** Whether the viewport has been fitted at least once (prevents redundant fits). */
  const fittedRef = useRef(false);

  // Clear in-progress draw points and dismiss text pin popup when tool changes
  useEffect(() => {
    drawPointsRef.current = [];
    setTextPinPopup(null);
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

  // Wheel zoom — use native listener with { passive: false } so preventDefault() works
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      vpRef.current = applyZoom(vpRef.current, factor, cx, cy);
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
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

          // LWPOLYLINE — test every segment + interior for closed polygons
          if (ent.type === 'LWPOLYLINE' && ent.vertices && ent.vertices.length >= 2) {
            // Test distance to each segment edge
            for (let i = 0; i < ent.vertices.length - 1; i++) {
              const sd = pointToSegmentDistance(world, ent.vertices[i]!, ent.vertices[i + 1]!);
              if (sd < d) d = sd;
            }
            // Closing segment
            if (ent.closed && ent.vertices.length >= 3) {
              const sd = pointToSegmentDistance(world, ent.vertices[ent.vertices.length - 1]!, ent.vertices[0]!);
              if (sd < d) d = sd;
            }
            // For closed polygons, also allow clicking inside the filled area
            if (ent.closed && ent.vertices.length >= 3 && pointInPolygon(world, ent.vertices)) {
              d = 0;
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

      // Text pin: single click — show floating popup instead of window.prompt
      if (activeTool === 'text_pin' && pts.length === 1) {
        const worldPt = pts[0]!;
        setTextPinPopup({ worldPt, screenPt: { x: sx, y: sy } });
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

  /** Confirm text pin annotation from the floating popup. */
  const handleTextPinConfirm = useCallback(
    (label: string, color: string, fontSize: number) => {
      if (!textPinPopup || !label.trim()) return;
      onAnnotationCreated({
        type: 'text_pin',
        points: [textPinPopup.worldPt],
        text: label.trim(),
        color,
        fontSize,
      });
      setTextPinPopup(null);
    },
    [textPinPopup, onAnnotationCreated],
  );

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden bg-[#1a1a2e]"
      style={{ cursor: activeTool === 'pan' ? 'grab' : activeTool === 'select' ? 'default' : 'crosshair' }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onDoubleClick={handleDoubleClick}
        className="h-full w-full"
      />
      {/* Text pin floating popup */}
      {textPinPopup && (
        <TextPinPopup
          screenPt={textPinPopup.screenPt}
          defaultColor={activeColor}
          onConfirm={handleTextPinConfirm}
          onCancel={() => setTextPinPopup(null)}
        />
      )}
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

/* ── Text Pin Popup (floating annotation form) ────────────────────── */

function TextPinPopup({
  screenPt,
  defaultColor,
  onConfirm,
  onCancel,
}: {
  screenPt: { x: number; y: number };
  defaultColor: string;
  onConfirm: (label: string, color: string, fontSize: number) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState('');
  const [color, setColor] = useState(defaultColor);
  const [fontSize, setFontSize] = useState(14);
  const inputRef = useRef<HTMLInputElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  // Autofocus the input on mount
  useEffect(() => {
    // Small timeout to let the DOM settle
    const timer = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(timer);
  }, []);

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onCancel]);

  // Position: offset 12px right and 12px down from click point, but keep within viewport
  const popupWidth = 260;
  const popupHeight = 220;
  const left = Math.min(screenPt.x + 12, (popupRef.current?.parentElement?.clientWidth ?? 9999) - popupWidth - 8);
  const top = Math.min(screenPt.y + 12, (popupRef.current?.parentElement?.clientHeight ?? 9999) - popupHeight - 8);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (label.trim()) onConfirm(label, color, fontSize);
  };

  return (
    <div
      ref={popupRef}
      className="absolute z-50 animate-in fade-in slide-in-from-top-1 duration-150"
      style={{ left: Math.max(8, left), top: Math.max(8, top), width: popupWidth }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-white/15 bg-[#1e1e38]/95 shadow-2xl backdrop-blur-md"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
          <span className="text-xs font-semibold text-white/90">
            {t('dwg_takeoff.text_annotation', 'Text Annotation')}
          </span>
          <button
            type="button"
            onClick={onCancel}
            className="flex h-5 w-5 items-center justify-center rounded-md
                       text-white/40 hover:text-white/80 hover:bg-white/10 transition-colors"
          >
            <X size={12} />
          </button>
        </div>

        <div className="px-3 py-2.5 space-y-3">
          {/* Text input */}
          <input
            ref={inputRef}
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('dwg_takeoff.enter_label', 'Enter label...')}
            className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5
                       text-sm text-white placeholder:text-white/30
                       focus:outline-none focus:ring-1 focus:ring-emerald-500/60 focus:border-emerald-500/40
                       transition-colors"
          />

          {/* Color picker */}
          <div>
            <label className="block text-[10px] font-medium text-white/50 uppercase tracking-wider mb-1.5">
              {t('dwg_takeoff.color', 'Color')}
            </label>
            <div className="flex items-center gap-1.5">
              {TEXT_PIN_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={`h-5 w-5 rounded-full border-2 transition-all ${
                    color === c
                      ? 'scale-125 border-emerald-400 shadow-sm shadow-emerald-400/30'
                      : 'border-transparent hover:scale-110'
                  }`}
                  style={{
                    backgroundColor: c,
                    boxShadow: c === '#ffffff' && color !== c ? 'inset 0 0 0 1px rgba(255,255,255,0.3)' : undefined,
                  }}
                />
              ))}
            </div>
          </div>

          {/* Font size selector */}
          <div>
            <label className="block text-[10px] font-medium text-white/50 uppercase tracking-wider mb-1.5">
              {t('dwg_takeoff.font_size', 'Font Size')}
            </label>
            <select
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value))}
              className="w-full rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5
                         text-sm text-white appearance-none
                         focus:outline-none focus:ring-1 focus:ring-emerald-500/60 focus:border-emerald-500/40
                         transition-colors cursor-pointer"
            >
              {FONT_SIZES.map((s) => (
                <option key={s} value={s} className="bg-[#1e1e38] text-white">
                  {s}px
                </option>
              ))}
            </select>
          </div>

          {/* Preview */}
          <div className="flex items-center gap-2 rounded-lg bg-white/5 px-2.5 py-1.5 min-h-[28px]">
            <span className="text-[10px] text-white/40 flex-shrink-0">
              {t('dwg_takeoff.preview', 'Preview')}:
            </span>
            <span
              className="truncate font-medium"
              style={{
                color,
                fontSize: `${Math.min(fontSize, 20)}px`,
                lineHeight: 1.2,
              }}
            >
              {label || t('dwg_takeoff.sample_text', 'Sample')}
            </span>
          </div>

          {/* Buttons */}
          <div className="flex items-center gap-2 pt-0.5">
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5
                         text-xs font-medium text-white/70 hover:text-white hover:bg-white/10
                         transition-colors"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              type="submit"
              disabled={!label.trim()}
              className="flex-1 rounded-lg bg-emerald-600 px-3 py-1.5
                         text-xs font-semibold text-white
                         hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed
                         transition-colors shadow-sm shadow-emerald-600/30"
            >
              {t('dwg_takeoff.place', 'Place')}
            </button>
          </div>
        </div>
      </form>
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

  // ── Semi-transparent area fill (drawn first, sits behind everything) ──
  if (closed && area > 0) {
    ctx.beginPath();
    const fp = worldToScreen(verts[0]!.x, verts[0]!.y, vp);
    ctx.moveTo(fp.x, fp.y);
    for (let i = 1; i < verts.length; i++) {
      const sp = worldToScreen(verts[i]!.x, verts[i]!.y, vp);
      ctx.lineTo(sp.x, sp.y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(59, 130, 246, 0.12)';
    ctx.fill();
    // Subtle dashed border for the fill region
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // ── Highlighted polyline stroke (glow effect over the selection blue) ──
  ctx.beginPath();
  const h0 = worldToScreen(verts[0]!.x, verts[0]!.y, vp);
  ctx.moveTo(h0.x, h0.y);
  for (let i = 1; i < verts.length; i++) {
    const sp = worldToScreen(verts[i]!.x, verts[i]!.y, vp);
    ctx.lineTo(sp.x, sp.y);
  }
  if (closed) ctx.closePath();
  // Outer glow
  ctx.strokeStyle = 'rgba(59, 130, 246, 0.3)';
  ctx.lineWidth = 6;
  ctx.stroke();
  // Inner bright stroke
  ctx.strokeStyle = '#60a5fa';
  ctx.lineWidth = 2;
  ctx.stroke();

  // ── Vertex dots with highlight ring ──
  for (let vi = 0; vi < verts.length; vi++) {
    const v = verts[vi]!;
    const sp = worldToScreen(v.x, v.y, vp);
    // Outer ring
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(6, 182, 212, 0.25)';
    ctx.fill();
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    // Inner dot
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#06b6d4';
    ctx.fill();
  }

  // ── Segment length pills (white text on colored background) ──
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

    const tw = ctx.measureText(label).width + 12;
    const th = fontSize + 8;

    // Drop shadow for depth
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;

    // Amber-tinted background pill with full rounding
    ctx.fillStyle = 'rgba(180, 120, 0, 0.88)';
    roundRect(ctx, sp.x - tw / 2, sp.y - th / 2, tw, th, th / 2);
    ctx.fill();

    // Reset shadow before drawing text
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    // White text on colored pill for readability
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, sp.x, sp.y + 0.5);
  }

  // ── Perimeter badge (top-right of bounding box) ──
  const bbox = verts.reduce(
    (acc, v) => ({
      minX: Math.min(acc.minX, v.x), minY: Math.min(acc.minY, v.y),
      maxX: Math.max(acc.maxX, v.x), maxY: Math.max(acc.maxY, v.y),
    }),
    { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity },
  );
  const topRight = worldToScreen(bbox.maxX, bbox.maxY, vp);

  const badgeFontSize = fontSize + 1;
  ctx.font = `700 ${badgeFontSize}px ui-sans-serif, sans-serif`;
  ctx.textAlign = 'left';

  const perimLabel = `P = ${formatMeasurement(perimeter, 'm')}`;
  const ptw = ctx.measureText(perimLabel).width + 16;
  const pth = badgeFontSize + 12;
  const px = topRight.x + 10;
  const py = topRight.y - 6;

  // Badge shadow
  ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;

  ctx.fillStyle = 'rgba(16, 185, 129, 0.92)';
  roundRect(ctx, px, py, ptw, pth, 6);
  ctx.fill();

  ctx.shadowColor = 'transparent';
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;

  ctx.fillStyle = '#ffffff';
  ctx.fillText(perimLabel, px + 8, py + pth / 2 + 0.5);

  // ── Area badge (at polygon centroid for closed polylines) ──
  if (closed && area > 0) {
    const areaLabel = `A = ${formatMeasurement(area, 'm\u00B2')}`;
    const atw = ctx.measureText(areaLabel).width + 16;
    const ath = badgeFontSize + 12;

    // Place at polygon centroid for natural positioning
    const centroid = polygonCentroid(verts);
    const centroidScreen = worldToScreen(centroid.x, centroid.y, vp);

    ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
    ctx.shadowBlur = 6;
    ctx.shadowOffsetY = 2;

    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(59, 130, 246, 0.92)';
    roundRect(ctx, centroidScreen.x - atw / 2, centroidScreen.y - ath / 2, atw, ath, 6);
    ctx.fill();

    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    ctx.fillStyle = '#ffffff';
    ctx.fillText(areaLabel, centroidScreen.x, centroidScreen.y + 0.5);
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

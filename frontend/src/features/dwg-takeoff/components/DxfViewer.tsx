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

/** Emitted when a user selects an entity, includes screen coords for floating UI. */
export interface EntitySelectEvent {
  entityId: string | null;
  /** Screen-space coordinates relative to the viewer container for floating UI. */
  screenX: number;
  screenY: number;
  /** Whether Shift was held — caller adds/toggles vs replaces the selection. */
  shiftKey?: boolean;
}

/** Right-click context menu target. */
export interface EntityContextMenuEvent {
  entityId: string;
  screenX: number;
  screenY: number;
}

interface Props {
  entities: DxfEntity[];
  annotations: DwgAnnotation[];
  visibleLayers: Set<string>;
  activeTool: DwgTool;
  activeColor: string;
  /** Multi-select (RFC 11): empty set = no selection. Single-select is a one-item set. */
  selectedEntityIds: Set<string>;
  /** Per-entity hide (RFC 11): hidden entities are not rendered and are not hit-testable. */
  hiddenEntityIds: Set<string>;
  selectedAnnotationId: string | null;
  /**
   * Drawing scale denominator (RFC 13 #13). `1` = no scaling (raw DXF
   * units). `50` = drawing is 1:50, so every measurement shown on the
   * canvas is multiplied by 50 (length) or 2500 (area). Applies to both
   * the on-screen labels AND the `measurement_value` persisted with each
   * annotation, so takeoff totals stay in real-world units.
   */
  drawingScale?: number;
  onSelectEntity: (id: string | null, event?: EntitySelectEvent) => void;
  onSelectAnnotation: (id: string | null) => void;
  onEntityContextMenu?: (event: EntityContextMenuEvent) => void;
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
  selectedEntityIds,
  hiddenEntityIds,
  selectedAnnotationId,
  drawingScale = 1,
  onSelectEntity,
  onSelectAnnotation,
  onEntityContextMenu,
  onAnnotationCreated,
}: Props) {
  const drawingScaleRef = useRef(drawingScale);
  drawingScaleRef.current = drawingScale;
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const vpRef = useRef<ViewportState>({ offsetX: 0, offsetY: 0, scale: 1 });
  const rafRef = useRef<number>(0);
  const isPanningRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });
  const drawPointsRef = useRef<{ x: number; y: number }[]>([]);
  const mousePosRef = useRef<{ x: number; y: number } | null>(null);
  const activeToolRef = useRef(activeTool);
  activeToolRef.current = activeTool;
  const activeColorRef = useRef(activeColor);
  activeColorRef.current = activeColor;
  const selectedEntityIdsRef = useRef(selectedEntityIds);
  selectedEntityIdsRef.current = selectedEntityIds;
  const hiddenEntityIdsRef = useRef(hiddenEntityIds);
  hiddenEntityIdsRef.current = hiddenEntityIds;
  const selectedAnnotationIdRef = useRef(selectedAnnotationId);
  selectedAnnotationIdRef.current = selectedAnnotationId;
  /**
   * Last click position + candidate cycle index (RFC 11 §4.2).
   * Tracks the ranked hit-test candidates at the last click so that a
   * second click at the same spot (within 6px + 300ms) advances to the
   * next candidate in the ranked list.
   */
  const lastHitRef = useRef<{
    x: number;
    y: number;
    index: number;
    ts: number;
    candidateIds: string[];
  } | null>(null);
  const [, forceRender] = useState(0);
  const [textPinPopup, setTextPinPopup] = useState<TextPinPopupState | null>(null);
  const [isPanning, setIsPanning] = useState(false);
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

      // Filter out hidden entities from both rendering and hit-testing
      const hidden = hiddenEntityIdsRef.current;
      const visibleEntities = hidden.size > 0
        ? entities.filter((e) => !hidden.has(e.id))
        : entities;
      // Highlight only the first selected id via the legacy single-id API; any
      // additional selected entities get a secondary halo drawn below.
      const selectedIds = selectedEntityIdsRef.current;
      const primarySelId = selectedIds.size > 0 ? selectedIds.values().next().value ?? null : null;
      renderEntities(ctx, visibleEntities, vp, visibleLayers, primarySelId, cw, ch);

      // Draw secondary selection halos for additional selected entities (multi-select)
      if (selectedIds.size > 1) {
        renderMultiSelectionHalos(ctx, visibleEntities, vp, selectedIds, primarySelId);
      }

      renderAnnotations(
        ctx,
        annotations,
        vp,
        selectedAnnotationIdRef.current,
        drawingScaleRef.current,
      );

      // Draw polyline measurements overlay for the primary selected entity only
      if (primarySelId) {
        const selEnt = entities.find((e) => e.id === primarySelId);
        if (selEnt?.type === 'LWPOLYLINE' && selEnt.vertices && selEnt.vertices.length >= 2) {
          renderPolylineMeasurements(ctx, selEnt, vp, drawingScaleRef.current);
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

        // ── Rubber band preview line from last placed point to cursor ──
        const mouseWorld = mousePosRef.current;
        if (mouseWorld) {
          const lastPt = pts[pts.length - 1]!;
          const firstPt = pts[0]!;
          const lastScreen = worldToScreen(lastPt.x, lastPt.y, vp);
          const mouseScreen = worldToScreen(mouseWorld.x, mouseWorld.y, vp);
          const firstScreen = worldToScreen(firstPt.x, firstPt.y, vp);

          // Parse active color to apply 60% opacity
          ctx.save();
          ctx.globalAlpha = 0.6;
          ctx.strokeStyle = curColor;
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 3]);

          if (curTool === 'rectangle' && pts.length === 1) {
            // Rectangle preview: dashed rect from first point to mouse
            const rx = Math.min(firstScreen.x, mouseScreen.x);
            const ry = Math.min(firstScreen.y, mouseScreen.y);
            const rw = Math.abs(mouseScreen.x - firstScreen.x);
            const rh = Math.abs(mouseScreen.y - firstScreen.y);
            ctx.beginPath();
            ctx.rect(rx, ry, rw, rh);
            ctx.stroke();
          } else if (curTool === 'area') {
            // Area tool: line from last point to mouse + closing line from mouse to first point
            ctx.beginPath();
            ctx.moveTo(lastScreen.x, lastScreen.y);
            ctx.lineTo(mouseScreen.x, mouseScreen.y);
            ctx.stroke();
            // Closing line (lighter)
            ctx.globalAlpha = 0.35;
            ctx.beginPath();
            ctx.moveTo(mouseScreen.x, mouseScreen.y);
            ctx.lineTo(firstScreen.x, firstScreen.y);
            ctx.stroke();
            ctx.globalAlpha = 0.6;
          } else {
            // Distance, arrow, and other tools: single line from last point to mouse
            ctx.beginPath();
            ctx.moveTo(lastScreen.x, lastScreen.y);
            ctx.lineTo(mouseScreen.x, mouseScreen.y);
            ctx.stroke();
          }

          ctx.setLineDash([]);
          ctx.globalAlpha = 1.0;

          // ── Live measurement label near the midpoint of the rubber band ──
          const dist = calculateDistance(lastPt, mouseWorld) * drawingScaleRef.current;
          const label = formatMeasurement(dist, 'm');
          const midX = (lastScreen.x + mouseScreen.x) / 2;
          const midY = (lastScreen.y + mouseScreen.y) / 2;

          const labelFontSize = 11;
          ctx.font = `600 ${labelFontSize}px ui-monospace, monospace`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';

          const textWidth = ctx.measureText(label).width;
          const pillW = textWidth + 12;
          const pillH = labelFontSize + 8;

          // Dark semi-transparent background pill
          ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
          roundRect(ctx, midX - pillW / 2, midY - pillH / 2 - 12, pillW, pillH, pillH / 2);
          ctx.fill();

          // White text
          ctx.fillStyle = '#ffffff';
          ctx.fillText(label, midX, midY - 12);

          ctx.restore();
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
        setIsPanning(true);
        lastMouseRef.current = { x: e.clientX, y: e.clientY };
        return;
      }

      if (activeTool === 'select') {
        // Ranked hit-test (RFC 11 §4.2): build candidate list, score, cycle.
        const world = screenToWorld(sx, sy, vpRef.current);
        const tolerance = 10 / vpRef.current.scale;
        const hidden = hiddenEntityIdsRef.current;

        const candidates = collectHitCandidates(
          world,
          entities,
          visibleLayers,
          hidden,
          tolerance,
        );

        let picked: string | null = null;

        if (candidates.length > 0) {
          // Cycle-through: within 6 CSS px + 300 ms, advance to the next
          // ranked candidate if the same set is under the cursor.
          const now = performance.now();
          const last = lastHitRef.current;
          const sameSpot =
            last != null &&
            Math.hypot(sx - last.x, sy - last.y) < 6 &&
            now - last.ts < 300 &&
            last.candidateIds.length === candidates.length &&
            last.candidateIds.every((id, i) => id === candidates[i]!.id);

          const index = sameSpot ? (last!.index + 1) % candidates.length : 0;
          picked = candidates[index]!.id;
          lastHitRef.current = {
            x: sx,
            y: sy,
            index,
            ts: now,
            candidateIds: candidates.map((c) => c.id),
          };
        } else {
          lastHitRef.current = null;
        }

        onSelectEntity(
          picked,
          picked
            ? { entityId: picked, screenX: sx, screenY: sy, shiftKey: e.shiftKey }
            : undefined,
        );
        onSelectAnnotation(null);
        return;
      }

      // Annotation tools: record point in world coords
      const world = screenToWorld(sx, sy, vpRef.current);
      const pts = [...drawPointsRef.current, world];
      drawPointsRef.current = pts;

      // For two-point tools, finalize on second click
      if (
        (activeTool === 'distance' ||
          activeTool === 'arrow' ||
          activeTool === 'rectangle' ||
          activeTool === 'line' ||
          activeTool === 'circle') &&
        pts.length === 2
      ) {
        const annType: DwgAnnotation['type'] =
          activeTool === 'distance' ? 'distance'
          : activeTool === 'arrow' ? 'arrow'
          : activeTool === 'rectangle' ? 'rectangle'
          : activeTool === 'line' ? 'line'
          : 'circle';
        const payload: Parameters<Props['onAnnotationCreated']>[0] = {
          type: annType,
          points: pts,
        };
        // Persist the raw DXF measurement. The current drawing scale is
        // applied on the fly in the render path (AnnotationOverlay +
        // Properties panel), so changing the Scale tab immediately
        // reflects on every existing label without a round trip.
        if (activeTool === 'distance' || activeTool === 'line') {
          payload.measurement_value = calculateDistance(pts[0]!, pts[1]!);
          payload.measurement_unit = 'm';
        }
        if (activeTool === 'circle') {
          // Circle: pts[0] is center, pts[1] is on the circumference.
          const r = calculateDistance(pts[0]!, pts[1]!);
          payload.measurement_value = Math.PI * r * r;
          payload.measurement_unit = 'm\u00B2';
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

  // Mouse move (pan + rubber band tracking)
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanningRef.current) {
      const dx = e.clientX - lastMouseRef.current.x;
      const dy = e.clientY - lastMouseRef.current.y;
      vpRef.current = applyPan(vpRef.current, dx, dy);
      lastMouseRef.current = { x: e.clientX, y: e.clientY };
    } else {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (rect) {
        const sx = e.clientX - rect.left;
        const sy = e.clientY - rect.top;
        mousePosRef.current = screenToWorld(sx, sy, vpRef.current);
      }
    }
  }, []);

  // Mouse up
  const handleMouseUp = useCallback(() => {
    isPanningRef.current = false;
    setIsPanning(false);
  }, []);

  // Mouse leave — clear rubber band cursor and stop panning
  const handleMouseLeave = useCallback(() => {
    isPanningRef.current = false;
    setIsPanning(false);
    mousePosRef.current = null;
  }, []);

  /**
   * Right-click context menu. Hit-test once to find what was clicked on,
   * then hand off to the parent to render the actual menu.
   */
  const handleContextMenu = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (!onEntityContextMenu) return;
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const world = screenToWorld(sx, sy, vpRef.current);
      const tolerance = 10 / vpRef.current.scale;
      const candidates = collectHitCandidates(
        world,
        entities,
        visibleLayers,
        hiddenEntityIdsRef.current,
        tolerance,
      );
      if (candidates.length === 0) return;
      onEntityContextMenu({
        entityId: candidates[0]!.id,
        screenX: sx,
        screenY: sy,
      });
    },
    [entities, visibleLayers, onEntityContextMenu],
  );

  // Double-click to finish multi-point tools (area polygon and open polyline).
  const handleDoubleClick = useCallback(() => {
    const pts = drawPointsRef.current;
    if (activeTool === 'area' && pts.length >= 3) {
      // Persist raw area; display path multiplies by drawingScale².
      onAnnotationCreated({
        type: 'area',
        points: pts,
        measurement_value: calculateArea(pts),
        measurement_unit: 'm\u00B2',
      });
      drawPointsRef.current = [];
    } else if (activeTool === 'polyline' && pts.length >= 2) {
      // Open polyline — sum of segment lengths, no area.
      let totalLen = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        totalLen += calculateDistance(pts[i]!, pts[i + 1]!);
      }
      onAnnotationCreated({
        type: 'polyline',
        points: pts,
        measurement_value: totalLen,
        measurement_unit: 'm',
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

  /** Confirm text pin annotation from the floating popup. An empty label is
   *  still accepted — the marker alone is useful as a quick pin — so the
   *  user sees immediate feedback even if they forget to type. */
  const handleTextPinConfirm = useCallback(
    (label: string, color: string, fontSize: number) => {
      if (!textPinPopup) return;
      onAnnotationCreated({
        type: 'text_pin',
        points: [textPinPopup.worldPt],
        text: label.trim() || undefined,
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
      style={{ cursor: isPanning ? 'grabbing' : activeTool === 'pan' ? 'grab' : activeTool === 'select' ? 'default' : 'crosshair' }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onDoubleClick={handleDoubleClick}
        onContextMenu={handleContextMenu}
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
      {/* Bottom-left overlay: world coordinate readout */}
      {mousePosRef.current && entities.length > 0 && (
        <div
          className="absolute bottom-3 left-3 h-7 px-2.5 rounded-lg bg-white/10 backdrop-blur-sm
                     text-white/40 text-[10px] font-mono flex items-center gap-2
                     border border-white/10 select-none pointer-events-none"
        >
          <span>X: {mousePosRef.current.x.toFixed(2)}</span>
          <span>Y: {mousePosRef.current.y.toFixed(2)}</span>
        </div>
      )}
      {/* Bottom-right overlay: zoom level + Fit button */}
      {extentsRef.current && (
        <div className="absolute bottom-3 right-3 flex items-center gap-1.5">
          <span
            className="h-8 px-2.5 rounded-lg bg-white/10 backdrop-blur-sm text-white/50 text-[11px]
                       font-mono flex items-center border border-white/10 select-none"
          >
            {Math.round(vpRef.current.scale * 100)}%
          </span>
          <button
            onClick={handleFitAll}
            className="h-8 px-2.5 rounded-lg
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
        </div>
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
    // Accept blank label too — the colored marker alone is useful feedback
    // that a pin was placed. Users can open the annotation later to rename.
    onConfirm(label, color, fontSize);
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
  scale = 1,
): void {
  const verts = entity.vertices!;
  const closed = !!entity.closed;
  const segments = getSegmentLengths(verts, closed).map((s) => s * scale);
  const perimeter = segments.reduce((a, b) => a + b, 0);
  const area = closed ? calculateArea(verts) * scale * scale : 0;

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

/* ── Ranked hit-test (RFC 11 §4.2) ───────────────────────────────────── */

/** One entity matching the click, annotated for scoring. */
export interface HitCandidate {
  id: string;
  /** Distance from click to the nearest boundary, normalized by tolerance (0..1 inside tolerance). */
  distance: number;
  /** Whether the click is inside the closed boundary. */
  inside: boolean;
  /** Pre-computed polygon area (0 for non-polygons). Smaller areas win ties. */
  area: number;
}

/**
 * Score a candidate. Lower is better (i.e. we sort ascending and pick index 0).
 *
 *   score = 0.5·min(d,1) + 0.5·(inside ? 0 : 1) + (inside ? 0.1·log(area+1) : 0)
 *
 * Inside-hits win over boundary-hits (the +0.5 penalty for outside). Among
 * inside-hits, smaller polygons (smaller log(area+1)) win — this fixes the
 * "outer polyline always wins" bug because the inner polygon contains fewer
 * square meters and therefore scores lower.
 *
 * (The RFC draft originally wrote a subtraction for the area term; that
 * inverts the intent — larger log(area+1) would pull the outer polygon to
 * the top. We add instead. The sign was a typo in the RFC snippet; the
 * behaviour matches §4.2's stated goal.)
 */
export function scoreOf(c: HitCandidate): number {
  return (
    0.5 * Math.min(c.distance, 1)
    + 0.5 * (c.inside ? 0 : 1)
    + (c.inside ? 0.1 * Math.log(Math.max(c.area, 0) + 1) : 0)
  );
}

/**
 * Extract the cached area for a closed polyline. The `_area` field is
 * attached at entity-load time in the page component — see
 * `DwgTakeoffPage.tsx` `annotatedEntities`. Falls back to 0 for
 * non-polygons so the score reduces to pure distance.
 */
function areaOf(entity: DxfEntity): number {
  const e = entity as DxfEntity & { _area?: number };
  if (typeof e._area === 'number' && Number.isFinite(e._area)) return e._area;
  return 0;
}

/**
 * Per-entity minimum distance + inside-test used by both the click
 * handler and the right-click context-menu handler. Pure function; the
 * only side effect is pushing onto the output array.
 *
 * Extracted from the legacy inline loop at `DxfViewer.tsx:431-520` so it
 * can be unit-tested without a DOM and without React state.
 */
export function collectHitCandidates(
  world: { x: number; y: number },
  entities: DxfEntity[],
  visibleLayers: Set<string>,
  hiddenEntityIds: Set<string>,
  tolerance: number,
): HitCandidate[] {
  const out: HitCandidate[] = [];

  for (const ent of entities) {
    if (!visibleLayers.has(ent.layer)) continue;
    if (hiddenEntityIds.has(ent.id)) continue;

    let d = Infinity;
    let inside = false;

    if (ent.type === 'LWPOLYLINE' && ent.vertices && ent.vertices.length >= 2) {
      for (let i = 0; i < ent.vertices.length - 1; i++) {
        const sd = pointToSegmentDistance(world, ent.vertices[i]!, ent.vertices[i + 1]!);
        if (sd < d) d = sd;
      }
      if (ent.closed && ent.vertices.length >= 3) {
        const sd = pointToSegmentDistance(
          world, ent.vertices[ent.vertices.length - 1]!, ent.vertices[0]!,
        );
        if (sd < d) d = sd;
        if (pointInPolygon(world, ent.vertices)) {
          inside = true;
          d = 0;
        }
      }
    } else if (ent.type === 'HATCH' && ent.vertices && ent.vertices.length >= 3) {
      if (pointInPolygon(world, ent.vertices)) {
        inside = true;
        d = 0;
      } else {
        for (let i = 0; i < ent.vertices.length - 1; i++) {
          const sd = pointToSegmentDistance(world, ent.vertices[i]!, ent.vertices[i + 1]!);
          if (sd < d) d = sd;
        }
        const sd = pointToSegmentDistance(
          world, ent.vertices[ent.vertices.length - 1]!, ent.vertices[0]!,
        );
        if (sd < d) d = sd;
      }
    } else if (ent.type === 'LINE' && ent.start && ent.end) {
      d = pointToSegmentDistance(world, ent.start, ent.end);
    } else if (ent.type === 'CIRCLE' && ent.start && ent.radius) {
      const toCenter = calculateDistance(world, ent.start);
      d = Math.abs(toCenter - ent.radius);
      // Inside-test: click within the disc. Closed polylines win against the
      // ring-only hit-test — matches the intuition that clicking inside a
      // circular floor plate should select the floor.
      if (toCenter < ent.radius) {
        inside = true;
        if (d > tolerance) d = 0;
      }
    } else if (ent.type === 'ARC' && ent.start && ent.radius) {
      const toCenter = calculateDistance(world, ent.start);
      const distToCirc = Math.abs(toCenter - ent.radius);
      if (ent.start_angle != null && ent.end_angle != null) {
        let clickAngle = Math.atan2(world.y - ent.start.y, world.x - ent.start.x);
        if (clickAngle < 0) clickAngle += Math.PI * 2;
        let sa = ent.start_angle % (Math.PI * 2);
        if (sa < 0) sa += Math.PI * 2;
        let ea = ent.end_angle % (Math.PI * 2);
        if (ea < 0) ea += Math.PI * 2;
        const inArc = sa <= ea
          ? clickAngle >= sa && clickAngle <= ea
          : clickAngle >= sa || clickAngle <= ea;
        d = inArc ? distToCirc : Infinity;
      } else {
        d = distToCirc;
      }
    } else if (ent.type === 'ELLIPSE' && ent.start) {
      d = calculateDistance(world, ent.start);
      const maxR = Math.max(ent.major_radius ?? 0, ent.minor_radius ?? 0, ent.radius ?? 0);
      if (maxR > 0) d = Math.abs(d - maxR);
    } else if (ent.start) {
      d = calculateDistance(world, ent.start);
    }

    if (d > tolerance && !inside) continue;

    out.push({
      id: ent.id,
      distance: d / tolerance,
      inside,
      area: areaOf(ent),
    });
  }

  out.sort((a, b) => scoreOf(a) - scoreOf(b));
  return out;
}

/* ── Multi-selection halos ────────────────────────────────────────────── */

/**
 * Draws a secondary halo around every selected entity other than the
 * primary one (which is already highlighted by `applyStyle` inside
 * `renderEntities`). A cheap visual cue that the extra entities are
 * part of the same multi-select group.
 */
function renderMultiSelectionHalos(
  ctx: CanvasRenderingContext2D,
  entities: DxfEntity[],
  vp: ViewportState,
  selectedIds: Set<string>,
  primaryId: string | null,
): void {
  ctx.save();
  ctx.strokeStyle = 'rgba(245, 158, 11, 0.9)';
  ctx.lineWidth = 2;
  ctx.shadowColor = 'rgba(245, 158, 11, 0.45)';
  ctx.shadowBlur = 6;

  for (const ent of entities) {
    if (!selectedIds.has(ent.id) || ent.id === primaryId) continue;

    if (ent.type === 'LWPOLYLINE' && ent.vertices && ent.vertices.length >= 2) {
      ctx.beginPath();
      const sp0 = worldToScreen(ent.vertices[0]!.x, ent.vertices[0]!.y, vp);
      ctx.moveTo(sp0.x, sp0.y);
      for (let i = 1; i < ent.vertices.length; i++) {
        const sp = worldToScreen(ent.vertices[i]!.x, ent.vertices[i]!.y, vp);
        ctx.lineTo(sp.x, sp.y);
      }
      if (ent.closed) ctx.closePath();
      ctx.stroke();
    } else if (ent.type === 'LINE' && ent.start && ent.end) {
      const a = worldToScreen(ent.start.x, ent.start.y, vp);
      const b = worldToScreen(ent.end.x, ent.end.y, vp);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    } else if (ent.type === 'CIRCLE' && ent.start && ent.radius) {
      const c = worldToScreen(ent.start.x, ent.start.y, vp);
      const r = ent.radius * vp.scale;
      ctx.beginPath();
      ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
      ctx.stroke();
    } else if (ent.start) {
      const c = worldToScreen(ent.start.x, ent.start.y, vp);
      ctx.beginPath();
      ctx.arc(c.x, c.y, 6, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  ctx.restore();
}

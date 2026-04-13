/**
 * Canvas2D-based DXF entity renderer with pan, zoom, selection, and annotation overlay.
 */

import { useRef, useEffect, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DxfEntity, DwgAnnotation } from '../api';
import type { ViewportState, Extents } from '../lib/viewport';
import { zoomToFit, applyZoom, applyPan, screenToWorld } from '../lib/viewport';
import { renderEntities } from '../lib/dxf-renderer';
import { renderAnnotations } from './AnnotationOverlay';
import type { DwgTool } from './ToolPalette';
import { calculateDistance, calculateArea } from '../lib/measurement';

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

  // Clear in-progress draw points when tool changes
  useEffect(() => {
    drawPointsRef.current = [];
  }, [activeTool]);

  // Fit on first mount or when entities change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || entities.length === 0) return;
    const ext = computeExtents(entities);
    vpRef.current = zoomToFit(ext, canvas.width, canvas.height);
    forceRender((n) => n + 1);
  }, [entities]);

  // Handle canvas resize
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const ro = new ResizeObserver(() => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      forceRender((n) => n + 1);
    });
    ro.observe(container);
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

      // Grid (subtle)
      const vp = vpRef.current;
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 1;
      const gridStep = Math.pow(10, Math.floor(Math.log10(50 / vp.scale)));
      const gridPx = gridStep * vp.scale;
      if (gridPx > 8) {
        const startX = Math.floor(-vp.offsetX / gridPx) * gridPx + vp.offsetX;
        const startY = Math.floor(-vp.offsetY / gridPx) * gridPx + vp.offsetY;
        for (let x = startX; x < canvas.width / dpr; x += gridPx) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, canvas.height / dpr);
          ctx.stroke();
        }
        for (let y = startY; y < canvas.height / dpr; y += gridPx) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(canvas.width / dpr, y);
          ctx.stroke();
        }
      }

      renderEntities(ctx, entities, vp, visibleLayers, selectedEntityIdRef.current);
      renderAnnotations(ctx, annotations, vp, selectedAnnotationIdRef.current);

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
        // Hit test entities (simple proximity)
        const world = screenToWorld(sx, sy, vpRef.current);
        let closest: string | null = null;
        let closestDist = 10 / vpRef.current.scale; // 10px tolerance
        for (const ent of entities) {
          if (!visibleLayers.has(ent.layer)) continue;
          if (ent.start) {
            const dx = ent.start.x - world.x;
            const dy = ent.start.y - world.y;
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d < closestDist) {
              closestDist = d;
              closest = ent.id;
            }
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

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden"
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
    </div>
  );
}

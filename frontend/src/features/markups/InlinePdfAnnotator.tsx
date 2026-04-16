/**
 * Inline PDF annotation viewer for the Markups page.
 *
 * Renders a PDF document page with an overlay canvas for drawing
 * cloud, arrow, text, rectangle, and highlight annotations.
 * Saves markups via the markups API.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import * as pdfjsLib from 'pdfjs-dist';
import {
  ZoomIn,
  ZoomOut,
  ChevronLeft,
  ChevronRight,
  MousePointer2,
  Cloud,
  ArrowUpRight,
  Type,
  Square,
  Highlighter,
  Loader2,
  X,
  Save,
  Trash2,
  Stamp,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { createMarkup, fetchMarkups } from './api';
import type { Markup, MarkupType, CreateMarkupPayload } from './api';

// Configure PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

/* ── Types ─────────────────────────────────────────────────────────────── */

type AnnotationTool = 'select' | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight' | 'stamp';

interface StampDef {
  name: string;
  label: string;
  color: string;
  bgColor: string;
}

interface DrawnAnnotation {
  id: string;
  tool: AnnotationTool;
  /**
   * Annotation vertices in PDF user units (the CRS returned by
   * ``viewport.convertToPdfPoint``). These are zoom-, rotation- and
   * device-pixel-ratio-independent, so a markup saved at zoom 1.0 renders
   * correctly when reopened at any other zoom.
   *
   * Legacy markups (``coordSpace === 'canvas'``) still hold raw overlay
   * canvas pixel coordinates; the render loop converts both variants into
   * viewport pixels on the fly.
   */
  points: { x: number; y: number }[];
  /** ``'pdf'`` for new markups, ``'canvas'`` for legacy pixel-space ones. */
  coordSpace: 'pdf' | 'canvas';
  text?: string;
  color: string;
  page: number;
  stampName?: string;
}

interface Props {
  documentId: string;
  documentName: string;
  projectId: string;
  onClose: () => void;
  onMarkupCreated: () => void;
  stamps?: StampDef[];
  activeStamp?: string;
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const TOOLS: { id: AnnotationTool; icon: React.ElementType; label: string }[] = [
  { id: 'select', icon: MousePointer2, label: 'Select' },
  { id: 'cloud', icon: Cloud, label: 'Cloud' },
  { id: 'arrow', icon: ArrowUpRight, label: 'Arrow' },
  { id: 'text', icon: Type, label: 'Text' },
  { id: 'rectangle', icon: Square, label: 'Rectangle' },
  { id: 'highlight', icon: Highlighter, label: 'Highlight' },
  { id: 'stamp', icon: Stamp, label: 'Stamp' },
];

const DEFAULT_STAMPS: StampDef[] = [
  { name: 'approved', label: 'APPROVED', color: '#16a34a', bgColor: '#dcfce7' },
  { name: 'rejected', label: 'REJECTED', color: '#dc2626', bgColor: '#fee2e2' },
  { name: 'for_review', label: 'FOR REVIEW', color: '#2563eb', bgColor: '#dbeafe' },
  { name: 'revised', label: 'REVISED', color: '#9333ea', bgColor: '#f3e8ff' },
  { name: 'final', label: 'FINAL', color: '#d97706', bgColor: '#fef3c7' },
];

const PRESET_COLORS = ['#EF4444', '#3B82F6', '#22C55E', '#F97316', '#A855F7', '#6B7280'];

const ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

const TOOL_TO_MARKUP_TYPE: Record<AnnotationTool, MarkupType | null> = {
  select: null,
  cloud: 'cloud',
  arrow: 'arrow',
  text: 'text',
  rectangle: 'rectangle',
  highlight: 'highlight',
  stamp: 'stamp',
};

/* ── Component ─────────────────────────────────────────────────────────── */

export function InlinePdfAnnotator({
  documentId,
  documentName,
  projectId,
  onClose,
  onMarkupCreated,
  stamps: externalStamps,
  activeStamp: initialStamp,
}: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // PDF state
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [zoom, setZoom] = useState(1.0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Annotation state
  const [activeTool, setActiveTool] = useState<AnnotationTool>('select');
  const [activeColor, setActiveColor] = useState(PRESET_COLORS[1]!);
  const [annotations, setAnnotations] = useState<DrawnAnnotation[]>([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(null);
  const [drawEnd, setDrawEnd] = useState<{ x: number; y: number } | null>(null);
  const [textInput, setTextInput] = useState('');
  const [showTextInput, setShowTextInput] = useState(false);
  const [textPosition, setTextPosition] = useState<{ x: number; y: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [selectedStamp, setSelectedStamp] = useState(initialStamp || 'approved');
  const availableStamps = externalStamps?.length ? externalStamps : DEFAULT_STAMPS;

  // Refs
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageDimensionsRef = useRef<{ width: number; height: number }>({ width: 0, height: 0 });
  // Current rendered viewport. Required for converting between PDF user
  // units (where annotations are stored) and canvas pixels (where we draw).
  const viewportRef = useRef<pdfjsLib.PageViewport | null>(null);

  /* ── Load PDF from backend ────────────────────────────────────────── */

  useEffect(() => {
    let cancelled = false;
    let loadedDoc: pdfjsLib.PDFDocumentProxy | null = null;
    const loadPdf = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const token = useAuthStore.getState().accessToken;
        const res = await fetch(`/api/v1/documents/${documentId}/download/`, {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            'X-DDC-Client': 'OE/1.0',
          },
        });
        if (!res.ok) throw new Error(`Failed to load document: ${res.statusText}`);
        const arrayBuffer = await res.arrayBuffer();
        if (cancelled) return;
        const doc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        if (cancelled) {
          // Component unmounted while the doc was loading — free native
          // resources immediately to prevent the classic PDF.js leak.
          doc.destroy?.();
          return;
        }
        loadedDoc = doc;
        setPdfDoc(doc);
        setTotalPages(doc.numPages);
        setCurrentPage(1);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load PDF');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    loadPdf();
    return () => {
      cancelled = true;
      // Release the worker-side document; without this PDF.js holds onto
      // the entire file buffer + parsed objects for the lifetime of the tab.
      loadedDoc?.destroy?.();
    };
  }, [documentId]);

  /* ── Load existing markups from server ─────────────────────────────── */

  useEffect(() => {
    if (!projectId || !documentId) return;
    let cancelled = false;
    const loadExisting = async () => {
      try {
        const existing = await fetchMarkups(projectId, { document_id: documentId });
        if (cancelled || existing.length === 0) return;
        const loaded: DrawnAnnotation[] = existing.map((m: Markup) => {
          const savedSpace = (m.geometry?.coord_space as 'pdf' | 'canvas' | undefined);
          return {
            id: m.id,
            tool: (m.geometry?.tool as AnnotationTool) || (m.type as AnnotationTool) || 'rectangle',
            points: (m.geometry?.points as { x: number; y: number }[]) || [{ x: 50, y: 50 }],
            // Backwards compat: pre-v1.3.17 markups were stored in overlay
            // canvas pixels and therefore mis-render at any non-saving zoom.
            // Treat anything without an explicit ``coord_space`` flag as
            // legacy ``canvas`` so they at least appear on-screen.
            coordSpace: savedSpace === 'pdf' ? 'pdf' : 'canvas',
            text: m.text || m.label || undefined,
            color: m.color || '#3B82F6',
            page: m.page || 1,
            stampName: (m.geometry?.stamp_name as string) || (m.type === 'stamp' ? (m.label || undefined) : undefined),
          };
        });
        if (!cancelled) setAnnotations((prev) => [...prev, ...loaded]);
      } catch {
        // non-critical — just won't show existing markups
      }
    };
    loadExisting();
    return () => { cancelled = true; };
  }, [projectId, documentId]);

  /* ── Render page ──────────────────────────────────────────────────── */

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;
    let activeTask: ReturnType<pdfjsLib.PDFPageProxy['render']> | null = null;
    const renderPage = async () => {
      const page = await pdfDoc.getPage(currentPage);
      if (cancelled) return;
      const viewport = page.getViewport({ scale: zoom * 1.5 });
      const canvas = canvasRef.current!;
      const ctx = canvas.getContext('2d')!;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      pageDimensionsRef.current = { width: viewport.width, height: viewport.height };
      viewportRef.current = viewport;

      // Also size the overlay canvas
      if (overlayRef.current) {
        overlayRef.current.width = viewport.width;
        overlayRef.current.height = viewport.height;
      }

      activeTask = page.render({ canvasContext: ctx, viewport });
      try {
        await activeTask.promise;
      } catch (err) {
        // RenderingCancelledException is expected on zoom / page flip —
        // swallow it, but surface anything else to the console.
        if (err && (err as { name?: string }).name !== 'RenderingCancelledException') {
          if (import.meta.env.DEV) console.warn('PDF page render failed', err);
        }
        return;
      }
      if (!cancelled) {
        drawAnnotations();
      }
    };
    renderPage();
    return () => {
      cancelled = true;
      // Cancel the in-flight render — otherwise rapidly flipping pages
      // accumulates orphan RenderTasks each holding a full canvas worth of
      // bitmap data.
      activeTask?.cancel?.();
    };
  }, [pdfDoc, currentPage, zoom]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Draw annotations on overlay ──────────────────────────────────── */

  const drawAnnotations = useCallback(() => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const viewport = viewportRef.current;

    /**
     * Project a stored point into current viewport pixel coordinates.
     *
     * - ``coordSpace === 'pdf'``: stored as PDF user units → map via
     *   ``viewport.convertToViewportPoint``.
     * - ``coordSpace === 'canvas'`` (legacy): stored as overlay pixels at
     *   the saving user's zoom. We have no reliable way to recover the
     *   original scale, so we render them at today's pixel values, which
     *   at least keeps the demo workflow showing existing markups.
     */
    const toPixel = (
      p: { x: number; y: number },
      space: 'pdf' | 'canvas',
    ): { x: number; y: number } => {
      if (space === 'pdf' && viewport) {
        const [px, py] = viewport.convertToViewportPoint(p.x, p.y);
        return { x: px, y: py };
      }
      return p;
    };

    const pageAnnotations = annotations.filter((a) => a.page === currentPage);

    for (const rawAnn of pageAnnotations) {
      // Materialise the annotation with points already mapped into
      // overlay-canvas pixel space so the shape-drawing branches stay
      // unchanged.
      const ann = {
        ...rawAnn,
        points: rawAnn.points.map((p) => toPixel(p, rawAnn.coordSpace)),
      };
      ctx.save();
      ctx.strokeStyle = ann.color;
      ctx.fillStyle = ann.color;
      ctx.lineWidth = 2;

      if (ann.tool === 'rectangle' && ann.points.length >= 2) {
        const [p1, p2] = ann.points;
        const x = Math.min(p1!.x, p2!.x);
        const y = Math.min(p1!.y, p2!.y);
        const w = Math.abs(p2!.x - p1!.x);
        const h = Math.abs(p2!.y - p1!.y);
        ctx.strokeRect(x, y, w, h);
      } else if (ann.tool === 'highlight' && ann.points.length >= 2) {
        const [p1, p2] = ann.points;
        const x = Math.min(p1!.x, p2!.x);
        const y = Math.min(p1!.y, p2!.y);
        const w = Math.abs(p2!.x - p1!.x);
        const h = Math.abs(p2!.y - p1!.y);
        ctx.globalAlpha = 0.3;
        ctx.fillRect(x, y, w, h);
        ctx.globalAlpha = 1;
      } else if (ann.tool === 'arrow' && ann.points.length >= 2) {
        const [p1, p2] = ann.points;
        ctx.beginPath();
        ctx.moveTo(p1!.x, p1!.y);
        ctx.lineTo(p2!.x, p2!.y);
        ctx.stroke();
        // Arrowhead
        const angle = Math.atan2(p2!.y - p1!.y, p2!.x - p1!.x);
        const headLen = 12;
        ctx.beginPath();
        ctx.moveTo(p2!.x, p2!.y);
        ctx.lineTo(
          p2!.x - headLen * Math.cos(angle - Math.PI / 6),
          p2!.y - headLen * Math.sin(angle - Math.PI / 6),
        );
        ctx.lineTo(
          p2!.x - headLen * Math.cos(angle + Math.PI / 6),
          p2!.y - headLen * Math.sin(angle + Math.PI / 6),
        );
        ctx.closePath();
        ctx.fill();
      } else if (ann.tool === 'cloud' && ann.points.length >= 2) {
        const [p1, p2] = ann.points;
        const cx = (p1!.x + p2!.x) / 2;
        const cy = (p1!.y + p2!.y) / 2;
        const rx = Math.abs(p2!.x - p1!.x) / 2;
        const ry = Math.abs(p2!.y - p1!.y) / 2;
        // Draw cloud-like shape with bumpy ellipse
        ctx.beginPath();
        const bumps = 16;
        for (let i = 0; i <= bumps; i++) {
          const t = (i / bumps) * Math.PI * 2;
          const bumpR = 1 + 0.12 * Math.sin(t * 6);
          const x = cx + rx * bumpR * Math.cos(t);
          const y = cy + ry * bumpR * Math.sin(t);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.stroke();
      } else if (ann.tool === 'text' && ann.points.length >= 1 && ann.text) {
        ctx.font = '14px sans-serif';
        ctx.fillText(ann.text, ann.points[0]!.x, ann.points[0]!.y);
      } else if (ann.tool === 'stamp' && ann.points.length >= 1 && ann.stampName) {
        const stampDef = availableStamps.find((s) => s.name === ann.stampName);
        const label = stampDef?.label || ann.stampName.toUpperCase();
        const bgCol = stampDef?.bgColor || '#f0f0f0';
        const textCol = stampDef?.color || ann.color;
        const px = ann.points[0]!.x;
        const py = ann.points[0]!.y;
        ctx.font = 'bold 13px sans-serif';
        const tw = ctx.measureText(label).width;
        const padX = 10;
        const padY = 6;
        const h = 22;
        // Background
        ctx.fillStyle = bgCol;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.roundRect(px - padX, py - h + padY, tw + padX * 2, h + padY, 4);
        ctx.fill();
        ctx.globalAlpha = 1;
        // Border
        ctx.strokeStyle = textCol;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(px - padX, py - h + padY, tw + padX * 2, h + padY, 4);
        ctx.stroke();
        // Text
        ctx.fillStyle = textCol;
        ctx.fillText(label, px, py);
      }

      ctx.restore();
    }

    // Draw current shape being drawn
    if (isDrawing && drawStart && drawEnd && activeTool !== 'select' && activeTool !== 'text') {
      ctx.save();
      ctx.strokeStyle = activeColor;
      ctx.fillStyle = activeColor;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);

      if (activeTool === 'rectangle') {
        const x = Math.min(drawStart.x, drawEnd.x);
        const y = Math.min(drawStart.y, drawEnd.y);
        const w = Math.abs(drawEnd.x - drawStart.x);
        const h = Math.abs(drawEnd.y - drawStart.y);
        ctx.strokeRect(x, y, w, h);
      } else if (activeTool === 'highlight') {
        const x = Math.min(drawStart.x, drawEnd.x);
        const y = Math.min(drawStart.y, drawEnd.y);
        const w = Math.abs(drawEnd.x - drawStart.x);
        const h = Math.abs(drawEnd.y - drawStart.y);
        ctx.globalAlpha = 0.3;
        ctx.fillRect(x, y, w, h);
      } else if (activeTool === 'arrow') {
        ctx.beginPath();
        ctx.moveTo(drawStart.x, drawStart.y);
        ctx.lineTo(drawEnd.x, drawEnd.y);
        ctx.stroke();
      } else if (activeTool === 'cloud') {
        const cx = (drawStart.x + drawEnd.x) / 2;
        const cy = (drawStart.y + drawEnd.y) / 2;
        const rx = Math.abs(drawEnd.x - drawStart.x) / 2;
        const ry = Math.abs(drawEnd.y - drawStart.y) / 2;
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();
      }

      ctx.restore();
    }
  }, [annotations, currentPage, isDrawing, drawStart, drawEnd, activeTool, activeColor]);

  // Redraw overlay whenever annotations or drawing state changes
  useEffect(() => {
    drawAnnotations();
  }, [drawAnnotations]);

  /* ── Mouse handlers ───────────────────────────────────────────────── */

  const getCanvasCoords = useCallback((e: React.MouseEvent): { x: number; y: number } => {
    const canvas = overlayRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }, []);

  /**
   * Convert an overlay canvas pixel point into PDF user units.
   *
   * All annotations are persisted in PDF user units so that a markup saved
   * at zoom 1.0 renders at the correct physical location when reopened at
   * any other zoom. If the viewport is not yet ready (edge case during
   * first paint), we fall back to the canvas coordinates unchanged; the
   * next render pass will use the correct viewport.
   */
  const toPdfPoint = useCallback((p: { x: number; y: number }): { x: number; y: number } => {
    const viewport = viewportRef.current;
    if (!viewport) return p;
    const [x, y] = viewport.convertToPdfPoint(p.x, p.y);
    return { x, y };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (activeTool === 'select') return;
    const coords = getCanvasCoords(e);

    if (activeTool === 'text') {
      setTextPosition(coords);
      setShowTextInput(true);
      setTextInput('');
      return;
    }

    if (activeTool === 'stamp') {
      const stampDef = availableStamps.find((s) => s.name === selectedStamp);
      const newAnnotation: DrawnAnnotation = {
        id: crypto.randomUUID(),
        tool: 'stamp',
        points: [toPdfPoint(coords)],
        coordSpace: 'pdf',
        stampName: selectedStamp,
        text: stampDef?.label || selectedStamp,
        color: stampDef?.color || activeColor,
        page: currentPage,
      };
      setAnnotations((prev) => [...prev, newAnnotation]);
      return;
    }

    setIsDrawing(true);
    setDrawStart(coords);
    setDrawEnd(coords);
  }, [activeTool, getCanvasCoords, selectedStamp, availableStamps, activeColor, currentPage]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDrawing) return;
    setDrawEnd(getCanvasCoords(e));
  }, [isDrawing, getCanvasCoords]);

  const handleMouseUp = useCallback(() => {
    if (!isDrawing || !drawStart || !drawEnd) return;
    setIsDrawing(false);

    // Minimum size check
    const dx = Math.abs(drawEnd.x - drawStart.x);
    const dy = Math.abs(drawEnd.y - drawStart.y);
    if (dx < 5 && dy < 5) {
      setDrawStart(null);
      setDrawEnd(null);
      return;
    }

    const newAnnotation: DrawnAnnotation = {
      id: crypto.randomUUID(),
      tool: activeTool,
      points: [toPdfPoint(drawStart), toPdfPoint(drawEnd)],
      coordSpace: 'pdf',
      color: activeColor,
      page: currentPage,
    };
    setAnnotations((prev) => [...prev, newAnnotation]);
    setDrawStart(null);
    setDrawEnd(null);
  }, [isDrawing, drawStart, drawEnd, activeTool, activeColor, currentPage, toPdfPoint]);

  const handleTextSubmit = useCallback(() => {
    if (!textPosition || !textInput.trim()) {
      setShowTextInput(false);
      return;
    }
    const newAnnotation: DrawnAnnotation = {
      id: crypto.randomUUID(),
      tool: 'text',
      points: [toPdfPoint(textPosition)],
      coordSpace: 'pdf',
      text: textInput.trim(),
      color: activeColor,
      page: currentPage,
    };
    setAnnotations((prev) => [...prev, newAnnotation]);
    setShowTextInput(false);
    setTextInput('');
    setTextPosition(null);
  }, [textPosition, textInput, activeColor, currentPage, toPdfPoint]);

  /* ── Save all annotations as markups ──────────────────────────────── */

  const handleSaveAll = useCallback(async () => {
    const unsaved = annotations.filter((a) => TOOL_TO_MARKUP_TYPE[a.tool]);
    if (unsaved.length === 0) {
      addToast({ type: 'info', title: t('markups.nothing_to_save', { defaultValue: 'No annotations to save' }) });
      return;
    }

    setSaving(true);
    let ok = 0;
    let fail = 0;

    for (const ann of unsaved) {
      const markupType = TOOL_TO_MARKUP_TYPE[ann.tool];
      if (!markupType) continue;

      const payload: CreateMarkupPayload = {
        project_id: projectId,
        type: markupType,
        document_id: documentId,
        page: ann.page,
        color: ann.color,
        geometry: {
          points: ann.points,
          tool: ann.tool,
          // Mark coordinate space so readers can correctly interpret
          // ``points``. Legacy markups (saved pre-v1.3.17) do not carry
          // this field and default to canvas pixels on read.
          coord_space: ann.coordSpace,
          ...(ann.stampName ? { stamp_name: ann.stampName } : {}),
        },
        ...(ann.text ? { text: ann.text } : {}),
        ...(ann.stampName ? { label: ann.stampName } : {}),
      };

      try {
        await createMarkup(payload);
        ok++;
      } catch {
        fail++;
      }
    }

    setSaving(false);

    if (ok > 0) {
      addToast({
        type: 'success',
        title: t('markups.annotations_saved', {
          defaultValue: '{{count}} annotation(s) saved',
          count: ok,
        }),
      });
      onMarkupCreated();
      setAnnotations([]);
    }
    if (fail > 0) {
      addToast({
        type: 'error',
        title: t('markups.save_failed', {
          defaultValue: '{{count}} annotation(s) failed to save',
          count: fail,
        }),
      });
    }
  }, [annotations, projectId, documentId, addToast, t, onMarkupCreated]);

  /* ── Navigation ───────────────────────────────────────────────────── */

  const goPage = useCallback((delta: number) => {
    setCurrentPage((p) => Math.max(1, Math.min(totalPages, p + delta)));
  }, [totalPages]);

  const changeZoom = useCallback((delta: number) => {
    setZoom((z) => {
      const idx = ZOOM_LEVELS.indexOf(z);
      if (idx < 0) return z;
      const newIdx = Math.max(0, Math.min(ZOOM_LEVELS.length - 1, idx + delta));
      return ZOOM_LEVELS[newIdx]!;
    });
  }, []);

  const pageAnnotationCount = annotations.filter((a) => a.page === currentPage).length;

  /* ── Render ───────────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={32} className="text-oe-blue animate-spin" />
        <span className="ml-3 text-sm text-content-secondary">
          {t('markups.loading_pdf', { defaultValue: 'Loading document...' })}
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-sm text-semantic-error mb-3">{error}</p>
        <Button variant="secondary" size="sm" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      </div>
    );
  }

  return (
    <div className="border border-border-light rounded-xl overflow-hidden bg-surface-primary">
      {/* ── Toolbar ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border-light bg-surface-secondary/50 flex-wrap">
        {/* Document name + close */}
        <div className="flex items-center gap-2 mr-2">
          <span className="text-xs font-medium text-content-primary truncate max-w-[180px]">
            {documentName}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
            title={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={14} />
          </button>
        </div>

        {/* Divider */}
        <div className="w-px h-5 bg-border-light mx-1" />

        {/* Annotation tools */}
        {TOOLS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => { setActiveTool(id); setShowTextInput(false); }}
            title={t(`markups.tool_${id}`, { defaultValue: label })}
            className={`p-1.5 rounded-md transition-colors ${
              activeTool === id
                ? 'bg-oe-blue text-white'
                : 'text-content-secondary hover:bg-surface-secondary'
            }`}
          >
            <Icon size={14} />
          </button>
        ))}

        {/* Divider */}
        <div className="w-px h-5 bg-border-light mx-1" />

        {/* Color picker (hidden when stamp tool active) */}
        {activeTool !== 'stamp' && (
          <div className="flex items-center gap-1">
            {PRESET_COLORS.map((c) => (
              <button
                key={c}
                onClick={() => setActiveColor(c)}
                className={`w-5 h-5 rounded-full border-2 transition-all ${
                  activeColor === c ? 'border-content-primary scale-110' : 'border-transparent'
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
        )}

        {/* Stamp type picker (shown when stamp tool active) */}
        {activeTool === 'stamp' && (
          <div className="flex items-center gap-1 relative">
            <div className="flex items-center gap-1">
              {availableStamps.map((s) => (
                <button
                  key={s.name}
                  onClick={() => setSelectedStamp(s.name)}
                  className={`px-2 py-0.5 rounded text-2xs font-bold border transition-all ${
                    selectedStamp === s.name
                      ? 'ring-1 ring-offset-1 ring-oe-blue/40 scale-105'
                      : 'opacity-70 hover:opacity-100'
                  }`}
                  style={{
                    backgroundColor: s.bgColor,
                    color: s.color,
                    borderColor: s.color,
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Divider */}
        <div className="w-px h-5 bg-border-light mx-1" />

        {/* Zoom controls */}
        <button
          onClick={() => changeZoom(-1)}
          disabled={zoom <= ZOOM_LEVELS[0]!}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          <ZoomOut size={14} />
        </button>
        <span className="text-2xs text-content-tertiary tabular-nums w-10 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => changeZoom(1)}
          disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]!}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          <ZoomIn size={14} />
        </button>

        {/* Page navigation */}
        <div className="w-px h-5 bg-border-light mx-1" />
        <button
          onClick={() => goPage(-1)}
          disabled={currentPage <= 1}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="text-2xs text-content-secondary tabular-nums">
          {currentPage} / {totalPages}
        </span>
        <button
          onClick={() => goPage(1)}
          disabled={currentPage >= totalPages}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        >
          <ChevronRight size={14} />
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Annotation count + save + clear */}
        {annotations.length > 0 && (
          <>
            <span className="text-2xs text-content-tertiary">
              {t('markups.annotations_count', {
                defaultValue: '{{count}} annotation(s)',
                count: annotations.length,
              })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAnnotations([])}
              className="text-semantic-error/70 hover:text-semantic-error"
            >
              <Trash2 size={13} className="mr-1" />
              {t('markups.clear_all', { defaultValue: 'Clear' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSaveAll}
              loading={saving}
            >
              <Save size={13} className="mr-1" />
              {t('markups.save_annotations', { defaultValue: 'Save All' })}
            </Button>
          </>
        )}
      </div>

      {/* ── Canvas Area ─────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        className="relative overflow-auto bg-neutral-100 dark:bg-neutral-900"
        style={{ maxHeight: '65vh' }}
      >
        <div className="relative inline-block">
          {/* PDF canvas */}
          <canvas ref={canvasRef} className="block" />

          {/* Overlay canvas for annotations */}
          <canvas
            ref={overlayRef}
            className="absolute inset-0 block"
            style={{ cursor: activeTool === 'select' ? 'default' : activeTool === 'text' ? 'text' : 'crosshair' }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          />

          {/* Text input overlay */}
          {showTextInput && textPosition && (
            <div
              className="absolute z-10"
              style={{
                left: textPosition.x / (pageDimensionsRef.current.width / (overlayRef.current?.getBoundingClientRect().width || 1)),
                top: textPosition.y / (pageDimensionsRef.current.height / (overlayRef.current?.getBoundingClientRect().height || 1)),
              }}
            >
              <div className="flex items-center gap-1 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-border-light p-1">
                <input
                  autoFocus
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleTextSubmit(); if (e.key === 'Escape') setShowTextInput(false); }}
                  placeholder={t('markups.type_text', { defaultValue: 'Type text...' })}
                  className="w-40 px-2 py-1 text-xs border-none bg-transparent outline-none text-content-primary"
                />
                <button
                  onClick={handleTextSubmit}
                  className="p-1 rounded text-oe-blue hover:bg-surface-secondary"
                >
                  <Save size={12} />
                </button>
                <button
                  onClick={() => setShowTextInput(false)}
                  className="p-1 rounded text-content-tertiary hover:bg-surface-secondary"
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom status bar ───────────────────────────────────────── */}
      {pageAnnotationCount > 0 && (
        <div className="flex items-center justify-between px-3 py-1.5 border-t border-border-light bg-surface-secondary/30 text-2xs text-content-tertiary">
          <span>
            {t('markups.page_annotations', {
              defaultValue: '{{count}} annotation(s) on this page',
              count: pageAnnotationCount,
            })}
          </span>
          <span>{t('markups.draw_hint', { defaultValue: 'Click and drag to draw. Select a tool from the toolbar.' })}</span>
        </div>
      )}
    </div>
  );
}

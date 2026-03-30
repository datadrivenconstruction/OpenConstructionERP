import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import * as pdfjsLib from 'pdfjs-dist';
import {
  Ruler,
  Upload,
  ZoomIn,
  ZoomOut,
  Maximize,
  ChevronLeft,
  ChevronRight,
  MousePointer2,
  Minus,
  Pentagon,
  Hash,
  Trash2,
  Settings2,
  Info,
  Undo2,
  Pencil,
  Save,
  HardDriveDownload,
} from 'lucide-react';
import { useToastStore } from '../../stores/useToastStore';
import { boqApi, type CreatePositionData } from '../../features/boq/api';
import { apiGet } from '../../shared/lib/api';
import { useMeasurementPersistence } from './useMeasurementPersistence';
import {
  type ScaleConfig,
  COMMON_SCALES,
  pixelDistance,
  toRealDistance,
  polygonAreaPixels,
  toRealArea,
  polygonPerimeterPixels,
  formatMeasurement,
  deriveScale,
} from './data/scale-helpers';

// Configure PDF.js worker — bundled locally (no CDN dependency)
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

/* ── Types ─────────────────────────────────────────────────────────── */

type MeasureTool = 'select' | 'distance' | 'area' | 'count';

interface Point {
  x: number;
  y: number;
}

interface Measurement {
  id: string;
  type: 'distance' | 'area' | 'count';
  points: Point[];
  value: number;
  unit: string;
  label: string;
  annotation: string; // User-provided text label (e.g. "Living room wall")
  page: number;
}

/** Describes a reversible measurement operation for the undo stack. */
type UndoOperation =
  | { kind: 'add_point'; tool: MeasureTool; point: Point }
  | { kind: 'complete_measurement'; measurement: Measurement; previousActivePoints: Point[] }
  | { kind: 'add_count_point'; measurementId: string; point: Point; wasNew: boolean; previousMeasurement: Measurement | null }
  | { kind: 'delete_measurement'; measurement: Measurement }
  | { kind: 'change_annotation'; measurementId: string; previousAnnotation: string };

/* ── Component ─────────────────────────────────────────────────────── */

export default function TakeoffViewerModule() {
  const { t } = useTranslation();

  // PDF state
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [zoom, setZoom] = useState(1.0);
  const [isLoading, setIsLoading] = useState(false);

  // Measurement state
  const [activeTool, setActiveTool] = useState<MeasureTool>('select');
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [activePoints, setActivePoints] = useState<Point[]>([]);
  const [countLabel, setCountLabel] = useState(t('takeoff_viewer.default_count_label', { defaultValue: 'Element' }));

  // Scale
  const [scale, setScale] = useState<ScaleConfig>({ pixelsPerUnit: 100, unitLabel: 'm' });
  const [showScaleDialog, setShowScaleDialog] = useState(false);
  const [scaleRefPixels, setScaleRefPixels] = useState(0);
  const [scaleRefReal, setScaleRefReal] = useState(1);
  const [settingScale, setSettingScale] = useState(false);
  const [scalePoints, setScalePoints] = useState<Point[]>([]);

  // Canvas refs
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Touch state for pinch-to-zoom
  const touchStateRef = useRef<{ initialDistance: number; initialZoom: number } | null>(null);

  // Annotation auto-numbering counters (type -> next index)
  const annotationCounterRef = useRef<Record<string, number>>({ distance: 0, area: 0, count: 0 });

  // Inline editing state for annotations in the measurement list
  const [editingAnnotationId, setEditingAnnotationId] = useState<string | null>(null);
  const [editingAnnotationValue, setEditingAnnotationValue] = useState('');

  // Undo stack
  const undoStackRef = useRef<UndoOperation[]>([]);
  const [undoCount, setUndoCount] = useState(0);
  const addToast = useToastStore((s) => s.addToast);

  // Export to BOQ state
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportProjects, setExportProjects] = useState<{ id: string; name: string }[]>([]);
  const [exportBoqs, setExportBoqs] = useState<{ id: string; name: string }[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [isExporting, setIsExporting] = useState(false);

  // Document persistence
  const [fileName, setFileName] = useState<string | null>(null);
  const { hasPersistedData, saveNow, clearPersisted } = useMeasurementPersistence({
    fileName,
    measurements,
    setMeasurements: (ms) => setMeasurements(ms),
    scale,
    setScale: (s) => setScale(s),
  });

  /* ── Load PDF ────────────────────────────────────────────────────── */

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsLoading(true);
    try {
      const arrayBuffer = await file.arrayBuffer();
      const doc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
      setPdfDoc(doc);
      setTotalPages(doc.numPages);
      setCurrentPage(1);
      setFileName(file.name); // Triggers persistence hook to load saved measurements
      setActivePoints([]);
      undoStackRef.current = [];
      setUndoCount(0);
      annotationCounterRef.current = { distance: 0, area: 0, count: 0 };
    } catch (err) {
      console.error('Failed to load PDF:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /* ── Render page to canvas ───────────────────────────────────────── */

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;

    (async () => {
      const page = await pdfDoc.getPage(currentPage);
      if (cancelled) return;

      const viewport = page.getViewport({ scale: zoom * window.devicePixelRatio });
      const canvas = canvasRef.current!;
      const ctx = canvas.getContext('2d')!;

      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / window.devicePixelRatio}px`;
      canvas.style.height = `${viewport.height / window.devicePixelRatio}px`;

      // Size overlay to match
      if (overlayRef.current) {
        overlayRef.current.width = viewport.width;
        overlayRef.current.height = viewport.height;
        overlayRef.current.style.width = canvas.style.width;
        overlayRef.current.style.height = canvas.style.height;
      }

      await page.render({ canvasContext: ctx, viewport }).promise;
    })();

    return () => { cancelled = true; };
  }, [pdfDoc, currentPage, zoom]);

  /* ── Draw overlay (measurements + active drawing) ────────────────── */

  useEffect(() => {
    if (!overlayRef.current) return;
    const ctx = overlayRef.current.getContext('2d')!;
    const dpr = window.devicePixelRatio;
    ctx.clearRect(0, 0, overlayRef.current.width, overlayRef.current.height);

    ctx.lineWidth = 2 * dpr;
    ctx.font = `${12 * dpr}px sans-serif`;

    /** Draw an annotation label with a semi-transparent background at (lx, ly). */
    const drawAnnotationLabel = (text: string, lx: number, ly: number, color: string) => {
      const fontSize = 11 * dpr;
      ctx.font = `bold ${fontSize}px sans-serif`;
      const metrics = ctx.measureText(text);
      const padX = 4 * dpr;
      const padY = 2 * dpr;
      const boxW = metrics.width + padX * 2;
      const boxH = fontSize + padY * 2;
      const bx = lx - padX;
      const by = ly - fontSize - padY;
      // Semi-transparent background
      ctx.globalAlpha = 0.75;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.globalAlpha = 1;
      // Border
      ctx.strokeStyle = color;
      ctx.lineWidth = 1 * dpr;
      ctx.strokeRect(bx, by, boxW, boxH);
      // Text
      ctx.fillStyle = color;
      ctx.fillText(text, lx, ly - padY);
      // Restore line width
      ctx.lineWidth = 2 * dpr;
    };

    // Draw completed measurements on current page
    for (const m of measurements.filter((m) => m.page === currentPage)) {
      const color = m.type === 'distance' ? '#3b82f6' : m.type === 'area' ? '#10b981' : '#f59e0b';
      ctx.strokeStyle = color;
      ctx.fillStyle = color;

      if (m.type === 'distance' && m.points.length === 2) {
        const p0 = m.points[0]!;
        const p1 = m.points[1]!;
        ctx.beginPath();
        ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
        ctx.lineTo(p1.x * dpr * zoom, p1.y * dpr * zoom);
        ctx.stroke();
        // Measurement value label
        const mx = ((p0.x + p1.x) / 2) * dpr * zoom;
        const my = ((p0.y + p1.y) / 2) * dpr * zoom - 8 * dpr;
        ctx.font = `${12 * dpr}px sans-serif`;
        ctx.fillText(m.label, mx, my);
        // Annotation near midpoint (offset above the value label)
        drawAnnotationLabel(m.annotation, mx, my - 14 * dpr, color);
      }

      if (m.type === 'area' && m.points.length >= 3) {
        const firstPt = m.points[0]!;
        ctx.beginPath();
        ctx.moveTo(firstPt.x * dpr * zoom, firstPt.y * dpr * zoom);
        for (let i = 1; i < m.points.length; i++) {
          const pt = m.points[i]!;
          ctx.lineTo(pt.x * dpr * zoom, pt.y * dpr * zoom);
        }
        ctx.closePath();
        ctx.globalAlpha = 0.15;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.stroke();
        // Measurement value label at centroid
        const cx = m.points.reduce((s, p) => s + p.x, 0) / m.points.length * dpr * zoom;
        const cy = m.points.reduce((s, p) => s + p.y, 0) / m.points.length * dpr * zoom;
        ctx.font = `${12 * dpr}px sans-serif`;
        ctx.fillText(m.label, cx, cy);
        // Annotation above centroid
        drawAnnotationLabel(m.annotation, cx, cy - 14 * dpr, color);
      }

      if (m.type === 'count') {
        for (const p of m.points) {
          ctx.beginPath();
          ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 8 * dpr, 0, Math.PI * 2);
          ctx.globalAlpha = 0.3;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.stroke();
        }
        // Annotation near first point
        if (m.points.length > 0) {
          const fp = m.points[0]!;
          drawAnnotationLabel(
            `${m.annotation} (${m.points.length})`,
            fp.x * dpr * zoom + 12 * dpr,
            fp.y * dpr * zoom - 4 * dpr,
            color,
          );
        }
      }
    }

    // Draw active points (in-progress measurement)
    if (activePoints.length > 0) {
      ctx.strokeStyle = '#ef4444';
      ctx.fillStyle = '#ef4444';
      for (const p of activePoints) {
        ctx.beginPath();
        ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 4 * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
      if (activePoints.length >= 2 && activeTool === 'area') {
        const ap0 = activePoints[0]!;
        ctx.beginPath();
        ctx.moveTo(ap0.x * dpr * zoom, ap0.y * dpr * zoom);
        for (let i = 1; i < activePoints.length; i++) {
          const apt = activePoints[i]!;
          ctx.lineTo(apt.x * dpr * zoom, apt.y * dpr * zoom);
        }
        ctx.stroke();
      }
    }

    // Scale reference line
    if (settingScale && scalePoints.length >= 1) {
      ctx.strokeStyle = '#a855f7';
      ctx.fillStyle = '#a855f7';
      for (const p of scalePoints) {
        ctx.beginPath();
        ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 5 * dpr, 0, Math.PI * 2);
        ctx.fill();
      }
      if (scalePoints.length === 2) {
        const sp0 = scalePoints[0]!;
        const sp1 = scalePoints[1]!;
        ctx.beginPath();
        ctx.moveTo(sp0.x * dpr * zoom, sp0.y * dpr * zoom);
        ctx.lineTo(sp1.x * dpr * zoom, sp1.y * dpr * zoom);
        ctx.stroke();
      }
    }
  }, [measurements, activePoints, currentPage, zoom, settingScale, scalePoints, activeTool]);

  /* ── Canvas click handler ────────────────────────────────────────── */

  const pushUndo = useCallback((op: UndoOperation) => {
    undoStackRef.current.push(op);
    setUndoCount(undoStackRef.current.length);
  }, []);

  /** Generate a default annotation for a new measurement (e.g. "Distance 1", "Area 2"). */
  const nextAnnotation = useCallback(
    (type: 'distance' | 'area' | 'count') => {
      annotationCounterRef.current[type] = (annotationCounterRef.current[type] || 0) + 1;
      const n = annotationCounterRef.current[type];
      if (type === 'distance') return t('takeoff.distance_n', { defaultValue: 'Distance {{n}}', n });
      if (type === 'area') return t('takeoff.area_n', { defaultValue: 'Area {{n}}', n });
      return t('takeoff.count_n', { defaultValue: 'Count {{n}}', n });
    },
    [t],
  );

  /** Update the annotation of a measurement with undo support. */
  const updateAnnotation = useCallback(
    (id: string, newAnnotation: string) => {
      setMeasurements((prev) =>
        prev.map((m) => {
          if (m.id !== id) return m;
          pushUndo({ kind: 'change_annotation', measurementId: id, previousAnnotation: m.annotation });
          return { ...m, annotation: newAnnotation };
        }),
      );
    },
    [pushUndo],
  );

  /** Start inline editing of an annotation. */
  const startEditAnnotation = useCallback((m: Measurement) => {
    setEditingAnnotationId(m.id);
    setEditingAnnotationValue(m.annotation);
  }, []);

  /** Commit the inline annotation edit. */
  const commitEditAnnotation = useCallback(() => {
    if (editingAnnotationId) {
      const trimmed = editingAnnotationValue.trim();
      // Only commit if actually changed
      const existing = measurements.find((m) => m.id === editingAnnotationId);
      if (existing && trimmed && trimmed !== existing.annotation) {
        updateAnnotation(editingAnnotationId, trimmed);
      }
    }
    setEditingAnnotationId(null);
    setEditingAnnotationValue('');
  }, [editingAnnotationId, editingAnnotationValue, measurements, updateAnnotation]);

  /* ── Touch handlers: pinch-to-zoom + tap for measurements ─────────── */

  const handleTouchStart = useCallback(
    (e: React.TouchEvent<HTMLCanvasElement>) => {
      if (e.touches.length === 2) {
        // Pinch start
        const t0 = e.touches[0]!;
        const t1 = e.touches[1]!;
        const dx = t0.clientX - t1.clientX;
        const dy = t0.clientY - t1.clientY;
        touchStateRef.current = {
          initialDistance: Math.sqrt(dx * dx + dy * dy),
          initialZoom: zoom,
        };
        e.preventDefault();
      }
    },
    [zoom],
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent<HTMLCanvasElement>) => {
      if (e.touches.length === 2 && touchStateRef.current) {
        // Pinch zoom
        const tm0 = e.touches[0]!;
        const tm1 = e.touches[1]!;
        const dx = tm0.clientX - tm1.clientX;
        const dy = tm0.clientY - tm1.clientY;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const scaleFactor = distance / touchStateRef.current.initialDistance;
        const newZoom = Math.max(0.25, Math.min(4.0, touchStateRef.current.initialZoom * scaleFactor));
        setZoom(Math.round(newZoom * 100) / 100);
        e.preventDefault();
      }
    },
    [],
  );

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent<HTMLCanvasElement>) => {
      if (touchStateRef.current) {
        touchStateRef.current = null;
        return; // Was a pinch gesture, don't trigger tap
      }

      // Single-finger tap → treat as click for measurement placement
      if (e.changedTouches.length === 1 && activeTool !== 'select') {
        const touch = e.changedTouches[0]!;
        const rect = overlayRef.current?.getBoundingClientRect();
        if (!rect) return;
        // Synthesize a click event for measurement placement
        const syntheticEvent = {
          clientX: touch.clientX,
          clientY: touch.clientY,
        } as React.MouseEvent<HTMLCanvasElement>;
        // Reuse handleCanvasClick logic
        handleCanvasClickRef.current?.(syntheticEvent);
      }
    },
    [activeTool],
  );

  // Ref to allow touch handler to call the latest click handler without circular deps
  const handleCanvasClickRef = useRef<((e: React.MouseEvent<HTMLCanvasElement>) => void) | null>(null);

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = overlayRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = (e.clientX - rect.left) / zoom;
      const y = (e.clientY - rect.top) / zoom;
      const point: Point = { x, y };

      // Setting scale mode
      if (settingScale) {
        const newPoints = [...scalePoints, point];
        setScalePoints(newPoints);
        if (newPoints.length === 2) {
          const np0 = newPoints[0]!;
          const np1 = newPoints[1]!;
          const dist = pixelDistance(np0.x, np0.y, np1.x, np1.y);
          setScaleRefPixels(dist);
          setSettingScale(false);
          setShowScaleDialog(true);
        }
        return;
      }

      if (activeTool === 'select') return;

      if (activeTool === 'distance') {
        const newPoints = [...activePoints, point];
        setActivePoints(newPoints);
        if (newPoints.length === 2) {
          const dp0 = newPoints[0]!;
          const dp1 = newPoints[1]!;
          const dist = pixelDistance(dp0.x, dp0.y, dp1.x, dp1.y);
          const realDist = toRealDistance(dist, scale);
          const newMeasurement: Measurement = {
            id: `m_${Date.now()}`,
            type: 'distance',
            points: newPoints,
            value: realDist,
            unit: scale.unitLabel,
            label: formatMeasurement(realDist, scale.unitLabel),
            annotation: nextAnnotation('distance'),
            page: currentPage,
          };
          pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
          setMeasurements((prev) => [...prev, newMeasurement]);
          setActivePoints([]);
        } else {
          pushUndo({ kind: 'add_point', tool: 'distance', point });
        }
        return;
      }

      if (activeTool === 'area') {
        pushUndo({ kind: 'add_point', tool: 'area', point });
        setActivePoints((prev) => [...prev, point]);
        return;
      }

      if (activeTool === 'count') {
        // Group by label — find existing or create new
        setMeasurements((prev) => {
          const existing = prev.find((m) => m.type === 'count' && m.label === countLabel && m.page === currentPage);
          if (existing) {
            pushUndo({ kind: 'add_count_point', measurementId: existing.id, point, wasNew: false, previousMeasurement: { ...existing, points: [...existing.points] } });
            return prev.map((m) =>
              m.id === existing.id
                ? { ...m, points: [...m.points, point], value: m.points.length + 1 }
                : m,
            );
          }
          const newId = `m_${Date.now()}`;
          const newMeasurement: Measurement = {
            id: newId,
            type: 'count',
            points: [point],
            value: 1,
            unit: 'pcs',
            label: countLabel,
            annotation: nextAnnotation('count'),
            page: currentPage,
          };
          pushUndo({ kind: 'add_count_point', measurementId: newId, point, wasNew: true, previousMeasurement: null });
          return [...prev, newMeasurement];
        });
      }
    },
    [activeTool, activePoints, scale, currentPage, countLabel, settingScale, scalePoints, zoom, pushUndo, nextAnnotation],
  );

  // Keep the ref in sync so touch handler can call it
  handleCanvasClickRef.current = handleCanvasClick;

  /** Double-click to close an area polygon */
  const handleCanvasDblClick = useCallback(() => {
    if (activeTool !== 'area' || activePoints.length < 3) return;
    const pixArea = polygonAreaPixels(activePoints);
    const realArea = toRealArea(pixArea, scale);
    const perimPx = polygonPerimeterPixels(activePoints);
    const realPerim = toRealDistance(perimPx, scale);
    const newMeasurement: Measurement = {
      id: `m_${Date.now()}`,
      type: 'area',
      points: [...activePoints],
      value: realArea,
      unit: `${scale.unitLabel}²`,
      label: `${formatMeasurement(realArea, scale.unitLabel + '²')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})`,
      annotation: nextAnnotation('area'),
      page: currentPage,
    };
    pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
    setMeasurements((prev) => [...prev, newMeasurement]);
    setActivePoints([]);
  }, [activeTool, activePoints, scale, currentPage, pushUndo, nextAnnotation]);

  /* ── Scale dialog confirm ────────────────────────────────────────── */

  const handleScaleConfirm = useCallback(() => {
    if (scaleRefPixels > 0 && scaleRefReal > 0) {
      setScale(deriveScale(scaleRefPixels, scaleRefReal));
    }
    setShowScaleDialog(false);
    setScalePoints([]);
  }, [scaleRefPixels, scaleRefReal]);

  /* ── Recalculate measurements when scale changes ───────────────── */

  const scaleRef = useRef(scale);
  useEffect(() => {
    const prev = scaleRef.current;
    scaleRef.current = scale;
    // Skip if scale hasn't actually changed (same pixelsPerUnit)
    if (prev.pixelsPerUnit === scale.pixelsPerUnit) return;
    setMeasurements((ms) =>
      ms.map((m) => {
        if (m.type === 'count') return m; // counts are scale-independent
        if (m.type === 'distance' && m.points.length === 2) {
          const dist = pixelDistance(m.points[0]!.x, m.points[0]!.y, m.points[1]!.x, m.points[1]!.y);
          const realDist = toRealDistance(dist, scale);
          return { ...m, value: realDist, unit: scale.unitLabel, label: formatMeasurement(realDist, scale.unitLabel) };
        }
        if (m.type === 'area' && m.points.length >= 3) {
          const pixArea = polygonAreaPixels(m.points);
          const realArea = toRealArea(pixArea, scale);
          const perimPx = polygonPerimeterPixels(m.points);
          const realPerim = toRealDistance(perimPx, scale);
          return { ...m, value: realArea, unit: `${scale.unitLabel}²`, label: `${formatMeasurement(realArea, scale.unitLabel + '²')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})` };
        }
        return m;
      }),
    );
  }, [scale]);

  /* ── Zoom controls ───────────────────────────────────────────────── */

  const zoomIn = useCallback(() => setZoom((z) => Math.min(z * 1.25, 4)), []);
  const zoomOut = useCallback(() => setZoom((z) => Math.max(z / 1.25, 0.25)), []);
  const zoomFit = useCallback(() => setZoom(1), []);

  /* ── Page navigation ─────────────────────────────────────────────── */

  const prevPage = useCallback(() => setCurrentPage((p) => Math.max(p - 1, 1)), []);
  const nextPage = useCallback(() => setCurrentPage((p) => Math.min(p + 1, totalPages)), []);

  /* ── Measurement summary ─────────────────────────────────────────── */

  const pageMeasurements = useMemo(
    () => measurements.filter((m) => m.page === currentPage),
    [measurements, currentPage],
  );

  const deleteMeasurement = useCallback((id: string) => {
    setMeasurements((prev) => {
      const target = prev.find((m) => m.id === id);
      if (target) {
        pushUndo({ kind: 'delete_measurement', measurement: { ...target, points: [...target.points] } });
      }
      return prev.filter((m) => m.id !== id);
    });
  }, [pushUndo]);

  /* ── Export measurements to BOQ ────────────────────────────────── */

  const openExportDialog = useCallback(async () => {
    setShowExportDialog(true);
    try {
      const projects = await apiGet<{ id: string; name: string }[]>('/v1/projects/');
      setExportProjects(projects);
    } catch {
      setExportProjects([]);
    }
  }, []);

  const handleProjectChange = useCallback(async (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedBoqId('');
    if (!projectId) { setExportBoqs([]); return; }
    try {
      const boqs = await apiGet<{ id: string; name: string }[]>(`/v1/boq/boqs/?project_id=${projectId}`);
      setExportBoqs(boqs);
    } catch {
      setExportBoqs([]);
    }
  }, []);

  const handleExportToBOQ = useCallback(async () => {
    if (!selectedBoqId || measurements.length === 0) return;
    setIsExporting(true);
    try {
      let ordinalCounter = 1;
      for (const m of measurements) {
        const unitMap: Record<string, string> = { m: 'm', 'm²': 'm2', pcs: 'pcs' };
        const posData: CreatePositionData = {
          boq_id: selectedBoqId,
          ordinal: `TK.${String(ordinalCounter++).padStart(3, '0')}`,
          description: m.annotation || `${m.type}: ${m.label}`,
          unit: unitMap[m.unit] ?? m.unit,
          quantity: Math.round(m.value * 100) / 100,
          unit_rate: 0,
        };
        await boqApi.addPosition(posData);
      }
      addToast({ type: 'success', title: t('takeoff.added_to_boq_success', { defaultValue: 'Measurements exported to BOQ' }) });
      setShowExportDialog(false);
    } catch {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Export failed' }) });
    } finally {
      setIsExporting(false);
    }
  }, [selectedBoqId, measurements, addToast, t]);

  const clearAll = useCallback(() => {
    setMeasurements([]);
    setActivePoints([]);
    undoStackRef.current = [];
    setUndoCount(0);
    annotationCounterRef.current = { distance: 0, area: 0, count: 0 };
    setEditingAnnotationId(null);
    setEditingAnnotationValue('');
    clearPersisted();
  }, [clearPersisted]);

  /* ── Undo ────────────────────────────────────────────────────────── */

  const handleUndo = useCallback(() => {
    const stack = undoStackRef.current;
    if (stack.length === 0) return;
    const op = stack.pop()!;
    setUndoCount(stack.length);

    switch (op.kind) {
      case 'add_point':
        // Remove the last point from the in-progress measurement
        setActivePoints((prev) => prev.slice(0, -1));
        break;

      case 'complete_measurement':
        // Remove the completed measurement and restore active points
        setMeasurements((prev) => prev.filter((m) => m.id !== op.measurement.id));
        setActivePoints(op.previousActivePoints);
        break;

      case 'add_count_point':
        if (op.wasNew) {
          // The count measurement was freshly created — remove it entirely
          setMeasurements((prev) => prev.filter((m) => m.id !== op.measurementId));
        } else {
          // Restore the count measurement to its state before the last point was added
          setMeasurements((prev) =>
            prev.map((m) =>
              m.id === op.measurementId && op.previousMeasurement
                ? { ...op.previousMeasurement }
                : m,
            ),
          );
        }
        break;

      case 'delete_measurement':
        // Restore the deleted measurement
        setMeasurements((prev) => [...prev, op.measurement]);
        break;

      case 'change_annotation':
        // Revert annotation to previous value
        setMeasurements((prev) =>
          prev.map((m) =>
            m.id === op.measurementId ? { ...m, annotation: op.previousAnnotation } : m,
          ),
        );
        break;
    }

    addToast({ type: 'info', title: t('takeoff.undo', { defaultValue: 'Undo' }), message: t('takeoff.measurement_undone', { defaultValue: 'Measurement undone' }) });
  }, [addToast, t]);

  /** Ctrl+Z / Cmd+Z keyboard shortcut */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleUndo]);

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100 dark:bg-blue-900/30">
          <Ruler className="h-5 w-5 text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('takeoff_viewer.title', { defaultValue: 'PDF Takeoff Viewer' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('takeoff_viewer.subtitle', { defaultValue: 'View drawings and take measurements' })}
          </p>
        </div>
      </div>

      {/* Upload area (when no PDF loaded) */}
      {!pdfDoc && (
        <label className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border p-12 cursor-pointer hover:border-oe-blue hover:bg-oe-blue-subtle/10 transition-all">
          <Upload className="h-10 w-10 text-content-tertiary mb-3" />
          <p className="text-sm font-medium text-content-primary">
            {t('takeoff_viewer.upload', { defaultValue: 'Drop a PDF here or click to upload' })}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {t('takeoff_viewer.upload_hint', { defaultValue: 'Supports architectural drawings, floor plans, sections' })}
          </p>
          <input type="file" accept="application/pdf" onChange={handleFileUpload} className="hidden" />
        </label>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      )}

      {/* Viewer + Sidebar */}
      {pdfDoc && (
        <div className="flex gap-4">
          {/* Left: PDF + Toolbar */}
          <div className="flex-1 space-y-2">
            {/* Toolbar */}
            <div className="flex items-center gap-1 rounded-lg border border-border bg-surface-primary p-1.5 flex-wrap">
              {/* Page nav */}
              <button onClick={prevPage} disabled={currentPage <= 1} className="p-1.5 rounded hover:bg-surface-secondary disabled:opacity-30 transition-colors" aria-label={t('takeoff_viewer.prev_page', { defaultValue: 'Previous page' })}>
                <ChevronLeft size={16} />
              </button>
              <span className="text-xs text-content-secondary tabular-nums px-1">
                {currentPage} / {totalPages}
              </span>
              <button onClick={nextPage} disabled={currentPage >= totalPages} className="p-1.5 rounded hover:bg-surface-secondary disabled:opacity-30 transition-colors" aria-label={t('takeoff_viewer.next_page', { defaultValue: 'Next page' })}>
                <ChevronRight size={16} />
              </button>

              <span className="w-px h-5 bg-border mx-1" />

              {/* Zoom */}
              <button onClick={zoomOut} className="p-1.5 rounded hover:bg-surface-secondary transition-colors" title={t('takeoff_viewer.zoom_out', { defaultValue: 'Zoom out' })} aria-label={t('takeoff_viewer.zoom_out', { defaultValue: 'Zoom out' })}>
                <ZoomOut size={16} />
              </button>
              <span className="text-xs text-content-tertiary tabular-nums w-10 text-center">{(zoom * 100).toFixed(0)}%</span>
              <button onClick={zoomIn} className="p-1.5 rounded hover:bg-surface-secondary transition-colors" title={t('takeoff_viewer.zoom_in', { defaultValue: 'Zoom in' })} aria-label={t('takeoff_viewer.zoom_in', { defaultValue: 'Zoom in' })}>
                <ZoomIn size={16} />
              </button>
              <button onClick={zoomFit} className="p-1.5 rounded hover:bg-surface-secondary transition-colors" title={t('takeoff_viewer.zoom_fit', { defaultValue: 'Fit' })} aria-label={t('takeoff_viewer.zoom_fit', { defaultValue: 'Fit' })}>
                <Maximize size={16} />
              </button>

              <span className="w-px h-5 bg-border mx-1" />

              {/* Measure tools */}
              {([
                { tool: 'select' as MeasureTool, icon: MousePointer2, label: t('takeoff_viewer.tool_select', { defaultValue: 'Select' }) },
                { tool: 'distance' as MeasureTool, icon: Minus, label: t('takeoff_viewer.tool_distance', { defaultValue: 'Distance' }) },
                { tool: 'area' as MeasureTool, icon: Pentagon, label: t('takeoff_viewer.tool_area', { defaultValue: 'Area' }) },
                { tool: 'count' as MeasureTool, icon: Hash, label: t('takeoff_viewer.tool_count', { defaultValue: 'Count' }) },
              ] as const).map(({ tool, icon: Icon, label }) => (
                <button
                  key={tool}
                  onClick={() => { setActiveTool(tool); setActivePoints([]); }}
                  className={`flex items-center gap-1 px-2 py-1.5 rounded text-xs transition-colors ${
                    activeTool === tool
                      ? 'bg-oe-blue text-white'
                      : 'hover:bg-surface-secondary text-content-secondary'
                  }`}
                  title={label}
                  aria-label={label}
                  aria-pressed={activeTool === tool}
                >
                  <Icon size={14} />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}

              <span className="w-px h-5 bg-border mx-1" />

              {/* Scale */}
              <button
                onClick={() => { setSettingScale(true); setScalePoints([]); }}
                className={`flex items-center gap-1 px-2 py-1.5 rounded text-xs transition-colors ${
                  settingScale ? 'bg-purple-500 text-white' : 'hover:bg-surface-secondary text-content-secondary'
                }`}
                title={t('takeoff_viewer.set_scale', { defaultValue: 'Set scale' })}
                aria-label={t('takeoff_viewer.set_scale', { defaultValue: 'Set scale' })}
              >
                <Settings2 size={14} />
                <span className="hidden sm:inline">{t('takeoff_viewer.scale', { defaultValue: 'Scale' })}</span>
              </button>

              {/* Undo */}
              <button
                onClick={handleUndo}
                disabled={undoCount === 0}
                className="flex items-center gap-1 px-2 py-1.5 rounded text-xs transition-colors hover:bg-surface-secondary text-content-secondary disabled:opacity-30 disabled:pointer-events-none ml-auto"
                title={t('takeoff.undo', { defaultValue: 'Undo' }) + ' (Ctrl+Z)'}
              >
                <Undo2 size={14} />
                <span className="hidden sm:inline">{t('takeoff.undo', { defaultValue: 'Undo' })}</span>
              </button>

              {/* Clear */}
              <button onClick={clearAll} className="p-1.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors" title={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })} aria-label={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })}>
                <Trash2 size={14} />
              </button>

              {/* New file */}
              <label className="p-1.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors cursor-pointer" title={t('takeoff_viewer.load_new_pdf', { defaultValue: 'Load new PDF' })} aria-label={t('takeoff_viewer.load_new_pdf', { defaultValue: 'Load new PDF' })}>
                <Upload size={14} />
                <input type="file" accept="application/pdf" onChange={handleFileUpload} className="hidden" />
              </label>
            </div>

            {/* Canvas */}
            <div
              ref={containerRef}
              className="relative rounded-lg border border-border overflow-auto bg-gray-100 dark:bg-gray-900"
              style={{ maxHeight: 'calc(100vh - 300px)' }}
            >
              <canvas ref={canvasRef} className="block" />
              <canvas
                ref={overlayRef}
                className="absolute top-0 left-0"
                style={{ cursor: activeTool === 'select' ? 'default' : 'crosshair' }}
                onClick={handleCanvasClick}
                onDoubleClick={handleCanvasDblClick}
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              />
              {settingScale && (
                <div className="absolute top-2 left-2 bg-purple-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium">
                  {scalePoints.length === 0
                    ? t('takeoff_viewer.scale_click_first', { defaultValue: 'Click first point of known dimension' })
                    : t('takeoff_viewer.scale_click_second', { defaultValue: 'Click second point' })}
                </div>
              )}
            </div>
          </div>

          {/* Right: Measurements panel */}
          <div className="w-72 shrink-0 space-y-3">
            {/* Scale info */}
            <div className="rounded-lg border border-border bg-surface-primary p-3">
              <p className="text-xs font-medium text-content-tertiary mb-1">
                {t('takeoff_viewer.scale', { defaultValue: 'Scale' })}
              </p>
              <p className="text-sm font-semibold text-content-primary">
                1px = {(1 / scale.pixelsPerUnit).toFixed(4)} {scale.unitLabel}
              </p>
              <div className="mt-2 flex gap-1 flex-wrap">
                {COMMON_SCALES.slice(0, 4).map((s) => (
                  <button
                    key={s.label}
                    onClick={() => setScale({ pixelsPerUnit: 72 / (0.0254 * s.ratio), unitLabel: 'm' })}
                    className="text-2xs px-1.5 py-0.5 rounded bg-surface-secondary hover:bg-surface-tertiary text-content-tertiary transition-colors"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Count label (when count tool active) */}
            {activeTool === 'count' && (
              <div className="rounded-lg border border-border bg-surface-primary p-3">
                <label className="text-xs font-medium text-content-tertiary block mb-1">
                  {t('takeoff_viewer.count_label', { defaultValue: 'Count Label' })}
                </label>
                <input
                  type="text"
                  value={countLabel}
                  onChange={(e) => setCountLabel(e.target.value)}
                  className="w-full rounded border border-border bg-surface-secondary px-2 py-1 text-xs text-content-primary"
                />
              </div>
            )}

            {/* Measurements list */}
            <div className="rounded-lg border border-border bg-surface-primary p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-content-primary">
                  {t('takeoff_viewer.measurements', { defaultValue: 'Measurements' })} ({pageMeasurements.length})
                </p>
                {fileName && (
                  <div className="flex items-center gap-1.5">
                    {hasPersistedData && (
                      <span className="text-[10px] text-semantic-success flex items-center gap-0.5">
                        <HardDriveDownload className="h-3 w-3" />
                        {t('takeoff_viewer.saved', { defaultValue: 'Saved' })}
                      </span>
                    )}
                    <button
                      onClick={saveNow}
                      className="p-1 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                      title={t('takeoff_viewer.save_measurements', { defaultValue: 'Save measurements' })}
                    >
                      <Save className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>

              {pageMeasurements.length === 0 && (
                <p className="text-xs text-content-tertiary py-4 text-center">
                  {t('takeoff_viewer.no_measurements', { defaultValue: 'No measurements yet. Select a tool and click on the drawing.' })}
                </p>
              )}

              <div className="space-y-1.5 max-h-[400px] overflow-auto">
                {pageMeasurements.map((m) => (
                  <div
                    key={m.id}
                    className="rounded-lg bg-surface-secondary px-2.5 py-2 group"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-2 w-2 rounded-full shrink-0 ${
                          m.type === 'distance' ? 'bg-blue-500' : m.type === 'area' ? 'bg-emerald-500' : 'bg-amber-500'
                        }`}
                      />
                      <div className="flex-1 min-w-0">
                        {editingAnnotationId === m.id ? (
                          <input
                            type="text"
                            value={editingAnnotationValue}
                            onChange={(e) => setEditingAnnotationValue(e.target.value)}
                            onBlur={commitEditAnnotation}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') commitEditAnnotation();
                              if (e.key === 'Escape') {
                                setEditingAnnotationId(null);
                                setEditingAnnotationValue('');
                              }
                            }}
                            autoFocus
                            className="w-full rounded border border-oe-blue bg-surface-primary px-1.5 py-0.5 text-xs font-medium text-content-primary outline-none"
                            placeholder={t('takeoff.add_label', { defaultValue: 'Add label...' })}
                          />
                        ) : (
                          <button
                            onClick={() => startEditAnnotation(m)}
                            className="flex items-center gap-1 text-xs font-medium text-content-primary truncate hover:text-oe-blue transition-colors w-full text-left"
                            title={t('takeoff.add_label', { defaultValue: 'Add label...' })}
                          >
                            <span className="truncate">{m.annotation}</span>
                            <Pencil size={10} className="shrink-0 opacity-0 group-hover:opacity-60 transition-opacity" />
                          </button>
                        )}
                        <p className="text-2xs text-content-tertiary capitalize">{m.type}: {m.label}</p>
                      </div>
                      <button
                        onClick={() => deleteMeasurement(m.id)}
                        className="opacity-0 group-hover:opacity-100 text-content-tertiary hover:text-semantic-error transition-all shrink-0"
                        aria-label={t('takeoff_viewer.delete_measurement', { defaultValue: 'Delete measurement' })}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Export to BOQ button */}
            {measurements.length > 0 && (
              <button
                onClick={openExportDialog}
                className="w-full rounded-lg bg-oe-blue px-3 py-2 text-xs font-semibold text-white hover:bg-oe-blue/90 transition-colors"
              >
                {t('takeoff_viewer.export_to_boq', { defaultValue: 'Export {{count}} measurements to BOQ', count: measurements.length })}
              </button>
            )}

            {/* Help */}
            <div className="flex items-start gap-2 text-xs text-content-quaternary">
              <Info className="h-4 w-4 mt-0.5 shrink-0" />
              <p>
                {t('takeoff_viewer.help', {
                  defaultValue: 'Set the scale first by clicking "Scale" and marking a known dimension. Then use Distance, Area, or Count tools to measure. Double-click to close area polygons.',
                })}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Scale dialog */}
      {showScaleDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded-xl border border-border bg-surface-elevated p-5 shadow-lg">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('takeoff_viewer.set_scale', { defaultValue: 'Set Scale' })}
            </h3>
            <p className="text-xs text-content-tertiary mb-3">
              {t('takeoff_viewer.scale_desc', {
                defaultValue: 'You marked a line of {{pixels}} pixels. Enter the real-world length:',
                pixels: scaleRefPixels.toFixed(0),
              })}
            </p>
            <div className="flex items-center gap-2 mb-4">
              <input
                type="number"
                value={scaleRefReal}
                onChange={(e) => setScaleRefReal(Number(e.target.value) || 0)}
                className="flex-1 rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary"
                min={0}
                step={0.1}
              />
              <span className="text-sm text-content-secondary">m</span>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowScaleDialog(false); setScalePoints([]); }}
                className="px-3 py-1.5 rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleScaleConfirm}
                className="px-3 py-1.5 rounded-lg bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue-hover transition-colors"
              >
                {t('common.apply', { defaultValue: 'Apply' })}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Export to BOQ dialog */}
      {showExportDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-96 rounded-xl border border-border bg-surface-elevated p-5 shadow-lg">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('takeoff_viewer.export_to_boq_title', { defaultValue: 'Export Measurements to BOQ' })}
            </h3>
            <p className="text-xs text-content-tertiary mb-4">
              {t('takeoff_viewer.export_to_boq_desc', {
                defaultValue: '{{count}} measurements will be added as new positions.',
                count: measurements.length,
              })}
            </p>

            <div className="space-y-3 mb-4">
              <div>
                <label className="text-xs font-medium text-content-secondary block mb-1">
                  {t('takeoff.select_project', { defaultValue: 'Project' })}
                </label>
                <select
                  value={selectedProjectId}
                  onChange={(e) => handleProjectChange(e.target.value)}
                  className="w-full rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary"
                >
                  <option value="">{t('takeoff.select_project_placeholder', { defaultValue: 'Select project...' })}</option>
                  {exportProjects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-content-secondary block mb-1">
                  {t('takeoff.select_boq', { defaultValue: 'Bill of Quantities' })}
                </label>
                <select
                  value={selectedBoqId}
                  onChange={(e) => setSelectedBoqId(e.target.value)}
                  disabled={!selectedProjectId}
                  className="w-full rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary disabled:opacity-50"
                >
                  <option value="">{t('takeoff.select_boq_placeholder', { defaultValue: 'Select BOQ...' })}</option>
                  {exportBoqs.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowExportDialog(false)}
                className="px-3 py-1.5 rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleExportToBOQ}
                disabled={!selectedBoqId || isExporting}
                className="px-3 py-1.5 rounded-lg bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue-hover transition-colors disabled:opacity-50"
              >
                {isExporting
                  ? t('common.exporting', { defaultValue: 'Exporting...' })
                  : t('takeoff_viewer.export_count', { defaultValue: 'Export {{count}} positions', count: measurements.length })}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

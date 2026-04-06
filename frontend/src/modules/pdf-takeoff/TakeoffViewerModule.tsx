// OpenConstructionERP — DataDrivenConstruction (DDC)
// CAD2DATA Pipeline · PDF Takeoff Module
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
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
  Route,
  Box,
  Eye,
  EyeOff,
  FileSpreadsheet,
  ChevronDown,
  ChevronUp,
  Cloud,
  ArrowUpRight,
  Type,
  Square,
  Highlighter,
  Loader2,
} from 'lucide-react';
import { useToastStore } from '../../stores/useToastStore';
import { useProjectContextStore } from '../../stores/useProjectContextStore';
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

type MeasureTool = 'select' | 'distance' | 'polyline' | 'area' | 'volume' | 'count'
  | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';

/** Annotation-specific tool types */
type AnnotationToolType = 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';

const ANNOTATION_TOOLS: AnnotationToolType[] = ['cloud', 'arrow', 'text', 'rectangle', 'highlight'];

/** Check if a tool is an annotation tool */
const isAnnotationTool = (tool: MeasureTool): tool is AnnotationToolType =>
  (ANNOTATION_TOOLS as string[]).includes(tool);

/** Check if a measurement type is an annotation type */
const isAnnotationType = (type: string): boolean =>
  (ANNOTATION_TOOLS as string[]).includes(type);

interface Point {
  x: number;
  y: number;
}

interface Measurement {
  id: string;
  type: 'distance' | 'polyline' | 'area' | 'volume' | 'count'
    | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';
  points: Point[];
  value: number;
  unit: string;
  label: string;
  annotation: string; // User-provided text label (e.g. "Living room wall")
  page: number;
  group: string; // Measurement group (e.g. "General", "Structural")
  depth?: number; // Depth in real units, only for volume type
  area?: number; // Area in real units, only for volume type
  text?: string; // Text content for text annotations
  color?: string; // Color for annotation tools
  width?: number; // Width for rectangle/highlight
  height?: number; // Height for rectangle/highlight
}

/* ── Annotation Colors ───────────────────────────────────────────── */

interface AnnotationColor {
  name: string;
  value: string;
}

const ANNOTATION_COLORS: AnnotationColor[] = [
  { name: 'Red', value: '#EF4444' },
  { name: 'Blue', value: '#3B82F6' },
  { name: 'Green', value: '#22C55E' },
  { name: 'Orange', value: '#F59E0B' },
  { name: 'Purple', value: '#8B5CF6' },
  { name: 'Yellow', value: '#FACC15' },
];

/** Default colors for each annotation tool */
const DEFAULT_ANNOTATION_COLORS: Record<AnnotationToolType, string> = {
  cloud: '#EF4444',
  arrow: '#3B82F6',
  text: '#000000',
  rectangle: '#22C55E',
  highlight: '#FACC15',
};

/* ── Measurement Groups ───────────────────────────────────────────── */

interface MeasurementGroup {
  name: string;
  color: string;
}

const MEASUREMENT_GROUPS: MeasurementGroup[] = [
  { name: 'General', color: '#3B82F6' },
  { name: 'Structural', color: '#EF4444' },
  { name: 'Electrical', color: '#F59E0B' },
  { name: 'Plumbing', color: '#8B5CF6' },
  { name: 'HVAC', color: '#06B6D4' },
  { name: 'Finishing', color: '#22C55E' },
  { name: 'Excavation', color: '#92400E' },
  { name: 'Concrete', color: '#6B7280' },
];

const GROUP_COLOR_MAP: Record<string, string> = Object.fromEntries(
  MEASUREMENT_GROUPS.map((g) => [g.name, g.color]),
);

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

  // Measurement groups
  const [activeGroup, setActiveGroup] = useState('General');
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // Volume depth input
  const [showVolumeDepthInput, setShowVolumeDepthInput] = useState(false);
  const [volumeDepthValue, setVolumeDepthValue] = useState('1');
  const [pendingVolumePoints, setPendingVolumePoints] = useState<Point[]>([]);

  // Annotation auto-numbering counters (type -> next index)
  const annotationCounterRef = useRef<Record<string, number>>({ distance: 0, polyline: 0, area: 0, volume: 0, count: 0, cloud: 0, arrow: 0, text: 0, rectangle: 0, highlight: 0 });

  // Annotation markup state
  const [annotationColor, setAnnotationColor] = useState('#EF4444');
  const [showTextInput, setShowTextInput] = useState(false);
  const [textInputPos, setTextInputPos] = useState<Point>({ x: 0, y: 0 });
  const [textInputValue, setTextInputValue] = useState('');
  const [rectStartPoint, setRectStartPoint] = useState<Point | null>(null);
  const [isDraggingRect, setIsDraggingRect] = useState(false);

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
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Document persistence + server sync
  const [fileName, setFileName] = useState<string | null>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { hasPersistedData, saveNow, clearPersisted, syncing, syncedToServer } = useMeasurementPersistence({
    fileName,
    measurements,
    setMeasurements: (ms) => setMeasurements(ms),
    scale,
    setScale: (s) => setScale(s),
    projectId: activeProjectId,
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
      annotationCounterRef.current = { distance: 0, polyline: 0, area: 0, volume: 0, count: 0, cloud: 0, arrow: 0, text: 0, rectangle: 0, highlight: 0 };
      setShowVolumeDepthInput(false);
      setPendingVolumePoints([]);
      setShowTextInput(false);
      setRectStartPoint(null);
      setIsDraggingRect(false);
    } catch (err) {
      console.error('Failed to load PDF:', err);
      addToast({
        type: 'error',
        title: t('takeoff_viewer.pdf_load_failed', { defaultValue: 'Failed to load PDF' }),
        message: err instanceof Error ? err.message : t('takeoff_viewer.pdf_load_error_hint', { defaultValue: 'The file may be corrupted or not a valid PDF.' }),
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  /* ── Warn on unsaved changes (tab close / navigation) ────────────── */

  useEffect(() => {
    if (measurements.length === 0) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [measurements.length]);

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

    // Draw completed measurements on current page (respecting group visibility)
    for (const m of measurements.filter((m) => m.page === currentPage && !hiddenGroups.has(m.group) && !(isAnnotationType(m.type) && hiddenGroups.has('__annotations__')))) {
      const color = GROUP_COLOR_MAP[m.group] || '#3B82F6';
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

      if (m.type === 'polyline' && m.points.length >= 2) {
        // Draw connected line segments
        const p0 = m.points[0]!;
        ctx.beginPath();
        ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
        for (let i = 1; i < m.points.length; i++) {
          const pt = m.points[i]!;
          ctx.lineTo(pt.x * dpr * zoom, pt.y * dpr * zoom);
        }
        ctx.stroke();
        // Draw segment midpoint labels
        for (let i = 0; i < m.points.length - 1; i++) {
          const pa = m.points[i]!;
          const pb = m.points[i + 1]!;
          const segDist = pixelDistance(pa.x, pa.y, pb.x, pb.y);
          const segReal = toRealDistance(segDist, scale);
          const smx = ((pa.x + pb.x) / 2) * dpr * zoom;
          const smy = ((pa.y + pb.y) / 2) * dpr * zoom - 6 * dpr;
          ctx.font = `${10 * dpr}px sans-serif`;
          ctx.fillText(formatMeasurement(segReal, scale.unitLabel), smx, smy);
        }
        // Draw points
        for (const p of m.points) {
          ctx.beginPath();
          ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 3 * dpr, 0, Math.PI * 2);
          ctx.fill();
        }
        // Total label near first point
        const fp = m.points[0]!;
        const totalLx = fp.x * dpr * zoom;
        const totalLy = fp.y * dpr * zoom - 12 * dpr;
        ctx.font = `${12 * dpr}px sans-serif`;
        ctx.fillText(m.label, totalLx, totalLy);
        drawAnnotationLabel(m.annotation, totalLx, totalLy - 14 * dpr, color);
      }

      if ((m.type === 'area' || m.type === 'volume') && m.points.length >= 3) {
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

      /* ── Annotation markup rendering ────────────────────────────── */

      const annoColor = m.color || color;

      if (m.type === 'cloud' && m.points.length >= 3) {
        // Revision cloud: draw scalloped arcs between consecutive points (closed polygon)
        ctx.strokeStyle = annoColor;
        ctx.lineWidth = 2.5 * dpr;
        ctx.beginPath();
        const pts = m.points;
        for (let i = 0; i < pts.length; i++) {
          const pA = pts[i]!;
          const pB = pts[(i + 1) % pts.length]!;
          const ax = pA.x * dpr * zoom;
          const ay = pA.y * dpr * zoom;
          const bx = pB.x * dpr * zoom;
          const by = pB.y * dpr * zoom;
          const segLen = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
          const arcCount = Math.max(2, Math.round(segLen / (18 * dpr)));
          for (let j = 0; j < arcCount; j++) {
            const t0 = j / arcCount;
            const t1 = (j + 1) / arcCount;
            const x0 = ax + (bx - ax) * t0;
            const y0 = ay + (by - ay) * t0;
            const x1 = ax + (bx - ax) * t1;
            const y1 = ay + (by - ay) * t1;
            const cpx = (x0 + x1) / 2;
            const cpy = (y0 + y1) / 2;
            // Perpendicular offset for the bump
            const dx = x1 - x0;
            const dy = y1 - y0;
            const bumpSize = 6 * dpr;
            // Determine outward direction using centroid
            const centX = pts.reduce((s, p) => s + p.x, 0) / pts.length * dpr * zoom;
            const centY = pts.reduce((s, p) => s + p.y, 0) / pts.length * dpr * zoom;
            const midToCentX = centX - cpx;
            const midToCentY = centY - cpy;
            const perpX = -dy;
            const perpY = dx;
            // Bump outward (away from centroid)
            const dot = perpX * midToCentX + perpY * midToCentY;
            const sign = dot > 0 ? -1 : 1;
            const len = Math.sqrt(perpX * perpX + perpY * perpY) || 1;
            const offX = (sign * perpX / len) * bumpSize;
            const offY = (sign * perpY / len) * bumpSize;
            ctx.moveTo(x0, y0);
            ctx.quadraticCurveTo(cpx + offX, cpy + offY, x1, y1);
          }
        }
        ctx.stroke();
        ctx.lineWidth = 2 * dpr;
        // Semi-transparent fill
        ctx.fillStyle = annoColor;
        ctx.globalAlpha = 0.06;
        ctx.beginPath();
        ctx.moveTo(pts[0]!.x * dpr * zoom, pts[0]!.y * dpr * zoom);
        for (let i = 1; i < pts.length; i++) {
          ctx.lineTo(pts[i]!.x * dpr * zoom, pts[i]!.y * dpr * zoom);
        }
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
        // Annotation label at centroid
        const centroidX = pts.reduce((s, p) => s + p.x, 0) / pts.length * dpr * zoom;
        const centroidY = pts.reduce((s, p) => s + p.y, 0) / pts.length * dpr * zoom;
        drawAnnotationLabel(m.annotation, centroidX, centroidY, annoColor);
      }

      if (m.type === 'arrow' && m.points.length === 2) {
        const p0 = m.points[0]!;
        const p1 = m.points[1]!;
        const x0 = p0.x * dpr * zoom;
        const y0 = p0.y * dpr * zoom;
        const x1 = p1.x * dpr * zoom;
        const y1 = p1.y * dpr * zoom;
        // Line
        ctx.strokeStyle = annoColor;
        ctx.lineWidth = 2.5 * dpr;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
        // Arrowhead at end point
        const angle = Math.atan2(y1 - y0, x1 - x0);
        const headLen = 12 * dpr;
        ctx.fillStyle = annoColor;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x1 - headLen * Math.cos(angle - Math.PI / 6), y1 - headLen * Math.sin(angle - Math.PI / 6));
        ctx.lineTo(x1 - headLen * Math.cos(angle + Math.PI / 6), y1 - headLen * Math.sin(angle + Math.PI / 6));
        ctx.closePath();
        ctx.fill();
        ctx.lineWidth = 2 * dpr;
        // Annotation label near start
        drawAnnotationLabel(m.annotation, x0 + 8 * dpr, y0 - 8 * dpr, annoColor);
      }

      if (m.type === 'text' && m.points.length >= 1) {
        const p = m.points[0]!;
        const tx = p.x * dpr * zoom;
        const ty = p.y * dpr * zoom;
        const textContent = m.text || m.annotation;
        const fontSize = 14 * dpr;
        ctx.font = `bold ${fontSize}px sans-serif`;
        ctx.fillStyle = annoColor;
        ctx.fillText(textContent, tx, ty);
      }

      if (m.type === 'rectangle' && m.points.length === 2) {
        const p0 = m.points[0]!;
        const p1 = m.points[1]!;
        const rx = Math.min(p0.x, p1.x) * dpr * zoom;
        const ry = Math.min(p0.y, p1.y) * dpr * zoom;
        const rw = Math.abs(p1.x - p0.x) * dpr * zoom;
        const rh = Math.abs(p1.y - p0.y) * dpr * zoom;
        ctx.strokeStyle = annoColor;
        ctx.lineWidth = 2.5 * dpr;
        ctx.strokeRect(rx, ry, rw, rh);
        ctx.lineWidth = 2 * dpr;
        // Annotation label at top-left
        drawAnnotationLabel(m.annotation, rx, ry - 4 * dpr, annoColor);
      }

      if (m.type === 'highlight' && m.points.length === 2) {
        const p0 = m.points[0]!;
        const p1 = m.points[1]!;
        const rx = Math.min(p0.x, p1.x) * dpr * zoom;
        const ry = Math.min(p0.y, p1.y) * dpr * zoom;
        const rw = Math.abs(p1.x - p0.x) * dpr * zoom;
        const rh = Math.abs(p1.y - p0.y) * dpr * zoom;
        ctx.fillStyle = annoColor;
        ctx.globalAlpha = 0.25;
        ctx.fillRect(rx, ry, rw, rh);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = annoColor;
        ctx.lineWidth = 1 * dpr;
        ctx.strokeRect(rx, ry, rw, rh);
        ctx.lineWidth = 2 * dpr;
        // Annotation label at top-left
        drawAnnotationLabel(m.annotation, rx, ry - 4 * dpr, annoColor);
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
      if (activePoints.length >= 2 && (activeTool === 'area' || activeTool === 'volume')) {
        const ap0 = activePoints[0]!;
        ctx.beginPath();
        ctx.moveTo(ap0.x * dpr * zoom, ap0.y * dpr * zoom);
        for (let i = 1; i < activePoints.length; i++) {
          const apt = activePoints[i]!;
          ctx.lineTo(apt.x * dpr * zoom, apt.y * dpr * zoom);
        }
        ctx.stroke();
      }
      if (activePoints.length >= 2 && activeTool === 'polyline') {
        const ap0 = activePoints[0]!;
        ctx.beginPath();
        ctx.moveTo(ap0.x * dpr * zoom, ap0.y * dpr * zoom);
        for (let i = 1; i < activePoints.length; i++) {
          const apt = activePoints[i]!;
          ctx.lineTo(apt.x * dpr * zoom, apt.y * dpr * zoom);
        }
        ctx.stroke();
        // Show cumulative distance label while drawing
        let totalPx = 0;
        for (let i = 0; i < activePoints.length - 1; i++) {
          const pa = activePoints[i]!;
          const pb = activePoints[i + 1]!;
          totalPx += pixelDistance(pa.x, pa.y, pb.x, pb.y);
        }
        const totalReal = toRealDistance(totalPx, scale);
        const lastPt = activePoints[activePoints.length - 1]!;
        ctx.font = `${12 * dpr}px sans-serif`;
        ctx.fillText(
          formatMeasurement(totalReal, scale.unitLabel),
          lastPt.x * dpr * zoom + 8 * dpr,
          lastPt.y * dpr * zoom - 8 * dpr,
        );
      }
      // In-progress cloud: draw connecting lines between placed points
      if (activePoints.length >= 2 && activeTool === 'cloud') {
        ctx.strokeStyle = annotationColor;
        ctx.setLineDash([4 * dpr, 4 * dpr]);
        ctx.beginPath();
        ctx.moveTo(activePoints[0]!.x * dpr * zoom, activePoints[0]!.y * dpr * zoom);
        for (let i = 1; i < activePoints.length; i++) {
          ctx.lineTo(activePoints[i]!.x * dpr * zoom, activePoints[i]!.y * dpr * zoom);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // In-progress arrow: show dashed line from start
      if (activePoints.length === 1 && activeTool === 'arrow') {
        // Just show the start dot (already drawn above)
      }
    }

    // In-progress rectangle/highlight drag preview
    if (rectStartPoint && isDraggingRect && activePoints.length === 1) {
      const p0 = rectStartPoint;
      const p1 = activePoints[0]!;
      const rx = Math.min(p0.x, p1.x) * dpr * zoom;
      const ry = Math.min(p0.y, p1.y) * dpr * zoom;
      const rw = Math.abs(p1.x - p0.x) * dpr * zoom;
      const rh = Math.abs(p1.y - p0.y) * dpr * zoom;
      if (activeTool === 'highlight') {
        ctx.fillStyle = annotationColor;
        ctx.globalAlpha = 0.2;
        ctx.fillRect(rx, ry, rw, rh);
        ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = annotationColor;
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.setLineDash([]);
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
  }, [measurements, activePoints, currentPage, zoom, settingScale, scalePoints, activeTool, hiddenGroups, scale, annotationColor, rectStartPoint, isDraggingRect]);

  /* ── Canvas click handler ────────────────────────────────────────── */

  const pushUndo = useCallback((op: UndoOperation) => {
    undoStackRef.current.push(op);
    setUndoCount(undoStackRef.current.length);
  }, []);

  /** Generate a default annotation for a new measurement (e.g. "Distance 1", "Area 2"). */
  const nextAnnotation = useCallback(
    (type: string) => {
      annotationCounterRef.current[type] = (annotationCounterRef.current[type] || 0) + 1;
      const n = annotationCounterRef.current[type];
      if (type === 'distance') return t('takeoff.distance_n', { defaultValue: 'Distance {{n}}', n });
      if (type === 'polyline') return t('takeoff.polyline_n', { defaultValue: 'Polyline {{n}}', n });
      if (type === 'area') return t('takeoff.area_n', { defaultValue: 'Area {{n}}', n });
      if (type === 'volume') return t('takeoff.volume_n', { defaultValue: 'Volume {{n}}', n });
      if (type === 'count') return t('takeoff.count_n', { defaultValue: 'Count {{n}}', n });
      if (type === 'cloud') return t('takeoff.cloud_n', { defaultValue: 'Cloud {{n}}', n });
      if (type === 'arrow') return t('takeoff.arrow_n', { defaultValue: 'Arrow {{n}}', n });
      if (type === 'text') return t('takeoff.text_n', { defaultValue: 'Text {{n}}', n });
      if (type === 'rectangle') return t('takeoff.rectangle_n', { defaultValue: 'Rectangle {{n}}', n });
      if (type === 'highlight') return t('takeoff.highlight_n', { defaultValue: 'Highlight {{n}}', n });
      return `${type} ${n}`;
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
            group: activeGroup,
          };
          pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
          setMeasurements((prev) => [...prev, newMeasurement]);
          setActivePoints([]);
        } else {
          pushUndo({ kind: 'add_point', tool: 'distance', point });
        }
        return;
      }

      if (activeTool === 'polyline') {
        pushUndo({ kind: 'add_point', tool: 'polyline', point });
        setActivePoints((prev) => [...prev, point]);
        return;
      }

      if (activeTool === 'area') {
        pushUndo({ kind: 'add_point', tool: 'area', point });
        setActivePoints((prev) => [...prev, point]);
        return;
      }

      if (activeTool === 'volume') {
        pushUndo({ kind: 'add_point', tool: 'volume', point });
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
            group: activeGroup,
          };
          pushUndo({ kind: 'add_count_point', measurementId: newId, point, wasNew: true, previousMeasurement: null });
          return [...prev, newMeasurement];
        });
        return;
      }

      /* ── Annotation tool click handlers ──────────────────────────── */

      if (activeTool === 'cloud') {
        pushUndo({ kind: 'add_point', tool: 'cloud', point });
        setActivePoints((prev) => [...prev, point]);
        return;
      }

      if (activeTool === 'arrow') {
        const newPoints = [...activePoints, point];
        setActivePoints(newPoints);
        if (newPoints.length === 2) {
          const newMeasurement: Measurement = {
            id: `m_${Date.now()}`,
            type: 'arrow',
            points: newPoints,
            value: 0,
            unit: '',
            label: '',
            annotation: nextAnnotation('arrow'),
            page: currentPage,
            group: activeGroup,
            color: annotationColor,
          };
          pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
          setMeasurements((prev) => [...prev, newMeasurement]);
          setActivePoints([]);
        } else {
          pushUndo({ kind: 'add_point', tool: 'arrow', point });
        }
        return;
      }

      if (activeTool === 'text') {
        // Show inline text input at click position
        setTextInputPos(point);
        setTextInputValue('');
        setShowTextInput(true);
        return;
      }

      if (activeTool === 'rectangle' || activeTool === 'highlight') {
        if (!rectStartPoint) {
          // First click — set start corner
          setRectStartPoint(point);
          setActivePoints([point]);
          pushUndo({ kind: 'add_point', tool: activeTool, point });
        } else {
          // Second click — complete rectangle
          const newMeasurement: Measurement = {
            id: `m_${Date.now()}`,
            type: activeTool,
            points: [rectStartPoint, point],
            value: 0,
            unit: '',
            label: '',
            annotation: nextAnnotation(activeTool),
            page: currentPage,
            group: activeGroup,
            color: annotationColor,
            width: Math.abs(point.x - rectStartPoint.x),
            height: Math.abs(point.y - rectStartPoint.y),
          };
          pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [rectStartPoint] });
          setMeasurements((prev) => [...prev, newMeasurement]);
          setRectStartPoint(null);
          setIsDraggingRect(false);
          setActivePoints([]);
        }
        return;
      }
    },
    [activeTool, activePoints, scale, currentPage, countLabel, settingScale, scalePoints, zoom, pushUndo, nextAnnotation, activeGroup, annotationColor, rectStartPoint],
  );

  // Keep the ref in sync so touch handler can call it
  handleCanvasClickRef.current = handleCanvasClick;

  /** Double-click to close an area/volume polygon or finish a polyline */
  const handleCanvasDblClick = useCallback(() => {
    // Polyline: finish with double-click (need at least 2 points)
    if (activeTool === 'polyline' && activePoints.length >= 2) {
      let totalPx = 0;
      for (let i = 0; i < activePoints.length - 1; i++) {
        const pa = activePoints[i]!;
        const pb = activePoints[i + 1]!;
        totalPx += pixelDistance(pa.x, pa.y, pb.x, pb.y);
      }
      const totalReal = toRealDistance(totalPx, scale);
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'polyline',
        points: [...activePoints],
        value: totalReal,
        unit: scale.unitLabel,
        label: formatMeasurement(totalReal, scale.unitLabel),
        annotation: nextAnnotation('polyline'),
        page: currentPage,
        group: activeGroup,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }

    // Area: close polygon with double-click
    if (activeTool === 'area' && activePoints.length >= 3) {
      const pixArea = polygonAreaPixels(activePoints);
      const realArea = toRealArea(pixArea, scale);
      const perimPx = polygonPerimeterPixels(activePoints);
      const realPerim = toRealDistance(perimPx, scale);
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'area',
        points: [...activePoints],
        value: realArea,
        unit: `${scale.unitLabel}\u00B2`,
        label: `${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})`,
        annotation: nextAnnotation('area'),
        page: currentPage,
        group: activeGroup,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }

    // Volume: close polygon then prompt for depth
    if (activeTool === 'volume' && activePoints.length >= 3) {
      setPendingVolumePoints([...activePoints]);
      setVolumeDepthValue('1');
      setShowVolumeDepthInput(true);
      setActivePoints([]);
      return;
    }

    // Cloud: close cloud polygon with double-click (need at least 3 points)
    if (activeTool === 'cloud' && activePoints.length >= 3) {
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'cloud',
        points: [...activePoints],
        value: 0,
        unit: '',
        label: '',
        annotation: nextAnnotation('cloud'),
        page: currentPage,
        group: activeGroup,
        color: annotationColor,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...activePoints] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }
  }, [activeTool, activePoints, scale, currentPage, pushUndo, nextAnnotation, activeGroup, annotationColor]);

  /** Confirm volume depth and create the volume measurement */
  const handleVolumeDepthConfirm = useCallback(() => {
    const depth = parseFloat(volumeDepthValue);
    if (isNaN(depth) || depth <= 0 || pendingVolumePoints.length < 3) {
      setShowVolumeDepthInput(false);
      setPendingVolumePoints([]);
      return;
    }
    const pixArea = polygonAreaPixels(pendingVolumePoints);
    const realArea = toRealArea(pixArea, scale);
    const volume = realArea * depth;
    const newMeasurement: Measurement = {
      id: `m_${Date.now()}`,
      type: 'volume',
      points: [...pendingVolumePoints],
      value: volume,
      unit: `${scale.unitLabel}\u00B3`,
      label: `V = ${formatMeasurement(volume, scale.unitLabel + '\u00B3')} (A: ${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} \u00D7 D: ${formatMeasurement(depth, scale.unitLabel)})`,
      annotation: nextAnnotation('volume'),
      page: currentPage,
      group: activeGroup,
      depth,
      area: realArea,
    };
    pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [] });
    setMeasurements((prev) => [...prev, newMeasurement]);
    setShowVolumeDepthInput(false);
    setPendingVolumePoints([]);
  }, [volumeDepthValue, pendingVolumePoints, scale, currentPage, pushUndo, nextAnnotation, activeGroup]);

  /** Right-click to finish polyline/cloud (alternative to double-click) */
  const handleCanvasContextMenu = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (activeTool === 'polyline' && activePoints.length >= 2) {
        e.preventDefault();
        handleCanvasDblClick(); // Reuse the double-click finish logic
      } else if (activeTool === 'volume' && activePoints.length >= 3) {
        e.preventDefault();
        handleCanvasDblClick();
      } else if (activeTool === 'cloud' && activePoints.length >= 3) {
        e.preventDefault();
        handleCanvasDblClick();
      } else if (activeTool !== 'select') {
        // Prevent context menu while using measurement tools
        e.preventDefault();
      }
    },
    [activeTool, activePoints, handleCanvasDblClick],
  );

  /* ── Mouse move for rectangle/highlight drag preview ──────────────── */

  const handleCanvasMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if ((activeTool === 'rectangle' || activeTool === 'highlight') && rectStartPoint) {
        const rect = overlayRef.current?.getBoundingClientRect();
        if (!rect) return;
        const x = (e.clientX - rect.left) / zoom;
        const y = (e.clientY - rect.top) / zoom;
        setActivePoints([{ x, y }]);
        setIsDraggingRect(true);
      }
    },
    [activeTool, rectStartPoint, zoom],
  );

  /* ── Confirm text annotation ──────────────────────────────────────── */

  const handleTextConfirm = useCallback(() => {
    const trimmed = textInputValue.trim();
    if (!trimmed) {
      setShowTextInput(false);
      return;
    }
    const newMeasurement: Measurement = {
      id: `m_${Date.now()}`,
      type: 'text',
      points: [textInputPos],
      value: 0,
      unit: '',
      label: '',
      annotation: nextAnnotation('text'),
      text: trimmed,
      page: currentPage,
      group: activeGroup,
      color: annotationColor,
    };
    pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [] });
    setMeasurements((prev) => [...prev, newMeasurement]);
    setShowTextInput(false);
    setTextInputValue('');
  }, [textInputValue, textInputPos, currentPage, activeGroup, annotationColor, pushUndo, nextAnnotation]);

  /* ── Scale dialog confirm ────────────────────────────────────────── */

  const handleScaleConfirm = useCallback(() => {
    if (scaleRefPixels <= 0 || scaleRefReal <= 0) {
      addToast({
        type: 'warning',
        title: t('takeoff_viewer.scale_invalid', { defaultValue: 'Invalid scale value' }),
        message: t('takeoff_viewer.scale_must_be_positive', { defaultValue: 'Reference distance must be greater than zero.' }),
      });
      return;
    }
    setScale(deriveScale(scaleRefPixels, scaleRefReal));
    setShowScaleDialog(false);
    setScalePoints([]);
  }, [scaleRefPixels, scaleRefReal, addToast, t]);

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
        if (isAnnotationType(m.type)) return m; // annotations are scale-independent
        if (m.type === 'distance' && m.points.length === 2) {
          const dist = pixelDistance(m.points[0]!.x, m.points[0]!.y, m.points[1]!.x, m.points[1]!.y);
          const realDist = toRealDistance(dist, scale);
          return { ...m, value: realDist, unit: scale.unitLabel, label: formatMeasurement(realDist, scale.unitLabel) };
        }
        if (m.type === 'polyline' && m.points.length >= 2) {
          let totalPx = 0;
          for (let i = 0; i < m.points.length - 1; i++) {
            const pa = m.points[i]!;
            const pb = m.points[i + 1]!;
            totalPx += pixelDistance(pa.x, pa.y, pb.x, pb.y);
          }
          const totalReal = toRealDistance(totalPx, scale);
          return { ...m, value: totalReal, unit: scale.unitLabel, label: formatMeasurement(totalReal, scale.unitLabel) };
        }
        if (m.type === 'area' && m.points.length >= 3) {
          const pixArea = polygonAreaPixels(m.points);
          const realArea = toRealArea(pixArea, scale);
          const perimPx = polygonPerimeterPixels(m.points);
          const realPerim = toRealDistance(perimPx, scale);
          return { ...m, value: realArea, unit: `${scale.unitLabel}\u00B2`, label: `${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})` };
        }
        if (m.type === 'volume' && m.points.length >= 3 && m.depth != null) {
          const pixArea = polygonAreaPixels(m.points);
          const realArea = toRealArea(pixArea, scale);
          const volume = realArea * m.depth;
          return {
            ...m,
            value: volume,
            area: realArea,
            unit: `${scale.unitLabel}\u00B3`,
            label: `V = ${formatMeasurement(volume, scale.unitLabel + '\u00B3')} (A: ${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} \u00D7 D: ${formatMeasurement(m.depth, scale.unitLabel)})`,
          };
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

  /** Group page measurements by their group name */
  const groupedPageMeasurements = useMemo(() => {
    const groups: Record<string, Measurement[]> = {};
    for (const m of pageMeasurements) {
      const g = m.group || 'General';
      if (!groups[g]) groups[g] = [];
      groups[g]!.push(m);
    }
    return groups;
  }, [pageMeasurements]);

  /** Toggle visibility of a measurement group */
  const toggleGroupVisibility = useCallback((groupName: string) => {
    setHiddenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) {
        next.delete(groupName);
      } else {
        next.add(groupName);
      }
      return next;
    });
  }, []);

  /** Toggle collapse of a measurement group in sidebar */
  const toggleGroupCollapse = useCallback((groupName: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) {
        next.delete(groupName);
      } else {
        next.add(groupName);
      }
      return next;
    });
  }, []);

  /** Export measurements to CSV */
  const handleExportCSV = useCallback(() => {
    if (measurements.length === 0) return;
    const rows: string[] = ['Group,Type,Annotation,Value,Unit,Page'];
    // Group measurements by group name for subtotals
    const byGroup: Record<string, Measurement[]> = {};
    for (const m of measurements) {
      const g = m.group || 'General';
      if (!byGroup[g]) byGroup[g] = [];
      byGroup[g]!.push(m);
    }
    for (const [groupName, groupMs] of Object.entries(byGroup)) {
      for (const m of groupMs) {
        const escapeCsv = (s: string) => `"${s.replace(/"/g, '""')}"`;
        rows.push(
          [
            escapeCsv(groupName),
            escapeCsv(m.type),
            escapeCsv(m.annotation),
            m.value.toFixed(3),
            escapeCsv(m.unit),
            String(m.page),
          ].join(','),
        );
      }
      // Add subtotal row for group
      const distMs = groupMs.filter((m) => m.type === 'distance' || m.type === 'polyline');
      const areaMs = groupMs.filter((m) => m.type === 'area');
      const volMs = groupMs.filter((m) => m.type === 'volume');
      const countMs = groupMs.filter((m) => m.type === 'count');
      if (distMs.length > 0) {
        rows.push(`"${groupName} - Subtotal","distance","Total distance",${distMs.reduce((s, m) => s + m.value, 0).toFixed(3)},"${distMs[0]!.unit}",""`);
      }
      if (areaMs.length > 0) {
        rows.push(`"${groupName} - Subtotal","area","Total area",${areaMs.reduce((s, m) => s + m.value, 0).toFixed(3)},"${areaMs[0]!.unit}",""`);
      }
      if (volMs.length > 0) {
        rows.push(`"${groupName} - Subtotal","volume","Total volume",${volMs.reduce((s, m) => s + m.value, 0).toFixed(3)},"${volMs[0]!.unit}",""`);
      }
      if (countMs.length > 0) {
        rows.push(`"${groupName} - Subtotal","count","Total count",${countMs.reduce((s, m) => s + m.value, 0).toFixed(0)},"pcs",""`);
      }
    }
    const csvContent = rows.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `takeoff-measurements-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    addToast({ type: 'success', title: t('takeoff.csv_exported', { defaultValue: 'Measurements exported to CSV' }) });
  }, [measurements, addToast, t]);

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
    } catch (err) {
      setExportProjects([]);
      addToast({
        type: 'error',
        title: t('takeoff.load_projects_failed', { defaultValue: 'Failed to load projects' }),
        message: err instanceof Error ? err.message : '',
      });
    }
  }, [addToast, t]);

  const handleProjectChange = useCallback(async (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedBoqId('');
    if (!projectId) { setExportBoqs([]); return; }
    try {
      const boqs = await apiGet<{ id: string; name: string }[]>(`/v1/boq/boqs/?project_id=${projectId}`);
      setExportBoqs(boqs);
    } catch (err) {
      setExportBoqs([]);
      addToast({
        type: 'error',
        title: t('takeoff.load_boqs_failed', { defaultValue: 'Failed to load BOQ list' }),
        message: err instanceof Error ? err.message : '',
      });
    }
  }, []);

  const handleExportToBOQ = useCallback(async () => {
    if (!selectedBoqId || measurements.length === 0) return;
    setIsExporting(true);
    try {
      let ordinalCounter = 1;
      const exportableMeasurements = measurements.filter((m) => !isAnnotationType(m.type));
      for (const m of exportableMeasurements) {
        const unitMap: Record<string, string> = { m: 'm', 'm\u00B2': 'm2', 'm\u00B3': 'm3', pcs: 'pcs' };
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
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff.export_failed', { defaultValue: 'Export to BOQ failed' }),
        message: err instanceof Error ? err.message : t('takeoff.export_error_hint', { defaultValue: 'Check your connection and try again.' }),
      });
    } finally {
      setIsExporting(false);
    }
  }, [selectedBoqId, measurements, addToast, t]);

  const clearAll = useCallback(() => {
    setMeasurements([]);
    setActivePoints([]);
    undoStackRef.current = [];
    setUndoCount(0);
    annotationCounterRef.current = { distance: 0, polyline: 0, area: 0, volume: 0, count: 0, cloud: 0, arrow: 0, text: 0, rectangle: 0, highlight: 0 };
    setEditingAnnotationId(null);
    setEditingAnnotationValue('');
    setShowVolumeDepthInput(false);
    setPendingVolumePoints([]);
    setShowTextInput(false);
    setTextInputValue('');
    setRectStartPoint(null);
    setIsDraggingRect(false);
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
        <label
          className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border p-12 cursor-pointer hover:border-oe-blue hover:bg-oe-blue-subtle/10 transition-all"
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('border-oe-blue', 'bg-oe-blue-subtle/10'); }}
          onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove('border-oe-blue', 'bg-oe-blue-subtle/10'); }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            e.currentTarget.classList.remove('border-oe-blue', 'bg-oe-blue-subtle/10');
            const file = Array.from(e.dataTransfer.files).find(f => f.type === 'application/pdf');
            if (file) {
              const fakeEvent = { target: { files: [file] } } as unknown as React.ChangeEvent<HTMLInputElement>;
              handleFileUpload(fakeEvent);
            }
          }}
        >
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
        <div className="flex gap-4 min-w-0">
          {/* Left: PDF + Toolbar */}
          <div className="flex-1 min-w-0 space-y-2">
            {/* Toolbar */}
            <div className="flex items-center gap-1 rounded-lg border border-border bg-surface-primary p-1.5 overflow-x-auto">
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
                { tool: 'polyline' as MeasureTool, icon: Route, label: t('takeoff_viewer.tool_polyline', { defaultValue: 'Polyline' }) },
                { tool: 'area' as MeasureTool, icon: Pentagon, label: t('takeoff_viewer.tool_area', { defaultValue: 'Area' }) },
                { tool: 'volume' as MeasureTool, icon: Box, label: t('takeoff_viewer.tool_volume', { defaultValue: 'Volume' }) },
                { tool: 'count' as MeasureTool, icon: Hash, label: t('takeoff_viewer.tool_count', { defaultValue: 'Count' }) },
              ] as const).map(({ tool, icon: Icon, label }) => (
                <button
                  key={tool}
                  onClick={() => { setActiveTool(tool); setActivePoints([]); setRectStartPoint(null); setIsDraggingRect(false); setShowTextInput(false); }}
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

              {/* Annotation tools divider */}
              <span className="w-px h-5 bg-border mx-1" />

              {/* Annotation markup tools */}
              {([
                { tool: 'cloud' as MeasureTool, icon: Cloud, label: t('takeoff_viewer.tool_cloud', { defaultValue: 'Cloud' }) },
                { tool: 'arrow' as MeasureTool, icon: ArrowUpRight, label: t('takeoff_viewer.tool_arrow', { defaultValue: 'Arrow' }) },
                { tool: 'text' as MeasureTool, icon: Type, label: t('takeoff_viewer.tool_text', { defaultValue: 'Text' }) },
                { tool: 'rectangle' as MeasureTool, icon: Square, label: t('takeoff_viewer.tool_rectangle', { defaultValue: 'Rectangle' }) },
                { tool: 'highlight' as MeasureTool, icon: Highlighter, label: t('takeoff_viewer.tool_highlight', { defaultValue: 'Highlight' }) },
              ] as const).map(({ tool, icon: Icon, label }) => (
                <button
                  key={tool}
                  onClick={() => {
                    setActiveTool(tool);
                    setActivePoints([]);
                    setRectStartPoint(null);
                    setIsDraggingRect(false);
                    setShowTextInput(false);
                    // Set default color for this annotation tool type
                    if (isAnnotationTool(tool)) {
                      setAnnotationColor(DEFAULT_ANNOTATION_COLORS[tool]);
                    }
                  }}
                  className={`flex items-center gap-1 px-2 py-1.5 rounded text-xs transition-colors ${
                    activeTool === tool
                      ? 'bg-orange-500 text-white'
                      : 'hover:bg-surface-secondary text-content-secondary'
                  }`}
                  title={label}
                  aria-label={label}
                  aria-pressed={activeTool === tool}
                >
                  <Icon size={14} />
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
              <button onClick={() => measurements.length > 0 ? setShowClearConfirm(true) : undefined} className="p-1.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors" title={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })} aria-label={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })}>
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
              style={{ maxHeight: 'calc(100vh - 280px)', maxWidth: '100%' }}
            >
              <canvas ref={canvasRef} className="block" />
              <canvas
                ref={overlayRef}
                className="absolute top-0 left-0"
                style={{ cursor: activeTool === 'select' ? 'default' : 'crosshair' }}
                onClick={handleCanvasClick}
                onDoubleClick={handleCanvasDblClick}
                onContextMenu={handleCanvasContextMenu}
                onMouseMove={handleCanvasMouseMove}
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
              {/* Inline text input overlay for text annotation tool */}
              {showTextInput && (
                <div
                  className="absolute z-10"
                  style={{
                    left: `${textInputPos.x * zoom}px`,
                    top: `${textInputPos.y * zoom}px`,
                  }}
                >
                  <input
                    type="text"
                    value={textInputValue}
                    onChange={(e) => setTextInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleTextConfirm();
                      if (e.key === 'Escape') { setShowTextInput(false); setTextInputValue(''); }
                    }}
                    onBlur={handleTextConfirm}
                    autoFocus
                    placeholder={t('takeoff_viewer.text_placeholder', { defaultValue: 'Type annotation text...' })}
                    className="rounded border-2 bg-white/95 dark:bg-gray-800/95 px-2 py-1 text-sm font-medium outline-none shadow-lg min-w-[150px]"
                    style={{ borderColor: annotationColor, color: annotationColor }}
                  />
                </div>
              )}
              {/* Cloud tool hint */}
              {activeTool === 'cloud' && activePoints.length > 0 && (
                <div className="absolute top-2 left-2 bg-orange-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium">
                  {t('takeoff_viewer.cloud_hint', { defaultValue: 'Click points to define cloud shape. Double-click or right-click to finish.' })}
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

            {/* Active group selector */}
            <div className="rounded-lg border border-border bg-surface-primary p-3">
              <label className="text-xs font-medium text-content-tertiary block mb-1">
                {t('takeoff_viewer.active_group', { defaultValue: 'Active Group' })}
              </label>
              <div className="flex items-center gap-2">
                <span
                  className="h-3 w-3 rounded-full shrink-0"
                  style={{ backgroundColor: GROUP_COLOR_MAP[activeGroup] || '#3B82F6' }}
                />
                <select
                  value={activeGroup}
                  onChange={(e) => setActiveGroup(e.target.value)}
                  className="flex-1 rounded border border-border bg-surface-secondary px-2 py-1 text-xs text-content-primary"
                >
                  {MEASUREMENT_GROUPS.map((g) => (
                    <option key={g.name} value={g.name}>{g.name}</option>
                  ))}
                </select>
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

            {/* Annotation color picker (when annotation tool active) */}
            {isAnnotationTool(activeTool) && (
              <div className="rounded-lg border border-border bg-surface-primary p-3">
                <label className="text-xs font-medium text-content-tertiary block mb-1.5">
                  {t('takeoff_viewer.annotation_color', { defaultValue: 'Annotation Color' })}
                </label>
                <div className="flex items-center gap-1.5">
                  {ANNOTATION_COLORS.map((c) => (
                    <button
                      key={c.value}
                      onClick={() => setAnnotationColor(c.value)}
                      className={`h-6 w-6 rounded-full border-2 transition-all ${
                        annotationColor === c.value
                          ? 'border-content-primary scale-110'
                          : 'border-transparent hover:scale-105'
                      }`}
                      style={{ backgroundColor: c.value }}
                      title={c.name}
                      aria-label={c.name}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Measurements list (grouped) */}
            <div className="rounded-lg border border-border bg-surface-primary p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-content-primary">
                  {t('takeoff_viewer.measurements', { defaultValue: 'Measurements' })} ({pageMeasurements.filter((m) => !isAnnotationType(m.type)).length})
                </p>
                {fileName && (
                  <div className="flex items-center gap-1.5">
                    {syncing ? (
                      <span className="text-[10px] text-oe-blue flex items-center gap-0.5 animate-pulse">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {t('takeoff_viewer.syncing', { defaultValue: 'Syncing...' })}
                      </span>
                    ) : syncedToServer ? (
                      <span className="text-[10px] text-semantic-success flex items-center gap-0.5">
                        <Cloud className="h-3 w-3" />
                        {t('takeoff_viewer.synced', { defaultValue: 'Synced' })}
                      </span>
                    ) : hasPersistedData ? (
                      <span className="text-[10px] text-amber-500 flex items-center gap-0.5">
                        <HardDriveDownload className="h-3 w-3" />
                        {t('takeoff_viewer.local_only', { defaultValue: 'Local' })}
                      </span>
                    ) : null}
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

              <div className="space-y-2 max-h-[400px] overflow-auto">
                {/* Measurement groups (non-annotation types) */}
                {Object.entries(groupedPageMeasurements).map(([groupName, groupMs]) => {
                  const measurementOnly = groupMs.filter((m) => !isAnnotationType(m.type));
                  if (measurementOnly.length === 0) return null;
                  const groupColor = GROUP_COLOR_MAP[groupName] || '#3B82F6';
                  const isHidden = hiddenGroups.has(groupName);
                  const isCollapsed = collapsedGroups.has(groupName);
                  return (
                    <div key={groupName}>
                      {/* Group header */}
                      <div className="flex items-center gap-1.5 mb-1">
                        <button
                          onClick={() => toggleGroupCollapse(groupName)}
                          className="p-0.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                        >
                          {isCollapsed ? <ChevronDown size={10} /> : <ChevronUp size={10} />}
                        </button>
                        <span
                          className="h-2.5 w-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: groupColor }}
                        />
                        <span className="text-2xs font-semibold text-content-secondary flex-1 uppercase tracking-wider">
                          {groupName} ({measurementOnly.length})
                        </span>
                        <button
                          onClick={() => toggleGroupVisibility(groupName)}
                          className="p-0.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                          title={isHidden
                            ? t('takeoff_viewer.show_group', { defaultValue: 'Show group' })
                            : t('takeoff_viewer.hide_group', { defaultValue: 'Hide group' })
                          }
                        >
                          {isHidden ? <EyeOff size={10} /> : <Eye size={10} />}
                        </button>
                      </div>
                      {/* Group measurements */}
                      {!isCollapsed && (
                        <div className="space-y-1 pl-2">
                          {measurementOnly.map((m) => (
                            <div
                              key={m.id}
                              className="rounded-lg bg-surface-secondary px-2.5 py-2 group/item"
                            >
                              <div className="flex items-center gap-2">
                                <span
                                  className="h-2 w-2 rounded-full shrink-0"
                                  style={{ backgroundColor: groupColor }}
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
                                      <Pencil size={10} className="shrink-0 opacity-0 group-hover/item:opacity-60 transition-opacity" />
                                    </button>
                                  )}
                                  <p className="text-2xs text-content-tertiary capitalize">{m.type}: {m.label}</p>
                                </div>
                                <button
                                  onClick={() => deleteMeasurement(m.id)}
                                  className="opacity-0 group-hover/item:opacity-100 text-content-tertiary hover:text-semantic-error transition-all shrink-0"
                                  aria-label={t('takeoff_viewer.delete_measurement', { defaultValue: 'Delete measurement' })}
                                >
                                  <Trash2 size={12} />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* Annotations section */}
                {(() => {
                  const annotations = pageMeasurements.filter((m) => isAnnotationType(m.type));
                  if (annotations.length === 0) return null;
                  const annoCollapsed = collapsedGroups.has('__annotations__');
                  const annoHidden = hiddenGroups.has('__annotations__');
                  return (
                    <div>
                      <div className="flex items-center gap-1.5 mb-1 mt-2 pt-2 border-t border-border">
                        <button
                          onClick={() => toggleGroupCollapse('__annotations__')}
                          className="p-0.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                        >
                          {annoCollapsed ? <ChevronDown size={10} /> : <ChevronUp size={10} />}
                        </button>
                        <Cloud size={10} className="text-orange-500 shrink-0" />
                        <span className="text-2xs font-semibold text-content-secondary flex-1 uppercase tracking-wider">
                          {t('takeoff_viewer.annotations', { defaultValue: 'Annotations' })} ({annotations.length})
                        </span>
                        <button
                          onClick={() => toggleGroupVisibility('__annotations__')}
                          className="p-0.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                          title={annoHidden
                            ? t('takeoff_viewer.show_annotations', { defaultValue: 'Show annotations' })
                            : t('takeoff_viewer.hide_annotations', { defaultValue: 'Hide annotations' })
                          }
                        >
                          {annoHidden ? <EyeOff size={10} /> : <Eye size={10} />}
                        </button>
                      </div>
                      {!annoCollapsed && (
                        <div className="space-y-1 pl-2">
                          {annotations.map((m) => {
                            const TypeIcon = m.type === 'cloud' ? Cloud
                              : m.type === 'arrow' ? ArrowUpRight
                              : m.type === 'text' ? Type
                              : m.type === 'rectangle' ? Square
                              : Highlighter;
                            return (
                              <div
                                key={m.id}
                                className="rounded-lg bg-surface-secondary px-2.5 py-2 group/item"
                              >
                                <div className="flex items-center gap-2">
                                  <TypeIcon
                                    size={12}
                                    className="shrink-0"
                                    style={{ color: m.color || '#EF4444' }}
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
                                        <span className="truncate">
                                          {m.type === 'text' ? (m.text || m.annotation) : m.annotation}
                                        </span>
                                        <Pencil size={10} className="shrink-0 opacity-0 group-hover/item:opacity-60 transition-opacity" />
                                      </button>
                                    )}
                                    <p className="text-2xs text-content-tertiary capitalize">{m.type}</p>
                                  </div>
                                  <button
                                    onClick={() => deleteMeasurement(m.id)}
                                    className="opacity-0 group-hover/item:opacity-100 text-content-tertiary hover:text-semantic-error transition-all shrink-0"
                                    aria-label={t('takeoff_viewer.delete_annotation', { defaultValue: 'Delete annotation' })}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Export buttons */}
            {measurements.length > 0 && (
              <div className="space-y-1.5">
                <button
                  onClick={openExportDialog}
                  className="w-full rounded-lg bg-oe-blue px-3 py-2 text-xs font-semibold text-white hover:bg-oe-blue/90 transition-colors"
                >
                  {t('takeoff_viewer.export_to_boq', { defaultValue: 'Export {{count}} measurements to BOQ', count: measurements.length })}
                </button>
                <button
                  onClick={handleExportCSV}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs font-semibold text-content-primary hover:bg-surface-tertiary transition-colors flex items-center justify-center gap-1.5"
                >
                  <FileSpreadsheet size={14} />
                  {t('takeoff_viewer.export_excel', { defaultValue: 'Export Excel (CSV)' })}
                </button>
              </div>
            )}

            {/* Help */}
            <div className="flex items-start gap-2 text-xs text-content-quaternary">
              <Info className="h-4 w-4 mt-0.5 shrink-0" />
              <p>
                {t('takeoff_viewer.help_extended', {
                  defaultValue: 'Set the scale first by clicking "Scale" and marking a known dimension. Use Distance, Polyline, Area, Volume, or Count tools for measurements. Use Cloud, Arrow, Text, Rectangle, or Highlight tools for annotations. Double-click to finish polylines, clouds, and close polygons. Right panel groups measurements and annotations separately.',
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
      {/* Volume depth input dialog */}
      {showVolumeDepthInput && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded-xl border border-border bg-surface-elevated p-5 shadow-lg">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('takeoff_viewer.volume_depth_title', { defaultValue: 'Enter Depth for Volume' })}
            </h3>
            <p className="text-xs text-content-tertiary mb-3">
              {t('takeoff_viewer.volume_depth_desc', {
                defaultValue: 'The polygon area has been captured. Enter the depth to calculate volume:',
              })}
            </p>
            <div className="flex items-center gap-2 mb-4">
              <input
                type="number"
                value={volumeDepthValue}
                onChange={(e) => setVolumeDepthValue(e.target.value)}
                className="flex-1 rounded border border-border bg-surface-secondary px-2 py-1.5 text-sm text-content-primary"
                min={0}
                step={0.01}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleVolumeDepthConfirm();
                  if (e.key === 'Escape') {
                    setShowVolumeDepthInput(false);
                    setPendingVolumePoints([]);
                  }
                }}
              />
              <span className="text-sm text-content-secondary">{scale.unitLabel}</span>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowVolumeDepthInput(false); setPendingVolumePoints([]); }}
                className="px-3 py-1.5 rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleVolumeDepthConfirm}
                className="px-3 py-1.5 rounded-lg bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue-hover transition-colors"
              >
                {t('takeoff_viewer.calculate_volume', { defaultValue: 'Calculate Volume' })}
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
      {/* Clear All Confirmation */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowClearConfirm(false)}>
          <div className="w-full max-w-sm mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-content-primary mb-2">
              {t('takeoff_viewer.clear_confirm_title', { defaultValue: 'Clear all measurements?' })}
            </h3>
            <p className="text-xs text-content-secondary mb-4">
              {t('takeoff_viewer.clear_confirm_message', {
                defaultValue: 'All {{count}} measurement(s) and annotations will be permanently removed. This cannot be undone.',
                count: measurements.length,
              })}
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowClearConfirm(false)} className="px-3 py-1.5 rounded-lg text-xs font-medium text-content-secondary hover:bg-surface-secondary transition-colors">
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button onClick={() => { clearAll(); setShowClearConfirm(false); }} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500 text-white hover:bg-red-600 transition-colors">
                {t('takeoff_viewer.clear_all', { defaultValue: 'Clear All' })}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

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
  MoveHorizontal,
  Focus,
  Hand,
  Spline,
  Magnet,
  Copy,
  ChevronLeft,
  ChevronRight,
  MousePointer2,
  Minus,
  Pentagon,
  Hash,
  Trash2,
  Settings2,
  Info,
  HelpCircle,
  Undo2,
  Redo2,
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
  RectangleHorizontal,
  Highlighter,
  Loader2,
  Link2,
  FileUp,
  Crosshair,
  Scan,
  FileText,
  Sparkles,
  Layers,
  List,
  PanelRight,
  X,
  Check,
  AlertTriangle,
  Search,
  Boxes,
} from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '../../stores/useToastStore';
import { useProjectContextStore } from '../../stores/useProjectContextStore';
import { useAuthStore } from '../../stores/useAuthStore';
import { usePreferencesStore } from '../../stores/usePreferencesStore';
import { useQueryClient } from '@tanstack/react-query';
import { boqApi, type CreatePositionData, type Position } from '../../features/boq/api';
import { takeoffApi } from '../../features/takeoff/api';
import {
  measurementDimension,
  unitDimension,
  type MeasureDimension,
} from '../../features/takeoff/lib/units';
import { apiGet, apiPost } from '../../shared/lib/api';
import { formatFileSize } from '../../shared/lib/formatters';
import { convertBetween } from '../../shared/lib/unitConversion';
import { useMeasurementPersistence } from './useMeasurementPersistence';
import {
  type ScaleConfig,
  type CalibrationUnit,
  COMMON_SCALES,
  pixelDistance,
  toRealDistance,
  polygonAreaPixels,
  toRealArea,
  polygonPerimeterPixels,
  formatMeasurement,
  deriveScale,
  presetScale,
  formatScaleRatio,
  toMeters,
  fromMeters,
} from './data/scale-helpers';
import {
  type PageScales,
  emptyPageScales,
  scaleForPage,
  setPageScale as setPageScaleIn,
  pageIsCalibrated,
} from './data/page-scales';
import {
  hitTest,
  insertVertexAt,
  deleteVertexAt,
  translatePoints,
  recomputeMeasurement,
  supportsVariableVertices,
  minVertices,
  type HitResult,
} from './data/hit-test';
import {
  SHORTCUT_LETTER,
  labelWithShortcut,
  shortcutToTool,
  shouldHandleShortcut,
} from '../../features/takeoff/lib/takeoff-shortcuts';
import {
  clampZoom,
  computeFitZoom,
  computeZoomToBox,
  boundingBoxOfPoints,
  zoomAtCursorScroll,
  wheelZoomStep,
  orthoSnap,
  orthoSnapVertexDrag,
  dropTrailingDuplicateVertex,
  snapToVertex,
  VERTEX_SNAP_SCREEN_PX,
  computeDrawReadout,
  type DrawReadout,
} from '../../features/takeoff/lib/takeoff-viewport';
import {
  THUMB_MAX_WIDTH,
  computeThumbScale,
  pagesNearestFirst,
  capThumbCache,
  countMeasurementsByPage,
} from '../../features/takeoff/lib/takeoff-thumbnails';
import {
  itemsFromTextContent,
  findMatchesInPage,
  type TextItem,
  type TextMatch,
} from '../../features/takeoff/lib/takeoff-textsearch';
import {
  computeGroupSummaries,
  formatGroupTotal,
} from '../../features/takeoff/lib/takeoff-groups';
import {
  effectiveQuantity,
  hasQuantityFactor,
  reportedMagnitude,
  slopeFactorFromDegrees,
  degreesFromSlopeFactor,
} from '../../features/takeoff/lib/takeoff-quantity';
import { replicateMeasurementsToPages } from '../../features/takeoff/lib/takeoff-replicate';
import { CalibrationDialog } from '../../features/takeoff/components/CalibrationDialog';
import { ScaleAutoDetect } from '../../features/takeoff/components/ScaleAutoDetect';
import { MeasurementLedger } from '../../features/takeoff/components/MeasurementLedger';
import { CreateRfiFromMeasurementDialog } from '../../features/takeoff/components/CreateRfiFromMeasurementDialog';
import { ReferencedInPanel } from '../../features/file-references/ReferencedInPanel';
import {
  buildExportFilename,
  buildTakeoffPdf,
  buildTakeoffWorkbook,
  triggerDownload,
} from '../../features/takeoff/lib/takeoff-export';
import {
  convertQuantity,
  formatQuantity,
  displayUnitFor,
  measurementLabel,
} from '../../features/takeoff/lib/takeoff-display-units';
import { ElementCostMatchPanel } from '@/features/match';
import { openLink } from '@/shared/lib/desktop';

// Configure PDF.js worker — bundled locally (no CDN dependency)
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

/* ── Types ─────────────────────────────────────────────────────────── */

type MeasureTool = 'select' | 'distance' | 'polyline' | 'area' | 'rectarea' | 'volume' | 'count'
  | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';

/** Annotation-specific tool types */
type AnnotationToolType = 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';

const ANNOTATION_TOOLS: AnnotationToolType[] = ['cloud', 'arrow', 'text', 'rectangle', 'highlight'];

// --- Takeoff toolbar styling primitives ---------------------------------
// Kept together so every control in the two-row toolbar shares one rhythm:
// 28px (h-7) hit targets, soft "segmented" group tracks (a faint surface
// pill behind related buttons, in place of hairline dividers) and a single
// clear active treatment per category. `tbBtn` returns the className for a
// toolbar button given its on/off state and which accent its active state
// uses (blue = measure, orange = markup, purple = scale, neutral = view).
const TB_GROUP = 'inline-flex items-center gap-0.5 rounded-lg bg-surface-secondary/70 p-0.5';
type TbAccent = 'blue' | 'orange' | 'purple' | 'neutral';
function tbBtn(active: boolean, accent: TbAccent = 'neutral'): string {
  const base =
    'inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-1.5 text-xs font-medium transition-colors disabled:opacity-30 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40';
  if (!active) return `${base} text-content-secondary hover:bg-surface-primary hover:text-content-primary`;
  if (accent === 'blue') return `${base} bg-oe-blue text-white shadow-sm`;
  if (accent === 'orange') return `${base} bg-orange-500 text-white shadow-sm`;
  if (accent === 'purple') return `${base} bg-purple-500 text-white shadow-sm`;
  return `${base} bg-surface-primary text-content-primary shadow-xs`;
}

/** Check if a tool is an annotation tool */
const isAnnotationTool = (tool: MeasureTool): tool is AnnotationToolType =>
  (ANNOTATION_TOOLS as string[]).includes(tool);

/** Check if a measurement type is an annotation type */
const isAnnotationType = (type: string): boolean =>
  (ANNOTATION_TOOLS as string[]).includes(type);

/**
 * Quantize a measured quantity for persistence to a BOQ position.
 *
 * Previously this rounded to 2 dp (`Math.round(v*100)/100`), which
 * silently destroyed precision the backend itself preserves: BOQ line
 * storage quantizes to **4 dp** (`_MONEY_QUANTUM = Decimal("0.0001")`),
 * so a 0.0345 m² patch or a 12.3456 m run lost real digits *before* it
 * ever reached the server (D-TKC-022). Round to the same 4 dp quantum
 * so the frontend never pre-truncates below backend storage fidelity;
 * display-side rounding stays separate (read-only, lossless on store).
 */
const boqQuantity = (value: number): number => {
  if (!Number.isFinite(value)) return 0;
  return Math.round(value * 1e4) / 1e4;
};

/** Map a takeoff measurement to a canonical quantities dict for cost
 *  matching: area measurements feed area_m2, volumes feed volume_m3,
 *  lines/polylines feed length_m, counts feed count. */
function pdfMeasurementQuantities(m: {
  type: string;
  value: number;
}): Record<string, number> {
  if (!Number.isFinite(m.value)) return {};
  switch (m.type) {
    case 'area':
      return { area_m2: m.value };
    case 'volume':
      return { volume_m3: m.value };
    case 'count':
      return { count: m.value };
    case 'distance':
    case 'polyline':
      return { length_m: m.value };
    default:
      return {};
  }
}

/** i18n descriptors for a measure dimension, used by the dimension-guard
 *  toast (mirrors the backend ``push_quantity`` guard, which refuses the
 *  push silently - the UI surfaces the mismatch instead). */
const DIMENSION_LABELS: Readonly<Record<MeasureDimension, { key: string; fallback: string }>> = {
  length: { key: 'takeoff.dim_length', fallback: 'length' },
  area: { key: 'takeoff.dim_area', fallback: 'area' },
  volume: { key: 'takeoff.dim_volume', fallback: 'volume' },
  mass: { key: 'takeoff.dim_mass', fallback: 'weight' },
  count: { key: 'takeoff.dim_count', fallback: 'count' },
  lsum: { key: 'takeoff.dim_lsum', fallback: 'lump sum' },
  time: { key: 'takeoff.dim_time', fallback: 'time' },
};

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
  fillAlpha?: number; // Per-measurement fill opacity 0..1 (issue #311)
  strokeWidth?: number; // Per-measurement stroke width in CSS px (issue #312)
  /** Per-measurement stroke width in canonical METRES (issue #339). When set
   *  (and the page is calibrated) the band renders at the element's true width
   *  via strokeWidthReal * pixelsPerUnit, so it stays consistent across pages at
   *  different scales. Mutually exclusive with `strokeWidth`; round-trips via
   *  metadata as ``stroke_width_real``. */
  strokeWidthReal?: number;
  strokeAlpha?: number; // Per-measurement LINE opacity 0..1 for linear types (issue #332)
  /** True-surface slope / pitch factor for an AREA measurement (roofs, ramps):
   *  true surface qty = plan area x slopeFactor (>= 1). Undefined = 1 (flat). */
  slopeFactor?: number;
  /** Material wastage / allowance percent on the reported quantity (10 = +10%).
   *  Undefined = 0. */
  wastagePct?: number;
  /** Typical-multiplier: this measurement stands for N identical repeats
   *  (typical floors / bays). Effective qty = base x multiplier. Undefined = 1. */
  multiplier?: number;
  /** Custom colour of this measurement's GROUP (issue #313), mirrored onto the
   *  measurement so the group colour scheme round-trips server-side through the
   *  metadata blob (like fillAlpha/strokeWidth) instead of being localStorage-
   *  only. Distinct from `color`, which is a per-measurement override. */
  groupColor?: string;
  /** Free-form notes entered via the properties panel. */
  notes?: string;
  /** Opening deduction: an `area` measurement that represents a void
   *  (door, window, cut-out) whose area is SUBTRACTED from the gross area
   *  of its group so a net area = gross - openings. Stored as a positive
   *  gross area; only the rollup subtracts it. Only meaningful for area. */
  isDeduction?: boolean;
  /** Server ID (set after first persistence sync). */
  serverId?: string;
  /** Linked BOQ position id — the canonical "this measurement feeds that position". */
  linkedPositionId?: string;
  /** Linked BOQ position ordinal, cached for the badge. */
  linkedPositionOrdinal?: string;
  /** Linked BOQ id — so the badge can deep-link straight into the editor. */
  linkedBoqId?: string;
  /** Human label of the linked position (description), for tooltip. */
  linkedPositionLabel?: string;
  /** AI-suggested but not yet confirmed by the user (issue #194 Recognize).
   *  Suggested measurements render dashed/translucent and are NEVER persisted
   *  until the user accepts them (which clears this flag). */
  suggested?: boolean;
  /** Recognition confidence 0..1, present only on AI-sourced measurements. */
  confidence?: number;
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

/** Built-in group colours. Custom groups add their colours at runtime via the
 *  component's `groupColorMap` memo (issue #313). */
const BASE_GROUP_COLORS: Record<string, string> = Object.fromEntries(
  MEASUREMENT_GROUPS.map((g) => [g.name, g.color]),
);

/** Describes a reversible measurement operation for the undo stack. */
type UndoOperation =
  | { kind: 'add_point'; tool: MeasureTool; point: Point }
  | { kind: 'complete_measurement'; measurement: Measurement; previousActivePoints: Point[] }
  | { kind: 'add_count_point'; measurementId: string; point: Point; wasNew: boolean; previousMeasurement: Measurement | null }
  | { kind: 'delete_measurement'; measurement: Measurement }
  | { kind: 'change_annotation'; measurementId: string; previousAnnotation: string }
  // In-canvas geometry edit (#194 Feature 1). Both kinds snapshot the
  // pre-edit measurement so undo restores the exact prior geometry +
  // derived value; redo replays the post-edit snapshot.
  | { kind: 'edit_geometry'; measurementId: string; previousMeasurement: Measurement; nextMeasurement: Measurement };

/* ── Component ─────────────────────────────────────────────────────── */

/** Minimal shape of a previously-uploaded takeoff document, surfaced as a
 *  "Recent drawings" list on the landing page so the user can reopen a PDF
 *  in one click instead of re-uploading it. */
export interface RecentTakeoffDocument {
  id: string;
  filename: string;
  pages: number;
  size_bytes: number;
  uploaded_at: string | null;
}

interface TakeoffViewerModuleProps {
  /** URL to pre-load a PDF from (e.g. `/api/v1/takeoff/documents/{id}/download/`). */
  initialPdfUrl?: string;
  /** Optional filename to associate with the pre-loaded PDF (display only). */
  initialPdfName?: string;
  /** Stable document UUID for this PDF (issue #238). Measurement identity is
   *  ``projectId`` + this id, never the filename. Openers that know the id
   *  (Project Files, filmstrip, deep-link) pass it explicitly; when omitted
   *  it is recovered from ``initialPdfUrl``. The explicit prop wins. */
  initialDocumentId?: string | null;
  /** Optional measurement id to auto-select + scroll-to once the measurement
   *  list lands (used by the /markups → /takeoff deep-link). Matches either
   *  the frontend id or the server-side UUID. */
  initialMeasurementId?: string | null;
  /** Previously-uploaded documents for the active project, shown on the
   *  landing page as a "Recent drawings" quick-open list. */
  recentDocuments?: RecentTakeoffDocument[];
  /** Open one of the recent documents in the viewer (parent owns navigation). */
  onOpenRecentDocument?: (docId: string) => void;
}

/** localStorage key for the dragged legend position (#358). A workspace
 *  preference, like a panel size - kept out of the document so it never follows
 *  the file to another user. */
const LEGEND_POS_KEY = 'oe.takeoff.legend-pos';

export default function TakeoffViewerModule({
  initialPdfUrl,
  initialPdfName,
  initialDocumentId,
  initialMeasurementId,
  recentDocuments,
  onOpenRecentDocument,
}: TakeoffViewerModuleProps = {}) {
  const { t } = useTranslation();

  // PDF state
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [zoom, setZoom] = useState(1.0);
  const [isLoading, setIsLoading] = useState(false);

  /* ── Page thumbnails sidebar ──────────────────────────────────────────
   * A left strip of small page previews for multi-page sets (click to jump,
   * current page highlighted, per-page measurement badge). Pure render maths
   * live in features/takeoff/lib/takeoff-thumbnails.ts; this state only drives
   * the strip. Thumbnails render into throwaway offscreen canvases (never the
   * live canvas/overlay) so they cannot disturb the main page render. */
  const [showThumbnails, setShowThumbnails] = useState<boolean>(() => {
    try {
      return localStorage.getItem('takeoff.showThumbnails') !== 'false';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try { localStorage.setItem('takeoff.showThumbnails', String(showThumbnails)); } catch { /* ignore */ }
  }, [showThumbnails]);
  /** Collapse the right Properties/Ledger sidebar for a near-full-viewport
   *  measuring mode, mirroring the Pages strip toggle (#315). Persisted. */
  const [showSidebar, setShowSidebar] = useState<boolean>(() => {
    try {
      return localStorage.getItem('takeoff.showSidebar') !== 'false';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try { localStorage.setItem('takeoff.showSidebar', String(showSidebar)); } catch { /* ignore */ }
  }, [showSidebar]);
  /** Mirror of showSidebar so the keydown handler can tell whether the panel is
   *  collapsed (#315) without joining the handler's dependency array. */
  const showSidebarRef = useRef(showSidebar);
  showSidebarRef.current = showSidebar;
  /** Independently hide the on-canvas measurement name badges and the dimension
   *  values, so a dense sheet can be decluttered without hiding geometry; the
   *  numbers stay in the Ledger and hover tooltip either way (#314). Persisted. */
  const [showLabels, setShowLabels] = useState<boolean>(() => {
    try {
      return localStorage.getItem('takeoff.showLabels') !== 'false';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try { localStorage.setItem('takeoff.showLabels', String(showLabels)); } catch { /* ignore */ }
  }, [showLabels]);
  const [showDimensions, setShowDimensions] = useState<boolean>(() => {
    try {
      return localStorage.getItem('takeoff.showDimensions') !== 'false';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try { localStorage.setItem('takeoff.showDimensions', String(showDimensions)); } catch { /* ignore */ }
  }, [showDimensions]);
  /** page number -> data-URL of a small rendered preview, lazily filled and
   *  LRU-capped (see capThumbCache) so a 300-page set never holds 300 bitmaps. */
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  /** Mirror of `thumbs` for the render loop to read which pages already have a
   *  bitmap without taking `thumbs` as an effect dependency (which would loop). */
  const thumbsRef = useRef(thumbs);
  thumbsRef.current = thumbs;
  /** in-flight guard so the render loop never renders the same page twice. */
  const thumbRenderQueueRef = useRef<Set<number>>(new Set());

  /* ── Find on sheet (text search) ──────────────────────────────────────
   * A search box over the current document's pdf.js text layer: lists matches
   * by page, click to jump+zoom and highlight on the canvas. The tricky
   * coordinate conversion (pdf.js bottom-left text space -> top-left overlay
   * space) is isolated + unit-tested in takeoff-textsearch.ts. Client-only. */
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMatches, setSearchMatches] = useState<TextMatch[]>([]);
  const [activeMatchIdx, setActiveMatchIdx] = useState(-1);
  /** True while the debounced fan-out is scanning page text layers. */
  const [searchBusy, setSearchBusy] = useState(false);
  /** per-page extracted+placed text items so re-searching never re-fetches a
   *  page's text layer. Cleared when the document changes. */
  const textLayerCacheRef = useRef<Map<number, TextItem[]>>(new Map());
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Measurement state
  const [activeTool, setActiveTool] = useState<MeasureTool>('select');
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [activePoints, setActivePoints] = useState<Point[]>([]);
  const [countLabel, setCountLabel] = useState(t('takeoff_viewer.default_count_label', { defaultValue: 'Element' }));
  // Focused/selected by Enter while the Count tool is armed, so the user can
  // rename the group and start a fresh count without hunting for the field (#308).
  const countLabelRef = useRef<HTMLInputElement | null>(null);

  // Scale - PER PAGE (per sheet). A multi-sheet drawing set has a different
  // scale per page (floor plan 1:50, site plan 1:500, ...), so the calibration
  // is keyed by 1-indexed page with a single document default for pages that
  // have not been calibrated yet. ``scale`` below is the effective scale for
  // the *current* page; the rest of the module reads it unchanged.
  const [pageScales, setPageScales] = useState<PageScales>(emptyPageScales);
  const scale = useMemo(
    () => scaleForPage(pageScales, currentPage),
    [pageScales, currentPage],
  );
  /** Set the scale for the CURRENT page only (calibration applies to the
   *  page it was set on). Other uncalibrated pages keep the document
   *  default. */
  const setScale = useCallback(
    (next: ScaleConfig) => {
      setPageScales((prev) => setPageScaleIn(prev, currentPage, next));
    },
    [currentPage],
  );
  // Issue #333: when persistence HYDRATES the page scales on load (restoring a
  // saved calibration), that is a reconciliation, not a recalibration. The
  // scale-change recompute effect below re-projects a volume's typed depth
  // through the old->new pixels-per-unit ratio; on load the "old" ratio is the
  // factory default, so the restore used to corrupt every stored depth (and,
  // via the server recompute, the volume). We flag the hydrate so that one
  // transition SKIPS the recompute entirely and every stored measurement stays
  // byte-identical across a plain reload. A genuine user recalibration goes
  // through ``setScale`` above (no flag) and still re-projects depth correctly.
  const skipScaleRecomputeRef = useRef(false);
  const hydratePageScalesFromPersistence = useCallback((next: PageScales) => {
    skipScaleRecomputeRef.current = true;
    setPageScales(next);
  }, []);
  const [showScaleDialog, setShowScaleDialog] = useState(false);
  const [scaleRefPixels, setScaleRefPixels] = useState(0);
  const [scaleRefReal, setScaleRefReal] = useState(1);
  const [settingScale, setSettingScale] = useState(false);
  const [scalePoints, setScalePoints] = useState<Point[]>([]);

  // Calibration (two-click → modal).  When armed, the same click-to-pick
  // logic as the existing legacy Scale dialog runs, but on completion
  // we route into the new CalibrationDialog which offers unit selection.
  const [showCalibrationDialog, setShowCalibrationDialog] = useState(false);
  const [calibrationPixels, setCalibrationPixels] = useState(0);
  const [calibrationMode, setCalibrationMode] = useState(false);
  /** Cached last calibration PER PAGE (for badge display) - real length +
   *  unit. Keyed by page so the badge always reflects the current sheet. */
  const [lastCalibrationByPage, setLastCalibrationByPage] = useState<
    Record<number, { realLength: number; unit: 'm' | 'mm' | 'ft' | 'in' }>
  >({});
  const lastCalibration = lastCalibrationByPage[currentPage] ?? null;
  /** True when the CURRENT page has its own calibration - drives the
   *  "Calibrated · 1:N @ Lm" status badge. Per-page so navigating to an
   *  uncalibrated sheet correctly shows "not calibrated". */
  const isCalibrated = pageIsCalibrated(pageScales, currentPage);

  // Sidebar right-panel tab: "Properties" (existing) or "Ledger" (new).
  // Persisted to localStorage so the choice survives reloads.
  const [sidebarTab, setSidebarTab] = useState<'properties' | 'ledger'>(() => {
    try {
      const saved = localStorage.getItem('takeoff.sidebarTab');
      return saved === 'ledger' ? 'ledger' : 'properties';
    } catch {
      return 'properties';
    }
  });
  useEffect(() => {
    try { localStorage.setItem('takeoff.sidebarTab', sidebarTab); } catch { /* ignore */ }
  }, [sidebarTab]);

  // Canvas refs
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Bumped at the end of every successful (non-cancelled) page render. The
  // overlay-draw effect depends on it so it repaints AFTER the render
  // continuation resets the overlay bitmap - otherwise a page navigation /
  // select-tool zoom leaves the measurements wiped until the next unrelated
  // redraw (issue #297). The render effect does NOT depend on it, so it can
  // never loop.
  const [renderNonce, setRenderNonce] = useState(0);
  // 1-indexed page the main canvas has actually finished rendering. The
  // thumbnail effect reads this to know the main canvas holds THIS page before
  // downscaling it into the current page's thumbnail (issue #301).
  const mainRenderedPageRef = useRef(0);

  // Touch state for pinch-to-zoom
  const touchStateRef = useRef<{ initialDistance: number; initialZoom: number } | null>(null);

  /* ── Viewport interaction (fit / ortho / pan / readout / hover) ───────
   * All the pure geometry lives in features/takeoff/lib/takeoff-viewport.ts;
   * this state only drives the React surface (toolbar toggles, the live HUD
   * and the hover tooltip). Zoom-at-cursor + touch pinch already exist and
   * are left intact. */

  /** Ortho lock toggle (toolbar). When on - or while Shift is held - a new
   *  segment is constrained to 0 / 45 / 90 degrees from its anchor. The
   *  draw + render paths read `orthoLock || shiftHeldRef.current`. */
  const [orthoLock, setOrthoLock] = useState(false);
  /** True while Shift is physically held, so a momentary press locks the
   *  segment without flipping the persistent toggle (CAD-standard). */
  const shiftHeldRef = useRef(false);

  /** Vertex-snap toggle (toolbar). When on, a new point being drawn snaps onto
   *  the nearest vertex of an already-drawn measurement within a screen-space
   *  radius, so shapes connect exactly to existing corners (issue #303). Read
   *  through a ref in the pointer handlers so toggling it never re-creates
   *  them. Takes precedence over the ortho lock when a vertex is in range. */
  const [vertexSnap, setVertexSnap] = useState(false);
  const vertexSnapRef = useRef(vertexSnap);
  vertexSnapRef.current = vertexSnap;
  /** The existing vertex the in-progress point is currently snapping to, in PDF
   *  units, or null. Drives the on-canvas snap ring cue. */
  const [snapPoint, setSnapPoint] = useState<Point | null>(null);

  /** Space-drag / middle-mouse pan transient. Lives in a ref so the
   *  mid-pan mousemove never triggers a re-render storm; `panning` state
   *  only flips the cursor + suppresses click-to-place. */
  const panRef = useRef<{ startX: number; startY: number; scrollLeft: number; scrollTop: number } | null>(null);
  const [panning, setPanning] = useState(false);
  /** Primary-button canvas press in flight (down, not yet released). Scoped to
   *  button 0: a non-primary press fires auxclick, never click, so keying this
   *  on any button would let a middle-click disarm a guard a tool switch armed
   *  (#356). */
  const pressActiveRef = useRef(false);
  /** The trailing click of the current press must not be treated as a
   *  placement - armed when the tool changes mid-press, consumed by the next
   *  handleCanvasClick (#356). Keyed on the press, not on dragRef, since Escape
   *  can null dragRef mid-press while the click is still coming. */
  const suppressNextClickRef = useRef(false);
  /** True while the Space bar is held - arms pan on the next mousedown and
   *  shows the grab cursor. Cleared on keyup / blur. */
  const [spaceHeld, setSpaceHeld] = useState(false);
  const spaceHeldRef = useRef(false);
  /** Hand / pan mode armed from the toolbar (#316). Unlike Space it is a sticky
   *  toggle: left-drag pans until the user clicks the toolbar button again or
   *  presses Escape. Helps trackpad users who find Space-drag awkward. A ref
   *  mirrors it for the pointer handlers that must not re-subscribe. */
  const [panLock, setPanLock] = useState(false);
  const panLockRef = useRef(false);
  useEffect(() => {
    panLockRef.current = panLock;
  }, [panLock]);

  /** Live pointer position in PDF units while a measure tool is active,
   *  drives the running-length HUD. Null when the pointer is off-canvas. */
  const [liveCursor, setLiveCursor] = useState<Point | null>(null);

  /** Hover tooltip for an existing measurement in select mode: the measured
   *  value / group / linked BOQ reference, anchored at the cursor. */
  const [hoverInfo, setHoverInfo] = useState<{
    measurementId: string;
    x: number;
    y: number;
  } | null>(null);
  /** Mirror of hoverInfo so the right-click context-menu handler can read the
   *  measurement under the cursor without adding hoverInfo to its deps. */
  const hoverInfoRef = useRef(hoverInfo);
  hoverInfoRef.current = hoverInfo;

  /** Right-click context menu for a measurement (select tool). Positioned at
   *  the viewport-space cursor; carries the target measurement id. Null when
   *  closed. Offers Duplicate / Delete (issue #302). */
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    measurementId: string;
  } | null>(null);
  const contextMenuRef = useRef(contextMenu);
  contextMenuRef.current = contextMenu;

  // Measurement groups
  const [activeGroup, setActiveGroup] = useState('General');
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());
  // Per-measurement visibility (issue #359), keyed by measurement id. Parallel
  // to hiddenGroups and honoured at every site group visibility is: a hidden
  // measurement leaves the canvas, the snap pool, the hit-test, the legend
  // count and the annotated PDF, but stays listed (dimmed) so it can be
  // restored. View concern only - it never affects CSV/XLSX/BOQ or totals.
  // Session-scoped, like hiddenGroups (not persisted).
  const [hiddenMeasurements, setHiddenMeasurements] = useState<Set<string>>(new Set());
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // Custom per-group colours (issue #313). Merged over the built-in colours so a
  // user-defined group paints in its chosen colour on the canvas, in the legend
  // and in exports. Loaded/saved per document below.
  const [customGroupColors, setCustomGroupColors] = useState<Record<string, string>>({});
  const groupColorMap = useMemo(
    () => ({ ...BASE_GROUP_COLORS, ...customGroupColors }),
    [customGroupColors],
  );
  /** Set a group's colour (issue #313). */
  const setGroupColor = useCallback((group: string, color: string) => {
    setCustomGroupColors((prev) => ({ ...prev, [group]: color }));
  }, []);

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
  /** Set on Escape so the imminent input onBlur skips handleTextConfirm.
   *  Without it, the unmounting input fires blur, blur calls confirm with
   *  the still-typed value, and a "ghost" annotation is created despite
   *  the user pressing Escape to cancel. */
  const textInputCancellingRef = useRef(false);
  const [rectStartPoint, setRectStartPoint] = useState<Point | null>(null);
  const [isDraggingRect, setIsDraggingRect] = useState(false);

  // Inline editing state for annotations in the measurement list
  const [editingAnnotationId, setEditingAnnotationId] = useState<string | null>(null);
  const [editingAnnotationValue, setEditingAnnotationValue] = useState('');

  // Undo / Redo stacks.  Redo is cleared whenever a fresh user operation
  // is pushed onto undo (so the two stacks never fork).
  const undoStackRef = useRef<UndoOperation[]>([]);
  const redoStackRef = useRef<UndoOperation[]>([]);
  const [undoCount, setUndoCount] = useState(0);
  const [redoCount, setRedoCount] = useState(0);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  // User's measurement system. Measurements are stored metric-canonical
  // (D-TKC-016); this drives display + export conversion (m -> ft, etc.).
  // Read with a selector so unrelated preference changes don't re-render.
  const measurementSystem = usePreferencesStore((s) => s.measurementSystem);

  // Selected measurement (drives the right-side Properties panel).
  const [selectedMeasurementId, setSelectedMeasurementId] = useState<string | null>(null);
  // "Copy to pages" target selection (issue #332 wave): pages the properties
  // panel will replicate the selected measurement / its group onto. Cleared
  // after a copy and whenever the selection changes.
  const [copyTargetPages, setCopyTargetPages] = useState<Set<number>>(new Set());
  // Line-width unit mode + edit buffer (issue #339). ``widthMode`` toggles the
  // Line-width control between screen pixels and the drawing's real-world unit;
  // ``widthDraft`` holds the in-progress text for the real-mode fields so typing
  // is not renormalised on every keystroke (the canonical value stays in
  // ``strokeWidthReal``, in metres). Seeded from the selection by an effect keyed
  // only on the selection id, so re-selecting re-seeds but an unrelated edit does
  // not clobber a half-typed value.
  const [widthMode, setWidthMode] = useState<'px' | 'real'>('px');
  const [widthDraft, setWidthDraft] = useState<{ m: string; ft: string; in: string }>({
    m: '',
    ft: '',
    in: '',
  });

  /* ── In-canvas editing (#194 Feature 1) ──────────────────────────────
   * Drag transient lives in a ref so mid-drag mousemove never triggers a
   * re-render storm. A single `dragPreview` state holds the live mutated
   * points the overlay draws for the one measurement being reshaped; the
   * commit lands on mouseup, which is also where the undo frame + the
   * server-authoritative PATCH (via the persistence hook) fire. */
  const dragRef = useRef<{
    mode: 'vertex' | 'shape';
    measurementId: string;
    /** Pre-edit measurement snapshot for the undo frame + abort restore. */
    original: Measurement;
    /** Original points captured at drag start (vertex / shape source). */
    origPoints: Point[];
    /** Vertex being dragged (vertex mode only). */
    vertexIndex: number;
    /** Pointer position at drag start in PDF units (shape mode only). */
    startPt: Point;
    /** True once the pointer actually moved, so a plain click that grabs a
     *  vertex but does not move it produces no edit / undo frame. */
    moved: boolean;
    /** The latest dragged points - the authoritative geometry the commit
     *  uses on mouseup (state only holds the pre-drag copy mid-drag). */
    lastPoints: Point[];
  } | null>(null);
  const [dragPreview, setDragPreview] = useState<
    {
      measurementId: string;
      points: Point[];
      label: string;
      selfIntersecting: boolean;
      // The live recompute result (value / unit / area / width / height), so the
      // completed-measurements pass can repoint the dragged band to the cursor
      // and its value label stays in sync (#357). selfIntersecting also lives on
      // this object (above), where the bowtie warning already reads it, so the
      // patch is projected field-by-field into the render, never spread whole.
      patch: ReturnType<typeof recomputeMeasurement>;
    } | null
  >(null);
  /** The vertex most recently grabbed / hovered on the selected
   *  measurement, so Delete can remove a vertex (when valid) instead of
   *  always deleting the whole measurement. Cleared on deselect. */
  const activeVertexRef = useRef<{ measurementId: string; index: number } | null>(null);

  // Legend overlay visibility (bottom-left of canvas).
  const [showLegend, setShowLegend] = useState(true);
  // Dragged legend position (#358), in px from the pinned wrapper's top-left;
  // null keeps the default bottom-2 left-2 corner. Seeded from localStorage.
  const [legendPos, setLegendPos] = useState<{ x: number; y: number } | null>(() => {
    if (typeof window === 'undefined') return null;
    try {
      const raw = window.localStorage.getItem(LEGEND_POS_KEY);
      if (raw) {
        const p = JSON.parse(raw) as { x?: unknown; y?: unknown };
        if (typeof p.x === 'number' && typeof p.y === 'number') return { x: p.x, y: p.y };
      }
    } catch {
      /* ignore malformed / unavailable storage */
    }
    return null;
  });
  /** The pinned, non-scrolling wrapper the legend is positioned against (#358):
   *  every drag coordinate and clamp bound is measured relative to it. */
  const legendViewportRef = useRef<HTMLDivElement | null>(null);
  const legendElRef = useRef<HTMLDivElement | null>(null);
  const legendResizeObsRef = useRef<ResizeObserver | null>(null);
  const legendDragRef = useRef<{ onMove: (e: MouseEvent) => void; onUp: () => void } | null>(null);

  // Export to BOQ state
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportProjects, setExportProjects] = useState<{ id: string; name: string }[]>([]);
  const [exportBoqs, setExportBoqs] = useState<{ id: string; name: string }[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Link measurement to BOQ state.  The picker is self-contained: it can
  // discover project + BOQ on its own (no dependency on the Export dialog
  // being opened first) and supports creating a new position inline.
  const [linkingMeasurementId, setLinkingMeasurementId] = useState<string | null>(null);
  const [linkPickerProjectId, setLinkPickerProjectId] = useState('');
  const [linkPickerBoqId, setLinkPickerBoqId] = useState('');
  const [linkPickerProjects, setLinkPickerProjects] = useState<{ id: string; name: string }[]>([]);
  const [linkPickerBoqs, setLinkPickerBoqs] = useState<{ id: string; name: string }[]>([]);
  const [linkBoqPositions, setLinkBoqPositions] = useState<Position[]>([]);
  const [linkBoqsLoading, setLinkBoqsLoading] = useState(false);
  const [linkPositionsLoading, setLinkPositionsLoading] = useState(false);
  const [linkingInProgress, setLinkingInProgress] = useState(false);
  const [linkPickerSearch, setLinkPickerSearch] = useState('');
  const [linkPickerMode, setLinkPickerMode] = useState<'pick' | 'create'>('pick');
  // Bulk "Add all to BOQ" from the Ledger tab: the eligible (unlinked,
  // measurable, human-confirmed) measurements awaiting a target BOQ pick.
  // null = panel closed. Reuses the link-picker project/BOQ state above.
  const [bulkAddMeasurements, setBulkAddMeasurements] = useState<Measurement[] | null>(null);

  // Cross-module linking (issue: takeoff -> Issue/RFI): the measurement the
  // "Create RFI" dialog is open for, or null when closed. A measurement must
  // be synced (have a serverId) to be linkable, so the openers gate on that.
  const [rfiMeasurement, setRfiMeasurement] = useState<Measurement | null>(null);

  // Document persistence + server sync
  const [fileName, setFileName] = useState<string | null>(null);
  // Stable document UUID (issue #238). Measurement identity is projectId +
  // this id. Resolved below from the explicit prop or the download URL; null
  // for a freshly dropped local file (which then persists locally only).
  const [documentId, setDocumentId] = useState<string | null>(initialDocumentId ?? null);
  // Per-page text-layer audit (8.2.0). When a document was opened from the
  // server we fetch its metadata to learn how many pages came back with no
  // text layer (likely scanned drawings that need OCR) so the viewer can flag
  // them instead of presenting them as silently empty. ``null`` = not loaded /
  // not applicable (e.g. a freshly dropped local file).
  const [noTextLayer, setNoTextLayer] = useState<{ count: number; pages: number[] } | null>(null);
  const [noTextBannerDismissed, setNoTextBannerDismissed] = useState(false);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  // PDF / Excel export in-flight flags (drive button spinner state).
  const [isExportingPdf, setIsExportingPdf] = useState(false);
  const [isExportingXlsx, setIsExportingXlsx] = useState(false);
  const { hasPersistedData, saveNow, clearPersisted, syncing, syncedToServer, registerDeletion, hasUnsavedChanges } = useMeasurementPersistence({
    fileName,
    // Stable document UUID drives both the localStorage key and server sync
    // (issue #238); a null id (fresh local drop) keeps everything local.
    documentId,
    measurements,
    // Pass the stable useState setters directly (NOT inline arrows): an
    // inline-arrow setter changes identity every render, which used to tear
    // down the persistence hook's in-flight server load and drop the just-
    // loaded measurements (issue #276).
    setMeasurements,
    // Per-page scale: the hook persists the whole page-scale model and
    // migrates a legacy single-scale document into the default on load.
    pageScales,
    // Hydration goes through the wrapped setter (issue #333) so a load-time
    // scale restore flags the recompute effect to skip re-projecting depth -
    // it is a reconciliation, not a recalibration. Still a stable callback, so
    // the #276 load-teardown guarantee holds.
    setPageScales: hydratePageScalesFromPersistence,
    // The current page's effective scale is still sent on each measurement
    // (scale_pixels_per_unit) so the server-side B8 recompute uses the same
    // ratio the row was drawn at.
    scale,
    projectId: activeProjectId,
  });

  /* ── Deep-link: auto-select measurement from /markups ─────────────────
   * The /markups hub deep-links here with ``?measurementId=<uuid>``. After
   * the persistence hook hydrates the measurement list we look up the row
   * by either the frontend id or the server-side UUID, switch to its page
   * if needed, swap the sidebar to the Ledger tab (so the scroll-to-flash
   * has somewhere visible to land) and select it. The MeasurementLedger
   * scrolls the matching row into view + flashes via CSS.
   *
   * Guarded by a ref so we only consume the param once per mount — the
   * user is free to click around afterwards without us yanking them back. */
  const deepLinkConsumedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!initialMeasurementId) return;
    if (deepLinkConsumedRef.current === initialMeasurementId) return;
    if (measurements.length === 0) return;
    const match = measurements.find(
      (m) => m.id === initialMeasurementId || m.serverId === initialMeasurementId,
    );
    if (!match) return;
    deepLinkConsumedRef.current = initialMeasurementId;
    const targetPage = Math.max(1, Math.min(match.page || 1, totalPages || 1));
    if (targetPage !== currentPage) setCurrentPage(targetPage);
    setSidebarTab('ledger');
    setSelectedMeasurementId(match.id);
  }, [initialMeasurementId, measurements, totalPages, currentPage]);

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
      // A freshly dropped local file has no server document UUID yet (issue
      // #238): clear the id so the persistence hook keeps it local-only and
      // never syncs filename-keyed rows to the server.
      setDocumentId(null);
      setActivePoints([]);
      undoStackRef.current = [];
      redoStackRef.current = [];
      setUndoCount(0);
      setRedoCount(0);
      setSelectedMeasurementId(null);
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

  /* ── Reset cross-page in-progress state on page change ───────────
   * Without this, an in-progress drawing (one click placed) on page 1,
   * a half-finished calibration pick, or a selected measurement that
   * lives on another page all leak to the new page.  Symptoms: the next
   * click on page 2 completes a polygon spanning pages, the calibration
   * dialog opens with a nonsense distance, the Properties panel shows
   * data for an off-screen measurement.  See takeoff audit BUG-1/2/5/6. */
  useEffect(() => {
    setActivePoints([]);
    setRectStartPoint(null);
    setIsDraggingRect(false);
    setShowTextInput(false);
    setPendingVolumePoints([]);
    setShowVolumeDepthInput(false);
    setSettingScale(false);
    setCalibrationMode(false);
    setScalePoints([]);
    // Clear the live draw/calibration preview so no rubber-band or snap ring
    // carries over to the new page (#367).
    setLiveCursor(null);
    setSnapPoint(null);
    // Abandon any in-flight in-canvas edit drag so it cannot bleed onto the
    // new page (#194).
    dragRef.current = null;
    activeVertexRef.current = null;
    setDragPreview(null);
  }, [currentPage]);

  /* Deselect a measurement that lives on a different page than the one
   * being viewed — keeps Properties panel coherent with the canvas. */
  useEffect(() => {
    if (!selectedMeasurementId) return;
    const m = measurements.find((x) => x.id === selectedMeasurementId);
    if (m && m.page !== currentPage) setSelectedMeasurementId(null);
  }, [currentPage, selectedMeasurementId, measurements]);

  /* Clear the active-vertex tracker whenever the selection changes, so a
   * stale vertex index from a previously-selected measurement can never
   * drive a Delete-vertex on the wrong shape (#194). */
  useEffect(() => {
    const active = activeVertexRef.current;
    if (active && active.measurementId !== selectedMeasurementId) {
      activeVertexRef.current = null;
    }
  }, [selectedMeasurementId]);

  /* ── Load PDF from URL (filmstrip click / deep link) ────────────── */

  useEffect(() => {
    if (!initialPdfUrl) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const token = useAuthStore.getState().accessToken;
        const headers: HeadersInit = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const response = await fetch(initialPdfUrl, { headers });
        if (!response.ok) {
          throw new Error(`Failed to fetch PDF (${response.status})`);
        }
        const arrayBuffer = await response.arrayBuffer();
        if (cancelled) return;
        const doc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        if (cancelled) return;
        setPdfDoc(doc);
        setTotalPages(doc.numPages);
        setCurrentPage(1);
        setFileName(initialPdfName || 'Document.pdf');
        setActivePoints([]);
        undoStackRef.current = [];
        redoStackRef.current = [];
        setUndoCount(0);
        setRedoCount(0);
        setSelectedMeasurementId(null);
        annotationCounterRef.current = { distance: 0, polyline: 0, area: 0, volume: 0, count: 0, cloud: 0, arrow: 0, text: 0, rectangle: 0, highlight: 0 };
        setShowVolumeDepthInput(false);
        setPendingVolumePoints([]);
        setShowTextInput(false);
        setRectStartPoint(null);
        setIsDraggingRect(false);
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load PDF from URL:', err);
        addToast({
          type: 'error',
          title: t('takeoff_viewer.pdf_load_failed', { defaultValue: 'Failed to load PDF' }),
          message: err instanceof Error ? err.message : t('takeoff_viewer.pdf_load_error_hint', { defaultValue: 'The file may be corrupted or not a valid PDF.' }),
        });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPdfUrl, initialPdfName]);

  /* ── Fetch server-side document metadata (text-layer audit) ───────── */
  // When a PDF is opened from the server (filmstrip / deep link) the URL is
  // ``/v1/takeoff/documents/{id}/download/``. We pull the document metadata so
  // the viewer can flag pages that came back with no text layer (likely
  // scanned drawings that need OCR). Best-effort: any failure leaves the
  // banner hidden rather than blocking the drawing.
  useEffect(() => {
    setNoTextLayer(null);
    if (!initialPdfUrl) {
      setNoTextBannerDismissed(false);
      return;
    }
    const match = initialPdfUrl.match(/\/documents\/([^/?#]+)/);
    const docId = match?.[1];
    if (!docId) {
      setNoTextBannerDismissed(false);
      return;
    }
    // Restore a per-document dismissal (issue #346): a banner the user already
    // closed for this drawing stays closed when the document is reopened,
    // instead of resetting on every mount. Keyed by the stable document id,
    // following the takeoff.groupColors.<id> idiom used in this component.
    let dismissed = false;
    try {
      dismissed =
        localStorage.getItem(`takeoff.ocrBannerDismissed.${decodeURIComponent(docId)}`) === 'true';
    } catch {
      /* ignore private-mode / quota read failures */
    }
    setNoTextBannerDismissed(dismissed);
    let cancelled = false;
    (async () => {
      try {
        const meta = await takeoffApi.getDocument(decodeURIComponent(docId));
        if (cancelled || !meta) return;
        const count = meta.pages_without_text ?? 0;
        if (count > 0) {
          setNoTextLayer({ count, pages: meta.pages_without_text_list ?? [] });
        }
      } catch {
        /* metadata is advisory - ignore and leave the banner hidden */
      }
    })();
    return () => { cancelled = true; };
  }, [initialPdfUrl]);

  /* ── Resolve the stable document UUID (issue #238) ────────────────────
   * Measurement identity is projectId + this id, never the filename. The
   * explicit ``initialDocumentId`` prop wins (the opener knows it); when
   * absent we recover the id from the download URL. Both the takeoff
   * (``/takeoff/documents/{id}/``) and Project Files (``/documents/{id}/``)
   * URLs carry it in the same capture group. A fresh local drop has neither
   * a prop nor a server URL, so documentId stays null and the persistence
   * hook keeps that file local-only until an upload yields a real id. */
  useEffect(() => {
    if (initialDocumentId) {
      setDocumentId(initialDocumentId);
      return;
    }
    if (initialPdfUrl) {
      const m = initialPdfUrl.match(/\/documents\/([^/?#]+)/);
      if (m?.[1]) {
        setDocumentId(decodeURIComponent(m[1]));
        return;
      }
    }
    // No explicit id and no server URL to recover one from.
    setDocumentId(null);
  }, [initialDocumentId, initialPdfUrl]);

  /* Custom group colours (issue #313) persist per document so a colour scheme
   * survives a reload. A still-local file (documentId null) keeps them for the
   * session only. */
  useEffect(() => {
    if (!documentId) return;
    try {
      const raw = localStorage.getItem(`takeoff.groupColors.${documentId}`);
      setCustomGroupColors(raw ? (JSON.parse(raw) as Record<string, string>) : {});
    } catch {
      setCustomGroupColors({});
    }
  }, [documentId]);
  useEffect(() => {
    if (!documentId) return;
    try {
      localStorage.setItem(
        `takeoff.groupColors.${documentId}`,
        JSON.stringify(customGroupColors),
      );
    } catch {
      /* ignore quota / private-mode failures */
    }
  }, [documentId, customGroupColors]);

  /* Server-side group-colour persistence (issue #313). localStorage alone left
   * a re-coloured group blue for a second user / another machine. The metadata
   * blob on each measurement DOES round-trip to the server (like the #311/#312
   * per-measurement styles), so mirror each group's custom colour onto its
   * measurements' `groupColor`: that stamps the sync-signature, PATCHes the
   * rows, and comes back through `fromApiFormat` -> the reconstruction effect
   * below. Guarded so it only re-renders when a colour actually drifts (no
   * migration, no new schema). */
  useEffect(() => {
    setMeasurements((prev) => {
      let changed = false;
      const next = prev.map((m) => {
        const gc = customGroupColors[m.group];
        if (gc === undefined || m.groupColor === gc) return m;
        changed = true;
        return { ...m, groupColor: gc };
      });
      return changed ? next : prev;
    });
  }, [customGroupColors, measurements]);

  /* Rebuild the group-colour map from measurements loaded off the server
   * (issue #313): a colour set on another machine arrives in each measurement's
   * `groupColor`, so fold it back into `customGroupColors` where the canvas,
   * legend and colour picker read it. Guarded to avoid a render loop with the
   * stamping effect above (they converge to the same value). */
  useEffect(() => {
    setCustomGroupColors((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const m of measurements) {
        if (m.groupColor && next[m.group] !== m.groupColor) {
          next[m.group] = m.groupColor;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [measurements]);

  /* ── Reset per-document caches when the open PDF changes ──────────────
   * Thumbnails and extracted text layers are keyed by page number, so they
   * MUST be dropped when a different document is opened or they would show
   * the previous file's previews / find a previous file's text. */
  useEffect(() => {
    setThumbs({});
    thumbRenderQueueRef.current.clear();
    textLayerCacheRef.current.clear();
    setSearchQuery('');
    setSearchMatches([]);
    setActiveMatchIdx(-1);
  }, [pdfDoc]);

  /* ── Warn on unsaved changes (tab close / navigation) ────────────── */

  useEffect(() => {
    if (measurements.length === 0) return;
    const handler = (e: BeforeUnloadEvent) => {
      // Actually persist before warning (issue #281): the old handler only
      // showed the browser prompt and relied on the user clicking "stay".
      // saveNow writes localStorage synchronously (and best-effort kicks the
      // server) so a tab close keeps the latest measurements regardless of
      // which button the user picks.
      saveNow();
      // Only nag when work is genuinely unsaved (issue #336). The old handler
      // prompted on EVERY navigation - even when everything was already synced -
      // so users learned to click through it. ``hasUnsavedChanges`` reads the
      // live pending state (debounced writes / server sync / edit-PATCH / queued
      // deletes) so a fully-synced document leaves without a prompt.
      if (!hasUnsavedChanges()) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [measurements.length, saveNow, hasUnsavedChanges]);

  /* ── First-measurement-without-calibration warning ───────────────── */
  // Fires exactly once per session: when the user creates their first
  // measurement on an uncalibrated drawing, surface a toast that links
  // back to the Calibrate tool. Without this, raw-pixel measurements
  // (e.g. "22.98 km" on a unitless DWG/PDF) sail through silently.
  const calibrationWarnShownRef = useRef(false);
  useEffect(() => {
    if (calibrationWarnShownRef.current) return;
    if (isCalibrated) return;
    if (measurements.length === 0) return;
    // Only count "real" measurements, not annotations.
    const hasRealMeasurement = measurements.some(
      (m) => !ANNOTATION_TOOLS.includes(m.type as AnnotationToolType),
    );
    if (!hasRealMeasurement) return;
    calibrationWarnShownRef.current = true;
    addToast({
      type: 'warning',
      title: t('takeoff_viewer.calibration_warn_title', {
        defaultValue: 'Drawing is not calibrated',
      }),
      message: t('takeoff_viewer.calibration_warn_msg', {
        defaultValue: 'Measurements may be inaccurate. Use the Calibrate tool to set a real-world length.',
      }),
    });
  }, [measurements, isCalibrated, addToast, t]);

  /* ── Render page to canvas ───────────────────────────────────────── */

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;
    let activeTask: { cancel: () => void } | null = null;

    (async () => {
      // Guard the whole render (getPage + page.render) in one try/catch.
      // A rapid zoom or page-flip supersedes an in-flight render - pdf.js
      // throws RenderingCancelledException, or "Cannot use the same canvas
      // during multiple render() operations" - a page-flip mid-getPage
      // rejects, and teardown aborts the worker. None of these are
      // actionable. The old code rethrew every non-cancellation error out of
      // this fire-and-forget IIFE, surfacing as "Uncaught (in promise)" in the
      // console (and getPage at the top was unguarded entirely). The sibling
      // PDF viewers (InlinePdfAnnotator / PunchPinBoard / PdfCompare) all
      // swallow this; do the same - swallow, dev-only warn.
      try {
        const page = await pdfDoc.getPage(currentPage);
        if (cancelled) return;

        const viewport = page.getViewport({ scale: zoom * window.devicePixelRatio });
        const canvas = canvasRef.current!;
        const ctx = canvas.getContext('2d')!;

        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width / window.devicePixelRatio}px`;
        canvas.style.height = `${viewport.height / window.devicePixelRatio}px`;

        if (overlayRef.current) {
          overlayRef.current.width = viewport.width;
          overlayRef.current.height = viewport.height;
          overlayRef.current.style.width = canvas.style.width;
          overlayRef.current.style.height = canvas.style.height;
          overlayRef.current.getContext('2d')?.clearRect(0, 0, viewport.width, viewport.height);
        }

        const task = page.render({ canvasContext: ctx, viewport });
        activeTask = task;
        await task.promise;
        if (cancelled) return;
        // Setting overlayRef.width/height above reset the overlay bitmap, wiping
        // any measurements the draw effect painted while this render was
        // suspended on getPage. Bump a nonce the draw effect depends on so it
        // repaints over the freshly rendered page (issue #297); record that the
        // main canvas now holds this page for the thumbnail downscale (#301).
        mainRenderedPageRef.current = currentPage;
        setRenderNonce((n) => n + 1);
      } catch (err: any) {
        // Superseded/cancelled render or a teardown abort - expected, silent.
        if (err?.name === 'RenderingCancelledException' || cancelled) return;
        if (import.meta.env.DEV) {
          console.warn('[takeoff] page render skipped:', err);
        }
      }
    })();

    return () => {
      cancelled = true;
      try { activeTask?.cancel(); } catch { /* ignore */ }
    };
  }, [pdfDoc, currentPage, zoom]);

  /* ── Render page thumbnails (sidebar previews) ────────────────────────
   * Renders previews for the visible neighbourhood first (pagesNearestFirst),
   * yielding a frame between pages so the main page render and pointer
   * handling stay responsive on a large set. Offscreen canvases at dpr 1 keep
   * memory modest; the result map is LRU-capped around the current page.
   * `thumbs` is deliberately NOT in the dep array - it is read through the
   * in-flight guard + functional setState, so including it would re-run the
   * effect on every rendered page and loop. */
  useEffect(() => {
    if (!pdfDoc || !showThumbnails || totalPages <= 1) return;
    let cancelled = false;
    const queue = thumbRenderQueueRef.current;
    (async () => {
      for (const n of pagesNearestFirst(currentPage, totalPages)) {
        if (cancelled) return;
        // The current page is captured from the main canvas by the effect
        // below, never re-rendered here: re-rendering it through pdf.js races
        // the main render effect for the same page object and the loser rejects
        // into the empty catch, so the thumbnail spins forever (issue #301).
        if (n === currentPage) continue;
        // Skip pages already rendered (thumbsRef) or currently rendering (queue).
        if (queue.has(n) || thumbsRef.current[n] !== undefined) continue;
        queue.add(n);
        try {
          const page = await pdfDoc.getPage(n);
          if (cancelled) { queue.delete(n); return; }
          const scale = computeThumbScale(page.getViewport({ scale: 1 }).width, THUMB_MAX_WIDTH);
          const vp = page.getViewport({ scale });
          const off = document.createElement('canvas');
          off.width = Math.max(1, Math.ceil(vp.width));
          off.height = Math.max(1, Math.ceil(vp.height));
          const offCtx = off.getContext('2d');
          if (!offCtx) { queue.delete(n); continue; }
          await page.render({ canvasContext: offCtx, viewport: vp }).promise;
          if (cancelled) { queue.delete(n); return; }
          const url = off.toDataURL('image/png');
          setThumbs((prev) => capThumbCache({ ...prev, [n]: url }, currentPage));
        } catch {
          /* a cancelled render or a bad page: drop it and move on */
        } finally {
          queue.delete(n);
        }
        // Yield a frame so navigation + drawing never block on thumbnails.
        await new Promise<void>((r) => requestAnimationFrame(() => r()));
      }
    })();
    return () => { cancelled = true; };
    // `thumbs` intentionally excluded - see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDoc, showThumbnails, currentPage, totalPages]);

  /* Current page thumbnail (issue #301). Rather than re-rendering the current
   * page through pdf.js (which races the main render effect), downscale the
   * already-rendered main canvas into the thumbnail once the main render has
   * settled. `renderNonce` bumps on every completed main render, so this
   * captures the page as soon as it is painted and the sidebar spinner clears.
   * Cheap (a single drawImage), so re-running it per render is fine. */
  useEffect(() => {
    if (!showThumbnails || totalPages <= 1) return;
    if (mainRenderedPageRef.current !== currentPage) return; // not painted yet
    if (thumbsRef.current[currentPage] !== undefined) return; // already captured
    const main = canvasRef.current;
    if (!main || main.width === 0) return;
    try {
      const targetW = Math.max(1, THUMB_MAX_WIDTH);
      const targetH = Math.max(1, Math.round(targetW * (main.height / main.width)));
      const off = document.createElement('canvas');
      off.width = targetW;
      off.height = targetH;
      const offCtx = off.getContext('2d');
      if (!offCtx) return;
      offCtx.drawImage(main, 0, 0, targetW, targetH);
      const url = off.toDataURL('image/png');
      setThumbs((prev) => capThumbCache({ ...prev, [currentPage]: url }, currentPage));
    } catch {
      /* tainted / not-ready canvas: a later render pass retries */
    }
    // `thumbs` read through thumbsRef; capture keyed off renderNonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showThumbnails, totalPages, currentPage, renderNonce]);

  /** Keep the current-page thumbnail in view as the page changes. */
  useEffect(() => {
    if (!showThumbnails) return;
    const el = document.querySelector<HTMLElement>(
      `[data-testid="thumbnail-item"][data-page="${currentPage}"]`,
    );
    el?.scrollIntoView({ block: 'nearest' });
  }, [currentPage, showThumbnails]);

  /* ── Draw overlay (measurements + active drawing) ────────────────── */

  useEffect(() => {
    if (!overlayRef.current) return;
    const ctx = overlayRef.current.getContext('2d')!;
    const dpr = window.devicePixelRatio;
    ctx.clearRect(0, 0, overlayRef.current.width, overlayRef.current.height);

    ctx.lineWidth = 2 * dpr;
    ctx.font = `${12 * dpr}px sans-serif`;

    /** Draw an annotation label with a semi-transparent background at (lx, ly).
     *
     * Dark-mode fix (D-TKC-DK01): the label pill background was hardcoded
     * to '#ffffff', which made it invisible against a light canvas in light
     * mode when globalAlpha was low, and looked jarring in dark mode where
     * the app chrome is dark but the PDF canvas itself is always white.
     * We now read the actual dark-mode state from the html element so the
     * pill adapts correctly: white background in light mode, dark-grey in
     * dark mode. The text color is always the measurement group color so
     * the label remains legible regardless of theme.
     */
    const isDark = document.documentElement.classList.contains('dark');
    const drawAnnotationLabel = (
      text: string,
      lx: number,
      ly: number,
      color: string,
      alignRight = false,
    ) => {
      // Names view toggle: the name badges (and the count badge, which carries
      // the running total) are the names layer and hide together (#314).
      if (!showLabels) return;
      const fontSize = 11 * dpr;
      ctx.font = `bold ${fontSize}px sans-serif`;
      const metrics = ctx.measureText(text);
      const padX = 4 * dpr;
      const padY = 2 * dpr;
      const boxW = metrics.width + padX * 2;
      const boxH = fontSize + padY * 2;
      // alignRight anchors the badge by its RIGHT edge and grows it leftward, so
      // a name stacked over a right-aligned value label (a near-vertical line
      // whose value sits left of the band, #355) extends away from the band
      // instead of back across it. The box stays left-aligned internally, so it
      // does not depend on the global ctx.textAlign the caller has restored.
      const tx = alignRight ? lx - metrics.width : lx;
      const bx = tx - padX;
      const by = ly - fontSize - padY;
      // Semi-transparent background — white in light mode, dark-grey in dark mode
      ctx.globalAlpha = 0.82;
      ctx.fillStyle = isDark ? '#1e293b' : '#ffffff';
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.globalAlpha = 1;
      // Border
      ctx.strokeStyle = color;
      ctx.lineWidth = 1 * dpr;
      ctx.strokeRect(bx, by, boxW, boxH);
      // Text
      ctx.fillStyle = color;
      ctx.fillText(text, tx, ly - padY);
      // Restore line width
      ctx.lineWidth = 2 * dpr;
    };

    /** Anchor a value label off the line it measures (issue #355).
     *
     * A distance / polyline can carry a real-world width (strokeWidthReal) and
     * paint as a band tens of device px wide, so a fixed straight-up offset lands
     * the text inside the band, in the band's own colour. Offset along the
     * segment's up-facing unit normal instead, by half the painted band plus the
     * caller's gap, and derive the text alignment from that normal so the text
     * runs away from the line rather than back across it. originX/Y is the point
     * the label sits by (a segment midpoint, or the first vertex for a polyline
     * total); segA/segB are that segment's endpoints; all are device coords.
     */
    const placeLabel = (
      originX: number,
      originY: number,
      segAx: number,
      segAy: number,
      segBx: number,
      segBy: number,
      gapPx: number,
      bandHalfPx: number,
    ): { lx: number; ly: number; align: CanvasTextAlign; baseline: CanvasTextBaseline } => {
      let nx = -(segBy - segAy);
      let ny = segBx - segAx;
      const len = Math.hypot(nx, ny);
      if (len < 1e-6) {
        // Zero-length segment (nothing dedupes coincident vertices): no
        // direction, so fall back to straight up instead of dividing by zero.
        nx = 0;
        ny = -1;
      } else {
        nx /= len;
        ny /= len;
        // Pick whichever of the two normals points up on screen (smaller y) so
        // labels sit above their lines as they did before. This flips the side
        // as a segment crosses vertical; the invariant that holds is that the
        // text ends up outside the band in every case.
        if (ny > 0) {
          nx = -nx;
          ny = -ny;
        }
      }
      const off = bandHalfPx + gapPx;
      return {
        lx: originX + nx * off,
        ly: originY + ny * off,
        // Canvas text runs rightward from its anchor on its baseline, so a label
        // left of a near-vertical band still runs back across it unless aligned:
        // align right when the normal points left, centre when it is vertical.
        align: nx < -0.01 ? 'right' : nx > 0.01 ? 'left' : 'center',
        baseline: ny < -0.01 ? 'bottom' : ny > 0.01 ? 'top' : 'middle',
      };
    };

    // The measurement being dragged, repointed to the live preview geometry so
    // its band, fills, value label, per-segment labels, vertex dots and
    // annotation all follow the cursor and there is only ever one band on screen
    // (#357). Project the recompute patch field-by-field exactly like
    // commitGeometryEdit does on release - never spread it, since it also carries
    // selfIntersecting, which is not a Measurement field.
    const previewMeasurement: Measurement | null = (() => {
      if (!dragPreview) return null;
      const base = measurements.find((mm) => mm.id === dragPreview.measurementId);
      if (!base || base.page !== currentPage) return null;
      const patch = dragPreview.patch;
      return {
        ...base,
        points: dragPreview.points,
        value: patch.value,
        label: patch.label,
        unit: patch.unit ?? base.unit,
        ...(patch.area !== undefined ? { area: patch.area } : {}),
        ...(patch.width !== undefined ? { width: patch.width } : {}),
        ...(patch.height !== undefined ? { height: patch.height } : {}),
      };
    })();

    // Draw completed measurements on current page (respecting group visibility)
    for (const rawM of measurements.filter((m) => m.page === currentPage && !hiddenGroups.has(m.group) && !hiddenMeasurements.has(m.id) && !(isAnnotationType(m.type) && hiddenGroups.has('__annotations__')))) {
      // Repoint the dragged measurement to its live geometry (#357); the rest of
      // the loop then draws the band / labels / dots from the cursor position.
      const m = previewMeasurement && previewMeasurement.id === rawM.id ? previewMeasurement : rawM;
      // A per-measurement colour (set via the properties swatch) wins over the
      // group default so a recoloured measurement paints in its chosen colour
      // (issue #299); annotation markups already resolve `m.color` below.
      const color = m.color || groupColorMap[m.group] || '#3B82F6';
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      // Optional per-measurement stroke width (issues #312/#339). A real-world
      // width (issue #339, canonical metres) wins when set and the measurement's
      // OWN page is calibrated (pixelsPerUnit > 0): the band then renders at the
      // element's true width via strokeWidthReal * pixelsPerUnit and stays
      // consistent across pages calibrated at different scales. Otherwise the
      // pixel width (issue #312) is used, defaulting to the 2px hairline so unset
      // measurements render exactly as before. Linear types honour it directly;
      // annotation markups reset their own width below. The width scales with
      // zoom (issue #321) so the outline stays fixed relative to the geometry as
      // the user zooms, matching document space.
      const ownPixelsPerUnit = scaleForPage(pageScales, m.page).pixelsPerUnit;
      const baseStrokeWidth =
        m.strokeWidthReal != null && m.strokeWidthReal > 0 && ownPixelsPerUnit > 0
          ? m.strokeWidthReal * ownPixelsPerUnit
          : (m.strokeWidth ?? 2);
      ctx.lineWidth = baseStrokeWidth * dpr * zoom;
      // Half the painted band, in device px, used to push value labels clear of
      // a wide real-world line so they are not drawn on top of it (issue #355).
      const bandHalfPx = (baseStrokeWidth * dpr * zoom) / 2;
      // AI suggestions (#194) render translucent + dashed until the user
      // confirms them, so they read as proposals rather than committed work.
      ctx.globalAlpha = m.suggested ? 0.5 : 1.0;
      ctx.setLineDash(m.suggested ? [6 * dpr, 4 * dpr] : []);

      if (m.type === 'distance' && m.points.length === 2) {
        const p0 = m.points[0]!;
        const p1 = m.points[1]!;
        ctx.beginPath();
        ctx.moveTo(p0.x * dpr * zoom, p0.y * dpr * zoom);
        ctx.lineTo(p1.x * dpr * zoom, p1.y * dpr * zoom);
        // Per-measurement line opacity (issue #332), composed with the loop
        // alpha (0.5 for an unconfirmed AI suggestion, else 1) so a suggested
        // line still reads as translucent. Restored to the loop alpha right
        // after the stroke so the value label / annotation that follow keep
        // full loop opacity. Unset strokeAlpha is fully opaque (no change).
        ctx.globalAlpha = (m.suggested ? 0.5 : 1) * (m.strokeAlpha ?? 1);
        ctx.stroke();
        ctx.globalAlpha = m.suggested ? 0.5 : 1;
        // Measurement value label (converted to the user's system; stored
        // metric per D-TKC-016). Offset perpendicular to the line so a wide
        // real-world band does not paint over it (issue #355).
        const ax = p0.x * dpr * zoom;
        const ay = p0.y * dpr * zoom;
        const bx = p1.x * dpr * zoom;
        const by = p1.y * dpr * zoom;
        const place = placeLabel((ax + bx) / 2, (ay + by) / 2, ax, ay, bx, by, 8 * dpr, bandHalfPx);
        ctx.font = `${12 * dpr}px sans-serif`;
        // Values view toggle: the computed dimension text is the values layer,
        // hidden independently of the name badges (#314).
        if (showDimensions) {
          ctx.textAlign = place.align;
          ctx.textBaseline = place.baseline;
          ctx.fillText(measurementLabel(m, scale, measurementSystem), place.lx, place.ly);
          // Canvas text state is global; restore it before drawAnnotationLabel
          // and every later branch, which all assume left-aligned alphabetic.
          ctx.textAlign = 'left';
          ctx.textBaseline = 'alphabetic';
        }
        // Annotation stacked above the value label (screen space), anchored to
        // its far edge so a long name does not grow back over the band.
        drawAnnotationLabel(m.annotation, place.lx, place.ly - 14 * dpr, color, place.align === 'right');
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
        // Per-measurement line opacity (issue #332), composed with the loop
        // alpha; restored to the loop alpha right after so the per-segment
        // labels + vertex dots below keep full loop opacity.
        ctx.globalAlpha = (m.suggested ? 0.5 : 1) * (m.strokeAlpha ?? 1);
        ctx.stroke();
        ctx.globalAlpha = m.suggested ? 0.5 : 1;
        // Draw segment midpoint labels (values layer, #314). On a traced
        // foundation these per-segment lengths are the densest text of all.
        if (showDimensions) {
          for (let i = 0; i < m.points.length - 1; i++) {
            const pa = m.points[i]!;
            const pb = m.points[i + 1]!;
            const segDist = pixelDistance(pa.x, pa.y, pb.x, pb.y);
            const segReal = toRealDistance(segDist, scale);
            // Offset each segment label perpendicular to its own segment so it
            // clears the band rather than sitting inside it (issue #355).
            const sax = pa.x * dpr * zoom;
            const say = pa.y * dpr * zoom;
            const sbx = pb.x * dpr * zoom;
            const sby = pb.y * dpr * zoom;
            const place = placeLabel((sax + sbx) / 2, (say + sby) / 2, sax, say, sbx, sby, 6 * dpr, bandHalfPx);
            ctx.font = `${10 * dpr}px sans-serif`;
            ctx.textAlign = place.align;
            ctx.textBaseline = place.baseline;
            ctx.fillText(formatQuantity(segReal, 'm', measurementSystem), place.lx, place.ly);
            ctx.textAlign = 'left';
            ctx.textBaseline = 'alphabetic';
          }
        }
        // Draw points
        for (const p of m.points) {
          ctx.beginPath();
          ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 3 * dpr, 0, Math.PI * 2);
          ctx.fill();
        }
        // Total label near first point, offset along the first segment's normal
        // (exactly one segment is incident there) so it clears the band (#355).
        const fp = m.points[0]!;
        const sp = m.points[1]!;
        const fax = fp.x * dpr * zoom;
        const fay = fp.y * dpr * zoom;
        const fbx = sp.x * dpr * zoom;
        const fby = sp.y * dpr * zoom;
        const total = placeLabel(fax, fay, fax, fay, fbx, fby, 12 * dpr, bandHalfPx);
        ctx.font = `${12 * dpr}px sans-serif`;
        if (showDimensions) {
          ctx.textAlign = total.align;
          ctx.textBaseline = total.baseline;
          ctx.fillText(measurementLabel(m, scale, measurementSystem), total.lx, total.ly);
          ctx.textAlign = 'left';
          ctx.textBaseline = 'alphabetic';
        }
        drawAnnotationLabel(m.annotation, total.lx, total.ly - 14 * dpr, color, total.align === 'right');
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
        // An opening deduction (area void) renders in a warning red with a
        // dashed outline so the estimator can see at a glance which areas are
        // being subtracted from the net.
        const isVoid = m.type === 'area' && m.isDeduction;
        if (isVoid) {
          ctx.save();
          ctx.fillStyle = '#ef4444';
          ctx.strokeStyle = '#ef4444';
          ctx.globalAlpha = m.fillAlpha ?? 0.18;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.setLineDash([6 * dpr, 4 * dpr]);
          ctx.stroke();
          ctx.restore();
        } else {
          ctx.globalAlpha = m.fillAlpha ?? 0.15;
          ctx.fill();
          ctx.globalAlpha = 1;
          ctx.stroke();
        }
        // Measurement value label at centroid (converted to the user's
        // measurement system; stored metric per D-TKC-016).
        const cx = m.points.reduce((s, p) => s + p.x, 0) / m.points.length * dpr * zoom;
        const cy = m.points.reduce((s, p) => s + p.y, 0) / m.points.length * dpr * zoom;
        ctx.font = `${12 * dpr}px sans-serif`;
        // Prefix a minus so the on-canvas number reads as a subtraction.
        const areaLabel = measurementLabel(m, scale, measurementSystem);
        if (showDimensions) ctx.fillText(isVoid ? `- ${areaLabel}` : areaLabel, cx, cy);
        // Annotation above centroid
        drawAnnotationLabel(m.annotation, cx, cy - 14 * dpr, color);
      }

      if (m.type === 'count') {
        for (const p of m.points) {
          ctx.beginPath();
          ctx.arc(p.x * dpr * zoom, p.y * dpr * zoom, 8 * dpr, 0, Math.PI * 2);
          ctx.globalAlpha = m.fillAlpha ?? 0.3;
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
    // Reset any AI-suggestion styling before drawing in-progress shapes.
    ctx.globalAlpha = 1.0;
    ctx.setLineDash([]);
    // Reset the per-measurement stroke width (issue #312) so it does not leak
    // into the in-progress drawing below.
    ctx.lineWidth = 2 * dpr;

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
          formatQuantity(totalReal, 'm', measurementSystem),
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

    // Live rubber-band from the last placed point to the cursor for the
    // linear / polygon tools, so an ortho-locked segment is visible before
    // the click lands. The cursor is already ortho-snapped upstream. A faint
    // closing edge back to the first vertex hints the area a polygon will
    // enclose. Skipped while panning (the cursor is not placing points).
    if (
      !settingScale &&
      liveCursor &&
      !panning &&
      activePoints.length > 0 &&
      (activeTool === 'distance' ||
        activeTool === 'polyline' ||
        activeTool === 'area' ||
        activeTool === 'volume')
    ) {
      const last = activePoints[activePoints.length - 1]!;
      ctx.save();
      ctx.strokeStyle = '#2563EB';
      ctx.lineWidth = 1.5 * dpr;
      ctx.setLineDash([5 * dpr, 4 * dpr]);
      ctx.beginPath();
      ctx.moveTo(last.x * dpr * zoom, last.y * dpr * zoom);
      ctx.lineTo(liveCursor.x * dpr * zoom, liveCursor.y * dpr * zoom);
      ctx.stroke();
      // Closing-edge hint for polygons (3+ vertices placed).
      if ((activeTool === 'area' || activeTool === 'volume') && activePoints.length >= 2) {
        const first = activePoints[0]!;
        ctx.globalAlpha = 0.4;
        ctx.beginPath();
        ctx.moveTo(liveCursor.x * dpr * zoom, liveCursor.y * dpr * zoom);
        ctx.lineTo(first.x * dpr * zoom, first.y * dpr * zoom);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.restore();
    }

    // In-progress rectangle/highlight drag preview
    if (!settingScale && rectStartPoint && isDraggingRect && activePoints.length === 1) {
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
      // Measured rectangle previews in measure-blue; annotations keep their color.
      ctx.strokeStyle = activeTool === 'rectarea' ? '#2563EB' : annotationColor;
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
      } else if (scalePoints.length === 1 && liveCursor) {
        // Live rubber-band from the first calibration point to the (possibly
        // ortho-snapped) cursor so the pick is WYSIWYG (issue #343).
        const sp0 = scalePoints[0]!;
        ctx.beginPath();
        ctx.setLineDash([4 * dpr, 4 * dpr]);
        ctx.moveTo(sp0.x * dpr * zoom, sp0.y * dpr * zoom);
        ctx.lineTo(liveCursor.x * dpr * zoom, liveCursor.y * dpr * zoom);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    /* ── In-canvas edit handles + drag preview (#194 Feature 1) ──────────
     * When the select tool is active and a measurement on this page is
     * selected, draw an edit overlay on top: a highlight outline, filled
     * vertex handles the user can grab, and hollow "+" midpoint handles on
     * add-capable types. While a drag is live, the preview points (from
     * `dragPreview`) replace the committed ones so the shape tracks the
     * cursor, with a live value readout and an amber bowtie warning. */
    if (activeTool === 'select') {
      const selected = measurements.find(
        (m) => m.id === selectedMeasurementId && m.page === currentPage,
      );
      // Do not draw the edit overlay for a hidden measurement (#359): a hidden
      // group or an individually hidden measurement should show no outline or
      // handles. The selection is also cleared on hide, but this guard covers
      // the case where something already hidden gets selected another way, and
      // it fixes the pre-existing group-level version of the same bug too.
      const selectedHidden =
        !!selected &&
        (hiddenGroups.has(selected.group) ||
          hiddenMeasurements.has(selected.id) ||
          (isAnnotationType(selected.type) && hiddenGroups.has('__annotations__')));
      if (selected && !selectedHidden) {
        const preview = dragPreview?.measurementId === selected.id ? dragPreview : null;
        const pts = preview ? preview.points : selected.points;
        const accent = '#2563EB';
        ctx.save();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);

        // Outline the selected shape so it reads as active.
        if (pts.length >= 2) {
          ctx.strokeStyle = accent;
          ctx.lineWidth = 1.5 * dpr;
          ctx.setLineDash([5 * dpr, 4 * dpr]);
          ctx.beginPath();
          const isClosed = selected.type === 'area' || selected.type === 'volume' || selected.type === 'cloud';
          const isRect = selected.type === 'rectangle' || selected.type === 'highlight';
          if (isRect && pts.length === 2) {
            const a = pts[0]!;
            const b = pts[1]!;
            ctx.strokeRect(
              Math.min(a.x, b.x) * dpr * zoom,
              Math.min(a.y, b.y) * dpr * zoom,
              Math.abs(b.x - a.x) * dpr * zoom,
              Math.abs(b.y - a.y) * dpr * zoom,
            );
          } else {
            ctx.moveTo(pts[0]!.x * dpr * zoom, pts[0]!.y * dpr * zoom);
            for (let i = 1; i < pts.length; i++) {
              ctx.lineTo(pts[i]!.x * dpr * zoom, pts[i]!.y * dpr * zoom);
            }
            if (isClosed) ctx.closePath();
            ctx.stroke();
          }
          ctx.setLineDash([]);
        }

        // Midpoint "+" add-vertex handles (variable-vertex types only).
        if (supportsVariableVertices(selected.type) && pts.length >= 2 && !preview) {
          const closed = selected.type === 'area' || selected.type === 'volume' || selected.type === 'cloud';
          const segCount = closed ? pts.length : pts.length - 1;
          ctx.strokeStyle = accent;
          ctx.lineWidth = 1.5 * dpr;
          for (let i = 0; i < segCount; i++) {
            const a = pts[i]!;
            const b = pts[(i + 1) % pts.length]!;
            const mx = ((a.x + b.x) / 2) * dpr * zoom;
            const my = ((a.y + b.y) / 2) * dpr * zoom;
            const r = 4 * dpr;
            ctx.beginPath();
            ctx.arc(mx, my, r, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.globalAlpha = 0.9;
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(mx - r * 0.5, my);
            ctx.lineTo(mx + r * 0.5, my);
            ctx.moveTo(mx, my - r * 0.5);
            ctx.lineTo(mx, my + r * 0.5);
            ctx.stroke();
          }
        }

        // Filled vertex handles (the grabbable points).
        const handleR = 5 * dpr;
        for (let i = 0; i < pts.length; i++) {
          const p = pts[i]!;
          const hx = p.x * dpr * zoom;
          const hy = p.y * dpr * zoom;
          ctx.beginPath();
          ctx.arc(hx, hy, handleR, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.fill();
          ctx.lineWidth = 2 * dpr;
          ctx.strokeStyle = accent;
          ctx.stroke();
        }

        // Live value readout + bowtie warning while dragging.
        if (preview) {
          const last = pts[pts.length - 1]!;
          const lx = last.x * dpr * zoom + 10 * dpr;
          const ly = last.y * dpr * zoom - 10 * dpr;
          if (preview.label) {
            ctx.font = `bold ${12 * dpr}px sans-serif`;
            // Route through measurementLabel so the readout reads in the user's
            // unit system, matching the committed label. preview.label is the raw
            // metric string, which would show an imperial user metres (#357).
            const txt = previewMeasurement
              ? measurementLabel(previewMeasurement, scale, measurementSystem)
              : preview.label;
            const w = ctx.measureText(txt).width + 8 * dpr;
            ctx.fillStyle = isDark ? '#1e293b' : '#ffffff';
            ctx.globalAlpha = 0.9;
            ctx.fillRect(lx - 4 * dpr, ly - 12 * dpr, w, 18 * dpr);
            ctx.globalAlpha = 1;
            ctx.fillStyle = accent;
            ctx.fillText(txt, lx, ly);
          }
          if (preview.selfIntersecting) {
            ctx.font = `bold ${11 * dpr}px sans-serif`;
            ctx.fillStyle = '#f59e0b';
            ctx.fillText('⚠', last.x * dpr * zoom - 18 * dpr, last.y * dpr * zoom - 10 * dpr);
          }
        }
        ctx.restore();
      }
    }

    // Find-on-sheet highlights for the current page. Drawn last so they sit
    // on top of measurements. Boxes are in the same top-left PDF-unit space as
    // measurement points, so the same `* dpr * zoom` transform applies. The
    // active match is a stronger orange; the rest are a translucent yellow.
    if (searchMatches.length > 0) {
      ctx.save();
      for (let k = 0; k < searchMatches.length; k++) {
        const mt = searchMatches[k]!;
        if (mt.page !== currentPage) continue;
        const x = mt.box.minX * dpr * zoom;
        const y = mt.box.minY * dpr * zoom;
        const w = (mt.box.maxX - mt.box.minX) * dpr * zoom;
        const h = (mt.box.maxY - mt.box.minY) * dpr * zoom;
        const isActive = k === activeMatchIdx;
        ctx.globalAlpha = isActive ? 0.45 : 0.25;
        ctx.fillStyle = isActive ? '#F59E0B' : '#FACC15';
        ctx.fillRect(x, y, w, h);
        if (isActive) {
          ctx.globalAlpha = 0.95;
          ctx.lineWidth = 1.5 * dpr;
          ctx.strokeStyle = '#D97706';
          ctx.strokeRect(x, y, w, h);
        }
      }
      ctx.restore();
    }

    // Snap-to-vertex cue (issue #303): a ring at the existing vertex the
    // in-progress point will lock onto, so the connection is visible before the
    // click lands. Drawn last so it sits above everything. Suppressed while a
    // scale calibration is armed so a stale draw-snap ring cannot linger (#367).
    if (snapPoint && !settingScale) {
      ctx.save();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = '#22C55E';
      ctx.lineWidth = 2 * dpr;
      ctx.beginPath();
      ctx.arc(snapPoint.x * dpr * zoom, snapPoint.y * dpr * zoom, 6 * dpr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }, [measurements, activePoints, currentPage, zoom, settingScale, scalePoints, activeTool, hiddenGroups, hiddenMeasurements, scale, pageScales, annotationColor, rectStartPoint, isDraggingRect, selectedMeasurementId, dragPreview, liveCursor, panning, searchMatches, activeMatchIdx, measurementSystem, snapPoint, showLabels, showDimensions, renderNonce, groupColorMap]);

  /* ── Canvas click handler ────────────────────────────────────────── */

  const pushUndo = useCallback((op: UndoOperation) => {
    undoStackRef.current.push(op);
    setUndoCount(undoStackRef.current.length);
    // A fresh user action invalidates any pending redo frames.
    if (redoStackRef.current.length > 0) {
      redoStackRef.current = [];
      setRedoCount(0);
    }
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
      // A mouse press that ended off-canvas can leave suppressNextClick set, and
      // handleTouchEnd calls the placement handler directly (not via a browser
      // click), so clear it here too or the next tap's placement is swallowed
      // (#356).
      suppressNextClickRef.current = false;
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

  // Count-by-example ("Count similar") seed plumbing. The arm latch and the
  // async seed handler are read through refs inside handleCanvasClick so the
  // big click handler never needs them in its dependency array (mirrors
  // handleCanvasClickRef). armCountSimilarRef is the one-shot "the next click
  // picks the seed symbol" latch; a state mirror drives the button styling.
  const armCountSimilarRef = useRef(false);
  const handleCountByExampleSeedRef = useRef<((seed: Point) => void) | null>(null);

  // Snap-target vertices (issue #303): every vertex of a visible, committed
  // measurement on the current page, hit-tested against the draw cursor when
  // vertex snap is on. Read through a ref inside the pointer handlers so it
  // never enters their dependency arrays. Suggestions + hidden groups are
  // excluded (you cannot connect to a corner you cannot see).
  const snapVertices = useMemo(() => {
    const out: Point[] = [];
    for (const m of measurements) {
      if (m.page !== currentPage || m.suggested) continue;
      if (hiddenGroups.has(m.group)) continue;
      // A hidden measurement's corners are not snappable either (#359): you
      // cannot connect to a corner you cannot see.
      if (hiddenMeasurements.has(m.id)) continue;
      if (isAnnotationType(m.type) && hiddenGroups.has('__annotations__')) continue;
      for (const p of m.points) out.push(p);
    }
    return out;
  }, [measurements, currentPage, hiddenGroups, hiddenMeasurements]);
  const snapVerticesRef = useRef(snapVertices);
  snapVerticesRef.current = snapVertices;
  // handleCanvasDblClick is defined below handleCanvasClick, so the click path
  // reaches the shared finish routine through a ref (avoids a declaration cycle),
  // used by close-on-first-vertex for polygons (#309). Assigned just after the
  // callback is defined.
  const handleCanvasDblClickRef = useRef<(() => void) | null>(null);

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      // A press that began before the tool changed (a mid-press shortcut switch)
      // must not place a point in the tool that replaced it (#356). Consume its
      // trailing click, in the same shape as the pan guard below.
      if (suppressNextClickRef.current) {
        suppressNextClickRef.current = false;
        return;
      }
      // A pan gesture that ended on this element must not also place a point,
      // and in sticky pan mode (#316) a click never places one either.
      if (panRef.current || spaceHeldRef.current || panLockRef.current) return;
      const rect = overlayRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = (e.clientX - rect.left) / zoom;
      const y = (e.clientY - rect.top) / zoom;
      let point: Point = { x, y };

      // Snap precedence (issue #303, then ortho): when vertex snap is on and a
      // nearby existing vertex is in range, the new point locks onto it so the
      // shape connects exactly to that corner (even for the first point, which
      // has no ortho anchor). Otherwise the ortho / angle lock (toggle or Shift)
      // constrains the new segment to 0 / 45 / 90 degrees from the previous
      // placed point. Rectangles are inherently axis-aligned so neither applies.
      const canVertexSnap =
        activeTool === 'distance' ||
        activeTool === 'polyline' ||
        activeTool === 'area' ||
        activeTool === 'volume';
      // While drawing, the shape's own placed vertices (all but the immediately
      // preceding one, which the ortho lock already anchors) join the committed
      // snap pool, so a run can connect back to its own corners, above all its
      // first vertex (#309).
      const snapPool =
        canVertexSnap && activePoints.length > 1
          ? [...snapVerticesRef.current, ...activePoints.slice(0, -1)]
          : snapVerticesRef.current;
      // While calibrating (settingScale) neither draw-path snap applies: the
      // calibration pick has its own ortho below, and letting an in-progress
      // measurement's vertices or ortho anchor hijack the scale click would
      // corrupt the calibration (issue #343).
      const vsnap = !settingScale && vertexSnapRef.current && canVertexSnap
        ? snapToVertex(point, snapPool, zoom, VERTEX_SNAP_SCREEN_PX)
        : null;
      if (vsnap) {
        point = vsnap;
        // Close-on-first-vertex: for the polygon tools, a snapped click on the
        // first vertex with 3+ points finishes the shape, as in common CAD and
        // takeoff tools. Requiring the snap hit keeps it deliberate and never
        // adds a stray vertex. Polylines are excluded, since revisiting a start
        // vertex without closing is legitimate there (#309).
        const first = activePoints[0];
        if (
          (activeTool === 'area' || activeTool === 'volume') &&
          activePoints.length >= 3 &&
          first &&
          point.x === first.x &&
          point.y === first.y
        ) {
          handleCanvasDblClickRef.current?.();
          return;
        }
      } else if (
        !settingScale &&
        (orthoLock || shiftHeldRef.current) &&
        activePoints.length > 0 &&
        (activeTool === 'distance' ||
          activeTool === 'polyline' ||
          activeTool === 'area' ||
          activeTool === 'volume' ||
          activeTool === 'cloud' ||
          activeTool === 'arrow')
      ) {
        point = orthoSnap(activePoints[activePoints.length - 1]!, point);
      }

      // Setting scale mode (legacy meters-only dialog OR new calibration).
      if (settingScale) {
        // Square the second calibration point against the first when the ortho
        // lock is engaged, so calibrating along a known horizontal / vertical
        // dimension line is exact (issue #343). Matches the live preview line.
        const calPoint =
          scalePoints.length === 1 && (orthoLock || shiftHeldRef.current)
            ? orthoSnap(scalePoints[0]!, point)
            : point;
        const newPoints = [...scalePoints, calPoint];
        setScalePoints(newPoints);
        if (newPoints.length === 2) {
          const np0 = newPoints[0]!;
          const np1 = newPoints[1]!;
          const dist = pixelDistance(np0.x, np0.y, np1.x, np1.y);
          setSettingScale(false);
          // The pick is done: clear the live preview so no rubber-band / snap
          // ring is left frozen behind the calibration dialog (#367).
          setLiveCursor(null);
          setSnapPoint(null);
          if (calibrationMode) {
            // Route to the new multi-unit calibration dialog.
            setCalibrationPixels(dist);
            setCalibrationMode(false);
            setShowCalibrationDialog(true);
          } else {
            setScaleRefPixels(dist);
            setShowScaleDialog(true);
          }
        }
        return;
      }

      // Count by example: once "Count similar" is armed, the next click picks
      // the seed symbol and the server returns every near-identical one. This
      // takes precedence over the active drawing tool, and runs through refs so
      // the click handler stays out of the async flow's dependency list.
      if (armCountSimilarRef.current) {
        armCountSimilarRef.current = false;
        handleCountByExampleSeedRef.current?.(point);
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
            return prev.map((m) => {
              if (m.id !== existing.id) return m;
              // Derive value from the *appended* array, never
              // `m.points.length + 1`: under React 18 StrictMode /
              // batched concurrent updates the pre-append length can be
              // stale and desync value from points.length (D-TKC-023).
              const nextPoints = [...m.points, point];
              return { ...m, points: nextPoints, value: nextPoints.length };
            });
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

      if (activeTool === 'rectarea') {
        if (!rectStartPoint) {
          // First click — set the start corner.
          setRectStartPoint(point);
          setActivePoints([point]);
          pushUndo({ kind: 'add_point', tool: activeTool, point });
        } else {
          // Second click — close the rectangle into a measured area polygon.
          // It is stored as a normal `area` measurement so it reuses all the
          // existing area rendering, scale-recompute and BOQ-link plumbing.
          const a = rectStartPoint;
          const b = point;
          const corners: Point[] = [
            { x: a.x, y: a.y },
            { x: b.x, y: a.y },
            { x: b.x, y: b.y },
            { x: a.x, y: b.y },
          ];
          const pixArea = polygonAreaPixels(corners);
          const realArea = toRealArea(pixArea, scale);
          const perimPx = polygonPerimeterPixels(corners);
          const realPerim = toRealDistance(perimPx, scale);
          const newMeasurement: Measurement = {
            id: `m_${Date.now()}`,
            type: 'area',
            points: corners,
            value: realArea,
            unit: `${scale.unitLabel}²`,
            label: `${formatMeasurement(realArea, scale.unitLabel + '²')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})`,
            annotation: nextAnnotation('area'),
            page: currentPage,
            group: activeGroup,
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
    [activeTool, activePoints, scale, currentPage, countLabel, settingScale, scalePoints, zoom, pushUndo, nextAnnotation, activeGroup, annotationColor, rectStartPoint, orthoLock],
  );

  // Keep the ref in sync so touch handler can call it
  handleCanvasClickRef.current = handleCanvasClick;

  /** Double-click to close an area/volume polygon or finish a polyline */
  const handleCanvasDblClick = useCallback(() => {
    // A double-click fires two click events before this handler, so the last
    // placed vertex is a near-duplicate of the one before it (issue #298a).
    // Drop it in screen space before finalizing, so a polyline has no
    // zero-length tail and an area / volume has no sliver edge. A right-click
    // finish (which reuses this path) has no preceding click, so its last two
    // vertices are meaningfully apart and nothing is trimmed.
    const pts = dropTrailingDuplicateVertex(activePoints, zoom);

    // Polyline: finish with double-click (need at least 2 points)
    if (activeTool === 'polyline' && pts.length >= 2) {
      let totalPx = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        const pa = pts[i]!;
        const pb = pts[i + 1]!;
        totalPx += pixelDistance(pa.x, pa.y, pb.x, pb.y);
      }
      const totalReal = toRealDistance(totalPx, scale);
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'polyline',
        points: [...pts],
        value: totalReal,
        unit: scale.unitLabel,
        label: formatMeasurement(totalReal, scale.unitLabel),
        annotation: nextAnnotation('polyline'),
        page: currentPage,
        group: activeGroup,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...pts] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }

    // Area: close polygon with double-click
    if (activeTool === 'area' && pts.length >= 3) {
      const pixArea = polygonAreaPixels(pts);
      const realArea = toRealArea(pixArea, scale);
      const perimPx = polygonPerimeterPixels(pts);
      const realPerim = toRealDistance(perimPx, scale);
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'area',
        points: [...pts],
        value: realArea,
        unit: `${scale.unitLabel}\u00B2`,
        label: `${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} (P: ${formatMeasurement(realPerim, scale.unitLabel)})`,
        annotation: nextAnnotation('area'),
        page: currentPage,
        group: activeGroup,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...pts] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }

    // Volume: close polygon then prompt for depth
    if (activeTool === 'volume' && pts.length >= 3) {
      setPendingVolumePoints([...pts]);
      setVolumeDepthValue('1');
      setShowVolumeDepthInput(true);
      setActivePoints([]);
      return;
    }

    // Cloud: close cloud polygon with double-click (need at least 3 points)
    if (activeTool === 'cloud' && pts.length >= 3) {
      const newMeasurement: Measurement = {
        id: `m_${Date.now()}`,
        type: 'cloud',
        points: [...pts],
        value: 0,
        unit: '',
        label: '',
        annotation: nextAnnotation('cloud'),
        page: currentPage,
        group: activeGroup,
        color: annotationColor,
      };
      pushUndo({ kind: 'complete_measurement', measurement: newMeasurement, previousActivePoints: [...pts] });
      setMeasurements((prev) => [...prev, newMeasurement]);
      setActivePoints([]);
      return;
    }
  }, [activeTool, activePoints, zoom, scale, currentPage, pushUndo, nextAnnotation, activeGroup, annotationColor]);
  // Expose the finish routine to the earlier-defined click handler so
  // close-on-first-vertex can reuse it without a declaration cycle (#309).
  handleCanvasDblClickRef.current = handleCanvasDblClick;

  /** Confirm volume depth and create the volume measurement */
  const handleVolumeDepthConfirm = useCallback(() => {
    const entered = parseFloat(volumeDepthValue);
    if (isNaN(entered) || entered <= 0 || pendingVolumePoints.length < 3) {
      setShowVolumeDepthInput(false);
      setPendingVolumePoints([]);
      return;
    }
    // The depth is typed in the user's display units (feet in Imperial), but
    // measurements are stored metric-canonical, so convert the entry back to
    // metres before multiplying by the canonical base area (D-TKC-016). This is
    // the one takeoff input that used the raw number as metres, which made an
    // Imperial depth come out about 3.28x too large with no warning (#323).
    const depthUnit: CalibrationUnit = measurementSystem === 'imperial' ? 'ft' : 'm';
    const depth = toMeters(entered, depthUnit);
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
  }, [volumeDepthValue, pendingVolumePoints, scale, currentPage, pushUndo, nextAnnotation, activeGroup, measurementSystem]);

  /** Right-click: finish an in-progress polyline / area / volume / cloud
   *  (reuses the double-click finish, which drops no stray vertex here since no
   *  click precedes the right-click), or, with the select tool, open the
   *  measurement context menu for the shape under the cursor (issue #302). */
  const handleCanvasContextMenu = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (activeTool === 'polyline' && activePoints.length >= 2) {
        e.preventDefault();
        handleCanvasDblClick(); // Reuse the double-click finish logic
      } else if (activeTool === 'area' && activePoints.length >= 3) {
        // Area was missing from the right-click finish (issue #298b).
        e.preventDefault();
        handleCanvasDblClick();
      } else if (activeTool === 'volume' && activePoints.length >= 3) {
        e.preventDefault();
        handleCanvasDblClick();
      } else if (activeTool === 'cloud' && activePoints.length >= 3) {
        e.preventDefault();
        handleCanvasDblClick();
      } else if (activeTool === 'select') {
        // Open a context menu for the measurement under the cursor. The hover
        // hit-test (mouse move) already tracks it, so no re-hit-test is needed.
        const targetId = hoverInfoRef.current?.measurementId;
        if (targetId) {
          e.preventDefault();
          setSelectedMeasurementId(targetId);
          setContextMenu({ x: e.clientX, y: e.clientY, measurementId: targetId });
        } else {
          setContextMenu(null);
        }
      } else {
        // Prevent the native context menu while using the other measurement tools.
        e.preventDefault();
      }
    },
    [activeTool, activePoints, handleCanvasDblClick],
  );

  /* ── In-canvas editing: live values read through refs ─────────────────
   * The drag handlers must read the latest measurements / selection /
   * scale / zoom without re-subscribing (a re-created handler mid-drag
   * would drop the window mouseup listener). Mirror the few values they
   * need into refs that the render keeps current. */
  const measurementsRef = useRef(measurements);
  measurementsRef.current = measurements;
  const editScaleRef = useRef(scale);
  editScaleRef.current = scale;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const currentPageRef = useRef(currentPage);
  currentPageRef.current = currentPage;
  const hiddenGroupsRef = useRef(hiddenGroups);
  hiddenGroupsRef.current = hiddenGroups;
  const hiddenMeasurementsRef = useRef(hiddenMeasurements);
  hiddenMeasurementsRef.current = hiddenMeasurements;
  const selectedMeasurementIdRef = useRef(selectedMeasurementId);
  selectedMeasurementIdRef.current = selectedMeasurementId;

  /** Convert a pointer event to PDF user units. Mirrors the create-path
   *  inversion exactly: divide by `zoom` only, never by `dpr` (the overlay
   *  CSS box is already `viewport.width / dpr`). */
  const pointerToPdf = useCallback((e: { clientX: number; clientY: number }): Point | null => {
    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const z = zoomRef.current || 1;
    return { x: (e.clientX - rect.left) / z, y: (e.clientY - rect.top) / z };
  }, []);

  /** Measurements visible on the current page (z-order = draw order), used
   *  for select-mode hit-testing. Last drawn is on top, so we scan in
   *  reverse for the topmost hit. Excludes hidden groups + AI suggestions
   *  (those have their own accept/reject affordances). */
  const editableOnPage = useCallback((): Measurement[] => {
    const page = currentPageRef.current;
    const hidden = hiddenGroupsRef.current;
    const hiddenM = hiddenMeasurementsRef.current;
    return measurementsRef.current.filter(
      (m) =>
        m.page === page &&
        !m.suggested &&
        !hidden.has(m.group) &&
        // A hidden measurement stops intercepting clicks too (#359).
        !hiddenM.has(m.id) &&
        !(isAnnotationType(m.type) && hidden.has('__annotations__')),
    );
  }, []);

  /** Apply a committed geometry edit to a measurement: recompute its value
   *  + label from the new points and push an undo frame. */
  const commitGeometryEdit = useCallback(
    (id: string, original: Measurement, nextPoints: Point[]) => {
      setMeasurements((prev) => {
        let nextSnapshot: Measurement | null = null;
        const updated = prev.map((m) => {
          if (m.id !== id) return m;
          const patch = recomputeMeasurement(m, nextPoints, editScaleRef.current);
          const next: Measurement = {
            ...m,
            points: nextPoints,
            value: patch.value,
            label: patch.label,
            unit: patch.unit ?? m.unit,
            ...(patch.area !== undefined ? { area: patch.area } : {}),
            ...(patch.width !== undefined ? { width: patch.width } : {}),
            ...(patch.height !== undefined ? { height: patch.height } : {}),
          };
          nextSnapshot = next;
          return next;
        });
        if (nextSnapshot) {
          pushUndo({
            kind: 'edit_geometry',
            measurementId: id,
            previousMeasurement: { ...original, points: [...original.points] },
            nextMeasurement: { ...(nextSnapshot as Measurement), points: [...nextPoints] },
          });
        }
        return updated;
      });
    },
    [pushUndo],
  );

  /** End any active drag, committing or aborting. */
  const finishDrag = useCallback(
    (commit: boolean) => {
      const drag = dragRef.current;
      dragRef.current = null;
      setDragPreview(null);
      if (!drag) return;
      const live = measurementsRef.current.find((m) => m.id === drag.measurementId);
      if (!live) return;
      if (commit && drag.moved) {
        // The committed geometry is the last dragged points (state only
        // holds the pre-drag copy mid-drag), recomputed server-side on PATCH.
        commitGeometryEdit(drag.measurementId, drag.original, drag.lastPoints);
      } else if (!commit) {
        // Abort: restore the pre-drag geometry, no undo frame.
        setMeasurements((prev) =>
          prev.map((m) =>
            m.id === drag.measurementId
              ? { ...drag.original, points: [...drag.original.points] }
              : m,
          ),
        );
      }
    },
    [commitGeometryEdit],
  );

  /** Mouse-down on the overlay in select mode: hit-test, select, and arm a
   *  drag. The vertex / edge-midpoint / body matrix follows the #194
   *  design. */
  const handleCanvasMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      // Track the primary press for the duration it is held (#356). A fresh
      // press also clears any suppression left set by a previous press that
      // ended off-canvas, so it cannot swallow this press's own click.
      if (e.button === 0) {
        pressActiveRef.current = true;
        suppressNextClickRef.current = false;
      }
      // Pan gesture: middle mouse (button 1) anywhere, or left-drag while the
      // Space bar is held. Works in any tool and is captured before tool logic
      // so it never places a measurement. The actual move + release are driven
      // by window listeners so a pan that leaves the canvas still tracks.
      if (e.button === 1 || (e.button === 0 && (spaceHeldRef.current || panLockRef.current))) {
        const c = containerRef.current;
        if (c) {
          panRef.current = {
            startX: e.clientX,
            startY: e.clientY,
            scrollLeft: c.scrollLeft,
            scrollTop: c.scrollTop,
          };
          setPanning(true);
          e.preventDefault();
        }
        return;
      }
      if (activeTool !== 'select' || e.button !== 0) return;
      const pt = pointerToPdf(e);
      if (!pt) return;
      const z = zoomRef.current || 1;
      const onPage = editableOnPage();
      const selId = selectedMeasurementIdRef.current;

      // Prefer the already-selected measurement so its handles win even when
      // another shape overlaps; otherwise scan top-to-bottom (reverse z).
      const ordered: Measurement[] = [];
      const sel = onPage.find((m) => m.id === selId);
      if (sel) ordered.push(sel);
      for (let i = onPage.length - 1; i >= 0; i--) {
        const m = onPage[i]!;
        if (m.id !== selId) ordered.push(m);
      }

      for (const m of ordered) {
        const isSel = m.id === selId;
        const hit: HitResult | null = hitTest(pt, m, z, isSel);
        if (!hit) continue;

        if (m.id !== selId) setSelectedMeasurementId(m.id);

        // A reshape is about to be armed below. Drop the hover card now, or it
        // stays frozen on top of the vertex being dragged: handleCanvasMouseMove
        // returns early while dragRef is set, so it never refreshes the card's
        // position during the drag (issue #353). Clearing it here rather than in
        // that move branch is deliberate: dragRef is armed on this mousedown, so
        // a press held (or pressed and released) without moving never reaches the
        // move handler and would otherwise leave the card stranded.
        setHoverInfo(null);

        if (hit.kind === 'vertex') {
          activeVertexRef.current = { measurementId: m.id, index: hit.index };
          dragRef.current = {
            mode: 'vertex',
            measurementId: m.id,
            original: { ...m, points: [...m.points] },
            origPoints: [...m.points],
            vertexIndex: hit.index,
            startPt: pt,
            moved: false,
            lastPoints: [...m.points],
          };
        } else if (hit.kind === 'edge' && supportsVariableVertices(m.type)) {
          // Insert a vertex at the segment midpoint and immediately drag it.
          const grown = insertVertexAt(m.points, hit.index);
          const newIndex = hit.index + 1;
          activeVertexRef.current = { measurementId: m.id, index: newIndex };
          dragRef.current = {
            mode: 'vertex',
            measurementId: m.id,
            original: { ...m, points: [...m.points] },
            origPoints: grown,
            vertexIndex: newIndex,
            startPt: pt,
            moved: true, // adding a vertex is itself an edit worth committing
            lastPoints: grown,
          };
          // Reflect the inserted vertex immediately so the drag has a handle.
          setMeasurements((prev) =>
            prev.map((x) => (x.id === m.id ? { ...x, points: grown } : x)),
          );
        } else {
          // body / interior -> translate the whole shape.
          activeVertexRef.current = null;
          dragRef.current = {
            mode: 'shape',
            measurementId: m.id,
            original: { ...m, points: [...m.points] },
            origPoints: [...m.points],
            vertexIndex: -1,
            startPt: pt,
            moved: false,
            lastPoints: [...m.points],
          };
        }
        e.preventDefault();
        return;
      }

      // Clicked empty space: deselect + clear any active vertex.
      activeVertexRef.current = null;
      if (selId) setSelectedMeasurementId(null);
    },
    [activeTool, pointerToPdf, editableOnPage],
  );

  /** Mouse-move while an in-canvas edit drag is active. Updates the live
   *  preview only (no setMeasurements, no network) until mouseup. */
  const handleEditDragMove = useCallback(
    (e: { clientX: number; clientY: number }) => {
      const drag = dragRef.current;
      if (!drag) return;
      const cur = pointerToPdf(e);
      if (!cur) return;
      // The ortho lock constrains edits too, not only drawing (issue #343):
      // squaring an existing edge on a vertex drag, or sliding a whole
      // measurement onto a 0 / 45 / 90 axis. Same trigger as the draw path.
      const ortho = orthoLock || shiftHeldRef.current;
      let next: Point[];
      if (drag.mode === 'vertex') {
        // Square the dragged vertex against its neighbour edge(s). Closed shapes
        // (area / volume / cloud) wrap around; open runs and the arrow anchor on
        // the adjacent vertex only. A count is a single point and the rectangle /
        // highlight boxes are two-corner, so neither has a vertex chain to square
        // and both stay freehand.
        const dm = measurementsRef.current.find((x) => x.id === drag.measurementId);
        const dt = dm?.type;
        const orthoVertex =
          dt === 'distance' ||
          dt === 'polyline' ||
          dt === 'area' ||
          dt === 'volume' ||
          dt === 'cloud' ||
          dt === 'arrow';
        const vpt =
          ortho && orthoVertex
            ? orthoSnapVertexDrag(
                drag.origPoints,
                drag.vertexIndex,
                cur,
                dt === 'area' || dt === 'volume' || dt === 'cloud',
              )
            : cur;
        next = drag.origPoints.map((p, i) => (i === drag.vertexIndex ? vpt : p));
      } else {
        // Constrain the whole-measurement move by snapping the translation
        // VECTOR (anchored at the drag start), so the shape slides along an axis
        // without being reshaped.
        const tip = ortho ? orthoSnap(drag.startPt, cur) : cur;
        next = translatePoints(drag.origPoints, tip.x - drag.startPt.x, tip.y - drag.startPt.y);
      }
      drag.moved = true;
      drag.lastPoints = next;
      const m = measurementsRef.current.find((x) => x.id === drag.measurementId);
      const patch = m
        ? recomputeMeasurement(m, next, editScaleRef.current)
        : { value: 0, label: '', selfIntersecting: false };
      setDragPreview({
        measurementId: drag.measurementId,
        points: next,
        label: patch.label,
        selfIntersecting: Boolean(patch.selfIntersecting),
        // Carry the recompute result so the render can repoint the band and its
        // value label to the live geometry (#357), instead of discarding it.
        patch,
      });
    },
    [pointerToPdf, orthoLock],
  );

  /* ── Mouse move: edit drag, rect preview, live readout, hover ─────── */

  const handleCanvasMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      // A pan in progress is driven by the window listener; ignore here.
      if (panRef.current) return;
      if (dragRef.current) {
        handleEditDragMove(e);
        return;
      }
      const pt = pointerToPdf(e);

      // Calibration live preview (issue #343): while placing the second scale
      // point, track the cursor (ortho-snapped against the first point when the
      // lock is engaged) so the render rubber-bands the scale line and the pick
      // is WYSIWYG. Calibration owns the cursor, so skip the measure-tool
      // readout and hover below.
      if (settingScale) {
        if (pt && scalePoints.length === 1) {
          const a = scalePoints[0]!;
          setLiveCursor(orthoLock || shiftHeldRef.current ? orthoSnap(a, pt) : pt);
        } else if (liveCursor) {
          setLiveCursor(null);
        }
        return;
      }

      if ((activeTool === 'rectangle' || activeTool === 'highlight' || activeTool === 'rectarea') && rectStartPoint) {
        if (!pt) return;
        setActivePoints([pt]);
        setIsDraggingRect(true);
        return;
      }

      // Live readout: track the cursor (snapped against a nearby existing
      // vertex when vertex snap is on, else ortho-snapped against the last
      // placed point when the lock is engaged) while a linear / polygon measure
      // tool is active, so the HUD shows the running segment + cumulative
      // length and the rubber-band follows the same point a click will place.
      if (
        pt &&
        (activeTool === 'distance' ||
          activeTool === 'polyline' ||
          activeTool === 'area' ||
          activeTool === 'volume')
      ) {
        // Vertex snap wins over ortho (issue #303): connecting to an existing
        // corner is a stronger intent than an angle constraint. The shape's own
        // placed vertices (minus the immediately preceding point) join the pool
        // so the snap ring shows on the first vertex too, cueing a close (#309).
        const hoverSnapPool =
          activePoints.length > 1
            ? [...snapVerticesRef.current, ...activePoints.slice(0, -1)]
            : snapVerticesRef.current;
        const vsnap = vertexSnapRef.current
          ? snapToVertex(pt, hoverSnapPool, zoomRef.current || 1, VERTEX_SNAP_SCREEN_PX)
          : null;
        if (vsnap) {
          setSnapPoint(vsnap);
          setLiveCursor(vsnap);
        } else {
          setSnapPoint((cur) => (cur ? null : cur));
          const anchor = activePoints[activePoints.length - 1];
          const snapped =
            anchor && (orthoLock || shiftHeldRef.current) ? orthoSnap(anchor, pt) : pt;
          setLiveCursor(snapped);
        }
      } else {
        if (liveCursor) setLiveCursor(null);
        setSnapPoint((cur) => (cur ? null : cur));
      }

      // Hover tooltip: in select mode, surface the topmost measurement under
      // the cursor (value / group / linked BOQ). Reuses the same hit-test the
      // selection path uses so the hover target matches what a click selects.
      if (activeTool === 'select' && pt) {
        const z = zoomRef.current || 1;
        const onPage = editableOnPage();
        let foundId: string | null = null;
        for (let i = onPage.length - 1; i >= 0; i--) {
          const m = onPage[i]!;
          if (hitTest(pt, m, z, m.id === selectedMeasurementIdRef.current)) {
            foundId = m.id;
            break;
          }
        }
        if (foundId) {
          const rect = overlayRef.current?.getBoundingClientRect();
          setHoverInfo({
            measurementId: foundId,
            x: rect ? e.clientX - rect.left : pt.x * z,
            y: rect ? e.clientY - rect.top : pt.y * z,
          });
        } else if (hoverInfo) {
          setHoverInfo(null);
        }
      } else if (hoverInfo) {
        setHoverInfo(null);
      }
    },
    [activeTool, rectStartPoint, pointerToPdf, handleEditDragMove, activePoints, orthoLock, liveCursor, editableOnPage, hoverInfo, settingScale, scalePoints],
  );

  /** Clear the transient HUD / hover state when the pointer leaves the canvas. */
  const handleCanvasMouseLeave = useCallback(() => {
    if (liveCursor) setLiveCursor(null);
    if (hoverInfo) setHoverInfo(null);
    setSnapPoint((cur) => (cur ? null : cur));
  }, [liveCursor, hoverInfo]);

  const handleCanvasMouseUp = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    // The primary press ended (#356). A release outside the canvas is caught by
    // the window mouseup listener below instead.
    if (e.button === 0) pressActiveRef.current = false;
    if (dragRef.current) finishDrag(true);
  }, [finishDrag]);

  /* ── Window listeners so a drag that leaves the canvas still commits ──
   * Without these, releasing the mouse outside the overlay (common at the
   * edges of a large drawing) would leave the shape stuck in preview. */
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      // Pan takes priority: translate scroll by the pointer delta. Scrolling
      // the container directly (not via state) keeps the pan smooth.
      const pan = panRef.current;
      if (pan) {
        const c = containerRef.current;
        if (c) {
          c.scrollLeft = pan.scrollLeft - (e.clientX - pan.startX);
          c.scrollTop = pan.scrollTop - (e.clientY - pan.startY);
        }
        return;
      }
      if (dragRef.current) handleEditDragMove(e);
    };
    const onUp = (e: MouseEvent) => {
      // Catches a primary release outside the canvas, where no React mouseup or
      // click fires (#356).
      if (e.button === 0) pressActiveRef.current = false;
      if (panRef.current) {
        panRef.current = null;
        setPanning(false);
        return;
      }
      if (dragRef.current) finishDrag(true);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [handleEditDragMove, finishDrag]);

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

  /* ── Calibration (two-click → unit picker) ───────────────────────── */

  /** Arm the calibration pick-mode.  The next two canvas clicks define
   *  the reference segment; the CalibrationDialog then opens. */
  const handleStartCalibration = useCallback(() => {
    setCalibrationMode(true);
    setSettingScale(true);
    setScalePoints([]);
    // Drop any draw-tool live preview so no rubber-band / snap ring from an
    // in-progress measurement tracks the calibration cursor or lingers (#367).
    setLiveCursor(null);
    setSnapPoint(null);
  }, []);

  /** User confirmed the calibration dialog — persist the new scale.
   *
   *  `nextScale` is metric-canonical (label always `'m'`).  `entry` echoes
   *  what the estimator actually typed (e.g. `10 ft`); we badge that unit
   *  rather than a bare `'m'` so a feet/inches calibration is no longer
   *  silently relabelled (D-TKC-016).  The metres value is also shown so
   *  it's clear the conversion was honoured. */
  const handleCalibrationConfirm = useCallback(
    (nextScale: ScaleConfig, entry?: { realLength: number; unit: CalibrationUnit }) => {
      // setScale targets the CURRENT page; that also marks the page as
      // calibrated (isCalibrated derives from pageIsCalibrated).
      const page = currentPage;
      setScale(nextScale);
      setShowCalibrationDialog(false);
      setScalePoints([]);
      const meters = calibrationPixels > 0 ? calibrationPixels / nextScale.pixelsPerUnit : 0;
      // Prefer the user's own entry/unit; fall back to derived metres.
      const badge = entry ?? { realLength: meters, unit: 'm' as const };
      setLastCalibrationByPage((prev) => ({ ...prev, [page]: badge }));
      const metricSuffix =
        badge.unit === 'm' ? '' : ` (${meters.toFixed(2)} m)`;
      addToast({
        type: 'success',
        title: t('takeoff_viewer.calibrated', { defaultValue: 'Scale calibrated' }),
        message: `${formatScaleRatio(nextScale)} · ${badge.realLength} ${badge.unit}${metricSuffix} · ${t('takeoff_viewer.calibrated_page', { defaultValue: 'page {{page}}', page })}`,
      });
    },
    [addToast, t, calibrationPixels, currentPage, setScale],
  );

  const handleCalibrationCancel = useCallback(() => {
    setShowCalibrationDialog(false);
    setScalePoints([]);
    setLiveCursor(null);
    setSnapPoint(null);
  }, []);

  /* ── Recalculate measurements when a PAGE'S scale changes ─────────────
   * Per-page scale (per sheet) means a calibration on page 3 must re-derive
   * only page-3 measurements, each against page 3's scale - not the whole
   * document against one global scale. We diff the previous vs current
   * ``pageScales`` and recompute every measurement whose OWN page's
   * effective scale moved, using that page's old scale (to re-project
   * volume depth) and new scale (for area / length). */

  const pageScalesRef = useRef(pageScales);
  useEffect(() => {
    const prevPS = pageScalesRef.current;
    pageScalesRef.current = pageScales;
    // Issue #333: a load-time hydrate is a reconciliation, not a recalibration.
    // Consume the skip flag unconditionally (so a no-op transition can never
    // leave it set to wrongly skip a LATER real recalibration), then skip the
    // recompute for exactly the hydrate transition. Skipping keeps a stored
    // volume's typed depth from being re-projected through the factory-default
    // ratio (which corrupted it and, via the server recompute, the volume). The
    // ref above is already advanced to the hydrated value, so a genuine user
    // recalibration afterwards diffs against the correct baseline and still
    // re-projects depth.
    const skipRecompute = skipScaleRecomputeRef.current;
    skipScaleRecomputeRef.current = false;
    if (prevPS === pageScales) return;
    if (skipRecompute) return;
    setMeasurements((ms) =>
      ms.map((m) => {
        if (m.type === 'count') return m; // counts are scale-independent
        if (isAnnotationType(m.type)) return m; // annotations are scale-independent
        // Each measurement uses ITS page's scale, old vs new. Skip rows on
        // pages whose effective scale did not change so we never churn a
        // sheet the user did not touch.
        const prev = scaleForPage(prevPS, m.page);
        const scale = scaleForPage(pageScales, m.page);
        if (prev.pixelsPerUnit === scale.pixelsPerUnit) return m;
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
          // The polygon points are scale-independent (PDF user units), so
          // ``realArea`` is freshly correct.  But ``m.depth`` is a stored
          // real-world length captured against the PREVIOUS scale's unit.
          // Multiplying the new-scale area by the old-scale depth produces
          // a mixed-scale volume (D-TKC-020).  Re-project the depth through
          // pixel space the same way the area is: old real \u2192 pixels via the
          // previous ppu, pixels \u2192 new real via the current ppu.  When the
          // previous scale was invalid (ppu <= 0) there is no meaningful
          // factor, so keep the stored depth as-is rather than zeroing it.
          const rescaledDepth =
            prev.pixelsPerUnit > 0 && scale.pixelsPerUnit > 0
              ? (m.depth * prev.pixelsPerUnit) / scale.pixelsPerUnit
              : m.depth;
          const volume = realArea * rescaledDepth;
          return {
            ...m,
            value: volume,
            area: realArea,
            depth: rescaledDepth,
            unit: `${scale.unitLabel}\u00B3`,
            label: `V = ${formatMeasurement(volume, scale.unitLabel + '\u00B3')} (A: ${formatMeasurement(realArea, scale.unitLabel + '\u00B2')} \u00D7 D: ${formatMeasurement(rescaledDepth, scale.unitLabel)})`,
          };
        }
        return m;
      }),
    );
  }, [pageScales]);

  /* ── Zoom controls ───────────────────────────────────────────────── */

  const zoomIn = useCallback(() => setZoom((z) => clampZoom(z * 1.25)), []);
  const zoomOut = useCallback(() => setZoom((z) => clampZoom(z / 1.25)), []);

  /** Current page size in PDF user units, derived from the rendered canvas:
   *  `canvas.width = pageWidthPdfUnits * zoom * dpr`, so we invert that. The
   *  page only changes size between pages / re-renders, so reading it off the
   *  live canvas avoids holding a second source of truth. Returns null before
   *  the first render. */
  const pageSizePdf = useCallback((): { width: number; height: number } | null => {
    const canvas = canvasRef.current;
    if (!canvas || canvas.width === 0) return null;
    const dpr = window.devicePixelRatio || 1;
    const z = zoomRef.current || 1;
    return {
      width: canvas.width / (z * dpr),
      height: canvas.height / (z * dpr),
    };
  }, []);

  /** Inner (content) size of the scroll container in CSS px. */
  const viewportSize = useCallback((): { width: number; height: number } => {
    const c = containerRef.current;
    return { width: c?.clientWidth ?? 0, height: c?.clientHeight ?? 0 };
  }, []);

  /** Fit the page to the viewport for a mode, re-anchoring scroll to the
   *  top-left (width fit) / center (page fit) so the result is framed. */
  const fitToViewport = useCallback(
    (mode: 'width' | 'page') => {
      const page = pageSizePdf();
      if (!page) return;
      const vp = viewportSize();
      const next = computeFitZoom(page.width, page.height, vp.width, vp.height, mode);
      setZoom(next);
      // After the canvas re-lays-out at the new zoom, reset scroll so the page
      // origin is visible (width) or the page is centered (page fit).
      requestAnimationFrame(() => {
        const c = containerRef.current;
        if (!c) return;
        if (mode === 'width') {
          c.scrollLeft = 0;
          c.scrollTop = 0;
        } else {
          // Center the (now fully visible) page in the viewport.
          c.scrollLeft = Math.max(0, (page.width * next - c.clientWidth) / 2);
          c.scrollTop = Math.max(0, (page.height * next - c.clientHeight) / 2);
        }
      });
    },
    [pageSizePdf, viewportSize],
  );

  const zoomFit = useCallback(() => fitToViewport('page'), [fitToViewport]);

  /** Zoom + pan so the selected measurement(s) on the current page fill the
   *  viewport with a margin. No-op (with a hint toast) when nothing on the
   *  current page is selected. */
  const zoomToSelection = useCallback(() => {
    const selId = selectedMeasurementIdRef.current;
    const sel = measurementsRef.current.find(
      (m) => m.id === selId && m.page === currentPageRef.current,
    );
    if (!sel || sel.points.length === 0) {
      addToast({
        type: 'info',
        title: t('takeoff_viewer.zoom_selection_none', { defaultValue: 'Select a measurement first' }),
      });
      return;
    }
    const box = boundingBoxOfPoints(sel.points);
    if (!box) return;
    const vp = viewportSize();
    const res = computeZoomToBox(box, vp.width, vp.height, {
      fallbackZoom: zoomRef.current || 1,
    });
    setZoom(res.zoom);
    requestAnimationFrame(() => {
      const c = containerRef.current;
      if (!c) return;
      c.scrollLeft = res.scrollLeft;
      c.scrollTop = res.scrollTop;
    });
  }, [viewportSize, addToast, t]);

  /* ── Find on sheet: debounced text-layer scan ─────────────────────────
   * On a (trimmed) query, scan every page's pdf.js text layer for matches,
   * caching the placed text items per page so re-searching is instant. The
   * cap (FIND_MATCH_CAP) keeps the result list and the highlight loop bounded
   * on a large set. Bails and clears on an empty query / closed panel. */
  const FIND_MATCH_CAP = 500;
  useEffect(() => {
    const q = searchQuery.trim();
    if (!pdfDoc || !searchOpen || q.length === 0) {
      setSearchMatches([]);
      setActiveMatchIdx(-1);
      setSearchBusy(false);
      return;
    }
    let cancelled = false;
    setSearchBusy(true);
    const handle = window.setTimeout(() => {
      (async () => {
        const all: TextMatch[] = [];
        try {
          for (let n = 1; n <= totalPages; n++) {
            if (cancelled) return;
            let items = textLayerCacheRef.current.get(n);
            if (!items) {
              const page = await pdfDoc.getPage(n);
              if (cancelled) return;
              const vp = page.getViewport({ scale: 1 }); // PDF-unit space
              const content = await page.getTextContent();
              if (cancelled) return;
              // pdf.js items are TextItem | TextMarkedContent; the helper reads
              // them structurally and skips markers (no transform).
              items = itemsFromTextContent(
                content.items as unknown as Parameters<typeof itemsFromTextContent>[0],
                vp.height,
              );
              textLayerCacheRef.current.set(n, items);
            }
            const hits = findMatchesInPage(items, q, n, all.length);
            for (const h of hits) {
              all.push(h);
              if (all.length >= FIND_MATCH_CAP) break;
            }
            if (all.length >= FIND_MATCH_CAP) break;
          }
        } catch {
          /* a cancelled / failed text-layer read: surface what we found */
        }
        if (cancelled) return;
        setSearchMatches(all);
        setActiveMatchIdx(all.length ? 0 : -1);
        setSearchBusy(false);
      })();
    }, 250);
    return () => { cancelled = true; window.clearTimeout(handle); };
  }, [pdfDoc, searchOpen, searchQuery, totalPages]);

  /** Jump to (and highlight) a match: flip to its page if needed, frame its
   *  box with the existing zoom-to-box machinery, then apply the scroll once
   *  the canvas has re-laid-out. The fit zoom is capped so a single short word
   *  does not slam the page to 400%. */
  const goToMatch = useCallback(
    (i: number) => {
      const match = searchMatches[i];
      if (!match) return;
      setActiveMatchIdx(i);
      const pageChanged = match.page !== currentPageRef.current;
      if (pageChanged) setCurrentPage(match.page);
      const apply = () => {
        const vp = viewportSize();
        if (vp.width === 0 || vp.height === 0) return;
        const res = computeZoomToBox(match.box, vp.width, vp.height, {
          marginFraction: 0.6, // keep some context around a small word
          fallbackZoom: zoomRef.current || 1,
        });
        // Cap the fit at 3x so a tiny word does not slam the page to 400%, but
        // never zoom OUT below the current view just to frame a match.
        const cappedZoom = Math.max(Math.min(res.zoom, 3), zoomRef.current || 1);
        setZoom(cappedZoom);
        requestAnimationFrame(() => {
          const c = containerRef.current;
          if (!c) return;
          // Recompute scroll for the (possibly capped) zoom so the box centers.
          const midX = (match.box.minX + match.box.maxX) / 2;
          const midY = (match.box.minY + match.box.maxY) / 2;
          c.scrollLeft = Math.max(0, midX * cappedZoom - vp.width / 2);
          c.scrollTop = Math.max(0, midY * cappedZoom - vp.height / 2);
        });
      };
      // When the page changes the canvas re-renders asynchronously; defer a
      // frame (twice) so the new page has laid out before we scroll to the box.
      if (pageChanged) {
        requestAnimationFrame(() => requestAnimationFrame(apply));
      } else {
        apply();
      }
    },
    [searchMatches, viewportSize],
  );

  /** Step to the next / previous match (wraps), used by the panel buttons and
   *  the Enter / Shift+Enter shortcuts inside the search input. */
  const stepMatch = useCallback(
    (dir: 1 | -1) => {
      const count = searchMatches.length;
      if (count === 0) return;
      const base = activeMatchIdx < 0 ? (dir === 1 ? -1 : 0) : activeMatchIdx;
      const next = (base + dir + count) % count;
      goToMatch(next);
    },
    [searchMatches.length, activeMatchIdx, goToMatch],
  );

  /** Live readout (cursor coordinate + running / cumulative length) for the
   *  HUD shown while a linear / polygon measure tool is active. Null when no
   *  such tool is drawing so the HUD hides. */
  const drawReadout: DrawReadout | null = useMemo(() => {
    if (
      settingScale ||
      !liveCursor ||
      !(activeTool === 'distance' || activeTool === 'polyline' || activeTool === 'area' || activeTool === 'volume')
    ) {
      return null;
    }
    return computeDrawReadout(activePoints, liveCursor, scale);
  }, [settingScale, liveCursor, activeTool, activePoints, scale]);

  /** The measurement currently hovered in select mode (for the tooltip). */
  const hoverMeasurement = useMemo(
    () => (hoverInfo ? measurements.find((m) => m.id === hoverInfo.measurementId) ?? null : null),
    [hoverInfo, measurements],
  );

  // Mouse-wheel zoom on the canvas container. Native listener with
  // `{ passive: false }` so we can preventDefault — React's synthetic
  // onWheel binds passive in v17+ which silently ignores preventDefault.
  // Zoom anchors at the cursor (CAD-standard): the world point under the
  // cursor stays put while we rescale, by adjusting scrollLeft/Top.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = container.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      setZoom((prev) => {
        const next = wheelZoomStep(prev, e.deltaY);
        if (next === prev) return prev;
        // Re-anchor scroll on next frame so the new canvas size is laid out;
        // keeps the world point under the cursor stationary (shared maths).
        requestAnimationFrame(() => {
          if (containerRef.current) {
            const { scrollLeft, scrollTop } = zoomAtCursorScroll(
              prev,
              next,
              container.scrollLeft,
              container.scrollTop,
              cx,
              cy,
            );
            containerRef.current.scrollLeft = scrollLeft;
            containerRef.current.scrollTop = scrollTop;
          }
        });
        return next;
      });
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, []);

  /* ── Page navigation ─────────────────────────────────────────────── */

  const prevPage = useCallback(() => setCurrentPage((p) => Math.max(p - 1, 1)), []);
  // BUG-fix: totalPages MUST be a dependency.  With `[]` the callback was
  // captured on first render when totalPages=0, so Math.min(p+1, 0) clamped
  // every "next" click to 0 — surfacing as "0/31" in the page indicator
  // and an empty Measurements list (no measurement has page=0).
  const nextPage = useCallback(
    () =>
      setCurrentPage((p) =>
        totalPages > 0 ? Math.min(p + 1, totalPages) : p,
      ),
    [totalPages],
  );

  /* ── Measurement summary ─────────────────────────────────────────── */

  const pageMeasurements = useMemo(
    () => measurements.filter((m) => m.page === currentPage),
    [measurements, currentPage],
  );

  /** Measurement count per 1-indexed page, for the thumbnail badge and the
   *  page-jump dropdown (both read the same memo so they never disagree). */
  const countsByPage = useMemo(
    () => countMeasurementsByPage(measurements),
    [measurements],
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

  /** Summaries for the color-coded legend overlay (bottom-left of canvas). */
  const legendSummaries = useMemo(
    () => computeGroupSummaries(
      pageMeasurements.filter((m) => !hiddenGroups.has(m.group) && !hiddenMeasurements.has(m.id)),
      groupColorMap,
    ),
    [pageMeasurements, hiddenGroups, hiddenMeasurements, groupColorMap],
  );

  /* ── Draggable legend (#358) ─────────────────────────────────────── */

  // Persist the position as a workspace preference; clear it on reset.
  useEffect(() => {
    try {
      if (legendPos) window.localStorage.setItem(LEGEND_POS_KEY, JSON.stringify(legendPos));
      else window.localStorage.removeItem(LEGEND_POS_KEY);
    } catch {
      /* ignore unavailable storage */
    }
  }, [legendPos]);

  /** Clamp a position so the legend stays fully inside the wrapper on BOTH
   *  bounds (a stored value can be negative; the wrapper resizes with the
   *  sidebar / thumbnail-strip toggles, which never resize the window). */
  const clampLegend = useCallback((pos: { x: number; y: number }) => {
    const vp = legendViewportRef.current;
    const el = legendElRef.current;
    if (!vp || !el) return pos;
    const vpRect = vp.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const maxX = Math.max(0, vpRect.width - elRect.width);
    const maxY = Math.max(0, vpRect.height - elRect.height);
    return {
      x: Math.min(Math.max(0, pos.x), maxX),
      y: Math.min(Math.max(0, pos.y), maxY),
    };
  }, []);

  /** Re-clamp the current position, bailing out when it does not move so a
   *  resize does not spin re-renders. */
  const reclampLegend = useCallback(() => {
    setLegendPos((cur) => {
      if (!cur) return cur;
      const c = clampLegend(cur);
      return c.x === cur.x && c.y === cur.y ? cur : c;
    });
  }, [clampLegend]);

  /** Tear down an in-flight legend drag - shared by mouseup, window blur, and
   *  the legend unmounting mid-drag. */
  const endLegendDrag = useCallback(() => {
    const d = legendDragRef.current;
    if (!d) return;
    window.removeEventListener('mousemove', d.onMove);
    window.removeEventListener('mouseup', d.onUp);
    window.removeEventListener('blur', d.onUp);
    legendDragRef.current = null;
  }, []);

  /** Stable ref callback for the legend box. Clamps the stored position as the
   *  element attaches (it only mounts once there is something to list, so a
   *  clamp keyed on the position alone would run while the legend is still
   *  absent), and observes both the viewport and the legend so a resize
   *  re-clamps it. It MUST be a stable useCallback, not an inline arrow: React
   *  calls an inline ref with null on every re-render, and the legend re-renders
   *  on every drag mousemove, so an inline ref would fire the unmount teardown
   *  on the first pixel of movement and the legend would be undraggable. */
  const attachLegend = useCallback((el: HTMLDivElement | null) => {
    if (legendResizeObsRef.current) {
      legendResizeObsRef.current.disconnect();
      legendResizeObsRef.current = null;
    }
    legendElRef.current = el;
    if (!el) {
      // Unmount mid-drag (toolbar toggle, page change, last measurement gone):
      // the window listeners would otherwise position a detached element.
      endLegendDrag();
      return;
    }
    const ro = new ResizeObserver(() => reclampLegend());
    ro.observe(el);
    const vp = legendViewportRef.current;
    if (vp) ro.observe(vp);
    legendResizeObsRef.current = ro;
    reclampLegend();
  }, [endLegendDrag, reclampLegend]);

  /** Begin dragging the legend by its header. Listeners live on the window so
   *  the drag survives the cursor leaving the small legend rectangle. */
  const startLegendDrag = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const el = legendElRef.current;
    if (!legendViewportRef.current || !el) return;
    e.preventDefault();
    const elRect = el.getBoundingClientRect();
    const grabX = e.clientX - elRect.left;
    const grabY = e.clientY - elRect.top;
    endLegendDrag(); // drop any stale gesture first
    const onMove = (ev: MouseEvent) => {
      const rect = legendViewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      setLegendPos(clampLegend({ x: ev.clientX - rect.left - grabX, y: ev.clientY - rect.top - grabY }));
    };
    const onUp = () => endLegendDrag();
    legendDragRef.current = { onMove, onUp };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('blur', onUp);
  }, [clampLegend, endLegendDrag]);

  /** Double-click the header to send the legend back to the default corner. */
  const resetLegendPos = useCallback(() => setLegendPos(null), []);

  /** Currently-selected measurement object (null if nothing selected / target deleted). */
  const selectedMeasurement = useMemo(() => {
    if (!selectedMeasurementId) return null;
    return measurements.find((m) => m.id === selectedMeasurementId) ?? null;
  }, [selectedMeasurementId, measurements]);

  /** All unique group names across all measurements — for the properties-panel
   *  Group dropdown so users can move items into existing groups. */
  const availableGroups = useMemo(() => {
    const names = new Set<string>(MEASUREMENT_GROUPS.map((g) => g.name));
    for (const m of measurements) names.add(m.group || 'General');
    return Array.from(names);
  }, [measurements]);

  /** Patch an arbitrary set of fields on the currently-selected measurement. */
  const updateSelectedMeasurement = useCallback(
    (patch: Partial<Measurement>) => {
      if (!selectedMeasurementId) return;
      setMeasurements((prev) =>
        prev.map((m) => (m.id === selectedMeasurementId ? { ...m, ...patch } : m)),
      );
    },
    [selectedMeasurementId],
  );

  // Latest selected measurement in a ref so the width-seed effect can read it
  // while depending ONLY on the selection id (issue #339). Depending on the
  // object itself would re-seed - and clobber a half-typed real-width value - on
  // every unrelated measurement change.
  const selectedMeasurementRef = useRef(selectedMeasurement);
  selectedMeasurementRef.current = selectedMeasurement;

  // Seed the Line-width mode + draft from the selection (issue #339). Keyed ONLY
  // on the selection id so switching selection re-seeds, but typing (which
  // changes the measurement object, not its id) never re-runs this and
  // renormalises the buffer mid-keystroke. A real width is decomposed into BOTH
  // metres and feet+inches (via fromMeters) so either measurement system shows a
  // value.
  useEffect(() => {
    // Read the metres value off the freshly-selected measurement (via the ref so
    // this depends only on the id). No selection -> reset to px / empty.
    const real = selectedMeasurementId
      ? selectedMeasurementRef.current?.strokeWidthReal
      : undefined;
    if (real != null && real > 0) {
      const totalInches = fromMeters(real, 'in');
      const feet = Math.floor(fromMeters(real, 'ft'));
      const inches = totalInches - feet * 12;
      setWidthMode('real');
      setWidthDraft({
        m: String(Number(fromMeters(real, 'm').toFixed(4))),
        ft: String(feet),
        in: String(Number(inches.toFixed(4))),
      });
    } else {
      setWidthMode('px');
      setWidthDraft({ m: '', ft: '', in: '' });
    }
  }, [selectedMeasurementId]);

  // Write a real-width draft (issue #339) back to the canonical strokeWidthReal
  // (metres). Empty fields mean "unset" (undefined), never 0; NaN is guarded.
  // Every write clears the pixel strokeWidth so the two stay mutually exclusive.
  // Reuses toMeters for the ft/in and metre maths (no new conversion code).
  const applyRealWidthFromDraft = useCallback(
    (draft: { m: string; ft: string; in: string }) => {
      let meters: number | undefined;
      if (measurementSystem === 'imperial') {
        const ftEmpty = draft.ft.trim() === '';
        const inEmpty = draft.in.trim() === '';
        if (ftEmpty && inEmpty) {
          meters = undefined;
        } else {
          const ft = parseFloat(draft.ft);
          const inch = parseFloat(draft.in);
          const combined =
            toMeters(Number.isFinite(ft) ? ft : 0, 'ft') +
            toMeters(Number.isFinite(inch) ? inch : 0, 'in');
          meters = combined > 0 ? combined : undefined;
        }
      } else if (draft.m.trim() === '') {
        meters = undefined;
      } else {
        const v = parseFloat(draft.m);
        meters = Number.isFinite(v) && v > 0 ? toMeters(v, 'm') : undefined;
      }
      updateSelectedMeasurement(
        meters === undefined
          ? { strokeWidthReal: undefined }
          : { strokeWidthReal: meters, strokeWidth: undefined },
      );
    },
    [measurementSystem, updateSelectedMeasurement],
  );

  // Switch the Line-width control between px and the real unit (issue #339).
  // Converts the current width across the boundary using the SELECTED
  // measurement's own page scale so the band keeps its on-screen size:
  // px -> metres divides by pixelsPerUnit; metres -> px multiplies (rounded,
  // clamped 1..100). Guards an uncalibrated page (pixelsPerUnit <= 0) so there is
  // no divide-by-zero. Writes stay mutually exclusive (one width clears the other).
  const handleWidthUnitChange = useCallback(
    (next: 'px' | 'real') => {
      const m = selectedMeasurement;
      if (!m) return;
      const pixelsPerUnit = scaleForPage(pageScales, m.page).pixelsPerUnit;
      if (next === 'real') {
        if (pixelsPerUnit > 0) {
          const meters = (m.strokeWidth ?? 2) / pixelsPerUnit;
          const totalInches = fromMeters(meters, 'in');
          const feet = Math.floor(fromMeters(meters, 'ft'));
          const inches = totalInches - feet * 12;
          setWidthDraft({
            m: String(Number(fromMeters(meters, 'm').toFixed(4))),
            ft: String(feet),
            in: String(Number(inches.toFixed(4))),
          });
          updateSelectedMeasurement({ strokeWidthReal: meters, strokeWidth: undefined });
        } else {
          // Not calibrated: cannot derive metres from px. Enter real mode with an
          // empty buffer; the "not calibrated" hint prompts the user to calibrate.
          setWidthDraft({ m: '', ft: '', in: '' });
        }
        setWidthMode('real');
      } else {
        const meters = m.strokeWidthReal;
        if (meters != null && meters > 0 && pixelsPerUnit > 0) {
          const px = Math.min(100, Math.max(1, Math.round(meters * pixelsPerUnit)));
          updateSelectedMeasurement({ strokeWidth: px, strokeWidthReal: undefined });
        } else {
          // No usable real width -> drop it and fall back to the default hairline.
          updateSelectedMeasurement({ strokeWidthReal: undefined });
        }
        setWidthMode('px');
      }
    },
    [selectedMeasurement, pageScales, updateSelectedMeasurement],
  );

  /** Rename the active custom group (issue #313): move its measurements and its
   *  colour onto the new name. Built-in preset groups are not renameable. */
  const renameActiveGroup = useCallback(() => {
    if (MEASUREMENT_GROUPS.some((g) => g.name === activeGroup)) return;
    const raw = window.prompt(
      t('takeoff_viewer.rename_group_prompt', { defaultValue: 'Rename group' }),
      activeGroup,
    );
    const name = raw?.trim();
    if (!name || name === activeGroup) return;
    setMeasurements((prev) =>
      prev.map((m) => (m.group === activeGroup ? { ...m, group: name } : m)),
    );
    setCustomGroupColors((prev) => {
      const moved = prev[activeGroup];
      if (moved == null) return prev;
      const next: Record<string, string> = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k !== activeGroup) next[k] = v;
      }
      next[name] = moved;
      return next;
    });
    // Carry the hidden / collapsed state across to the new name (issue #313):
    // without this a hidden group reappears and a collapsed one expands after a
    // rename because those sets still key on the old name.
    setHiddenGroups((prev) => {
      if (!prev.has(activeGroup)) return prev;
      const next = new Set(prev);
      next.delete(activeGroup);
      next.add(name);
      return next;
    });
    setCollapsedGroups((prev) => {
      if (!prev.has(activeGroup)) return prev;
      const next = new Set(prev);
      next.delete(activeGroup);
      next.add(name);
      return next;
    });
    setActiveGroup(name);
  }, [activeGroup, t]);

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

  /** Toggle visibility of a single measurement (issue #359). View-only, like
   *  the group eye: it never touches quantities or exports to CSV/XLSX/BOQ. */
  const toggleMeasurementVisibility = useCallback((id: string) => {
    // Read the pre-toggle state before flipping it, so we know whether this is
    // a hide (was visible) or a show (was hidden).
    const wasHidden = hiddenMeasurementsRef.current.has(id);
    setHiddenMeasurements((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    // Hiding the selected measurement clears the selection, so the select-tool
    // edit overlay stops drawing handles over a now-hidden shape.
    if (!wasHidden) setSelectedMeasurementId((cur) => (cur === id ? null : cur));
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
    // Stored quantities are metric-canonical (D-TKC-016); convert values +
    // units to the user's system at the export boundary. Metric is a
    // pass-through so the file is unchanged for metric users.
    const sumUnit = (ms: Measurement[]) =>
      convertQuantity(
        // Effective quantity folds slope / wastage / multiplier and the
        // deduction sign, so this CSV reconciles with the ledger + Excel.
        ms.reduce((s, m) => s + effectiveQuantity(m), 0),
        ms[0]!.unit || '',
        measurementSystem,
      );
    for (const [groupName, groupMs] of Object.entries(byGroup)) {
      for (const m of groupMs) {
        const escapeCsv = (s: string) => `"${s.replace(/"/g, '""')}"`;
        // Opening deductions are stored as a positive gross area but net out
        // of the totals (net = gross - openings). Mirror the Excel and ledger
        // exports: show the row value as negative and flag the type, so the
        // CSV rows and subtotals reconcile instead of reporting inflated gross.
        const signedValue = effectiveQuantity(m);
        const disp = convertQuantity(signedValue, m.unit || '', measurementSystem);
        const typeLabel = m.isDeduction ? `${m.type} (deduction)` : m.type;
        rows.push(
          [
            escapeCsv(groupName),
            escapeCsv(typeLabel),
            escapeCsv(m.annotation),
            disp.value.toFixed(3),
            escapeCsv(disp.unit),
            String(m.page),
          ].join(','),
        );
      }
      // Add subtotal row for group
      const distMs = groupMs.filter((m) => m.type === 'distance' || m.type === 'polyline');
      const areaMs = groupMs.filter((m) => m.type === 'area');
      const volMs = groupMs.filter((m) => m.type === 'volume');
      const countMs = groupMs.filter((m) => m.type === 'count');
      // Subtotals net out opening deductions (gross - openings), matching the
      // Excel subtotal and the legend. Only area carries the flag today, but
      // the sign-flip is applied uniformly so it stays correct if that changes.
      if (distMs.length > 0) {
        const d = sumUnit(distMs);
        rows.push(`"${groupName} - Subtotal","distance","Total distance",${d.value.toFixed(3)},"${d.unit}",""`);
      }
      if (areaMs.length > 0) {
        const d = sumUnit(areaMs);
        rows.push(`"${groupName} - Subtotal","area","Total area",${d.value.toFixed(3)},"${d.unit}",""`);
      }
      if (volMs.length > 0) {
        const d = sumUnit(volMs);
        rows.push(`"${groupName} - Subtotal","volume","Total volume",${d.value.toFixed(3)},"${d.unit}",""`);
      }
      if (countMs.length > 0) {
        rows.push(`"${groupName} - Subtotal","count","Total count",${countMs.reduce((s, m) => s + effectiveQuantity(m), 0).toFixed(0)},"pcs",""`);
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
  }, [measurements, addToast, t, measurementSystem]);

  /**
   * Resolve the human-friendly project name for export filenames.
   *
   * Priority: explicit project context store value → loaded PDF filename
   * (stripped of extension) → "untitled".  Surface as a thin memo so the
   * PDF and Excel handlers stay in sync.
   */
  const exportProjectName = useMemo(() => {
    if (activeProjectName) return activeProjectName;
    if (fileName) return fileName.replace(/\.[^.]+$/, '');
    return 'untitled';
  }, [activeProjectName, fileName]);

  /** Export the current PDF with baked-in annotations + summary page. */
  const handleExportPdf = useCallback(async () => {
    if (!pdfDoc) {
      addToast({
        type: 'warning',
        title: t('takeoff_viewer.pdf_export_no_doc', { defaultValue: 'Load a PDF first' }),
      });
      return;
    }
    if (measurements.length === 0) {
      addToast({
        type: 'warning',
        title: t('takeoff_viewer.pdf_export_empty', { defaultValue: 'No measurements to export' }),
      });
      return;
    }
    setIsExportingPdf(true);
    addToast({
      type: 'info',
      title: t('takeoff_viewer.pdf_export_started', {
        defaultValue: 'Generating annotated PDF…',
      }),
    });
    try {
      const pdf = await buildTakeoffPdf({
        pdfDoc,
        measurements,
        hiddenGroups,
        hiddenMeasurements,
        scale,
        groupColorMap,
        projectName: exportProjectName,
        measurementSystem,
      });
      const blob = pdf.output('blob');
      triggerDownload(blob, buildExportFilename(exportProjectName, 'pdf'));
      addToast({
        type: 'success',
        title: t('takeoff_viewer.pdf_export_success', {
          defaultValue: 'Annotated PDF downloaded',
        }),
      });
    } catch (err) {
      console.error('PDF export failed:', err);
      addToast({
        type: 'error',
        title: t('takeoff_viewer.pdf_export_failed', {
          defaultValue: 'Failed to export PDF',
        }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setIsExportingPdf(false);
    }
  }, [pdfDoc, measurements, hiddenGroups, hiddenMeasurements, scale, exportProjectName, addToast, t, measurementSystem, groupColorMap]);

  /** Export measurements + summary to an .xlsx workbook. */
  const handleExportExcel = useCallback(async () => {
    if (measurements.length === 0) {
      addToast({
        type: 'warning',
        title: t('takeoff_viewer.excel_export_empty', {
          defaultValue: 'No measurements to export',
        }),
      });
      return;
    }
    setIsExportingXlsx(true);
    addToast({
      type: 'info',
      title: t('takeoff_viewer.excel_export_started', {
        defaultValue: 'Building Excel workbook…',
      }),
    });
    try {
      const wb = await buildTakeoffWorkbook({
        measurements,
        scale,
        groupColorMap,
        projectName: exportProjectName,
        measurementSystem,
      });
      const buf = await wb.xlsx.writeBuffer();
      const blob = new Blob([buf], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      triggerDownload(blob, buildExportFilename(exportProjectName, 'xlsx'));
      addToast({
        type: 'success',
        title: t('takeoff_viewer.excel_export_success', {
          defaultValue: 'Excel workbook downloaded',
        }),
      });
    } catch (err) {
      console.error('Excel export failed:', err);
      addToast({
        type: 'error',
        title: t('takeoff_viewer.excel_export_failed', {
          defaultValue: 'Failed to export Excel',
        }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setIsExportingXlsx(false);
    }
  }, [measurements, scale, exportProjectName, addToast, t, measurementSystem, groupColorMap]);

  const deleteMeasurement = useCallback((id: string) => {
    // Capture the target up front so we can both push an undo frame and queue
    // the server-side delete (issue #282) without running side-effects inside
    // the state updater (which React may invoke twice under StrictMode).
    const target = measurements.find((m) => m.id === id);
    if (target) {
      pushUndo({ kind: 'delete_measurement', measurement: { ...target, points: [...target.points] } });
      // A synced row must also be removed on the server; a never-synced row
      // (no serverId) just drops locally. registerDeletion is a no-op for the
      // latter and an undo that restores the row cancels the queued delete.
      registerDeletion(target.serverId);
    }
    setMeasurements((prev) => prev.filter((m) => m.id !== id));
    // Clear selection if the deleted measurement was selected.
    setSelectedMeasurementId((cur) => (cur === id ? null : cur));
  }, [measurements, pushUndo, registerDeletion]);

  /**
   * Duplicate a measurement (issue #302): clone it with a fresh id, a small
   * visible offset (so the copy is not exactly on top), and the same group /
   * annotation / colour / geometry / other properties. Server identity, BOQ
   * link and AI-suggestion flags are intentionally dropped so the copy is a
   * fresh, unsynced, unlinked measurement rather than a second row pointing at
   * the same server object / BOQ position. Goes through the normal create path
   * (build -> pushUndo -> append) so undo removes it in one step.
   */
  const duplicateMeasurement = useCallback((id: string) => {
    const src = measurements.find((m) => m.id === id);
    if (!src) return;
    // Offset by a fixed screen distance regardless of zoom so the copy is
    // always visibly separated from the original.
    const offset = 12 / (zoomRef.current || 1);
    const clone: Measurement = {
      ...src,
      // Random suffix so rapid Ctrl+D (keyboard auto-repeat, same millisecond)
      // never mints two colliding ids.
      id: `m_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      points: src.points.map((p) => ({ x: p.x + offset, y: p.y + offset })),
      serverId: undefined,
      suggested: undefined,
      linkedPositionId: undefined,
      linkedPositionOrdinal: undefined,
      linkedBoqId: undefined,
      linkedPositionLabel: undefined,
    };
    pushUndo({ kind: 'complete_measurement', measurement: clone, previousActivePoints: [] });
    setMeasurements((prev) => [...prev, clone]);
    setSelectedMeasurementId(clone.id);
    setContextMenu(null);
  }, [measurements, pushUndo]);

  /**
   * Replicate takeoff measurements onto other pages (issue #332 wave): the
   * "typical floor" shortcut. A slab outline / column run / fixture count
   * measured once on one sheet is copied - same geometry, group, appearance
   * and quantity adjustments - onto every selected page, as fresh, unlinked,
   * unsynced measurements. Each clone gets its own undo frame so a copy that
   * spanned five pages can be walked back one page-copy at a time. The heavy
   * lifting is in the pure `replicateMeasurementsToPages` helper (unit-tested);
   * this thin wrapper mints ids, appends to state, and toasts the result.
   */
  const copyMeasurementsToPages = useCallback(
    (sources: Measurement[], pages: number[]) => {
      if (sources.length === 0 || pages.length === 0) return;
      const stamp = Date.now();
      const clones = replicateMeasurementsToPages(
        sources,
        pages,
        (_src, page, i) =>
          `m_${stamp}_p${page}_${i}_${Math.random().toString(36).slice(2, 6)}`,
      );
      if (clones.length === 0) return;
      for (const c of clones) {
        pushUndo({ kind: 'complete_measurement', measurement: c, previousActivePoints: [] });
      }
      setMeasurements((prev) => [...prev, ...clones]);
      setCopyTargetPages(new Set());
      addToast({
        type: 'success',
        title: t('takeoff_viewer.copied_to_pages_title', { defaultValue: 'Copied to pages' }),
        message: t('takeoff_viewer.copied_to_pages_msg', {
          defaultValue: '{{count}} measurement(s) copied to {{pages}} page(s).',
          count: clones.length,
          pages: new Set(clones.map((c) => c.page)).size,
        }),
      });
    },
    [pushUndo, addToast, t],
  );

  // Reset the "copy to pages" target selection whenever the selected
  // measurement changes, so a stale page selection never carries across.
  useEffect(() => {
    setCopyTargetPages(new Set());
  }, [selectedMeasurementId]);

  // Close the measurement context menu when the select tool is left or its
  // target measurement disappears (issue #302).
  useEffect(() => {
    if (!contextMenu) return;
    if (activeTool !== 'select' || !measurements.some((m) => m.id === contextMenu.measurementId)) {
      setContextMenu(null);
    }
  }, [activeTool, measurements, contextMenu]);

  /* ── Recognize: offline AI vector detection (issue #194) ───────────── */

  const [recognizeBusy, setRecognizeBusy] = useState(false);
  // "Count similar" (seeded count-by-example) state. `armCountSimilar` is the
  // UI pressed/cursor state; `countSimilarBusy` disables the button and spins
  // while the server matches symbols. The click latch lives in
  // armCountSimilarRef (declared up by handleCanvasClick) to avoid stale reads.
  const [armCountSimilar, setArmCountSimilar] = useState(false);
  const [countSimilarBusy, setCountSimilarBusy] = useState(false);

  /** Number of unconfirmed AI suggestions currently on the canvas. */
  const suggestionCount = useMemo(
    () => measurements.filter((m) => m.suggested).length,
    [measurements],
  );

  /** Scan the current page's vector layer and drop suggested measurements.
   *  Suggestions are flagged (never persisted) until the user accepts them. */
  const handleRecognize = useCallback(async () => {
    if (recognizeBusy) return;
    // The server reads the stored PDF off disk, so it needs the document's
    // id, which the deep-link download URL carries.
    const docId = initialPdfUrl?.match(/\/documents\/([^/?#]+)\/(?:download|recognize)/)?.[1];
    if (!docId) {
      addToast({
        type: 'info',
        title: t('takeoff_viewer.recognize_needs_upload_title', { defaultValue: 'Recognition needs an uploaded drawing' }),
        message: t('takeoff_viewer.recognize_needs_upload_msg', {
          defaultValue: 'Upload this PDF to the project first, then open it from the documents list to recognize measurements.',
        }),
      });
      return;
    }
    setRecognizeBusy(true);
    try {
      const result = await takeoffApi.recognize(docId, currentPage, scale.pixelsPerUnit);
      const cands = result.candidates ?? [];
      if (cands.length === 0) {
        addToast({
          type: 'info',
          title: t('takeoff_viewer.recognize_none_title', { defaultValue: 'No measurements detected' }),
          message:
            result.notes === 'no_vector_layer'
              ? t('takeoff_viewer.recognize_no_vectors', { defaultValue: 'This page has no vector layer (it may be scanned). Try the AI text analysis on the Documents tab instead.' })
              : t('takeoff_viewer.recognize_none_msg', { defaultValue: 'Nothing clear enough to suggest on this page.' }),
        });
        return;
      }
      const suggestions: Measurement[] = cands.map((c, i) => {
        const mType: Measurement['type'] = c.type === 'distance' ? 'distance' : c.type === 'count' ? 'count' : 'area';
        const unit = c.type === 'area' ? `${scale.unitLabel}²` : c.type === 'distance' ? scale.unitLabel : 'pcs';
        const value = c.type === 'count' ? (c.count ?? c.points.length) : (c.value ?? 0);
        const labelText =
          c.type === 'count'
            ? String(c.count ?? c.points.length)
            : c.value != null
              ? formatMeasurement(c.value, unit)
              : t('takeoff_viewer.recognize_uncalibrated', { defaultValue: 'calibrate for value' });
        return {
          id: `sug_${Date.now()}_${i}`,
          type: mType,
          points: c.points.map((p) => ({ x: p.x, y: p.y })),
          value,
          unit,
          label: labelText,
          annotation: nextAnnotation(mType),
          page: currentPage,
          group: activeGroup,
          suggested: true,
          confidence: c.confidence,
        };
      });
      setMeasurements((prev) => [...prev, ...suggestions]);
      addToast({
        type: 'success',
        title: t('takeoff_viewer.recognize_added_title', { defaultValue: '{{n}} suggestions added', n: suggestions.length }),
        message: t('takeoff_viewer.recognize_added_msg', { defaultValue: 'Review them on the drawing, then accept or dismiss each.' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff_viewer.recognize_failed', { defaultValue: 'Recognition failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setRecognizeBusy(false);
    }
  }, [recognizeBusy, initialPdfUrl, currentPage, scale, activeGroup, nextAnnotation, addToast, t]);

  /* ── Count similar: seeded "count by example" (issue #194) ──────────────
   * The user arms the tool and clicks one symbol (a door, socket, column).
   * The server scans this page's vector layer for every near-identical symbol
   * and returns their centroids; we drop ONE suggested `count` measurement at
   * those points. Like Recognize it is a suggestion - nothing is persisted
   * until the user accepts it. Coordinates are PDF points, the same space the
   * canvas and stored measurements use, so the hit centroids map straight
   * through (identical to how handleRecognize consumes its candidate points). */
  const handleCountByExampleSeed = useCallback(
    async (seed: Point) => {
      const docId = initialPdfUrl?.match(/\/documents\/([^/?#]+)\/(?:download|recognize)/)?.[1];
      if (!docId) {
        addToast({
          type: 'info',
          title: t('takeoff_viewer.count_similar.needs_upload_title', {
            defaultValue: 'Count similar needs an uploaded drawing',
          }),
          message: t('takeoff_viewer.count_similar.needs_upload_msg', {
            defaultValue:
              'Upload this PDF to the project first, then open it from the documents list to count symbols.',
          }),
        });
        return;
      }
      setCountSimilarBusy(true);
      try {
        const result = await takeoffApi.similarSymbols(docId, currentPage, seed.x, seed.y);
        const hits = result.hits ?? [];
        if (hits.length === 0) {
          addToast({
            type: 'info',
            title: t('takeoff_viewer.count_similar.none_title', { defaultValue: 'No matching symbols' }),
            message:
              result.note === 'no_vector_layer'
                ? t('takeoff_viewer.count_similar.no_vectors', {
                    defaultValue:
                      'This page has no vector layer (it may be scanned), so symbols cannot be matched.',
                  })
                : result.seed_found
                  ? t('takeoff_viewer.count_similar.none_msg', {
                      defaultValue: 'No other symbol on this page looks like the one you clicked.',
                    })
                  : t('takeoff_viewer.count_similar.no_seed', {
                      defaultValue:
                        'No symbol was found under that click. Click directly on a symbol to count it.',
                    }),
          });
          return;
        }
        const points = hits.map((h) => ({ x: h.x, y: h.y }));
        const avgConfidence = hits.reduce((s, h) => s + (h.confidence ?? 0), 0) / hits.length;
        const suggestion: Measurement = {
          id: `sug_${Date.now()}_cnt`,
          type: 'count',
          points,
          value: points.length,
          unit: 'pcs',
          label: String(points.length),
          annotation: nextAnnotation('count'),
          page: currentPage,
          group: activeGroup,
          suggested: true,
          confidence: Math.round(avgConfidence * 100) / 100,
        };
        setMeasurements((prev) => [...prev, suggestion]);
        addToast({
          type: 'success',
          title: t('takeoff_viewer.count_similar.added_title', {
            defaultValue: '{{n}} matching symbols counted',
            n: points.length,
          }),
          message: t('takeoff_viewer.count_similar.added_msg', {
            defaultValue:
              'Review the highlighted symbols on the drawing, then accept or dismiss the count.',
          }),
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('takeoff_viewer.count_similar.failed', { defaultValue: 'Count similar failed' }),
          message: err instanceof Error ? err.message : '',
        });
      } finally {
        setCountSimilarBusy(false);
        setArmCountSimilar(false);
        armCountSimilarRef.current = false;
      }
    },
    [initialPdfUrl, currentPage, activeGroup, nextAnnotation, addToast, t],
  );
  // Keep the ref handleCanvasClick reads in sync with the latest closure.
  handleCountByExampleSeedRef.current = handleCountByExampleSeed;

  /** Toggle the "Count similar" arm. Arming switches to the select tool (so a
   *  half-drawn shape never swallows the seed click) and prompts the user to
   *  click a symbol; clicking the button again cancels. */
  const toggleCountSimilar = useCallback(() => {
    const docId = initialPdfUrl?.match(/\/documents\/([^/?#]+)\/(?:download|recognize)/)?.[1];
    if (!docId) {
      addToast({
        type: 'info',
        title: t('takeoff_viewer.count_similar.needs_upload_title', {
          defaultValue: 'Count similar needs an uploaded drawing',
        }),
        message: t('takeoff_viewer.count_similar.needs_upload_msg', {
          defaultValue:
            'Upload this PDF to the project first, then open it from the documents list to count symbols.',
        }),
      });
      return;
    }
    setArmCountSimilar((on) => {
      const next = !on;
      armCountSimilarRef.current = next;
      if (next) {
        setActiveTool('select');
        setActivePoints([]);
        addToast({
          type: 'info',
          title: t('takeoff_viewer.count_similar.armed_title', { defaultValue: 'Click a symbol to count' }),
          message: t('takeoff_viewer.count_similar.armed_msg', {
            defaultValue:
              'Click one symbol on the drawing and every matching symbol on this page is counted.',
          }),
        });
      }
      return next;
    });
  }, [initialPdfUrl, addToast, t]);

  /* ── Read plan with AI: vision-LLM plan reading (issue #194) ────────────
   * The opt-in, bring-your-own-key, cost-capped complement to the offline
   * Recognize tool. It can read room names, dimension strings and a scale that
   * OpenCV structurally cannot. Every result is a SUGGESTION with a confidence;
   * nothing is applied until the user accepts it (same provisional-overlay
   * flow as offline Recognize), and the server recomputes the billed number. */

  const [planReadBusy, setPlanReadBusy] = useState(false);
  /** Null until /plan-read/meta resolves; false hides the action when no
   *  vision-capable AI key is configured (graceful degradation). */
  const [planReadVision, setPlanReadVision] = useState<{ available: boolean; reason: string | null } | null>(
    null,
  );

  // Probe vision availability once on mount so the action can hide / disable
  // cleanly when no key is configured. Never throws to the user.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const meta = await takeoffApi.planRead.meta();
        if (!cancelled && meta) {
          setPlanReadVision({ available: meta.vision_available, reason: meta.reason });
        } else if (!cancelled) {
          setPlanReadVision({ available: false, reason: null });
        }
      } catch {
        if (!cancelled) setPlanReadVision({ available: false, reason: null });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Read the current page with a vision model: start a run, poll it to
   *  completion, then drop its proposals as provisional suggestions the user
   *  reviews and accepts (human-confirmed). Never auto-applies. */
  const handleReadWithAi = useCallback(async () => {
    if (planReadBusy) return;
    const docId = initialPdfUrl?.match(/\/documents\/([^/?#]+)\/(?:download|recognize)/)?.[1];
    const projectId = selectedProjectId || activeProjectId || '';
    if (!docId || !projectId) {
      addToast({
        type: 'info',
        title: t('takeoff_viewer.plan_read.needs_upload_title', {
          defaultValue: 'AI plan reading needs an uploaded drawing',
        }),
        message: t('takeoff_viewer.plan_read.needs_upload_msg', {
          defaultValue:
            'Upload this PDF to a project first, then open it from the documents list to read it with AI.',
        }),
      });
      return;
    }
    setPlanReadBusy(true);
    try {
      const run = await takeoffApi.planRead.start({
        project_id: projectId,
        document_id: docId,
        page: currentPage,
        mode: 'rooms',
        scale_pixels_per_unit: scale.pixelsPerUnit > 0 ? scale.pixelsPerUnit : null,
      });
      // Poll the FSM to a terminal state (review / applied / failed). The run
      // is in-process and fast for one page; cap the wait so the UI never hangs.
      let current = run;
      const deadline = Date.now() + 130_000;
      while (!['review', 'applied', 'failed', 'cancelled'].includes(current.status)) {
        if (Date.now() > deadline) break;
        await new Promise((r) => setTimeout(r, 1500));
        current = await takeoffApi.planRead.getRun(run.id);
      }
      if (current.status === 'failed') {
        addToast({
          type: 'error',
          title: t('takeoff_viewer.plan_read.failed', { defaultValue: 'AI plan reading failed' }),
          message: current.failure_reason
            ? t(`takeoff_viewer.plan_read.reason_${current.failure_reason}`, {
                defaultValue: current.failure_reason,
              })
            : '',
        });
        return;
      }
      const proposals = await takeoffApi.planRead.proposals(run.id);
      if (proposals.length === 0) {
        addToast({
          type: 'info',
          title: t('takeoff_viewer.plan_read.none_title', { defaultValue: 'No rooms detected' }),
          message: t('takeoff_viewer.plan_read.none_msg', {
            defaultValue: 'The model did not find anything clear enough to suggest on this page.',
          }),
        });
        return;
      }
      const suggestions: Measurement[] = proposals.map((p, i) => {
        const mType: Measurement['type'] = p.type === 'count' ? 'count' : 'area';
        const unit = p.type === 'count' ? 'pcs' : `${scale.unitLabel}²`;
        const value =
          p.type === 'count'
            ? (p.count_value ?? p.points.length)
            : (typeof p.measurement_value === 'number' ? p.measurement_value : 0);
        const labelText =
          p.type === 'count'
            ? String(p.count_value ?? p.points.length)
            : p.measurement_value != null
              ? formatMeasurement(Number(p.measurement_value), unit)
              : t('takeoff_viewer.recognize_uncalibrated', { defaultValue: 'calibrate for value' });
        return {
          id: `ai_${run.id}_${i}`,
          type: mType,
          points: p.points.map((pt) => ({ x: pt.x, y: pt.y })),
          value: Number(value) || 0,
          unit,
          label: labelText,
          annotation: p.annotation || nextAnnotation(mType),
          page: currentPage,
          group: activeGroup,
          suggested: true,
          confidence: p.confidence ?? undefined,
        };
      });
      setMeasurements((prev) => [...prev, ...suggestions]);
      addToast({
        type: 'success',
        title: t('takeoff_viewer.plan_read.added_title', {
          defaultValue: '{{n}} AI suggestions added',
          n: suggestions.length,
        }),
        message: t('takeoff_viewer.plan_read.added_msg', {
          defaultValue: 'Review them on the drawing, then accept or reject each (AI proposes, you confirm).',
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff_viewer.plan_read.failed', { defaultValue: 'AI plan reading failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setPlanReadBusy(false);
    }
  }, [
    planReadBusy,
    initialPdfUrl,
    selectedProjectId,
    activeProjectId,
    currentPage,
    scale,
    activeGroup,
    nextAnnotation,
    addToast,
    t,
  ]);

  /** Accept one suggestion: clear the flag so it persists on the next sync. */
  const acceptSuggestion = useCallback((id: string) => {
    setMeasurements((prev) => prev.map((m) => (m.id === id ? { ...m, suggested: false } : m)));
  }, []);

  /** Reject one suggestion: drop it (it was never persisted). */
  const rejectSuggestion = useCallback((id: string) => {
    setMeasurements((prev) => prev.filter((m) => m.id !== id));
    setSelectedMeasurementId((cur) => (cur === id ? null : cur));
  }, []);

  /** Accept every pending suggestion at once. */
  const acceptAllSuggestions = useCallback(() => {
    setMeasurements((prev) => prev.map((m) => (m.suggested ? { ...m, suggested: false } : m)));
  }, []);

  /** Dismiss every pending suggestion at once. */
  const dismissAllSuggestions = useCallback(() => {
    setMeasurements((prev) => prev.filter((m) => !m.suggested));
  }, []);

  /* ── Export measurements to BOQ ────────────────────────────────── */

  const loadExportBoqs = useCallback(async (projectId: string) => {
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
  }, [addToast, t]);

  const openExportDialog = useCallback(async () => {
    setShowExportDialog(true);
    // Seed the picker from the app's active project context so the
    // estimator doesn't have to reselect the project they're already
    // working in. The BOQ list loads in step with it.
    const seedProject = selectedProjectId || activeProjectId || '';
    if (seedProject) {
      setSelectedProjectId(seedProject);
      if (exportBoqs.length === 0) {
        await loadExportBoqs(seedProject);
      }
    }
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
  }, [addToast, t, selectedProjectId, activeProjectId, exportBoqs.length, loadExportBoqs]);

  const handleProjectChange = useCallback(async (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedBoqId('');
    await loadExportBoqs(projectId);
  }, [loadExportBoqs]);

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
          quantity: boqQuantity(m.value),
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
    // Queue a server-side delete for every synced row before wiping state
    // (issue #282) so clear-all does not leave orphaned measurements on the
    // server that would resurrect on the next load. clearPersisted removes the
    // document's localStorage copy but NOT the separate pending-delete queue,
    // so the debounced server-sync still applies these deletes.
    for (const m of measurements) {
      if (m.serverId) registerDeletion(m.serverId);
    }
    setMeasurements([]);
    setActivePoints([]);
    undoStackRef.current = [];
    redoStackRef.current = [];
    setUndoCount(0);
    setRedoCount(0);
    setSelectedMeasurementId(null);
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
  }, [measurements, registerDeletion, clearPersisted]);

  /* ── Link measurement to BOQ ─────────────────────────────────────── */

  const activeBoqIdFromStore = useProjectContextStore((s) => s.activeBOQId);

  /** Canonical unit normalization — maps display glyph → canonical backend unit. */
  const normalizeUnit = useCallback((unit: string) => {
    const map: Record<string, string> = { m: 'm', 'm\u00B2': 'm2', 'm\u00B3': 'm3', pcs: 'pcs' };
    return map[unit] ?? unit;
  }, []);

  /** Load BOQs for a project (picker-side). */
  const loadPickerBoqs = useCallback(async (projectId: string) => {
    if (!projectId) { setLinkPickerBoqs([]); return; }
    setLinkBoqsLoading(true);
    try {
      const boqs = await apiGet<{ id: string; name: string }[]>(`/v1/boq/boqs/?project_id=${projectId}`);
      setLinkPickerBoqs(boqs);
    } catch {
      setLinkPickerBoqs([]);
    } finally {
      setLinkBoqsLoading(false);
    }
  }, []);

  /** Load positions for a BOQ (picker-side). */
  const loadPickerPositions = useCallback(async (boqId: string) => {
    if (!boqId) { setLinkBoqPositions([]); return; }
    setLinkPositionsLoading(true);
    try {
      const boqData = await apiGet<{ positions: Position[] }>(`/v1/boq/boqs/${boqId}`);
      setLinkBoqPositions(boqData.positions || []);
    } catch {
      setLinkBoqPositions([]);
    } finally {
      setLinkPositionsLoading(false);
    }
  }, []);

  /** Open the BOQ position picker for a measurement.
   *  Self-sufficient: discovers project + BOQ even if the Export dialog was
   *  never opened.  Reuses the export selection if it exists, otherwise
   *  falls back to the app's active project/BOQ context.
   */
  const handleOpenLinkToBoq = useCallback(async (measurementId: string) => {
    setLinkingMeasurementId(measurementId);
    setLinkPickerSearch('');
    setLinkPickerMode('pick');

    // Seed picker selection.  Priority: export-dialog pick > active context.
    const seedProject = selectedProjectId || activeProjectId || '';
    const seedBoq = (selectedProjectId ? selectedBoqId : '') || (activeProjectId ? activeBoqIdFromStore ?? '' : '') || '';
    setLinkPickerProjectId(seedProject);
    setLinkPickerBoqId(seedBoq);

    // Always (re-)load the project list lazily so the user can switch.
    try {
      const projects = await apiGet<{ id: string; name: string }[]>('/v1/projects/');
      setLinkPickerProjects(projects);
    } catch {
      setLinkPickerProjects([]);
    }

    if (seedProject) {
      await loadPickerBoqs(seedProject);
    } else {
      setLinkPickerBoqs([]);
    }
    if (seedBoq) {
      await loadPickerPositions(seedBoq);
    } else {
      setLinkBoqPositions([]);
    }
  }, [selectedProjectId, selectedBoqId, activeProjectId, activeBoqIdFromStore, loadPickerBoqs, loadPickerPositions]);

  /** Picker: user switched project.  Reset BOQ + positions, load BOQs for new project. */
  const handlePickerProjectChange = useCallback(async (projectId: string) => {
    setLinkPickerProjectId(projectId);
    setLinkPickerBoqId('');
    setLinkBoqPositions([]);
    await loadPickerBoqs(projectId);
  }, [loadPickerBoqs]);

  /** Picker: user picked a BOQ.  Load its positions. */
  const handlePickerBoqChange = useCallback(async (boqId: string) => {
    setLinkPickerBoqId(boqId);
    await loadPickerPositions(boqId);
  }, [loadPickerPositions]);

  /** Link a measurement to a specific existing BOQ position, pushing the
   *  measurement's quantity/unit into the position and recording both
   *  sides of the link (measurement.linked_boq_position_id +
   *  position.metadata.pdf_measurement_source).
   */
  const handleLinkToPosition = useCallback(async (measurementId: string, position: Position) => {
    const measurement = measurements.find((m) => m.id === measurementId);
    if (!measurement) return;

    // Dimension guard - mirror of the backend ``push_quantity`` check.
    // The server refuses a cross-dimension push SILENTLY (HTTP 200, BOQ
    // quantity untouched), so detect the mismatch up front and tell the
    // user why nothing would flow instead of leaving a stale total.
    const mDim = measurementDimension(measurement.type, normalizeUnit(measurement.unit));
    const pDim = unitDimension(position.unit);
    if (mDim !== null && pDim !== null && mDim !== pDim) {
      const mLabel = t(DIMENSION_LABELS[mDim].key, { defaultValue: DIMENSION_LABELS[mDim].fallback });
      const pLabel = t(DIMENSION_LABELS[pDim].key, { defaultValue: DIMENSION_LABELS[pDim].fallback });
      addToast({
        type: 'error',
        title: t('takeoff.dimension_mismatch_title', { defaultValue: 'Dimension mismatch' }),
        // "ordinal" is a reserved i18next option (ordinal plurals) -
        // interpolate the position ordinal as posOrdinal instead.
        message: t('takeoff.dimension_mismatch_msg', {
          defaultValue:
            'This {{measurementDim}} measurement cannot fill position {{posOrdinal}} measured in {{unit}} ({{positionDim}}). Pick a {{measurementDim}} position or create a new one.',
          measurementDim: mLabel,
          positionDim: pLabel,
          posOrdinal: position.ordinal,
          unit: position.unit,
        }),
      });
      return;
    }

    setLinkingInProgress(true);
    try {
      const sourceLabel = `Takeoff: ${measurement.annotation || measurement.type} (page ${measurement.page})`;
      const canonicalUnit = normalizeUnit(measurement.unit);
      const positionUnit = (position.unit ?? '').trim();

      // Reported (effective) quantity: folds slope / wastage / typical-
      // multiplier so the BOQ receives the same number the ledger + exports
      // show, not the raw geometry (issue #332 wave). Magnitude, since a BOQ
      // quantity is positive; a no-factor measurement equals its raw value, so
      // this is byte-identical for existing data.
      const baseQty = reportedMagnitude(measurement);
      // Convert the measured value into the position's own unit before it is
      // written (GitHub #319). A position already priced per its unit (say cubic
      // yards) must receive the quantity restated in that unit or its unit_rate
      // silently mis-prices the line. Only when the position has no unit yet do
      // we adopt the measurement's unit, matching the create-and-link path.
      let newQtyValue = baseQty;
      let unitToWrite: string | undefined;
      if (!positionUnit) {
        unitToWrite = canonicalUnit;
      } else {
        const converted = convertBetween(baseQty, canonicalUnit, positionUnit);
        if (converted === null) {
          addToast({
            type: 'error',
            title: t('takeoff.unit_not_convertible_title', { defaultValue: 'Units do not match' }),
            message: t('takeoff.unit_not_convertible_msg', {
              defaultValue:
                'This {{from}} measurement cannot be converted into position {{posOrdinal}} priced in {{to}}. Pick a matching position or create a new one.',
              from: canonicalUnit,
              to: positionUnit,
              posOrdinal: position.ordinal,
            }),
          });
          setLinkingInProgress(false);
          return;
        }
        newQtyValue = converted;
      }
      const newQty = boqQuantity(newQtyValue);
      const displayUnit = unitToWrite ?? positionUnit;
      const existingMeta = (position.metadata ?? {}) as Record<string, unknown>;

      await boqApi.updatePosition(position.id, {
        quantity: newQty,
        // Keep the position's own unit when it already has one, so its
        // unit_rate stays valid; only set the unit when the position had none.
        ...(unitToWrite !== undefined ? { unit: unitToWrite } : {}),
        metadata: {
          ...existingMeta,
          pdf_measurement_source: sourceLabel,
          pdf_measurement_id: measurement.serverId ?? measurement.id,
          pdf_document_id: fileName ?? undefined,
          pdf_page: measurement.page,
        },
      });

      // Link on server (only if the measurement has a real server id).
      // ``pushQuantity: true`` lets the backend copy its own recomputed
      // measurement value into the position and re-run the canonical total
      // recompute, so the server stays the authority on the number. But a
      // frontend quantity adjustment (slope / wastage / typical-multiplier)
      // lives only client-side, so the server recompute would DROP it and
      // clobber the effective quantity we just wrote. In that case record the
      // link WITHOUT pushing (a factored quantity is a deliberate manual figure,
      // like a hand-typed quantity); with no factor keep the server push,
      // byte-identical to before this wave.
      if (measurement.serverId) {
        const pushQuantity = !hasQuantityFactor(measurement);
        try { await takeoffApi.linkToBoq(measurement.serverId, position.id, { pushQuantity }); } catch { /* non-critical */ }
      }

      // Update local measurement so the badge appears immediately.
      setMeasurements((prev) => prev.map((m) =>
        m.id === measurementId
          ? {
              ...m,
              linkedPositionId: position.id,
              linkedPositionOrdinal: position.ordinal,
              linkedBoqId: position.boq_id,
              linkedPositionLabel: position.description,
            }
          : m,
      ));

      // The BOQ editor caches positions under ['boq', <id>] - refresh so
      // the pushed quantity shows up there without a manual reload.
      queryClient.invalidateQueries({ queryKey: ['boq', position.boq_id] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });

      addToast({
        type: 'success',
        title: t('takeoff.linked_to_boq', { defaultValue: 'Linked to BOQ' }),
        message: `${newQty} ${displayUnit} → ${position.ordinal} ${position.description?.slice(0, 40) || ''}`.trim(),
      });
      setLinkingMeasurementId(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff.link_failed', { defaultValue: 'Link failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [measurements, addToast, t, normalizeUnit, queryClient]);

  /** Create a brand-new BOQ position from the measurement and link to it.
   *  The ordinal is auto-generated as TK.NNN based on existing TK positions.
   */
  const handleCreateAndLink = useCallback(async (measurementId: string) => {
    const measurement = measurements.find((m) => m.id === measurementId);
    if (!measurement) return;
    if (!linkPickerBoqId) {
      addToast({
        type: 'warning',
        title: t('takeoff.link_need_boq', { defaultValue: 'Pick a BOQ first' }),
      });
      return;
    }
    setLinkingInProgress(true);
    try {
      // Derive next TK.NNN ordinal from existing positions.
      const takeoffOrdinals = linkBoqPositions
        .map((p) => {
          const match = /^TK\.(\d+)$/.exec(p.ordinal || '');
          return match ? parseInt(match[1]!, 10) : 0;
        })
        .filter((n) => n > 0);
      const nextNum = (takeoffOrdinals.length ? Math.max(...takeoffOrdinals) : 0) + 1;
      const ordinal = `TK.${String(nextNum).padStart(3, '0')}`;

      // Reported (effective) quantity: slope / wastage / multiplier folded in
      // (issue #332 wave); equals the raw value for an unadjusted measurement.
      const newQty = boqQuantity(reportedMagnitude(measurement));
      const canonicalUnit = normalizeUnit(measurement.unit);
      const description = measurement.annotation
        || t('takeoff.position_default_desc', {
          defaultValue: 'Takeoff · {{type}} page {{page}}',
          type: measurement.type,
          page: measurement.page,
        });

      const newPos = await boqApi.addPosition({
        boq_id: linkPickerBoqId,
        ordinal,
        description,
        unit: canonicalUnit,
        quantity: newQty,
        unit_rate: 0,
      });

      // Write measurement-source metadata via a follow-up patch so the BOQ
      // cell renderers show the PDF source badge + can deep-link back.
      try {
        await boqApi.updatePosition(newPos.id, {
          metadata: {
            pdf_measurement_source: `Takeoff: ${measurement.annotation || measurement.type} (page ${measurement.page})`,
            pdf_measurement_id: measurement.serverId ?? measurement.id,
            pdf_document_id: fileName ?? undefined,
            pdf_page: measurement.page,
          },
        });
      } catch { /* metadata is non-critical */ }

      if (measurement.serverId) {
        // pushQuantity keeps the server authoritative on the value (it
        // re-copies its own recomputed measurement into the new position). A
        // frontend adjustment (slope / wastage / multiplier) would be dropped
        // by that recompute, so skip the push when one is present and let the
        // effective quantity we wrote above stand (issue #332 wave).
        const pushQuantity = !hasQuantityFactor(measurement);
        try { await takeoffApi.linkToBoq(measurement.serverId, newPos.id, { pushQuantity }); } catch { /* non-critical */ }
      }

      setMeasurements((prev) => prev.map((m) =>
        m.id === measurementId
          ? {
              ...m,
              linkedPositionId: newPos.id,
              linkedPositionOrdinal: newPos.ordinal,
              linkedBoqId: newPos.boq_id,
              linkedPositionLabel: newPos.description,
            }
          : m,
      ));
      // Also keep the local position list fresh so subsequent ordinals
      // increment correctly without a round-trip.
      setLinkBoqPositions((prev) => [...prev, newPos]);

      // Refresh the react-query cached BOQ editor views.
      queryClient.invalidateQueries({ queryKey: ['boq', newPos.boq_id] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });

      addToast({
        type: 'success',
        title: t('takeoff.linked_created', { defaultValue: 'Position created & linked' }),
        message: `${ordinal} - ${newQty} ${canonicalUnit}`,
      });
      setLinkingMeasurementId(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff.create_link_failed', { defaultValue: 'Create & link failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [measurements, linkPickerBoqId, linkBoqPositions, addToast, t, normalizeUnit, queryClient]);

  /** Remove the link between a measurement and its BOQ position.
   *  We intentionally leave the BOQ position alone — unlinking just
   *  detaches the relationship, so the user doesn't accidentally wipe a
   *  quantity they've reviewed.
   */
  const handleUnlinkMeasurement = useCallback(async (measurementId: string) => {
    const measurement = measurements.find((m) => m.id === measurementId);
    if (!measurement) return;
    setLinkingInProgress(true);
    try {
      if (measurement.serverId) {
        try {
          await takeoffApi.update(measurement.serverId, { linked_boq_position_id: null });
        } catch { /* non-critical */ }
      }
      setMeasurements((prev) => prev.map((m) =>
        m.id === measurementId
          ? {
              ...m,
              linkedPositionId: undefined,
              linkedPositionOrdinal: undefined,
              linkedBoqId: undefined,
              linkedPositionLabel: undefined,
            }
          : m,
      ));
      addToast({
        type: 'success',
        title: t('takeoff.unlinked', { defaultValue: 'Unlinked from BOQ' }),
      });
      setLinkingMeasurementId(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff.unlink_failed', { defaultValue: 'Unlink failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [measurements, addToast, t]);

  /** Jump into the BOQ editor focused on the linked position. */
  const handleOpenLinkedPosition = useCallback((m: Measurement) => {
    if (!m.linkedBoqId || !m.linkedPositionId) return;
    // Absolute navigation; takeoff is embedded under /takeoff route.
    openLink(`/boq/${m.linkedBoqId}?highlight=${m.linkedPositionId}`);
  }, []);

  /** Ledger row click → navigate to the measurement.  Switch to its page
   *  if it's on a different one, select it, and (if the Properties tab
   *  is more useful at that point) leave the user on Ledger so they can
   *  click the next row without losing context. */
  const handleLedgerRowClick = useCallback((m: Measurement) => {
    // Defensive clamp: server-stored measurements may have page=0 from older
    // imports.  Snapping to the valid 1..totalPages range avoids pushing
    // currentPage to 0 (which would render an empty viewport + "0/N" header).
    const target = Math.max(1, Math.min(m.page || 1, totalPages || 1));
    if (target !== currentPage) {
      setCurrentPage(target);
    }
    setSelectedMeasurementId(m.id);
  }, [currentPage, totalPages]);

  /* ── Cross-module linking (takeoff -> RFI) ───────────────────────────
   * Open the "Create RFI from measurement" dialog. A measurement can only
   * be the "file" side of a cross-entity reference once it has synced (it
   * needs a durable serverId), so an unsynced row is bounced with a hint to
   * save first rather than silently failing. */
  const openRfiForMeasurement = useCallback(
    (m: Measurement) => {
      if (!m.serverId) {
        addToast({
          type: 'info',
          title: t('takeoff_crosslink.save_first', {
            defaultValue: 'Save the measurement first',
          }),
          message: t('takeoff_crosslink.save_first_msg', {
            defaultValue:
              'This measurement has not synced yet. Save it, then create the RFI.',
          }),
        });
        return;
      }
      setRfiMeasurement(m);
    },
    [addToast, t],
  );

  /* ── Ledger → BOQ actions ─────────────────────────────────────────── */

  /** Per-row "Add to BOQ" from the Ledger tab. Reuses the inline link
   *  picker that lives in the Properties-tab measurement list: navigate
   *  to the measurement's page, select it, switch tabs and open the
   *  picker on it (pick-existing with push, or create-new). */
  const handleLedgerAddToBoq = useCallback((m: Measurement) => {
    setBulkAddMeasurements(null);
    handleLedgerRowClick(m);
    setSidebarTab('properties');
    // The inline picker renders inside the measurement's group section -
    // make sure that section is expanded or the picker would be invisible.
    const groupKey = m.group || 'General';
    setCollapsedGroups((prev) => {
      if (!prev.has(groupKey)) return prev;
      const next = new Set(prev);
      next.delete(groupKey);
      return next;
    });
    void handleOpenLinkToBoq(m.id);
  }, [handleLedgerRowClick, handleOpenLinkToBoq]);

  /** Bulk "Add all to BOQ" from the Ledger tab: stage the eligible rows
   *  and open the target-BOQ panel above the ledger. The ledger already
   *  filtered to linkable rows (measurable type, human-confirmed); here
   *  we additionally drop already-linked rows and empty values. */
  const handleLedgerAddAllToBoq = useCallback(async (ms: Measurement[]) => {
    const eligible = ms.filter(
      (m) => !m.linkedPositionId && Number.isFinite(m.value) && m.value > 0,
    );
    if (eligible.length === 0) {
      addToast({
        type: 'info',
        title: t('takeoff.bulk_add_none_title', { defaultValue: 'Nothing to add' }),
        message: t('takeoff.bulk_add_none_msg', {
          defaultValue:
            'Every filtered measurement is already linked to a BOQ position (or carries no value).',
        }),
      });
      return;
    }
    setLinkingMeasurementId(null);
    setBulkAddMeasurements(eligible);

    // Seed the project/BOQ pickers exactly like the per-measurement picker.
    const seedProject = selectedProjectId || activeProjectId || '';
    const seedBoq = (selectedProjectId ? selectedBoqId : '') || (activeProjectId ? activeBoqIdFromStore ?? '' : '') || '';
    setLinkPickerProjectId(seedProject);
    setLinkPickerBoqId(seedBoq);
    try {
      const projects = await apiGet<{ id: string; name: string }[]>('/v1/projects/');
      setLinkPickerProjects(projects);
    } catch {
      setLinkPickerProjects([]);
    }
    if (seedProject) {
      await loadPickerBoqs(seedProject);
    } else {
      setLinkPickerBoqs([]);
    }
  }, [addToast, t, selectedProjectId, selectedBoqId, activeProjectId, activeBoqIdFromStore, loadPickerBoqs]);

  /** Confirm the bulk add: one bulk-create call into the picked BOQ (the
   *  same ``positions/bulk/`` endpoint the Takeoff page uses, returning
   *  the created positions in input order), then link each measurement to
   *  its new position with ``pushQuantity`` so the server-side value
   *  stays authoritative. */
  const handleBulkAddConfirm = useCallback(async () => {
    if (!bulkAddMeasurements || bulkAddMeasurements.length === 0 || !linkPickerBoqId) return;
    setLinkingInProgress(true);
    try {
      const items = bulkAddMeasurements.map((m) => ({
        description: m.annotation || t('takeoff.position_default_desc', {
          defaultValue: 'Takeoff · {{type}} page {{page}}',
          type: m.type,
          page: m.page,
        }),
        quantity: boqQuantity(m.value),
        unit: normalizeUnit(m.unit),
        source: 'takeoff',
        metadata: {
          takeoff_raw_unit: m.unit,
          pdf_measurement_source: `Takeoff: ${m.annotation || m.type} (page ${m.page})`,
          pdf_measurement_id: m.serverId ?? m.id,
          pdf_document_id: fileName ?? undefined,
          pdf_page: m.page,
        },
      }));
      const created = await apiPost<Position[]>(
        `/v1/boq/boqs/${linkPickerBoqId}/positions/bulk/`,
        { items },
      );

      // The bulk endpoint drops rows that fail validation and returns only
      // the inserted positions, so when the response is shorter an index
      // zip would link measurement i to a NEIGHBOR's position - silently
      // wrong quantities. Match by the measurement id we stamped into each
      // position's metadata instead; index matching stays only as the
      // fallback for an equal-length response.
      const sameLength = created.length === bulkAddMeasurements.length;
      const createdByMeasurementId = new Map<string, Position>();
      for (const pos of created) {
        const meta = (pos.metadata ?? pos.metadata_) as Record<string, unknown> | undefined;
        const mid = meta?.pdf_measurement_id;
        if (typeof mid === 'string') createdByMeasurementId.set(mid, pos);
      }

      // Link measurements to their new positions (and push the quantity
      // server-side). A per-item failure only degrades the back-link -
      // the position already exists with the measured quantity.
      let linkFailures = 0;
      const createdByMeasurement = new Map<string, Position>();
      for (let i = 0; i < bulkAddMeasurements.length; i += 1) {
        const m = bulkAddMeasurements[i]!;
        const pos = createdByMeasurementId.get(m.serverId ?? m.id) ?? (sameLength ? created[i] : undefined);
        if (!pos) continue;
        createdByMeasurement.set(m.id, pos);
        if (m.serverId) {
          try {
            await takeoffApi.linkToBoq(m.serverId, pos.id, { pushQuantity: true });
          } catch {
            linkFailures += 1;
          }
        }
      }

      // Reflect the new links locally so the ledger badges flip at once.
      setMeasurements((prev) => prev.map((m) => {
        const pos = createdByMeasurement.get(m.id);
        if (!pos) return m;
        return {
          ...m,
          linkedPositionId: pos.id,
          linkedPositionOrdinal: pos.ordinal,
          linkedBoqId: pos.boq_id,
          linkedPositionLabel: pos.description,
        };
      }));

      queryClient.invalidateQueries({ queryKey: ['boq', linkPickerBoqId] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });

      const first = created[0];
      addToast({
        type: 'success',
        title: t('takeoff.bulk_add_success_title', { defaultValue: 'Added to BOQ' }),
        message: t('takeoff.bulk_add_success_msg', {
          defaultValue: '{{count}} positions created, starting at {{first}}',
          count: created.length,
          first: first ? `${first.ordinal} ${first.description?.slice(0, 30) ?? ''}`.trim() : '',
        }),
      });
      if (linkFailures > 0) {
        addToast({
          type: 'warning',
          title: t('takeoff.bulk_link_partial_title', { defaultValue: 'Some links failed' }),
          message: t('takeoff.bulk_link_partial_msg', {
            defaultValue:
              '{{count}} measurements could not be linked back to their new positions. The positions were still created with the measured quantities.',
            count: linkFailures,
          }),
        });
      }
      setBulkAddMeasurements(null);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('takeoff.bulk_add_failed', { defaultValue: 'Add to BOQ failed' }),
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setLinkingInProgress(false);
    }
  }, [bulkAddMeasurements, linkPickerBoqId, normalizeUnit, fileName, addToast, t, queryClient]);

  /* ── Undo ────────────────────────────────────────────────────────── */

  const handleUndo = useCallback(() => {
    const stack = undoStackRef.current;
    if (stack.length === 0) return;
    const op = stack.pop()!;
    setUndoCount(stack.length);

    // Push onto the redo stack BEFORE applying the reversal, so that
    // Redo can re-issue the operation.  For `change_annotation` we
    // capture the CURRENT (pre-revert) annotation text below so redo
    // can swap it back.
    let forwardOp: UndoOperation = op;

    switch (op.kind) {
      case 'add_point':
        // Remove the last point from the in-progress measurement
        setActivePoints((prev) => prev.slice(0, -1));
        break;

      case 'complete_measurement':
        // Remove the completed measurement and restore active points. If the
        // measurement was already synced (the 3s debounce fired before the
        // undo), queue the server-side delete too so undoing a create does not
        // leave an orphan that resurrects on reload (issue #282).
        setMeasurements((prev) => {
          const live = prev.find((m) => m.id === op.measurement.id);
          if (live?.serverId) registerDeletion(live.serverId);
          return prev.filter((m) => m.id !== op.measurement.id);
        });
        setActivePoints(op.previousActivePoints);
        // Clear selection if we undid its creation
        setSelectedMeasurementId((sel) => (sel === op.measurement.id ? null : sel));
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

      case 'change_annotation': {
        // Grab the current (about-to-be-overwritten) annotation so redo
        // can replay the forward delta by swapping again.
        setMeasurements((prev) => {
          const target = prev.find((m) => m.id === op.measurementId);
          if (target) {
            forwardOp = {
              kind: 'change_annotation',
              measurementId: op.measurementId,
              previousAnnotation: target.annotation,
            };
          }
          return prev.map((m) =>
            m.id === op.measurementId ? { ...m, annotation: op.previousAnnotation } : m,
          );
        });
        break;
      }

      case 'edit_geometry':
        // Restore the pre-edit measurement (geometry + derived value/label).
        // The persistence effect re-PATCHes the restored points so the
        // server re-derives the billed quantity and stays authoritative.
        setMeasurements((prev) =>
          prev.map((m) =>
            m.id === op.measurementId
              ? { ...op.previousMeasurement, points: [...op.previousMeasurement.points] }
              : m,
          ),
        );
        break;
    }

    // Push the (possibly-adjusted) forward op onto redo.
    redoStackRef.current.push(forwardOp);
    setRedoCount(redoStackRef.current.length);

    addToast({ type: 'info', title: t('takeoff.undo', { defaultValue: 'Undo' }), message: t('takeoff.measurement_undone', { defaultValue: 'Measurement undone' }) });
  }, [addToast, t, registerDeletion]);

  /** Re-apply the most recently undone operation. */
  const handleRedo = useCallback(() => {
    const stack = redoStackRef.current;
    if (stack.length === 0) return;
    const op = stack.pop()!;
    setRedoCount(stack.length);

    let reverseOp: UndoOperation = op;

    switch (op.kind) {
      case 'add_point':
        setActivePoints((prev) => [...prev, op.point]);
        break;

      case 'complete_measurement':
        setMeasurements((prev) => [...prev, op.measurement]);
        setActivePoints([]);
        break;

      case 'add_count_point':
        if (op.wasNew) {
          // Re-create the count measurement.  Use the previousMeasurement
          // snapshot plus the new point, or build a minimal one.
          const base = op.previousMeasurement ?? null;
          const restoredPoints = base ? [...base.points, op.point] : [op.point];
          const restored: Measurement = base
            ? { ...base, points: restoredPoints, value: restoredPoints.length }
            : {
                id: op.measurementId,
                type: 'count',
                points: [op.point],
                value: 1,
                unit: 'pcs',
                label: countLabel,
                annotation: '',
                page: currentPage,
                group: activeGroup,
              };
          setMeasurements((prev) => [...prev, restored]);
        } else {
          setMeasurements((prev) =>
            prev.map((m) => {
              if (m.id !== op.measurementId) return m;
              const nextPoints = [...m.points, op.point];
              return { ...m, points: nextPoints, value: nextPoints.length };
            }),
          );
        }
        break;

      case 'delete_measurement':
        // Re-queue the server-side delete (issue #282): an undo cancelled it
        // by restoring the row, so redoing the delete must remove it again.
        // Look up the live row to read the serverId it may have gained after
        // the original snapshot was taken.
        setMeasurements((prev) => {
          const live = prev.find((m) => m.id === op.measurement.id);
          if (live?.serverId) registerDeletion(live.serverId);
          return prev.filter((m) => m.id !== op.measurement.id);
        });
        setSelectedMeasurementId((sel) => (sel === op.measurement.id ? null : sel));
        break;

      case 'change_annotation': {
        // Swap annotations again — capture the current value so a
        // subsequent undo can revert this redo.
        setMeasurements((prev) => {
          const target = prev.find((m) => m.id === op.measurementId);
          if (target) {
            reverseOp = {
              kind: 'change_annotation',
              measurementId: op.measurementId,
              previousAnnotation: target.annotation,
            };
          }
          return prev.map((m) =>
            m.id === op.measurementId ? { ...m, annotation: op.previousAnnotation } : m,
          );
        });
        break;
      }

      case 'edit_geometry':
        // Re-apply the post-edit measurement.
        setMeasurements((prev) =>
          prev.map((m) =>
            m.id === op.measurementId
              ? { ...op.nextMeasurement, points: [...op.nextMeasurement.points] }
              : m,
          ),
        );
        break;
    }

    // Push the reverse op onto undo so Ctrl+Z works again.
    undoStackRef.current.push(reverseOp);
    setUndoCount(undoStackRef.current.length);

    addToast({
      type: 'info',
      title: t('takeoff.redo', { defaultValue: 'Redo' }),
      message: t('takeoff.measurement_redone', { defaultValue: 'Measurement redone' }),
    });
  }, [addToast, t, countLabel, currentPage, activeGroup, registerDeletion]);

  /** Unified tool-switch logic (shared between toolbar buttons + shortcuts). */
  const selectTool = useCallback((tool: MeasureTool) => {
    // Only react to an ACTUAL tool change (#356). V maps to select, so pressing
    // it during a select-tool drag must not cancel the edit; and it is the
    // change of tool that makes a trailing click land in a different tool.
    if (tool !== activeTool) {
      // Abandon an in-flight vertex/shape edit rather than committing it at a
      // position the canvas stopped showing the instant the tool changed. Same
      // no-undo-frame abandon path Escape uses.
      if (dragRef.current) finishDrag(false);
      // Suppress the click this held press will still emit on release, so it is
      // not consumed as a placement by the tool just selected. Keyed on the
      // live press, not on dragRef (Escape can null dragRef mid-press).
      if (pressActiveRef.current) suppressNextClickRef.current = true;
    }
    setActiveTool(tool);
    setActivePoints([]);
    setRectStartPoint(null);
    setIsDraggingRect(false);
    setShowTextInput(false);
    // Switching tools also cancels an in-progress two-click calibration pick,
    // mirroring the Escape handler. Without this the calibration stays armed
    // and its click branch eats the next click on the newly selected tool (#344).
    setSettingScale(false);
    setCalibrationMode(false);
    setScalePoints([]);
    // Drop any calibration/draw live preview so no rubber-band or snap ring is
    // left frozen when the tool changes (#367).
    setLiveCursor(null);
    setSnapPoint(null);
    if (isAnnotationTool(tool)) {
      setAnnotationColor(DEFAULT_ANNOTATION_COLORS[tool]);
    }
  }, [activeTool, finishDrag]);

  /** Keyboard shortcuts: per-tool letters, Ctrl+Z/Y redo/undo, Esc cancel,
   *  Space (pan), Shift (ortho lock), Shift+1/2/3 (fit width / page /
   *  selection). */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Track the live Shift state so the draw path can engage ortho without
      // flipping the persistent toggle. Updated on every keydown regardless of
      // focus so it never goes stale.
      shiftHeldRef.current = e.shiftKey;

      // Undo / Redo — handled even inside inputs (standard browser semantics).
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        handleRedo();
        return;
      }

      // Ctrl/Cmd+D: duplicate the selected measurement (issue #302). Gated on
      // the same focus guard as the tool letters so it never fires while typing
      // in the properties panel; preventDefault suppresses the browser bookmark
      // default when it does apply.
      if (
        (e.ctrlKey || e.metaKey) &&
        !e.shiftKey &&
        !e.altKey &&
        e.key.toLowerCase() === 'd' &&
        shouldHandleShortcut(e.target)
      ) {
        e.preventDefault();
        if (selectedMeasurementId) duplicateMeasurement(selectedMeasurementId);
        return;
      }

      // Esc: cancel any in-progress drawing + deselect any selected measurement
      if (e.key === 'Escape') {
        // Close an open context menu first (issue #302).
        if (contextMenuRef.current) {
          setContextMenu(null);
          return;
        }
        // Abort an in-flight in-canvas edit drag first (restore geometry,
        // no undo frame) - the user is bailing out of a reshape.
        if (dragRef.current) {
          finishDrag(false);
          return;
        }
        if (calibrationMode || settingScale) {
          // Bail out of two-click pick mode cleanly.
          setCalibrationMode(false);
          setSettingScale(false);
          setScalePoints([]);
          // Clear the live preview so nothing is left frozen on the canvas (#367).
          setLiveCursor(null);
          setSnapPoint(null);
          return;
        }
        // Leave sticky pan mode (#316), mirroring a second click on the toggle.
        if (panLockRef.current) {
          setPanLock(false);
          return;
        }
        if (activePoints.length > 0 || rectStartPoint !== null || showTextInput || showScaleDialog || showVolumeDepthInput) {
          // First Esc on a drawing tool cancels the in-progress shape.
          setActivePoints([]);
          setRectStartPoint(null);
          setIsDraggingRect(false);
          setShowTextInput(false);
          setTextInputValue('');
          // Don't close dialogs here - they have their own handlers.
          return;
        }
        if (selectedMeasurementId) {
          setSelectedMeasurementId(null);
          return;
        }
        // Nothing in progress and nothing selected: disarm the active drawing
        // or markup tool back to Select. This gives every tool a uniform
        // two-step bail-out (Esc cancels the shape, a second Esc disarms) and
        // delivers what the Count hint already promises: Count commits on every
        // click and has no in-progress shape, so its first Esc lands here (#307).
        if (activeTool !== 'select') {
          selectTool('select');
        }
        return;
      }

      // Enter: finish an in-progress multi-point measurement (polyline, area,
      // volume, cloud) under the same minimum-point rules as a double-click or
      // right-click, so committing never depends on pointer precision or
      // double-click timing (#308). Handled before the focus guard is applied
      // to the tool letters, but only when focus is not in a field (guarded
      // just below), so typing a label or depth still gets a normal Enter.
      if (e.key === 'Enter' && shouldHandleShortcut(e.target)) {
        if (
          (activeTool === 'polyline' && activePoints.length >= 2) ||
          ((activeTool === 'area' || activeTool === 'volume' || activeTool === 'cloud') &&
            activePoints.length >= 3)
        ) {
          e.preventDefault();
          handleCanvasDblClick();
          return;
        }
        // Count commits per click and has no in-progress shape, so Enter instead
        // moves focus to the Count Label field and selects it, so the next label
        // can be typed and the following clicks start a fresh count group instead
        // of appending to the one just finished (#307/#308).
        if (activeTool === 'count') {
          e.preventDefault();
          const focusCountLabel = () => {
            countLabelRef.current?.focus();
            countLabelRef.current?.select();
          };
          // The Count Label input lives in the right sidebar, which #315 can
          // collapse with display:none - a hidden element cannot take focus, so
          // the shortcut was a silent no-op when the panel was closed. Expand
          // the panel first, then focus once it has rendered on the next frame.
          if (!showSidebarRef.current) {
            setShowSidebar(true);
            requestAnimationFrame(focusCountLabel);
          } else {
            focusCountLabel();
          }
          return;
        }
      }

      // Tool letters — only when focus isn't in an input / textarea / etc.
      if (!shouldHandleShortcut(e.target)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      // Space: arm pan (grab cursor + suppress click-to-place). preventDefault
      // so the page does not scroll while Space is held over the canvas.
      if (e.code === 'Space' || e.key === ' ') {
        e.preventDefault();
        if (!spaceHeldRef.current) {
          spaceHeldRef.current = true;
          setSpaceHeld(true);
        }
        return;
      }

      // Fit shortcuts (Shift+1 / Shift+2 / Shift+3). Digit codes are used so
      // the binding is layout-stable. These do not collide with the
      // single-letter tool shortcuts (see takeoff-shortcuts.ts).
      if (e.shiftKey && (e.code === 'Digit1' || e.code === 'Digit2' || e.code === 'Digit3')) {
        e.preventDefault();
        if (e.code === 'Digit1') fitToViewport('width');
        else if (e.code === 'Digit2') fitToViewport('page');
        else zoomToSelection();
        return;
      }

      // Delete / Backspace. If a specific vertex is active on the selected
      // measurement and removing it keeps the shape valid, delete just that
      // vertex and recompute (#194). Otherwise fall through to deleting the
      // whole measurement, preserving the long-standing "select row, press
      // Delete" flow.
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedMeasurementId) {
        e.preventDefault();
        const active = activeVertexRef.current;
        const target = measurements.find((m) => m.id === selectedMeasurementId);
        if (
          target &&
          active &&
          active.measurementId === selectedMeasurementId &&
          supportsVariableVertices(target.type) &&
          target.points.length > minVertices(target.type) &&
          active.index < target.points.length
        ) {
          const nextPoints = deleteVertexAt(target.points, active.index);
          commitGeometryEdit(selectedMeasurementId, { ...target, points: [...target.points] }, nextPoints);
          activeVertexRef.current = null;
          return;
        }
        setMeasurements((prev) => {
          const t2 = prev.find((m) => m.id === selectedMeasurementId);
          if (t2) pushUndo({ kind: 'delete_measurement', measurement: t2 });
          return prev.filter((m) => m.id !== selectedMeasurementId);
        });
        activeVertexRef.current = null;
        setSelectedMeasurementId(null);
        return;
      }

      const tool = shortcutToTool(e.key);
      if (tool) {
        e.preventDefault();
        selectTool(tool);
      }
    };
    const upHandler = (e: KeyboardEvent) => {
      shiftHeldRef.current = e.shiftKey;
      if (e.code === 'Space' || e.key === ' ') {
        spaceHeldRef.current = false;
        setSpaceHeld(false);
        // A pan that was mid-drag when Space released ends cleanly.
        if (panRef.current) {
          panRef.current = null;
          setPanning(false);
        }
      }
    };
    // A window blur (alt-tab) would otherwise strand the Space/Shift held
    // state on, leaving a stuck grab cursor / ortho lock.
    const blurHandler = () => {
      shiftHeldRef.current = false;
      spaceHeldRef.current = false;
      setSpaceHeld(false);
      // A button released in another application delivers no mouseup to this
      // window, so tear down every in-flight gesture keyed on a held button
      // (#356). Each is independent and any of them can be armed at once, so do
      // not return early between them.
      if (dragRef.current) finishDrag(false); // abandon, no undo frame (like Escape)
      if (panRef.current) {
        panRef.current = null;
        setPanning(false); // leave panLock alone: it is a mode, not a gesture
      }
      pressActiveRef.current = false;
      suppressNextClickRef.current = false;
    };
    window.addEventListener('keydown', handler);
    window.addEventListener('keyup', upHandler);
    window.addEventListener('blur', blurHandler);
    return () => {
      window.removeEventListener('keydown', handler);
      window.removeEventListener('keyup', upHandler);
      window.removeEventListener('blur', blurHandler);
    };
  }, [handleUndo, handleRedo, selectTool, activeTool, activePoints.length, rectStartPoint, showTextInput, showScaleDialog, showVolumeDepthInput, selectedMeasurementId, calibrationMode, settingScale, measurements, finishDrag, commitGeometryEdit, pushUndo, fitToViewport, zoomToSelection, duplicateMeasurement, handleCanvasDblClick]);

  /* ── Render ──────────────────────────────────────────────────────── */

  /* ── Landing features (BIM-style) ──────────────────────────── */

  const landingFeatures = [
    {
      icon: Crosshair,
      color: 'bg-blue-50 dark:bg-blue-950/20 border-blue-100 dark:border-blue-800',
      ic: 'text-blue-500',
      title: t('takeoff.landing_feat_click_title', { defaultValue: 'Click-to-measure' }),
      desc: t('takeoff.landing_feat_click_desc', { defaultValue: 'Distance, area, polyline and count tools - click directly on the PDF to capture quantities.' }),
    },
    {
      icon: Scan,
      color: 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-100 dark:border-emerald-800',
      ic: 'text-emerald-500',
      title: t('takeoff.landing_feat_extract_title', { defaultValue: 'AI text & table extraction' }),
      desc: t('takeoff.landing_feat_extract_desc', { defaultValue: 'Pull schedules and BOQ tables straight out of the PDF text - each row comes back with a confidence score to review.' }),
    },
    {
      icon: Ruler,
      color: 'bg-violet-50 dark:bg-violet-950/20 border-violet-100 dark:border-violet-800',
      ic: 'text-violet-500',
      title: t('takeoff.landing_feat_scale_title', { defaultValue: 'Scale calibration' }),
      desc: t('takeoff.landing_feat_scale_desc', { defaultValue: 'Two-point calibration or preset scales (1:50, 1:100) - every measurement stays accurate.' }),
    },
    {
      icon: Layers,
      color: 'bg-orange-50 dark:bg-orange-950/20 border-orange-100 dark:border-orange-800',
      ic: 'text-orange-500',
      title: t('takeoff.landing_feat_units_title', { defaultValue: 'Area · length · count' }),
      desc: t('takeoff.landing_feat_units_desc', { defaultValue: 'Switch freely between m, m², m³, pcs - grouped by trade with hide/show per layer.' }),
    },
    {
      icon: Sparkles,
      color: 'bg-pink-50 dark:bg-pink-950/20 border-pink-100 dark:border-pink-800',
      ic: 'text-pink-500',
      title: t('takeoff.landing_feat_ai_title', { defaultValue: 'AI-assisted quantities' }),
      desc: t('takeoff.landing_feat_ai_desc', { defaultValue: 'Let the AI extract walls, slabs and rooms from a drawing - you review and confirm before committing.' }),
    },
    {
      icon: Link2,
      color: 'bg-cyan-50 dark:bg-cyan-950/20 border-cyan-100 dark:border-cyan-800',
      ic: 'text-cyan-500',
      title: t('takeoff.landing_feat_export_title', { defaultValue: 'Export to BOQ' }),
      desc: t('takeoff.landing_feat_export_desc', { defaultValue: 'Send measurements straight into your Bill of Quantities - with links back to the source drawing.' }),
    },
  ];

  const landingFormats = [
    { ext: 'PDF', label: t('takeoff.landing_fmt_pdf', { defaultValue: 'Vector drawings, floor plans, sections' }), icon: FileText, primary: true, muted: false },
    { ext: 'DWG', label: t('takeoff.landing_fmt_dwg', { defaultValue: 'Use DWG Takeoff module instead' }), icon: Box, primary: false, muted: true },
  ];

  return (
    <div className="relative flex flex-1 min-h-0 flex-col space-y-4">
      {/* Decorative field-surveyor geometry — rectangles and polylines
          like what an estimator drags across a drawing to measure
          area or perimeter.  Very low opacity, behind everything,
          pointer-events disabled so it never interferes. */}
      <svg
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 w-full h-full text-slate-500 dark:text-slate-400"
        preserveAspectRatio="xMidYMid slice"
        viewBox="0 0 1600 1000"
      >
        <defs>
          <linearGradient id="tkoFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0.3" />
            <stop offset="40%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0.15" />
          </linearGradient>
          <mask id="tkoMask">
            <rect width="1600" height="1000" fill="url(#tkoFade)" />
          </mask>
        </defs>
        <g mask="url(#tkoMask)" opacity="0.07" fill="none" stroke="currentColor" strokeWidth="1.1">
          {/* Rectangle A — top-left, dashed outline w/ vertex handles */}
          <rect x="110" y="90" width="280" height="170" strokeDasharray="8 6" />
          <circle cx="110" cy="90" r="4" fill="currentColor" />
          <circle cx="390" cy="90" r="4" fill="currentColor" />
          <circle cx="390" cy="260" r="4" fill="currentColor" />
          <circle cx="110" cy="260" r="4" fill="currentColor" />
          <text x="250" y="180" textAnchor="middle" fill="currentColor" stroke="none" fontSize="14" fontFamily="ui-monospace,monospace" opacity="0.6">47.6 m²</text>

          {/* Polygon B — irregular room outline with vertex handles */}
          <polygon points="820,120 1080,140 1180,260 1140,390 940,430 820,340 760,230" strokeDasharray="6 4" />
          {([
            [820, 120], [1080, 140], [1180, 260], [1140, 390], [940, 430], [820, 340], [760, 230],
          ] as [number, number][]).map(([x, y], i) => <circle key={i} cx={x} cy={y} r="3.5" fill="currentColor" />)}
          <text x="960" y="290" textAnchor="middle" fill="currentColor" stroke="none" fontSize="13" fontFamily="ui-monospace,monospace" opacity="0.55">83.2 m²</text>

          {/* Distance line C — two endpoints + dimension text */}
          <g strokeDasharray="3 3">
            <line x1="1280" y1="130" x2="1540" y2="200" />
            <line x1="1275" y1="120" x2="1285" y2="140" strokeDasharray="0" strokeWidth="2" />
            <line x1="1535" y1="190" x2="1545" y2="210" strokeDasharray="0" strokeWidth="2" />
          </g>
          <text x="1410" y="155" textAnchor="middle" fill="currentColor" stroke="none" fontSize="12" fontFamily="ui-monospace,monospace" opacity="0.55">12.43 m</text>

          {/* Polyline D — open path like a wall run with vertex handles */}
          <polyline points="140,620 260,560 380,620 520,560 640,640" />
          {([
            [140, 620], [260, 560], [380, 620], [520, 560], [640, 640],
          ] as [number, number][]).map(([x, y], i) => <rect key={i} x={x - 3} y={y - 3} width="6" height="6" fill="currentColor" />)}

          {/* Rectangle E — bottom right, solid dashed outline */}
          <rect x="1080" y="620" width="360" height="220" strokeDasharray="8 6" />
          {([[1080, 620], [1440, 620], [1440, 840], [1080, 840]] as [number, number][]).map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="4" fill="currentColor" />
          ))}
          <text x="1260" y="740" textAnchor="middle" fill="currentColor" stroke="none" fontSize="14" fontFamily="ui-monospace,monospace" opacity="0.55">79.2 m²</text>

          {/* Polygon F — low-angle quad on mid-left */}
          <polygon points="60,440 270,460 320,640 90,630" strokeDasharray="4 4" />
          {([[60, 440], [270, 460], [320, 640], [90, 630]] as [number, number][]).map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="3" fill="currentColor" />
          ))}

          {/* Scale tick ruler bottom-center (stylised) */}
          <g>
            <line x1="660" y1="920" x2="940" y2="920" strokeWidth="1" />
            {Array.from({ length: 11 }).map((_, i) => (
              <line
                key={i}
                x1={660 + i * 28}
                y1={i % 2 === 0 ? 912 : 916}
                x2={660 + i * 28}
                y2="928"
                strokeWidth="1"
              />
            ))}
          </g>

          {/* Tiny vertex-count pins scattered — estimator's clicked points */}
          {([
            [480, 200], [540, 260], [700, 360], [1240, 500], [960, 820], [200, 780], [1500, 520],
          ] as [number, number][]).map(([x, y], i) => (
            <g key={i}>
              <circle cx={x} cy={y} r="4" fill="currentColor" opacity="0.45" />
              <circle cx={x} cy={y} r="9" stroke="currentColor" strokeWidth="0.6" />
            </g>
          ))}
        </g>
      </svg>

      {/* Header removed — the parent TakeoffPage already shows the page
          title / subtitle, so the duplicate is pure noise. */}

      {/* Landing (BIM-style) — when no PDF loaded */}
      {!pdfDoc && (
        <div className="-mx-4 sm:-mx-7 -mt-6 -mb-6 min-h-full bg-gradient-to-br from-slate-50 via-white to-blue-50/50 dark:from-gray-900 dark:via-gray-900 dark:to-blue-950/20">
          <div className="max-w-7xl mx-auto px-6 pt-8 pb-6">

            {/* Row 1: Upload card (left) + Hero text (right) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch mb-5">

              {/* LEFT — Upload card */}
              <div className="flex flex-col">
                <div className="rounded-2xl bg-white dark:bg-gray-800/60 border border-border-light shadow-lg shadow-black/5 dark:shadow-black/20 p-4 flex flex-col h-full">
                  <label
                    aria-label={t('takeoff.landing_dropzone_aria', { defaultValue: 'Drop a PDF here or click to browse.' })}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('ring-2', 'ring-oe-blue/40'); }}
                    onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove('ring-2', 'ring-oe-blue/40'); }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      e.currentTarget.classList.remove('ring-2', 'ring-oe-blue/40');
                      const dropped = Array.from(e.dataTransfer.files);
                      if (dropped.length === 0) return;
                      const pdf = dropped.find((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
                      if (pdf) {
                        const fakeEvent = { target: { files: [pdf] } } as unknown as React.ChangeEvent<HTMLInputElement>;
                        handleFileUpload(fakeEvent);
                      } else {
                        // Visible feedback so the user isn't left wondering why a non-PDF drop did nothing.
                        addToast({
                          type: 'warning',
                          title: t('takeoff.landing_drop_pdf_only_title', { defaultValue: 'PDF only' }),
                          message: t('takeoff.landing_drop_pdf_only_msg', { defaultValue: 'This viewer measures PDF drawings. Drop a PDF file to get started.' }),
                        });
                      }
                    }}
                    className="group/drop flex flex-col items-center justify-center gap-3 rounded-xl p-6 text-center cursor-pointer transition-all flex-1 border-2 border-dashed border-border-medium bg-gradient-to-br from-blue-50/60 via-white to-violet-50/40 dark:from-blue-950/20 dark:via-gray-800/40 dark:to-violet-950/20 hover:border-oe-blue/50 hover:shadow-md"
                  >
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-oe-blue/10 to-violet-500/10 flex items-center justify-center group-hover/drop:scale-110 transition-transform">
                      <FileUp size={26} className="text-oe-blue" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('takeoff.landing_drop_here', { defaultValue: 'Drop a PDF here or click to browse' })}
                      </p>
                      <p className="text-xs text-content-tertiary mt-1">
                        {t('takeoff.landing_size_hint', { defaultValue: 'Vector or scanned PDF drawings' })}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap justify-center">
                      <span className="text-[10px] font-mono px-2 py-1 rounded-md bg-oe-blue/8 text-oe-blue border border-oe-blue/15 font-semibold">.pdf</span>
                    </div>
                    <p className="text-[10px] text-content-quaternary leading-relaxed mt-1 text-center">
                      {t('takeoff.landing_dropzone_hint', { defaultValue: 'Architectural drawings \u00B7 floor plans \u00B7 sections \u00B7 scans' })}
                    </p>
                    <input type="file" accept="application/pdf" onChange={handleFileUpload} className="hidden" />
                  </label>
                </div>

                {/* Recent drawings — previously uploaded PDFs for this
                    project, so the estimator can reopen one in a click
                    instead of re-uploading the same file. */}
                {recentDocuments && recentDocuments.length > 0 && (
                  <div className="mt-4">
                    <h2 className="text-[10px] font-bold text-content-tertiary uppercase tracking-widest mb-2">
                      {t('takeoff.landing_recent_drawings', { defaultValue: 'Recent drawings' })}
                    </h2>
                    <ul className="space-y-1.5">
                      {recentDocuments.slice(0, 5).map((doc) => (
                        <li key={doc.id}>
                          <button
                            type="button"
                            onClick={() => onOpenRecentDocument?.(doc.id)}
                            className="group/recent flex w-full items-center gap-2.5 rounded-lg border border-border-light/60 bg-white dark:bg-gray-800/40 px-2.5 py-2 text-left transition-all hover:border-oe-blue/40 hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                          >
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-light bg-surface-secondary text-content-tertiary group-hover/recent:text-oe-blue">
                              <FileText size={13} />
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-[11px] font-semibold text-content-primary">
                                {doc.filename}
                              </p>
                              <p className="text-[10px] text-content-tertiary">
                                {doc.pages > 0
                                  ? `${doc.pages} ${t('takeoff.pages_short', { defaultValue: 'p' })} · `
                                  : ''}
                                {formatFileSize(doc.size_bytes)}
                              </p>
                            </div>
                            <ChevronRight
                              size={13}
                              className="shrink-0 text-content-quaternary group-hover/recent:text-oe-blue"
                            />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* RIGHT — Hero text + supported formats cards */}
              <div className="flex flex-col justify-center gap-4">
                <div>
                  <h2 className="text-2xl font-bold text-content-primary tracking-tight leading-tight">
                    {t('takeoff.landing_hero_title', { defaultValue: 'PDF Takeoff' })}
                  </h2>
                  <p className="text-base text-content-secondary mt-3 leading-relaxed">
                    {t('takeoff.landing_hero_subtitle', {
                      defaultValue: 'Click-to-measure on any drawing \u2014 lengths, areas, counts \u2014 with AI that suggests quantities and sends them straight into your BOQ.',
                    })}
                  </p>
                </div>

                {/* Supported formats — compact cards tucked right under the
                    hero subtitle.  Used to live in its own full-width row
                    below; pulling it up here keeps the formats-at-a-glance
                    without the redundant textual line. */}
                <div>
                  <h2 className="text-[10px] font-bold text-content-tertiary uppercase tracking-widest mb-2">
                    {t('takeoff.landing_supported_formats', { defaultValue: 'Supported formats' })}
                  </h2>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {landingFormats.map((f, i) => (
                      <div
                        key={i}
                        className={`flex items-start gap-2 rounded-lg p-2 bg-white dark:bg-gray-800/40 border transition-all ${
                          f.primary
                            ? 'border-oe-blue/30 shadow-sm ring-1 ring-oe-blue/10'
                            : f.muted
                              ? 'border-border-light/60 opacity-70'
                              : 'border-border-light/60 hover:border-border-light hover:shadow-sm'
                        }`}
                      >
                        <div
                          className={`w-7 h-7 rounded-md border flex items-center justify-center shrink-0 ${
                            f.primary
                              ? 'bg-oe-blue/10 border-oe-blue/20 text-oe-blue'
                              : 'bg-surface-secondary border-border-light text-content-tertiary'
                          }`}
                        >
                          <f.icon size={13} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1">
                            <span className={`text-[11px] font-mono font-bold ${f.primary ? 'text-oe-blue' : 'text-content-primary'}`}>
                              .{f.ext.toLowerCase()}
                            </span>
                            {f.primary && (
                              <span className="text-[8px] font-semibold uppercase tracking-wider text-oe-blue">
                                {t('takeoff.landing_fmt_primary', { defaultValue: 'Primary' })}
                              </span>
                            )}
                          </div>
                          <p className="text-[10px] text-content-tertiary leading-snug mt-0.5 truncate">{f.label}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Row 2: Feature cards */}
            <div>
              <h2 className="text-xs font-bold text-content-tertiary uppercase tracking-widest mb-2">
                {t('takeoff.landing_what_you_get', { defaultValue: 'What you get' })}
              </h2>
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                {landingFeatures.map((f, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 rounded-xl p-3 bg-white dark:bg-gray-800/40 border border-border-light/60 hover:border-border-light hover:shadow-sm transition-all"
                  >
                    <div className={`w-8 h-8 rounded-lg ${f.color} border flex items-center justify-center shrink-0`}>
                      <f.icon size={15} className={f.ic} />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-xs font-semibold text-content-primary leading-tight">{f.title}</h3>
                      <p className="text-[11px] text-content-tertiary leading-snug mt-1">{f.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      )}

      {/* Viewer + Sidebar (PDF on the left, Measurements panel on the right) */}
      {pdfDoc && (
        <div className="flex flex-1 min-h-0 gap-4 min-w-0">
          {/* Page thumbnails strip - only for multi-page sets and when toggled
              on. Click a thumbnail to jump; the current page is ringed; a badge
              shows that page's measurement count. */}
          {totalPages > 1 && showThumbnails && (
            <div
              className="w-32 shrink-0 min-h-0 overflow-y-auto rounded-lg border border-border bg-surface-primary p-2 space-y-2"
              data-testid="thumbnail-strip"
            >
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setCurrentPage(n)}
                  data-testid="thumbnail-item"
                  data-page={n}
                  data-current={n === currentPage}
                  aria-current={n === currentPage ? 'page' : undefined}
                  className={clsx(
                    'group block w-full overflow-hidden rounded border bg-white transition-colors',
                    n === currentPage
                      ? 'ring-2 ring-oe-blue border-oe-blue'
                      : 'border-border hover:border-oe-blue/60',
                  )}
                  title={t('takeoff_viewer.thumb_page', { defaultValue: 'Page {{n}}', n })}
                >
                  {thumbs[n] ? (
                    <img src={thumbs[n]} alt={t('takeoff_viewer.thumb_page', { defaultValue: 'Page {{n}}', n })} className="block w-full" />
                  ) : (
                    <div className="flex aspect-[1/1.4] items-center justify-center text-content-tertiary">
                      <Loader2 size={16} className="animate-spin" />
                    </div>
                  )}
                  <span className="flex items-center justify-between gap-1 px-1 py-0.5 text-[10px] text-content-secondary">
                    <span className="tabular-nums">{n}</span>
                    {countsByPage[n] ? (
                      <span className="tabular-nums rounded-full bg-purple-500/15 px-1 text-purple-500" data-testid="thumbnail-badge">
                        {countsByPage[n]}
                      </span>
                    ) : null}
                  </span>
                </button>
              ))}
            </div>
          )}
          {/* Left: PDF + Toolbar */}
          <div className="flex flex-1 min-w-0 min-h-0 flex-col space-y-2">
            {/* Toolbar - two grouped rows so every control stays visible
                without a horizontal scrollbar. Row 1 = navigate + view +
                document actions; row 2 = scale + drawing tools. Related
                controls sit in soft "segmented" tracks instead of being
                separated by hairline dividers. */}
            <div className="takeoff-toolbar flex shrink-0 flex-col gap-1.5 rounded-lg border border-border bg-surface-primary p-1.5 shadow-xs">
              <div className="flex items-center gap-1 flex-wrap">
              {/* Page nav - prev / jump / next in one segmented track. */}
              <div className={TB_GROUP}>
                <button onClick={prevPage} disabled={currentPage <= 1} className={tbBtn(false)} aria-label={t('takeoff_viewer.prev_page', { defaultValue: 'Previous page' })}>
                  <ChevronLeft size={16} />
                </button>
                <details className="relative shrink-0" data-testid="page-jump">
                  <summary className="inline-flex h-7 cursor-pointer list-none select-none items-center rounded-md px-2 text-xs font-medium tabular-nums text-content-secondary transition-colors hover:bg-surface-primary hover:text-content-primary" title={t('takeoff_viewer.jump_to_page', { defaultValue: 'Click to jump to a page' })}>
                    {currentPage}/{totalPages}
                  </summary>
                  {totalPages > 1 && (
                    <div className="absolute left-0 top-full mt-1 z-30 max-h-72 w-44 overflow-y-auto rounded-lg border border-border bg-surface-elevated shadow-lg p-1">
                      {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => {
                        const cnt = countsByPage[p] ?? 0;
                        return (
                          <button
                            key={p}
                            type="button"
                            onClick={(e) => {
                              setCurrentPage(p);
                              (e.currentTarget.closest('details') as HTMLDetailsElement | null)?.removeAttribute('open');
                            }}
                            className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-xs ${p === currentPage ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary'}`}
                          >
                            <span className="tabular-nums">{t('takeoff_viewer.page_label', { defaultValue: 'Page' })} {p}</span>
                            {cnt > 0 && (
                              <span className={`tabular-nums rounded-full px-1.5 py-0.5 text-[10px] ${p === currentPage ? 'bg-white/20' : 'bg-purple-500/15 text-purple-500'}`}>
                                {cnt}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </details>
                <button onClick={nextPage} disabled={currentPage >= totalPages} className={tbBtn(false)} aria-label={t('takeoff_viewer.next_page', { defaultValue: 'Next page' })}>
                  <ChevronRight size={16} />
                </button>
              </div>

              {/* Find on sheet - text search over the document's text layer.
                  The toggle opens an anchored panel; matches list by page and
                  click to jump+zoom+highlight. Client-only (pdf.js text). */}
              <div className="relative shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    setSearchOpen((v) => {
                      const next = !v;
                      if (next) {
                        // Focus the input on the next frame (after it mounts).
                        requestAnimationFrame(() => searchInputRef.current?.focus());
                      }
                      return next;
                    });
                  }}
                  className={tbBtn(searchOpen, 'blue')}
                  title={t('takeoff_viewer.find_hint', { defaultValue: 'Find text on this drawing' })}
                  aria-label={t('takeoff_viewer.find_aria', { defaultValue: 'Find on sheet' })}
                  aria-expanded={searchOpen}
                  data-testid="find-on-sheet-toggle"
                >
                  <Search size={15} />
                  <span className="takeoff-toolbar-label">{t('takeoff_viewer.find', { defaultValue: 'Find' })}</span>
                </button>
                {searchOpen && (
                  <div
                    className="absolute left-0 top-full mt-1 z-40 w-72 rounded-lg border border-border bg-surface-elevated shadow-xl p-2 space-y-2"
                    data-testid="find-on-sheet-panel"
                  >
                    <div className="flex items-center gap-1">
                      <div className="relative flex-1">
                        <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none" />
                        <input
                          ref={searchInputRef}
                          type="text"
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              stepMatch(e.shiftKey ? -1 : 1);
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              setSearchOpen(false);
                            }
                          }}
                          placeholder={t('takeoff_viewer.find_placeholder', { defaultValue: 'Find text on sheet…' })}
                          className="w-full rounded border border-border bg-surface-primary pl-7 pr-2 py-1 text-xs text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none"
                          data-testid="find-on-sheet-input"
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => stepMatch(-1)}
                        disabled={searchMatches.length === 0}
                        className="p-1 rounded hover:bg-surface-secondary text-content-secondary disabled:opacity-30 disabled:pointer-events-none"
                        title={t('takeoff_viewer.find_prev', { defaultValue: 'Previous match (Shift+Enter)' })}
                        aria-label={t('takeoff_viewer.find_prev', { defaultValue: 'Previous match' })}
                        data-testid="find-prev"
                      >
                        <ChevronUp size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => stepMatch(1)}
                        disabled={searchMatches.length === 0}
                        className="p-1 rounded hover:bg-surface-secondary text-content-secondary disabled:opacity-30 disabled:pointer-events-none"
                        title={t('takeoff_viewer.find_next', { defaultValue: 'Next match (Enter)' })}
                        aria-label={t('takeoff_viewer.find_next', { defaultValue: 'Next match' })}
                        data-testid="find-next"
                      >
                        <ChevronDown size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setSearchOpen(false)}
                        className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
                        aria-label={t('takeoff_viewer.find_close', { defaultValue: 'Close find' })}
                        data-testid="find-close"
                      >
                        <X size={14} />
                      </button>
                    </div>
                    {/* Status line: match count / busy / empty. */}
                    <div className="flex items-center justify-between px-0.5 text-[11px] text-content-tertiary" data-testid="find-match-count">
                      {searchBusy ? (
                        <span className="flex items-center gap-1"><Loader2 size={11} className="animate-spin" />{t('takeoff_viewer.find_searching', { defaultValue: 'Searching…' })}</span>
                      ) : searchQuery.trim().length === 0 ? (
                        <span>{t('takeoff_viewer.find_type_hint', { defaultValue: 'Type to search the text on this drawing' })}</span>
                      ) : searchMatches.length === 0 ? (
                        <span data-testid="find-no-matches">{t('takeoff_viewer.find_no_matches', { defaultValue: 'No matches on this document' })}</span>
                      ) : (
                        <span className="tabular-nums">
                          {t('takeoff_viewer.find_count', {
                            defaultValue: '{{current}} of {{total}}',
                            current: activeMatchIdx >= 0 ? activeMatchIdx + 1 : 0,
                            total: searchMatches.length,
                          })}
                        </span>
                      )}
                    </div>
                    {/* Results list. */}
                    {searchMatches.length > 0 && (
                      <div className="max-h-56 overflow-y-auto rounded border border-border divide-y divide-border">
                        {searchMatches.map((m, i) => (
                          <button
                            key={`${m.page}-${m.index}`}
                            type="button"
                            onClick={() => goToMatch(i)}
                            data-testid="find-result"
                            data-page={m.page}
                            data-index={m.index}
                            data-active={i === activeMatchIdx}
                            className={`flex w-full items-start gap-2 px-2 py-1.5 text-left text-[11px] transition-colors ${
                              i === activeMatchIdx ? 'bg-oe-blue/10' : 'hover:bg-surface-secondary'
                            }`}
                          >
                            <span className="shrink-0 rounded bg-surface-secondary px-1 py-0.5 font-mono text-[10px] text-content-secondary tabular-nums">
                              {t('takeoff_viewer.find_page_chip', { defaultValue: 'p{{n}}', n: m.page })}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-content-primary">{m.snippet}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Zoom - out / level / in / fit-width / fit-page / fit-selection. */}
              <div className={TB_GROUP}>
                <button onClick={zoomOut} className={tbBtn(false)} title={t('takeoff_viewer.zoom_out', { defaultValue: 'Zoom out' })} aria-label={t('takeoff_viewer.zoom_out', { defaultValue: 'Zoom out' })}>
                  <ZoomOut size={16} />
                </button>
                <span className="inline-flex h-7 min-w-[2.75rem] items-center justify-center px-1 text-xs tabular-nums text-content-tertiary">{(zoom * 100).toFixed(0)}%</span>
                <button onClick={zoomIn} className={tbBtn(false)} title={t('takeoff_viewer.zoom_in', { defaultValue: 'Zoom in' })} aria-label={t('takeoff_viewer.zoom_in', { defaultValue: 'Zoom in' })}>
                  <ZoomIn size={16} />
                </button>
                <button onClick={() => fitToViewport('width')} className={tbBtn(false)} title={t('takeoff_viewer.fit_width_hint', { defaultValue: 'Fit the page to the viewport width (Shift+1)' })} aria-label={t('takeoff_viewer.fit_width', { defaultValue: 'Fit width' })}>
                  <MoveHorizontal size={16} />
                </button>
                <button onClick={zoomFit} className={tbBtn(false)} title={t('takeoff_viewer.fit_page_hint', { defaultValue: 'Fit the whole page in view (Shift+2)' })} aria-label={t('takeoff_viewer.fit_page', { defaultValue: 'Fit page' })}>
                  <Maximize size={16} />
                </button>
                <button onClick={zoomToSelection} disabled={!selectedMeasurementId} className={tbBtn(false)} title={t('takeoff_viewer.zoom_selection_hint', { defaultValue: 'Zoom to the selected measurement (Shift+3)' })} aria-label={t('takeoff_viewer.zoom_selection', { defaultValue: 'Zoom to selection' })}>
                  <Focus size={16} />
                </button>
              </div>

              {/* Ortho lock + pan affordance. Ortho also engages while Shift is
                  physically held (CAD-standard); pan engages on Space or
                  middle-mouse, so the pan glyph is an indicator + hint. */}
              <div className={TB_GROUP}>
                <button
                  onClick={() => setOrthoLock((v) => !v)}
                  className={tbBtn(orthoLock, 'blue')}
                  title={t('takeoff_viewer.ortho_lock_hint', { defaultValue: 'Constrain new segments to 0, 45 or 90 degrees (hold Shift, or toggle here)' })}
                  aria-label={t('takeoff_viewer.ortho_lock', { defaultValue: 'Ortho lock' })}
                  aria-pressed={orthoLock}
                  data-testid="ortho-lock-toggle"
                >
                  <Spline size={16} />
                </button>
                <button
                  onClick={() => { setVertexSnap((v) => !v); setSnapPoint(null); }}
                  className={tbBtn(vertexSnap, 'blue')}
                  title={t('takeoff_viewer.vertex_snap_hint', { defaultValue: 'Snap new points to the corners of existing measurements' })}
                  aria-label={t('takeoff_viewer.vertex_snap', { defaultValue: 'Snap to vertices' })}
                  aria-pressed={vertexSnap}
                  data-testid="vertex-snap-toggle"
                >
                  <Magnet size={16} />
                </button>
                <button
                  onClick={() => setPanLock((v) => !v)}
                  className={tbBtn(panLock || spaceHeld || panning, 'blue')}
                  title={t('takeoff_viewer.pan_hint', { defaultValue: 'Hand tool: click to pan by dragging. You can also hold Space or use the middle mouse button. Click again or press Esc to leave.' })}
                  aria-label={t('takeoff_viewer.pan', { defaultValue: 'Pan' })}
                  aria-pressed={panLock}
                  data-testid="pan-toggle"
                >
                  <Hand size={16} />
                </button>
              </div>

              {/* Right cluster - view toggles, history and document actions,
                  pushed to the right so row 1 reads navigate -> view -> act. */}
              <div className="ml-auto flex items-center gap-1.5">
                {/* View toggles */}
                <div className={TB_GROUP}>
                  {totalPages > 1 && (
                    <button
                      onClick={() => setShowThumbnails((v) => !v)}
                      className={tbBtn(showThumbnails)}
                      title={t('takeoff_viewer.toggle_thumbnails', { defaultValue: 'Toggle page thumbnails' })}
                      aria-label={t('takeoff_viewer.toggle_thumbnails', { defaultValue: 'Toggle page thumbnails' })}
                      aria-pressed={showThumbnails}
                      data-testid="thumbnails-toggle"
                    >
                      <Layers size={15} />
                      <span className="takeoff-toolbar-label">{t('takeoff_viewer.thumbnails', { defaultValue: 'Pages' })}</span>
                    </button>
                  )}
                  <button
                    onClick={() => setShowLegend((v) => !v)}
                    className={tbBtn(showLegend)}
                    title={t('takeoff_viewer.toggle_legend', { defaultValue: 'Toggle legend' })}
                    aria-label={t('takeoff_viewer.toggle_legend', { defaultValue: 'Toggle legend' })}
                    aria-pressed={showLegend}
                    data-testid="legend-toggle"
                  >
                    <List size={15} />
                    <span className="takeoff-toolbar-label">{t('takeoff_viewer.legend', { defaultValue: 'Legend' })}</span>
                  </button>
                  {/* Declutter toggles: hide the on-canvas name badges and the
                      dimension values independently; geometry stays visible and
                      the numbers stay in the Ledger and hover tooltip (#314). */}
                  <button
                    onClick={() => setShowLabels((v) => !v)}
                    className={tbBtn(showLabels)}
                    title={t('takeoff_viewer.toggle_names', { defaultValue: 'Show measurement names' })}
                    aria-label={t('takeoff_viewer.toggle_names', { defaultValue: 'Show measurement names' })}
                    aria-pressed={showLabels}
                    data-testid="names-toggle"
                  >
                    <Type size={15} />
                    <span className="takeoff-toolbar-label">{t('takeoff_viewer.names', { defaultValue: 'Names' })}</span>
                  </button>
                  <button
                    onClick={() => setShowDimensions((v) => !v)}
                    className={tbBtn(showDimensions)}
                    title={t('takeoff_viewer.toggle_values', { defaultValue: 'Show dimension values' })}
                    aria-label={t('takeoff_viewer.toggle_values', { defaultValue: 'Show dimension values' })}
                    aria-pressed={showDimensions}
                    data-testid="values-toggle"
                  >
                    <Hash size={15} />
                    <span className="takeoff-toolbar-label">{t('takeoff_viewer.values', { defaultValue: 'Values' })}</span>
                  </button>
                  {/* Collapse the right sidebar for a larger drawing viewport (#315). */}
                  <button
                    onClick={() => setShowSidebar((v) => !v)}
                    className={tbBtn(showSidebar)}
                    title={t('takeoff_viewer.toggle_sidebar', { defaultValue: 'Toggle the properties panel' })}
                    aria-label={t('takeoff_viewer.toggle_sidebar', { defaultValue: 'Toggle the properties panel' })}
                    aria-pressed={showSidebar}
                    data-testid="sidebar-toggle"
                  >
                    <PanelRight size={15} />
                    <span className="takeoff-toolbar-label">{t('takeoff_viewer.panel', { defaultValue: 'Panel' })}</span>
                  </button>
                </div>

                {/* History - undo / redo / clear */}
                <div className={TB_GROUP}>
                  <button
                    onClick={handleUndo}
                    disabled={undoCount === 0}
                    className={tbBtn(false)}
                    title={t('takeoff.undo', { defaultValue: 'Undo' }) + ' (Ctrl+Z)'}
                    aria-label={t('takeoff.undo', { defaultValue: 'Undo' })}
                    data-testid="undo-button"
                  >
                    <Undo2 size={15} />
                  </button>
                  <button
                    onClick={handleRedo}
                    disabled={redoCount === 0}
                    className={tbBtn(false)}
                    title={t('takeoff.redo', { defaultValue: 'Redo' }) + ' (Ctrl+Y)'}
                    aria-label={t('takeoff.redo', { defaultValue: 'Redo' })}
                    data-testid="redo-button"
                  >
                    <Redo2 size={15} />
                  </button>
                  <button
                    onClick={() => measurements.length > 0 ? setShowClearConfirm(true) : undefined}
                    className={tbBtn(false)}
                    title={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })}
                    aria-label={t('takeoff_viewer.clear_all', { defaultValue: 'Clear all' })}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>

                {/* Save PDF - the document's hero action. */}
                <button
                  onClick={handleExportPdf}
                  disabled={isExportingPdf || !pdfDoc}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-emerald-600 px-2.5 text-xs font-semibold text-white shadow-xs transition-all hover:bg-emerald-700 hover:shadow-sm disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/50"
                  title={t('takeoff_viewer.save_pdf_hint', { defaultValue: 'Save this drawing as a PDF with your measurements and markups' })}
                  aria-label={t('takeoff_viewer.save_pdf', { defaultValue: 'Save PDF' })}
                  data-testid="toolbar-export-pdf-button"
                >
                  {isExportingPdf ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  <span className="takeoff-toolbar-label">{t('takeoff_viewer.save_pdf', { defaultValue: 'Save PDF' })}</span>
                </button>

                {/* New file */}
                <label className={`${tbBtn(false)} cursor-pointer`} title={t('takeoff_viewer.load_new_pdf', { defaultValue: 'Load new PDF' })} aria-label={t('takeoff_viewer.load_new_pdf', { defaultValue: 'Load new PDF' })}>
                  <Upload size={15} />
                  <input type="file" accept="application/pdf" onChange={handleFileUpload} className="hidden" />
                </label>
              </div>
              </div>

              {/* Row 2: scale and the drawing tools. Scale controls lead, then
                  the measure tools, then the markup tools; the AI-assist
                  actions (Recognize / Read-with-AI) sit at the right. */}
              <div className="flex items-center gap-1 flex-wrap">
              {/* Scale + calibration controls, grouped in one segmented track. */}
              <div className={TB_GROUP}>
                {/* Scale */}
                <button
                  onClick={() => { setCalibrationMode(false); setSettingScale(true); setScalePoints([]); setLiveCursor(null); setSnapPoint(null); }}
                  className={tbBtn(settingScale && !calibrationMode, 'purple')}
                  title={t('takeoff_viewer.set_scale', { defaultValue: 'Set scale' })}
                  aria-label={t('takeoff_viewer.set_scale', { defaultValue: 'Set scale' })}
                  aria-pressed={settingScale && !calibrationMode}
                >
                  <Settings2 size={15} />
                  <span className="hidden sm:inline">{t('takeoff_viewer.scale', { defaultValue: 'Scale' })}</span>
                </button>
                {/* Calibrate - two-click with multi-unit dialog */}
                <button
                  onClick={handleStartCalibration}
                  className={tbBtn(calibrationMode, 'purple')}
                  title={t('takeoff_viewer.calibrate', { defaultValue: 'Calibrate scale (two-click)' })}
                  aria-label={t('takeoff_viewer.calibrate', { defaultValue: 'Calibrate scale' })}
                  aria-pressed={calibrationMode}
                  data-testid="calibrate-button"
                >
                  <Ruler size={15} />
                  <span className="hidden sm:inline">{t('takeoff_viewer.calibrate_short', { defaultValue: 'Calibrate' })}</span>
                </button>
              </div>

              {/* Calibration status chip - ratio + length when calibrated, an
                  amber "Not calibrated" warning otherwise. Click to (re)calibrate.
                  Reuses the scale purple so it reads as part of the scale group. */}
              {isCalibrated && !calibrationMode && !settingScale && (
                <button
                  onClick={handleStartCalibration}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-purple-300/60 bg-purple-50 px-2 text-[11px] font-medium text-purple-700 transition-colors hover:bg-purple-100 dark:border-purple-700/50 dark:bg-purple-900/25 dark:text-purple-300 dark:hover:bg-purple-900/40"
                  title={t('takeoff_viewer.calibrated_tooltip', {
                    defaultValue: 'Calibrated · {{ratio}}{{atLen}} - click to recalibrate',
                    ratio: formatScaleRatio(scale),
                    atLen: lastCalibration
                      ? ` @ ${lastCalibration.realLength} ${lastCalibration.unit}`
                      : '',
                  })}
                  data-testid="calibration-badge"
                >
                  <Check size={13} className="shrink-0 text-purple-500" />
                  <span className="font-mono tabular-nums">{formatScaleRatio(scale)}</span>
                  {lastCalibration && (
                    <span className="font-mono tabular-nums text-purple-500/80">· {lastCalibration.realLength} {lastCalibration.unit}</span>
                  )}
                </button>
              )}
              {!isCalibrated && !calibrationMode && !settingScale && (
                <button
                  onClick={handleStartCalibration}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-amber-300/60 bg-amber-50 px-2 text-[11px] font-medium text-amber-700 transition-colors hover:bg-amber-100 dark:border-amber-700/50 dark:bg-amber-900/25 dark:text-amber-300 dark:hover:bg-amber-900/40"
                  title={t('takeoff_viewer.uncalibrated_hint', { defaultValue: 'Drawing is not calibrated - measurements may be inaccurate. Click to calibrate.' })}
                  data-testid="uncalibrated-badge"
                >
                  <AlertTriangle size={13} className="shrink-0 text-amber-500" />
                  <span>{t('takeoff_viewer.not_calibrated', { defaultValue: 'Not calibrated' })}</span>
                </button>
              )}

              {/* Measure tools - one segmented track, icon-only with tooltips
                  + shortcut letters; the armed tool gets the blue accent. */}
              <div className={TB_GROUP} role="group" aria-label={t('takeoff_viewer.measure_tools', { defaultValue: 'Measure tools' })} data-guide="takeoff-tools">
                {([
                  { tool: 'select' as MeasureTool, icon: MousePointer2, label: t('takeoff_viewer.tool_select', { defaultValue: 'Select' }) },
                  { tool: 'distance' as MeasureTool, icon: Minus, label: t('takeoff_viewer.tool_distance', { defaultValue: 'Distance' }) },
                  { tool: 'polyline' as MeasureTool, icon: Route, label: t('takeoff_viewer.tool_polyline', { defaultValue: 'Polyline' }) },
                  { tool: 'area' as MeasureTool, icon: Pentagon, label: t('takeoff_viewer.tool_area', { defaultValue: 'Area' }) },
                  { tool: 'rectarea' as MeasureTool, icon: RectangleHorizontal, label: t('takeoff_viewer.tool_rectarea', { defaultValue: 'Rectangle' }) },
                  { tool: 'volume' as MeasureTool, icon: Box, label: t('takeoff_viewer.tool_volume', { defaultValue: 'Volume' }) },
                  { tool: 'count' as MeasureTool, icon: Hash, label: t('takeoff_viewer.tool_count', { defaultValue: 'Count' }) },
                ] as const).map(({ tool, icon: Icon, label }) => (
                  <button
                    key={tool}
                    onClick={() => selectTool(tool)}
                    className={tbBtn(activeTool === tool, 'blue')}
                    title={labelWithShortcut(label, tool)}
                    aria-label={labelWithShortcut(label, tool)}
                    aria-pressed={activeTool === tool}
                    data-tool={tool}
                    data-shortcut={SHORTCUT_LETTER[tool]}
                  >
                    <Icon size={15} />
                  </button>
                ))}
              </div>

              {/* Markup tools - second segmented track; orange accent marks
                  the armed annotation tool. */}
              <div className={TB_GROUP} role="group" aria-label={t('takeoff_viewer.markup_tools', { defaultValue: 'Markup tools' })}>
                {([
                  { tool: 'cloud' as MeasureTool, icon: Cloud, label: t('takeoff_viewer.tool_cloud', { defaultValue: 'Cloud' }) },
                  { tool: 'arrow' as MeasureTool, icon: ArrowUpRight, label: t('takeoff_viewer.tool_arrow', { defaultValue: 'Arrow' }) },
                  { tool: 'text' as MeasureTool, icon: Type, label: t('takeoff_viewer.tool_text', { defaultValue: 'Text' }) },
                  { tool: 'rectangle' as MeasureTool, icon: Square, label: t('takeoff_viewer.tool_rectangle', { defaultValue: 'Rectangle' }) },
                  { tool: 'highlight' as MeasureTool, icon: Highlighter, label: t('takeoff_viewer.tool_highlight', { defaultValue: 'Highlight' }) },
                ] as const).map(({ tool, icon: Icon, label }) => (
                  <button
                    key={tool}
                    onClick={() => selectTool(tool)}
                    className={tbBtn(activeTool === tool, 'orange')}
                    title={labelWithShortcut(label, tool)}
                    aria-label={labelWithShortcut(label, tool)}
                    aria-pressed={activeTool === tool}
                    data-tool={tool}
                    data-shortcut={SHORTCUT_LETTER[tool]}
                  >
                    <Icon size={15} />
                  </button>
                ))}
              </div>

              {/* AI assist - offline Recognize (issue #194) + optional vision
                  Read-with-AI. Pushed right as the two hero actions of the row. */}
              <button
                onClick={handleRecognize}
                disabled={recognizeBusy}
                className="ml-auto inline-flex h-7 items-center gap-1.5 rounded-md bg-gradient-to-r from-violet-500 to-indigo-500 px-2.5 text-xs font-semibold text-white shadow-xs transition-all hover:from-violet-600 hover:to-indigo-600 hover:shadow-sm disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/50"
                title={t('takeoff_viewer.recognize_hint', { defaultValue: 'Scan this page and suggest measurements (AI proposes, you confirm)' })}
                aria-label={t('takeoff_viewer.recognize', { defaultValue: 'Recognize' })}
                data-testid="recognize-button"
              >
                {recognizeBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                <span className="hidden sm:inline">{t('takeoff_viewer.recognize', { defaultValue: 'Recognize' })}</span>
              </button>

              {/* Count similar - seeded count-by-example. Click one symbol and
                  the server counts every matching symbol on the page (#194). */}
              <button
                onClick={toggleCountSimilar}
                disabled={countSimilarBusy}
                aria-pressed={armCountSimilar}
                className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold shadow-xs transition-all disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/50 ${
                  armCountSimilar
                    ? 'bg-emerald-600 text-white ring-2 ring-emerald-300'
                    : 'bg-gradient-to-r from-emerald-500 to-teal-500 text-white hover:from-emerald-600 hover:to-teal-600 hover:shadow-sm'
                }`}
                title={t('takeoff_viewer.count_similar.hint', {
                  defaultValue:
                    'Click one symbol and count every matching symbol on this page (AI proposes, you confirm)',
                })}
                aria-label={t('takeoff_viewer.count_similar.action', { defaultValue: 'Count similar' })}
                data-testid="count-similar-button"
              >
                {countSimilarBusy ? <Loader2 size={14} className="animate-spin" /> : <Boxes size={14} />}
                <span className="hidden sm:inline">
                  {t('takeoff_viewer.count_similar.action', { defaultValue: 'Count similar' })}
                </span>
              </button>

              {planReadVision?.available && (
                <button
                  onClick={handleReadWithAi}
                  disabled={planReadBusy}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-gradient-to-r from-fuchsia-500 to-purple-600 px-2.5 text-xs font-semibold text-white shadow-xs transition-all hover:from-fuchsia-600 hover:to-purple-700 hover:shadow-sm disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-fuchsia-400/50"
                  title={t('takeoff_viewer.plan_read.hint', {
                    defaultValue: 'Read this page with a vision AI: room names and scale (AI proposes, you confirm)',
                  })}
                  aria-label={t('takeoff_viewer.plan_read.action', { defaultValue: 'Read plan with AI' })}
                  data-testid="plan-read-ai-button"
                >
                  {planReadBusy ? <Loader2 size={14} className="animate-spin" /> : <Scan size={14} />}
                  <span className="hidden sm:inline">
                    {t('takeoff_viewer.plan_read.action', { defaultValue: 'Read plan with AI' })}
                  </span>
                </button>
              )}

              </div>
            </div>

            {/* Scale auto-detect suggestion - kept on its own slim strip
                directly below the toolbar so the two toolbar rows stay clean.
                Only for server-side documents (it needs a document id to scan)
                and hidden while actively setting or calibrating scale so it
                never competes with those flows. Nothing auto-applies - the
                user confirms via "Use this" (CLAUDE.md rule 7). */}
            {documentId && !calibrationMode && !settingScale && (
              <ScaleAutoDetect
                documentId={documentId}
                pageNumber={currentPage}
                onApply={(next) => setScale(next)}
              />
            )}

            {/* No-text-layer banner (8.2.0) — surfaces how many pages came back
                with no text layer (usually scanned drawings) so a partly- or
                fully-scanned PDF is clearly flagged for OCR instead of being
                silently treated as empty. Dismissible per opened document. */}
            {noTextLayer && noTextLayer.count > 0 && !noTextBannerDismissed && (
              <div
                className="mb-2 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-200"
                role="status"
                data-testid="takeoff-needs-ocr-banner"
              >
                <Scan size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
                <div className="flex-1">
                  <span className="font-semibold">
                    {totalPages > 0 && noTextLayer.count >= totalPages
                      ? t('takeoff.needs_ocr_banner_all', {
                          defaultValue: 'No text layer found - this looks like a scanned drawing and likely needs OCR.',
                        })
                      : t('takeoff.needs_ocr_banner', {
                          defaultValue: '{{n}} of {{total}} pages have no text layer and likely need OCR.',
                          n: noTextLayer.count,
                          total: totalPages || noTextLayer.count,
                        })}
                  </span>
                  {noTextLayer.pages.length > 0 && noTextLayer.pages.length <= 30 && (
                    <span className="ml-1 opacity-80">
                      {t('takeoff.needs_ocr_banner_pages', {
                        defaultValue: 'Pages: {{pages}}',
                        pages: noTextLayer.pages.join(', '),
                      })}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setNoTextBannerDismissed(true);
                    // Remember the dismissal for this document so it does not
                    // reappear on the next open (issue #346). Local-only files
                    // (no document id) stay session-only.
                    if (documentId) {
                      try {
                        localStorage.setItem(`takeoff.ocrBannerDismissed.${documentId}`, 'true');
                      } catch {
                        /* ignore quota / private-mode failures */
                      }
                    }
                  }}
                  className="shrink-0 rounded p-0.5 text-amber-700 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900/40"
                  aria-label={t('takeoff.needs_ocr_banner_dismiss', { defaultValue: 'Dismiss' })}
                >
                  <X size={14} />
                </button>
              </div>
            )}

            {/* Non-scrolling positioning context for the canvas chrome (#354).
                The legend, tool hints, calibration banner, suggestion pill and
                draw readout are pinned here, to the visible canvas, instead of
                inside the scroll container where they were children of the
                scrolled content and rode the drawing off screen. The wrapper
                takes the container's slot in the canvas column (flex-1 + the
                fixed min-h-[320px] floor) and passes it straight through, so the
                container's own classes stay untouched and the definite-height
                chain fit-to-page depends on (#306/#341) is intact. The hover
                card and the text-annotation input stay INSIDE the container:
                both are placed in canvas coordinates and must track the drawing. */}
            <div
              ref={legendViewportRef}
              className="relative flex flex-1 min-w-0 min-h-[320px] flex-col"
            >
            {/* Canvas — the PDF render surface is a genuinely-needed internal
                scroll region (drawings are far larger than any viewport).
                `flex-1` makes it claim the height left over in the canvas
                column after the toolbar, so it grows and shrinks with the
                viewport instead of the old hardcoded `100vh - 396px` math that
                left the drawing boxed in when there was space to spare (#341).
                The height stays DEFINITE because every ancestor up to the
                page root is a flex item with `min-h-0`, so fit-to-page reads a
                real clientHeight. The floor is a FIXED `min-h-[320px]` (not the
                flex default `auto`): a fixed min-height still lets the box
                shrink below its own canvas content, so the container never
                grows with what it renders - that content-sized growth is what
                made every fit re-measure the last fit's output and zoom out on
                each click (#306) - and it keeps the surface usable on very
                short viewports. */}
            <div
              ref={containerRef}
              className="relative flex-1 min-h-[320px] max-w-full rounded-lg border border-border overflow-auto bg-gray-100 dark:bg-gray-900"
            >
              <canvas ref={canvasRef} className="block" />
              <canvas
                ref={overlayRef}
                className="absolute top-0 left-0"
                style={{
                  cursor: panning
                    ? 'grabbing'
                    : spaceHeld || panLock
                      ? 'grab'
                      : activeTool === 'select'
                        ? (dragPreview ? 'grabbing' : 'default')
                        : 'crosshair',
                }}
                onClick={handleCanvasClick}
                onDoubleClick={handleCanvasDblClick}
                onContextMenu={handleCanvasContextMenu}
                onMouseDown={handleCanvasMouseDown}
                onMouseMove={handleCanvasMouseMove}
                onMouseUp={handleCanvasMouseUp}
                onMouseLeave={handleCanvasMouseLeave}
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              />

              {/* Hover tooltip and the text-annotation input STAY inside the
                  scroll container: both are positioned in canvas coordinates and
                  must travel with the drawing, unlike the pinned chrome below
                  (#354). Hover tooltip on an existing measurement (select mode) -
                  value, group and linked BOQ position. Offset from the cursor so
                  it does not sit under the pointer; pointer-events disabled so it
                  never eats the click. */}
              {hoverInfo && hoverMeasurement && (
                <div
                  className="absolute z-20 max-w-[220px] rounded-md border border-border bg-surface-primary/95 dark:bg-gray-800/95 backdrop-blur-sm shadow-lg px-2.5 py-1.5 text-[11px] pointer-events-none"
                  style={{ left: `${hoverInfo.x + 14}px`, top: `${hoverInfo.y + 14}px` }}
                  data-testid="measurement-hover-tooltip"
                >
                  <div className="font-semibold text-content-primary truncate">
                    {hoverMeasurement.annotation
                      || (hoverMeasurement.label
                        ? measurementLabel(hoverMeasurement, scale, measurementSystem)
                        : hoverMeasurement.type)}
                  </div>
                  {hoverMeasurement.label && (
                    <div className="tabular-nums text-content-secondary">
                      {measurementLabel(hoverMeasurement, scale, measurementSystem)}
                    </div>
                  )}
                  <div className="mt-0.5 flex items-center gap-1 text-content-tertiary">
                    <span className="uppercase tracking-wide text-[10px]">
                      {t('takeoff_viewer.tooltip_group', { defaultValue: 'Group' })}
                    </span>
                    <span>{hoverMeasurement.group || 'General'}</span>
                  </div>
                  <div className="mt-0.5 text-[10px]">
                    {hoverMeasurement.linkedPositionOrdinal ? (
                      <span className="text-emerald-600 dark:text-emerald-400 font-mono">
                        {t('takeoff_viewer.tooltip_linked', {
                          defaultValue: 'Linked to {{pos}}',
                          pos: hoverMeasurement.linkedPositionOrdinal,
                        })}
                      </span>
                    ) : (
                      <span className="text-content-quaternary">
                        {t('takeoff_viewer.tooltip_unlinked', { defaultValue: 'Not linked to a BOQ position' })}
                      </span>
                    )}
                  </div>
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
                      if (e.key === 'Escape') {
                        textInputCancellingRef.current = true;
                        setShowTextInput(false);
                        setTextInputValue('');
                      }
                    }}
                    onBlur={() => {
                      if (textInputCancellingRef.current) {
                        textInputCancellingRef.current = false;
                        return;
                      }
                      handleTextConfirm();
                    }}
                    autoFocus
                    placeholder={t('takeoff_viewer.text_placeholder', { defaultValue: 'Type annotation text...' })}
                    className="rounded border-2 bg-white/95 dark:bg-gray-800/95 px-2 py-1 text-sm font-medium outline-none shadow-lg min-w-[150px]"
                    style={{ borderColor: annotationColor, color: annotationColor }}
                  />
                </div>
              )}
            </div>

              {/* Live drawing readout HUD - cursor coordinate + running
                  segment / cumulative length while a measure tool draws.
                  Bottom-right so it never collides with the bottom-left legend
                  or the top tool hint. Lengths hide when the page has no
                  scale (the helper returns null) so we never show "0 m". */}
              {drawReadout && (
                <div
                  className="absolute bottom-2 right-2 z-10 rounded-lg border border-border bg-surface-primary/95 dark:bg-gray-800/95 backdrop-blur-sm shadow-lg px-3 py-2 text-[11px] font-mono text-content-secondary pointer-events-none space-y-0.5"
                  data-testid="draw-readout"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-content-quaternary uppercase tracking-wide">
                      {t('takeoff_viewer.readout_position', { defaultValue: 'Position' })}
                    </span>
                    <span className="tabular-nums text-content-primary">
                      {drawReadout.cursor.x}, {drawReadout.cursor.y}
                    </span>
                  </div>
                  {drawReadout.segment != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-content-quaternary uppercase tracking-wide">
                        {t('takeoff_viewer.readout_segment', { defaultValue: 'Segment' })}
                      </span>
                      <span className="tabular-nums text-content-primary">
                        {formatQuantity(drawReadout.segment, drawReadout.unit || 'm', measurementSystem)}
                      </span>
                    </div>
                  )}
                  {drawReadout.total != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-content-quaternary uppercase tracking-wide">
                        {t('takeoff_viewer.readout_total', { defaultValue: 'Total' })}
                      </span>
                      <span className="tabular-nums text-content-primary">
                        {formatQuantity(drawReadout.total, drawReadout.unit || 'm', measurementSystem)}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {settingScale && (
                <div
                  className="absolute top-2 left-2 bg-purple-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium"
                  data-testid="calibration-hint"
                >
                  {calibrationMode
                    ? (scalePoints.length === 0
                        ? t('takeoff_viewer.calibrate_click_first', { defaultValue: 'Calibrate: click point A on a known dimension' })
                        : t('takeoff_viewer.calibrate_click_second', { defaultValue: 'Calibrate: click point B' }))
                    : (scalePoints.length === 0
                        ? t('takeoff_viewer.scale_click_first', { defaultValue: 'Click first point of known dimension' })
                        : t('takeoff_viewer.scale_click_second', { defaultValue: 'Click second point' }))}
                </div>
              )}
              {/* AI suggestions review bar (#194) — appears when Recognize has
                  dropped unconfirmed proposals. Accept-all clears the flags so
                  they persist; dismiss-all drops them. Per-item accept/reject
                  lives in the measurement list below. */}
              {suggestionCount > 0 && (
                <div
                  className="absolute top-2 left-1/2 -translate-x-1/2 z-10 flex items-center gap-2 rounded-full border border-violet-300/60 bg-white/95 dark:bg-gray-800/95 px-3 py-1.5 shadow-lg backdrop-blur"
                  data-testid="suggestions-bar"
                >
                  <Sparkles size={14} className="text-violet-500 shrink-0" />
                  <span className="text-xs font-medium text-content-primary whitespace-nowrap">
                    {t('takeoff_viewer.suggestions_pending', { defaultValue: '{{n}} AI suggestions', n: suggestionCount })}
                  </span>
                  <button
                    onClick={acceptAllSuggestions}
                    className="rounded-full bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-600 transition-colors"
                    data-testid="accept-all-suggestions"
                  >
                    {t('takeoff_viewer.accept_all', { defaultValue: 'Accept all' })}
                  </button>
                  <button
                    onClick={dismissAllSuggestions}
                    className="rounded-full bg-surface-secondary px-2.5 py-1 text-[11px] font-semibold text-content-secondary hover:bg-surface-tertiary transition-colors"
                    data-testid="dismiss-all-suggestions"
                  >
                    {t('takeoff_viewer.dismiss_all', { defaultValue: 'Dismiss all' })}
                  </button>
                </div>
              )}
              {/* Active-tool hint banner — shows what the current tool expects.
                  Critical for Count/Polyline/Area where users were unsure how
                  to terminate a session (Esc) and for Calibrate workflow. The
                  calibration-specific hint above already covers settingScale,
                  so this branch only fires for measure/annotation tools. */}
              {!settingScale && activeTool !== 'select' && (
                <div
                  className="absolute top-2 left-1/2 -translate-x-1/2 bg-oe-blue/90 text-white px-3 py-1 rounded-md text-[11px] font-medium shadow-lg pointer-events-none flex items-center gap-2"
                  data-testid="active-tool-hint"
                >
                  <span>
                    {activeTool === 'count' && t('takeoff_viewer.hint_count', { defaultValue: 'Click on each item to count.' })}
                    {activeTool === 'distance' && t('takeoff_viewer.hint_distance', { defaultValue: 'Click two points for a distance.' })}
                    {activeTool === 'polyline' && t('takeoff_viewer.hint_polyline', { defaultValue: 'Click points along the line.' })}
                    {activeTool === 'area' && t('takeoff_viewer.hint_area', { defaultValue: 'Click polygon vertices.' })}
                    {activeTool === 'volume' && t('takeoff_viewer.hint_volume', { defaultValue: 'Click area outline.' })}
                    {activeTool === 'cloud' && t('takeoff_viewer.hint_cloud', { defaultValue: 'Click cloud outline points.' })}
                    {activeTool === 'arrow' && t('takeoff_viewer.hint_arrow', { defaultValue: 'Click arrow start, then end.' })}
                    {activeTool === 'rectangle' && t('takeoff_viewer.hint_rectangle', { defaultValue: 'Click two corners.' })}
                    {activeTool === 'highlight' && t('takeoff_viewer.hint_highlight', { defaultValue: 'Drag to highlight a region.' })}
                    {activeTool === 'text' && t('takeoff_viewer.hint_text', { defaultValue: 'Click to place a text pin.' })}
                  </span>
                  {(activeTool === 'count' || activeTool === 'polyline' || activeTool === 'area' || activeTool === 'volume' || activeTool === 'cloud') && (
                    <span className="opacity-80 border-l border-white/30 pl-2">
                      {activeTool === 'count'
                        ? t('takeoff_viewer.hint_esc_to_finish', { defaultValue: 'Enter: new count group · Esc: switch tool' })
                        : t('takeoff_viewer.hint_dblclick_close', { defaultValue: 'Enter or double-click: close shape · Esc: cancel' })}
                    </span>
                  )}
                </div>
              )}
              {/* Cloud tool hint */}
              {activeTool === 'cloud' && activePoints.length > 0 && (
                <div className="absolute top-2 left-2 bg-orange-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-medium">
                  {t('takeoff_viewer.cloud_hint', { defaultValue: 'Click points to define cloud shape. Double-click or right-click to finish.' })}
                </div>
              )}

              {/* Color-coded group legend — bottom-left, click row to toggle visibility. */}
              {/* Gate on the page having measurements at all, not on
                  legendSummaries being non-empty (#359): the summaries already
                  exclude hidden groups and hidden measurements, so hiding the
                  last visible thing would otherwise unmount the legend and with
                  it the only rows that can bring anything back. The row builder
                  reconstructs a row for every group on the page regardless. */}
              {showLegend && pageMeasurements.length > 0 && (
                <div
                  ref={attachLegend}
                  className={clsx(
                    // Height cap (#358): flex column so the header stays pinned and
                    // the rows scroll inside it, and the box can never grow its
                    // header (the drag handle + close button) off the top.
                    'absolute max-w-[240px] rounded-lg border border-border bg-surface-primary/95 dark:bg-gray-800/95 backdrop-blur-sm shadow-lg overflow-hidden flex flex-col max-h-[calc(50%-1rem)]',
                    // Default corner when there is no dragged position (#358).
                    legendPos === null && 'bottom-2 left-2',
                    // When a measurement/annotation tool is armed, let clicks pass through to the
                    // overlay canvas beneath — otherwise the legend swallows canvas clicks, the user
                    // sees no mark appear, and group-visibility toggles silently hide their work.
                    // The draggable header re-enables pointer events below so it stays grabbable.
                    activeTool !== 'select' && 'pointer-events-none',
                  )}
                  style={legendPos ? { left: `${legendPos.x}px`, top: `${legendPos.y}px` } : undefined}
                  data-testid="legend-overlay"
                >
                  <div
                    className="flex items-center justify-between px-2.5 py-1.5 border-b border-border-light bg-surface-secondary/40 shrink-0 cursor-move select-none pointer-events-auto"
                    onMouseDown={startLegendDrag}
                    onDoubleClick={resetLegendPos}
                    data-testid="legend-drag-handle"
                    title={t('takeoff_viewer.legend_drag_hint', { defaultValue: 'Drag to move, double-click to reset' })}
                  >
                    <span className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary">
                      {t('takeoff_viewer.legend', { defaultValue: 'Legend' })}
                    </span>
                    <button
                      type="button"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => setShowLegend(false)}
                      className="text-content-tertiary hover:text-content-primary transition-colors p-0.5"
                      aria-label={t('takeoff_viewer.hide_legend', { defaultValue: 'Hide legend' })}
                    >
                      <X size={10} />
                    </button>
                  </div>
                  <div className="py-1 min-h-0 overflow-y-auto">
                    {/* Always show every group on the page, hidden or not, so a
                        hidden group (or a group whose measurements are all
                        individually hidden) can still be restored (#359). */}
                    {(() => {
                      const allGroupsOnPage = new Set<string>();
                      for (const m of pageMeasurements) allGroupsOnPage.add(m.group || 'General');
                      const visible = new Map(legendSummaries.map((s) => [s.name, s]));
                      const rows: Array<{ name: string; color: string; count: number; total: number; unit: string; hidden: boolean }> = [];
                      for (const name of Array.from(allGroupsOnPage).sort()) {
                        // Derive hidden from hiddenGroups directly, never from a
                        // group's absence in the summaries: a visible group whose
                        // measurements are all individually hidden is absent too,
                        // and treating that as a hidden GROUP would restore its
                        // hidden count and wire its click to toggle a group that
                        // was never hidden.
                        const groupHidden = hiddenGroups.has(name);
                        const summary = visible.get(name);
                        if (!groupHidden && summary) {
                          // Visible group with visible measurements: the summary
                          // already excludes hidden groups and hidden measurements.
                          rows.push({ ...summary, hidden: false });
                        } else {
                          // A hidden group shows its full content (dimmed) so it
                          // can be restored; a visible-but-all-hidden group reads
                          // as present with nothing visible in it. Filter by
                          // hiddenMeasurements only when the group is not hidden.
                          const items = pageMeasurements.filter(
                            (m) =>
                              (m.group || 'General') === name &&
                              (groupHidden || !hiddenMeasurements.has(m.id)),
                          );
                          rows.push({
                            name,
                            color: groupColorMap[name] || '#3B82F6',
                            count: items.length,
                            total: items.reduce((s, it) => s + it.value, 0),
                            unit: items.find((it) => it.unit)?.unit ?? '',
                            hidden: groupHidden,
                          });
                        }
                      }
                      return rows.map((row) => (
                        <button
                          key={row.name}
                          type="button"
                          onClick={() => toggleGroupVisibility(row.name)}
                          className={clsx(
                            'w-full flex items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-surface-secondary',
                            row.hidden && 'opacity-50',
                          )}
                          data-testid="legend-row"
                          data-group={row.name}
                          data-hidden={row.hidden}
                          title={row.hidden
                            ? t('takeoff_viewer.show_group', { defaultValue: 'Show group' })
                            : t('takeoff_viewer.hide_group', { defaultValue: 'Hide group' })
                          }
                        >
                          <span
                            className="h-3 w-3 rounded-full shrink-0 ring-1 ring-white/40"
                            style={{ backgroundColor: row.color }}
                          />
                          <span className="flex-1 text-[11px] font-semibold text-content-primary truncate">
                            {row.name}
                          </span>
                          <span className="text-[10px] font-mono text-content-tertiary tabular-nums">
                            {row.count}
                          </span>
                          <span className="text-[10px] font-mono text-content-secondary tabular-nums min-w-0">
                            {(() => {
                              const d = convertQuantity(row.total, row.unit, measurementSystem);
                              return formatGroupTotal(d.value, d.unit);
                            })()}
                          </span>
                          {row.hidden
                            ? <EyeOff size={10} className="text-content-tertiary shrink-0" />
                            : <Eye size={10} className="text-content-tertiary shrink-0" />
                          }
                        </button>
                      ));
                    })()}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Left-visually / DOM-first: Measurements panel. Collapsible for a
              larger drawing viewport; hiding it lets the flex-1 canvas column
              take the full width (#315). Stretches to the definite-height
              viewer row (#341), so it scrolls internally with `overflow-y-auto`
              + `min-h-0` rather than clipping a long measurement list. */}
          <div className={clsx('w-72 shrink-0 space-y-2 overflow-y-auto min-h-0', !showSidebar && 'hidden')}>
            {/* Scale info */}
            <div className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm">
              <p className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary mb-1">
                {t('takeoff_viewer.scale', { defaultValue: 'Scale' })}
              </p>
              <p className="text-sm font-semibold text-content-primary tabular-nums">
                {(() => {
                  // Stored scale is pixels-per-metre (D-TKC-016); show the
                  // per-pixel length in the user's measurement system.
                  const perPixel = convertQuantity(
                    1 / scale.pixelsPerUnit,
                    scale.unitLabel,
                    measurementSystem,
                  );
                  return `1px = ${perPixel.value.toFixed(4)} ${perPixel.unit}`;
                })()}
              </p>
              <div className="mt-2 flex gap-1 flex-wrap">
                {COMMON_SCALES.slice(0, 4).map((s) => (
                  <button
                    key={s.label}
                    onClick={() => setScale(presetScale(s.ratio))}
                    className="text-[10px] px-1.5 py-0.5 rounded-sm bg-surface-secondary hover:bg-oe-blue hover:text-white text-content-secondary transition-all font-medium"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Active group selector */}
            <div className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm">
              <label className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary block mb-1">
                {t('takeoff_viewer.active_group', { defaultValue: 'Active Group' })}
              </label>
              <div className="flex items-center gap-2">
                {/* Editable group colour (issue #313): the swatch is a colour
                    input, so a custom or preset group can be recoloured and the
                    change flows to the canvas, legend and exports. */}
                <input
                  type="color"
                  value={groupColorMap[activeGroup] || '#3B82F6'}
                  onChange={(e) => setGroupColor(activeGroup, e.target.value)}
                  className="h-5 w-6 shrink-0 cursor-pointer rounded border border-border bg-transparent p-0"
                  title={t('takeoff_viewer.group_color', { defaultValue: 'Group color' })}
                  aria-label={t('takeoff_viewer.group_color', { defaultValue: 'Group color' })}
                  data-testid="active-group-color"
                />
                {/* Any existing group (built-in or user-defined) plus a New group
                    entry, so a custom group can be chosen BEFORE drawing (#313)
                    instead of drawing into a preset and reassigning afterwards. */}
                <select
                  value={activeGroup}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === '__new__') {
                      const raw = window.prompt(
                        t('takeoff_viewer.new_group_prompt', { defaultValue: 'New group name' }),
                      );
                      const name = raw?.trim();
                      if (name) setActiveGroup(name);
                      return;
                    }
                    setActiveGroup(val);
                  }}
                  className="flex-1 rounded-sm border border-border bg-surface-secondary px-2 py-1 text-xs text-content-primary"
                  data-testid="active-group-select"
                >
                  {Array.from(new Set([...availableGroups, activeGroup])).map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                  <option value="__new__">
                    {t('takeoff_viewer.new_group', { defaultValue: '+ New group' })}
                  </option>
                </select>
                {!MEASUREMENT_GROUPS.some((g) => g.name === activeGroup) && (
                  <button
                    type="button"
                    onClick={renameActiveGroup}
                    className="shrink-0 rounded-sm border border-border p-1 text-content-tertiary hover:text-content-primary"
                    title={t('takeoff_viewer.rename_group', { defaultValue: 'Rename group' })}
                    aria-label={t('takeoff_viewer.rename_group', { defaultValue: 'Rename group' })}
                    data-testid="active-group-rename"
                  >
                    <Pencil size={12} />
                  </button>
                )}
              </div>
            </div>

            {/* Count label (when count tool active) */}
            {activeTool === 'count' && (
              <div className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm">
                <label className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary block mb-1">
                  {t('takeoff_viewer.count_label', { defaultValue: 'Count Label' })}
                </label>
                <input
                  ref={countLabelRef}
                  type="text"
                  value={countLabel}
                  onChange={(e) => setCountLabel(e.target.value)}
                  className="w-full rounded-sm border border-border bg-surface-secondary px-2 py-1 text-xs text-content-primary"
                />
              </div>
            )}

            {/* Annotation color picker (when annotation tool active) */}
            {isAnnotationTool(activeTool) && (
              <div className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm">
                <label className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary block mb-1.5">
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

            {/* Segmented tab: Properties | Ledger */}
            <div
              className="flex rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-1 shadow-sm"
              role="tablist"
              data-testid="sidebar-tab-toggle"
            >
              <button
                type="button"
                role="tab"
                aria-selected={sidebarTab === 'properties'}
                onClick={() => setSidebarTab('properties')}
                className={clsx(
                  'flex-1 px-2 py-1 rounded text-[11px] font-semibold transition-colors',
                  sidebarTab === 'properties'
                    ? 'bg-oe-blue text-white shadow-sm'
                    : 'text-content-secondary hover:bg-surface-secondary',
                )}
                data-testid="sidebar-tab-properties"
              >
                {t('takeoff_viewer.tab_properties', { defaultValue: 'Properties' })}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={sidebarTab === 'ledger'}
                onClick={() => setSidebarTab('ledger')}
                className={clsx(
                  'flex-1 px-2 py-1 rounded text-[11px] font-semibold transition-colors',
                  sidebarTab === 'ledger'
                    ? 'bg-oe-blue text-white shadow-sm'
                    : 'text-content-secondary hover:bg-surface-secondary',
                )}
                data-testid="sidebar-tab-ledger"
              >
                {t('takeoff_viewer.tab_ledger', { defaultValue: 'Ledger' })}
                <span className="ml-1 text-[9px] opacity-70">
                  ({measurements.length})
                </span>
              </button>
            </div>

            {/* Ledger view — all measurements, sortable + filterable. */}
            {sidebarTab === 'ledger' && (
              <div className="space-y-2">
                {/* Bulk "Add all to BOQ" target picker. */}
                {bulkAddMeasurements && (
                  <div
                    className="rounded-md border border-oe-blue/40 bg-oe-blue/5 backdrop-blur-sm p-2.5 shadow-sm animate-fade-in"
                    data-testid="ledger-bulk-add-panel"
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-oe-blue">
                        {t('takeoff.bulk_add_title', {
                          defaultValue: 'Add {{count}} measurements to BOQ',
                          count: bulkAddMeasurements.length,
                        })}
                      </span>
                      <button
                        type="button"
                        onClick={() => setBulkAddMeasurements(null)}
                        className="text-content-tertiary hover:text-content-primary transition-colors"
                        aria-label={t('common.close', { defaultValue: 'Close' })}
                      >
                        <X size={10} />
                      </button>
                    </div>
                    <p className="text-[10px] text-content-tertiary mb-1.5">
                      {t('takeoff.bulk_add_desc', {
                        defaultValue:
                          'Each measurement becomes a new position carrying its measured quantity, unit and label.',
                      })}
                    </p>
                    <div className="grid grid-cols-2 gap-1 mb-1.5">
                      <select
                        value={linkPickerProjectId}
                        onChange={(e) => handlePickerProjectChange(e.target.value)}
                        className="text-[10px] rounded border border-border-subtle bg-surface-primary px-1 py-0.5 text-content-primary"
                        aria-label={t('takeoff.bulk_add_target_project', {
                          defaultValue: 'Target project',
                        })}
                      >
                        <option value="">{t('takeoff.pick_project', { defaultValue: '- project -' })}</option>
                        {linkPickerProjects.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                      <select
                        value={linkPickerBoqId}
                        onChange={(e) => handlePickerBoqChange(e.target.value)}
                        disabled={!linkPickerProjectId || linkBoqsLoading}
                        className="text-[10px] rounded border border-border-subtle bg-surface-primary px-1 py-0.5 text-content-primary disabled:opacity-60"
                        aria-label={t('takeoff.bulk_add_target_boq', {
                          defaultValue: 'Target BOQ',
                        })}
                      >
                        <option value="">
                          {linkBoqsLoading
                            ? t('common.loading', { defaultValue: 'Loading...' })
                            : t('takeoff.pick_boq', { defaultValue: '- BOQ -' })}
                        </option>
                        {linkPickerBoqs.map((b) => (
                          <option key={b.id} value={b.id}>{b.name}</option>
                        ))}
                      </select>
                    </div>
                    <button
                      type="button"
                      onClick={handleBulkAddConfirm}
                      disabled={linkingInProgress || !linkPickerBoqId}
                      className="w-full flex items-center justify-center gap-1.5 px-2 py-1 rounded text-[10px] font-semibold bg-oe-blue text-white hover:bg-oe-blue/90 disabled:opacity-50 transition-colors"
                      data-testid="ledger-bulk-add-confirm"
                    >
                      {linkingInProgress && <Loader2 size={10} className="animate-spin" />}
                      {t('takeoff.bulk_add_confirm', {
                        defaultValue: 'Create {{count}} positions',
                        count: bulkAddMeasurements.length,
                      })}
                    </button>
                  </div>
                )}
                <MeasurementLedger
                  measurements={measurements}
                  groupColorMap={groupColorMap}
                  onRowClick={handleLedgerRowClick}
                  selectedMeasurementId={selectedMeasurementId}
                  onAddToBoq={handleLedgerAddToBoq}
                  onAddAllToBoq={handleLedgerAddAllToBoq}
                  onCreateRfi={openRfiForMeasurement}
                />
              </div>
            )}

            {/* Properties panel — shown when a measurement is selected in the list */}
            {sidebarTab === 'properties' && selectedMeasurement && (
              <div
                className="rounded-md border border-oe-blue/40 bg-oe-blue/5 backdrop-blur-sm p-3 shadow-sm space-y-2.5 animate-fade-in"
                data-testid="properties-panel"
              >
                <div className="flex items-center justify-between">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-oe-blue">
                    {t('takeoff_viewer.properties', { defaultValue: 'Properties' })}
                  </p>
                  <button
                    type="button"
                    onClick={() => setSelectedMeasurementId(null)}
                    className="text-content-tertiary hover:text-content-primary transition-colors"
                    aria-label={t('takeoff_viewer.close_properties', { defaultValue: 'Close properties' })}
                  >
                    <X size={12} />
                  </button>
                </div>

                {/* Linked in - cross-module references for this measurement.
                    Read-only chips; self-hides when the measurement has never
                    synced (no serverId) or carries no links yet. */}
                {selectedMeasurement.serverId && (
                  <ReferencedInPanel
                    projectId={activeProjectId || selectedProjectId || ''}
                    fileKind="takeoff"
                    fileId={selectedMeasurement.serverId}
                    onChipClick={(ref) => {
                      const openTab = (path: string) => openLink(path);
                      switch (ref.target_type) {
                        case 'rfi':
                          openTab(`/rfi/${ref.target_id}`);
                          break;
                        case 'punch_item':
                          openTab(`/punchlist?highlight=${ref.target_id}`);
                          break;
                        case 'task':
                          openTab('/tasks');
                          break;
                        case 'boq_position':
                          // The reference carries the position id, not the
                          // owning BOQ id, so land on the BOQ list with the
                          // position highlighted instead of guessing a boqId.
                          openTab(`/boq?highlight=${ref.target_id}`);
                          break;
                        case 'ncr':
                          openTab(`/ncr?highlight=${ref.target_id}`);
                          break;
                        default:
                          break;
                      }
                    }}
                  />
                )}

                {/* Group dropdown */}
                <div>
                  <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                    {t('takeoff_viewer.prop_group', { defaultValue: 'Group' })}
                  </label>
                  <select
                    value={selectedMeasurement.group}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (val === '__new__') {
                        const name = prompt(t('takeoff_viewer.new_group_prompt', { defaultValue: 'New group name' }));
                        if (name && name.trim()) {
                          updateSelectedMeasurement({ group: name.trim() });
                        }
                        return;
                      }
                      updateSelectedMeasurement({ group: val });
                    }}
                    className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary"
                    data-testid="prop-group-select"
                  >
                    {availableGroups.map((g) => (
                      <option key={g} value={g}>{g}</option>
                    ))}
                    <option value="__new__">{t('takeoff_viewer.new_group', { defaultValue: '+ New group' })}</option>
                  </select>
                </div>

                {/* Color: 6 quick swatches plus a native picker for any hex, so
                    a busy sheet with many measurement types is not limited to
                    six colors (#310). The chosen color persists round-trip and
                    both renderers honor it over the group color. */}
                <div>
                  <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                    {t('takeoff_viewer.prop_color', { defaultValue: 'Color' })}
                  </label>
                  <div className="flex items-center gap-1.5">
                    {ANNOTATION_COLORS.map((c) => (
                      <button
                        key={c.value}
                        type="button"
                        onClick={() => updateSelectedMeasurement({ color: c.value })}
                        className={clsx(
                          'h-5 w-5 rounded-full border-2 transition-all',
                          (selectedMeasurement.color ?? '') === c.value
                            ? 'border-content-primary scale-110'
                            : 'border-transparent hover:scale-105',
                        )}
                        style={{ backgroundColor: c.value }}
                        title={c.name}
                        aria-label={c.name}
                        data-testid={`prop-color-${c.name.toLowerCase()}`}
                      />
                    ))}
                    <input
                      type="color"
                      value={selectedMeasurement.color || groupColorMap[selectedMeasurement.group] || '#3B82F6'}
                      onChange={(e) => updateSelectedMeasurement({ color: e.target.value })}
                      className="h-5 w-6 cursor-pointer rounded border border-border bg-transparent p-0"
                      title={t('takeoff_viewer.prop_color_custom', { defaultValue: 'Custom color' })}
                      aria-label={t('takeoff_viewer.prop_color_custom', { defaultValue: 'Custom color' })}
                      data-testid="prop-color-custom"
                    />
                  </div>
                </div>

                {/* Fill opacity (issue #311): area, volume and count carry a
                    tinted fill; let the estimator raise it when hatching under an
                    area hides the tint, or lower it to read overlapping areas.
                    Unset uses the per-type default (15% area/volume, 30% count). */}
                {(selectedMeasurement.type === 'area' ||
                  selectedMeasurement.type === 'volume' ||
                  selectedMeasurement.type === 'count') && (
                  <div>
                    <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                      <span>{t('takeoff_viewer.prop_fill_opacity', { defaultValue: 'Fill opacity' })}</span>
                      <span className="tabular-nums">
                        {Math.round(
                          (selectedMeasurement.fillAlpha ??
                            (selectedMeasurement.type === 'count' ? 0.3 : 0.15)) * 100,
                        )}
                        %
                      </span>
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min={0}
                        max={100}
                        step={5}
                        value={Math.round(
                          (selectedMeasurement.fillAlpha ??
                            (selectedMeasurement.type === 'count' ? 0.3 : 0.15)) * 100,
                        )}
                        onChange={(e) =>
                          updateSelectedMeasurement({ fillAlpha: Number(e.target.value) / 100 })
                        }
                        className="flex-1"
                        data-testid="prop-fill-opacity"
                      />
                      {selectedMeasurement.fillAlpha != null && (
                        <button
                          type="button"
                          onClick={() => updateSelectedMeasurement({ fillAlpha: undefined })}
                          className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                          data-testid="prop-fill-opacity-reset"
                        >
                          {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Line width (issues #312/#339): distance and polyline runs render
                    at a 2px hairline; raise it so two near-identical lines (a footing
                    and the stem wall above it) can be told apart. The unit select
                    switches between screen pixels and the drawing's real-world unit
                    (issue #339): a real width (metres, or feet + decimal inches) makes
                    the band render at the element's TRUE width and stay consistent
                    across pages calibrated at different scales. Unset = 2px. */}
                {(selectedMeasurement.type === 'distance' ||
                  selectedMeasurement.type === 'polyline') && (
                  <div>
                    <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                      <span>{t('takeoff_viewer.prop_stroke_width', { defaultValue: 'Line width' })}</span>
                      <select
                        value={widthMode}
                        onChange={(e) => handleWidthUnitChange(e.target.value as 'px' | 'real')}
                        className="rounded border border-border bg-surface-primary px-1 py-0.5 text-[10px] text-content-primary"
                        data-testid="prop-width-unit"
                      >
                        <option value="px">{t('takeoff_viewer.width_unit_px', { defaultValue: 'px' })}</option>
                        <option value="real">
                          {measurementSystem === 'imperial'
                            ? t('takeoff_viewer.width_unit_ftin', { defaultValue: 'ft + in' })
                            : t('takeoff_viewer.width_unit_m', { defaultValue: 'm' })}
                        </option>
                      </select>
                    </label>
                    {widthMode === 'px' ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="range"
                          min={1}
                          max={50}
                          step={1}
                          value={Math.min(selectedMeasurement.strokeWidth ?? 2, 50)}
                          onChange={(e) =>
                            updateSelectedMeasurement({
                              strokeWidth: Number(e.target.value),
                              strokeWidthReal: undefined,
                            })
                          }
                          className="flex-1"
                          data-testid="prop-stroke-width"
                        />
                        {/* Numeric field so a width beyond the 50px slider can be typed
                            for very wide elements like a continuous footing (issue #338);
                            clamped to 1-100px. The slider value above is capped at its own
                            max so the thumb stays valid when a larger width is typed here. */}
                        <input
                          type="number"
                          min={1}
                          max={100}
                          step={1}
                          value={selectedMeasurement.strokeWidth ?? 2}
                          onChange={(e) => {
                            const v = Number(e.target.value);
                            if (!Number.isFinite(v) || v < 1) return;
                            updateSelectedMeasurement({
                              strokeWidth: Math.min(100, Math.round(v)),
                              strokeWidthReal: undefined,
                            });
                          }}
                          className="w-16 rounded border border-border bg-surface-primary px-1.5 py-1 text-xs text-content-primary tabular-nums"
                          data-testid="prop-stroke-width-num"
                        />
                        {selectedMeasurement.strokeWidth != null && (
                          <button
                            type="button"
                            onClick={() => updateSelectedMeasurement({ strokeWidth: undefined })}
                            className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                            data-testid="prop-stroke-width-reset"
                          >
                            {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                          </button>
                        )}
                      </div>
                    ) : (
                      <div>
                        <div className="flex items-center gap-2">
                          {measurementSystem === 'imperial' ? (
                            <>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={widthDraft.ft}
                                onChange={(e) => {
                                  const nextDraft = { ...widthDraft, ft: e.target.value };
                                  setWidthDraft(nextDraft);
                                  applyRealWidthFromDraft(nextDraft);
                                }}
                                className="w-14 rounded border border-border bg-surface-primary px-1.5 py-1 text-xs text-content-primary tabular-nums"
                                data-testid="prop-stroke-width-ft"
                              />
                              <span className="text-[10px] text-content-tertiary">
                                {t('takeoff_viewer.width_unit_ft', { defaultValue: 'ft' })}
                              </span>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={widthDraft.in}
                                onChange={(e) => {
                                  const nextDraft = { ...widthDraft, in: e.target.value };
                                  setWidthDraft(nextDraft);
                                  applyRealWidthFromDraft(nextDraft);
                                }}
                                className="w-16 rounded border border-border bg-surface-primary px-1.5 py-1 text-xs text-content-primary tabular-nums"
                                data-testid="prop-stroke-width-in"
                              />
                              <span className="text-[10px] text-content-tertiary">
                                {t('takeoff_viewer.width_unit_in', { defaultValue: 'in' })}
                              </span>
                            </>
                          ) : (
                            <>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={widthDraft.m}
                                onChange={(e) => {
                                  const nextDraft = { ...widthDraft, m: e.target.value };
                                  setWidthDraft(nextDraft);
                                  applyRealWidthFromDraft(nextDraft);
                                }}
                                className="w-20 rounded border border-border bg-surface-primary px-1.5 py-1 text-xs text-content-primary tabular-nums"
                                data-testid="prop-stroke-width-m"
                              />
                              <span className="text-[10px] text-content-tertiary">
                                {t('takeoff_viewer.width_unit_m', { defaultValue: 'm' })}
                              </span>
                            </>
                          )}
                          {selectedMeasurement.strokeWidthReal != null && (
                            <button
                              type="button"
                              onClick={() => {
                                setWidthDraft({ m: '', ft: '', in: '' });
                                updateSelectedMeasurement({ strokeWidthReal: undefined });
                              }}
                              className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                              data-testid="prop-stroke-width-real-reset"
                            >
                              {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                            </button>
                          )}
                        </div>
                        {/* A real width only renders correctly once the page has a
                            true scale; on an uncalibrated sheet pixelsPerUnit is the
                            placeholder default, so warn the user to calibrate. */}
                        {!pageIsCalibrated(pageScales, selectedMeasurement.page) && (
                          <p
                            className="mt-1 text-[10px] leading-tight text-amber-700 dark:text-amber-300"
                            data-testid="prop-width-not-calibrated"
                          >
                            {t('takeoff_viewer.width_not_calibrated', {
                              defaultValue: 'Calibrate this page to size the line in real-world units.',
                            })}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Line opacity (issue #332): distance + polyline runs draw fully
                    opaque; let the estimator fade a reference / underlay run so a
                    busy sheet reads. Mirrors the #311 fill-opacity slider. Unset =
                    fully opaque (100%), so lines are unchanged until touched. */}
                {(selectedMeasurement.type === 'distance' ||
                  selectedMeasurement.type === 'polyline') && (
                  <div>
                    <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                      <span>{t('takeoff_viewer.prop_stroke_opacity', { defaultValue: 'Line opacity' })}</span>
                      <span className="tabular-nums">
                        {Math.round((selectedMeasurement.strokeAlpha ?? 1) * 100)}%
                      </span>
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min={0}
                        max={100}
                        step={5}
                        value={Math.round((selectedMeasurement.strokeAlpha ?? 1) * 100)}
                        onChange={(e) =>
                          updateSelectedMeasurement({ strokeAlpha: Number(e.target.value) / 100 })
                        }
                        className="flex-1"
                        data-testid="prop-stroke-opacity"
                      />
                      {selectedMeasurement.strokeAlpha != null && (
                        <button
                          type="button"
                          onClick={() => updateSelectedMeasurement({ strokeAlpha: undefined })}
                          className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                          data-testid="prop-stroke-opacity-reset"
                        >
                          {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Value + Unit (read-only for computed types) */}
                <div className="grid grid-cols-[1fr_auto] gap-2">
                  <div>
                    <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                      {t('takeoff_viewer.prop_value', { defaultValue: 'Value' })}
                    </label>
                    <div
                      className="w-full rounded border border-border/60 bg-surface-secondary/60 px-2 py-1 text-xs text-content-primary font-mono tabular-nums"
                      data-testid="prop-value"
                    >
                      {selectedMeasurement.value
                        ? convertQuantity(
                            selectedMeasurement.value,
                            selectedMeasurement.unit || '',
                            measurementSystem,
                          ).value.toFixed(3)
                        : '—'}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                      {t('takeoff_viewer.prop_unit', { defaultValue: 'Unit' })}
                    </label>
                    <div
                      className="min-w-[44px] rounded border border-border/60 bg-surface-secondary/60 px-2 py-1 text-xs text-content-primary text-center"
                      data-testid="prop-unit"
                    >
                      {displayUnitFor(selectedMeasurement.unit || '', measurementSystem) || '—'}
                    </div>
                  </div>
                </div>

                {/* Opening deduction toggle - area measurements only. A
                    deduction (door / window / cut-out) is subtracted from the
                    group's gross area so a net area = gross - openings. */}
                {selectedMeasurement.type === 'area' && (
                  <label
                    className="flex items-center gap-2 rounded border border-border/60 bg-surface-secondary/40 px-2 py-1.5 cursor-pointer"
                    data-testid="prop-deduction-toggle"
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(selectedMeasurement.isDeduction)}
                      onChange={(e) => updateSelectedMeasurement({ isDeduction: e.target.checked })}
                      className="h-3.5 w-3.5 accent-semantic-error"
                    />
                    <span className="text-[11px] text-content-secondary">
                      {t('takeoff_viewer.prop_deduction', {
                        defaultValue: 'Opening / deduction (subtract from net area)',
                      })}
                    </span>
                  </label>
                )}

                {/* Reported-quantity adjustments (issue #332 wave): slope /
                    pitch (area only), wastage %, and a typical multiplier. Each
                    defaults to its identity value, so an untouched measurement
                    reports its raw geometry. Shown for measurable types only. */}
                {(selectedMeasurement.type === 'distance' ||
                  selectedMeasurement.type === 'polyline' ||
                  selectedMeasurement.type === 'area' ||
                  selectedMeasurement.type === 'volume' ||
                  selectedMeasurement.type === 'count') && (
                  <div
                    className="space-y-2 rounded border border-border/60 bg-surface-secondary/30 p-2"
                    data-testid="prop-adjustments"
                  >
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('takeoff_viewer.prop_adjustments', { defaultValue: 'Quantity adjustments' })}
                    </p>

                    {/* Slope / pitch (area only): true surface = plan x factor.
                        Accepts either a factor (>=1) or a pitch in degrees
                        (factor = 1 / cos(deg)); editing one syncs the other. */}
                    {selectedMeasurement.type === 'area' && (
                      <div>
                        <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                          <span>{t('takeoff_viewer.prop_slope', { defaultValue: 'Slope / pitch (roof, ramp)' })}</span>
                          {selectedMeasurement.slopeFactor != null && (
                            <button
                              type="button"
                              onClick={() => updateSelectedMeasurement({ slopeFactor: undefined })}
                              className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                              data-testid="prop-slope-reset"
                            >
                              {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                            </button>
                          )}
                        </label>
                        <div className="flex items-end gap-1.5">
                          <label className="flex-1 flex flex-col gap-0.5">
                            <input
                              type="number"
                              min={1}
                              step={0.01}
                              value={selectedMeasurement.slopeFactor ?? 1}
                              onChange={(e) => {
                                const v = Number(e.target.value);
                                updateSelectedMeasurement({
                                  slopeFactor: Number.isFinite(v) && v > 1 ? v : undefined,
                                });
                              }}
                              className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary tabular-nums"
                              data-testid="prop-slope-factor"
                            />
                            <span className="text-[9px] text-content-quaternary">
                              {t('takeoff_viewer.prop_slope_factor', { defaultValue: 'factor' })}
                            </span>
                          </label>
                          <label className="flex-1 flex flex-col gap-0.5">
                            <input
                              type="number"
                              min={0}
                              max={89}
                              step={0.5}
                              value={Number(
                                degreesFromSlopeFactor(selectedMeasurement.slopeFactor ?? 1).toFixed(1),
                              )}
                              onChange={(e) => {
                                const deg = Number(e.target.value);
                                const f = slopeFactorFromDegrees(deg);
                                updateSelectedMeasurement({ slopeFactor: f > 1 ? f : undefined });
                              }}
                              className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary tabular-nums"
                              data-testid="prop-slope-degrees"
                            />
                            <span className="text-[9px] text-content-quaternary">
                              {t('takeoff_viewer.prop_slope_degrees', { defaultValue: 'pitch °' })}
                            </span>
                          </label>
                        </div>
                      </div>
                    )}

                    {/* Wastage / allowance % (all measurable types). */}
                    <div>
                      <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                        <span>{t('takeoff_viewer.prop_wastage', { defaultValue: 'Wastage / allowance %' })}</span>
                        {selectedMeasurement.wastagePct != null && (
                          <button
                            type="button"
                            onClick={() => updateSelectedMeasurement({ wastagePct: undefined })}
                            className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                            data-testid="prop-wastage-reset"
                          >
                            {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                          </button>
                        )}
                      </label>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={selectedMeasurement.wastagePct ?? 0}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          updateSelectedMeasurement({
                            wastagePct: Number.isFinite(v) && v > 0 ? v : undefined,
                          });
                        }}
                        className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary tabular-nums"
                        data-testid="prop-wastage"
                      />
                    </div>

                    {/* Typical multiplier (all measurable types): this shape
                        stands for N identical repeats (typical floors / bays). */}
                    <div>
                      <label className="text-[10px] font-semibold text-content-tertiary flex items-center justify-between mb-0.5">
                        <span>{t('takeoff_viewer.prop_multiplier', { defaultValue: 'Typical multiplier (x)' })}</span>
                        {selectedMeasurement.multiplier != null && (
                          <button
                            type="button"
                            onClick={() => updateSelectedMeasurement({ multiplier: undefined })}
                            className="text-[10px] text-content-tertiary hover:text-content-primary underline"
                            data-testid="prop-multiplier-reset"
                          >
                            {t('takeoff_viewer.reset', { defaultValue: 'Reset' })}
                          </button>
                        )}
                      </label>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={selectedMeasurement.multiplier ?? 1}
                        onChange={(e) => {
                          const v = Math.floor(Number(e.target.value));
                          updateSelectedMeasurement({
                            multiplier: Number.isFinite(v) && v > 1 ? v : undefined,
                          });
                        }}
                        className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary tabular-nums"
                        data-testid="prop-multiplier"
                      />
                    </div>

                    {/* Effective (reported) quantity - shown only when a factor
                        is active so an unadjusted measurement stays uncluttered. */}
                    {hasQuantityFactor(selectedMeasurement) && (
                      <div className="flex items-center justify-between text-[11px] pt-0.5 border-t border-border/50">
                        <span className="text-content-tertiary">
                          {t('takeoff_viewer.prop_effective_qty', { defaultValue: 'Effective qty' })}
                        </span>
                        <span
                          className="font-mono tabular-nums text-oe-blue font-semibold"
                          data-testid="prop-effective-qty"
                        >
                          {(() => {
                            const eff = convertQuantity(
                              Math.abs(effectiveQuantity(selectedMeasurement)),
                              selectedMeasurement.unit || '',
                              measurementSystem,
                            );
                            return `${eff.value.toFixed(3)} ${eff.unit}`;
                          })()}
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {/* Annotation / label */}
                <div>
                  <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                    {t('takeoff_viewer.prop_annotation', { defaultValue: 'Annotation' })}
                  </label>
                  <input
                    type="text"
                    value={selectedMeasurement.annotation}
                    onChange={(e) => updateSelectedMeasurement({ annotation: e.target.value })}
                    placeholder={t('takeoff_viewer.prop_annotation_placeholder', { defaultValue: 'Label for this measurement' })}
                    className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary"
                    data-testid="prop-annotation-input"
                  />
                </div>

                {/* Notes */}
                <div>
                  <label className="text-[10px] font-semibold text-content-tertiary block mb-0.5">
                    {t('takeoff_viewer.prop_notes', { defaultValue: 'Notes' })}
                  </label>
                  <textarea
                    value={selectedMeasurement.notes ?? ''}
                    onChange={(e) => updateSelectedMeasurement({ notes: e.target.value })}
                    placeholder={t('takeoff_viewer.prop_notes_placeholder', { defaultValue: 'Additional details...' })}
                    rows={3}
                    className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary resize-none"
                    data-testid="prop-notes-input"
                  />
                </div>

                {/* Copy to pages (issue #332 wave): the "typical floor"
                    shortcut - replicate this measurement, or its whole group on
                    this page, onto other selected sheets as fresh unlinked
                    measurements. Hidden for a single-page document. */}
                {totalPages > 1 && (
                  <div
                    className="space-y-1.5 rounded border border-border/60 bg-surface-secondary/30 p-2"
                    data-testid="prop-copy-to-pages"
                  >
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('takeoff_viewer.prop_copy_to_pages', { defaultValue: 'Copy to pages' })}
                    </p>
                    <div className="flex flex-wrap gap-1 max-h-24 overflow-auto">
                      {Array.from({ length: totalPages }, (_, i) => i + 1)
                        .filter((p) => p !== selectedMeasurement.page)
                        .map((p) => {
                          const on = copyTargetPages.has(p);
                          return (
                            <button
                              key={p}
                              type="button"
                              onClick={() =>
                                setCopyTargetPages((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(p)) next.delete(p);
                                  else next.add(p);
                                  return next;
                                })
                              }
                              className={clsx(
                                'px-1.5 py-0.5 rounded text-[10px] border tabular-nums transition-colors',
                                on
                                  ? 'bg-oe-blue/15 text-oe-blue border-oe-blue/30'
                                  : 'bg-surface-primary text-content-secondary border-border hover:border-oe-blue/40',
                              )}
                              data-testid="copy-page-chip"
                              data-page={p}
                              data-active={on}
                            >
                              {p}
                            </button>
                          );
                        })}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={copyTargetPages.size === 0}
                        onClick={() =>
                          copyMeasurementsToPages([selectedMeasurement], Array.from(copyTargetPages))
                        }
                        className="flex-1 rounded bg-oe-blue/10 text-oe-blue border border-oe-blue/30 hover:bg-oe-blue/20 disabled:opacity-40 disabled:pointer-events-none px-2 py-1 text-[11px] font-semibold transition-colors"
                        data-testid="copy-measurement-btn"
                      >
                        {t('takeoff_viewer.copy_measurement', { defaultValue: 'This measurement' })}
                      </button>
                      <button
                        type="button"
                        disabled={copyTargetPages.size === 0}
                        onClick={() => {
                          const groupHere = measurements.filter(
                            (mm) =>
                              mm.page === selectedMeasurement.page &&
                              mm.group === selectedMeasurement.group &&
                              !mm.suggested,
                          );
                          copyMeasurementsToPages(groupHere, Array.from(copyTargetPages));
                        }}
                        className="flex-1 rounded bg-surface-primary text-content-secondary border border-border hover:border-oe-blue/40 disabled:opacity-40 disabled:pointer-events-none px-2 py-1 text-[11px] font-semibold transition-colors"
                        data-testid="copy-group-btn"
                        title={t('takeoff_viewer.copy_group_hint', {
                          defaultValue: 'Copy every measurement in this group on this page',
                        })}
                      >
                        {t('takeoff_viewer.copy_group', { defaultValue: 'Whole group' })}
                      </button>
                    </div>
                  </div>
                )}

                {/* Delete button */}
                <button
                  type="button"
                  onClick={() => deleteMeasurement(selectedMeasurement.id)}
                  className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-semantic-error-bg text-semantic-error hover:bg-semantic-error hover:text-white px-2 py-1.5 text-xs font-semibold transition-colors border border-semantic-error/30"
                  data-testid="prop-delete-button"
                >
                  <Trash2 size={12} />
                  {t('takeoff_viewer.prop_delete', { defaultValue: 'Delete measurement' })}
                </button>

                {/* Match to a cost position - search every loaded cost catalogue by
                    this measurement's type/size and apply a priced BOQ position to it. */}
                {activeProjectId && (
                  <div className="pt-2 border-t border-oe-blue/20">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-oe-blue mb-1.5">
                      {t('match.apply_section_title', { defaultValue: 'Find a cost position' })}
                    </p>
                    <div className="h-96 rounded-md border border-border-light overflow-hidden bg-surface-primary">
                      <ElementCostMatchPanel
                        key={selectedMeasurement.id}
                        source="pdf"
                        projectId={activeProjectId}
                        elementKey={selectedMeasurement.id}
                        compact
                        rawElementData={{
                          source: 'pdf',
                          id: selectedMeasurement.id,
                          label: selectedMeasurement.label ?? selectedMeasurement.annotation ?? '',
                          measurementType: selectedMeasurement.type,
                          value: selectedMeasurement.value,
                          unit: selectedMeasurement.unit,
                          properties: selectedMeasurement.annotation
                            ? { note: selectedMeasurement.annotation }
                            : {},
                        }}
                        envelope={{
                          category: selectedMeasurement.type,
                          description:
                            selectedMeasurement.label ||
                            selectedMeasurement.annotation ||
                            selectedMeasurement.type,
                          quantities: pdfMeasurementQuantities(selectedMeasurement),
                          unitHint: selectedMeasurement.unit || null,
                        }}
                        quantityOverride={
                          Number.isFinite(selectedMeasurement.value)
                            ? selectedMeasurement.value
                            : null
                        }
                        onApplied={async (result) => {
                          // Native back-link: bind the created position to this measurement
                          // so the takeoff row shows as linked. Only synced measurements
                          // (with a serverId) can be linked; unsynced ones still got a
                          // priced position created in the BOQ.
                          if (selectedMeasurement.serverId) {
                            await takeoffApi.linkToBoq(selectedMeasurement.serverId, result.position_id, {
                              pushQuantity: false,
                            });
                          }
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Measurements list (grouped) — only on Properties tab; the
                Ledger tab renders its own, cross-page table instead. */}
            {sidebarTab === 'properties' && (
            <div className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-content-primary">
                  {t('takeoff_viewer.measurements', { defaultValue: 'Measurements' })}{' '}
                  <span className="tabular-nums text-content-tertiary font-normal">
                    {(() => {
                      const onPage = pageMeasurements.filter((m) => !isAnnotationType(m.type)).length;
                      const total = measurements.filter((m) => !isAnnotationType(m.type)).length;
                      // "5 on page · 31 total" reads as "yes your data is still there".
                      return total > onPage
                        ? t('takeoff_viewer.measurement_count_split', {
                            defaultValue: '({{onPage}} on page · {{total}} total)',
                            onPage,
                            total,
                          })
                        : `(${onPage})`;
                    })()}
                  </span>
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
                      aria-label={t('takeoff_viewer.save_measurements', { defaultValue: 'Save measurements' })}
                    >
                      <Save className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>

              {pageMeasurements.length === 0 && (() => {
                const totalOtherPages = measurements.filter(
                  (m) => !isAnnotationType(m.type) && m.page !== currentPage,
                ).length;
                return (
                  <p className="text-xs text-content-tertiary py-4 text-center px-2">
                    {totalOtherPages > 0
                      ? t('takeoff_viewer.no_measurements_this_page', {
                          defaultValue:
                            'No measurements on page {{page}}. {{count}} measurement(s) on other pages - open the Ledger tab to see them all.',
                          page: currentPage,
                          count: totalOtherPages,
                        })
                      : t('takeoff_viewer.no_measurements', {
                          defaultValue:
                            'No measurements yet. Select a tool and click on the drawing.',
                        })}
                  </p>
                );
              })()}

              <div className="space-y-2 max-h-[400px] overflow-auto">
                {/* Measurement groups (non-annotation types) */}
                {Object.entries(groupedPageMeasurements).map(([groupName, groupMs]) => {
                  const measurementOnly = groupMs.filter((m) => !isAnnotationType(m.type));
                  if (measurementOnly.length === 0) return null;
                  const groupColor = groupColorMap[groupName] || '#3B82F6';
                  const isHidden = hiddenGroups.has(groupName);
                  const isCollapsed = collapsedGroups.has(groupName);
                  return (
                    <div key={groupName}>
                      {/* Group header */}
                      <div className="flex items-center gap-1.5 mb-1">
                        <button
                          onClick={() => toggleGroupCollapse(groupName)}
                          className="p-0.5 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                          aria-label={isCollapsed
                            ? t('takeoff_viewer.expand_group', { defaultValue: 'Expand group' })
                            : t('takeoff_viewer.collapse_group', { defaultValue: 'Collapse group' })
                          }
                          title={isCollapsed
                            ? t('takeoff_viewer.expand_group', { defaultValue: 'Expand group' })
                            : t('takeoff_viewer.collapse_group', { defaultValue: 'Collapse group' })
                          }
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
                              onClick={() => setSelectedMeasurementId((cur) => (cur === m.id ? null : m.id))}
                              className={clsx(
                                'rounded-sm px-2 py-1 group/item transition-all cursor-pointer',
                                selectedMeasurementId === m.id
                                  ? 'bg-oe-blue/10 border border-oe-blue/40'
                                  : 'bg-surface-secondary/70 hover:bg-surface-secondary border border-transparent hover:border-border-light',
                                // Dim a hidden measurement, keeping it listed so it
                                // can be restored, the way hidden groups behave (#359).
                                hiddenMeasurements.has(m.id) && 'opacity-50',
                              )}
                              data-testid="measurement-item"
                              data-selected={selectedMeasurementId === m.id}
                              data-hidden={hiddenMeasurements.has(m.id)}
                            >
                              <div className="flex items-center gap-2 leading-tight">
                                <span
                                  className="h-2 w-2 rounded-full shrink-0"
                                  style={{ backgroundColor: groupColor }}
                                />
                                <div className="flex-1 min-w-0 flex items-center gap-1.5">
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
                                      onClick={(e) => { e.stopPropagation(); startEditAnnotation(m); }}
                                      className="flex items-center gap-1 text-xs font-medium text-content-primary truncate hover:text-oe-blue transition-colors min-w-0 text-left"
                                      title={t('takeoff.add_label', { defaultValue: 'Add label...' })}
                                    >
                                      <span className="truncate">{m.annotation}</span>
                                      <Pencil size={10} className="shrink-0 opacity-0 group-hover/item:opacity-60 transition-opacity" />
                                    </button>
                                  )}
                                  <span className="text-2xs text-content-tertiary capitalize truncate shrink">
                                    {/* Issue #287: show the measurement label in the
                                        user's system (m -> ft); identity for metric. */}
                                    {measurementLabel(m, scale, measurementSystem)}
                                  </span>
                                  {m.suggested && (
                                    <span
                                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300 text-[9px] font-semibold shrink-0"
                                      title={t('takeoff_viewer.suggested_hint', { defaultValue: 'AI suggestion - accept to keep it' })}
                                    >
                                      <Sparkles size={8} />
                                      {typeof m.confidence === 'number' ? `${Math.round(m.confidence * 100)}%` : t('takeoff_viewer.suggested', { defaultValue: 'AI' })}
                                    </span>
                                  )}
                                  {m.linkedPositionOrdinal && (
                                    <button
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); handleOpenLinkedPosition(m); }}
                                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 text-[9px] font-mono font-semibold hover:bg-emerald-200 dark:hover:bg-emerald-900/70 transition-colors shrink-0"
                                      title={`${t('takeoff.linked_badge_title', { defaultValue: 'Linked to BOQ' })}: ${m.linkedPositionOrdinal}`}
                                    >
                                      <Link2 size={8} />
                                      {m.linkedPositionOrdinal}
                                    </button>
                                  )}
                                </div>
                                <div className="flex items-center gap-0.5 shrink-0">
                                  {/* Accept / reject AI suggestions inline (#194). */}
                                  {m.suggested && (
                                    <>
                                      <button
                                        onClick={(e) => { e.stopPropagation(); acceptSuggestion(m.id); }}
                                        className="p-0.5 rounded text-emerald-600 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition-colors"
                                        aria-label={t('takeoff_viewer.accept_suggestion', { defaultValue: 'Accept suggestion' })}
                                        title={t('takeoff_viewer.accept_suggestion', { defaultValue: 'Accept suggestion' })}
                                        data-testid="accept-suggestion"
                                      >
                                        <Check size={13} />
                                      </button>
                                      <button
                                        onClick={(e) => { e.stopPropagation(); rejectSuggestion(m.id); }}
                                        className="p-0.5 rounded text-rose-500 hover:bg-rose-100 dark:hover:bg-rose-900/30 transition-colors"
                                        aria-label={t('takeoff_viewer.reject_suggestion', { defaultValue: 'Reject suggestion' })}
                                        title={t('takeoff_viewer.reject_suggestion', { defaultValue: 'Reject suggestion' })}
                                        data-testid="reject-suggestion"
                                      >
                                        <X size={13} />
                                      </button>
                                    </>
                                  )}
                                  {/* Link to BOQ button — always visible (the primary
                                      per-measurement action). Linked rows get an emerald
                                      tint; unlinked rows get a rose tint that strengthens
                                      on hover. Discoverability matters here: hover-only
                                      revealed too late for first-time users. */}
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handleOpenLinkToBoq(m.id); }}
                                    className={clsx(
                                      'transition-all p-0.5 rounded',
                                      m.linkedPositionId
                                        ? 'text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                                        : 'text-rose-500/60 dark:text-rose-400/60 hover:text-rose-700 dark:hover:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/30',
                                    )}
                                    aria-label={t('takeoff_viewer.link_to_boq', { defaultValue: 'Link to BOQ' })}
                                    title={
                                      m.linkedPositionId
                                        ? t('takeoff_viewer.relink_to_boq', { defaultValue: 'Re-link or unlink BOQ position' })
                                        : t('takeoff_viewer.link_to_boq_hint', {
                                            defaultValue: 'Push this measurement\'s quantity to a BOQ position',
                                          })
                                    }
                                  >
                                    <Link2 size={12} />
                                  </button>
                                  {/* Per-measurement visibility toggle (#359):
                                      hide one measurement from the canvas without
                                      moving it into its own group. View-only. */}
                                  <button
                                    onClick={(e) => { e.stopPropagation(); toggleMeasurementVisibility(m.id); }}
                                    className="p-0.5 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors shrink-0"
                                    aria-label={hiddenMeasurements.has(m.id)
                                      ? t('takeoff_viewer.show_measurement', { defaultValue: 'Show measurement' })
                                      : t('takeoff_viewer.hide_measurement', { defaultValue: 'Hide measurement' })
                                    }
                                    title={hiddenMeasurements.has(m.id)
                                      ? t('takeoff_viewer.show_measurement', { defaultValue: 'Show measurement' })
                                      : t('takeoff_viewer.hide_measurement', { defaultValue: 'Hide measurement' })
                                    }
                                    data-testid="toggle-measurement-visibility"
                                  >
                                    {hiddenMeasurements.has(m.id) ? <EyeOff size={12} /> : <Eye size={12} />}
                                  </button>
                                  <button
                                    onClick={(e) => { e.stopPropagation(); deleteMeasurement(m.id); }}
                                    className="opacity-40 group-hover/item:opacity-100 text-content-tertiary hover:text-semantic-error transition-all shrink-0"
                                    aria-label={t('takeoff_viewer.delete_measurement', { defaultValue: 'Delete measurement' })}
                                    title={`${t('takeoff_viewer.delete_measurement', { defaultValue: 'Delete measurement' })} (Del)`}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                              {/* Link to BOQ picker — self-contained, no prerequisites.
                                  Issue #337: the picker renders inside the measurement
                                  row, whose click handler toggles selection and opens the
                                  Properties pane. stopPropagation on the container keeps
                                  every click inside the picker (the project/BOQ dropdowns,
                                  the search box, a position row, even the close button)
                                  from also firing the row handler and toggling the pane. */}
                              {linkingMeasurementId === m.id && (
                                <div
                                  className="mt-1.5 rounded-lg border border-rose-200 dark:border-rose-800/40 bg-rose-50/50 dark:bg-rose-950/20 p-2 animate-fade-in"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-rose-700 dark:text-rose-400">
                                      {m.linkedPositionId
                                        ? t('takeoff_viewer.relink_title', { defaultValue: 'Linked - pick new or unlink' })
                                        : t('takeoff_viewer.link_to_boq_title', { defaultValue: 'Link to BOQ position' })}
                                    </span>
                                    <button
                                      onClick={() => setLinkingMeasurementId(null)}
                                      className="text-content-tertiary hover:text-content-primary transition-colors"
                                      aria-label={t('common.close', { defaultValue: 'Close' })}
                                      title={t('common.close', { defaultValue: 'Close' })}
                                    >
                                      <X size={10} />
                                    </button>
                                  </div>

                                  {/* Transfer-preview banner — shows exactly what will
                                      be pushed to the picked position. Removes the "I
                                      hope I clicked the right thing" anxiety. */}
                                  <div className="mb-1.5 flex items-center gap-1.5 rounded bg-rose-100/70 dark:bg-rose-950/40 border border-rose-200/60 dark:border-rose-800/30 px-1.5 py-1 text-[10px]">
                                    <ArrowUpRight size={10} className="text-rose-600 dark:text-rose-400 shrink-0" />
                                    <span className="text-content-tertiary shrink-0">
                                      {t('takeoff.will_transfer', { defaultValue: 'Will transfer:' })}
                                    </span>
                                    <span className="font-mono font-semibold text-rose-700 dark:text-rose-300 tabular-nums">
                                      {/* Issue #287: preview the quantity in the user's
                                          system so it matches the canvas readout. The
                                          value pushed to the position stays metric. */}
                                      {(
                                        Math.round(
                                          convertQuantity(m.value, m.unit || '', measurementSystem).value * 100,
                                        ) / 100
                                      ).toLocaleString()}
                                    </span>
                                    <span className="font-mono text-rose-700/80 dark:text-rose-300/80 shrink-0">
                                      {displayUnitFor(m.unit || '', measurementSystem)}
                                    </span>
                                    {m.page && (
                                      <span className="text-content-tertiary shrink-0 ml-auto">
                                        {t('takeoff_viewer.page_label', { defaultValue: 'Page' })} {m.page}
                                      </span>
                                    )}
                                  </div>

                                  {/* Currently-linked summary + unlink */}
                                  {m.linkedPositionId && (
                                    <div className="mb-1.5 flex items-center gap-1.5 rounded bg-emerald-100/60 dark:bg-emerald-950/30 px-1.5 py-1">
                                      <Link2 size={10} className="text-emerald-700 dark:text-emerald-400 shrink-0" />
                                      <span className="flex-1 min-w-0 text-[10px]">
                                        <span className="font-mono text-emerald-700 dark:text-emerald-400">{m.linkedPositionOrdinal}</span>
                                        {m.linkedPositionLabel && (
                                          <span className="text-content-secondary"> — {m.linkedPositionLabel.slice(0, 40)}</span>
                                        )}
                                      </span>
                                      <button
                                        onClick={() => handleUnlinkMeasurement(m.id)}
                                        disabled={linkingInProgress}
                                        className="text-[10px] text-rose-600 dark:text-rose-400 hover:underline disabled:opacity-50"
                                      >
                                        {t('takeoff.unlink', { defaultValue: 'Unlink' })}
                                      </button>
                                    </div>
                                  )}

                                  {/* Project + BOQ pickers */}
                                  <div className="grid grid-cols-2 gap-1 mb-1.5">
                                    <select
                                      value={linkPickerProjectId}
                                      onChange={(e) => handlePickerProjectChange(e.target.value)}
                                      className="text-[10px] rounded border border-border-subtle bg-surface-primary px-1 py-0.5 text-content-primary"
                                    >
                                      <option value="">{t('takeoff.pick_project', { defaultValue: '- project -' })}</option>
                                      {linkPickerProjects.map((p) => (
                                        <option key={p.id} value={p.id}>{p.name}</option>
                                      ))}
                                    </select>
                                    <select
                                      value={linkPickerBoqId}
                                      onChange={(e) => handlePickerBoqChange(e.target.value)}
                                      disabled={!linkPickerProjectId || linkBoqsLoading}
                                      className="text-[10px] rounded border border-border-subtle bg-surface-primary px-1 py-0.5 text-content-primary disabled:opacity-60"
                                    >
                                      <option value="">
                                        {linkBoqsLoading
                                          ? t('common.loading', { defaultValue: 'Loading...' })
                                          : t('takeoff.pick_boq', { defaultValue: '- BOQ -' })}
                                      </option>
                                      {linkPickerBoqs.map((b) => (
                                        <option key={b.id} value={b.id}>{b.name}</option>
                                      ))}
                                    </select>
                                  </div>

                                  {/* Mode switch: Pick existing / Create new */}
                                  <div className="flex gap-1 mb-1.5 text-[10px]">
                                    <button
                                      type="button"
                                      onClick={() => setLinkPickerMode('pick')}
                                      className={clsx(
                                        'flex-1 px-1.5 py-0.5 rounded font-medium transition-colors',
                                        linkPickerMode === 'pick'
                                          ? 'bg-rose-600 text-white'
                                          : 'bg-surface-primary text-content-secondary hover:bg-rose-100 dark:hover:bg-rose-900/30',
                                      )}
                                    >
                                      {t('takeoff.mode_pick', { defaultValue: 'Pick existing' })}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setLinkPickerMode('create')}
                                      disabled={!linkPickerBoqId}
                                      className={clsx(
                                        'flex-1 px-1.5 py-0.5 rounded font-medium transition-colors disabled:opacity-50',
                                        linkPickerMode === 'create'
                                          ? 'bg-rose-600 text-white'
                                          : 'bg-surface-primary text-content-secondary hover:bg-rose-100 dark:hover:bg-rose-900/30',
                                      )}
                                    >
                                      {t('takeoff.mode_create', { defaultValue: '+ Create new' })}
                                    </button>
                                  </div>

                                  {linkPickerMode === 'pick' ? (
                                    !linkPickerBoqId ? (
                                      <p className="text-[10px] text-content-tertiary py-1">
                                        {t('takeoff.link_need_project_boq', { defaultValue: 'Pick a project and BOQ above.' })}
                                      </p>
                                    ) : linkPositionsLoading ? (
                                      <div className="flex items-center gap-1.5 py-2">
                                        <Loader2 size={12} className="animate-spin text-rose-600" />
                                        <span className="text-[10px] text-content-tertiary">
                                          {t('common.loading', { defaultValue: 'Loading...' })}
                                        </span>
                                      </div>
                                    ) : linkBoqPositions.filter((p) => p.unit).length === 0 ? (
                                      <p className="text-[10px] text-content-tertiary py-1">
                                        {t('takeoff.link_boq_empty', { defaultValue: 'BOQ is empty - switch to "Create new".' })}
                                      </p>
                                    ) : (
                                      <>
                                        <input
                                          type="text"
                                          value={linkPickerSearch}
                                          onChange={(e) => setLinkPickerSearch(e.target.value)}
                                          placeholder={t('takeoff.link_search_placeholder', { defaultValue: 'Search ordinal or description...' })}
                                          className="w-full mb-1 text-[10px] rounded border border-border-subtle bg-surface-primary px-1.5 py-0.5 text-content-primary"
                                        />
                                        <div className="max-h-32 overflow-y-auto space-y-0.5">
                                          {linkBoqPositions
                                            .filter((p) => p.unit)
                                            .filter((p) => {
                                              if (!linkPickerSearch) return true;
                                              const q = linkPickerSearch.toLowerCase();
                                              return (
                                                (p.ordinal || '').toLowerCase().includes(q) ||
                                                (p.description || '').toLowerCase().includes(q)
                                              );
                                            })
                                            .slice(0, 100)
                                            .map((pos) => {
                                              const measurementUnit = normalizeUnit(m.unit);
                                              const unitMismatch = !!pos.unit && !!measurementUnit && pos.unit !== measurementUnit;
                                              // True cross-dimension mismatch (area → m3 etc.) -
                                              // the backend push guard refuses these, and
                                              // handleLinkToPosition surfaces the refusal as an
                                              // error toast instead of silently linking.
                                              const mDim = measurementDimension(m.type, measurementUnit);
                                              const pDim = unitDimension(pos.unit);
                                              const dimensionMismatch = mDim !== null && pDim !== null && mDim !== pDim;
                                              const currentQty = typeof pos.quantity === 'number' ? pos.quantity : Number(pos.quantity ?? 0);
                                              return (
                                                <button
                                                  key={pos.id}
                                                  type="button"
                                                  onClick={() => handleLinkToPosition(m.id, pos)}
                                                  disabled={linkingInProgress}
                                                  className="w-full text-left px-2 py-1 rounded text-[10px] hover:bg-rose-100 dark:hover:bg-rose-900/30 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                                                  title={
                                                    dimensionMismatch
                                                      ? t('takeoff.dimension_mismatch_row_hint', {
                                                          defaultValue: 'Dimension mismatch: a {{measUnit}} measurement cannot fill a {{posUnit}} position.',
                                                          posUnit: pos.unit,
                                                          measUnit: measurementUnit,
                                                        })
                                                      : unitMismatch
                                                        ? t('takeoff.unit_mismatch_warning', {
                                                            defaultValue: 'Unit mismatch: position is in {{posUnit}}, measurement is in {{measUnit}}. Linking will overwrite the position\'s unit.',
                                                            posUnit: pos.unit,
                                                            measUnit: measurementUnit,
                                                          })
                                                        : t('takeoff.link_overwrites_qty', {
                                                            defaultValue: 'Link → overwrites current quantity ({{q}} {{u}}) with the measurement value',
                                                            q: currentQty,
                                                            u: pos.unit ?? '',
                                                          })
                                                  }
                                                >
                                                  <span className="font-mono text-rose-600 dark:text-rose-400 shrink-0">{pos.ordinal}</span>
                                                  <span className="text-content-primary truncate flex-1">{pos.description}</span>
                                                  {/* Current qty badge — shows what's about to be replaced. */}
                                                  {currentQty > 0 && (
                                                    <span className="font-mono tabular-nums text-content-tertiary shrink-0 text-[9px]">
                                                      {currentQty.toLocaleString()}
                                                    </span>
                                                  )}
                                                  {unitMismatch ? (
                                                    <span className="inline-flex items-center gap-0.5 font-mono shrink-0 text-[9px] text-amber-600 dark:text-amber-400" aria-label={t('takeoff.unit_mismatch', { defaultValue: 'unit mismatch' })}>
                                                      <AlertTriangle size={9} />
                                                      {pos.unit}
                                                    </span>
                                                  ) : (
                                                    <span className="text-content-tertiary shrink-0 text-[9px]">{pos.unit}</span>
                                                  )}
                                                </button>
                                              );
                                            })}
                                        </div>
                                      </>
                                    )
                                  ) : (
                                    /* Create new position from measurement */
                                    <div className="rounded bg-surface-primary/60 p-1.5 space-y-1">
                                      <div className="grid grid-cols-[auto_1fr] gap-x-1.5 text-[10px] text-content-secondary">
                                        <span className="font-semibold">{t('takeoff.description', { defaultValue: 'Description' })}:</span>
                                        <span className="text-content-primary truncate">
                                          {m.annotation || `${m.type} page ${m.page}`}
                                        </span>
                                        <span className="font-semibold">{t('takeoff.quantity', { defaultValue: 'Quantity' })}:</span>
                                        <span className="text-content-primary font-mono">
                                          {/* Issue #287: display the quantity in the user's
                                              system; the created position stores metric. */}
                                          {Math.round(
                                            convertQuantity(m.value, m.unit || '', measurementSystem).value * 100,
                                          ) / 100}{' '}
                                          {displayUnitFor(m.unit || '', measurementSystem)}
                                        </span>
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() => handleCreateAndLink(m.id)}
                                        disabled={linkingInProgress || !linkPickerBoqId}
                                        className="w-full flex items-center justify-center gap-1.5 px-2 py-1 rounded text-[10px] font-semibold bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 transition-colors"
                                      >
                                        {linkingInProgress && <Loader2 size={10} className="animate-spin" />}
                                        {t('takeoff.create_and_link', { defaultValue: 'Create position & link' })}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* Annotations section (Properties tab only) */}
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
                          aria-label={annoCollapsed
                            ? t('takeoff_viewer.expand_group', { defaultValue: 'Expand group' })
                            : t('takeoff_viewer.collapse_group', { defaultValue: 'Collapse group' })
                          }
                          title={annoCollapsed
                            ? t('takeoff_viewer.expand_group', { defaultValue: 'Expand group' })
                            : t('takeoff_viewer.collapse_group', { defaultValue: 'Collapse group' })
                          }
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
                                className="rounded-lg bg-surface-secondary px-2 py-1 group/item"
                              >
                                <div className="flex items-center gap-2 leading-tight">
                                  <TypeIcon
                                    size={12}
                                    className="shrink-0"
                                    style={{ color: m.color || '#EF4444' }}
                                  />
                                  <div className="flex-1 min-w-0 flex items-center gap-1.5">
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
                                        className="flex items-center gap-1 text-xs font-medium text-content-primary truncate hover:text-oe-blue transition-colors min-w-0 text-left"
                                        title={t('takeoff.add_label', { defaultValue: 'Add label...' })}
                                      >
                                        <span className="truncate">
                                          {m.type === 'text' ? (m.text || m.annotation) : m.annotation}
                                        </span>
                                        <Pencil size={10} className="shrink-0 opacity-0 group-hover/item:opacity-60 transition-opacity" />
                                      </button>
                                    )}
                                    <span className="text-2xs text-content-tertiary capitalize truncate shrink">{m.type}</span>
                                  </div>
                                  {/* Color picker — change annotation colour
                                      after creation. Native <input type="color">
                                      gives a free palette without a custom UI;
                                      uses the swatch as both the trigger and
                                      the live preview. */}
                                  <input
                                    type="color"
                                    value={m.color || '#EF4444'}
                                    onChange={(e) => {
                                      const newColor = e.target.value;
                                      setMeasurements((prev) => prev.map((x) => (x.id === m.id ? { ...x, color: newColor } : x)));
                                    }}
                                    className="opacity-60 group-hover/item:opacity-100 transition-opacity h-4 w-4 rounded-full border border-border cursor-pointer shrink-0 p-0"
                                    aria-label={t('takeoff_viewer.change_annotation_color', { defaultValue: 'Change annotation color' })}
                                    title={t('takeoff_viewer.change_annotation_color', { defaultValue: 'Change color' })}
                                  />
                                  <button
                                    onClick={() => deleteMeasurement(m.id)}
                                    className="opacity-50 group-hover/item:opacity-100 text-content-tertiary hover:text-semantic-error transition-all shrink-0"
                                    aria-label={t('takeoff_viewer.delete_annotation', { defaultValue: 'Delete annotation' })}
                                    title={`${t('takeoff_viewer.delete_annotation', { defaultValue: 'Delete annotation' })} (Del)`}
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
            )}

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
                  onClick={handleExportPdf}
                  disabled={isExportingPdf || !pdfDoc}
                  data-testid="takeoff-export-pdf-button"
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs font-semibold text-content-primary hover:bg-surface-tertiary transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isExportingPdf ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
                  {t('takeoff_viewer.export_pdf_annotated', {
                    defaultValue: 'Export PDF (with annotations)',
                  })}
                </button>
                <button
                  onClick={handleExportExcel}
                  disabled={isExportingXlsx}
                  data-testid="takeoff-export-excel-button"
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs font-semibold text-content-primary hover:bg-surface-tertiary transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isExportingXlsx ? <Loader2 size={14} className="animate-spin" /> : <FileSpreadsheet size={14} />}
                  {t('takeoff_viewer.export_excel_xlsx', { defaultValue: 'Export Excel (.xlsx)' })}
                </button>
                <button
                  onClick={handleExportCSV}
                  data-testid="takeoff-export-csv-button"
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs font-semibold text-content-primary hover:bg-surface-tertiary transition-colors flex items-center justify-center gap-1.5"
                >
                  <FileSpreadsheet size={14} />
                  {t('takeoff_viewer.export_csv', { defaultValue: 'Export CSV' })}
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

      {/* Calibration dialog (two-click with multi-unit picker) */}
      {showCalibrationDialog && (
        <CalibrationDialog
          pixelDistance={calibrationPixels}
          onConfirm={handleCalibrationConfirm}
          onCancel={handleCalibrationCancel}
        />
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
      {/* Measurement context menu (issue #302): right-click a measurement with
          the select tool to duplicate or delete it. The transparent backdrop
          dismisses it on any outside click / right-click / scroll. */}
      {contextMenu && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setContextMenu(null)}
          onContextMenu={(e) => { e.preventDefault(); setContextMenu(null); }}
          onWheel={() => setContextMenu(null)}
        >
          <div
            className="absolute min-w-[168px] rounded-lg border border-border bg-surface-elevated py-1 shadow-lg"
            style={{
              left: Math.min(contextMenu.x, window.innerWidth - 184),
              top: Math.min(contextMenu.y, window.innerHeight - 96),
            }}
            onClick={(e) => e.stopPropagation()}
            role="menu"
            data-testid="measurement-context-menu"
          >
            <button
              type="button"
              onClick={() => duplicateMeasurement(contextMenu.measurementId)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-content-primary hover:bg-surface-secondary transition-colors"
              role="menuitem"
              data-testid="context-duplicate"
            >
              <Copy size={13} />
              <span className="flex-1">{t('takeoff_viewer.duplicate_measurement', { defaultValue: 'Duplicate' })}</span>
              <span className="text-content-tertiary tabular-nums">Ctrl+D</span>
            </button>
            <button
              type="button"
              onClick={() => {
                const target = measurements.find((mm) => mm.id === contextMenu.measurementId);
                setContextMenu(null);
                if (target) openRfiForMeasurement(target);
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-start text-xs text-content-primary hover:bg-surface-secondary transition-colors"
              role="menuitem"
              data-testid="context-create-rfi"
            >
              <HelpCircle size={13} />
              <span className="flex-1">{t('takeoff_crosslink.create_rfi', { defaultValue: 'Create RFI' })}</span>
            </button>
            <button
              type="button"
              onClick={() => { deleteMeasurement(contextMenu.measurementId); setContextMenu(null); }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-semantic-error hover:bg-semantic-error-bg transition-colors"
              role="menuitem"
              data-testid="context-delete"
            >
              <Trash2 size={13} />
              <span className="flex-1">{t('takeoff_viewer.delete_measurement', { defaultValue: 'Delete measurement' })}</span>
              <span className="text-content-tertiary tabular-nums">Del</span>
            </button>
          </div>
        </div>
      )}
      {/* Create RFI from a measurement (cross-module link). Rendered fresh per
          open so the prefilled fields initialise from the chosen measurement. */}
      {rfiMeasurement && (
        <CreateRfiFromMeasurementDialog
          measurement={rfiMeasurement}
          projectId={activeProjectId || selectedProjectId || ''}
          documentId={documentId}
          documentName={fileName}
          onClose={() => setRfiMeasurement(null)}
          onCreated={() => setRfiMeasurement(null)}
        />
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
              <span className="text-sm text-content-secondary">
                {displayUnitFor(scale.unitLabel, measurementSystem)}
              </span>
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

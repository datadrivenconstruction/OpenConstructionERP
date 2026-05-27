/**
 * BIMViewer — Three.js-based 3D BIM viewer component.
 *
 * Renders BIM model elements as colored 3D boxes (by discipline), supports
 * click/hover selection, wireframe toggle, zoom-to-fit, and a properties panel.
 *
 * NOTE: Requires `three` and `@types/three` npm packages.
 */

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { MatchSuggestionsPanel } from '@/features/match';
import clsx from 'clsx';
import {
  Home,
  Grid3X3,
  Box,
  Eye,
  EyeOff,
  Maximize2,
  Loader2,
  AlertCircle,
  AlertTriangle,
  Link2,
  Link2Off,
  Plus,
  Square,
  CornerUpLeft,
  FileText,
  CheckSquare,
  Calendar,
  ClipboardCheck,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  LayoutGrid,
  Boxes,
  PanelTop,
  X,
  EyeOff as EyeOffIcon,
  Ruler,
  Tag,
  Settings,
  Camera,
  Sparkles,
  Scissors,
  Triangle,
  PencilRuler,
  RotateCcw,
  Move3d,
} from 'lucide-react';
import { fetchBIMElementProperties } from '@/features/bim/api';
import { SceneManager } from './SceneManager';
import { ElementManager } from './ElementManager';
import {
  applySmartView,
  revertSmartView,
  type SmartViewEvalResult,
} from './applySmartView';
import type { BIMElementData } from './ElementManager';
import { aggregateBIMQuantities, type AggResult } from './aggregation';
import { SelectionManager } from './SelectionManager';
import { MeasureManager } from './MeasureManager';
import { ClipManager } from './ClipManager';
// Slice: BIMcollab-style additive viewer tools (Section Box from selection,
// Walk mode, point-to-point Measure). Wired in additively next to the
// existing managers so they coexist without disrupting current flows.
import { SectionBox } from './SectionBox';
import { WalkMode } from './WalkMode';
import { MeasureTool } from './MeasureTool';
import { ViewerToolbar } from './ViewerToolbar';
import { deriveGeometry, deriveRelations } from './canonicalElementDetails';
import { BIMContextMenu } from './BIMContextMenu';
import type { BIMContextMenuState } from './BIMContextMenu';
import BIMViewCube from './BIMViewCube';
import {
  colorForRate,
  DEFAULT_5D_GRADIENT,
  NO_LINK_OPACITY,
} from './color5d';
import { TimelineScrubber } from './TimelineScrubber';
import { use4dTimeline } from './use4dTimeline';
import { resolveElementStatus } from './4dStatus';
import SimilarItemsPanel from '@/shared/ui/SimilarItemsPanel';
import { Slider } from '@/shared/ui/Slider';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';
import { useBIMGeometryCache } from '@/stores/useBIMGeometryCache';
import { useBIMMeasurementsStore } from '@/stores/useBIMMeasurementsStore';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type BIMViewMode = 'default' | '5d_cost' | '4d_schedule' | 'discipline';

export interface BIMViewerProps {
  /** BIM model ID to load. */
  modelId: string;
  /** Project ID. */
  projectId: string;
  /** Element IDs to highlight (controlled selection from parent). */
  selectedElementIds?: string[];
  /** Callback when an element is clicked. Receives the LAST clicked element
   *  id; for the full multi-selection set use `onSelectionChange`. */
  onElementSelect?: (elementId: string | null) => void;
  /** Callback firing on every selection change with the FULL set of selected
   *  element ids. Use this (not `onElementSelect`) to track Ctrl+click /
   *  Shift+click multi-selection in the parent so highlights stay correct
   *  across renders.
   *
   *  The second arg carries the resolved `BIMElementData` rows for the
   *  selection (including viewer-side stubs that have a `mesh_ref` but no
   *  DB row yet). Callers that need to persist the selection — e.g. "save
   *  as group" — must use these rows so stub ids get resolved to real
   *  BIMElement UUIDs instead of being stored verbatim. */
  onSelectionChange?: (
    elementIds: string[],
    elements: BIMElementData[],
  ) => void;
  /** Callback when an element is hovered. */
  onElementHover?: (elementId: string | null) => void;
  /** View mode coloring scheme. */
  viewMode?: BIMViewMode;
  /** Show measurement tools. */
  showMeasureTools?: boolean;
  /** Additional CSS class. */
  className?: string;
  /** Elements to render (loaded externally by the parent). */
  elements?: BIMElementData[];
  /** Loading state (from parent). */
  isLoading?: boolean;
  /** Error message (from parent). */
  error?: string | null;
  /** URL to DAE/COLLADA geometry file (served from backend). */
  geometryUrl?: string | null;
  /**
   * Optional visibility predicate. When set, the viewer calls
   * ElementManager.applyFilter(predicate) so only matching elements stay
   * visible. Fast — no re-render, just mesh.visible toggles.
   */
  filterPredicate?: ((el: BIMElementData) => boolean) | null;
  /**
   * Color-by mode.  Two families of modes:
   *
   * Field-based (golden-angle palette over a string key):
   *   - 'default'    — restore original COLLADA materials
   *   - 'discipline' — color by element.discipline
   *   - 'storey'     — color by element.storey
   *   - 'type'       — color by element.element_type
   *
   * Compliance-based (fixed red/amber/green palette, drives a real
   * compliance dashboard out of the 3D viewer):
   *   - 'validation'        — red=error, amber=warning, green=pass, grey=unchecked
   *   - 'boq_coverage'      — green=linked to ≥1 BOQ position, red=unlinked
   *   - 'document_coverage' — green=has ≥1 linked drawing/RFI, red=none
   */
  colorByMode?:
    | 'default'
    | 'discipline'
    | 'storey'
    | 'type'
    | 'validation'
    | 'boq_coverage'
    | 'document_coverage'
    | '5d_cost'
    | '4d_schedule';
  /** Show bounding box placeholders alongside geometry. Off by default. */
  showBoundingBoxes?: boolean;
  /** Element IDs to isolate (hide everything else). Empty = show all. */
  isolatedIds?: string[] | null;
  /** Fired when the user changes isolation from inside the viewer
   *  (keyboard `I`, context menu, "Isolate selection" button, "Show
   *  all" button).  Pass through to the parent so the filter panel
   *  banner, summary panels and any other UI bound to `isolatedIds`
   *  stay in sync — without this callback, internal isolation would
   *  invisibly diverge from the prop. */
  onIsolationChange?: (ids: string[] | null) => void;
  /** Element IDs to highlight in orange WITHOUT hiding the rest of the
   *  model — used to show which BIM elements are linked to the currently
   *  selected BOQ position.  Pass null/empty to clear. */
  highlightedIds?: string[] | null;
  /**
   * Called once DAE geometry finishes loading, with the ratio of elements
   * whose mesh was successfully matched by stable_id/name (0..1). The
   * parent uses this to warn users when per-element filters cannot affect
   * the viewport (e.g. DDC RVT exports with numeric node names).
   */
  onGeometryLoaded?: (meshMatchRatio: number) => void;
  /** User clicked "Add to BOQ" — parent opens the AddToBOQModal pre-filled
   *  with the selected element(s).  When multiple elements are selected the
   *  array contains all of them so the modal can do a bulk link. */
  onAddToBOQ?: (elements: BIMElementData[]) => void;
  /** User clicked "Unlink" on a specific link in the properties panel. */
  onUnlinkBOQ?: (linkId: string) => void;
  /** User clicked a linked document in the properties panel — parent
   *  navigates to /documents/{id} or opens an embedded preview. */
  onOpenDocument?: (documentId: string) => void;
  /** User clicked a linked task in the properties panel. */
  onOpenTask?: (taskId: string) => void;
  /** User clicked a linked schedule activity in the properties panel. */
  onOpenActivity?: (activityId: string) => void;
  /** User clicked a linked requirement in the properties panel. */
  onOpenRequirement?: (requirementId: string) => void;
  /** User clicked "+ New" in the Linked Tasks section — parent opens
   *  CreateTaskFromBIMModal pre-filled with this element. */
  onCreateTask?: (element: BIMElementData) => void;
  /** User clicked "+ Link" in the Linked Documents section — parent opens
   *  the LinkDocumentToBIMModal picker. */
  onLinkDocument?: (element: BIMElementData) => void;
  /** User clicked "+ Link" in the Schedule Activities section. */
  onLinkActivity?: (element: BIMElementData) => void;
  /** User clicked "+ Link" in the Linked Requirements section — parent
   *  opens the LinkRequirementToBIMModal picker. */
  onLinkRequirement?: (element: BIMElementData) => void;
  /** User clicked one of the smart-filter pills in the health stats
   *  banner. The parent applies the matching predicate via setFilterPredicate
   *  so the 3D viewport narrows to "errors only" / "unlinked only" / etc. */
  onSmartFilter?: (
    filterId: 'errors' | 'warnings' | 'unlinked_boq' | 'has_tasks' | 'has_docs',
  ) => void;
  /** When true, the parent's filter sidebar is open — the viewer shifts
   *  its top-left toolbar to the right so it doesn't sit behind the panel. */
  leftPanelOpen?: boolean;
  /** Width (in px) of the left filter panel — used to offset the toolbar
   *  when `leftPanelOpen` is true. Defaults to 320 to match BIMFilterPanel. */
  leftPanelWidth?: number;
  /** Model display name — used in the screenshot filename so users who
   *  screenshot several models at once can tell them apart. Optional; the
   *  filename falls back to "bim-screenshot-<timestamp>.png" when unset. */
  modelName?: string;
  /** Model.metadata bag from the backend. The viewer reads
   *  ``geometry_type === "placeholder"`` here to surface the placeholder
   *  banner even before any element-level ``is_placeholder`` flag arrives
   *  (paginated element fetch can lag behind the model load). */
  modelMetadata?: Record<string, unknown> | null;
  /**
   * Model-version diff overlay. When set, every element is recoloured by
   * its change type (added = green, deleted = red, modified = amber,
   * unchanged = faded grey).  Read-only consumption of the backend diff —
   * keyed by `stable_id` (deleted elements don't exist in this model so
   * they can't be coloured, only counted/listed in the diff panel).
   * Pass null to clear the overlay. The `elementsByStableId` lookup is
   * built by the viewer itself.
   */
  diffChangeByStableId?: Map<string, 'added' | 'deleted' | 'modified'> | null;
  /**
   * Clash-review deep-link support. When the user opens a clash result's
   * "3D" link the parent passes the two interfering element ids here so the
   * viewer colours them in a distinct clash red (≠ the orange BOQ-link
   * highlight) ON TOP of the isolation set in `isolatedIds`. Pass null when
   * not reviewing a clash.
   */
  clashHighlightIds?: string[] | null;
  /**
   * World-space point to frame the camera on. The clash-review deep-link
   * passes the clash centroid (`cx/cy/cz`) — a reliable focus target even
   * for showcase IFC/RVT models whose GLB nodes are numeric Revit ids that
   * never match the DB element UUIDs (so per-element mesh resolution is only
   * approximate and `zoomToSelection` on the matched meshes can frame the
   * wrong spot). Re-applied after geometry finishes loading so the deep-link
   * survives the load race. Pass null for normal viewing.
   */
  focusPoint?: { x: number; y: number; z: number } | null;
  /**
   * Smart View evaluator result — keyed by element ``stable_id`` (the
   * IFC GUID / Revit UniqueId). When set, the viewer paints each mesh
   * with the resolved per-element ``{visible, color, opacity}`` state.
   * Pass ``null`` (or omit) for normal rendering. Re-paint is additive
   * and fully reversible: the helper caches each mesh's original
   * material so toggling the prop back to ``null`` restores the model
   * exactly.  See {@link applySmartView} / {@link revertSmartView}. */
  smartViewEvalResult?: SmartViewEvalResult | null;
}

/* ── Properties Table ──────────────────────────────────────────────────── */

/** Recognise values that should be hidden as "empty". Excel exports from
 *  DDC often emit the literal strings "None" or "0" for unset attributes;
 *  showing them in the panel is noise. */
function isEmptyValue(v: unknown): boolean {
  if (v == null) return true;
  if (typeof v === 'number' && v === 0) return true;
  if (typeof v === 'string') {
    const s = v.trim();
    if (s === '' || s === '0' || s === 'None' || s === 'null' || s === 'N/A' || s === 'n/a') return true;
  }
  return false;
}

/** Parse German booleans (`WAHR`/`FALSCH`) and their English equivalents. */
function parseBool(v: unknown): boolean | null {
  if (typeof v === 'boolean') return v;
  if (typeof v !== 'string') return null;
  const s = v.trim().toLowerCase();
  if (s === 'wahr' || s === 'true' || s === 'yes' || s === 'y') return true;
  if (s === 'falsch' || s === 'false' || s === 'no' || s === 'n') return false;
  return null;
}

/** Parse a DDC-style property bag encoded as `Key=Value; Key=Value` into
 *  a {key: value} dict. Returns null if the string doesn't look like one
 *  (needs at least two `;`-separated `Key=Value` pairs). */
function parseMaterialString(v: unknown): Record<string, string> | null {
  if (typeof v !== 'string') return null;
  if (!v.includes('=') || !v.includes(';')) return null;
  const parts = v.split(';').map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return null;
  const out: Record<string, string> = {};
  for (const part of parts) {
    const eq = part.indexOf('=');
    if (eq <= 0) return null; // not well-formed
    const k = part.slice(0, eq).trim();
    const raw = part.slice(eq + 1).trim();
    const val = raw.replace(/^"(.*)"$/, '$1');
    if (!k || isEmptyValue(val)) continue;
    out[k] = val;
  }
  return Object.keys(out).length > 0 ? out : null;
}

/** Render `key=value; key=value` as a compact sub-table. */
function SubTable({ data }: { data: Record<string, string> }) {
  return (
    <div className="mt-1 rounded-md border border-border-light/60 bg-surface-secondary/40 divide-y divide-border-light/40">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex justify-between items-start gap-2 py-1 px-2">
          <span className="text-[10px] text-content-tertiary shrink-0 max-w-[45%] truncate" title={k}>
            {k}
          </span>
          <span className="text-[10px] text-content-primary text-end break-words min-w-0" title={v}>
            {v}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Render a boolean as a coloured tag. */
function BoolTag({ value }: { value: boolean }) {
  return value ? (
    <span className="inline-flex items-center rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 px-2 py-[1px] text-[10px] font-semibold">
      true
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-300 px-2 py-[1px] text-[10px] font-semibold">
      false
    </span>
  );
}

/** Normalise a DDC Parquet column name for display.
 *  `[Type] Category` → `Type: Category`; `category` → `Category`. */
function prettyKey(raw: string): string {
  let k = raw.trim();
  const typePrefix = k.match(/^\[Type\]\s*(.+)$/i);
  if (typePrefix) {
    k = `Type: ${typePrefix[1]!}`;
  }
  // Title-case single-word lowercase keys only; leave already-cased keys alone.
  if (/^[a-z][a-z0-9_ ]*$/.test(k)) {
    k = k.replace(/[_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return k;
}

/** Sort keys so the most-useful identity fields surface at the top. */
const KEY_PRIORITY: Record<string, number> = {
  id: -100,
  type_name: -90,
  'type name': -90,
  name: -85,
  category: -80,
  'family name': -75,
  family: -75,
  type: -70,
  uniqueid: -65,
  ifcguid: -60,
  workset: -55,
  'design option': -50,
};

function sortedEntries(props: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(props)
    .filter(([, v]) => !isEmptyValue(v))
    .sort(([a], [b]) => {
      const pa = KEY_PRIORITY[a.toLowerCase()] ?? 0;
      const pb = KEY_PRIORITY[b.toLowerCase()] ?? 0;
      if (pa !== pb) return pa - pb;
      return a.localeCompare(b);
    });
}

function PropertiesTable({ properties }: { properties: Record<string, unknown> }) {
  const entries = sortedEntries(properties);
  if (entries.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {entries.map(([key, value]) => {
        const label = prettyKey(key);
        const bool = parseBool(value);
        const mat = bool === null ? parseMaterialString(value) : null;
        return (
          <div
            key={key}
            className="flex flex-col gap-0.5 py-1.5 px-2 rounded-md border bg-white/60 border-black/5 dark:bg-white/5 dark:border-white/10 hover:bg-white/80 dark:hover:bg-white/10 transition-colors group"
          >
            <div className="flex justify-between items-start gap-3">
              <span
                className="text-[11px] text-content-tertiary shrink-0 max-w-[45%] truncate"
                title={key}
              >
                {label}
              </span>
              {bool !== null ? (
                <BoolTag value={bool} />
              ) : mat ? (
                <span className="text-[10px] text-content-tertiary italic">
                  {Object.keys(mat).length} fields
                </span>
              ) : (
                <span
                  className="text-[11px] text-content-primary font-medium text-end break-words min-w-0"
                  title={String(value)}
                >
                  {String(value)}
                </span>
              )}
            </div>
            {mat && <SubTable data={mat} />}
          </div>
        );
      })}
    </div>
  );
}

function QuantitiesTable({ quantities }: { quantities: Record<string, number> }) {
  const entries = Object.entries(quantities).filter(([, v]) => v != null);
  if (entries.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="flex justify-between items-center gap-3 py-1.5 px-2 rounded-md border bg-white/60 border-black/5 dark:bg-white/5 dark:border-white/10 hover:bg-white/80 dark:hover:bg-white/10 transition-colors"
        >
          <span className="text-[11px] text-content-tertiary truncate max-w-[50%]" title={key}>
            {key}
          </span>
          <span className="text-[11px] text-content-primary font-semibold tabular-nums">
            {typeof value === 'number'
              ? value.toLocaleString(undefined, { maximumFractionDigits: 3 })
              : String(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── BIM Viewer Component ──────────────────────────────────────────────── */

export function BIMViewer({
  modelId,
  projectId,
  selectedElementIds,
  onElementSelect,
  onSelectionChange,
  onElementHover,
  viewMode: _viewMode = 'default',
  showMeasureTools: _showMeasureTools = false,
  className,
  elements,
  isLoading = false,
  error = null,
  geometryUrl = null,
  showBoundingBoxes = false,
  filterPredicate = null,
  colorByMode = 'default',
  isolatedIds = null,
  onIsolationChange,
  highlightedIds = null,
  onGeometryLoaded,
  onAddToBOQ,
  onUnlinkBOQ,
  onOpenDocument,
  onOpenTask,
  onOpenActivity,
  onOpenRequirement,
  onCreateTask,
  onLinkDocument,
  onLinkActivity,
  onLinkRequirement,
  onSmartFilter,
  leftPanelOpen = false,
  leftPanelWidth = 320,
  modelName,
  modelMetadata = null,
  diffChangeByStableId = null,
  clashHighlightIds = null,
  focusPoint = null,
  smartViewEvalResult = null,
}: BIMViewerProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SceneManager | null>(null);
  const elementMgrRef = useRef<ElementManager | null>(null);
  const selectionMgrRef = useRef<SelectionManager | null>(null);
  const measureMgrRef = useRef<MeasureManager | null>(null);
  const clipMgrRef = useRef<ClipManager | null>(null);
  // BIMcollab-style additive helpers (Section Box / Walk / Measure).
  // Initialised inside the scene-setup useEffect below and disposed in its
  // cleanup. Exposed via state so the ViewerToolbar overlay can render
  // once they're ready.
  const sectionBoxRef = useRef<SectionBox | null>(null);
  const walkModeRef = useRef<WalkMode | null>(null);
  const measureToolRef = useRef<MeasureTool | null>(null);
  const [viewerToolsReady, setViewerToolsReady] = useState(false);
  /** True while WalkMode currently owns the pointer lock — drives the
   *  on-screen "Mouse: look · WASD: move" hint overlay. */
  const [walkLocked, setWalkLocked] = useState(false);
  const categoryOpacity = useBIMViewerStore((s) => s.categoryOpacity);
  const hiddenCategories = useBIMViewerStore((s) => s.hiddenCategories);
  const measureActive = useBIMViewerStore((s) => s.measureActive);
  const setMeasureActive = useBIMViewerStore((s) => s.setMeasureActive);
  const measureKind = useBIMViewerStore((s) => s.measureKind);
  const setMeasureKind = useBIMViewerStore((s) => s.setMeasureKind);
  const measureSnap = useBIMViewerStore((s) => s.measureSnap);
  const setMeasureSnap = useBIMViewerStore((s) => s.setMeasureSnap);
  const clipMode = useBIMViewerStore((s) => s.clipMode);
  const setClipMode = useBIMViewerStore((s) => s.setClipMode);
  const clipPanelOpen = useBIMViewerStore((s) => s.clipPanelOpen);
  const setClipPanelOpen = useBIMViewerStore((s) => s.setClipPanelOpen);
  const ghostActive = useBIMViewerStore((s) => s.ghostActive);
  const setGhostActive = useBIMViewerStore((s) => s.setGhostActive);
  const summaryPanelOpen = useBIMViewerStore((s) => s.summaryPanelOpen);
  const setSummaryPanelOpen = useBIMViewerStore((s) => s.setSummaryPanelOpen);
  const qualityMode = useBIMViewerStore((s) => s.qualityMode);
  const [measureCount, setMeasureCount] = useState(0);
  /** Local mirror of the live section-box / plane state for the popover. */
  const [clipBox, setClipBox] = useState({
    minX: 0,
    maxX: 1,
    minY: 0,
    maxY: 1,
    minZ: 0,
    maxZ: 1,
  });
  const [clipPlane, setClipPlane] = useState<{
    axis: 'x' | 'y' | 'z';
    offset: number;
    flipped: boolean;
  }>({ axis: 'y', offset: 0.5, flipped: false });
  // Latest onIsolationChange callback — needed because the
  // SelectionManager init effect runs only on mount and would
  // otherwise capture a stale prop reference.
  const onIsolationChangeRef = useRef(onIsolationChange);
  useEffect(() => {
    onIsolationChangeRef.current = onIsolationChange;
  }, [onIsolationChange]);

  const [wireframe, setWireframe] = useState(false);
  const [gridVisible, setGridVisible] = useState(false);
  const [boxesVisible, setBoxesVisible] = useState(true);
  const [selectedElement, setSelectedElement] = useState<BIMElementData | null>(null);
  const [elementCount, setElementCount] = useState(0);
  /** Hover tooltip state — tracks the hovered element and mouse position
   *  so a floating label appears next to the cursor in the 3D viewport. */
  const [hoveredElement, setHoveredElement] = useState<BIMElementData | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  /** Keyboard shortcut overlay toggle (press ? to show). */
  const [showShortcuts, setShowShortcuts] = useState(false);
  /** Properties panel active tab. */
  const [propsTab, setPropsTab] = useState<'key' | 'all' | 'links' | 'validation' | 'match'>('key');
  /** Parquet/DuckDB "all properties" expansion state. */
  const [parquetProps, setParquetProps] = useState<Record<string, unknown> | null>(null);
  const [parquetLoading, setParquetLoading] = useState(false);
  const [parquetExpanded, setParquetExpanded] = useState(false);
  /** DAE/COLLADA download progress, in [0, 1].  ``null`` when no
   *  geometry load is in flight; a fraction while bytes are streaming
   *  in; ``1`` momentarily before the overlay hides itself.  Drives
   *  the progress overlay rendered below the canvas while the geometry
   *  blob downloads — a 100MB model can take 30+ seconds and the
   *  previous spinner gave the user no signal anything was happening. */
  const [geometryProgress, setGeometryProgress] = useState<number | null>(null);
  /** User-visible error when the geometry blob fails to load — bad
   *  GLB/DAE bytes, 401 from a stale token, 404 from a freshly-deleted
   *  redeploy, etc. Issue #113: previously this case was logged to the
   *  console only and the user saw an empty canvas with no signal at
   *  all. Now we surface a banner with the message + a Retry button.
   *  Cleared whenever a fresh load is kicked off. */
  const [geometryError, setGeometryError] = useState<string | null>(null);
  /** Top-3 frames of the captured ``err.stack`` for the most recent
   *  geometry load failure. Surfaced in a collapsible block under the
   *  banner so a user can paste the stack on a bug report without
   *  opening DevTools. ``null`` when the error had no stack (rare —
   *  some loaders throw plain strings) or no error is active. */
  const [geometryErrorStack, setGeometryErrorStack] = useState<string | null>(null);
  /** Structured diagnostic dict surfaced by the backend when it serves
   *  a 422 from the geometry endpoint (magic-byte / signature check
   *  failed). Contains only non-PII bytes: first 8 hex/ASCII, file size,
   *  parser reason, expected signature, first XML tag (DAE), and a
   *  remediation hint. Rendered as a labelled table under the banner so
   *  a user can diagnose without DevTools. ``null`` when the failure had
   *  no structured payload (network errors, 404s, JS-side parse). */
  const [geometryErrorDiagnostic, setGeometryErrorDiagnostic] = useState<Record<
    string,
    unknown
  > | null>(null);
  /** HTTP status code of the latest geometry failure (401 / 403 / 404 /
   *  422 / 5xx / null for network errors). Drives the headline copy +
   *  remediation hint shown in the banner — "Refresh to renew session"
   *  reads completely different from "The 3D file is corrupt" yet they
   *  both surface through the same banner. */
  const [geometryErrorStatus, setGeometryErrorStatus] = useState<number | null>(
    null,
  );
  /** Correlation ID emitted by the backend on every geometry response
   *  (the ``X-Request-Id`` header). Shown verbatim in the banner so the
   *  user can quote it to support — and is the SOLE field that lets
   *  support locate the failure in server logs. */
  const [geometryErrorRequestId, setGeometryErrorRequestId] = useState<
    string | null
  >(null);
  /** Bumped to force the geometry-load effect to re-run when the user
   *  clicks Retry. Doesn't change ``geometryUrl`` so we can't simply
   *  re-set state to the same value — a discriminating dep is needed. */
  const [geometryRetryNonce, setGeometryRetryNonce] = useState(0);
  /** Bumped once geometry has finished loading + parsing AND the mesh⇄
   *  element map is populated. The isolate / highlight / clash-focus effects
   *  depend on this so a deep-link (`?isolate=`, clash "3D" link) that
   *  arrives BEFORE geometry is ready is re-applied after the load instead
   *  of being silently dropped (the meshMap was empty → isolate() hid
   *  everything → zoomToSelection([]) early-returned → blank viewer). */
  const [geometryReadyNonce, setGeometryReadyNonce] = useState(0);
  // Track the "hide-overlay" timeout so the cleanup effect can clear it
  // when the component unmounts mid-load (avoids setState-on-unmounted warns).
  const geometryProgressTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** "Placeholder geometry" banner dismissal. Persisted per-model in
   *  localStorage so a user who dismisses it for model A still sees it
   *  on model B (separate decision per upload). The banner appears when
   *  ``model.metadata.geometry_type === "placeholder"`` (set by the text-IFC
   *  fallback at ``ifc_processor.py``) OR when ANY loaded element carries
   *  ``properties.is_placeholder === true``. The metadata-level check
   *  fires on first paint even before paginated element fetch arrives. */
  const placeholderDismissKey = modelId
    ? `oe_bim_placeholder_banner_dismissed:${modelId}`
    : null;
  const [placeholderBannerDismissed, setPlaceholderBannerDismissedState] = useState<boolean>(() => {
    if (!placeholderDismissKey) return false;
    try {
      return localStorage.getItem(placeholderDismissKey) === '1';
    } catch {
      return false;
    }
  });
  // Re-hydrate dismissal when modelId changes — user might switch models
  // and the previous one was dismissed but the new one wasn't.
  useEffect(() => {
    if (!placeholderDismissKey) {
      setPlaceholderBannerDismissedState(false);
      return;
    }
    try {
      setPlaceholderBannerDismissedState(
        localStorage.getItem(placeholderDismissKey) === '1',
      );
    } catch {
      setPlaceholderBannerDismissedState(false);
    }
  }, [placeholderDismissKey]);
  const setPlaceholderBannerDismissed = useCallback(
    (val: boolean) => {
      setPlaceholderBannerDismissedState(val);
      if (!placeholderDismissKey) return;
      try {
        if (val) localStorage.setItem(placeholderDismissKey, '1');
        else localStorage.removeItem(placeholderDismissKey);
      } catch {
        /* storage unavailable */
      }
    },
    [placeholderDismissKey],
  );
  const isPlaceholderGeometry = useMemo(() => {
    // Model-level signal lights the banner instantly on first paint —
    // metadata.geometry_type is set by the text-IFC fallback path.
    const geomType = modelMetadata?.['geometry_type'];
    if (typeof geomType === 'string' && geomType === 'placeholder') return true;
    if (!elements || elements.length === 0) return false;
    // Element-level fallback — covers older uploads where the metadata
    // bag wasn't populated yet but element flags were.
    for (const el of elements) {
      if (el.is_placeholder === true) return true;
      const flag = (el.properties as Record<string, unknown> | undefined)?.is_placeholder;
      if (flag === true || flag === 'true' || flag === 1) return true;
    }
    return false;
  }, [elements, modelMetadata]);

  /** Context menu state -- null when closed. */
  const [contextMenu, setContextMenu] = useState<BIMContextMenuState | null>(null);
  /** Set of element IDs that the user has manually hidden via the context
   *  menu.  Tracked as React state so the "N hidden" badge updates. */
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  /** Number of currently selected elements -- drives the selection toolbar. */
  const [selectionCount, setSelectionCount] = useState(0);
  /** Summary of selected elements for the toolbar label. */
  const [selectionSummary, setSelectionSummary] = useState('');
  /** Whether the viewer is in isolation mode (double-click). */
  const [isIsolated, setIsIsolated] = useState(false);
  /** W6.6 Stream B — track the live SceneManager in React state so the
   *  Site Compass (`<BIMViewCube>`) can mount after the scene initialises.
   *  Using a state mirror (rather than the ref directly) means the cube
   *  re-renders the moment the scene becomes available without polling. */
  const [sceneManagerReady, setSceneManagerReady] = useState<SceneManager | null>(
    null,
  );
  /** W6.6 Stream C — hidden element count driven by ElementManager's
   *  ``onHiddenCountChange`` subscription. Powers the floating "{n} hidden"
   *  badge in the upper-left corner and the "Show all" affordance. */
  const [hiddenCount, setHiddenCount] = useState(0);

  /** 4D timeline state — fetches schedule + activities for the project
   *  and manages the playable cursor.  Enabled only when the user
   *  activates 4D mode so we don't hit the schedule API on every page
   *  visit.  When the project has no schedule, `isAvailable` is false
   *  and the scrubber renders nothing. */
  const fourD = use4dTimeline(projectId, colorByMode === '4d_schedule');

  /** 5D cost rate stats — min / max unit_rate across all linked BOQ
   *  positions on the loaded elements.  Drives the legend strip in the
   *  bottom-right corner when `colorByMode === '5d_cost'`. */
  const rateStats = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    let linkedCount = 0;
    for (const el of elements ?? []) {
      let best: number | null = null;
      for (const link of el.boq_links ?? []) {
        const r = link.boq_position_unit_rate;
        if (r == null || !Number.isFinite(r) || r <= 0) continue;
        if (best === null || r > best) best = r;
      }
      if (best !== null) {
        linkedCount++;
        if (best < min) min = best;
        if (best > max) max = best;
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      return { min: 0, max: 0, linkedCount: 0 };
    }
    return { min, max, linkedCount };
  }, [elements]);

  /** Health-stat rollup over the loaded elements.  Drives the banner at
   *  the top of the viewport: total / linked-to-BOQ / errors / warnings /
   *  has-tasks / has-documents.  Pure derived state so it updates the
   *  moment the parent re-fetches after any link/unlink/validation run. */
  const healthStats = useMemo(() => {
    const els = elements ?? [];
    let linkedToBoq = 0;
    let errors = 0;
    let warnings = 0;
    let hasTasks = 0;
    let hasDocs = 0;
    let hasActivities = 0;
    let validated = 0;
    for (const el of els) {
      if ((el.boq_links?.length ?? 0) > 0) linkedToBoq++;
      if (el.validation_status && el.validation_status !== 'unchecked') validated++;
      if (el.validation_status === 'error') errors++;
      else if (el.validation_status === 'warning') warnings++;
      if ((el.linked_tasks?.length ?? 0) > 0) hasTasks++;
      if ((el.linked_documents?.length ?? 0) > 0) hasDocs++;
      if ((el.linked_activities?.length ?? 0) > 0) hasActivities++;
    }
    return {
      total: els.length,
      linkedToBoq,
      errors,
      warnings,
      hasTasks,
      hasDocs,
      hasActivities,
      validated,
    };
  }, [elements]);

  // Initialize Three.js scene on mount
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scene = new SceneManager(canvas);
    sceneRef.current = scene;
    // W6.6 Stream B — surface the scene manager to React state so the
    // Site Compass (BIMViewCube) and any sibling consumers can mount after
    // the scene initialises.
    setSceneManagerReady(scene);

    const elementMgr = new ElementManager(scene);
    elementMgrRef.current = elementMgr;
    // W6.6 Stream C — subscribe to hidden-count changes so the floating
    // "{n} hidden · Show all" badge stays in sync with hide / isolate /
    // show-all actions wherever they originate. The subscription is torn
    // down with the rest of the scene below.
    const unsubscribeHiddenCount = elementMgr.onHiddenCountChange((count) => {
      setHiddenCount(count);
    });

    const selectionMgr = new SelectionManager(scene, elementMgr, {
      onElementSelect: (id) => {
        if (id) {
          const data = elementMgr.getElementData(id);
          setSelectedElement(data ?? null);
        } else {
          setSelectedElement(null);
        }
        // Reset parquet expansion and tab when element changes
        setParquetProps(null);
        setParquetExpanded(false);
        setPropsTab('key');
        onElementSelectRef.current?.(id);
      },
      onElementHover: (id) => {
        if (id) {
          const data = elementMgr.getElementData(id);
          setHoveredElement(data ?? null);
        } else {
          setHoveredElement(null);
          setTooltipPos(null);
        }
        onElementHoverRef.current?.(id);
      },
      onSelectionChange: (ids) => {
        setSelectionCount(ids.length);
        // Build summary like "2 Walls, 1 Door"
        if (ids.length > 1) {
          const counts = new Map<string, number>();
          for (const id of ids) {
            const data = elementMgr.getElementData(id);
            const cat = data?.element_type || 'Unknown';
            counts.set(cat, (counts.get(cat) ?? 0) + 1);
          }
          const parts = [...counts.entries()]
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)
            .map(([cat, n]) => `${n} ${cat}`);
          setSelectionSummary(parts.join(', '));
        } else {
          setSelectionSummary('');
        }
        // Update properties panel — show first selected element
        if (ids.length > 0) {
          const first = elementMgr.getElementData(ids[0]!);
          setSelectedElement(first ?? null);
        } else {
          setSelectedElement(null);
        }
        // Flag so the parent's selectedElementIds change doesn't reset our multi-select
        internalSelectionRef.current = true;
        // Notify parent with both signals: the LAST clicked id (back-compat
        // for callers that only need single-selection) and the FULL set
        // (so the parent can echo it back via selectedElementIds and keep
        // every Ctrl+click highlighted across renders).
        onElementSelectRef.current?.(ids.length > 0 ? ids[ids.length - 1]! : null);
        // Resolve full rows (including viewer stubs) so the parent can
        // persist the selection without losing stub mesh_refs.
        const selectedData: BIMElementData[] = [];
        for (const id of ids) {
          const d = elementMgr.getElementData(id);
          if (d) selectedData.push(d);
        }
        onSelectionChangeRef.current?.(ids, selectedData);
        // Close context menu on selection change
        setContextMenu(null);
      },
      onContextMenu: (event, _elementId) => {
        const selected = selectionMgr.getSelectedElements();
        const directElement = _elementId
          ? elementMgr.getElementData(_elementId) ?? null
          : null;
        if (selected.length > 0 || directElement) {
          setContextMenu({
            x: event.clientX,
            y: event.clientY,
            element: directElement,
            selectedElements: selected.length > 0 ? selected : (directElement ? [directElement] : []),
          });
        }
      },
      onDoubleClick: (elementId) => {
        if (elementId) {
          // Double-click element -> isolate it (plus current selection)
          const ids = selectionMgr.getSelectedIds();
          const toIsolate = ids.includes(elementId) ? ids : [elementId];
          elementMgr.isolate(toIsolate);
          setIsIsolated(true);
          onIsolationChangeRef.current?.(toIsolate);
          // Zoom to the isolated elements
          const meshes = toIsolate
            .map((id) => elementMgr.getMesh(id))
            .filter((m): m is NonNullable<typeof m> => m != null);
          if (meshes.length > 0) {
            scene.zoomToSelection(meshes);
          }
        } else {
          // Double-click empty space -> exit isolation, show all
          elementMgr.showAll();
          setIsIsolated(false);
          onIsolationChangeRef.current?.(null);
          setHiddenIds(new Set());
          scene.zoomToFit();
        }
      },
    });
    selectionMgrRef.current = selectionMgr;

    const measureMgr = new MeasureManager(scene, elementMgr, {
      onMeasurementsChanged: (count) => setMeasureCount(count),
      onMeasurementAdded: (m) => {
        // Mirror the new measurement into the Tools-panel store so the user
        // can manage it (rename / hide / delete) after they leave measure
        // mode. RFC 19 §UX-10. Carries kind/value/perimeter so the list can
        // show m / m² / ° correctly (not just metres).
        useBIMMeasurementsStore.getState().add({
          id: m.id,
          kind: m.kind,
          distance: m.distance,
          value: m.value,
          perimeter: m.perimeter,
        });
      },
      onMiss: () => {
        useToastStore.getState().addToast({
          type: 'info',
          title: t('bim.measure_miss_title', { defaultValue: 'Click missed the model' }),
          message: t('bim.measure_miss_msg', {
            defaultValue: 'Click directly on an element to place a measurement point.',
          }),
        });
      },
    });
    measureMgrRef.current = measureMgr;

    const clipMgr = new ClipManager(scene);
    // W6.6 Stream A "Section Stamp" — make sure the hatched cap renders on
    // every section cut by default. The flag is on by default in the
    // manager itself; we re-affirm here so this call site is the single
    // source of truth in case the default ever flips.
    clipMgr.setCapEnabled(true);
    clipMgrRef.current = clipMgr;

    // ── Additive viewer tools (Slice: Section Box / Walk / Measure) ──
    // These are independent of the existing ClipManager/MeasureManager —
    // they're surfaced through the floating `ViewerToolbar` overlay and
    // intended as BIMcollab-style affordances. Mutual exclusion (only one
    // active at a time) is enforced by the toolbar; the helpers themselves
    // only operate on the shared Three.js scene/camera/renderer.
    const sectionBox = new SectionBox({
      scene: scene.scene,
      camera: scene.camera,
      renderer: scene.renderer,
    });
    const walkModeHelper = new WalkMode({
      camera: scene.camera,
      renderer: scene.renderer,
      domElement: canvas,
      orbitControls: scene.controls,
    });
    const measureToolHelper = new MeasureTool({
      scene: scene.scene,
      camera: scene.camera,
      renderer: scene.renderer,
      domElement: canvas,
    });
    sectionBoxRef.current = sectionBox;
    walkModeRef.current = walkModeHelper;
    measureToolRef.current = measureToolHelper;
    // Drive the on-screen Walk hint from the actual pointer-lock state —
    // the user sees the overlay only while the cursor is captured.
    const unsubWalkLock = walkModeHelper.onLockChange((locked) => {
      setWalkLocked(locked);
    });
    setViewerToolsReady(true);

    // Track mouse position for hover tooltip
    const handleMouseMoveForTooltip = (e: MouseEvent) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      setTooltipPos({
        x: e.clientX - rect.left + 14,
        y: e.clientY - rect.top + 14,
      });
    };
    canvas.addEventListener('mousemove', handleMouseMoveForTooltip);

    return () => {
      canvas.removeEventListener('mousemove', handleMouseMoveForTooltip);
      unsubscribeHiddenCount();
      unsubWalkLock();
      clipMgr.dispose();
      measureMgr.dispose();
      // Dispose the additive viewer-tools slice helpers BEFORE the scene
      // itself so they can detach their overlays from a still-live scene.
      sectionBox.dispose();
      walkModeHelper.dispose();
      measureToolHelper.dispose();
      selectionMgr.dispose();
      elementMgr.dispose();
      scene.dispose();
      sceneRef.current = null;
      elementMgrRef.current = null;
      selectionMgrRef.current = null;
      measureMgrRef.current = null;
      clipMgrRef.current = null;
      sectionBoxRef.current = null;
      walkModeRef.current = null;
      measureToolRef.current = null;
      setViewerToolsReady(false);
      setSceneManagerReady(null);
    };
    // Intentionally only run on mount — stable refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Dark mode detection — watches the <html> element's `class` attribute
  // for "dark" and tells the SceneManager to swap background + grid colors.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const html = document.documentElement;
    const sync = () => scene.setDarkMode(html.classList.contains('dark'));
    sync(); // initial
    const observer = new MutationObserver(sync);
    observer.observe(html, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // Re-wire callbacks when handlers change (avoid stale closures).  The mount
  // effect above captures the initial values of these props in the
  // SelectionManager closures, so without ref-forwarding the prop changes
  // never reach the parent.  Mirrors what onIsolationChangeRef already does.
  const onElementSelectRef = useRef(onElementSelect);
  onElementSelectRef.current = onElementSelect;
  const onElementHoverRef = useRef(onElementHover);
  onElementHoverRef.current = onElementHover;
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  // Load elements when data changes.  Reload (clear + recreate meshes) on
  // model identity change — driving off `modelId` rather than element count
  // avoids the silent failure where two models happen to have the same
  // count and the new model's data is grafted onto the previous model's
  // meshes.  In-place data updates remain for non-identity changes (link
  // updates, validation refresh).
  const lastLoadedModelIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!elementMgrRef.current || !elements) return;
    const modelChanged = lastLoadedModelIdRef.current !== modelId;
    if (modelChanged) {
      elementMgrRef.current.clear();
      elementMgrRef.current.loadElements(elements, { skipPlaceholders: !showBoundingBoxes });
      lastLoadedModelIdRef.current = modelId;
      // Drop any leftover measurement view-state — the underlying THREE
      // objects were removed with the previous scene and the model swap
      // gives every measurement a stale anchor.
      useBIMMeasurementsStore.getState().clear();
      measureMgrRef.current?.clearAll();
    } else {
      // Same model, data refreshed (e.g. new BOQ links).  Update in place.
      elementMgrRef.current.updateElementData(elements);
    }
    setElementCount(elements.length);
    // Refresh selected element with latest data (e.g. new BOQ links)
    if (selectedElement && elementMgrRef.current) {
      const fresh = elementMgrRef.current.getElementData(selectedElement.id);
      if (fresh) setSelectedElement(fresh);
    }
  }, [elements, showBoundingBoxes]);

  // Load DAE geometry when URL is available (after elements are loaded)
  const onGeometryLoadedRef = useRef(onGeometryLoaded);
  onGeometryLoadedRef.current = onGeometryLoaded;
  // True while a deep-link isolation OR a clash-focus point is active. The
  // post-load camera re-fit (which frames the FULL model) must NOT run in
  // that case — it would override the deep-link framing the isolate/clash
  // effect is about to apply, leaving the user staring at the whole model
  // again (the original "nothing happens" symptom).
  const deepLinkActiveRef = useRef(false);
  deepLinkActiveRef.current =
    !!(isolatedIds && isolatedIds.length > 0) || !!focusPoint;
  useEffect(() => {
    if (!elementMgrRef.current || !geometryUrl || !elements?.length) return;
    const mgr = elementMgrRef.current;
    // Only load if not already loaded for this URL
    if (!mgr.hasLoadedGeometry()) {
      // Reset progress + error state at the start of every load.
      setGeometryProgress(0);
      setGeometryError(null);
      setGeometryErrorStack(null);
      setGeometryErrorDiagnostic(null);
      setGeometryErrorStatus(null);
      setGeometryErrorRequestId(null);
      // Per-modelId geometry cache (RFC 19 §UX-1). Hits skip the network
      // round-trip entirely; misses populate the cache for the next mount.
      const cacheStore = useBIMGeometryCache.getState();
      mgr
        .loadGeometry(
          geometryUrl,
          (fraction) => {
            // ColladaLoader fires this on every XHR progress event,
            // typically every few KB.  We clamp to [0, 1] defensively
            // and let the React render schedule batch updates.
            setGeometryProgress(Math.max(0, Math.min(1, fraction)));
          },
          {
            lookup: (url) => {
              const hit = cacheStore.get(modelId, url);
              if (!hit) return null;
              return { buffer: hit.buffer, format: hit.format };
            },
            store: (url, buffer, format) => {
              useBIMGeometryCache.getState().put(modelId, {
                buffer,
                format,
                url,
                cachedAt: Date.now(),
              });
            },
          },
        )
        .then(() => {
          // Final 100% tick is emitted by ElementManager itself
          // (after parsing finishes); hide the overlay one frame
          // later so the bar fully fills before disappearing.
          setGeometryProgress(1);
          if (geometryProgressTimeoutRef.current !== null) {
            clearTimeout(geometryProgressTimeoutRef.current);
          }
          geometryProgressTimeoutRef.current = setTimeout(() => {
            setGeometryProgress(null);
            geometryProgressTimeoutRef.current = null;
          }, 200);
          onGeometryLoadedRef.current?.(mgr.getMeshMatchRatio());
          // Signal that the meshMap is now populated so any deep-link
          // isolate / clash-highlight / clash-focus that arrived before the
          // geometry finished (the common case — the skeleton element list
          // resolves long before the multi-MB GLB) gets re-applied instead
          // of being lost to the load race.
          setGeometryReadyNonce((n) => n + 1);
          // Re-fit the camera AFTER the DAE scene has been parented and
          // the next render cycle had a chance to commit world matrices.
          // We chain two requestAnimationFrame calls so the fit runs
          // after the browser has actually committed the new geometry to
          // the scene graph and performed a layout/paint pass.  This
          // replaces the previous triple-setTimeout approach which was
          // fragile and could still miss frames on slow machines.
          // Each call inside SceneManager.zoomToFit forces
          // updateMatrixWorld(true), so a stale matrix tree cannot
          // sabotage the bbox computation.
          const fit = () => {
            // Skip the full-model fit when a deep-link isolation / clash
            // focus is pending — the isolate/clash effect frames the right
            // subset/point instead (re-triggered by geometryReadyNonce).
            if (deepLinkActiveRef.current) return;
            sceneRef.current?.zoomToFit();
          };
          fit();
          requestAnimationFrame(() => {
            fit();
            requestAnimationFrame(fit);
          });
        })
        .catch((err) => {
          // Surface the error in the UI — issue #113. Previously this
          // path only logged to console, so the user saw an empty
          // canvas with no signal at all. The banner exposes the
          // failure mode (network 401/404, malformed GLB/DAE, etc.) and
          // offers a retry without forcing a full page reload.
          //
          // We now also capture the top 3 stack frames so a user can
          // include them on a bug report without opening DevTools —
          // the deep stack tells us whether the error came from inside
          // GLTFLoader, ColladaLoader, or our processLoadedScene path,
          // which previously required reproducing the failure locally
          // to diagnose. Truncated to 3 frames so we don't dump a 50-
          // line wall of text into the UI for a parse error.
          // eslint-disable-next-line no-console
          console.warn('[BIM] Geometry load failed:', err);
          const message =
            err instanceof Error
              ? err.message || err.name || 'Unknown error'
              : typeof err === 'string'
                ? err
                : 'Unknown error';
          const stackText =
            err instanceof Error && err.stack
              ? err.stack
                  .split('\n')
                  .slice(0, 4) // first line is the message; next 3 are frames
                  .join('\n')
              : null;
          // Backend now attaches a structured `diagnostic` dict to ALL
          // geometry-error paths (401/403/404/422), each carrying the
          // correlation request_id, a plain-language `cause` (422 only),
          // and an actionable `remediation` string. Pull it out plus the
          // HTTP status code and the request_id so the banner can render
          // status-aware copy instead of "Failed to fetch geometry: 422".
          const errAny = err as {
            diagnostic?: unknown;
            status?: number;
            requestId?: string | null;
          };
          const diagnostic =
            err && typeof err === 'object' && 'diagnostic' in err
              ? (errAny.diagnostic as Record<string, unknown> | null | undefined)
              : null;
          const status =
            err && typeof err === 'object' && typeof errAny.status === 'number'
              ? errAny.status
              : null;
          // Request ID may also live INSIDE the diagnostic dict — backends
          // emit it both ways for resilience against header stripping by
          // intermediate proxies.
          let requestIdFromDiag: string | null = null;
          if (diagnostic && typeof diagnostic === 'object') {
            const rid = (diagnostic as { request_id?: unknown }).request_id;
            if (typeof rid === 'string' && rid) requestIdFromDiag = rid;
          }
          const requestId =
            (typeof errAny.requestId === 'string' && errAny.requestId) ||
            requestIdFromDiag ||
            null;
          setGeometryError(message);
          setGeometryErrorStack(stackText);
          setGeometryErrorDiagnostic(
            diagnostic && typeof diagnostic === 'object' ? diagnostic : null,
          );
          setGeometryErrorStatus(status);
          setGeometryErrorRequestId(requestId);
          setGeometryProgress(null);
        });
    }
    return () => {
      // Clear the "hide overlay" timer if we unmount or re-trigger before
      // the 200ms delay elapses — prevents setState-on-unmounted warnings.
      if (geometryProgressTimeoutRef.current !== null) {
        clearTimeout(geometryProgressTimeoutRef.current);
        geometryProgressTimeoutRef.current = null;
      }
    };
  // Re-run when geometryUrl changes OR when elements first arrive (guard above).
  // ``geometryRetryNonce`` is bumped by the retry button on the error banner
  // (issue #113) — it forces a re-run with the same URL after the user
  // resets the load-status flag below.
  // Using elements.length as dep avoids re-triggering on data-only updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometryUrl, elements?.length, geometryRetryNonce]);

  // Apply filter predicate whenever it changes. Predicates from BIMFilterPanel
  // are rebuilt on every filter state change, so this effect fires fast but
  // only toggles mesh.visible — no geometry regeneration.
  //
  // After applying, we ZOOM the camera to the visible subset so the user gets
  // immediate spatial feedback. For models where mesh ↔ element mapping is
  // approximate (DDC RVT exports without stable IDs), the zoom gives the
  // user a tangible "the filter did something" signal even when the per-mesh
  // visibility isn't perfectly accurate.
  useEffect(() => {
    if (!elementMgrRef.current || !sceneRef.current) return;
    // Clear manually hidden elements so the new filter starts from a
    // clean slate.  Without this, IDs hidden via the context-menu
    // "Hide element" action leak across filter changes.
    setHiddenIds(new Set());
    const hasIsolation = !!(isolatedIds && isolatedIds.length > 0);
    const hasFilter = !!filterPredicate;
    const hasClashFocus = !!focusPoint;
    // Frame the camera on the clash centroid when one was supplied. This is
    // the reliable focus target for the clash-review deep-link: showcase
    // IFC/RVT models export GLB nodes named with numeric Revit ids that
    // never equal the DB element UUIDs, so the per-element mesh pairing is
    // only an approximate positional fallback — zooming to those meshes can
    // frame the wrong spot. The clash centroid is exact regardless.
    const frameClash = (): boolean => {
      if (!hasClashFocus || !sceneRef.current) return false;
      // `focusPoint` is the clash centroid in the backend's canonical Z-up
      // world (same frame as element bounding boxes). The loaded scene is
      // rotated -90° about X (Z-up → Y-up) — exactly the transform the
      // positional-fallback applies to element bbox centres
      // (ElementManager: vx = x, vy = z, vz = -y). Apply the same here so
      // the camera target lands on the geometry, not 90° off.
      sceneRef.current.focusOnPoint(
        { x: focusPoint!.x, y: focusPoint!.z, z: -focusPoint!.y },
        4,
      );
      return true;
    };
    if (hasIsolation && hasFilter) {
      // Intersection semantics: visible = isolatedIds ∩ filterPredicate(elements).
      // Compute the intersecting id set and route through isolate() so the
      // unmatched DAE background is hidden (consistent with pure-isolate
      // mode). An empty intersection is fine — viewer shows nothing, same
      // as a filter that rejects everything.
      const idSet = new Set(isolatedIds);
      const pool = elements ?? [];
      const intersectIds = pool
        .filter((e) => idSet.has(e.id) && filterPredicate!(e))
        .map((e) => e.id);
      elementMgrRef.current.isolate(intersectIds);
      if (!frameClash()) {
        const visibleMeshes = elementMgrRef.current
          .getAllMeshes()
          .filter((m) => m.visible);
        if (visibleMeshes.length > 0) {
          sceneRef.current.zoomToSelection(visibleMeshes);
        }
      }
    } else if (hasIsolation) {
      elementMgrRef.current.isolate(isolatedIds!);
      // (The clash red / BOQ orange colouring is applied by the dedicated
      // highlight effect below — keeping all highlight-material mutation in
      // one place so the two consumers don't clear each other.)
      //
      // Prefer the clash centroid for framing; fall back to the matched
      // meshes (and only those — not the whole model) when no centroid was
      // passed.
      if (!frameClash()) {
        const visibleMeshes = elementMgrRef.current
          .getAllMeshes()
          .filter((m) => m.visible);
        if (visibleMeshes.length > 0) {
          sceneRef.current.zoomToSelection(visibleMeshes);
        }
      }
      // Loud, useful failure: nothing isolated AND no centroid to fall
      // back on means the clash elements could not be located in this
      // model's geometry. Better than a silently blank viewer.
      if (clashHighlightIds && clashHighlightIds.length > 0) {
        const matched = elementMgrRef.current.getMeshesForIds(clashHighlightIds);
        if (matched.length === 0 && !hasClashFocus) {
          // eslint-disable-next-line no-console
          console.warn(
            '[BIM] clash deep-link: none of',
            clashHighlightIds,
            'resolved to a mesh in model',
            modelId,
            '— and no clash centroid was supplied for camera framing.',
          );
          useToastStore.getState().addToast({
            type: 'warning',
            title: t('bim.clash_elements_not_found', {
              defaultValue:
                "Couldn't locate these elements in the 3D model.",
            }),
            message: t('bim.clash_elements_not_found_hint', {
              defaultValue:
                'The clash references elements that are not in this geometry. Re-upload the model so the viewer can attach a stable reference.',
            }),
          });
        }
      }
    } else if (hasFilter) {
      const visibleCount = elementMgrRef.current.applyFilter(filterPredicate!);
      if (visibleCount > 0 && visibleCount < elementMgrRef.current.getAllMeshes().length) {
        const visibleMeshes = elementMgrRef.current
          .getAllMeshes()
          .filter((m) => m.visible);
        if (visibleMeshes.length > 0) {
          sceneRef.current.zoomToSelection(visibleMeshes);
        }
      } else if (visibleCount === elementMgrRef.current.getAllMeshes().length) {
        // All visible (e.g. cleared filter) — zoom back out to the full model
        sceneRef.current.zoomToFit();
      }
    } else if (hasClashFocus) {
      // Clash focus with no isolation/filter — keep the model visible for
      // context and just point the camera at the interference. Colouring is
      // handled by the highlight effect below.
      elementMgrRef.current.showAll();
      frameClash();
    } else {
      elementMgrRef.current.showAll();
      sceneRef.current.zoomToFit();
    }
  // ``geometryReadyNonce`` re-runs this once the meshMap is populated so a
  // deep-link that arrived before the GLB finished is (re)applied. The
  // clash props frame/colour the interference.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filterPredicate,
    isolatedIds,
    elements,
    geometryReadyNonce,
    clashHighlightIds,
    focusPoint,
  ]);

  // Highlight linked elements when the parent passes a set of IDs. Unlike
  // isolate(), this does NOT hide the rest of the model — it just recolours
  // the matched meshes.
  //
  // Two consumers share this single highlight pass (the manager keeps only
  // one set of highlight materials, so they must NOT run in separate effects
  // or the later one clears the earlier one):
  //   • clashHighlightIds → clash red (#ff3b30) — the clash-review deep-link
  //     flags the two interfering elements on top of the isolation set.
  //   • highlightedIds     → BOQ-link orange — shows which elements a BOQ
  //     position is linked to.
  // Clash takes precedence when both are set. Depends on geometryReadyNonce
  // so a deep-link that arrived before the GLB finished is re-applied.
  useEffect(() => {
    if (!elementMgrRef.current) return;
    if (clashHighlightIds && clashHighlightIds.length > 0) {
      elementMgrRef.current.highlight(clashHighlightIds, 0xff3b30);
    } else {
      elementMgrRef.current.highlight(highlightedIds ?? []);
    }
  }, [highlightedIds, clashHighlightIds, elements, geometryReadyNonce]);

  // Apply color-by mode when it changes.
  // Field-based modes use the existing hash-to-hue palette via colorBy().
  // Compliance modes use a fixed red/amber/green palette via colorByDirect()
  // so the 3D viewer becomes a live compliance dashboard.
  useEffect(() => {
    if (!elementMgrRef.current || !elements?.length) return;
    const mgr = elementMgrRef.current;
    // Diff overlay takes precedence over every colour-by mode: while a
    // model-version comparison is active the user is reviewing changes,
    // not coverage/validation. Added = green, modified = amber, unchanged
    // = faded grey. Deleted elements aren't in this model so they only
    // show in the diff panel list.
    if (diffChangeByStableId && diffChangeByStableId.size > 0) {
      import('three').then((THREE) => {
        const GREEN = new THREE.Color('#10b981');
        const AMBER = new THREE.Color('#f59e0b');
        const GREY = new THREE.Color('#cbd5e1');
        mgr.colorByDirect(
          (el) => {
            const change = el.stable_id
              ? diffChangeByStableId.get(el.stable_id)
              : undefined;
            if (change === 'added') return GREEN;
            if (change === 'modified') return AMBER;
            return GREY;
          },
          (el) => {
            const change = el.stable_id
              ? diffChangeByStableId.get(el.stable_id)
              : undefined;
            // Fade the unchanged context so the changes pop.
            return change === 'added' || change === 'modified' ? 1 : 0.35;
          },
        );
      });
      return;
    }
    if (colorByMode === 'storey') {
      mgr.colorBy((el) => el.storey || 'Unassigned');
    } else if (colorByMode === 'type') {
      mgr.colorBy((el) => el.element_type || 'Unknown');
    } else if (colorByMode === 'validation') {
      // Lazy import THREE so we don't blow up SSR / type-only consumers.
      import('three').then((THREE) => {
        const RED = new THREE.Color('#ef4444');
        const AMBER = new THREE.Color('#f59e0b');
        const GREEN = new THREE.Color('#10b981');
        const GREY = new THREE.Color('#9ca3af');
        mgr.colorByDirect((el) => {
          const status = el.validation_status ?? 'unchecked';
          if (status === 'error') return RED;
          if (status === 'warning') return AMBER;
          if (status === 'pass') return GREEN;
          return GREY;
        });
      });
    } else if (colorByMode === 'boq_coverage') {
      import('three').then((THREE) => {
        const RED = new THREE.Color('#ef4444');
        const GREEN = new THREE.Color('#10b981');
        mgr.colorByDirect((el) =>
          (el.boq_links?.length ?? 0) > 0 ? GREEN : RED,
        );
      });
    } else if (colorByMode === 'document_coverage') {
      import('three').then((THREE) => {
        const RED = new THREE.Color('#ef4444');
        const GREEN = new THREE.Color('#10b981');
        mgr.colorByDirect((el) =>
          (el.linked_documents?.length ?? 0) > 0 ? GREEN : RED,
        );
      });
    } else if (colorByMode === '4d_schedule') {
      // 4D schedule mode — recolour based on the status of each element
      // at the current scrubber position.  When the schedule isn't
      // available we degrade to "default" colors so the viewer still
      // looks sensible while the user is picking a 4D-enabled project.
      if (!fourD.isAvailable) {
        mgr.resetColors();
        return;
      }
      import('three').then((THREE) => {
        const GREY_HIDDEN = new THREE.Color('#9ca3af');
        // Amber = in-progress (spec allows a user-configured colour later,
        // but the default matches validation-warning amber so the visual
        // language stays consistent across the viewer).
        const AMBER = new THREE.Color('#f59e0b');
        mgr.colorByDirect(
          (el) => {
            const status = resolveElementStatus(
              el.id,
              fourD.currentMs,
              fourD.elementToActivities,
              fourD.activitiesById,
            );
            if (status === 'unlinked') return null; // leave untouched
            if (status === 'not_started') return GREY_HIDDEN;
            if (status === 'completed') return null; // full normal colour
            return AMBER; // in_progress
          },
          (el) => {
            const status = resolveElementStatus(
              el.id,
              fourD.currentMs,
              fourD.elementToActivities,
              fourD.activitiesById,
            );
            // Not-started elements fade to 20% opacity so the user still
            // sees the ghost shape of the future work (helps orient the
            // scene as the scrubber moves).
            if (status === 'not_started') return 0.2;
            return 1;
          },
        );
      });
    } else if (colorByMode === '5d_cost') {
      // Build a rate map: for each element, pick the highest unit_rate
      // across its linked BOQ positions. "Highest" because the user is
      // looking at a 3D heatmap of cost — an element that participates in
      // both a €5 position and a €500 position reads as "high cost" to a
      // human, not "average cost". Zero / null rates are treated as "no
      // data" so they don't drag the min down to 0 for every model.
      const rateByElement = new Map<string, number>();
      let minRate = Infinity;
      let maxRate = -Infinity;
      for (const el of elements ?? []) {
        let best: number | null = null;
        for (const link of el.boq_links ?? []) {
          const r = link.boq_position_unit_rate;
          if (r == null || !Number.isFinite(r) || r <= 0) continue;
          if (best === null || r > best) best = r;
        }
        if (best !== null) {
          rateByElement.set(el.id, best);
          if (best < minRate) minRate = best;
          if (best > maxRate) maxRate = best;
        }
      }
      // If no rates at all, degrade to a single "no data" fade so the
      // viewer still responds to the mode switch instead of silently
      // staying on the previous colouring.
      if (!Number.isFinite(minRate) || !Number.isFinite(maxRate)) {
        minRate = 0;
        maxRate = 0;
      }
      import('three').then((THREE) => {
        mgr.colorByDirect(
          (el) => {
            const rate = rateByElement.get(el.id) ?? null;
            const { color } = colorForRate(rate, minRate, maxRate);
            return new THREE.Color(color);
          },
          (el) => (rateByElement.has(el.id) ? 1 : NO_LINK_OPACITY),
        );
      });
    } else {
      mgr.resetColors();
    }
  }, [
    colorByMode,
    elements,
    diffChangeByStableId,
    // 4D mode is time-varying: recolour whenever the scrubber moves or
    // the schedule data re-arrives.  These deps are harmless for other
    // modes because `fourD.currentMs` is a stable 0 when unavailable.
    fourD.isAvailable,
    fourD.currentMs,
    fourD.activitiesById,
    fourD.elementToActivities,
  ]);

  // Sync per-category opacity (RFC 19 §4.2) from the shared store — materials
  // are cloned on first use so this is cheap on subsequent slider drags.
  useEffect(() => {
    const mgr = elementMgrRef.current;
    if (!mgr) return;
    for (const [category, opacity] of Object.entries(categoryOpacity)) {
      mgr.setCategoryOpacity(category, opacity);
    }
  }, [categoryOpacity, elements]);

  // Apply the selected render-quality preset whenever the store value
  // changes — or whenever the scene/element managers are (re)created so
  // a freshly loaded model picks up the persisted localStorage choice
  // without the user having to re-toggle the segment.
  useEffect(() => {
    sceneManagerReady?.applyQualityMode(qualityMode);
    elementMgrRef.current?.applyQualityMode(qualityMode);
  }, [qualityMode, sceneManagerReady, elements]);

  // Sync hidden-category toggles from the Layers tab.
  useEffect(() => {
    const mgr = elementMgrRef.current;
    if (!mgr) return;
    for (const el of mgr.getAllElements()) {
      const mesh = mgr.getMesh(el.id);
      if (!mesh) continue;
      if (hiddenCategories[el.element_type] === true) {
        mesh.visible = false;
      }
    }
    sceneRef.current?.requestRender();
  }, [hiddenCategories, elements]);

  // Toggle the measure tool in response to the Zustand flag. Selection is
  // suspended while measure is active so clicks land only on the ruler and
  // don't drag selection state around with each point placement.
  useEffect(() => {
    measureMgrRef.current?.setActive(measureActive);
    selectionMgrRef.current?.setSuspended(measureActive);
  }, [measureActive]);

  // Sync measure kind (distance / area / angle) + vertex snapping from the
  // shared store. Changing the kind clears any half-traced measurement.
  useEffect(() => {
    measureMgrRef.current?.setKind(measureKind);
  }, [measureKind]);
  useEffect(() => {
    measureMgrRef.current?.setSnapEnabled(measureSnap);
  }, [measureSnap]);

  // Sync the section box / clipping plane from the shared store.
  useEffect(() => {
    clipMgrRef.current?.setMode(clipMode);
  }, [clipMode]);
  useEffect(() => {
    clipMgrRef.current?.setBoxExtent(clipBox);
  }, [clipBox]);
  useEffect(() => {
    clipMgrRef.current?.setPlaneState(clipPlane);
  }, [clipPlane]);

  // Re-fit the clip planes to the freshly loaded model so a section that was
  // enabled before geometry streamed in cuts the new mesh, not the old box.
  useEffect(() => {
    if (clipMode !== 'none') clipMgrRef.current?.invalidateModelBox();
    // Driven off element identity + geometry-loaded the same way the rest of
    // the load chain is.
  }, [elements, clipMode]);

  // Ghost mode: dim everything except the current selection. Restores
  // cleanly when toggled off or when the selection clears. Mutually
  // exclusive with isolation (isolation hides, ghost dims) — the UI only
  // lets one run at a time.
  useEffect(() => {
    const mgr = elementMgrRef.current;
    if (!mgr) return;
    if (ghostActive && selectedElementIds && selectedElementIds.length > 0) {
      mgr.ghost(selectedElementIds);
    } else {
      mgr.clearGhost();
    }
  }, [ghostActive, selectedElementIds, elements]);

  // Expose a tiny camera bridge on `window.__oeBim` so sibling right-panel
  // tabs can snapshot/restore the camera without a direct SceneManager handle.
  // Also surfaces measure-tool actions (remove / clear / setVisible / focus)
  // so the Tools panel measurement list can drive the in-scene THREE objects.
  //
  // v3.12.0 (Stream D) — surface screenshot capture + clip state on the same
  // bridge so the saved-views feature can snapshot the full viewer state
  // (camera + filter + clip + thumbnail) in one call. Filter state lives in
  // BIMFilterPanel and is exposed via a separate ``window.__oeBimFilter``
  // bridge installed by that panel.
  useEffect(() => {
    const w = window as unknown as {
      __oeBim?: {
        getViewpoint: () => ReturnType<SceneManager['getViewpoint']> | null;
        setViewpoint: (
          pos: { x: number; y: number; z: number },
          target: { x: number; y: number; z: number },
        ) => void;
        /** W6.6 Stream B — tween the camera to ``target`` over ``durationMs``
         *  (default 600). Resolves when the tween completes and rejects with
         *  ``Error('flyTo cancelled')`` if a newer tween overtakes it. */
        flyTo: (
          target: {
            position: [number, number, number] | { x: number; y: number; z: number };
            target: [number, number, number] | { x: number; y: number; z: number };
          },
          durationMs?: number,
        ) => Promise<void>;
        /** W6.6 Stream B — fly the camera to one of the cube presets
         *  (top / bottom / front / back / left / right / iso). Same promise
         *  semantics as ``flyTo``. */
        setViewPreset: (
          name:
            | 'top'
            | 'bottom'
            | 'front'
            | 'back'
            | 'left'
            | 'right'
            | 'iso',
          durationMs?: number,
        ) => Promise<void>;
        getScreenshot: (opts?: { width?: number; height?: number }) => string | null;
        getClipState: () => {
          mode: 'none' | 'box' | 'plane';
          boxExtent: ReturnType<NonNullable<typeof clipMgrRef.current>['getBoxExtent']>;
          plane: ReturnType<NonNullable<typeof clipMgrRef.current>['getPlaneState']>;
        } | null;
        setClipState: (state: {
          mode: 'none' | 'box' | 'plane';
          boxExtent?: typeof clipBox;
          plane?: typeof clipPlane;
        }) => void;
        removeMeasurement: (id: string) => void;
        clearMeasurements: () => void;
        setMeasurementVisible: (id: string, visible: boolean) => void;
        focusMeasurement: (id: string) => void;
        /** W6.6 — live manager handles for sibling panels (Trait Lens,
         *  Element Bundles) and Playwright scripts. ``null`` while the
         *  scene is still mounting; consumers should re-read on demand. */
        sceneManager: SceneManager | null;
        elementManager: ElementManager | null;
        selectionManager: SelectionManager | null;
      };
    };
    w.__oeBim = {
      getViewpoint: () => sceneRef.current?.getViewpoint() ?? null,
      setViewpoint: (pos, target) => sceneRef.current?.setViewpoint(pos, target),
      flyTo: (target, durationMs) => {
        const scene = sceneRef.current;
        if (!scene) return Promise.resolve();
        // Coerce ``{x,y,z}`` into tuples to match SceneManager.flyTo's
        // CameraState signature without forcing callers to know that detail.
        const toTuple = (
          v: [number, number, number] | { x: number; y: number; z: number },
        ): [number, number, number] =>
          Array.isArray(v) ? v : [v.x, v.y, v.z];
        return scene.flyTo(
          {
            position: toTuple(target.position),
            target: toTuple(target.target),
          },
          durationMs ?? 600,
        );
      },
      setViewPreset: (name, durationMs) => {
        const scene = sceneRef.current;
        if (!scene) return Promise.resolve();
        // The window-bridge accepts the friendly alias 'iso' to keep
        // calling code simple; SceneManager's canonical ViewPreset uses
        // the four-quadrant variants. NE is the conventional default
        // (top-down NE-looking isometric).
        const canonical = name === 'iso' ? 'iso_ne' : name;
        return scene.setViewPreset(canonical, durationMs ?? 600);
      },
      getScreenshot: (opts) => sceneRef.current?.getScreenshot(opts) ?? null,
      getClipState: () => {
        const mgr = clipMgrRef.current;
        if (!mgr) return null;
        return {
          mode: mgr.mode,
          boxExtent: mgr.getBoxExtent(),
          plane: mgr.getPlaneState(),
        };
      },
      setClipState: (state) => {
        // Order matters: update the local mirrors first so the existing
        // sync effects push the values into ClipManager and the React
        // popover at the same time.
        if (state.boxExtent) setClipBox(state.boxExtent);
        if (state.plane) setClipPlane(state.plane);
        setClipMode(state.mode);
      },
      removeMeasurement: (id) => measureMgrRef.current?.removeMeasurement(id),
      clearMeasurements: () => measureMgrRef.current?.clearAll(),
      setMeasurementVisible: (id, visible) =>
        measureMgrRef.current?.setMeasurementVisible(id, visible),
      focusMeasurement: (id) => measureMgrRef.current?.focusMeasurement(id),
      sceneManager: sceneManagerReady,
      elementManager: elementMgrRef.current,
      selectionManager: selectionMgrRef.current,
    };
    return () => {
      if (w.__oeBim) delete w.__oeBim;
    };
  }, [setClipBox, setClipPlane, setClipMode, sceneManagerReady]);

  // Sync selection from parent — ONLY when the parent explicitly changes
  // selection (e.g. clicking a row in the filter panel). Skip when the
  // selection originated from the viewer's own SelectionManager (Ctrl+Click)
  // to avoid resetting multi-select back to a single element.
  const internalSelectionRef = useRef(false);
  useEffect(() => {
    if (!selectionMgrRef.current || !selectedElementIds) return;
    // Skip if this change was triggered by our own onSelectionChange callback
    if (internalSelectionRef.current) {
      internalSelectionRef.current = false;
      return;
    }
    selectionMgrRef.current.setSelection(selectedElementIds);

    if (selectedElementIds.length > 0 && elementMgrRef.current) {
      const data = elementMgrRef.current.getElementData(selectedElementIds[0]!);
      setSelectedElement(data ?? null);
    }
  }, [selectedElementIds]);

  // Toolbar actions
  const handleZoomToFit = useCallback(() => {
    sceneRef.current?.zoomToFit();
  }, []);

  const handleToggleWireframe = useCallback(() => {
    elementMgrRef.current?.toggleWireframe();
    setWireframe((prev) => !prev);
  }, []);

  const handleZoomToSelection = useCallback(() => {
    const selMgr = selectionMgrRef.current;
    const elMgr = elementMgrRef.current;
    const scene = sceneRef.current;
    if (!selMgr || !elMgr || !scene) return;

    const ids = selMgr.getSelectedIds();
    const meshes = ids
      .map((id) => elMgr.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0) {
      scene.zoomToSelection(meshes);
    }
  }, []);

  const handleCloseProperties = useCallback(() => {
    setSelectedElement(null);
    setParquetProps(null);
    setParquetExpanded(false);
    selectionMgrRef.current?.clearSelection();
    onElementSelect?.(null);
  }, [onElementSelect]);

  /** Per-element Parquet row cache. Keyed by revitId (mesh_ref / DAE node
   *  id) so re-clicking an element is instant — no refetch, no skeleton
   *  flash. Cleared when the model changes (below). */
  const parquetCacheRef = useRef<Map<string, Record<string, unknown> | null>>(new Map());
  // Abort in-flight fetch when the user picks a different element mid-request,
  // so a slow query for element A never overwrites fresh data for element B.
  const parquetAbortRef = useRef<AbortController | null>(null);

  /** Resolve the Revit ElementId of the currently-selected element. The
   *  Parquet's primary key column is `id` and contains this value — it is
   *  exposed on the BIMElement row as `mesh_ref`. Unmatched stubs use the
   *  DAE node name (backend-patched to equal the Revit id). */
  const revitIdOf = useCallback((el: BIMElementData | null): string | null => {
    if (!el) return null;
    const props = el.properties as Record<string, unknown> | undefined;
    const nodeName = props?.node_name as string | undefined;
    const propId = props?.id as string | undefined;
    return el.mesh_ref || propId || nodeName || el.stable_id || null;
  }, []);

  // Clear the cache when the model itself changes — a new model has a
  // different Parquet and potentially colliding ids.
  useEffect(() => {
    parquetCacheRef.current.clear();
    parquetAbortRef.current?.abort();
    parquetAbortRef.current = null;
    setParquetProps(null);
    setParquetLoading(false);
  }, [modelId]);

  // Auto-fetch the full Parquet row as soon as an element is selected so
  // the user sees all properties without switching tabs. Results are cached
  // per revitId in `parquetCacheRef` — re-clicking the same element is
  // instant and shows no skeleton flash.
  useEffect(() => {
    if (!selectedElement || !modelId) {
      setParquetProps(null);
      setParquetLoading(false);
      return;
    }
    const revitId = revitIdOf(selectedElement);
    if (!revitId) {
      setParquetProps(null);
      setParquetLoading(false);
      return;
    }

    // Cache hit → render immediately, no loading state, no flash.
    const cached = parquetCacheRef.current.get(revitId);
    if (cached !== undefined) {
      setParquetProps(cached);
      setParquetLoading(false);
      setParquetExpanded(true);
      return;
    }

    // Cancel any in-flight fetch for the previous selection.
    parquetAbortRef.current?.abort();
    const ac = new AbortController();
    parquetAbortRef.current = ac;

    setParquetLoading(true);
    setParquetProps(null);

    void (async () => {
      try {
        const row = await fetchBIMElementProperties(modelId, revitId, ac.signal);
        if (ac.signal.aborted) return;
        parquetCacheRef.current.set(revitId, row);
        setParquetProps(row);
      } catch (err) {
        // Abort is expected when the user clicks a new element mid-fetch —
        // we don't want to null out state, the next effect run will handle it.
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (!ac.signal.aborted) setParquetProps(null);
      } finally {
        if (!ac.signal.aborted) {
          setParquetLoading(false);
          setParquetExpanded(true);
        }
      }
    })();

    return () => {
      ac.abort();
    };
  }, [selectedElement, modelId, revitIdOf]);

  /** Kept for the legacy "All properties" refresh button so it still
   *  force-refetches on demand, bypassing the cache. */
  const handleFetchAllProperties = useCallback(async () => {
    if (!selectedElement || !modelId) return;
    const revitId = revitIdOf(selectedElement);
    if (!revitId) {
      setParquetProps({});
      return;
    }
    parquetCacheRef.current.delete(revitId);
    parquetAbortRef.current?.abort();
    const ac = new AbortController();
    parquetAbortRef.current = ac;

    setParquetLoading(true);
    try {
      const row = await fetchBIMElementProperties(modelId, revitId, ac.signal);
      parquetCacheRef.current.set(revitId, row);
      if (!ac.signal.aborted) setParquetProps(row);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!ac.signal.aborted) setParquetProps(null);
    } finally {
      if (!ac.signal.aborted) {
        setParquetLoading(false);
        setParquetExpanded(true);
      }
    }
  }, [selectedElement, modelId, revitIdOf]);

  const handleToggleGrid = useCallback(() => {
    sceneRef.current?.toggleGrid();
    setGridVisible((v) => !v);
  }, []);

  const handleToggleBoxes = useCallback(() => {
    if (!elementMgrRef.current) return;
    const mgr = elementMgrRef.current;
    setBoxesVisible((prev) => {
      const next = !prev;
      // Toggle visibility of all placeholder box meshes in elementGroup
      mgr.elementGroup.visible = next;
      sceneRef.current?.requestRender();
      return next;
    });
  }, []);

  const handleCameraPreset = useCallback((view: 'top' | 'front' | 'side' | 'iso') => {
    sceneRef.current?.setCameraPreset(view);
  }, []);

  const addToast = useToastStore((s) => s.addToast);

  /** Capture the current 3D viewport as a PNG, prompt the browser to save
   *  it, and (best-effort) copy it to the clipboard so the user can paste
   *  into Slack / docs / email without a round-trip through the filesystem.
   *
   *  Rendering is synchronous: Three.js' on-demand render loop means the
   *  canvas may be up to one frame stale relative to the latest selection
   *  state, so we force a fresh render before calling `toDataURL`.  The
   *  clipboard step silently falls back when the browser blocks it
   *  (Firefox at time of writing ignores image/png on http://) — users
   *  still get the downloaded PNG either way. */
  const handleScreenshot = useCallback(async () => {
    const scene = sceneRef.current;
    if (!scene) return;
    // Force a synchronous render into the canvas so whatever is visible
    // right now is what ends up in the PNG — not the pre-selection frame.
    scene.renderer.render(scene.scene, scene.camera);
    const canvas = scene.renderer.domElement;
    let dataUrl: string;
    try {
      dataUrl = canvas.toDataURL('image/png');
    } catch {
      addToast?.({
        type: 'error',
        title: t('bim.screenshot_failed_title', {
          defaultValue: 'Screenshot failed',
        }),
        message: t('bim.screenshot_failed', {
          defaultValue: 'WebGL context unavailable — try reloading the viewer.',
        }),
      });
      return;
    }

    // File download — safe in every browser Chrome/Firefox/Safari.
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const slug = (modelName ?? 'model')
      .replace(/[^a-z0-9_-]+/gi, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48) || 'model';
    const filename = `bim-screenshot-${slug}-${ts}.png`;
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Clipboard write — requires secure context (https or localhost) AND
    // a browser that implements ClipboardItem with image/png. Swallow all
    // errors silently: the download above already fulfils the primary
    // user need, and we don't want to spam a toast on every click just
    // because Firefox says no.
    const nav = navigator as Navigator & {
      clipboard?: Clipboard & {
        write?: (items: ClipboardItem[]) => Promise<void>;
      };
    };
    const ClipboardItemCtor = (
      window as unknown as { ClipboardItem?: typeof ClipboardItem }
    ).ClipboardItem;
    if (
      typeof ClipboardItemCtor === 'function' &&
      nav.clipboard &&
      typeof nav.clipboard.write === 'function'
    ) {
      try {
        const blob = await fetch(dataUrl).then((r) => r.blob());
        const item = new ClipboardItemCtor({ 'image/png': blob });
        await nav.clipboard.write([item]);
      } catch {
        // Clipboard blocked / unsupported — download is already done.
      }
    }

    addToast?.({
      type: 'success',
      title: t('bim.screenshot_saved_title', {
        defaultValue: 'Screenshot saved',
      }),
      message: filename,
    });
  }, [modelName, t, addToast]);

  // ── Context menu actions ────────────────────────────────────────────
  const handleCloseContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  const handleCtxZoomToElement = useCallback(() => {
    if (!contextMenu?.element) return;
    const mesh = elementMgrRef.current?.getMesh(contextMenu.element.id);
    if (mesh && sceneRef.current) {
      sceneRef.current.zoomToSelection([mesh]);
    }
  }, [contextMenu]);

  const handleCtxCopyProperties = useCallback(() => {
    if (!contextMenu?.element) return;
    const el = contextMenu.element;
    const text = JSON.stringify(
      { id: el.id, name: el.name, type: el.element_type, storey: el.storey, quantities: el.quantities, properties: el.properties },
      null,
      2,
    );
    navigator.clipboard.writeText(text).catch(() => {/* ignore */});
  }, [contextMenu]);

  const handleCtxAddToBOQ = useCallback(() => {
    if (!contextMenu || !onAddToBOQ) return;
    // Prefer all selected elements (bulk); fall back to the single right-clicked element.
    const bulk = contextMenu.selectedElements;
    if (bulk && bulk.length > 0) {
      onAddToBOQ(bulk);
    } else if (contextMenu.element) {
      onAddToBOQ([contextMenu.element]);
    }
  }, [contextMenu, onAddToBOQ]);

  const handleCtxLinkDocument = useCallback(() => {
    if (!contextMenu) return;
    const el = contextMenu.element ?? contextMenu.selectedElements[0];
    if (el && onLinkDocument) onLinkDocument(el);
  }, [contextMenu, onLinkDocument]);

  const handleCtxLinkActivity = useCallback(() => {
    if (!contextMenu) return;
    const el = contextMenu.element ?? contextMenu.selectedElements[0];
    if (el && onLinkActivity) onLinkActivity(el);
  }, [contextMenu, onLinkActivity]);

  const handleCtxCreateTask = useCallback(() => {
    if (!contextMenu) return;
    const el = contextMenu.element ?? contextMenu.selectedElements[0];
    if (el && onCreateTask) onCreateTask(el);
  }, [contextMenu, onCreateTask]);

  const handleCtxIsolate = useCallback(() => {
    if (!contextMenu || !elementMgrRef.current) return;
    const ids = contextMenu.selectedElements.map((el) => el.id);
    if (ids.length === 0) return;
    elementMgrRef.current.isolate(ids);
    setIsIsolated(true);
    onIsolationChange?.(ids);
    const meshes = ids
      .map((id) => elementMgrRef.current!.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0 && sceneRef.current) {
      sceneRef.current.zoomToSelection(meshes);
    }
  }, [contextMenu, onIsolationChange]);

  const handleCtxHide = useCallback(() => {
    if (!contextMenu || !elementMgrRef.current) return;
    const ids = contextMenu.selectedElements.map((el) => el.id);
    if (ids.length === 0) return;
    const newHidden = new Set(hiddenIds);
    for (const id of ids) newHidden.add(id);
    setHiddenIds(newHidden);
    elementMgrRef.current.hideElements(newHidden);
    // Deselect hidden elements
    selectionMgrRef.current?.clearSelection();
    setSelectedElement(null);
    setSelectionCount(0);
    onElementSelect?.(null);
  }, [contextMenu, hiddenIds, onElementSelect]);

  const handleShowAll = useCallback(() => {
    if (!elementMgrRef.current) return;
    elementMgrRef.current.showAll();
    setHiddenIds(new Set());
    setIsIsolated(false);
    onIsolationChange?.(null);
    sceneRef.current?.zoomToFit();
  }, [onIsolationChange]);

  const handleClearSelection = useCallback(() => {
    selectionMgrRef.current?.clearSelection();
    setSelectedElement(null);
    setSelectionCount(0);
    onElementSelect?.(null);
  }, [onElementSelect]);

  const handleSelectionIsolate = useCallback(() => {
    if (!selectionMgrRef.current || !elementMgrRef.current) return;
    const ids = selectionMgrRef.current.getSelectedIds();
    if (ids.length === 0) return;
    elementMgrRef.current.isolate(ids);
    setIsIsolated(true);
    onIsolationChange?.(ids);
    const meshes = ids
      .map((id) => elementMgrRef.current!.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0 && sceneRef.current) {
      sceneRef.current.zoomToSelection(meshes);
    }
  }, [onIsolationChange]);

  const handleSelectionHide = useCallback(() => {
    if (!selectionMgrRef.current || !elementMgrRef.current) return;
    const ids = selectionMgrRef.current.getSelectedIds();
    if (ids.length === 0) return;
    const newHidden = new Set(hiddenIds);
    for (const id of ids) newHidden.add(id);
    setHiddenIds(newHidden);
    elementMgrRef.current.hideElements(newHidden);
    selectionMgrRef.current.clearSelection();
    setSelectedElement(null);
    setSelectionCount(0);
    onElementSelect?.(null);
  }, [hiddenIds, onElementSelect]);

  // ── Smart View overlay (rule-based per-element paint) ───────────────
  // Runs whenever `smartViewEvalResult` flips. When non-null we paint
  // the evaluated state onto every matching mesh; when null we revert
  // every mesh that previously had a cached pristine material. Safe to
  // re-run with the same result thanks to the helper's idempotency.
  useEffect(() => {
    const elementMgr = elementMgrRef.current;
    const scene = sceneRef.current?.scene;
    if (!elementMgr || !scene) return;
    const viewerHandle = { scene, root: scene };
    if (smartViewEvalResult) {
      applySmartView(viewerHandle, smartViewEvalResult);
    } else {
      revertSmartView(viewerHandle);
    }
    // Force one frame so paint changes show up on the next animation tick.
    sceneRef.current?.renderer?.render(scene, sceneRef.current.camera);
  }, [smartViewEvalResult]);

  // ── Keyboard shortcuts ──────────────────────────────────────────────
  //   F     — zoom to fit all
  //   W     — toggle wireframe
  //   G     — toggle grid
  //   1     — front view
  //   2     — side view
  //   3     — top view
  //   0     — isometric view (reset)
  //   Escape — deselect element / close properties
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore shortcuts when user is typing in an input/textarea
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      // Also ignore when modifier keys are held (Ctrl/Cmd combos are browser shortcuts)
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      // Measure tool gets first crack at Escape so an in-progress point
      // is cancelled (and the tool flipped off) before the global deselect
      // path runs.  We DO NOT delegate the on/off flip to the
      // MeasureManager itself: it can't reach into the React store, and
      // when it disabled itself unilaterally the toolbar still showed
      // "Stop measuring" because `measureActive` stayed true (RFC 19 §UX-8).
      if (measureMgrRef.current?.active && e.key === 'Escape') {
        e.preventDefault();
        if (measureMgrRef.current.state === 'awaiting-second') {
          // Mid-measurement — just drop the pending point. Tool stays on.
          // Note: we deliberately DO NOT call clearAll() here — Escape
          // cancels the in-progress click only, completed measurements
          // survive (RFC 19 §UX-9).
          measureMgrRef.current.cancelPending();
        } else {
          // No pending point — leave measure mode entirely. Completed
          // measurements stay rendered + listed in the Tools panel.
          setMeasureActive(false);
        }
        return;
      }

      // Enter closes an in-progress area polygon (delegated to the manager,
      // which only acts when the area kind has ≥3 points).
      if (measureMgrRef.current?.active && e.key === 'Enter') {
        if (measureMgrRef.current.handleKeyDown(e)) {
          e.preventDefault();
          return;
        }
      }

      // #153 guard — keydown on RVT-upload completion-modal close had a
      // synthetic event with `e.key === undefined`, crashing the viewer.
      switch ((e.key ?? '').toLowerCase()) {
        case 'f':
          e.preventDefault();
          sceneRef.current?.zoomToFit();
          break;
        case 'm':
          // Toggle measure tool (RFC 19 §4.4).
          e.preventDefault();
          setMeasureActive(!useBIMViewerStore.getState().measureActive);
          break;
        case 's':
          // Toggle Tools tab on the right panel (RFC 19 §4.5).
          e.preventDefault();
          useBIMViewerStore
            .getState()
            .setRightPanelTab(
              useBIMViewerStore.getState().rightPanelTab === 'tools'
                ? 'properties'
                : 'tools',
            );
          break;
        case 'w':
          e.preventDefault();
          elementMgrRef.current?.toggleWireframe();
          setWireframe((prev) => !prev);
          break;
        case 'g':
          e.preventDefault();
          sceneRef.current?.toggleGrid();
          setGridVisible((v) => !v);
          break;
        case 'b':
          e.preventDefault();
          handleToggleBoxes();
          break;
        case '1':
          e.preventDefault();
          sceneRef.current?.setCameraPreset('front');
          break;
        case '2':
          e.preventDefault();
          sceneRef.current?.setCameraPreset('side');
          break;
        case '3':
          e.preventDefault();
          sceneRef.current?.setCameraPreset('top');
          break;
        case '0':
          e.preventDefault();
          sceneRef.current?.setCameraPreset('iso');
          break;
        case 'h':
        case 'delete':
          // Hide selected elements from view (not permanently deleted)
          e.preventDefault();
          handleSelectionHide();
          break;
        case 'i':
          // Isolate selected elements
          e.preventDefault();
          if (isIsolated) {
            handleShowAll();
          } else {
            handleSelectionIsolate();
          }
          break;
        case 'escape':
          // Close context menu first, then shortcuts, then deselect
          if (contextMenu) {
            setContextMenu(null);
          } else if (showShortcuts) {
            setShowShortcuts(false);
          } else if (isIsolated) {
            handleShowAll();
          } else {
            setSelectedElement(null);
            setParquetProps(null);
            setParquetExpanded(false);
            selectionMgrRef.current?.clearSelection();
            setSelectionCount(0);
            onElementSelect?.(null);
          }
          break;
        case '?':
          e.preventDefault();
          setShowShortcuts((v) => !v);
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onElementSelect, showShortcuts, contextMenu, isIsolated, handleSelectionHide, handleSelectionIsolate, handleShowAll]);

  // Memoize the element properties/quantities for the panel
  const elementProperties = useMemo(() => {
    if (!selectedElement?.properties) return {};
    return selectedElement.properties;
  }, [selectedElement]);

  /** Model summary breakdown — reactive to the active view.
   *
   *  Scope precedence (highest wins):
   *    1. **selection** — user has 2+ elements selected. The summary
   *       aggregates just those elements (useful for "what did I just
   *       isolate?" and "how much of X is in my picks?").
   *    2. **filtered** — a filterPredicate is applied (category chip /
   *       storey chip / discipline toggle). The summary reflects what
   *       the user actually SEES in the viewport.
   *    3. **all** — no filter, no multi-selection: full model stats.
   *
   *  The backing `elements` array can itself already be a group subset
   *  (BIMPage restricts the query when `?group=<id>` is in the URL), so
   *  when a saved group is active the "all" scope is really "whole group".
   *  The `total` / `shown` counts describe what's in `elements` vs what
   *  passes the active scope filter. */
  const modelSummary = useMemo(() => {
    const all = elements ?? [];
    if (all.length === 0) return null;

    // Establish the "viewport universe" — elements the user actually
    // sees. Isolation narrows this BEFORE any other scope reasoning so
    // the summary numbers match the geometry visible on screen (a
    // 109-element filter that isolates 6 walls should report 6, not 109).
    // NOTE: when both isolation AND a filterPredicate are active, the
    // filter below runs over `universe` — so `subset` ends up as the
    // intersection (ids ∩ predicate), matching the viewer's render logic.
    const isolationSet =
      isolatedIds && isolatedIds.length > 0 ? new Set(isolatedIds) : null;
    const universe = isolationSet ? all.filter((el) => isolationSet.has(el.id)) : all;
    if (universe.length === 0) return null;

    const selectedIds = selectedElementIds ?? [];
    let subset: BIMElementData[];
    let scope: 'all' | 'filtered' | 'selection';
    if (selectedIds.length > 1) {
      const set = new Set(selectedIds);
      subset = universe.filter((el) => set.has(el.id));
      scope = 'selection';
    } else if (filterPredicate) {
      subset = universe.filter(filterPredicate);
      scope = 'filtered';
    } else {
      subset = universe;
      // When isolation is the ONLY narrowing in play, badge it as
      // "filtered" so the panel header and "of N" caption switch on.
      scope = isolationSet ? 'filtered' : 'all';
    }
    if (subset.length === 0) return null;

    const byCat = new Map<string, number>();
    const byStorey = new Map<string, number>();
    let totalVolume = 0;
    let totalArea = 0;
    let totalLength = 0;
    for (const el of subset) {
      const cat = el.element_type || 'Unknown';
      byCat.set(cat, (byCat.get(cat) ?? 0) + 1);
      const st = el.storey || 'Unassigned';
      byStorey.set(st, (byStorey.get(st) ?? 0) + 1);
      if (el.quantities) {
        totalVolume += el.quantities['volume'] ?? el.quantities['Volume'] ?? 0;
        totalArea += el.quantities['area'] ?? el.quantities['Area'] ?? 0;
        totalLength += el.quantities['length'] ?? el.quantities['Length'] ?? 0;
      }
    }
    const categories = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
    const storeys = [...byStorey.entries()].sort((a, b) => b[1] - a[1]);
    // Per-key aggregation (SUM / AVG / DISTINCT) — replaces the
    // hard-coded Volume/Area/Length triplet with a deep, classifier-
    // driven roll-up that handles thickness as average, mark numbers
    // as distinct counts, etc.  Computed for any narrowed scope —
    // selection, filter, isolation — because each of these answers
    // "what are the totals for THIS subset?". Skipped only for the
    // unscoped "all" view, where the basic Volume/Area/Length triplet
    // above already covers the model-wide rollup at lower cost.
    const aggregations: AggResult[] =
      scope !== 'all' ? aggregateBIMQuantities(subset) : [];
    return {
      categories,
      storeys,
      totalVolume,
      totalArea,
      totalLength,
      aggregations,
      scope,
      total: all.length,
      shown: subset.length,
    };
  }, [elements, filterPredicate, selectedElementIds, isolatedIds]);

  const elementQuantities = useMemo(() => {
    if (!selectedElement?.quantities) return {};
    return selectedElement.quantities;
  }, [selectedElement]);

  // Canonical geometry derived from the element's bounding box (the
  // canonical format's geometry block is flattened into bbox/quantities by
  // the API — this surfaces the W/D/H/footprint/diagonal it implies).
  const elementGeometry = useMemo(
    () => deriveGeometry(selectedElement?.bounding_box),
    [selectedElement],
  );
  // Canonical spatial relations (level / zone / system / assembly / phase).
  const elementRelations = useMemo(
    () =>
      selectedElement
        ? deriveRelations({
            storey: selectedElement.storey,
            properties: selectedElement.properties,
            metadata: (selectedElement as { metadata?: Record<string, unknown> })
              .metadata,
          })
        : [],
    [selectedElement],
  );

  return (
    <div ref={containerRef} className={clsx('relative w-full h-full min-h-[400px] bg-surface-secondary rounded-lg overflow-hidden', className)}>
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        role="img"
        aria-label={t('bim.viewer.canvas_aria_label', {
          defaultValue: '3D BIM model viewer — use mouse or touch to orbit, zoom, and pan',
        })}
      />

      {/* W6.6 Stream B — Site Compass. Mounts only after the SceneManager
          is alive so the cube never tries to read from a null ref. The
          cube is purely an indicator + cheap raycast target; positioning
          here (top-3 right-3 z-20) keeps it above the canvas and the
          placeholder banner. */}
      {sceneManagerReady && (
        <div
          className="absolute bottom-3 z-20"
          style={{ left: leftPanelOpen ? leftPanelWidth + 16 : 12 }}
          aria-label={t('bim.site_compass.aria_label', {
            defaultValue: 'Site Compass — 3D navigation cube',
          })}
        >
          <BIMViewCube sceneManager={sceneManagerReady} size={112} />
        </div>
      )}

      {/* W6.6 Stream C — Solo Mode hidden-count badge. Visible only when
          at least one element is currently hidden by hide / isolate.
          Click to call ElementManager.showAll() — the same hook the
          context menu uses, so the badge and menu stay in lock-step. */}
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={handleShowAll}
          data-testid="bim-hidden-count-badge"
          className="absolute top-3 left-3 z-20 inline-flex items-center gap-1.5 rounded-full bg-yellow-100/95 backdrop-blur px-3 py-1 text-xs font-semibold text-yellow-900 border border-yellow-300 shadow hover:bg-yellow-200/95 transition cursor-pointer"
          title={t('bim.solo_mode.show_all', { defaultValue: 'Show all' })}
        >
          <EyeOff size={12} className="shrink-0" />
          <span>
            {t('bim.solo_mode.hidden_badge', {
              defaultValue: '{{count}} hidden',
              count: hiddenCount,
            })}
            <span className="mx-1 text-yellow-700">·</span>
            {t('bim.solo_mode.show_all', { defaultValue: 'Show all' })}
          </span>
        </button>
      )}

      {/* Placeholder geometry warning — shown when the backend used the
          text-IFC fallback (DDC cad2data unavailable) and the on-screen
          model is a grid of 0.3×3.0×1.0 m boxes rather than the real
          geometry.  The banner is non-blocking (pointer-events: none on
          the wrapper, re-enabled on its own buttons) so the user can
          still rotate/select underneath.  Issue #53 H1. */}
      {isPlaceholderGeometry && !placeholderBannerDismissed && (
        <div
          data-testid="bim-placeholder-banner"
          className="absolute top-3 left-1/2 -translate-x-1/2 z-20 pointer-events-none flex justify-center px-2 max-w-[90%]"
        >
          <div
            className="pointer-events-auto flex items-start gap-3 rounded-lg border border-amber-300/80 bg-amber-50/95 px-4 py-2.5 text-amber-900 shadow-md backdrop-blur-sm dark:border-amber-500/60 dark:bg-amber-950/90 dark:text-amber-100"
            role="status"
            aria-live="polite"
          >
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="text-xs leading-relaxed">
              <span className="font-semibold">
                {t('bim.placeholder_banner.title', {
                  defaultValue: 'Placeholder geometry',
                })}
              </span>
              <span>{' — '}</span>
              <span>
                {t('bim.placeholder_banner.body', {
                  defaultValue:
                    'install DDC IFC Converter for accurate meshes.',
                })}
              </span>{' '}
              <a
                href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN"
                target="_blank"
                rel="noreferrer"
                className="font-medium underline underline-offset-2 hover:text-amber-700 dark:hover:text-amber-200"
              >
                {t('bim.placeholder_banner.learn_more', { defaultValue: 'Learn more →' })}
              </a>
            </div>
            <button
              type="button"
              onClick={() => setPlaceholderBannerDismissed(true)}
              aria-label={t('bim.placeholder_banner.dismiss', { defaultValue: 'Dismiss' })}
              data-testid="bim-placeholder-banner-dismiss"
              className="ml-1 rounded p-0.5 text-amber-700/80 hover:bg-amber-200/60 hover:text-amber-900 dark:text-amber-300/80 dark:hover:bg-amber-900/40 dark:hover:text-amber-100"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Loading overlay — covers the canvas while either the
          element list is being fetched OR the DAE/COLLADA geometry
          blob is downloading.  When ``geometryProgress`` is non-null
          we show a determinate progress bar with the percent
          complete; otherwise (element fetch only) we show the
          spinner with the generic "Loading model..." label. */}
      {(isLoading || geometryProgress !== null) && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary/80 backdrop-blur-sm z-10">
          <div className="flex flex-col items-center gap-4 w-72 max-w-[80%]">
            <div className="relative">
              <Loader2 size={36} className="animate-spin text-oe-blue" />
              {geometryProgress !== null && geometryProgress < 1 && (
                <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-oe-blue tabular-nums">
                  {Math.round(geometryProgress * 100)}%
                </span>
              )}
            </div>
            <div className="flex flex-col items-center gap-2 w-full">
              <span className="text-sm font-medium text-content-primary">
                {geometryProgress !== null
                  ? t('bim.loading_geometry', {
                      defaultValue: 'Loading 3D geometry…',
                    })
                  : t('bim.loading_model', { defaultValue: 'Loading model…' })}
              </span>
              {geometryProgress !== null ? (
                <>
                  <div className="h-2 w-full rounded-full bg-surface-tertiary overflow-hidden ring-1 ring-border-light">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-oe-blue via-blue-400 to-cyan-400 transition-all duration-150 ease-out"
                      style={{
                        width: `${Math.max(2, Math.round(geometryProgress * 100))}%`,
                      }}
                    />
                  </div>
                  <span className="text-[11px] text-content-tertiary text-center">
                    {geometryProgress >= 0.97
                      ? t('bim.loading_parsing', {
                          defaultValue:
                            'Parsing 3D geometry — for large models (>50 MB) this can take 20-60s; do not refresh',
                        })
                      : geometryProgress >= 0.95
                        ? t('bim.loading_finalising', {
                            defaultValue: 'Finalising scene…',
                          })
                        : t('bim.loading_streaming', {
                            defaultValue: 'Streaming geometry from server…',
                          })}
                  </span>
                  <span className="text-[10px] text-content-quaternary text-center mt-1">
                    {t('bim.loading_navigate_hint', {
                      defaultValue: 'You can navigate to other pages — loading will continue in the background',
                    })}
                  </span>
                </>
              ) : (
                <>
                  {/* Indeterminate bar while the element list / model meta is
                      fetching — users need motion feedback so the UI doesn't
                      feel frozen during the pre-geometry phase. */}
                  <div className="h-2 w-full rounded-full bg-surface-tertiary overflow-hidden ring-1 ring-border-light relative">
                    <div
                      className="absolute top-0 h-full w-1/3 rounded-full bg-gradient-to-r from-transparent via-oe-blue to-transparent"
                      style={{ animation: 'oeBimIndeterminate 1.4s ease-in-out infinite' }}
                    />
                  </div>
                  <span className="text-[11px] text-content-tertiary text-center">
                    {t('bim.loading_elements', {
                      defaultValue: 'Fetching element list…',
                    })}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Error overlay */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary/80 z-10">
          <div className="flex flex-col items-center gap-3 text-center px-8">
            <AlertCircle size={32} className="text-red-500" />
            <span className="text-sm text-content-secondary">{error}</span>
          </div>
        </div>
      )}

      {/* Geometry load failure (issue #113). Distinct from the
          ``error`` overlay above (element-list fetch failure) — this
          one fires after elements arrive but the GLB/DAE blob can't
          be parsed (401 from a stale token, 404 from a redeploy that
          ate the file, malformed bytes, OOM during BVH build, etc.).
          Surfaced as a non-blocking banner anchored top-center so the
          user can still pan/zoom whatever DID load (e.g. placeholder
          boxes from the text-IFC fallback). The Retry button re-runs
          the load by bumping ``geometryRetryNonce``. */}
      {geometryError && (() => {
        // Derive a status-aware headline + plain-language "What happened"
        // sentence. The backend's structured diagnostic carries `cause`
        // (422 only) and `remediation` (every error). We pick a friendly
        // top-line based on HTTP status so a 401 doesn't scare the user
        // with "Could not load 3D geometry" when the real story is "your
        // login expired — refresh".
        const diag = geometryErrorDiagnostic;
        const diagCause =
          diag && typeof (diag as { cause?: unknown }).cause === 'string'
            ? ((diag as { cause: string }).cause)
            : null;
        const diagRemediation =
          diag && typeof (diag as { remediation?: unknown }).remediation === 'string'
            ? ((diag as { remediation: string }).remediation)
            : null;
        const diagMessage =
          diag && typeof (diag as { message?: unknown }).message === 'string'
            ? ((diag as { message: string }).message)
            : null;
        const status = geometryErrorStatus;
        let headline = t('bim.geometry_load_failed', {
          defaultValue: 'Could not load 3D geometry',
        });
        let plainCause = diagCause;
        if (status === 401) {
          headline = t('bim.geometry_err_auth_title', {
            defaultValue: 'Your session expired',
          });
          plainCause = plainCause ?? t('bim.geometry_err_auth_cause', {
            defaultValue:
              'The viewer could not authenticate to the server. Refreshing the page usually fixes this.',
          });
        } else if (status === 403) {
          headline = t('bim.geometry_err_forbidden_title', {
            defaultValue: 'You don’t have access to this model',
          });
          plainCause = plainCause ?? t('bim.geometry_err_forbidden_cause', {
            defaultValue:
              'Your account does not include permission to view BIM models on this project.',
          });
        } else if (status === 404) {
          headline = t('bim.geometry_err_missing_title', {
            defaultValue: 'This model has no 3D geometry on the server',
          });
          plainCause = plainCause ?? t('bim.geometry_err_missing_cause', {
            defaultValue:
              'Either the model was uploaded but the converter produced no 3D mesh, or the file was removed.',
          });
        } else if (status === 422) {
          headline = t('bim.geometry_err_invalid_title', {
            defaultValue: 'The 3D file looks damaged or unsupported',
          });
          // `plainCause` from the backend diagnostic already covers this
          // case in plain language (HTML-page-instead-of-DAE, IFC schedule
          // instead of mesh, truncated upload, etc.).
        } else if (status && status >= 500) {
          headline = t('bim.geometry_err_server_title', {
            defaultValue: 'The server had a problem loading this model',
          });
          plainCause = plainCause ?? t('bim.geometry_err_server_cause', {
            defaultValue:
              'A backend error prevented the file from being served. This is usually temporary — try Retry.',
          });
        } else if (status === null) {
          headline = t('bim.geometry_err_network_title', {
            defaultValue: 'Could not reach the server',
          });
          plainCause = plainCause ?? t('bim.geometry_err_network_cause', {
            defaultValue:
              'The browser couldn’t connect to the backend. Check your internet connection or VPN, then click Retry.',
          });
        }
        return (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 max-w-md w-[90%]">
          <div className="rounded-lg border border-amber-300/70 dark:border-amber-700/60 bg-amber-50/95 dark:bg-amber-900/30 backdrop-blur-sm shadow-lg px-4 py-3">
            <div className="flex items-start gap-3">
              <AlertCircle size={18} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-amber-900 dark:text-amber-100">
                  {headline}
                </div>
                {plainCause && (
                  <div className="mt-1 text-[12.5px] text-amber-900 dark:text-amber-100 leading-snug">
                    {plainCause}
                  </div>
                )}
                {diagRemediation && (
                  <div className="mt-2 text-[11.5px] text-amber-800 dark:text-amber-200 leading-snug">
                    <span className="font-semibold">
                      {t('bim.geometry_try_this', { defaultValue: 'Try this' })}:
                    </span>{' '}
                    {diagRemediation}
                  </div>
                )}
                <div className="mt-1.5 text-[10.5px] text-amber-700/80 dark:text-amber-300/80 font-mono break-all">
                  {status !== null && (
                    <>
                      <span>HTTP {status}</span>
                      {(geometryErrorRequestId || diagMessage) && <span> &middot; </span>}
                    </>
                  )}
                  {geometryErrorRequestId && (
                    <>
                      <span>Request ID: {geometryErrorRequestId}</span>
                      {diagMessage && <span> &middot; </span>}
                    </>
                  )}
                  {diagMessage && <span>{diagMessage}</span>}
                </div>
                {geometryErrorDiagnostic && (
                  <details className="mt-2 text-[11px] text-amber-900/85 dark:text-amber-100/80" open>
                    <summary className="cursor-pointer select-none hover:text-amber-900 dark:hover:text-amber-100 font-medium">
                      {t('bim.geometry_diagnostic.title', {
                        defaultValue: 'File diagnostic',
                      })}
                    </summary>
                    <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-2 gap-y-0.5 rounded bg-amber-100/60 dark:bg-amber-900/40 p-2 text-[10px] font-mono">
                      {typeof geometryErrorDiagnostic.format === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.format', { defaultValue: 'Format' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.format)}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.size_bytes === 'number' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.size', { defaultValue: 'Size' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.size_bytes)} {t('common.bytes', { defaultValue: 'bytes' })}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.expected_signature === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.expected', { defaultValue: 'Expected' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.expected_signature)}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.head_hex === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.head_hex', { defaultValue: 'First bytes (hex)' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.head_hex)}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.head_ascii === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.head_ascii', { defaultValue: 'First bytes (ASCII)' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.head_ascii)}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.first_tag === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.first_tag', { defaultValue: 'First XML tag' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.first_tag)}
                          </dd>
                        </>
                      )}
                      {typeof geometryErrorDiagnostic.reason === 'string' && (
                        <>
                          <dt className="text-amber-700 dark:text-amber-300">
                            {t('bim.geometry_diagnostic.reason', { defaultValue: 'Reason' })}
                          </dt>
                          <dd className="text-amber-900 dark:text-amber-100 break-all">
                            {String(geometryErrorDiagnostic.reason)}
                          </dd>
                        </>
                      )}
                    </dl>
                  </details>
                )}
                {geometryErrorStack && (
                  <details className="mt-2 text-[11px] text-amber-900/80 dark:text-amber-100/70">
                    <summary className="cursor-pointer select-none hover:text-amber-900 dark:hover:text-amber-100">
                      {t('bim.geometry_show_diagnostic', {
                        defaultValue: 'Show diagnostic',
                      })}
                    </summary>
                    <pre className="mt-1 max-h-32 overflow-auto rounded bg-amber-100/60 dark:bg-amber-900/40 p-2 text-[10px] whitespace-pre-wrap break-all font-mono">
                      {geometryErrorStack}
                    </pre>
                  </details>
                )}
                <div className="mt-2 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      const mgr = elementMgrRef.current;
                      if (mgr) mgr.resetGeometryLoadFlag();
                      setGeometryError(null);
                      setGeometryErrorStack(null);
                      setGeometryErrorDiagnostic(null);
                      setGeometryErrorStatus(null);
                      setGeometryErrorRequestId(null);
                      setGeometryRetryNonce((n) => n + 1);
                    }}
                    className="inline-flex items-center gap-1 rounded-md border border-amber-400 dark:border-amber-700 bg-white dark:bg-amber-800/40 hover:bg-amber-100 dark:hover:bg-amber-700/60 px-2.5 py-1 text-xs font-medium text-amber-900 dark:text-amber-100 transition-colors"
                  >
                    {t('bim.geometry_retry', { defaultValue: 'Retry' })}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      // Build a one-shot, human-readable bug report block
                      // the user can paste straight into an email or
                      // GitHub issue. The Request ID is the single most
                      // important field for support to find this failure
                      // in server logs. We deliberately use a markdown-
                      // style template (not raw JSON) because most users
                      // pasting into an email expect readable text, not
                      // `{ "error": "..." }`. Privacy: no auth token, no
                      // file path, no user PII — only what backend already
                      // exposed in its 422/404/etc detail payload.
                      const lines: string[] = [];
                      lines.push('### BIM viewer error report');
                      lines.push('');
                      lines.push(
                        `- When: ${new Date().toISOString()}`,
                      );
                      if (geometryErrorRequestId) {
                        lines.push(`- Request ID: ${geometryErrorRequestId}`);
                      }
                      if (geometryErrorStatus !== null) {
                        lines.push(`- HTTP status: ${geometryErrorStatus}`);
                      }
                      if (diagMessage) {
                        lines.push(`- Backend message: ${diagMessage}`);
                      }
                      if (plainCause) {
                        lines.push(`- Likely cause: ${plainCause}`);
                      }
                      if (geometryErrorDiagnostic) {
                        const d = geometryErrorDiagnostic as Record<string, unknown>;
                        if (typeof d.format === 'string') {
                          lines.push(`- Format: ${d.format}`);
                        }
                        if (typeof d.size_bytes === 'number') {
                          lines.push(`- File size: ${d.size_bytes} bytes`);
                        }
                        if (typeof d.expected_signature === 'string') {
                          lines.push(`- Expected: ${d.expected_signature}`);
                        }
                        if (typeof d.head_hex === 'string') {
                          lines.push(`- First bytes (hex): ${d.head_hex}`);
                        }
                        if (typeof d.head_ascii === 'string') {
                          lines.push(`- First bytes (ASCII): ${d.head_ascii}`);
                        }
                        if (typeof d.first_tag === 'string' && d.first_tag) {
                          lines.push(`- First XML tag: ${d.first_tag}`);
                        }
                        if (typeof d.reason === 'string') {
                          lines.push(`- Parser reason: ${d.reason}`);
                        }
                      }
                      lines.push(`- Browser: ${navigator.userAgent}`);
                      lines.push(`- URL: ${window.location.href}`);
                      if (geometryErrorStack) {
                        lines.push('');
                        lines.push('Stack (top frames):');
                        lines.push('```');
                        lines.push(geometryErrorStack);
                        lines.push('```');
                      }
                      const blob = lines.join('\n');
                      try {
                        navigator.clipboard?.writeText(blob);
                      } catch {
                        /* clipboard blocked — silent */
                      }
                    }}
                    className="text-[11px] text-amber-700/80 dark:text-amber-300/80 hover:text-amber-900 dark:hover:text-amber-100 underline-offset-2 hover:underline"
                  >
                    {t('bim.geometry_copy_report', {
                      defaultValue: 'Copy bug report',
                    })}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setGeometryError(null);
                      setGeometryErrorStack(null);
                      setGeometryErrorDiagnostic(null);
                      setGeometryErrorStatus(null);
                      setGeometryErrorRequestId(null);
                    }}
                    className="text-[11px] text-amber-700/80 dark:text-amber-300/80 hover:text-amber-900 dark:hover:text-amber-100"
                  >
                    {t('bim.geometry_dismiss', { defaultValue: 'Dismiss' })}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        );
      })()}

      {/* Empty state */}
      {!isLoading && !error && elementCount === 0 && modelId && (
        <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <div className="flex flex-col items-center gap-2 text-center">
            <Box size={40} className="text-content-tertiary" />
            <span className="text-sm text-content-tertiary">
              {t('bim.no_elements', { defaultValue: 'No elements to display' })}
            </span>
          </div>
        </div>
      )}

      {/* Top-left toolbar — one row: camera presets on the left,
          a soft divider, then visibility toggles. Shifts right when the
          parent's filter sidebar is open so it never sits behind it. */}
      <div
        className="absolute top-3 z-20 flex items-center gap-1 rounded-lg bg-surface-primary border border-border-light shadow-sm p-1 transition-[inset-inline-start] duration-200"
        style={{ insetInlineStart: leftPanelOpen ? leftPanelWidth + 12 : 12 }}
      >
        <ToolbarButton
          icon={Home}
          label={t('bim.zoom_fit', { defaultValue: 'Fit all (F)' })}
          onClick={handleZoomToFit}
          variant="group"
        />
        <ToolbarButton
          icon={Boxes}
          label={t('bim.view_iso', { defaultValue: 'Isometric (0)' })}
          onClick={() => handleCameraPreset('iso')}
          variant="group"
        />
        <ToolbarButton
          icon={PanelTop}
          label={t('bim.view_top', { defaultValue: 'Top view (3)' })}
          onClick={() => handleCameraPreset('top')}
          variant="group"
        />
        <ToolbarButton
          icon={Square}
          label={t('bim.view_front', { defaultValue: 'Front view (1)' })}
          onClick={() => handleCameraPreset('front')}
          variant="group"
        />
        <ToolbarButton
          icon={CornerUpLeft}
          label={t('bim.view_side', { defaultValue: 'Side view (2)' })}
          onClick={() => handleCameraPreset('side')}
          variant="group"
        />
        <ToolbarButton
          icon={Maximize2}
          label={t('bim.zoom_selection', { defaultValue: 'Zoom to selection' })}
          onClick={handleZoomToSelection}
          variant="group"
        />
        <ToolbarButton
          icon={Camera}
          label={t('bim.screenshot', { defaultValue: 'Screenshot (PNG)' })}
          onClick={() => {
            void handleScreenshot();
          }}
          variant="group"
          testId="bim-screenshot-btn"
        />
        <div className="w-px h-5 bg-border-light mx-1.5" />
        <ToolbarButton
          icon={LayoutGrid}
          label={t('bim.wireframe', { defaultValue: 'Wireframe (W)' })}
          onClick={handleToggleWireframe}
          active={wireframe}
          variant="group"
        />
        <ToolbarButton
          icon={Grid3X3}
          label={
            gridVisible
              ? t('bim.hide_grid', { defaultValue: 'Hide grid (G)' })
              : t('bim.show_grid', { defaultValue: 'Show grid (G)' })
          }
          onClick={handleToggleGrid}
          active={gridVisible}
          variant="group"
        />
        <ToolbarButton
          icon={Box}
          label={
            boxesVisible
              ? t('bim.hide_boxes', { defaultValue: 'Hide placeholder boxes (B)' })
              : t('bim.show_boxes', { defaultValue: 'Show placeholder boxes (B)' })
          }
          onClick={handleToggleBoxes}
          active={boxesVisible}
          variant="group"
        />
        <div className="w-px h-5 bg-border-light mx-1.5" />
        <ToolbarButton
          icon={Ruler}
          label={t('bim.measure_toggle', { defaultValue: 'Measure distance (M)' })}
          onClick={() => setMeasureActive(!measureActive)}
          active={measureActive}
          variant="group"
        />
        <ToolbarButton
          icon={Scissors}
          label={t('bim.clip_toggle', {
            defaultValue: 'Section box / clipping plane',
          })}
          onClick={() => setClipPanelOpen(!clipPanelOpen)}
          active={clipMode !== 'none' || clipPanelOpen}
          variant="group"
          testId="bim-clip-toggle"
        />
        <ToolbarButton
          icon={EyeOffIcon}
          label={t('bim.ghost_toggle', {
            defaultValue: 'Ghost non-selected (G hold)',
          })}
          onClick={() => setGhostActive(!ghostActive)}
          active={ghostActive}
          variant="group"
          testId="bim-ghost-toggle"
        />
      </div>

      {/* BIMcollab-style additive viewer tools — Section Box / Walk /
          Measure. Anchored bottom-left, immediately to the right of the
          Site Compass ViewCube so the cube + tools form a single floating
          control cluster (per UX request 2026-05-23). Renders only once
          the scene-init effect has built the helper trio.

          Cluster math:
            - ViewCube origin: left = leftPanelOpen ? leftPanelWidth + 16 : 12
            - ViewCube width:  112 px (BIMViewCube size prop)
            - Gap to toolbar:  10 px
          → toolbar leftOffset = cube_origin + 112 + 10 */}
      {viewerToolsReady &&
        sectionBoxRef.current &&
        walkModeRef.current &&
        measureToolRef.current && (
          <ViewerToolbar
            sectionBox={sectionBoxRef.current}
            walkMode={walkModeRef.current}
            measureTool={measureToolRef.current}
            position="bottom-left"
            leftOffset={(leftPanelOpen ? leftPanelWidth + 16 : 12) + 112 + 10}
            onBeforeToolEnable={(next) => {
              // Walk mode CANNOT coexist with OrbitControls — the helper's
              // own guard throws if controls.enabled is still true. We
              // disable them here BEFORE the toolbar calls walkMode.enable(),
              // and re-enable them on the matching `onAfterToolDisable`.
              if (next === 'walk') {
                const ctrl = sceneRef.current?.controls;
                if (ctrl) ctrl.enabled = false;
              }
              return true;
            }}
            onAfterToolDisable={(prev) => {
              if (prev === 'walk') {
                const ctrl = sceneRef.current?.controls;
                if (ctrl) ctrl.enabled = true;
              }
            }}
            onSectionAction={(action) => {
              // Wire section actions to the live selection + element
              // manager when available. The helper itself enforces the
              // INWARD-facing planes; we just feed it the right AABB.
              const sb = sectionBoxRef.current;
              const elementMgr = elementMgrRef.current;
              const selectionMgr = selectionMgrRef.current;
              if (!sb) return;
              if (action === 'reset') {
                sb.disable();
                return;
              }
              if (action === 'fit_selection' && elementMgr && selectionMgr) {
                const ids = selectionMgr.getSelectedIds();
                const meshes = ids
                  .map((id) => elementMgr.getMesh(id))
                  .filter((m): m is NonNullable<typeof m> => m != null);
                if (meshes.length > 0) {
                  sb.setBoundsToSelection(meshes);
                  sb.enable();
                }
                return;
              }
              if (action === 'fit_all' && sceneRef.current) {
                const scene = sceneRef.current.scene;
                const allMeshes: Array<{ isObject3D: true } & object> = [];
                scene.traverse((obj) => {
                  // Re-use the helper's own filter: anything not the
                  // overlay + meshes only.
                  if (
                    (obj as { isMesh?: boolean }).isMesh &&
                    !obj.userData?.isSectionBoxOverlay &&
                    !obj.userData?.isMeasureLine &&
                    !obj.userData?.isMeasureMarker &&
                    !obj.userData?.isClipCap
                  ) {
                    allMeshes.push(obj as unknown as { isObject3D: true } & object);
                  }
                });
                if (allMeshes.length > 0) {
                  sb.setBoundsToSelection(
                    allMeshes as unknown as import('three').Object3D[],
                  );
                  sb.enable();
                }
              }
            }}
          />
        )}

      {/* Walk mode on-screen hint — only visible while the pointer is
          actually locked (i.e. WASD/mouse actively control the camera).
          Anchored top-center so the user notices it; auto-disappears when
          the browser releases pointer lock. */}
      {walkLocked && (
        <div
          className="absolute top-3 start-1/2 -translate-x-1/2 z-30 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/85 backdrop-blur text-white text-[11px] font-medium shadow-lg pointer-events-none select-none"
          data-testid="bim-walk-hint"
          role="status"
          aria-live="polite"
        >
          <Move3d size={12} className="text-sky-300 shrink-0" />
          <span>
            {t('viewerTools.walk_hint_overlay', {
              defaultValue:
                'Mouse: look · WASD: move · Space/Q: up/down · Shift: sprint · Esc: exit',
            })}
          </span>
        </div>
      )}

      {/* Section / clipping-plane control popover. Anchored under the
          toolbar; mutually-exclusive box vs plane modes with live
          sliders. */}
      {clipPanelOpen && (
        <ClipControls
          mode={clipMode}
          onModeChange={setClipMode}
          box={clipBox}
          onBoxChange={(patch) => setClipBox((b) => ({ ...b, ...patch }))}
          plane={clipPlane}
          onPlaneChange={(patch) => setClipPlane((p) => ({ ...p, ...patch }))}
          onReset={() => {
            setClipMode('none');
            setClipBox({
              minX: 0,
              maxX: 1,
              minY: 0,
              maxY: 1,
              minZ: 0,
              maxZ: 1,
            });
            setClipPlane({ axis: 'y', offset: 0.5, flipped: false });
          }}
          onClose={() => setClipPanelOpen(false)}
          leftOffset={leftPanelOpen ? leftPanelWidth + 12 : 12}
        />
      )}
      {/* Measure hint shown while the tool is active. Includes a Clear
          affordance so users don't have to hunt for the right-panel Tools
          tab to drop stale measurements. */}
      {measureActive && (
        <div
          className="absolute top-14 start-1/2 -translate-x-1/2 z-20 flex flex-col items-center gap-1.5 px-3 py-2 rounded-md bg-surface-primary border border-oe-blue/40 shadow-sm text-[11px] text-content-secondary"
          data-testid="bim-measure-hint"
        >
          <div className="flex items-center gap-2">
            {/* Measure-kind segmented control. */}
            <div
              className="inline-flex rounded-md border border-border-light overflow-hidden"
              role="group"
              aria-label={t('bim.measure_kind_aria', {
                defaultValue: 'Measurement type',
              })}
            >
              {([
                ['distance', Ruler, t('bim.measure_distance', { defaultValue: 'Distance' })] as const,
                ['area', PencilRuler, t('bim.measure_area', { defaultValue: 'Area' })] as const,
                ['angle', Triangle, t('bim.measure_angle', { defaultValue: 'Angle' })] as const,
              ]).map(([k, KIcon, kLabel]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setMeasureKind(k)}
                  aria-pressed={measureKind === k}
                  data-testid={`measure-kind-${k}`}
                  className={clsx(
                    'inline-flex items-center gap-1 px-2 py-1 text-[10px] font-medium transition-colors',
                    measureKind === k
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                  )}
                >
                  <KIcon size={11} />
                  {kLabel}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setMeasureSnap(!measureSnap)}
              aria-pressed={measureSnap}
              data-testid="measure-snap-toggle"
              title={t('bim.measure_snap_hint', {
                defaultValue: 'Snap clicks to the nearest geometry vertex',
              })}
              className={clsx(
                'inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-colors',
                measureSnap
                  ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/40'
                  : 'bg-surface-secondary text-content-tertiary border-border-light hover:bg-surface-tertiary',
              )}
            >
              <Move3d size={11} />
              {t('bim.measure_snap', { defaultValue: 'Snap' })}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Ruler size={12} className="text-oe-blue shrink-0" />
            <span>
              {measureKind === 'area'
                ? t('bim.measure_hint_area', {
                    defaultValue:
                      'Click ≥3 points, then double-click or Enter to close. {{count}} saved.',
                    count: measureCount,
                  })
                : measureKind === 'angle'
                  ? t('bim.measure_hint_angle', {
                      defaultValue:
                        'Click 3 points — the angle is at the middle point. {{count}} saved.',
                      count: measureCount,
                    })
                  : t('bim.measure_hint', {
                      defaultValue:
                        'Click two points to measure. Esc to cancel. {{count}} saved.',
                      count: measureCount,
                    })}
            </span>
            {measureCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  measureMgrRef.current?.clearAll();
                  useBIMMeasurementsStore.getState().clear();
                }}
                className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-oe-blue hover:bg-oe-blue/10 transition-colors"
              >
                {t('bim.measure_clear', { defaultValue: 'Clear' })}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Selection toolbar — appears above the viewport when 1+ elements
          are selected.  Gives quick access to BOQ/Hide/Isolate/Clear without
          right-clicking. */}
      {selectionCount > 0 && (
        <div className="absolute bottom-3 start-1/2 -translate-x-1/2 z-30 flex items-center gap-2 rounded-lg bg-surface-primary border border-oe-blue/40 shadow-md px-3 py-1.5">
          <span className="text-xs font-semibold text-content-primary whitespace-nowrap">
            {selectionCount === 1
              ? t('bim.sel_one', {
                  defaultValue: '1 selected',
                })
              : t('bim.sel_n', {
                  defaultValue: '{{count}} selected',
                  count: selectionCount,
                })}
          </span>
          {selectionSummary && (
            <span className="text-[10px] text-content-tertiary truncate max-w-[200px]">
              ({selectionSummary})
            </span>
          )}
          <div className="w-px h-4 bg-border-light" />
          {onAddToBOQ && (
            <button
              type="button"
              onClick={() => {
                const selected = selectionMgrRef.current?.getSelectedElements() ?? [];
                if (selected.length > 0) onAddToBOQ(selected);
              }}
              className="px-2 py-0.5 rounded text-[11px] font-medium text-white bg-oe-blue hover:bg-oe-blue-dark transition-colors"
            >
              {t('bim.sel_boq', { defaultValue: 'BOQ' })}
            </button>
          )}
          <button
            type="button"
            onClick={handleSelectionHide}
            className="px-2 py-0.5 rounded text-[11px] font-medium text-content-secondary bg-surface-secondary hover:bg-surface-tertiary transition-colors"
            title={t('bim.sel_hide', { defaultValue: 'Hide selected (H)' })}
          >
            {t('bim.hide', { defaultValue: 'Hide' })}
          </button>
          <button
            type="button"
            onClick={handleSelectionIsolate}
            className="px-2 py-0.5 rounded text-[11px] font-medium text-content-secondary bg-surface-secondary hover:bg-surface-tertiary transition-colors"
            title={t('bim.sel_isolate', { defaultValue: 'Isolate selected (I)' })}
          >
            {t('bim.isolate', { defaultValue: 'Isolate' })}
          </button>
          <button
            type="button"
            onClick={handleClearSelection}
            className="flex items-center justify-center h-5 w-5 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            title={t('bim.sel_clear', { defaultValue: 'Clear selection (Esc)' })}
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* 4D schedule scrubber — bottom-center, visible only in 4d_schedule
          mode AND when the project has a usable schedule.  The hook
          returns `isAvailable: false` for unscheduled projects so the
          viewer stays clean. */}
      {colorByMode === '4d_schedule' && fourD.isAvailable && (
        <TimelineScrubber
          startMs={fourD.startMs}
          endMs={fourD.endMs}
          currentMs={fourD.currentMs}
          onChange={fourD.setCurrentMs}
          playing={fourD.playing}
          onPlayToggle={fourD.togglePlay}
          speed={fourD.speed}
          onSpeedChange={fourD.setSpeed}
          activeActivity={fourD.activeActivityName}
        />
      )}

      {/* 5D cost legend — bottom-right, visible only in 5d_cost mode. Shows
          the rate range linked to the currently-coloured model plus a
          gradient strip so users can read the colours as cost magnitudes.
          Rendered above the hidden-elements badge by using a higher bottom
          offset so the two never collide. */}
      {colorByMode === '5d_cost' && (
        <div
          className="absolute bottom-3 end-3 z-20 flex flex-col items-end gap-1 rounded-lg bg-surface-primary border border-border-light shadow-sm px-3 py-2 min-w-[180px]"
          data-testid="bim-5d-legend"
        >
          <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
            {t('bim.5d_legend_title', { defaultValue: 'Unit rate' })}
          </span>
          <div
            className="h-2 w-full rounded-full"
            style={{
              background: `linear-gradient(to right, ${DEFAULT_5D_GRADIENT.map(
                (s) => `${s.hex} ${Math.round(s.t * 100)}%`,
              ).join(', ')})`,
            }}
          />
          <div className="flex items-center justify-between w-full text-[10px] text-content-secondary tabular-nums">
            <span>
              {rateStats.linkedCount > 0
                ? rateStats.min.toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })
                : '—'}
            </span>
            <span className="text-content-tertiary">
              {t('bim.5d_legend_unit', { defaultValue: '/ unit' })}
            </span>
            <span>
              {rateStats.linkedCount > 0
                ? rateStats.max.toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })
                : '—'}
            </span>
          </div>
          <div className="flex items-center gap-1.5 w-full justify-between text-[10px] text-content-tertiary">
            <span>
              {t('bim.5d_legend_linked', {
                defaultValue: '{{n}} linked',
                n: rateStats.linkedCount,
              })}
            </span>
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: '#9ca3af', opacity: NO_LINK_OPACITY }}
              />
              {t('bim.5d_legend_no_link', { defaultValue: 'no link' })}
            </span>
          </div>
        </div>
      )}

      {/* Color-mode legend (storey / category / validation / coverage).
          Matches the active palette one-for-one so the user can decode the
          3D scene at a glance. The 5D-cost gradient legend is rendered
          separately above; here we handle the discrete-palette modes. */}
      {(colorByMode === 'storey' ||
        colorByMode === 'type' ||
        colorByMode === 'validation' ||
        colorByMode === 'boq_coverage' ||
        colorByMode === 'document_coverage') &&
        elements && elements.length > 0 && (
          <ColorModeLegend mode={colorByMode} elements={elements} />
        )}

      {/* Hidden elements badge + Show all button — bottom-right corner */}
      {(hiddenIds.size > 0 || isIsolated) && (
        <div className="absolute bottom-3 end-3 z-20 flex items-center gap-1.5">
          {hiddenIds.size > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-surface-primary border border-border-light shadow-sm text-content-secondary">
              <EyeOffIcon size={11} />
              {t('bim.hidden_count', {
                defaultValue: '{{count}} hidden',
                count: hiddenIds.size,
              })}
            </span>
          )}
          {isIsolated && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-oe-blue/10 border border-oe-blue/30 shadow-sm text-oe-blue">
              <Eye size={11} />
              {t('bim.isolated', { defaultValue: 'Isolated' })}
            </span>
          )}
          <button
            type="button"
            onClick={handleShowAll}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-surface-primary border border-border-light shadow-sm text-content-secondary hover:bg-surface-secondary transition-colors"
          >
            <Eye size={11} />
            {t('bim.show_all', { defaultValue: 'Show all' })}
          </button>
        </div>
      )}

      {/* Health stats banner — top-right, multi-pill clickable counts.
          The pills are smart filters: clicking "Errors" narrows the
          3D viewport to elements with validation_status='error', etc.
          The parent applies the predicate via onSmartFilter.

          The container is ``pointer-events-none`` so clicks land on
          whatever sits beneath the banner (right-panel tabs, model
          selector, etc.). Each individual pill flips back to
          ``pointer-events-auto`` so its own click / hover tooltip
          still works. Verified against the v2.7.5 Match-tab regression
          where banner pills were intercepting clicks on the 5th tab. */}
      {elementCount > 0 && (
        <div className="absolute top-3 end-3 z-20 flex items-center gap-1.5 flex-wrap justify-end max-w-[calc(100%-400px)] pointer-events-none">
          {/* Total elements pill — not clickable, just informational */}
          <span
            className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-surface-primary text-content-secondary border border-border-light shadow-sm"
            title={t('bim.element_count_title', {
              defaultValue: '{{count}} elements loaded in this model',
              count: elementCount,
            })}
          >
            <Box size={11} />
            {elementCount.toLocaleString()}
          </span>

          {/* BOQ-linked count — clickable, narrows to linked-to-BOQ elements */}
          {healthStats.linkedToBoq > 0 && (
            <button
              type="button"
              onClick={() => onSmartFilter?.('unlinked_boq')}
              className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-sm hover:bg-emerald-100"
              title={t('bim.linked_count_title', {
                defaultValue:
                  '{{linked}} of {{total}} linked to BOQ — click to show ONLY the unlinked',
                linked: healthStats.linkedToBoq,
                total: elementCount,
              })}
            >
              <Link2 size={11} />
              {healthStats.linkedToBoq.toLocaleString()}/{elementCount.toLocaleString()} BOQ
            </button>
          )}

          {/* Validation errors — clickable, narrows to errors only */}
          {healthStats.errors > 0 && (
            <button
              type="button"
              onClick={() => onSmartFilter?.('errors')}
              className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200 shadow-sm hover:bg-rose-100"
              title={t('bim.errors_count_title', {
                defaultValue: '{{count}} elements with validation errors — click to filter',
                count: healthStats.errors,
              })}
            >
              <AlertCircle size={11} />
              {healthStats.errors.toLocaleString()} errors
            </button>
          )}

          {/* Validation warnings */}
          {healthStats.warnings > 0 && (
            <button
              type="button"
              onClick={() => onSmartFilter?.('warnings')}
              className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200 shadow-sm hover:bg-amber-100"
              title={t('bim.warnings_count_title', {
                defaultValue: '{{count}} elements with validation warnings — click to filter',
                count: healthStats.warnings,
              })}
            >
              <AlertCircle size={11} />
              {healthStats.warnings.toLocaleString()} warn
            </button>
          )}

          {/* Open tasks */}
          {healthStats.hasTasks > 0 && (
            <button
              type="button"
              onClick={() => onSmartFilter?.('has_tasks')}
              className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200 shadow-sm hover:bg-amber-100"
              title={t('bim.tasks_count_title', {
                defaultValue: '{{count}} elements have linked tasks — click to filter',
                count: healthStats.hasTasks,
              })}
            >
              <CheckSquare size={11} />
              {healthStats.hasTasks.toLocaleString()}
            </button>
          )}

          {/* Linked documents */}
          {healthStats.hasDocs > 0 && (
            <button
              type="button"
              onClick={() => onSmartFilter?.('has_docs')}
              className="pointer-events-auto inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet-50 text-violet-700 border border-violet-200 shadow-sm hover:bg-violet-100"
              title={t('bim.docs_count_title', {
                defaultValue: '{{count}} elements have linked documents — click to filter',
                count: healthStats.hasDocs,
              })}
            >
              <FileText size={11} />
              {healthStats.hasDocs.toLocaleString()}
            </button>
          )}
        </div>
      )}

      {/* Hover tooltip — follows the cursor when hovering over an element */}
      {hoveredElement && tooltipPos && !selectedElement && (
        <div
          className="absolute z-30 pointer-events-none px-2.5 py-1.5 rounded-md bg-gray-900/90 text-white text-[11px] leading-tight shadow-lg backdrop-blur-sm max-w-[220px]"
          style={{ left: tooltipPos.x, top: tooltipPos.y }}
        >
          <div className="font-semibold truncate">
            {hoveredElement.name || hoveredElement.element_type}
          </div>
          <div className="text-gray-300 text-[10px]">
            {hoveredElement.element_type}
            {hoveredElement.storey && (
              <span className="ml-1.5 text-gray-400">{hoveredElement.storey}</span>
            )}
          </div>
        </div>
      )}

      {/* Keyboard shortcut overlay — toggled by pressing ? */}
      {showShortcuts && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-lg">
          <div className="bg-surface-primary rounded-xl shadow-2xl border border-border-light p-6 w-80">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-content-primary">
                {t('bim.keyboard_shortcuts', { defaultValue: 'Keyboard Shortcuts' })}
              </h3>
              <button
                onClick={() => setShowShortcuts(false)}
                className="text-content-tertiary hover:text-content-primary text-xs"
              >
                Esc
              </button>
            </div>
            <div className="space-y-2 text-xs">
              {[
                ['F', 'Fit all elements'],
                ['W', 'Toggle wireframe'],
                ['G', 'Toggle grid'],
                ['H', 'Hide selected'],
                ['I', 'Isolate / exit isolation'],
                ['1', 'Front view'],
                ['2', 'Side view'],
                ['3', 'Top view'],
                ['0', 'Isometric view'],
                ['Esc', 'Deselect / close panel'],
                ['Click', 'Select element'],
                ['Ctrl+Click', 'Multi-select (toggle)'],
                ['Shift+Click', 'Add to selection'],
                ['DblClick', 'Isolate element'],
                ['DblClick empty', 'Exit isolation'],
                ['Right-click', 'Context menu'],
                ['?', 'Toggle this overlay'],
              ].map(([key, desc]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-content-secondary">{desc}</span>
                  <kbd className="px-1.5 py-0.5 bg-surface-secondary border border-border-light rounded text-[10px] font-mono text-content-primary min-w-[28px] text-center">
                    {key}
                  </kbd>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Summary panel — reactive to active scope:
            * no selection + no filter → full model
            * filter active            → filtered subset
            * 2+ elements selected     → selection summary
          A single selected element still shows the Properties panel
          (handled above). */}
      {summaryPanelOpen && (!selectedElement || (selectedElementIds && selectedElementIds.length > 1)) && modelSummary && elementCount > 0 && (
        <div className="absolute top-12 end-3 w-72 bg-surface-primary/95 backdrop-blur-sm border border-border-light rounded-lg shadow-lg z-20 max-h-[calc(100%-6rem)] overflow-y-auto">
          <div className="px-4 py-3 border-b border-border-light">
            <div className="flex items-center gap-2">
              {modelSummary.scope === 'selection' ? (
                <CheckSquare size={16} className="text-oe-blue shrink-0" />
              ) : modelSummary.scope === 'filtered' ? (
                <Tag size={16} className="text-oe-blue shrink-0" />
              ) : (
                <LayoutGrid size={16} className="text-oe-blue shrink-0" />
              )}
              <h3 className="text-sm font-bold text-content-primary flex-1">
                {modelSummary.scope === 'selection'
                  ? t('bim.selection_summary', { defaultValue: 'Selection summary' })
                  : modelSummary.scope === 'filtered'
                    ? t('bim.filtered_summary', { defaultValue: 'Filtered summary' })
                    : t('bim.model_summary', { defaultValue: 'Model summary' })}
              </h3>
              <button
                type="button"
                onClick={() => setSummaryPanelOpen(false)}
                aria-label={t('bim.summary_close', { defaultValue: 'Hide summary' })}
                title={t('bim.summary_close', { defaultValue: 'Hide summary' })}
                className="shrink-0 p-1 rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
                data-testid="bim-summary-close"
              >
                <X size={14} />
              </button>
            </div>
            <div className="mt-1.5 flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center rounded-md bg-oe-blue/10 px-2 py-0.5 text-xs font-semibold text-oe-blue tabular-nums">
                {modelSummary.shown.toLocaleString()}
              </span>
              <span className="text-xs text-content-tertiary">
                {t('bim.model_total_elements_label', { defaultValue: 'elements' })}
              </span>
              {modelSummary.scope !== 'all' && modelSummary.total !== modelSummary.shown && (
                <span className="text-[10px] text-content-quaternary tabular-nums">
                  {t('bim.of_total', { defaultValue: 'of {{total}}', total: modelSummary.total.toLocaleString() })}
                </span>
              )}
            </div>
          </div>
          <div className="px-4 py-3 space-y-4">
            {/* Category breakdown — inline bar acts as the row background,
                no stripy half-filled progress track. Each row shows the
                share visually via a tinted fill that stretches from the
                left, with category name and count overlaid. */}
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">
                {t('bim.by_category', { defaultValue: 'By category' })}
              </h4>
              <div className="space-y-0.5 max-h-48 overflow-y-auto -mx-1 px-1">
                {modelSummary.categories.slice(0, 15).map(([cat, count]) => {
                  const maxCount = modelSummary.categories[0]?.[1] ?? 1;
                  const pct = Math.max(4, (count / maxCount) * 100);
                  return (
                    <div
                      key={cat}
                      className="relative flex items-center justify-between rounded-md px-2 py-1 overflow-hidden"
                    >
                      <div
                        aria-hidden="true"
                        className="absolute inset-y-0 left-0 bg-oe-blue/10 rounded-md pointer-events-none"
                        style={{ width: `${pct}%` }}
                      />
                      <span className="relative text-xs text-content-secondary truncate mr-2 font-medium">{cat}</span>
                      <span className="relative text-[11px] font-semibold text-content-primary tabular-nums shrink-0">
                        {count.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
                {modelSummary.categories.length > 15 && (
                  <div className="text-[11px] text-content-quaternary italic pt-0.5 pl-2">
                    + {modelSummary.categories.length - 15} {t('common.more', { defaultValue: 'more' })}
                  </div>
                )}
              </div>
            </div>
            {/* Storey breakdown — same row-bg style for visual rhythm */}
            {modelSummary.storeys.length > 1 && (
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">
                  {t('bim.by_storey', { defaultValue: 'By storey' })}
                </h4>
                <div className="space-y-0.5 max-h-36 overflow-y-auto -mx-1 px-1">
                  {(() => {
                    const maxS = modelSummary.storeys[0]?.[1] ?? 1;
                    return modelSummary.storeys.map(([st, count]) => {
                      const pct = Math.max(4, (count / maxS) * 100);
                      return (
                        <div
                          key={st}
                          className="relative flex items-center justify-between rounded-md px-2 py-1 overflow-hidden"
                        >
                          <div
                            aria-hidden="true"
                            className="absolute inset-y-0 left-0 bg-emerald-500/10 rounded-md pointer-events-none"
                            style={{ width: `${pct}%` }}
                          />
                          <span className="relative text-xs text-content-secondary truncate mr-2">{st}</span>
                          <span className="relative text-[11px] font-semibold text-content-primary tabular-nums shrink-0">
                            {count.toLocaleString()}
                          </span>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            )}
            {/* Aggregate quantities */}
            {(modelSummary.totalVolume > 0 || modelSummary.totalArea > 0 || modelSummary.totalLength > 0) && (
              <div>
                <h4 className="text-xs font-bold text-content-primary mb-2">
                  {t('bim.total_quantities', { defaultValue: 'Total quantities' })}
                </h4>
                <div className="grid grid-cols-1 gap-1.5">
                  {modelSummary.totalVolume > 0 && (
                    <div className="flex items-center justify-between rounded-md bg-surface-secondary px-2.5 py-1.5">
                      <span className="text-xs font-medium text-content-secondary">Volume</span>
                      <span className="text-xs font-semibold text-content-primary tabular-nums">
                        {modelSummary.totalVolume.toLocaleString(undefined, { maximumFractionDigits: 1 })} m&sup3;
                      </span>
                    </div>
                  )}
                  {modelSummary.totalArea > 0 && (
                    <div className="flex items-center justify-between rounded-md bg-surface-secondary px-2.5 py-1.5">
                      <span className="text-xs font-medium text-content-secondary">Area</span>
                      <span className="text-xs font-semibold text-content-primary tabular-nums">
                        {modelSummary.totalArea.toLocaleString(undefined, { maximumFractionDigits: 1 })} m&sup2;
                      </span>
                    </div>
                  )}
                  {modelSummary.totalLength > 0 && (
                    <div className="flex items-center justify-between rounded-md bg-surface-secondary px-2.5 py-1.5">
                      <span className="text-xs font-medium text-content-secondary">Length</span>
                      <span className="text-xs font-semibold text-content-primary tabular-nums">
                        {modelSummary.totalLength.toLocaleString(undefined, { maximumFractionDigits: 1 })} m
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
            {/* Deep aggregations — any narrowed scope (selection,
                filtered, isolated). Each numeric key is rolled up with
                the rule that actually means something for it: SUM for
                additive totals, AVG (with min/max) for per-element
                dimensions, DISTINCT for categorical values. The
                section title adapts so the user knows whether they're
                seeing totals for "what I picked" vs "what I isolated"
                vs "what the filter narrowed to". */}
            {modelSummary.aggregations.length > 0 && (
              <div className="pt-2 border-t border-border-light">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-content-tertiary mb-2">
                  {modelSummary.scope === 'selection'
                    ? t('bim.group_quantities_selection', {
                        defaultValue: 'Selection quantities',
                      })
                    : t('bim.group_quantities_filtered', {
                        defaultValue: 'Quantities for visible group',
                      })}
                </h4>
                <div className="space-y-1">
                  {modelSummary.aggregations.map((a) => {
                    const fmtNum = (n: number) =>
                      Number.isInteger(n)
                        ? n.toLocaleString()
                        : n.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 4,
                          });
                    if (a.mode === 'sum') {
                      return (
                        <div
                          key={a.key}
                          className="flex items-baseline justify-between gap-2 rounded-md bg-emerald-50/60 dark:bg-emerald-950/20 px-2 py-1"
                          title={t('bim.agg_sum_tooltip', {
                            defaultValue: 'Σ across {{count}} elements',
                            count: a.count,
                          })}
                        >
                          <div className="flex items-center gap-1 min-w-0">
                            <span
                              className="text-[9px] font-bold uppercase text-emerald-600/90 tracking-wider shrink-0"
                              aria-hidden
                            >
                              Σ
                            </span>
                            <span className="text-[11px] text-content-secondary truncate">
                              {a.label}
                            </span>
                          </div>
                          <div className="flex items-baseline gap-1 shrink-0">
                            <span className="text-[12px] font-semibold text-content-primary tabular-nums">
                              {fmtNum(a.sum)}
                            </span>
                            {a.unit && (
                              <span className="text-[9px] text-content-quaternary font-mono">
                                {a.unit}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    }
                    if (a.mode === 'avg') {
                      const sameMinMax = Math.abs(a.max - a.min) < 0.0001;
                      return (
                        <div
                          key={a.key}
                          className="rounded-md bg-blue-50/50 dark:bg-blue-950/20 px-2 py-1"
                          title={t('bim.agg_avg_tooltip', {
                            defaultValue:
                              'Per-element value — averaged across {{count}} elements',
                            count: a.count,
                          })}
                        >
                          <div className="flex items-baseline justify-between gap-2">
                            <div className="flex items-center gap-1 min-w-0">
                              <span
                                className="text-[9px] font-bold uppercase text-blue-600/90 tracking-wider shrink-0"
                                aria-hidden
                              >
                                ⌀
                              </span>
                              <span className="text-[11px] text-content-secondary truncate">
                                {a.label}
                              </span>
                            </div>
                            <div className="flex items-baseline gap-1 shrink-0">
                              <span className="text-[12px] font-semibold text-content-primary tabular-nums">
                                {fmtNum(a.avg)}
                              </span>
                              {a.unit && (
                                <span className="text-[9px] text-content-quaternary font-mono">
                                  {a.unit}
                                </span>
                              )}
                            </div>
                          </div>
                          {!sameMinMax && (
                            <div className="flex items-center justify-end gap-2 mt-0.5 text-[9px] text-content-quaternary tabular-nums">
                              <span>
                                {t('bim.agg_min', { defaultValue: 'min' })}{' '}
                                {fmtNum(a.min)}
                              </span>
                              <span>·</span>
                              <span>
                                {t('bim.agg_max', { defaultValue: 'max' })}{' '}
                                {fmtNum(a.max)}
                              </span>
                              <span>·</span>
                              <span>
                                {t('bim.agg_uniq', {
                                  defaultValue: '{{n}} uniq.',
                                  n: a.uniqueValues.length,
                                })}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    }
                    // DISTINCT — show up to 5 unique values inline as
                    // chips; collapse the rest behind "+N more".
                    const cap = 5;
                    const head = a.uniqueValues.slice(0, cap);
                    const rest = a.uniqueValues.length - head.length;
                    return (
                      <div
                        key={a.key}
                        className="rounded-md bg-sky-50/40 dark:bg-sky-950/20 px-2 py-1"
                        title={t('bim.agg_distinct_tooltip', {
                          defaultValue:
                            'Per-element value — listing the {{n}} unique value(s) seen',
                          n: a.uniqueValues.length,
                        })}
                      >
                        <div className="flex items-center gap-1 mb-0.5">
                          <span className="text-[11px] text-content-secondary truncate flex-1">
                            {a.label}
                          </span>
                          <span className="text-[9px] text-sky-600/90 font-bold uppercase tracking-wider shrink-0">
                            {a.uniqueValues.length === 1
                              ? '='
                              : t('bim.agg_distinct_label', {
                                  defaultValue: '{{n}} values',
                                  n: a.uniqueValues.length,
                                })}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 flex-wrap">
                          {head.map((v) => (
                            <span
                              key={v}
                              className="inline-flex items-baseline gap-0.5 px-1.5 py-0.5 rounded border border-border-light bg-surface-secondary text-[10px] tabular-nums font-mono text-content-primary"
                            >
                              {fmtNum(v)}
                              {a.unit && (
                                <span className="text-[8px] text-content-quaternary">
                                  {a.unit}
                                </span>
                              )}
                            </span>
                          ))}
                          {rest > 0 && (
                            <span className="text-[10px] text-content-quaternary italic">
                              + {rest}{' '}
                              {t('common.more', { defaultValue: 'more' })}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {/* Keyboard shortcuts hint */}
            <div className="pt-2 border-t border-border-light">
              <h4 className="text-[10px] font-semibold text-content-quaternary uppercase tracking-wider mb-1">
                {t('bim.shortcuts', { defaultValue: 'Shortcuts' })}
              </h4>
              <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] text-content-tertiary">
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">F</kbd> Fit all</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">W</kbd> Wireframe</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">G</kbd> Grid</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">H</kbd> Hide</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">I</kbd> Isolate</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">Esc</kbd> Deselect</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">1</kbd> Front</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">2</kbd> Side</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">3</kbd> Top</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">0</kbd> Iso</span>
                <span><kbd className="px-1 py-0.5 bg-surface-secondary rounded text-[9px] font-mono">?</kbd> All shortcuts</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Properties panel (when EXACTLY ONE element is selected) — tabbed
          layout. When 2+ elements are selected the Selection summary
          panel above takes priority at the same anchor position; showing
          both would visually stack them on top of each other. The
          summary aggregates the multi-pick, which is what the user
          actually wants in that case. */}
      {selectedElement && (!selectedElementIds || selectedElementIds.length <= 1) && (
        <div data-testid="bim-properties-panel" className="absolute top-12 end-3 w-72 bg-surface-primary/95 backdrop-blur-sm border border-border-light rounded-lg shadow-lg z-20 max-h-[calc(100%-6rem)] flex flex-col">
          <div className="p-3 border-b border-border-light shrink-0">
            {(() => {
              // Is the element an "Unmatched" stub (mesh has no BIMElement
              // row yet — Parquet round-trip will fill in the real values)?
              // While loading, we show neutral skeleton bars instead of the
              // literal "Unmatched" placeholder — otherwise clicking any
              // stub flashes "Unmatched" for a frame before the real name
              // arrives, which looks like a bug.
              const isStub = selectedElement.element_type === 'Unmatched';
              const stubLoading = isStub && !parquetProps && parquetLoading;

              const rawTitle = isStub && parquetProps
                ? ((parquetProps['type name'] ?? parquetProps.type_name ?? parquetProps.name ?? selectedElement.name) as string)
                : ((selectedElement.properties as Record<string, unknown>)?.type_name as string
                    || selectedElement.name
                    || (isStub ? '' : selectedElement.element_type)
                    || selectedElement.id);

              const rawCategory = isStub && parquetProps
                ? String(parquetProps.category ?? '')
                : (isStub ? '' : selectedElement.element_type);
              const prettyCategory = rawCategory
                ? rawCategory.replace(/^OST_/, '').replace(/([a-z])([A-Z])/g, '$1 $2')
                : '';

              // Key the real-content block on the resolved title so a new
              // element or a stub resolving from skeleton to full data
              // re-triggers the 200ms fade-in — no pop-in flicker.
              const fadeKey = stubLoading ? '__skeleton__' : `${rawTitle}|${prettyCategory}`;

              return (
                <div key={fadeKey} className="animate-fade-in">
                  <div className="flex items-center justify-between mb-0.5">
                    {stubLoading ? (
                      <div className="h-4 flex-1 mr-2 rounded bg-surface-secondary animate-pulse" />
                    ) : (
                      <h3 className="text-sm font-semibold text-content-primary truncate">{rawTitle}</h3>
                    )}
                    <button
                      onClick={handleCloseProperties}
                      className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary transition-colors"
                      aria-label={t('common.close', { defaultValue: 'Close' })}
                    >
                      <span className="text-xs font-bold">&times;</span>
                    </button>
                  </div>
                  {stubLoading ? (
                    <div className="h-2.5 w-20 rounded bg-surface-secondary animate-pulse mb-0.5" />
                  ) : prettyCategory ? (
                    <p className="text-[10px] text-content-tertiary mb-0.5">{prettyCategory}</p>
                  ) : null}
                </div>
              );
            })()}
            {/* Element ID(s) — clickable to copy */}
            <button
              type="button"
              onClick={() => {
                const ids = (selectedElementIds && selectedElementIds.length > 1)
                  ? selectedElementIds.map((eid) => {
                      const el = elementMgrRef.current?.getElementData(eid);
                      return el?.mesh_ref || el?.stable_id || eid;
                    }).join(', ')
                  : selectedElement.mesh_ref || selectedElement.stable_id || selectedElement.id;
                navigator.clipboard.writeText(ids);
              }}
              className="flex items-center gap-1 text-[10px] text-content-tertiary hover:text-oe-blue transition-colors group"
              title={t('bim.copy_id', { defaultValue: 'Click to copy ID' })}
            >
              <span className="font-mono truncate max-w-[220px]">
                {(selectedElementIds && selectedElementIds.length > 1)
                  ? selectedElementIds.map((eid) => {
                      const el = elementMgrRef.current?.getElementData(eid);
                      return el?.mesh_ref || eid.slice(0, 8);
                    }).join(', ')
                  : `ID: ${selectedElement.mesh_ref || selectedElement.stable_id || selectedElement.id}`}
              </span>
              <svg className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
          </div>

          {/* Quick-action bar — always visible, not buried in a tab */}
          {(onAddToBOQ || onCreateTask || onLinkDocument || onLinkActivity || onLinkRequirement) && (
            <div className="px-3 py-1.5 border-b border-border-light shrink-0 flex flex-wrap gap-1">
              {onAddToBOQ && (
                <button
                  type="button"
                  onClick={() => onAddToBOQ([selectedElement])}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-oe-blue/10 text-oe-blue hover:bg-oe-blue/20 border border-oe-blue/20 transition-colors"
                >
                  <Plus size={10} />
                  {t('bim.quick_boq', { defaultValue: 'BOQ' })}
                </button>
              )}
              {onCreateTask && (
                <button
                  type="button"
                  onClick={() => onCreateTask(selectedElement)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-amber-500/10 text-amber-700 dark:text-amber-400 hover:bg-amber-500/20 border border-amber-500/20 transition-colors"
                >
                  <Plus size={10} />
                  {t('bim.quick_task', { defaultValue: 'Task' })}
                </button>
              )}
              {onLinkDocument && (
                <button
                  type="button"
                  onClick={() => onLinkDocument(selectedElement)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-violet-500/10 text-violet-700 dark:text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-colors"
                >
                  <Plus size={10} />
                  {t('bim.quick_doc', { defaultValue: 'Document' })}
                </button>
              )}
              {onLinkActivity && (
                <button
                  type="button"
                  onClick={() => onLinkActivity(selectedElement)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-colors"
                >
                  <Plus size={10} />
                  {t('bim.quick_schedule', { defaultValue: 'Schedule' })}
                </button>
              )}
              {onLinkRequirement && (
                <button
                  type="button"
                  onClick={() => onLinkRequirement(selectedElement)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-violet-500/10 text-violet-700 dark:text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-colors"
                >
                  <Plus size={10} />
                  {t('bim.quick_req', { defaultValue: 'Requirement' })}
                </button>
              )}
            </div>
          )}

          {/* Tab bar */}
          <div className="flex border-b border-border-light shrink-0">
            {([
              ['key', t('bim.tab_properties', { defaultValue: 'Properties' })] as const,
              ['links', t('bim.tab_links', { defaultValue: 'Links' })] as const,
              ['validation', t('bim.tab_check', { defaultValue: 'Check' })] as const,
              ['match', t('bim.tab_match', { defaultValue: 'Match' })] as const,
            ]).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setPropsTab(id);
                  if (id === 'key' && parquetProps === null && !parquetExpanded) {
                    handleFetchAllProperties();
                  }
                }}
                className={`flex-1 py-2 text-xs font-semibold transition-colors border-b-2 inline-flex items-center justify-center gap-1 ${
                  propsTab === id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-tertiary hover:text-content-secondary'
                }`}
              >
                {id === 'match' && <Sparkles size={11} />}
                {label}
                {id === 'links' && (selectedElement.boq_links?.length ?? 0) > 0 && (
                  <span className="ml-1 text-[10px] text-oe-blue">
                    {selectedElement.boq_links!.length}
                  </span>
                )}
                {id === 'validation' && selectedElement.validation_status === 'error' && (
                  <span className="ml-1 text-[10px] text-rose-500">!</span>
                )}
              </button>
            ))}
          </div>

          <div className="overflow-y-auto p-3 space-y-3 bg-white/40 dark:bg-white/5">
            {/* ── Tab: Properties (merged Key + All) ──────────────────── */}
            {propsTab === 'key' && (
              <>
                {/* Copy all properties button */}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      const lines: string[] = [];
                      lines.push(`Type: ${selectedElement.element_type || ''}`);
                      lines.push(`Name: ${selectedElement.name || ''}`);
                      if (selectedElement.discipline) lines.push(`Discipline: ${selectedElement.discipline}`);
                      if (selectedElement.storey) lines.push(`Storey: ${selectedElement.storey}`);
                      if (selectedElement.mesh_ref) lines.push(`ID: ${selectedElement.mesh_ref}`);
                      for (const [k, v] of Object.entries(elementQuantities)) {
                        lines.push(`${k}: ${v}`);
                      }
                      for (const [k, v] of Object.entries(elementProperties)) {
                        lines.push(`${k}: ${v}`);
                      }
                      navigator.clipboard.writeText(lines.join('\n'));
                    }}
                    className="text-[10px] text-content-tertiary hover:text-oe-blue transition-colors flex items-center gap-1"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    {t('bim.copy_all', { defaultValue: 'Copy all' })}
                  </button>
                </div>

                {/* Element info */}
                <div className="space-y-1.5">
                  <InfoRow
                    label={t('bim.prop_type', { defaultValue: 'Type' })}
                    value={selectedElement.element_type}
                  />
                  <InfoRow
                    label={t('bim.prop_discipline', { defaultValue: 'Discipline' })}
                    value={selectedElement.discipline}
                  />
                  {selectedElement.storey && (
                    <InfoRow
                      label={t('bim.prop_storey', { defaultValue: 'Storey' })}
                      value={selectedElement.storey}
                    />
                  )}
                  {selectedElement.category && (
                    <InfoRow
                      label={t('bim.prop_category', { defaultValue: 'Category' })}
                      value={selectedElement.category}
                    />
                  )}
                </div>

                {/* Quantities */}
                {Object.keys(elementQuantities).length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold text-content-primary mb-1.5 flex items-center gap-1.5">
                      <Ruler size={13} className="text-oe-blue" />
                      {t('bim.quantities', { defaultValue: 'Quantities' })}
                    </h4>
                    <QuantitiesTable quantities={elementQuantities} />
                  </div>
                )}

                {/* Geometry — derived from the canonical bounding box. */}
                {elementGeometry && (
                  <div data-testid="bim-geometry-section">
                    <h4 className="text-sm font-semibold text-content-primary mb-1.5 flex items-center gap-1.5">
                      <Move3d size={13} className="text-oe-blue" />
                      {t('bim.geometry', { defaultValue: 'Geometry' })}
                    </h4>
                    <QuantitiesTable
                      quantities={{
                        [t('bim.geo_width', { defaultValue: 'Width (m)' })]:
                          elementGeometry.width,
                        [t('bim.geo_depth', { defaultValue: 'Depth (m)' })]:
                          elementGeometry.depth,
                        [t('bim.geo_height', { defaultValue: 'Height (m)' })]:
                          elementGeometry.height,
                        [t('bim.geo_footprint', {
                          defaultValue: 'Footprint (m²)',
                        })]: elementGeometry.footprint,
                        [t('bim.geo_bbox_volume', {
                          defaultValue: 'Bounding volume (m³)',
                        })]: elementGeometry.bboxVolume,
                        [t('bim.geo_diagonal', {
                          defaultValue: 'Diagonal (m)',
                        })]: elementGeometry.diagonal,
                      }}
                    />
                  </div>
                )}

                {/* Spatial relations — level / zone / system / assembly. */}
                {elementRelations.length > 0 && (
                  <div data-testid="bim-relations-section">
                    <h4 className="text-sm font-semibold text-content-primary mb-1.5 flex items-center gap-1.5">
                      <Boxes size={13} className="text-emerald-500" />
                      {t('bim.relations', { defaultValue: 'Spatial structure' })}
                    </h4>
                    <div className="space-y-1.5">
                      {elementRelations.map((r) => (
                        <InfoRow key={r.key} label={r.key} value={r.value} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Classification */}
                {selectedElement.classification && Object.keys(selectedElement.classification).length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold text-content-primary mb-1.5 flex items-center gap-1.5">
                      <Tag size={13} className="text-violet-500" />
                      {t('bim.classification', { defaultValue: 'Classification' })}
                    </h4>
                    <PropertiesTable properties={selectedElement.classification} />
                  </div>
                )}

                {/* Properties (inline + parquet merged) */}
                <div>
                  <h4 className="text-sm font-semibold text-content-primary mb-1.5 flex items-center gap-1.5">
                    <Settings size={13} className="text-content-tertiary" />
                    {t('bim.all_properties', { defaultValue: 'All properties' })}
                  </h4>
                  {parquetLoading && (
                    <div className="flex items-center gap-2 text-xs text-content-tertiary py-2">
                      <Loader2 size={12} className="animate-spin text-oe-blue" />
                      {t('bim.loading_properties', { defaultValue: 'Loading...' })}
                    </div>
                  )}
                  {parquetProps && Object.keys(parquetProps).length > 0 ? (
                    <PropertiesTable properties={parquetProps} />
                  ) : !parquetLoading && Object.keys(elementProperties).length > 0 ? (
                    <PropertiesTable properties={elementProperties} />
                  ) : !parquetLoading ? (
                    <p className="text-[10px] text-content-tertiary italic py-1">
                      {t('bim.no_extra_props', { defaultValue: 'No additional properties' })}
                    </p>
                  ) : null}
                </div>
              </>
            )}

            {/* ── Tab: Validation ────────────────────────────────── */}
            {propsTab === 'validation' && (
              <>
                {selectedElement.validation_results && selectedElement.validation_results.length > 0 ? (
                  <div
                    className={`rounded-md border p-2 ${
                      selectedElement.validation_status === 'error'
                        ? 'border-rose-300/60 bg-rose-50/50 dark:bg-rose-950/20'
                        : selectedElement.validation_status === 'warning'
                          ? 'border-amber-300/60 bg-amber-50/50 dark:bg-amber-950/20'
                          : 'border-emerald-300/60 bg-emerald-50/50 dark:bg-emerald-950/20'
                    }`}
                  >
                    <h4
                      className={`text-xs font-semibold flex items-center gap-1 mb-1.5 ${
                        selectedElement.validation_status === 'error'
                          ? 'text-rose-700 dark:text-rose-300'
                          : selectedElement.validation_status === 'warning'
                            ? 'text-amber-700 dark:text-amber-300'
                            : 'text-emerald-700 dark:text-emerald-300'
                      }`}
                    >
                      {selectedElement.validation_status === 'error' ? (
                        <ShieldX size={11} />
                      ) : selectedElement.validation_status === 'warning' ? (
                        <ShieldAlert size={11} />
                      ) : (
                        <ShieldCheck size={11} />
                      )}
                      {t('bim.validation_results', { defaultValue: 'Validation results' })}
                      <span className="text-[10px] text-content-tertiary font-normal">
                        ({selectedElement.validation_results.length})
                      </span>
                    </h4>
                    <ul className="space-y-0.5">
                      {selectedElement.validation_results.map((vr, i) => (
                        <li
                          key={`${vr.rule_id}-${i}`}
                          className="flex items-start gap-1.5 text-[10px] text-content-secondary"
                        >
                          <span
                            className={`mt-0.5 inline-block h-1.5 w-1.5 rounded-full shrink-0 ${
                              vr.severity === 'error'
                                ? 'bg-rose-500'
                                : vr.severity === 'warning'
                                  ? 'bg-amber-500'
                                  : 'bg-sky-500'
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-content-primary truncate" title={vr.rule_id}>
                              {vr.rule_id}
                            </div>
                            <div className="text-content-tertiary text-[9px] line-clamp-2">
                              {vr.message}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <ShieldCheck size={24} className="mx-auto text-content-quaternary mb-2" />
                    <p className="text-[11px] text-content-tertiary">
                      {t('bim.no_validation', {
                        defaultValue: 'No validation results yet. Run a validation check on this model.',
                      })}
                    </p>
                  </div>
                )}
              </>
            )}

            {/* ── Tab: Match (CWICR vector matcher) ──────────────────
                Suggests CWICR cost-positions for the selected element.
                ``key={selectedElement.id}`` forces the panel to remount
                on element switch so the autoFetch effect refires and
                the per-element rejection accumulator doesn't leak. */}
            {propsTab === 'match' && (
              <div className="-mx-3 -mb-3 h-[420px]">
                <MatchSuggestionsPanel
                  key={selectedElement.id}
                  source="bim"
                  projectId={projectId}
                  rawElementData={{
                    id: selectedElement.id,
                    element_type: selectedElement.element_type,
                    name: selectedElement.name,
                    properties:
                      (selectedElement as { properties?: Record<string, unknown> })
                        .properties ?? {},
                    quantities:
                      (selectedElement as { quantities?: Record<string, number> })
                        .quantities ?? {},
                  }}
                  autoFetch
                  compact
                />
              </div>
            )}

            {/* ── Tab: Links ──────────────────────────────────────── */}
            {propsTab === 'links' && (
              <>
            {/* BOQ Links — the headline integration feature.
                Shows every BOQ position this element is linked to, with an
                "Unlink" action on each, plus an "Add to BOQ" button that
                opens the AddToBOQModal in the parent. */}
            <div className="rounded-md border border-oe-blue/30 bg-oe-blue/5 p-2">
              <div className="flex items-center justify-between mb-1.5">
                <h4 className="text-xs font-semibold text-oe-blue flex items-center gap-1">
                  <Link2 size={11} />
                  {t('bim.linked_boq', { defaultValue: 'Linked BOQ positions' })}
                  {selectedElement.boq_links && selectedElement.boq_links.length > 0 && (
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.boq_links.length})
                    </span>
                  )}
                </h4>
                {onAddToBOQ && (
                  <button
                    type="button"
                    onClick={() => onAddToBOQ([selectedElement])}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-oe-blue text-white hover:bg-oe-blue-dark"
                    title={t('bim.link_add_title', { defaultValue: 'Add this element to a BOQ position' })}
                  >
                    <Plus size={10} />
                    {t('bim.link_add', { defaultValue: 'Add to BOQ' })}
                  </button>
                )}
              </div>
              {selectedElement.boq_links && selectedElement.boq_links.length > 0 ? (
                <ul className="space-y-1">
                  {selectedElement.boq_links.map((link) => (
                    <li
                      key={link.id}
                      className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {link.boq_position_ordinal && (
                            <span className="text-[10px] font-mono font-semibold text-content-primary tabular-nums">
                              {link.boq_position_ordinal}
                            </span>
                          )}
                          <span
                            className={`text-[9px] px-1 rounded ${
                              link.link_type === 'manual'
                                ? 'bg-emerald-100 text-emerald-700'
                                : link.link_type === 'rule_based'
                                  ? 'bg-violet-100 text-violet-700'
                                  : 'bg-sky-100 text-sky-700'
                            }`}
                          >
                            {link.link_type.replace('_', ' ')}
                          </span>
                        </div>
                        <div className="text-[11px] text-content-secondary truncate" title={link.boq_position_description || ''}>
                          {link.boq_position_description || '—'}
                        </div>
                      </div>
                      {onUnlinkBOQ && (
                        <button
                          type="button"
                          onClick={() => onUnlinkBOQ(link.id)}
                          className="p-1 rounded text-content-tertiary hover:text-rose-600 hover:bg-rose-50"
                          title={t('bim.link_remove', { defaultValue: 'Remove link' })}
                        >
                          <Link2Off size={11} />
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-[10px] text-content-tertiary italic">
                  {t('bim.link_empty', {
                    defaultValue: 'Not linked — click "Add to BOQ" to link this element to a cost position',
                  })}
                </div>
              )}
            </div>

            {/* Linked Documents — always rendered when callbacks present
                so users can ADD links from an empty state too. */}
            {(onLinkDocument || (selectedElement.linked_documents && selectedElement.linked_documents.length > 0)) && (
              <div className="rounded-md border border-violet-300/50 bg-violet-50/40 dark:bg-violet-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-violet-700 dark:text-violet-300 flex items-center gap-1">
                    <FileText size={11} />
                    {t('bim.linked_documents', { defaultValue: 'Linked documents' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_documents?.length ?? 0})
                    </span>
                  </h4>
                  {onLinkDocument && (
                    <button
                      type="button"
                      onClick={() => onLinkDocument(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-600 text-white hover:bg-violet-700"
                      title={t('bim.link_doc', { defaultValue: 'Link a document to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.link', { defaultValue: 'Link' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_documents && selectedElement.linked_documents.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_documents.map((d) => (
                      <li
                        key={d.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenDocument?.(d.document_id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="text-[11px] text-content-primary truncate" title={d.document_name || ''}>
                            {d.document_name || '—'}
                          </div>
                          {d.document_category && (
                            <div className="text-[9px] text-content-tertiary uppercase tracking-wider">
                              {d.document_category}
                            </div>
                          )}
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.docs_empty', {
                      defaultValue: 'No drawings linked yet — click "Link" to attach a drawing or photo',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Linked Tasks — always rendered when callback present. */}
            {(onCreateTask || (selectedElement.linked_tasks && selectedElement.linked_tasks.length > 0)) && (
              <div className="rounded-md border border-amber-300/50 bg-amber-50/40 dark:bg-amber-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-amber-700 dark:text-amber-300 flex items-center gap-1">
                    <CheckSquare size={11} />
                    {t('bim.linked_tasks', { defaultValue: 'Linked tasks' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_tasks?.length ?? 0})
                    </span>
                  </h4>
                  {onCreateTask && (
                    <button
                      type="button"
                      onClick={() => onCreateTask(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-600 text-white hover:bg-amber-700"
                      title={t('bim.create_task', { defaultValue: 'Create a task pinned to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.new', { defaultValue: 'New' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_tasks && selectedElement.linked_tasks.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_tasks.map((task) => (
                      <li
                        key={task.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenTask?.(task.id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`text-[9px] px-1 rounded uppercase tracking-wider ${
                                task.status === 'closed' || task.status === 'done'
                                  ? 'bg-emerald-100 text-emerald-700'
                                  : task.status === 'in_progress'
                                    ? 'bg-sky-100 text-sky-700'
                                    : 'bg-amber-100 text-amber-700'
                              }`}
                            >
                              {task.status}
                            </span>
                            {task.task_type && (
                              <span className="text-[9px] text-content-tertiary">{task.task_type}</span>
                            )}
                          </div>
                          <div className="text-[11px] text-content-primary truncate" title={task.title}>
                            {task.title}
                          </div>
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.tasks_empty', {
                      defaultValue: 'No tasks pinned yet — click "New" to file a defect or RFI',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Schedule Activities (4D) — always rendered when callback present. */}
            {(onLinkActivity || (selectedElement.linked_activities && selectedElement.linked_activities.length > 0)) && (
              <div className="rounded-md border border-emerald-300/50 bg-emerald-50/40 dark:bg-emerald-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-emerald-700 dark:text-emerald-300 flex items-center gap-1">
                    <Calendar size={11} />
                    {t('bim.linked_activities', { defaultValue: 'Schedule activities (4D)' })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_activities?.length ?? 0})
                    </span>
                  </h4>
                  {onLinkActivity && (
                    <button
                      type="button"
                      onClick={() => onLinkActivity(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-600 text-white hover:bg-emerald-700"
                      title={t('bim.link_activity', { defaultValue: 'Link a schedule activity to this element' })}
                    >
                      <Plus size={10} />
                      {t('bim.link', { defaultValue: 'Link' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_activities && selectedElement.linked_activities.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_activities.map((act) => (
                      <li
                        key={act.id}
                        className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                      >
                        <button
                          type="button"
                          onClick={() => onOpenActivity?.(act.id)}
                          className="flex-1 min-w-0 text-left"
                        >
                          <div className="text-[11px] text-content-primary truncate" title={act.name}>
                            {act.name}
                          </div>
                          <div className="flex items-center gap-1.5 text-[9px] text-content-tertiary tabular-nums">
                            {act.start_date && <span>{act.start_date.slice(0, 10)}</span>}
                            {act.start_date && act.end_date && <span>→</span>}
                            {act.end_date && <span>{act.end_date.slice(0, 10)}</span>}
                            {typeof act.percent_complete === 'number' && (
                              <span className="ms-auto font-medium">{act.percent_complete}%</span>
                            )}
                          </div>
                        </button>
                        <ExternalLink size={10} className="text-content-tertiary shrink-0" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.acts_empty', {
                      defaultValue: 'No 4D activities yet — click "Link" to attach a schedule activity',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Linked Requirements (EAC triplets — the bridge between
                client intent / spec and the executed model).  Stored on
                the requirement side under metadata_["bim_element_ids"]
                and surfaced here via the bim_hub eager-load path. */}
            {(onLinkRequirement ||
              (selectedElement.linked_requirements &&
                selectedElement.linked_requirements.length > 0)) && (
              <div className="rounded-md border border-violet-300/50 bg-violet-50/40 dark:bg-violet-950/20 p-2">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="text-xs font-semibold text-violet-700 dark:text-violet-300 flex items-center gap-1">
                    <ClipboardCheck size={11} />
                    {t('bim.linked_requirements', {
                      defaultValue: 'Linked requirements',
                    })}
                    <span className="text-[10px] text-content-tertiary font-normal">
                      ({selectedElement.linked_requirements?.length ?? 0})
                    </span>
                  </h4>
                  {onLinkRequirement && (
                    <button
                      type="button"
                      onClick={() => onLinkRequirement(selectedElement)}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-600 text-white hover:bg-violet-700"
                      title={t('bim.link_requirement', {
                        defaultValue: 'Pin a requirement to this element',
                      })}
                    >
                      <Plus size={10} />
                      {t('bim.link', { defaultValue: 'Link' })}
                    </button>
                  )}
                </div>
                {selectedElement.linked_requirements &&
                selectedElement.linked_requirements.length > 0 ? (
                  <ul className="space-y-1">
                    {selectedElement.linked_requirements.map((req) => {
                      const priorityColor =
                        req.priority === 'must'
                          ? 'text-rose-600'
                          : req.priority === 'should'
                            ? 'text-amber-600'
                            : 'text-slate-500';
                      return (
                        <li
                          key={req.id}
                          className="flex items-center justify-between gap-1 px-1.5 py-1 rounded bg-surface-primary border border-border-light"
                        >
                          <button
                            type="button"
                            onClick={() => onOpenRequirement?.(req.id)}
                            className="flex-1 min-w-0 text-left"
                          >
                            <div className="flex items-center gap-1.5">
                              <span className="text-[11px] font-medium text-content-primary truncate">
                                {req.entity}
                                {req.attribute && (
                                  <span className="text-content-tertiary">
                                    .{req.attribute}
                                  </span>
                                )}
                              </span>
                              <span
                                className={`text-[9px] font-bold uppercase shrink-0 ${priorityColor}`}
                              >
                                {req.priority}
                              </span>
                            </div>
                            <div className="text-[9px] font-mono text-content-tertiary tabular-nums truncate">
                              {req.constraint_type} {req.constraint_value}
                              {req.unit ? ` ${req.unit}` : ''}
                            </div>
                          </button>
                          <ExternalLink
                            size={10}
                            className="text-content-tertiary shrink-0"
                          />
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <div className="text-[10px] text-content-tertiary italic">
                    {t('bim.req_empty', {
                      defaultValue:
                        'No requirements yet — click "Link" to pin a constraint to this element',
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Semantic similarity — in links tab since it helps find
                related elements for linking workflows. */}
            <div>
              <SimilarItemsPanel
                module="bim_elements"
                id={selectedElement.id}
                limit={5}
              />
            </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Note: the old bottom-left view-mode selector (Default / Discipline /
          5D Cost / 4D Schedule) has been removed in v1.3.22.  It was a
          visual-only stub with no backend — the 5D and 4D modes were never
          wired to cost or schedule data.  Coloring by discipline / storey /
          type now lives in the top toolbar of BIMPage via the colorByMode
          dropdown, which is the single source of truth. */}

      {/* Right-click context menu — rendered as a fixed-position portal-like
          overlay.  Closes on click outside, Escape, or scroll. */}
      {contextMenu && (
        <BIMContextMenu
          menu={contextMenu}
          onClose={handleCloseContextMenu}
          actions={{
            onZoomToElement: handleCtxZoomToElement,
            onCopyProperties: handleCtxCopyProperties,
            onAddToBOQ: onAddToBOQ ? handleCtxAddToBOQ : undefined,
            onLinkDocument: onLinkDocument ? handleCtxLinkDocument : undefined,
            onLinkActivity: onLinkActivity ? handleCtxLinkActivity : undefined,
            onCreateTask: onCreateTask ? handleCtxCreateTask : undefined,
            onIsolate: handleCtxIsolate,
            onHide: handleCtxHide,
            // W6.6 Stream C — Solo Mode: surface "Show all" in the context
            // menu and gate it on whether anything is actually hidden.
            hasHidden:
              elementMgrRef.current?.hasHidden() ?? hiddenCount > 0,
            onShowAll: handleShowAll,
          }}
        />
      )}
    </div>
  );
}

/* ── Section / clipping controls ───────────────────────────────────────── */

interface ClipControlsProps {
  mode: 'none' | 'box' | 'plane';
  onModeChange: (m: 'none' | 'box' | 'plane') => void;
  box: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    minZ: number;
    maxZ: number;
  };
  onBoxChange: (
    patch: Partial<ClipControlsProps['box']>,
  ) => void;
  plane: { axis: 'x' | 'y' | 'z'; offset: number; flipped: boolean };
  onPlaneChange: (patch: Partial<ClipControlsProps['plane']>) => void;
  onReset: () => void;
  onClose: () => void;
  leftOffset: number;
}

/**
 * ClipControls — popover for the section box / single clipping plane.
 * Pure presentational; all geometry math lives in `ClipManager`. The two
 * cut modes are mutually exclusive (a radio-style mode strip) so the user
 * is never fighting six box planes and an arbitrary plane at once.
 */
function ClipControls({
  mode,
  onModeChange,
  box,
  onBoxChange,
  plane,
  onPlaneChange,
  onReset,
  onClose,
  leftOffset,
}: ClipControlsProps) {
  const { t } = useTranslation();
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div
      data-testid="bim-clip-controls"
      className="absolute top-14 z-30 w-72 rounded-lg bg-surface-primary border border-border-light shadow-lg p-3 flex flex-col gap-3"
      style={{ insetInlineStart: leftOffset }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-primary">
          {t('bim.clip_title', { defaultValue: 'Section & clipping' })}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
        >
          <X size={13} />
        </button>
      </div>

      {/* Mode strip */}
      <div
        className="inline-flex rounded-md border border-border-light overflow-hidden"
        role="group"
        aria-label={t('bim.clip_mode_aria', { defaultValue: 'Clip mode' })}
      >
        {([
          ['none', t('bim.clip_off', { defaultValue: 'Off' })] as const,
          ['box', t('bim.clip_box', { defaultValue: 'Section box' })] as const,
          ['plane', t('bim.clip_plane', { defaultValue: 'Plane' })] as const,
        ]).map(([m, lbl]) => (
          <button
            key={m}
            type="button"
            onClick={() => onModeChange(m)}
            aria-pressed={mode === m}
            data-testid={`clip-mode-${m}`}
            className={clsx(
              'flex-1 px-2 py-1 text-[11px] font-medium transition-colors',
              mode === m
                ? 'bg-oe-blue text-white'
                : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
            )}
          >
            {lbl}
          </button>
        ))}
      </div>

      {mode === 'box' && (
        <div className="flex flex-col gap-2.5">
          {(
            [
              ['X', 'minX', 'maxX'],
              ['Y', 'minY', 'maxY'],
              ['Z', 'minZ', 'maxZ'],
            ] as const
          ).map(([axisLabel, minKey, maxKey]) => (
            <div key={axisLabel} className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-[10px] text-content-tertiary uppercase tracking-wider">
                <span>
                  {t('bim.clip_axis', {
                    defaultValue: 'Axis {{axis}}',
                    axis: axisLabel,
                  })}
                </span>
                <span className="tabular-nums">
                  {pct(box[minKey])} – {pct(box[maxKey])}
                </span>
              </div>
              <Slider
                value={box[minKey]}
                onChange={(v) => onBoxChange({ [minKey]: v })}
                min={0}
                max={1}
                step={0.01}
              />
              <Slider
                value={box[maxKey]}
                onChange={(v) => onBoxChange({ [maxKey]: v })}
                min={0}
                max={1}
                step={0.01}
              />
            </div>
          ))}
        </div>
      )}

      {mode === 'plane' && (
        <div className="flex flex-col gap-2.5">
          <div
            className="inline-flex rounded-md border border-border-light overflow-hidden"
            role="group"
            aria-label={t('bim.clip_plane_axis_aria', {
              defaultValue: 'Plane axis',
            })}
          >
            {(['x', 'y', 'z'] as const).map((ax) => (
              <button
                key={ax}
                type="button"
                onClick={() => onPlaneChange({ axis: ax })}
                aria-pressed={plane.axis === ax}
                data-testid={`clip-plane-axis-${ax}`}
                className={clsx(
                  'flex-1 px-2 py-1 text-[11px] font-medium uppercase transition-colors',
                  plane.axis === ax
                    ? 'bg-oe-blue text-white'
                    : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                )}
              >
                {ax}
              </button>
            ))}
          </div>
          <Slider
            label={t('bim.clip_plane_offset', { defaultValue: 'Offset' })}
            value={plane.offset}
            onChange={(v) => onPlaneChange({ offset: v })}
            min={0}
            max={1}
            step={0.01}
            format={(v) => `${Math.round(v * 100)}%`}
          />
          <button
            type="button"
            onClick={() => onPlaneChange({ flipped: !plane.flipped })}
            aria-pressed={plane.flipped}
            data-testid="clip-plane-flip"
            className="inline-flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium border border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary transition-colors"
          >
            <RotateCcw size={12} />
            {t('bim.clip_plane_flip', { defaultValue: 'Flip side' })}
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={onReset}
        data-testid="clip-reset"
        className="inline-flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
      >
        <RotateCcw size={12} />
        {t('bim.clip_reset', { defaultValue: 'Reset & disable' })}
      </button>
    </div>
  );
}

/* ── Shared Sub-components ─────────────────────────────────────────────── */

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
  active = false,
  variant = 'standalone',
  testId,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  active?: boolean;
  /** `standalone` renders with its own background + border + shadow.
   *  `group` renders flat so it slots into a shared container (the reorganised
   *  toolbar wraps every button in one bordered row). */
  variant?: 'standalone' | 'group';
  /** Optional data-testid for e2e selectors. */
  testId?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      data-testid={testId}
      className={clsx(
        'flex h-7 w-7 items-center justify-center rounded transition-colors',
        variant === 'standalone' && 'shadow-sm border bg-surface-primary/90 backdrop-blur border-border-light',
        active
          ? 'bg-oe-blue text-white' + (variant === 'standalone' ? ' border-oe-blue' : '')
          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      <Icon size={14} />
    </button>
  );
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between items-center gap-3 py-1.5 px-2 rounded-md border bg-white/60 border-black/5 dark:bg-white/5 dark:border-white/10 hover:bg-white/80 dark:hover:bg-white/10 transition-colors">
      <span className="text-[11px] text-content-tertiary shrink-0">{label}</span>
      <span className="text-[11px] text-content-primary font-medium text-end truncate min-w-0" title={value}>
        {value}
      </span>
    </div>
  );
}

/* ── Color-mode legend ─────────────────────────────────────────────────── */

/**
 * ColorModeLegend — small overlay surfacing what each mesh colour means
 * for the currently-active discrete-palette colour mode.
 *
 * Field-based modes (storey, type) regenerate their swatches from the
 * exact same golden-angle HSL algorithm `ElementManager.colorBy()` uses,
 * so the legend stays in lock-step with the live scene without any extra
 * coordination state.  Compliance modes use a fixed three-colour palette
 * (red / amber / green) that mirrors the validation rules in
 * `BIMViewer.tsx:912-942`.
 *
 * Anchored bottom-right at `bottom-12 end-3` so it sits one row above the
 * Hidden / Isolated badge stack and never collides with it.
 */
function ColorModeLegend({
  mode,
  elements,
}: {
  mode: 'storey' | 'type' | 'validation' | 'boq_coverage' | 'document_coverage';
  elements: BIMElementData[];
}) {
  const { t } = useTranslation();
  const items: { label: string; hex: string }[] = (() => {
    if (mode === 'storey') {
      return ElementManager.buildColorByPalette(elements, (el) => el.storey || 'Unassigned')
        .map(({ key, hex }) => ({ label: key, hex }));
    }
    if (mode === 'type') {
      return ElementManager.buildColorByPalette(elements, (el) => el.element_type || 'Unknown')
        .map(({ key, hex }) => ({ label: key, hex }));
    }
    if (mode === 'validation') {
      return [
        { label: t('bim.validation_pass', { defaultValue: 'Pass' }), hex: '#10b981' },
        { label: t('bim.validation_warning', { defaultValue: 'Warning' }), hex: '#f59e0b' },
        { label: t('bim.validation_error', { defaultValue: 'Error' }), hex: '#ef4444' },
        { label: t('bim.validation_unchecked', { defaultValue: 'Unchecked' }), hex: '#9ca3af' },
      ];
    }
    if (mode === 'boq_coverage') {
      return [
        { label: t('bim.coverage_linked', { defaultValue: 'Linked to BOQ' }), hex: '#10b981' },
        { label: t('bim.coverage_not_linked', { defaultValue: 'Not linked' }), hex: '#ef4444' },
      ];
    }
    // document_coverage
    return [
      { label: t('bim.coverage_doc_linked', { defaultValue: 'Has documents' }), hex: '#10b981' },
      { label: t('bim.coverage_doc_none', { defaultValue: 'No documents' }), hex: '#ef4444' },
    ];
  })();

  const titleByMode = {
    storey: t('bim.legend_storey', { defaultValue: 'Storey' }),
    type: t('bim.legend_type', { defaultValue: 'Category' }),
    validation: t('bim.legend_validation', { defaultValue: 'Validation' }),
    boq_coverage: t('bim.legend_boq_coverage', { defaultValue: 'BOQ coverage' }),
    document_coverage: t('bim.legend_doc_coverage', { defaultValue: 'Document coverage' }),
  } as const;

  // Field-based palettes can be huge (one swatch per storey/category).
  // Cap the visible list at 12 and indicate the overflow so the overlay
  // never grows past a couple hundred px.
  const MAX = 12;
  const visible = items.slice(0, MAX);
  const hiddenCount = Math.max(0, items.length - MAX);

  return (
    <div
      className="absolute bottom-12 end-3 z-20 flex flex-col gap-1 rounded-lg bg-surface-primary/95 backdrop-blur-sm border border-border-light shadow-sm px-3 py-2 max-w-[220px]"
      data-testid="bim-color-legend"
    >
      <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
        {titleByMode[mode]}
      </span>
      <ul className="flex flex-col gap-0.5">
        {visible.map(({ label, hex }) => (
          <li
            key={`${label}-${hex}`}
            className="flex items-center gap-1.5 text-[11px] text-content-secondary"
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm shrink-0 border border-black/10"
              style={{ background: hex }}
            />
            <span className="truncate" title={label}>{label}</span>
          </li>
        ))}
      </ul>
      {hiddenCount > 0 && (
        <span className="text-[10px] text-content-tertiary italic">
          {t('bim.legend_more', {
            defaultValue: '+{{count}} more',
            count: hiddenCount,
          })}
        </span>
      )}
    </div>
  );
}

/* ── Discipline Visibility Toggle ──────────────────────────────────────── */

export function DisciplineToggle({
  disciplines,
  visible,
  onToggle,
}: {
  disciplines: string[];
  visible: Record<string, boolean>;
  onToggle: (discipline: string) => void;
}) {
  const { t } = useTranslation();
  if (disciplines.length === 0) return null;

  return (
    <div className="space-y-1">
      <h4 className="text-xs font-semibold text-content-primary">
        {t('bim.disciplines', { defaultValue: 'Disciplines' })}
      </h4>
      {disciplines.map((d) => {
        const isVisible = visible[d] !== false;
        return (
          <button
            key={d}
            onClick={() => onToggle(d)}
            className="flex items-center gap-2 w-full text-xs px-2 py-1 rounded hover:bg-surface-secondary transition-colors"
          >
            {isVisible ? (
              <Eye size={14} className="text-oe-blue" />
            ) : (
              <EyeOff size={14} className="text-content-tertiary" />
            )}
            <span className={clsx(isVisible ? 'text-content-primary' : 'text-content-tertiary')}>
              {d}
            </span>
          </button>
        );
      })}
    </div>
  );
}

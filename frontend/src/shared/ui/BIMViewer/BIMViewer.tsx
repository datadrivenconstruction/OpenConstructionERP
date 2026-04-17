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
} from 'lucide-react';
import { fetchBIMElementProperties } from '@/features/bim/api';
import { SceneManager } from './SceneManager';
import { ElementManager } from './ElementManager';
import type { BIMElementData } from './ElementManager';
import { SelectionManager } from './SelectionManager';
import { BIMContextMenu } from './BIMContextMenu';
import type { BIMContextMenuState } from './BIMContextMenu';
import SimilarItemsPanel from '@/shared/ui/SimilarItemsPanel';

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
   *  across renders. */
  onSelectionChange?: (elementIds: string[]) => void;
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
    | 'document_coverage';
  /** Show bounding box placeholders alongside geometry. Off by default. */
  showBoundingBoxes?: boolean;
  /** Element IDs to isolate (hide everything else). Empty = show all. */
  isolatedIds?: string[] | null;
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
    <div className="space-y-0.5">
      {entries.map(([key, value]) => {
        const label = prettyKey(key);
        const bool = parseBool(value);
        const mat = bool === null ? parseMaterialString(value) : null;
        return (
          <div
            key={key}
            className="flex flex-col gap-0.5 py-1.5 px-2 rounded hover:bg-surface-secondary/50 group"
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
    <div className="space-y-0.5">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="flex justify-between items-center gap-3 py-1.5 px-2 rounded hover:bg-surface-secondary/50"
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
  projectId: _projectId,
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
}: BIMViewerProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SceneManager | null>(null);
  const elementMgrRef = useRef<ElementManager | null>(null);
  const selectionMgrRef = useRef<SelectionManager | null>(null);

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
  const [propsTab, setPropsTab] = useState<'key' | 'all' | 'links' | 'validation'>('key');
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

    const elementMgr = new ElementManager(scene);
    elementMgrRef.current = elementMgr;

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
        onElementSelect?.(id);
      },
      onElementHover: (id) => {
        if (id) {
          const data = elementMgr.getElementData(id);
          setHoveredElement(data ?? null);
        } else {
          setHoveredElement(null);
          setTooltipPos(null);
        }
        onElementHover?.(id);
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
        onElementSelect?.(ids.length > 0 ? ids[ids.length - 1]! : null);
        onSelectionChange?.(ids);
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
          setHiddenIds(new Set());
          scene.zoomToFit();
        }
      },
    });
    selectionMgrRef.current = selectionMgr;

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
      selectionMgr.dispose();
      elementMgr.dispose();
      scene.dispose();
      sceneRef.current = null;
      elementMgrRef.current = null;
      selectionMgrRef.current = null;
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

  // Re-wire callbacks when handlers change (avoid stale closures)
  const onElementSelectRef = useRef(onElementSelect);
  onElementSelectRef.current = onElementSelect;
  const onElementHoverRef = useRef(onElementHover);
  onElementHoverRef.current = onElementHover;

  // Load elements when data changes. When a real DAE/COLLADA geometry
  // URL is available we skip the placeholder boxes — the placeholders
  // would briefly render at the BIM bounding-box coordinates (which are
  // in source-CAD units, often a different scale than the COLLADA scene)
  // and trigger a wrong-distance camera fit before the DAE finishes
  // loading. Skipping them keeps the first zoomToFit clean.
  useEffect(() => {
    if (!elementMgrRef.current || !elements) return;
    // Bounding box placeholders only when user explicitly toggles them on.
    // Real 3D geometry comes from DAE/GLB — no boxes by default.
    // Only reload elements if the element count actually changed (new model).
    // Data updates (link changes, validation) don't require full element reload
    // — just update the elementDataMap in-place.
    const prevCount = elementMgrRef.current.getElementCount();
    if (elements.length !== prevCount) {
      elementMgrRef.current.loadElements(elements, { skipPlaceholders: !showBoundingBoxes });
    } else {
      // Update element data in-place without recreating meshes
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
  useEffect(() => {
    if (!elementMgrRef.current || !geometryUrl || !elements?.length) return;
    const mgr = elementMgrRef.current;
    // Only load if not already loaded for this URL
    if (!mgr.hasLoadedGeometry()) {
      // Reset progress state at the start of every load.  null →
      // hide overlay; 0 → start animating in.
      setGeometryProgress(0);
      mgr
        .loadGeometry(geometryUrl, (fraction) => {
          // ColladaLoader fires this on every XHR progress event,
          // typically every few KB.  We clamp to [0, 1] defensively
          // and let the React render schedule batch updates.
          setGeometryProgress(Math.max(0, Math.min(1, fraction)));
        })
        .then(() => {
          // Final 100% tick is emitted by ElementManager itself
          // (after parsing finishes); hide the overlay one frame
          // later so the bar fully fills before disappearing.
          setGeometryProgress(1);
          setTimeout(() => setGeometryProgress(null), 200);
          onGeometryLoadedRef.current?.(mgr.getMeshMatchRatio());
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
          const fit = () => sceneRef.current?.zoomToFit();
          fit();
          requestAnimationFrame(() => {
            fit();
            requestAnimationFrame(fit);
          });
        })
        .catch((err) => {
          // Geometry load failed — no fallback boxes, just clear progress.
          // eslint-disable-next-line no-console
          console.warn('[BIM] Geometry load failed:', err);
          setGeometryProgress(null);
        });
    }
  // Re-run when geometryUrl changes OR when elements first arrive (guard above).
  // Using elements.length as dep avoids re-triggering on data-only updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometryUrl, elements?.length]);

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
    if (isolatedIds && isolatedIds.length > 0) {
      elementMgrRef.current.isolate(isolatedIds);
      const visibleMeshes = elementMgrRef.current
        .getAllMeshes()
        .filter((m) => m.visible);
      if (visibleMeshes.length > 0) {
        sceneRef.current.zoomToSelection(visibleMeshes);
      }
    } else if (filterPredicate) {
      const visibleCount = elementMgrRef.current.applyFilter(filterPredicate);
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
    } else {
      elementMgrRef.current.showAll();
      sceneRef.current.zoomToFit();
    }
  }, [filterPredicate, isolatedIds, elements]);

  // Highlight linked elements in orange when the parent passes a set of
  // IDs.  Unlike isolate(), this does NOT hide the rest of the model —
  // it just recolours the matched meshes so the user sees the spatial
  // distribution of whichever BOQ position they're inspecting.
  useEffect(() => {
    if (!elementMgrRef.current) return;
    elementMgrRef.current.highlight(highlightedIds ?? []);
  }, [highlightedIds, elements]);

  // Apply color-by mode when it changes.
  // Field-based modes use the existing hash-to-hue palette via colorBy().
  // Compliance modes use a fixed red/amber/green palette via colorByDirect()
  // so the 3D viewer becomes a live compliance dashboard.
  useEffect(() => {
    if (!elementMgrRef.current || !elements?.length) return;
    const mgr = elementMgrRef.current;
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
    } else {
      mgr.resetColors();
    }
  }, [colorByMode, elements]);

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
    const meshes = ids
      .map((id) => elementMgrRef.current!.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0 && sceneRef.current) {
      sceneRef.current.zoomToSelection(meshes);
    }
  }, [contextMenu]);

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
    sceneRef.current?.zoomToFit();
  }, []);

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
    const meshes = ids
      .map((id) => elementMgrRef.current!.getMesh(id))
      .filter((m): m is NonNullable<typeof m> => m != null);
    if (meshes.length > 0 && sceneRef.current) {
      sceneRef.current.zoomToSelection(meshes);
    }
  }, []);

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

      switch (e.key.toLowerCase()) {
        case 'f':
          e.preventDefault();
          sceneRef.current?.zoomToFit();
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

    const selectedIds = selectedElementIds ?? [];
    let subset: BIMElementData[];
    let scope: 'all' | 'filtered' | 'selection';
    if (selectedIds.length > 1) {
      const set = new Set(selectedIds);
      subset = all.filter((el) => set.has(el.id));
      scope = 'selection';
    } else if (filterPredicate) {
      subset = all.filter(filterPredicate);
      scope = 'filtered';
    } else {
      subset = all;
      scope = 'all';
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
    return {
      categories,
      storeys,
      totalVolume,
      totalArea,
      totalLength,
      scope,
      total: all.length,
      shown: subset.length,
    };
  }, [elements, filterPredicate, selectedElementIds]);

  const elementQuantities = useMemo(() => {
    if (!selectedElement?.quantities) return {};
    return selectedElement.quantities;
  }, [selectedElement]);

  return (
    <div ref={containerRef} className={clsx('relative w-full h-full min-h-[400px] bg-surface-secondary rounded-lg overflow-hidden', className)}>
      <canvas ref={canvasRef} className="w-full h-full block" />

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
                    {geometryProgress >= 0.95
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
      </div>

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
          The parent applies the predicate via onSmartFilter. */}
      {elementCount > 0 && (
        <div className="absolute top-3 end-3 z-20 flex items-center gap-1.5 flex-wrap justify-end max-w-[calc(100%-280px)]">
          {/* Total elements pill — not clickable, just informational */}
          <span
            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-surface-primary text-content-secondary border border-border-light shadow-sm"
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
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-sm hover:bg-emerald-100"
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
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200 shadow-sm hover:bg-rose-100"
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
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200 shadow-sm hover:bg-amber-100"
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
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200 shadow-sm hover:bg-amber-100"
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
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet-50 text-violet-700 border border-violet-200 shadow-sm hover:bg-violet-100"
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
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/40 backdrop-blur-sm">
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
      {(!selectedElement || (selectedElementIds && selectedElementIds.length > 1)) && modelSummary && elementCount > 0 && (
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
              <h3 className="text-sm font-bold text-content-primary">
                {modelSummary.scope === 'selection'
                  ? t('bim.selection_summary', { defaultValue: 'Selection summary' })
                  : modelSummary.scope === 'filtered'
                    ? t('bim.filtered_summary', { defaultValue: 'Filtered summary' })
                    : t('bim.model_summary', { defaultValue: 'Model summary' })}
              </h3>
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

      {/* Properties panel (when element selected) — tabbed layout */}
      {selectedElement && (
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
                className={`flex-1 py-2 text-xs font-semibold transition-colors border-b-2 ${
                  propsTab === id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-tertiary hover:text-content-secondary'
                }`}
              >
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

          <div className="overflow-y-auto p-3 space-y-3">
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
                <div className="space-y-1">
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
          }}
        />
      )}
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
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  active?: boolean;
  /** `standalone` renders with its own background + border + shadow.
   *  `group` renders flat so it slots into a shared container (the reorganised
   *  toolbar wraps every button in one bordered row). */
  variant?: 'standalone' | 'group';
}) {
  return (
    <button
      onClick={onClick}
      title={label}
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
    <div className="flex justify-between items-center gap-3 py-1 px-2 rounded hover:bg-surface-secondary/50">
      <span className="text-[11px] text-content-tertiary shrink-0">{label}</span>
      <span className="text-[11px] text-content-primary font-medium text-end truncate min-w-0" title={value}>
        {value}
      </span>
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

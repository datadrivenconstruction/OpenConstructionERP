import { useState, useMemo, useCallback, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import type {
  GridApi,
  CellValueChangedEvent,
  CellEditingStartedEvent,
  CellEditingStoppedEvent,
  RowDragEndEvent,
  GridReadyEvent,
  GetRowIdParams,
  RowClassParams,
  ColumnResizedEvent,
  TabToNextCellParams,
  CellPosition,
  SelectionChangedEvent,
  IsFullWidthRowParams,
  RowHeightParams,
  CellContextMenuEvent,
} from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import {
  Plus,
  Database,
  MessageSquare,
  Trash2,
  Copy,
  ChevronDown,
  ChevronRight,
  BookmarkPlus,
  ExternalLink,
  Wrench,
  X,
  Sparkles,
  TrendingUp,
  AlertTriangle,
  Tag,
  Layers,
  Boxes,
  Cuboid,
  Link2,
  Link2Off,
  Banknote,
} from 'lucide-react';

import {
  type Position,
  type UpdatePositionData,
  type CostAutocompleteItem,
  type ResourceCodeMatch,
  isSection,
  getPositionDepth,
  DEFAULT_MAX_NESTING_DEPTH,
} from './api';
import {
  acquireLock as acquireCollabLock,
  releaseLock as releaseCollabLock,
  type CollabLock,
} from '@/features/collab_locks';
import { getColumnDefs, getCustomColumnDefs } from './grid/columnDefs';
import type { FormulaVariable } from './grid/formula';
import {
  FormulaCellEditor,
  AutocompleteCellEditor,
  UnitCellEditor,
} from './grid/cellEditors';
import {
  ActionsCellRenderer,
  ExpandCellRenderer,
  OrdinalCellRenderer,
  BimLinkCellRenderer,
  QuantityCellRenderer,
  UnitCellRenderer,
  UnitRateCellRenderer,
  SectionFullWidthRenderer,
  ResourceFullWidthRenderer,
  BimQtyPickerCellRenderer,
  DescriptionCellRenderer,
  type ContextMenuTarget,
  type FullGridContext,
} from './grid/cellRenderers';
import { countComments } from './CommentDrawer';
import {
  convertToBase,
  fmtWithCurrency,
  getUnitsForLocale,
  resourceAwareTotalInBase,
  saveCustomUnit,
} from './boqHelpers';
import { RESOURCE_TYPES, getResourceTypeLabel } from './boqResourceTypes';
import { CURRENCY_GROUPS } from '@/features/projects/CreateProjectPage';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { VariantPicker } from '@/features/costs/VariantPicker';
import type { CostVariant, VariantStats } from '@/features/costs/api';
import { copyToClipboard, readClipboard } from '@/shared/lib/browser';

/* ── Column width persistence ─────────────────────────────────────── */

const COLUMN_WIDTHS_KEY = 'oe_boq_column_widths';

function loadColumnWidths(): Record<string, number> {
  try {
    const raw = localStorage.getItem(COLUMN_WIDTHS_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // Ignore corrupt data
  }
  return {};
}

function saveColumnWidths(widths: Record<string, number>): void {
  try {
    localStorage.setItem(COLUMN_WIDTHS_KEY, JSON.stringify(widths));
  } catch {
    // Ignore storage errors (quota, etc.)
  }
}

/* ── Clipboard: fields that cannot be pasted into ─────────────────── */

/** Columns that are computed or read-only — paste is suppressed for these. */
const PASTE_PROTECTED_FIELDS = new Set(['total', '_actions', '_drag', '_checkbox', '_expand', '_bim_link', '_bim_qty']);

/** Numeric column fields — pasted text must be parsed to a number. */
const NUMERIC_FIELDS = new Set(['quantity', 'unit_rate']);

/**
 * Parse a pasted string into a number. Handles thousand separators
 * (both comma and period variants) and strips currency symbols.
 * Returns NaN when the string is not a valid number.
 */
export function parseClipboardNumber(raw: string): number {
  // Strip leading/trailing whitespace
  let cleaned = raw.trim();
  // Remove common currency symbols / prefixes that users may copy from spreadsheets
  cleaned = cleaned.replace(/^[€$£¥₹₽Fr.C\$A\$NZ\$zł₺Kčkr]+/i, '').trim();
  // If both comma and period are present, the last one is the decimal separator
  const hasComma = cleaned.includes(',');
  const hasPeriod = cleaned.includes('.');
  if (hasComma && hasPeriod) {
    if (cleaned.lastIndexOf(',') > cleaned.lastIndexOf('.')) {
      // e.g. "1.234,56" → period is thousand sep, comma is decimal
      cleaned = cleaned.replace(/\./g, '').replace(',', '.');
    } else {
      // e.g. "1,234.56" → comma is thousand sep, period is decimal
      cleaned = cleaned.replace(/,/g, '');
    }
  } else if (hasComma && !hasPeriod) {
    // Could be "1,5" (decimal) or "1,000" (thousand sep).
    // Heuristic: if exactly 3 digits after the last comma, treat as thousand sep.
    const parts = cleaned.split(',');
    const lastPart = parts[parts.length - 1] ?? '';
    if (parts.length === 2 && lastPart.length === 3 && (parts[0] ?? '').length <= 3) {
      // Ambiguous — but "1,000" is more likely thousand-separated in BOQ context
      cleaned = cleaned.replace(/,/g, '');
    } else {
      cleaned = cleaned.replace(',', '.');
    }
  }
  return parseFloat(cleaned);
}

/* ── Types ─────────────────────────────────────────────────────────── */

interface FooterRow {
  _isFooter: true;
  _footerType: string;
  id: string;
  description: string;
  total: number;
  ordinal: string;
  unit: string;
  quantity: number;
  unit_rate: number;
}

interface SectionRow {
  _isSection: true;
  _childCount: number;
  _subtotal: number;
  /**
   * Issue #136 — nesting level of this row in the section tree.
   * 0 = top-level. Drives left-indentation so sections-within-sections
   * and their child positions read as a real hierarchy in the grid.
   * Present on section rows AND on the position rows beneath them.
   */
  _depth?: number;
}

interface ResourceRow {
  _isResource: true;
  _parentPositionId: string;
  _resourceIndex: number;
  _resourceName: string;
  _resourceType: string;
  _resourceUnit: string;
  _resourceQty: number;
  _resourceRate: number;
  /** Optional ISO 4217 code for foreign-currency resources (RFC 37 / #93). */
  _resourceCurrency?: string;
  /** Optional resource code (e.g. CWICR id) — used by inline editor. */
  _resourceCode?: string;
  /**
   * Cached CWICR variant catalog for this resource (v2.6.26+).  Populated at
   * apply-time from ``CostItem.metadata_.variants``; absent on legacy rows.
   * Drives the per-resource re-pick pill.
   */
  _resourceAvailableVariants?: Array<Record<string, unknown>>;
  /** Aggregate stats matching ``_resourceAvailableVariants`` for the picker UI. */
  _resourceAvailableVariantStats?: Record<string, unknown>;
  /** Currently-applied variant marker (mirrors the resource's ``variant`` key). */
  _resourceVariant?: { label: string; price: number; index: number };
  /** Auto-default strategy when the user accepted mean / median (no explicit pick). */
  _resourceVariantDefault?: 'mean' | 'median';
  /** Frozen snapshot stamped by the backend; surfaced for hover tooltips. */
  _resourceVariantSnapshot?: Record<string, unknown>;
  id: string;
  // Fields needed for GridRow compatibility
  description: string;
  ordinal: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

interface AddResourceRow {
  _isAddResource: true;
  _parentPositionId: string;
  _positionResourceTotal: number;
  id: string;
  description: string;
  ordinal: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

/**
 * Synthetic "abstract variant" header row prepended to the resource panel
 * for legacy CWICR position-mode applies. Surfaces the variant catalog
 * (``cost_item_variants``) as a visible, clickable row inside the resource
 * area so the user finds the picker by scanning down — not just by hunting
 * the description-cell V icon. The row is read-only and its only action
 * is to re-open the position-level picker (same as the V icon).
 */
interface VariantHeaderRow {
  _isVariantHeader: true;
  _parentPositionId: string;
  _variantHeaderName: string;
  _variantHeaderChosenLabel: string | null;
  _variantHeaderChosenPrice: number | null;
  _variantHeaderCount: number;
  _variantHeaderCurrency: string;
  /** Position-level quantity — the abstract variant inherits the position's
   *  quantity so the user sees the same volume × variant-price math as on
   *  the position row above (and on every other component resource). */
  _variantHeaderQty: number;
  /** Position-level unit (e.g. "t", "m³"). Needed to render the unit cell
   *  in alignment with the rest of the resource grid. */
  _variantHeaderUnit: string;
  id: string;
  // Fields needed for GridRow compatibility (kept empty / 0).
  description: string;
  ordinal: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

type GridRow =
  | (Position & Partial<SectionRow>)
  | (FooterRow & Record<string, unknown>)
  | (ResourceRow & Record<string, unknown>)
  | (AddResourceRow & Record<string, unknown>)
  | (VariantHeaderRow & Record<string, unknown>);

export interface ManualResource {
  name: string;
  type: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  /** Optional ISO 4217 code for foreign-currency resources (RFC 37 / #93). */
  currency?: string;
  /** Optional reusable resource code (Issue #133). Persisted on the
   *  resource entry so it stays referenceable for future reuse. */
  code?: string;
}

export interface BOQGridProps {
  positions: Position[];
  onUpdatePosition: (id: string, data: UpdatePositionData, oldData: UpdatePositionData) => void;
  onDeletePosition: (id: string) => void;
  onAddPosition: (sectionId?: string) => void;
  onSelectSuggestion: (positionId: string, item: CostAutocompleteItem) => void;
  onSaveToDatabase: (positionId: string) => void;
  onAddComment?: (positionId: string) => void;
  onFormulaApplied: (positionId: string, formula: string, result: number) => void;
  onReorderSections?: (fromId: string, toId: string) => void;
  onReorderPositions?: (reorderedIds: string[]) => void;
  onDeleteSection?: (sectionId: string) => void;
  collapsedSections: Set<string>;
  onToggleSection: (sectionId: string) => void;
  highlightPositionId?: string;
  currencySymbol: string;
  currencyCode: string;
  /**
   * Optional FX rate template (RFC 37 / #93). Used by per-resource currency
   * picker. Each entry maps a foreign currency to a rate-to-base.
   */
  fxRates?: { currency: string; rate: number; label?: string }[];
  /**
   * Issue #157 — persist an FX rate the estimator types into the resource
   * currency popover straight into the PROJECT ``fx_rates`` so the section
   * subtotal, backend rollup and exports all convert the currency. ``code``
   * is the foreign currency, ``rate`` is "1 unit of code = rate units of
   * base". Wired by BOQEditorPage; omitted ⇒ the popover edit only updates
   * the device-local global store (read-only viewers).
   */
  onUpsertProjectFxRate?: (code: string, rate: number) => void;
  /**
   * ── Display-currency override (Issue #88 follow-up).
   * When set, all monetary aggregates rendered by the grid (per-position
   * total, section subtotals, footer rows) are formatted in `code` using
   * `rate` for conversion. View-only — does NOT alter what the server
   * persists. `null` / undefined ⇒ render in project base currency.
   */
  displayCurrency?: { code: string; rate: number } | null;
  /**
   * Issue #105 — open-handler for the Project Settings → FX Rates page.
   * Wired by BOQEditorPage to `navigate('/projects/:id/settings#fx-rates')`.
   * When omitted, the warning badge stays a non-clickable info chip.
   */
  onOpenFxRateSettings?: () => void;
  locale: string;
  footerRows: FooterRow[];
  onSelectionChanged?: (selectedIds: string[]) => void;
  /**
   * Issue #139 — the row the user last *interacted with* (clicked a cell
   * in / focused), regardless of checkbox selection. ``rowSelection`` has
   * ``enableClickSelection:false`` (a plain click edits, it does NOT tick
   * the checkbox), so ``onSelectionChanged`` stays empty when the user
   * simply clicks a partida and hits "Add Position". Without this signal
   * the editor fell back to appending at the LAST section instead of
   * inserting directly below the clicked row — the exact #139 symptom.
   * ``null`` clears the anchor (focus left the data rows).
   */
  onActiveRowChange?: (positionId: string | null) => void;
  onRemoveResource?: (positionId: string, resourceIndex: number) => void;
  onUpdateResource?: (positionId: string, resourceIndex: number, field: string, value: number | string) => void;
  onUpdateResourceFields?: (positionId: string, resourceIndex: number, fields: Record<string, number | string>) => void;
  /** Per-resource custom-field write — stored at
   *  ``parent.metadata.resources[i].metadata.custom_fields[fieldName]`` so a
   *  resource can carry its own supplier / lead time / QC inspector etc. */
  onUpdateResourceCustomField?: (positionId: string, resourceIndex: number, fieldName: string, value: number | string) => void;
  onSaveResourceToCatalog?: (positionId: string, resourceIndex: number) => void;
  /**
   * Save the variant-header synthetic row to the user's catalog under a
   * custom name. The variant header is not in ``metadata.resources`` so the
   * standard ``onSaveResourceToCatalog`` can't reach it — this dedicated
   * handler reads the chosen variant off the position metadata directly.
   */
  onSaveVariantHeaderToCatalog?: (positionId: string, customName: string) => void;
  onOpenCostDbForPosition?: (positionId: string) => void;
  onOpenCatalogForPosition?: (positionId: string) => void;
  /**
   * Re-pick the variant on an already-added resource row (v2.6.26+).
   * Reads ``available_variants`` cached on the resource entry and PATCHes
   * ``/positions/{id}/resources/{idx}/variant/`` server-side. Optional —
   * when omitted, the row's re-pick pill is hidden (graceful degrade).
   */
  onRepickResourceVariant?: (positionId: string, resourceIndex: number, variantCode: string) => void;
  onAddManualResource?: (positionId: string, resource: ManualResource) => void;
  /**
   * Issue #133 — project-wide resource-code lookup. When the user types a
   * code in the manual-resource form that is already used elsewhere,
   * resolve the existing resource's reusable definition so the form can
   * offer "insert the existing resource" vs "create a new one with
   * another code". Returns ``null`` when the code is free. Optional —
   * when omitted the code is treated as a plain free-text field.
   */
  onLookupResourceByCode?: (code: string) => Promise<ResourceCodeMatch | null>;
  onDuplicatePosition?: (positionId: string) => void;
  /**
   * Issue #127 — reuse an existing project code at a given placement.
   * Prompts for the code and creates a linked instance (own ordinal + own
   * editable quantity). `sectionId` scopes the placement when invoked from
   * a section row.
   */
  onReuseCode?: (sectionId?: string) => void;
  /**
   * Issue #136 — add a child Partida under the given position (deep
   * nesting of partidas-within-partidas). Disabled in the UI once the
   * configurable depth cap is reached.
   */
  onAddChildPosition?: (parentId: string) => void;
  /**
   * Issue #136 — add a sub-section under the given section (deep nesting
   * of sections-within-sections). Disabled at the depth cap.
   */
  onAddSubSection?: (parentSectionId: string) => void;
  /**
   * Issue #136 — server-enforced maximum nesting depth (tiers). The grid
   * disables "add child" / "add sub-section" once a row sits at this
   * depth and shows an i18n tooltip explaining the cap.
   */
  maxNestingDepth?: number;
  /** Issue #127 — open the linked-positions modal for a position. */
  onShowLinks?: (positionId: string) => void;
  /** Issue #127 — detach a position from its shared code (value-preserving). */
  onUnlinkPosition?: (positionId: string) => void;
  /** Feature 1 — open the model→quantity binding panel for a position. */
  onModelLink?: (positionId: string) => void;
  /* AI features */
  onSuggestRate?: (positionId: string) => void;
  onClassify?: (positionId: string) => void;
  onCheckAnomalies?: () => void;
  /** Map of position_id → anomaly info, populated from anomaly check */
  anomalyMap?: Map<string, { severity: string; message: string; suggestion: number }>;
  /** Apply the suggested rate from an anomaly to a position */
  onApplyAnomalySuggestion?: (positionId: string, suggestedRate: number) => void;
  /** Save a BOQ position as a reusable assembly */
  onSaveAsAssembly?: (positionId: string) => void;
  /** Custom column definitions from BOQ metadata */
  customColumns?: import('./grid/columnDefs').CustomColumnDef[];
  /**
   * BOQ-scoped named variables ($GFA, $LABOR_RATE, …). Used by `calculated`
   * custom columns; safe to omit when no calculated columns are defined.
   */
  boqVariables?: import('./api').BOQVariable[];
  /** First ready BIM model ID for the project (used for mini 3D preview in ordinal badge). */
  bimModelId?: string | null;
  /** Highlight linked BIM elements in the 3D viewer (triggered from ordinal badge click). */
  onHighlightBIMElements?: (elementIds: string[]) => void;
}

/** Imperative handle exposed by BOQGrid for external control (e.g. clearing selection). */
export interface BOQGridHandle {
  clearSelection: () => void;
  /**
   * Open a freshly-added leaf partida directly in inline edit on its
   * Description cell, so the user types straight away instead of hunting
   * for a cell to click ("Click any cell to edit" UX gap). Polls briefly
   * because the row only materialises after the post-add refetch; a no-op
   * for sections, collapsed/missing rows, or once the retry budget is
   * spent (graceful fall-back to the previous click-to-edit behaviour).
   */
  beginEditDescription: (positionId: string) => void;
}

/* ── Component ─────────────────────────────────────────────────────── */

const BOQGrid = forwardRef<BOQGridHandle, BOQGridProps>(function BOQGrid({
  positions,
  onUpdatePosition,
  onDeletePosition,
  onAddPosition,
  onSelectSuggestion: _onSelectSuggestion,
  onSaveToDatabase,
  onAddComment,
  onFormulaApplied,
  onReorderSections,
  onReorderPositions,
  onDeleteSection,
  collapsedSections,
  onToggleSection,
  highlightPositionId,
  currencySymbol,
  currencyCode,
  fxRates,
  onUpsertProjectFxRate,
  displayCurrency,
  onOpenFxRateSettings,
  locale,
  footerRows,
  onSelectionChanged,
  onActiveRowChange,
  onRemoveResource,
  onUpdateResource,
  onUpdateResourceFields,
  onUpdateResourceCustomField,
  onSaveResourceToCatalog,
  onSaveVariantHeaderToCatalog,
  onOpenCostDbForPosition,
  onOpenCatalogForPosition,
  onRepickResourceVariant,
  onAddManualResource,
  onLookupResourceByCode,
  onDuplicatePosition,
  onReuseCode,
  onAddChildPosition,
  onAddSubSection,
  maxNestingDepth = DEFAULT_MAX_NESTING_DEPTH,
  onShowLinks,
  onUnlinkPosition,
  onModelLink,
  onSuggestRate,
  onClassify,
  // onCheckAnomalies is consumed by BOQToolbar, not directly by the grid
  anomalyMap,
  onApplyAnomalySuggestion,
  onSaveAsAssembly,
  customColumns,
  boqVariables,
  bimModelId,
  onHighlightBIMElements,
}, ref) {
  const { t, i18n } = useTranslation();
  // `t` is a fresh function on every render which would invalidate the
  // `columnDefs` useMemo every render and force AG Grid to rebuild its
  // column model (resets sort, width, pinning state). Mirror the latest
  // `t` into a ref and key the memo on the actual language string instead
  // — v4.3 audit (BOQGrid column-defs thrash).
  const tRef = useRef(t);
  tRef.current = t;
  const navigate = useNavigate();
  const gridRef = useRef<AgGridReact>(null);
  const gridApiRef = useRef<GridApi | null>(null);
  const gridWrapperRef = useRef<HTMLDivElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  // Track all setTimeout(..., 0) handles scheduled to refresh AG Grid cells
  // after a state change (toggle resources, open variant picker, position
  // variant picker). If the component unmounts mid-flight the callback would
  // still fire and call gridApiRef.current.refreshCells on a torn-down grid,
  // which produces silent errors in long-lived sessions. Clearing them in a
  // cleanup effect closes that window.
  const pendingGridRefreshesRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const scheduleGridRefresh = useCallback(
    (columns: string[]) => {
      const id = setTimeout(() => {
        pendingGridRefreshesRef.current.delete(id);
        gridApiRef.current?.stopEditing();
        gridApiRef.current?.refreshCells({ columns, force: true });
      }, 0);
      pendingGridRefreshesRef.current.add(id);
    },
    [],
  );
  useEffect(() => {
    return () => {
      pendingGridRefreshesRef.current.forEach((id) => clearTimeout(id));
      pendingGridRefreshesRef.current.clear();
    };
  }, []);

  /* ── Collaboration locks (layer 1) ───────────────────────────────
   * Per-row soft lock state: positionId -> held lock object.  We
   * acquire on onCellEditingStarted and release on
   * onCellEditingStopped.  A 409 triggers a toast and cancels the
   * in-flight edit.  All lock failures degrade silently so a broken
   * collab service never blocks editing.
   */
  const rowLockMapRef = useRef<Map<string, CollabLock>>(new Map());
  const rowLockPendingRef = useRef<Set<string>>(new Set());
  // Tracks positions whose edit stopped while the acquire was still
  // in-flight.  The .then() callback checks this set and releases
  // immediately instead of storing the lock in rowLockMapRef.
  const rowLockCancelledRef = useRef<Set<string>>(new Set());

  const releaseRowLock = useCallback((positionId: string) => {
    const held = rowLockMapRef.current.get(positionId);
    if (held !== undefined) {
      rowLockMapRef.current.delete(positionId);
      // Fire-and-forget — unmount / row-leave must not await a network call.
      releaseCollabLock(held.id).catch(() => undefined);
      return;
    }
    // If the acquire is still pending, mark for release-on-resolve so
    // the lock does not leak until TTL expiry.
    if (rowLockPendingRef.current.has(positionId)) {
      rowLockCancelledRef.current.add(positionId);
    }
  }, []);

  // Release every held row lock on unmount.
  useEffect(() => {
    const mapRef = rowLockMapRef.current;
    return () => {
      for (const lock of mapRef.values()) {
        releaseCollabLock(lock.id).catch(() => undefined);
      }
      mapRef.clear();
    };
  }, []);

  /* ── Context menu state ──────────────────────────────────────────── */
  interface ContextMenuState {
    x: number;
    y: number;
    type: ContextMenuTarget;
    data: Record<string, unknown>;
  }
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  const showContextMenu = useCallback(
    (e: React.MouseEvent, type: ContextMenuTarget, data: Record<string, unknown>) => {
      e.preventDefault();
      // Position adjusted to not overflow viewport
      const x = Math.min(e.clientX, window.innerWidth - 220);
      const y = Math.min(e.clientY, window.innerHeight - 300);
      setContextMenu({ x, y, type, data });
    },
    [],
  );

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  /* ── Issue #136: depth helpers for the deep-nesting cap ──────────────
   * ``rowTier`` is 1-based (a top-level row is tier 1). Adding a CHILD
   * makes it ``rowTier + 1``; the action is disabled once that would
   * exceed ``maxNestingDepth`` so the UI never lets the user attempt a
   * placement the backend would reject (and shows a tooltip explaining
   * the cap). Single source of truth for the limit: the server. */
  const posDepthMap = useMemo(() => {
    const m = new Map<string, Position>();
    for (const p of positions) m.set(p.id, p);
    return m;
  }, [positions]);

  const rowTier = useCallback(
    (rowId: string): number => {
      const p = posDepthMap.get(rowId);
      if (!p) return 1;
      // getPositionDepth is 0-based ancestor count → +1 for 1-based tier.
      return getPositionDepth(p, posDepthMap) + 1;
    },
    [posDepthMap],
  );

  /** True when a child added under ``rowId`` would breach the cap. */
  const childWouldExceedCap = useCallback(
    (rowId: string): boolean => rowTier(rowId) + 1 > maxNestingDepth,
    [rowTier, maxNestingDepth],
  );

  const depthCapTooltip = t('boq.max_depth_reached_tooltip', {
    defaultValue:
      'Maximum nesting depth of {{max}} levels reached - flatten the structure or use fewer sub-levels.',
    max: maxNestingDepth,
  });

  /* ── Manual resource dialog state ────────────────────────────────── */
  interface ManualResourceDialogState {
    positionId: string;
    name: string;
    type: string;
    unit: string;
    quantity: string;
    unitRate: string;
    /** ISO 4217 — empty string = use project base currency. */
    currency: string;
    /** Issue #133 — reusable resource code; empty = no code. */
    code: string;
    /** Set while the project-wide code lookup is in flight. */
    checkingCode?: boolean;
    /** Set when the typed code is already used — drives the
     *  insert-existing vs change-code prompt instead of submitting. */
    collision?: ResourceCodeMatch | null;
  }
  const [manualResourceDialog, setManualResourceDialog] = useState<ManualResourceDialogState | null>(null);
  const manualResNameRef = useRef<HTMLInputElement>(null);
  const manualResCodeRef = useRef<HTMLInputElement>(null);

  /* ── Expanded resource positions ─────────────────────────────────── */
  const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set());

  const toggleResources = useCallback((positionId: string) => {
    // Stop any active cell editing to prevent ordinal cell staying in edit mode
    gridApiRef.current?.stopEditing();

    setExpandedPositions((prev) => {
      const next = new Set(prev);
      if (next.has(positionId)) {
        next.delete(positionId);
      } else {
        next.add(positionId);
      }
      return next;
    });
    // Force AG Grid to refresh ordinal cells so chevron state updates
    scheduleGridRefresh(['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total']);
  }, [scheduleGridRefresh]);

  /* ── Variant-picker auto-open signal ──────────────────────────────
   *  Triggered by the position-description "V" icon.  We ensure the
   *  position's resource panel is expanded, then stash a one-shot
   *  signal that the matching ``EditableResourceRow`` consumes in a
   *  mount effect to pop its VariantPicker open. The row clears the
   *  signal after consuming so it never re-fires on a re-render. */
  const [openVariantPickerSignal, setOpenVariantPickerSignal] = useState<{
    positionId: string;
    resourceIdx: number;
  } | null>(null);

  const openVariantPickerFor = useCallback(
    (positionId: string, resourceIdx: number) => {
      setExpandedPositions((prev) => {
        if (prev.has(positionId)) return prev;
        const next = new Set(prev);
        next.add(positionId);
        return next;
      });
      setOpenVariantPickerSignal({ positionId, resourceIdx });
      // Same refresh-cells dance as toggleResources so the new resource
      // rows mount on the next tick — the row's mount-time effect then
      // sees the signal and opens the picker.
      scheduleGridRefresh(['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total']);
    },
    [scheduleGridRefresh],
  );

  const clearOpenVariantPicker = useCallback(() => setOpenVariantPickerSignal(null), []);

  /* ── Position-level variant picker ────────────────────────────────
   *  Legacy CWICR position-mode applies stash the variant catalog on
   *  ``position.metadata.cost_item_variants`` (no per-resource cache).
   *  When the user clicks the description "V" icon for such a position,
   *  we render a portal-anchored ``VariantPicker`` directly here against
   *  those catalog entries; ``onApply`` updates the position's
   *  ``unit_rate`` and ``metadata.variant`` via ``onUpdatePosition``. */
  const [positionVariantPicker, setPositionVariantPicker] = useState<{
    positionId: string;
    anchorEl: HTMLElement | null;
  } | null>(null);

  /** Per-position currency dialog (multi-currency BOQ). Lets the user set
   *  ``metadata.currency`` on a leaf position directly — the only entry
   *  point for positions that carry no resources (resource-driven rows set
   *  currency per resource via the inline combobox). Empty code ⇒ reset to
   *  project base currency (drops ``metadata.currency``). */
  const [positionCurrencyDialog, setPositionCurrencyDialog] = useState<{
    positionId: string;
    code: string;
  } | null>(null);

  const commitPositionCurrency = useCallback(() => {
    const dlg = positionCurrencyDialog;
    if (!dlg) return;
    const pos = positions.find((p) => p.id === dlg.positionId);
    if (!pos) {
      setPositionCurrencyDialog(null);
      return;
    }
    const oldMeta = (pos.metadata ?? {}) as Record<string, unknown>;
    const newMeta: Record<string, unknown> = { ...oldMeta };
    const code = dlg.code.trim().toUpperCase();
    // Empty / base currency ⇒ remove the override so the position falls back
    // to the project base currency (keeps metadata clean, matches the
    // backend ``_position_currency`` fallback contract).
    if (!code || code === currencyCode.trim().toUpperCase()) {
      delete (newMeta as { currency?: unknown }).currency;
    } else {
      newMeta.currency = code;
    }
    onUpdatePosition?.(
      pos.id,
      { metadata: newMeta } as UpdatePositionData,
      { metadata: oldMeta } as UpdatePositionData,
    );
    setPositionCurrencyDialog(null);
    scheduleGridRefresh(['unit_rate', 'total']);
  }, [positionCurrencyDialog, positions, onUpdatePosition, currencyCode, scheduleGridRefresh]);

  const openPositionVariantPicker = useCallback(
    (positionId: string, anchorEl: HTMLElement | null) => {
      // Also expand the resource panel so the synthetic variant-header row
      // becomes visible alongside the popover. Mirrors the resource-level V
      // flow for a consistent "click V → see variant + resources" feel.
      setExpandedPositions((prev) => {
        if (prev.has(positionId)) return prev;
        const next = new Set(prev);
        next.add(positionId);
        return next;
      });
      setPositionVariantPicker({ positionId, anchorEl });
      scheduleGridRefresh(['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total']);
    },
    [scheduleGridRefresh],
  );

  const closePositionVariantPicker = useCallback(
    () => setPositionVariantPicker(null),
    [],
  );

  /** Applies a chosen variant to the OPEN position-level picker target.
   *  Mirrors the resource-level repick contract but writes to the
   *  position itself: ``unit_rate`` ← variant.price, ``metadata.variant``
   *  ← chosen marker. ``variant_default`` is dropped on an explicit pick
   *  so the position-level pill reflects the deliberate choice. */
  const applyPositionVariant = useCallback(
    (chosen: CostVariant) => {
      const target = positionVariantPicker;
      if (!target) return;
      const pos = positions.find((p) => p.id === target.positionId);
      if (!pos) {
        setPositionVariantPicker(null);
        return;
      }
      const oldMeta = (pos.metadata ?? {}) as Record<string, unknown>;
      const newMeta: Record<string, unknown> = {
        ...oldMeta,
        variant: { label: chosen.label, price: chosen.price, index: chosen.index },
      };
      delete (newMeta as { variant_default?: unknown }).variant_default;
      onUpdatePosition?.(
        pos.id,
        { unit_rate: chosen.price, metadata: newMeta } as UpdatePositionData,
        pos as unknown as Record<string, unknown>,
      );
      setPositionVariantPicker(null);
    },
    [positionVariantPicker, positions, onUpdatePosition],
  );

  /** Patch the parent position behind a variant-header synthetic row.
   *
   *  Variant qty/price edits land on ``metadata.variant`` AND materialize
   *  a corresponding entry in ``metadata.resources[]`` so the variant
   *  contributes to the position's unit_rate (sum-of-resources) the same
   *  way every other resource does. Per the user's spec: "вариативный
   *  ресурс точно такой же ресурс как и остальные". After the first edit
   *  the synthetic header is suppressed (``hasResourceLevelVariants``
   *  branch) and the variant renders as a regular resource line with its
   *  own re-pick pill. */
  const onUpdateVariantHeader = useCallback(
    (positionId: string, fields: { quantity?: number; unit_rate?: number }) => {
      const pos = positions.find((p) => p.id === positionId);
      if (!pos) return;
      if (fields.quantity == null && fields.unit_rate == null) return;

      const oldMeta = (pos.metadata ?? {}) as Record<string, unknown>;
      const oldVariant = (oldMeta.variant ?? {}) as Record<string, unknown>;
      const newVariant: Record<string, unknown> = { ...oldVariant };

      if (fields.quantity != null) newVariant.quantity = fields.quantity;
      if (fields.unit_rate != null) newVariant.price = fields.unit_rate;
      if (typeof newVariant.label !== 'string') newVariant.label = 'manual';
      if (typeof newVariant.index !== 'number') newVariant.index = -1;

      // Materialize / update the variant as a real entry in resources[].
      const oldResources = ((oldMeta.resources as Array<Record<string, unknown>>) ?? []).slice();
      const variantsList = oldMeta.cost_item_variants as
        | Array<Record<string, unknown>> | undefined;
      const variantStats = oldMeta.cost_item_variant_stats as
        | { common_start?: string; unit?: string; unit_localized?: string } | undefined;

      // Identify the existing variant resource by the variant marker, NOT
      // by code/name (the chosen variant label changes between picks). We
      // only treat a row as "the variant" when it currently carries either
      // ``variant`` or ``available_variants`` cached on it.
      const variantResIdx = oldResources.findIndex(
        (r) => Boolean(r?.variant) || Boolean(r?.available_variants),
      );

      const variantQty =
        typeof newVariant.quantity === 'number' ? (newVariant.quantity as number) : 1;
      const variantRate =
        typeof newVariant.price === 'number' ? (newVariant.price as number) : 0;
      const commonStart = (variantStats?.common_start || '').trim();
      const variantLabel = String(newVariant.label || '').trim();
      const composedName = [commonStart, variantLabel].filter(Boolean).join(' ').trim()
        || (pos.description || 'Variant');

      const variantResource: Record<string, unknown> = {
        name: composedName,
        code: (oldMeta.cost_item_code as string) || '',
        type: 'material',
        unit: (variantStats?.unit_localized || variantStats?.unit || pos.unit || 'pcs').trim(),
        quantity: variantQty,
        unit_rate: variantRate,
        total: Math.round(variantQty * variantRate * 100) / 100,
        variant: {
          label: newVariant.label,
          price: variantRate,
          index: newVariant.index,
        },
        available_variants: variantsList,
        available_variant_stats: variantStats,
      };

      if (variantResIdx >= 0) {
        oldResources[variantResIdx] = { ...oldResources[variantResIdx], ...variantResource };
      } else {
        oldResources.push(variantResource);
      }

      // Recompute position unit_rate as Σ(resource.qty × resource.rate) —
      // same convention the backend uses (boq/service.py::update_position
      // with triggered_by_resources). Keeps the displayed total consistent
      // with the resource panel before the server roundtrip.
      const newUnitRate = oldResources.reduce(
        (sum, r) => sum + ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0),
        0,
      );
      const newUnitRateRounded = Math.round(newUnitRate * 10000) / 10000;

      const newMeta: Record<string, unknown> = {
        ...oldMeta,
        variant: newVariant,
        resources: oldResources,
      };
      if ('variant_default' in newMeta) {
        delete newMeta.variant_default;
      }

      onUpdatePosition?.(
        pos.id,
        { metadata: newMeta, unit_rate: newUnitRateRounded },
        pos as unknown as Record<string, unknown>,
      );
    },
    [positions, onUpdatePosition],
  );

  /* ── Imperative handle for parent components ───────────────────── */
  useImperativeHandle(ref, () => ({
    clearSelection: () => {
      gridApiRef.current?.deselectAll();
    },
    beginEditDescription: (positionId: string) => {
      // Open a freshly-added leaf row directly in inline edit on its
      // Description cell. Two-phase, because:
      //  • the row only exists after the post-add refetch (poll for it);
      //  • AG Grid won't edit a row that is virtualised out of the DOM,
      //    so we must ensureNodeVisible, let the scroll/render settle on
      //    a later tick, THEN startEditingCell (calling it synchronously
      //    after ensureNodeVisible is a silent no-op — getEditingCells()
      //    stays empty);
      //  • `stopEditingWhenCellsLoseFocus` is on, so DOM focus still
      //    sitting on the "Add" button tears a fresh editor down — pull
      //    focus into the editor input once it has mounted.
      let attempts = 0;
      const MAX = 30;
      const step = (): void => {
        if (attempts++ > MAX) return; // give up → click-to-edit fallback
        const api = gridApiRef.current;
        if (!api) { window.setTimeout(step, 150); return; }
        // Always RE-RESOLVE by id: invalidateAll() can trigger a second
        // refetch that rebuilds the row model, so any rowIndex captured
        // on an earlier tick is stale and startEditingCell would no-op.
        const node = api.getRowNode(positionId);
        const rowIndex = node?.rowIndex;
        if (
          !node ||
          typeof rowIndex !== 'number' ||
          rowIndex < 0 ||
          node.data?._isSection ||
          node.data?._isFooter
        ) {
          window.setTimeout(step, 150);
          return;
        }
        // Edit only succeeds once the row is actually rendered into the
        // DOM (AG Grid virtualises far rows). Ensure it is visible, then
        // confirm the cell element exists before starting the editor.
        api.ensureNodeVisible(node, 'middle');
        const cell = document.querySelector(
          `.ag-row[row-id="${positionId}"] .ag-cell[col-id="description"]`,
        );
        if (!cell) { window.setTimeout(step, 120); return; }
        api.setFocusedCell(rowIndex, 'description');
        api.startEditingCell({ rowIndex, colKey: 'description' });
        if (api.getEditingCells().length === 0) {
          // Still mid-scroll/rebuild — retry the whole cycle.
          window.setTimeout(step, 150);
          return;
        }
        // `stopEditingWhenCellsLoseFocus` is on: focus still on the
        // toast / "Add" button would tear the fresh editor down — pull
        // focus into the editor input once it has mounted.
        window.requestAnimationFrame(() => {
          const editor = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(
            '.ag-cell.ag-cell-inline-editing input, .ag-cell.ag-cell-inline-editing textarea',
          );
          if (editor) {
            editor.focus();
            editor.select?.();
          }
        });
      };
      step();
    },
  }), []);

  const fmt = useMemo(
    () =>
      new Intl.NumberFormat(locale || getIntlLocale(), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
    [locale],
  );

  /* ── Context for column formatters + section group + resources + actions */
  const gridContext = useMemo(
    () => ({
      currencySymbol,
      currencyCode,
      fxRates: fxRates ?? [],
      onUpsertProjectFxRate,
      // Issue #88 — display-currency view-only override. The
      // `totalFormatter` in columnDefs reads this and reformats every
      // aggregate (footer rows, section subtotals, per-position totals)
      // through the configured rate. Null when the user is on base.
      displayCurrency: displayCurrency ?? null,
      onOpenFxRateSettings,
      locale,
      fmt,
      t,
      collapsedSections,
      onToggleSection,
      onAddPosition,
      onAddSubSection,
      expandedPositions,
      onToggleResources: toggleResources,
      onRemoveResource: onRemoveResource ?? (() => {}),
      onUpdateResource: onUpdateResource ?? (() => {}),
      onUpdateResourceFields,
      onSaveResourceToCatalog: onSaveResourceToCatalog ?? (() => {}),
      onSaveVariantHeaderToCatalog,
      onOpenCostDbForPosition: onOpenCostDbForPosition ?? (() => {}),
      onOpenCatalogForPosition: onOpenCatalogForPosition ?? (() => {}),
      onRepickResourceVariant,
      openVariantPickerFor: openVariantPickerSignal,
      onClearOpenVariantPicker: clearOpenVariantPicker,
      onOpenVariantPickerFor: openVariantPickerFor,
      onOpenPositionVariantPicker: openPositionVariantPicker,
      onUpdateVariantHeader,
      onDeletePosition,
      onSaveToDatabase,
      onAddComment: onAddComment ?? (() => {}),
      onAddManualResource: (positionId: string) => {
        setManualResourceDialog({
          positionId, name: '', type: 'material', unit: 'm²', quantity: '1', unitRate: '0',
          currency: '', // empty ⇒ use project base currency
          code: '',
        });
        setTimeout(() => manualResNameRef.current?.focus(), 50);
      },
      onDuplicatePosition: onDuplicatePosition ?? (() => {}),
      onShowContextMenu: showContextMenu,
      anomalyMap,
      onApplyAnomalySuggestion,
      bimModelId,
      onUpdatePosition,
      onHighlightBIMElements,
      onDeleteSection: onDeleteSection ?? (() => {}),
      onReorderSections: onReorderSections ?? (() => {}),
      // Issue #90: FormulaCellEditor reads onFormulaApplied via context
      // because the Quantity column doesn't supply cellEditorParams.
      onFormulaApplied,
      // v2.9.29 — full-width resource rows iterate `customColumns` to
      // render slots aligned with regional-preset columns; reading
      // `positions` lets the renderer surface per-resource custom_fields
      // values without a network round-trip.
      positions,
      customColumns,
    }) as FullGridContext,
    [currencySymbol, currencyCode, fxRates, onUpsertProjectFxRate, displayCurrency, onOpenFxRateSettings, locale, fmt, t, collapsedSections, onToggleSection, onAddPosition, onAddSubSection,
     expandedPositions, toggleResources, onRemoveResource, onUpdateResource, onUpdateResourceFields,
     onSaveResourceToCatalog, onSaveVariantHeaderToCatalog, onOpenCostDbForPosition, onOpenCatalogForPosition, onRepickResourceVariant,
     openVariantPickerSignal, openVariantPickerFor, clearOpenVariantPicker, openPositionVariantPicker, onUpdateVariantHeader,
     onDeletePosition, onSaveToDatabase, onAddComment,
     onDuplicatePosition, showContextMenu, anomalyMap, onApplyAnomalySuggestion, bimModelId,
     onUpdatePosition, onHighlightBIMElements, onDeleteSection, onReorderSections, onFormulaApplied,
     positions, customColumns],
  );

  /* ── Column defs (standard + custom) ─────────────────────────────── */
  const columnDefs = useMemo(() => {
    const defs = getColumnDefs({ currencySymbol, currencyCode, locale, fmt, t: tRef.current, displayCurrency: displayCurrency ?? null });
    // Override ordinal column with custom renderer
    const ordinalCol = defs.find((c) => c.field === 'ordinal');
    if (ordinalCol) {
      ordinalCol.cellRenderer = OrdinalCellRenderer;
      ordinalCol.cellRendererSelector = (params: { data?: { _isSection?: boolean; _isFooter?: boolean } }) => {
        if (params.data?._isSection || params.data?._isFooter) return undefined;
        return { component: OrdinalCellRenderer };
      };
    }
    // Insert custom columns before _actions column
    if (customColumns && customColumns.length > 0) {
      const actionsIdx = defs.findIndex((c) => c.field === '_actions');
      // v2.7.0/E — `calculated` columns evaluate user-authored formulas
      // against the live positions list + BOQ variables. We project the
      // BOQ-level variables map (UPPER_SNAKE keyed) into the engine's
      // FormulaVariable shape on every column-defs rebuild; AG Grid then
      // calls our valueGetter on every refresh, so changing a position
      // automatically re-runs the calculation (we trigger refreshes via
      // the effect below).
      const variablesMap = new Map<string, FormulaVariable>();
      if (boqVariables) {
        for (const v of boqVariables) {
          variablesMap.set(v.name.toUpperCase(), { type: v.type, value: v.value });
        }
      }
      const customDefs = getCustomColumnDefs(customColumns, {
        positions,
        variables: variablesMap,
      });
      if (actionsIdx >= 0) {
        defs.splice(actionsIdx, 0, ...customDefs);
      } else {
        defs.push(...customDefs);
      }
    }
    return defs;
  }, [currencySymbol, currencyCode, locale, fmt, i18n.language, customColumns, positions, boqVariables, displayCurrency]);

  /* ── Calculated-column refresh on positions change ──────────────────
   * AG Grid re-runs `valueGetter` on every refresh; for cross-position
   * formulas (e.g. `=pos("01.005").qty / quantity`) we must explicitly
   * invalidate the calculated cells whenever the positions array changes.
   * This is cheap — `refreshCells` only touches the listed columns. */
  useEffect(() => {
    if (!gridApiRef.current) return;
    if (!customColumns || customColumns.length === 0) return;
    const calculatedCols = customColumns
      .filter((c) => c.column_type === 'calculated')
      .map((c) => `custom_${c.name}`);
    if (calculatedCols.length === 0) return;
    gridApiRef.current.refreshCells({ columns: calculatedCols, force: true });
  }, [positions, boqVariables, customColumns]);

  /* ── Re-fit columns when count grows (preset applied) ────────────────
   * Adding a regional preset (GAEB, ÖNORM, MasterFormat, …) drops 5–6
   * new columns into the grid. Without re-fitting, the cumulative width
   * exceeds the viewport and forces a horizontal scrollbar. Re-fit only
   * when the count GROWS so we don't clobber a width the user dragged. */
  const prevCustomColCount = useRef<number>(customColumns?.length ?? 0);
  useEffect(() => {
    const next = customColumns?.length ?? 0;
    const prev = prevCustomColCount.current;
    prevCustomColCount.current = next;
    if (gridApiRef.current && next > prev) {
      // Two rAFs — AG Grid v32 commits new columnDefs in the next frame,
      // and sizeColumnsToFit needs them committed to know the new widths.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => gridApiRef.current?.sizeColumnsToFit());
      });
    }
  }, [customColumns]);

  /* ── Display-currency refresh (Issue #88) ────────────────────────────
   * When the user flips the active display currency the column-defs
   * memo rebuilds (it depends on `displayCurrency`), but AG Grid keeps
   * the prior formatted strings cached for already-rendered cells.
   * Force a cell refresh on the total column so every footer / section
   * subtotal / per-position total reformats in lock-step.
   *
   * Full-width section rows are NOT part of the `total` column — they
   * render through SectionFullWidthRenderer, which reads `_subtotal` and
   * divides by `displayCurrency.rate` itself. `refreshCells` does not
   * reach them, so without an explicit redraw the section subtotals
   * stay frozen at the previous currency. That was the regression
   * reported on multi-currency BOQs (Spanish video, nested HIJO_*
   * sections showing 0.00 in ARS while the grand total updated).
   *
   * Bug #220 follow-up: the same caching trap fires when a resource's
   * currency is edited inline. The `rowData` memo recomputes the new
   * `_subtotal` (via `resourceAwareTotalInBase`), but AG Grid keeps the
   * previously-rendered section banner mounted — its React instance
   * isn't told to re-read `data._subtotal` until the section row is
   * collapsed/re-expanded. The section subtotal therefore stays stale
   * (in the old currency / wrong base value) after an inline currency
   * swap. A second effect (further down, once `rowData` is in scope)
   * fingerprints the section subtotals and redraws the banners whenever
   * any of them actually changes.
   */
  useEffect(() => {
    const api = gridApiRef.current;
    if (!api) return;
    api.refreshCells({ columns: ['total'], force: true });
    const sectionNodes: unknown[] = [];
    api.forEachNode((node: unknown) => {
      const data = (node as { data?: { _isSection?: boolean } } | null)?.data;
      if (data?._isSection) sectionNodes.push(node);
    });
    if (sectionNodes.length > 0) {
      api.redrawRows({ rowNodes: sectionNodes as never[] });
    }
    api.refreshHeader();
  }, [displayCurrency?.code, displayCurrency?.rate]);

  /* ── Helper: insert resource sub-rows after an expanded position ── */
  const insertResourceRows = useCallback((rows: GridRow[], pos: Position, depth = 0) => {
    // Shallow-copy so attaching the tree-depth marker never mutates the
    // React Query-cached Position object (Issue #136).
    rows.push({ ...pos, _depth: depth } as GridRow);

    if (!expandedPositions.has(pos.id)) return;

    const meta = (pos.metadata ?? {}) as Record<string, unknown>;

    // Synthetic variant-header row — only for positions that carry
    // ``cost_item_variants`` at position level (legacy CWICR position-mode).
    // Acts as the "variant resource" the user expects to see among the
    // components: V badge prominent, click → reopen position-level picker.
    const posVariants = meta.cost_item_variants as Array<{
      index: number; label: string; price: number;
    }> | undefined;
    const posVariantStats = meta.cost_item_variant_stats as
      | { common_start?: string; unit?: string; unit_localized?: string }
      | undefined;
    const posChosenVariant = meta.variant as
      | { label?: string; price?: number; index?: number; quantity?: number }
      | undefined;
    const hasPositionLevelVariants = Array.isArray(posVariants) && posVariants.length >= 2;
    // When the resources list already carries one or more entries with their
    // own ``available_variants``, those entries render their own per-resource
    // picker pill in EditableResourceRow and the position-level synthetic
    // header would just duplicate them. Suppress the header in that case so
    // a position can host MANY variant resources cleanly — each resource
    // line is its own variant with its own picker. (User spec 2026-04-30:
    // "у позиции может быть много вариативных ресурсов".)
    const resourcesArr = (meta.resources as Array<Record<string, unknown>> | undefined) ?? [];
    const hasResourceLevelVariants = resourcesArr.some((r) => {
      const av = r?.available_variants;
      return Array.isArray(av) && av.length >= 2;
    });
    if (hasPositionLevelVariants && !hasResourceLevelVariants) {
      // Variant header name = ONLY the abstract base
      // (``price_abstract_resource_common_start``). NEVER fall back to
      // the position description — the variant resource must carry its
      // own catalog identity, not duplicate the parent position's text.
      // When ``common_start`` wasn't captured (legacy / pre-v2.6.30
      // imports) we leave it empty so the synthetic row only shows the
      // chosen variant label (or the "Variant" chip when nothing's picked).
      const headerName =
        (posVariantStats?.common_start && posVariantStats.common_start.trim()) || '';
      const headerRow: VariantHeaderRow = {
        _isVariantHeader: true,
        _parentPositionId: pos.id,
        _variantHeaderName: headerName,
        _variantHeaderChosenLabel: posChosenVariant?.label ?? null,
        _variantHeaderChosenPrice: typeof posChosenVariant?.price === 'number'
          ? posChosenVariant.price
          : null,
        _variantHeaderCount: posVariants!.length,
        _variantHeaderCurrency: (meta.currency as string | undefined) || currencyCode,
        // Variant resource qty is stored INDEPENDENTLY of the position qty
        // (per the user's spec: "Объём вариативного ресурса никак не
        // связан с объёмом позиции"). When ``metadata.variant.quantity``
        // hasn't been set (legacy pre-decouple imports OR brand-new pick),
        // default to 1 — the per-unit norm convention used by every other
        // resource line. Falling back to ``pos.quantity`` here was the bug
        // that made the variant row APPEAR to track the position's qty.
        _variantHeaderQty:
          typeof posChosenVariant?.quantity === 'number'
            ? posChosenVariant.quantity
            : 1,
        // Unit is sourced from the variant catalog itself (the average /
        // baseline value the CWICR row was estimated against), not from
        // the position. Falls back to the position unit when the variant
        // catalog doesn't carry one (older imports).
        _variantHeaderUnit:
          (posVariantStats?.unit_localized && posVariantStats.unit_localized.trim()) ||
          (posVariantStats?.unit && posVariantStats.unit.trim()) ||
          (pos.unit ?? ''),
        id: `${pos.id}_variant_header`,
        description: '',
        ordinal: '',
        unit: '',
        quantity: 0,
        unit_rate: 0,
        total: 0,
      };
      rows.push(headerRow as GridRow);
    }

    const resources = (pos.metadata?.resources ?? []) as Array<{
      name: string; code?: string; type: string;
      unit: string; quantity: number; unit_rate: number; total?: number;
      currency?: string;
      // CWICR variant fields (v2.6.26+) — surfaced to EditableResourceRow
      // so the re-pick pill can render and the user's explicit pick can
      // be marked vs an auto-default.
      available_variants?: Array<Record<string, unknown>>;
      available_variant_stats?: Record<string, unknown>;
      variant?: { label: string; price: number; index: number };
      variant_default?: 'mean' | 'median';
      variant_snapshot?: Record<string, unknown>;
    }>;
    if (resources.length === 0) return;

    // Variant-catalog dedupe at render time. Two scenarios collapse here:
    //
    //   1. CWICR ships two components with the same ``resource_code`` (e.g.
    //      KADX_KATO_KAKASA_KATO has two rows under KALI-RI-KATO-KANE with
    //      identical 3-variant catalogs).
    //   2. The cost item's TOP-LEVEL variant catalog was persisted as a
    //      synthetic extra resource AND one of its components already carries
    //      the same 8-variant catalog (real BG_SOFIA shape — рате surfaces
    //      "Стоманени конструкции" both as the cost item's variants and as
    //      component[0]).
    //
    // Both manifest as multiple resource rows showing identical ▾N pills.
    // Strip ``available_variants`` from every row whose catalog already
    // appeared on an earlier row (matched by either ``resource_code`` or by
    // variant-label-set hash) so only ONE picker is rendered per unique
    // catalog. ``BOQModals.tsx`` does the same dedupe at apply-time, but
    // legacy positions persisted before that landed need this safety net.
    const variantPrimaryByCode = new Map<string, number>();
    const variantPrimaryByHash = new Map<string, number>();

    let resTotal = 0;
    for (let i = 0; i < resources.length; i++) {
      const r = resources[i]!;
      const rTotal = r.total ?? r.quantity * r.unit_rate;
      // Issue #111 (skolodi follow-up) — the per-position resource
      // subtotal (``_positionResourceTotal``, rendered on the
      // "Add resource" row) is one of the TWO places the contributor
      // circled where a USD-priced resource in an ARS project showed
      // its raw foreign number as if it were base. Convert each
      // resource's contribution via its own currency before summing so
      // the subtotal is stated in the project base currency. Resource
      // currency wins; absent ⇒ project base (no conversion).
      const rCcy = (r.currency || '').trim() || currencyCode;
      resTotal += convertToBase(rTotal, rCcy, currencyCode, fxRates ?? null);

      const hasVariantCatalog =
        Array.isArray(r.available_variants) && r.available_variants.length >= 2;
      let variantsForThisRow = r.available_variants;
      let variantStatsForThisRow = r.available_variant_stats;
      if (hasVariantCatalog) {
        const code = (r.code || '').trim();
        const labelHash = (r.available_variants ?? [])
          .map((v) => ((v as { label?: string }).label || '').trim())
          .join('|');
        const codePrimary = code ? variantPrimaryByCode.get(code) : undefined;
        const hashPrimary = labelHash
          ? variantPrimaryByHash.get(labelHash)
          : undefined;
        if (codePrimary !== undefined && codePrimary !== i) {
          variantsForThisRow = undefined;
          variantStatsForThisRow = undefined;
        } else if (hashPrimary !== undefined && hashPrimary !== i) {
          variantsForThisRow = undefined;
          variantStatsForThisRow = undefined;
        } else {
          if (code) variantPrimaryByCode.set(code, i);
          if (labelHash) variantPrimaryByHash.set(labelHash, i);
        }
      }

      const resRow: ResourceRow = {
        _isResource: true,
        _parentPositionId: pos.id,
        _resourceIndex: i,
        _resourceName: r.name,
        _resourceType: r.type || 'other',
        _resourceUnit: r.unit,
        _resourceQty: r.quantity,
        _resourceRate: r.unit_rate,
        _resourceCurrency: r.currency,
        _resourceCode: r.code,
        _resourceAvailableVariants: variantsForThisRow,
        _resourceAvailableVariantStats: variantStatsForThisRow,
        _resourceVariant: r.variant,
        _resourceVariantDefault: r.variant_default,
        _resourceVariantSnapshot: r.variant_snapshot,
        id: `${pos.id}_res_${i}`,
        description: r.name,
        ordinal: '',
        unit: r.unit,
        quantity: r.quantity,
        unit_rate: r.unit_rate,
        total: rTotal,
      };
      rows.push(resRow as GridRow);
    }

    // "Add resource" row at the bottom
    const addRow: AddResourceRow = {
      _isAddResource: true,
      _parentPositionId: pos.id,
      _positionResourceTotal: resTotal,
      id: `${pos.id}_add_res`,
      description: '',
      ordinal: '',
      unit: '',
      quantity: 0,
      unit_rate: 0,
      total: 0,
    };
    rows.push(addRow as GridRow);
    // ``fxRates`` added (Issue #111) — the resource subtotal now depends
    // on the project FX table, so an FX-rate edit must recompute it.
  }, [expandedPositions, currencyCode, fxRates]);

  /* ── Build row data from positions ────────────────────────────── */
  const rowData: GridRow[] = useMemo(() => {
    const num = (v: unknown): number => {
      const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''));
      return Number.isFinite(n) ? n : 0;
    };

    // Issue #111 (skolodi follow-up) — rebase a position's total into the
    // project base before it contributes to any (possibly nested) section
    // subtotal. ``resourceAwareTotalInBase`` converts BOTH a position-level
    // ``metadata.currency`` (the verified #131 path) AND the
    // previously-missed case the contributor circled: a position with NO
    // ``metadata.currency`` but USD-priced ``metadata.resources`` (its
    // stored total was built from Σ(r.qty×r.rate) with no FX applied).
    const rebase = (pos: Position): number => {
      if (!currencyCode) return num(pos.total);
      return resourceAwareTotalInBase(
        pos as unknown as {
          total?: number | string | null;
          quantity?: number | string | null;
          metadata?: Record<string, unknown> | null;
        },
        currencyCode,
        fxRates,
      );
    };

    // Issue #136 — render the TRUE section tree. The previous flat grouping
    // only ever attached non-section positions to a single section level, so
    // a section nested under another section (sub-section) was dropped from
    // the tree entirely — it surfaced only as a stray row and the hierarchy
    // was invisible. We now walk parent_id recursively. A position whose
    // parent_id is missing or dangling is treated as a root so nothing can
    // silently vanish from the смета.
    const byId = new Map<string, Position>();
    for (const p of positions) byId.set(p.id, p);
    const childrenOf = new Map<string | null, Position[]>();
    for (const p of positions) {
      const pid = p.parent_id && byId.has(p.parent_id) ? p.parent_id : null;
      const arr = childrenOf.get(pid) ?? [];
      arr.push(p);
      childrenOf.set(pid, arr);
    }
    const sortSiblings = (arr: Position[]): Position[] =>
      [...arr].sort((a, b) => {
        if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
        return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
      });

    // Section subtotal = Σ rebased line totals of every descendant
    // position, recursing through any number of nested sub-sections.
    const subtotalCache = new Map<string, number>();
    const subtotalOf = (sec: Position): number => {
      const cached = subtotalCache.get(sec.id);
      if (cached !== undefined) return cached;
      let sum = 0;
      for (const child of childrenOf.get(sec.id) ?? []) {
        sum += isSection(child) ? subtotalOf(child) : rebase(child);
      }
      subtotalCache.set(sec.id, sum);
      return sum;
    };

    // Issue #157 (skolodi): a section's subtotal can be silently
    // wrong when one of its descendants has a resource priced in a
    // currency the project has no FX rate for — the local rebase
    // ``resourceAwareTotalInBase`` returns the value unconverted, so
    // changing EUR→USD-without-rate produces an identical sum and
    // the user reports "didn't update". Bubble the missing codes up
    // the tree so the section banner can render an amber "FX missing
    // — section total may be incorrect" badge next to the subtotal.
    const fxWarningsCache = new Map<string, string[]>();
    const collectFxWarnings = (pos: Position): string[] => {
      const cached = fxWarningsCache.get(pos.id);
      if (cached !== undefined) return cached;
      const base = (currencyCode || '').trim().toUpperCase();
      const have = new Set((fxRates ?? []).map((r) => r.currency.toUpperCase()));
      const codes = new Set<string>();
      if (isSection(pos)) {
        for (const child of childrenOf.get(pos.id) ?? []) {
          for (const c of collectFxWarnings(child)) codes.add(c);
        }
      } else {
        const meta = (pos.metadata ?? null) as Record<string, unknown> | null;
        const resources = meta?.resources;
        if (Array.isArray(resources)) {
          for (const r of resources) {
            if (!r || typeof r !== 'object') continue;
            const code = String((r as { currency?: unknown }).currency ?? '')
              .trim()
              .toUpperCase();
            if (!code || code === base) continue;
            if (have.has(code)) continue;
            codes.add(code);
          }
        }
        // Also consider a position whose own metadata.currency is set
        // to a foreign code without an FX rate — same silent no-op
        // semantics in ``convertToBase``.
        const posCode = String((meta?.currency as string | undefined) ?? '')
          .trim()
          .toUpperCase();
        if (posCode && posCode !== base && !have.has(posCode)) {
          codes.add(posCode);
        }
      }
      const out = Array.from(codes).sort();
      fxWarningsCache.set(pos.id, out);
      return out;
    };

    const rows: GridRow[] = [];
    const emit = (pos: Position, depth: number): void => {
      if (isSection(pos)) {
        const kids = sortSiblings(childrenOf.get(pos.id) ?? []);
        const subtotal = subtotalOf(pos);
        const fxWarnings = collectFxWarnings(pos);
        rows.push({
          ...pos,
          _isSection: true,
          _depth: depth,
          _childCount: kids.length,
          _subtotal: subtotal,
          _fxWarnings: fxWarnings,
          total: subtotal,
        } as GridRow);
        if (collapsedSections.has(pos.id)) return;
        for (const child of kids) emit(child, depth + 1);
      } else {
        insertResourceRows(rows, pos, depth);
      }
    };

    for (const root of sortSiblings(childrenOf.get(null) ?? [])) emit(root, 0);
    return rows;
  }, [positions, collapsedSections, insertResourceRows, currencyCode, fxRates]);

  /* ── Bug #220: redraw section banners when subtotals change ───────────
   * Mirror of the displayCurrency effect above, but keyed on the actual
   * section subtotals so an inline resource-currency swap (which leaves
   * the position's stored `unit_rate`/`total` untouched and only updates
   * `metadata.resources[i].currency`) repaints the full-width section
   * row. Without this, `rowData` carries the freshly rebased subtotal
   * but the previously-mounted `SectionFullWidthRenderer` instance keeps
   * the old value on screen until the user collapses + re-expands the
   * section — the "close + reopen → updates" smoking gun from #220.
   */
  const sectionSubtotalFingerprint = useMemo(
    () =>
      rowData
        .filter((r) => Boolean((r as { _isSection?: boolean })._isSection))
        .map(
          (r) =>
            `${(r as { id: string }).id}:${(r as { _subtotal?: number })._subtotal ?? 0}`,
        )
        .join('|'),
    [rowData],
  );

  useEffect(() => {
    const api = gridApiRef.current;
    if (!api) return;
    const sectionNodes: unknown[] = [];
    api.forEachNode((node: unknown) => {
      const data = (node as { data?: { _isSection?: boolean } } | null)?.data;
      if (data?._isSection) sectionNodes.push(node);
    });
    if (sectionNodes.length > 0) {
      api.redrawRows({ rowNodes: sectionNodes as never[] });
    }
  }, [sectionSubtotalFingerprint]);

  /* ── Pinned bottom rows (footer) ──────────────────────────────── */
  const pinnedBottomRowData = useMemo(() => footerRows, [footerRows]);

  /* ── Row ID ───────────────────────────────────────────────────── */
  const getRowId = useCallback(
    (params: GetRowIdParams) => params.data?.id ?? params.data?._footerType ?? '',
    [],
  );

  /* ── Row class rules ──────────────────────────────────────────── */
  const getRowClass = useCallback((params: RowClassParams) => {
    const classes: string[] = [];
    if (params.data?._isSection) {
      classes.push(
        'oe-section-group-row',
        'bg-surface-secondary/70',
        'border-t-2',
        'border-border',
        'font-bold',
      );
    }
    if (params.data?._isFooter) {
      classes.push('bg-surface-tertiary/50', 'border-t', 'border-border');
    }
    if (params.data?._isResource || params.data?._isAddResource || params.data?._isVariantHeader) {
      classes.push('oe-resource-row');
    }
    // Add 'group' to regular position rows so hover actions (save/delete) appear on hover
    if (!params.data?._isSection && !params.data?._isFooter && !params.data?._isResource && !params.data?._isAddResource && !params.data?._isVariantHeader) {
      classes.push('group');

      // Highlight unpriced positions (unit_rate is 0/empty) so the user can
      // see at a glance what still needs work. Skip resource sub-rows and
      // section headers — only real position rows.
      const rate = Number(params.data?.unit_rate ?? 0);
      const qty = Number(params.data?.quantity ?? 0);
      if ((!rate || rate === 0) && qty > 0) {
        classes.push('oe-unpriced-row');
      }

      // Validation status left-border accent for quick scanning
      const validationStatus = params.data?.validation_status as string | undefined;
      if (validationStatus === 'errors') {
        classes.push('boq-row-error');
      } else if (validationStatus === 'warnings') {
        classes.push('boq-row-warning');
      }

      // CWICR abstract-resource left-edge accent. We give the row a 4px
      // colour bar on the leading edge so the user can scan a long BOQ
      // and tell which positions came from a multi-variant cost item:
      //   • Picked variant   → blue (oe-blue, matches the picker chip)
      //   • Auto default     → amber (matches the "default · refine" pill)
      // Only applied when no validation accent is already winning, so an
      // erroring row keeps its red bar instead of being recoloured.
      if (validationStatus !== 'errors' && validationStatus !== 'warnings') {
        const meta = params.data?.metadata as Record<string, unknown> | undefined;
        if (meta) {
          if (meta.variant && typeof meta.variant === 'object') {
            classes.push('boq-row-variant');
          } else if (meta.variant_default === 'mean' || meta.variant_default === 'median') {
            classes.push('boq-row-variant-default');
          }
        }
      }
    }
    return classes.join(' ');
  }, []);

  /* ── Full-width row: sections + resource sub-rows ─────────────── */
  const isFullWidthRow = useCallback(
    (params: IsFullWidthRowParams) => {
      const d = params.rowNode.data;
      return !!d?._isSection || !!d?._isResource || !!d?._isAddResource || !!d?._isVariantHeader;
    },
    [],
  );

  const getRowHeight = useCallback((params: RowHeightParams) => {
    if (params.data?._isSection) return 38;
    if (params.data?._isResource) return 28;
    if (params.data?._isAddResource) return 30;
    if (params.data?._isVariantHeader) return 36;
    return 32;
  }, []);

  /* ── Cancel accidental ordinal edits from chevron clicks ─────── */
  const onCellEditingStarted = useCallback(
    (event: CellEditingStartedEvent) => {
      // Ordinal column is editable:false — editing triggered via onCellDoubleClicked.

      // ── Layer-1 collaboration lock ──────────────────────────────
      // Acquire a soft lock on the row (not the cell) the first
      // time the user enters edit mode on it.  Subsequent cell
      // edits on the same row piggy-back on the existing lock.
      const positionId = event.data?.id;
      if (
        typeof positionId !== 'string' ||
        positionId.length === 0 ||
        event.data?._isSection ||
        event.data?._isFooter
      ) {
        return;
      }
      if (
        rowLockMapRef.current.has(positionId) ||
        rowLockPendingRef.current.has(positionId)
      ) {
        return;
      }
      rowLockPendingRef.current.add(positionId);
      acquireCollabLock('boq_position', positionId, 60)
        .then((result) => {
          rowLockPendingRef.current.delete(positionId);
          if (result.ok) {
            // If editing stopped while the acquire was in-flight,
            // release the lock immediately instead of storing it.
            if (rowLockCancelledRef.current.has(positionId)) {
              rowLockCancelledRef.current.delete(positionId);
              releaseCollabLock(result.lock.id).catch(() => undefined);
              return;
            }
            rowLockMapRef.current.set(positionId, result.lock);
            return;
          }
          // Conflict: cancel the in-flight edit so we cannot
          // overwrite the holder's work.  The hook has already
          // shown a toast.
          try {
            event.api.stopEditing(true);
          } catch {
            // ignore — the user may have already blurred
          }
          addToast({
            type: 'warning',
            title: t('collab_locks.lock_conflict_title', {
              defaultValue: 'Someone is editing this',
            }),
            message: t('collab_locks.lock_conflict_toast', {
              defaultValue:
                'Locked by {{name}}. Try again in {{seconds}} seconds.',
              name: result.conflict.current_holder_name,
              seconds: result.conflict.remaining_seconds,
            }),
          });
        })
        .catch(() => {
          // Network / 5xx — degrade silently so the user can still
          // edit.  The worst case is the existing "last writer
          // wins" behaviour we had before layer 1.
          rowLockPendingRef.current.delete(positionId);
          rowLockCancelledRef.current.delete(positionId);
        });
    },
    [addToast, t],
  );

  const onCellEditingStopped = useCallback(
    (event: CellEditingStoppedEvent) => {
      const positionId = event.data?.id;
      if (typeof positionId !== 'string' || positionId.length === 0) return;
      // Release on stop — the user has either committed or cancelled
      // the edit.  If they immediately start editing another cell on
      // the same row, onCellEditingStarted will re-acquire.
      releaseRowLock(positionId);
    },
    [releaseRowLock],
  );

  /* ── Cell value changed → dispatch update ─────────────────────── */
  const onCellValueChanged = useCallback(
    (event: CellValueChangedEvent) => {
      const { data, colDef, oldValue } = event;
      let { newValue } = event;
      if (!data?.id || data._isFooter) return;

      // Detect custom columns by `colId` (set by getCustomColumnDefs
      // to ``custom_<name>``). Doing this BEFORE the standard-field
      // dispatch means a custom column can never accidentally be
      // routed through the standard `update[field]` path, even if a
      // future refactor changes the field string. The column name
      // we write to `metadata.custom_fields` comes from `colId`, not
      // from string-stripping `field` — so two columns can never
      // alias onto the same key.
      const colId = event.column?.getColId() ?? colDef.colId ?? '';
      if (typeof colId === 'string' && colId.startsWith('custom_')) {
        const colName = colId.slice('custom_'.length);
        if (!colName) return;
        if (oldValue === newValue) return;
        // Resource sub-row: route through the per-resource custom-field
        // handler so the value lands in
        // ``parent.metadata.resources[i].metadata.custom_fields[name]``
        // instead of trying to PATCH the synthetic resource row id
        // (``${posId}_res_${idx}`` — which the backend doesn't know).
        if (data._isResource) {
          const posId = data._parentPositionId as string | undefined;
          const resIdx = data._resourceIndex as number | undefined;
          if (!posId || resIdx == null) return;
          onUpdateResourceCustomField?.(
            posId,
            resIdx,
            colName,
            newValue as string | number,
          );
          return;
        }
        const meta = (data.metadata as Record<string, unknown>) ?? {};
        const cf = (meta.custom_fields as Record<string, unknown> | undefined) ?? {};
        const customFields = { ...cf, [colName]: newValue };
        const updatedMeta = { ...meta, custom_fields: customFields };
        const oldMeta = { ...meta, custom_fields: { ...cf } };
        onUpdatePosition(data.id, { metadata: updatedMeta }, { metadata: oldMeta });
        return;
      }

      const field = colDef.field;
      if (!field) return;

      // Unit column uses a custom ``valueSetter`` (see columnDefs.ts +
      // cellEditors.tsx) that drains a StrictMode-proof commit channel
      // and writes the picked value directly to ``data.unit``. AG Grid
      // still emits the event's ``newValue`` from the editor's
      // (possibly stale) ``getValue()`` — so for the unit column we
      // trust the post-setter value on ``data`` instead.
      if (field === 'unit') {
        newValue = (data as Record<string, unknown>).unit;
      }

      if (oldValue === newValue) return;

      const update: UpdatePositionData = { [field]: newValue };
      const old: UpdatePositionData = { [field]: oldValue };

      // Position quantity is a multiplier on the per-unit unit_rate.
      // Resources are stored as PER-UNIT norms (qty per 1 unit of
      // position) — same convention as integrated 5D estimating suites —
      // so changing position qty must NOT touch resource qty/rate or
      // unit_rate. Backend re-derives total = qty × unit_rate.
      if (field === 'quantity') {
        const parsedNew = typeof newValue === 'number' ? newValue : parseFloat(newValue) || 0;
        const parsedOld = typeof oldValue === 'number' ? oldValue : parseFloat(oldValue) || 0;
        update.quantity = parsedNew;
        old.quantity = parsedOld;
      }

      onUpdatePosition(data.id, update, old);
    },
    [onUpdatePosition, onUpdateResourceCustomField],
  );

  /* ── Row drag end → reorder sections or positions ────────────── */
  const handleRowDragEnd = useCallback(
    (event: RowDragEndEvent) => {
      const movedData = event.node.data;
      const overData = event.overNode?.data;
      if (!movedData || !overData) return;

      // Skip footer rows entirely
      if (movedData._isFooter || overData._isFooter) return;

      // Section-to-section reorder
      if (movedData._isSection && overData._isSection && onReorderSections) {
        onReorderSections(movedData.id, overData.id);
        return;
      }

      // Position reorder within the grid
      if (!movedData._isSection && onReorderPositions) {
        const api = gridApiRef.current;
        if (!api) return;

        // Determine the new parent section (closest section above the drop target)
        let newParentId: string | null = null;
        const overIndex = event.overNode?.rowIndex ?? 0;
        api.forEachNode((node) => {
          if (node.data?._isSection && (node.rowIndex ?? 0) <= overIndex) {
            newParentId = node.data.id;
          }
        });

        // If parent changed, update position's parent_id first
        if (newParentId && movedData.parent_id !== newParentId && onUpdatePosition) {
          onUpdatePosition(movedData.id, { parent_id: newParentId }, { parent_id: movedData.parent_id });
        }

        // Collect the current row order from the grid (excluding footer and section rows)
        const reorderedIds: string[] = [];
        api.forEachNode((node) => {
          if (node.data && !node.data._isFooter && !node.data._isSection && node.data.id) {
            reorderedIds.push(node.data.id);
          }
        });

        if (reorderedIds.length > 0) {
          onReorderPositions(reorderedIds);
        }
      }
    },
    [onReorderSections, onReorderPositions, onUpdatePosition],
  );

  /* ── Column resize → persist widths to localStorage ──────────── */
  const handleColumnResized = useCallback((event: ColumnResizedEvent) => {
    if (!event.finished || !event.column) return;
    const colId = event.column.getColId();
    const width = event.column.getActualWidth();
    const existing = loadColumnWidths();
    existing[colId] = width;
    saveColumnWidths(existing);
  }, []);

  /* ── Grid ready ───────────────────────────────────────────────── */
  const onGridReady = useCallback((event: GridReadyEvent) => {
    gridApiRef.current = event.api;

    // Restore persisted column widths
    const saved = loadColumnWidths();
    const entries = Object.entries(saved);
    if (entries.length > 0) {
      const stateItems = entries.map(([colId, width]) => ({ colId, width }));
      event.api.applyColumnState({ state: stateItems, applyOrder: false });
    } else {
      event.api.sizeColumnsToFit();
    }
  }, []);

  /* ── Highlight position ───────────────────────────────────────── */
  useEffect(() => {
    if (!highlightPositionId || !gridApiRef.current) return;
    const api = gridApiRef.current;
    const rowNode = api.getRowNode(highlightPositionId);
    if (rowNode) {
      api.ensureNodeVisible(rowNode, 'middle');
      api.flashCells({ rowNodes: [rowNode] });
    }
  }, [highlightPositionId]);

  /* ── Selection changed → notify parent ────────────────────────── */
  const handleSelectionChanged = useCallback(
    (event: SelectionChangedEvent) => {
      if (!onSelectionChanged) return;
      const api = event.api;
      const selectedRows = api.getSelectedRows();
      const ids = selectedRows
        .filter((row: Record<string, unknown>) => row.id && !row._isFooter && !row._isSection)
        .map((row: Record<string, unknown>) => row.id as string);
      onSelectionChanged(ids);
    },
    [onSelectionChanged],
  );

  /* ── Custom components ────────────────────────────────────────── */
  const components = useMemo(
    () => ({
      formulaCellEditor: FormulaCellEditor,
      autocompleteCellEditor: AutocompleteCellEditor,
      unitCellEditor: UnitCellEditor,
      actionsCellRenderer: ActionsCellRenderer,
      expandCellRenderer: ExpandCellRenderer,
      bimLinkCellRenderer: BimLinkCellRenderer,
      quantityCellRenderer: QuantityCellRenderer,
      unitCellRenderer: UnitCellRenderer,
      unitRateCellRenderer: UnitRateCellRenderer,
      bimQtyPickerCellRenderer: BimQtyPickerCellRenderer,
      sectionFullWidthRenderer: SectionFullWidthRenderer,
      resourceFullWidthRenderer: ResourceFullWidthRenderer,
      descriptionCellRenderer: DescriptionCellRenderer,
    }),
    [],
  );

  /* ── Default column defs ──────────────────────────────────────── */
  const defaultColDef = useMemo(
    () => ({
      resizable: true,
      sortable: false,
      suppressMovable: true,
      suppressHeaderMenuButton: true,
      cellClass: 'text-content-primary',
      headerClass: 'oe-header-centered',
    }),
    [],
  );

  /* ── Tab navigation: skip non-editable cells (Drag, Total, Actions) */
  const NON_EDITABLE_FIELDS = useMemo(() => new Set(['_drag', '_checkbox', 'total', '_actions', '_expand', '_bim_link', '_bim_qty']), []);

  const tabToNextCell = useCallback(
    (params: TabToNextCellParams): CellPosition | boolean => {
      const { nextCellPosition, backwards } = params;
      if (!nextCellPosition) return false;

      // Walk forward/backward until we find an editable column
      const api = gridApiRef.current;
      if (!api) return nextCellPosition;

      const allColumns = api.getAllDisplayedColumns();
      const startIdx = allColumns.findIndex(
        (col) => col.getColId() === nextCellPosition.column.getColId(),
      );
      if (startIdx === -1) return nextCellPosition;

      const step = backwards ? -1 : 1;
      let colIdx = startIdx;
      let { rowIndex } = nextCellPosition;

      // Search across columns (and rows if we wrap around)
      for (let attempts = 0; attempts < allColumns.length * 2; attempts++) {
        const col = allColumns[colIdx];
        const colId = col?.getColId() ?? '';
        if (col && !NON_EDITABLE_FIELDS.has(colId)) {
          return { rowIndex, column: col, rowPinned: nextCellPosition.rowPinned };
        }

        colIdx += step;
        if (colIdx >= allColumns.length) {
          colIdx = 0;
          rowIndex += 1;
        } else if (colIdx < 0) {
          colIdx = allColumns.length - 1;
          rowIndex -= 1;
        }
      }

      return nextCellPosition;
    },
    [NON_EDITABLE_FIELDS],
  );

  /* ── Clipboard: Ctrl+C / Ctrl+V on focused cells ────────────────── */

  /**
   * Get the raw (unformatted) value for a cell identified by row index and column id.
   * Returns the underlying data value, not the displayed formatted string.
   */
  const getCellRawValue = useCallback(
    (api: GridApi, rowIndex: number, colId: string): unknown => {
      const rowNode = api.getDisplayedRowAtIndex(rowIndex);
      if (!rowNode?.data) return undefined;
      return rowNode.data[colId];
    },
    [],
  );

  /**
   * Format a cell value for clipboard output. Numbers are serialized without
   * currency symbols so they paste cleanly into spreadsheets.
   */
  const formatCellForClipboard = useCallback(
    (value: unknown, _colId: string): string => {
      if (value == null) return '';
      return String(value);
    },
    [],
  );

  /**
   * Check whether a cell is editable given its row data and column id.
   * Mirrors the editable logic from column definitions.
   */
  const isCellPasteable = useCallback(
    (data: Record<string, unknown>, colId: string): boolean => {
      if (PASTE_PROTECTED_FIELDS.has(colId)) return false;
      if (data._isFooter) return false;
      // Section rows only allow description editing
      if (data._isSection) return colId === 'description';
      return true;
    },
    [],
  );

  /**
   * Apply a single pasted value to a cell, calling onUpdatePosition to persist it.
   * Returns true if the paste was applied, false if it was rejected.
   */
  const applyCellPaste = useCallback(
    (api: GridApi, rowIndex: number, colId: string, rawClipboard: string): boolean => {
      const rowNode = api.getDisplayedRowAtIndex(rowIndex);
      if (!rowNode?.data?.id) return false;

      const data = rowNode.data as Record<string, unknown>;
      if (!isCellPasteable(data, colId)) return false;

      const oldValue = data[colId];
      let newValue: string | number = rawClipboard;

      if (NUMERIC_FIELDS.has(colId)) {
        const parsed = parseClipboardNumber(rawClipboard);
        if (isNaN(parsed) || !isFinite(parsed) || parsed < 0) return false;
        newValue = Math.round(parsed * 100) / 100;
      }

      // Skip if value is unchanged
      if (oldValue === newValue) return false;

      const update: UpdatePositionData = { [colId]: newValue };
      const old: UpdatePositionData = { [colId]: oldValue };
      onUpdatePosition(data.id as string, update, old);
      return true;
    },
    [onUpdatePosition, isCellPasteable],
  );

  useEffect(() => {
    const wrapper = gridWrapperRef.current;
    if (!wrapper) return;

    const handleKeyDown = async (e: KeyboardEvent) => {
      const api = gridApiRef.current;
      if (!api) return;

      // Only handle Ctrl+C / Ctrl+V (or Cmd on macOS)
      const isCtrlOrMeta = e.ctrlKey || e.metaKey;
      if (!isCtrlOrMeta) return;

      // Don't intercept when a cell editor is active — let the editor handle clipboard natively
      if (api.getEditingCells().length > 0) return;

      if (e.key === 'c' || e.key === 'C') {
        /* ── COPY ───────────────────────────────────────────────── */
        const focusedCell = api.getFocusedCell();
        if (!focusedCell) return;

        const colId = focusedCell.column.getColId();
        const value = getCellRawValue(api, focusedCell.rowIndex, colId);
        const text = formatCellForClipboard(value, colId);

        try {
          await copyToClipboard(text);
        } catch {
          // Clipboard API may be unavailable (e.g. insecure context) — silently ignore
        }

        // Flash the copied cell for visual feedback
        const rowNode = api.getDisplayedRowAtIndex(focusedCell.rowIndex);
        if (rowNode) {
          api.flashCells({
            rowNodes: [rowNode],
            columns: [focusedCell.column],
          });
        }

        e.preventDefault();
      } else if (e.key === 'v' || e.key === 'V') {
        /* ── PASTE ──────────────────────────────────────────────── */
        const focusedCell = api.getFocusedCell();
        if (!focusedCell) return;

        let clipboardText: string;
        try {
          clipboardText = await readClipboard();
        } catch {
          // Clipboard read blocked — nothing we can do
          return;
        }

        if (!clipboardText) return;

        e.preventDefault();

        // Split clipboard into rows (newline) and columns (tab) for multi-cell paste
        const clipboardRows = clipboardText.split(/\r?\n/).filter((row) => row.length > 0);
        const allColumns = api.getAllDisplayedColumns();
        const startColIdx = allColumns.findIndex(
          (col) => col.getColId() === focusedCell.column.getColId(),
        );
        if (startColIdx === -1) return;

        let pastedCount = 0;
        const totalRowCount = api.getDisplayedRowCount();

        for (let rowOffset = 0; rowOffset < clipboardRows.length; rowOffset++) {
          const targetRowIdx = focusedCell.rowIndex + rowOffset;
          if (targetRowIdx >= totalRowCount) break;

          const cells = clipboardRows[rowOffset]!.split('\t');
          for (let colOffset = 0; colOffset < cells.length; colOffset++) {
            const targetColIdx = startColIdx + colOffset;
            if (targetColIdx >= allColumns.length) break;

            const targetCol = allColumns[targetColIdx]!;
            const targetColId = targetCol.getColId();
            const applied = applyCellPaste(api, targetRowIdx, targetColId, cells[colOffset] ?? '');
            if (applied) pastedCount++;
          }
        }

        if (pastedCount === 0) {
          addToast(
            {
              type: 'error',
              title: t('boq.paste_failed', { defaultValue: 'Could not paste - invalid data or read-only cells' }),
            },
            { duration: 3000 },
          );
        } else {
          addToast(
            {
              type: 'success',
              title: t('boq.value_pasted', { defaultValue: 'Value pasted' }),
            },
            { duration: 2000 },
          );

          // Flash pasted cells for visual feedback
          const flashRowNodes = [];
          const flashColumns = [];
          for (let rowOffset = 0; rowOffset < clipboardRows.length; rowOffset++) {
            const targetRowIdx = focusedCell.rowIndex + rowOffset;
            if (targetRowIdx >= totalRowCount) break;
            const rowNode = api.getDisplayedRowAtIndex(targetRowIdx);
            if (rowNode) flashRowNodes.push(rowNode);

            const cells = clipboardRows[rowOffset]!.split('\t');
            for (let colOffset = 0; colOffset < cells.length; colOffset++) {
              const targetColIdx = startColIdx + colOffset;
              if (targetColIdx >= allColumns.length) break;
              const col = allColumns[targetColIdx];
              if (rowOffset === 0 && col) flashColumns.push(col);
            }
          }
          if (flashRowNodes.length > 0) {
            api.flashCells({ rowNodes: flashRowNodes, columns: flashColumns });
          }
        }
      } else if (e.key === 'd' || e.key === 'D') {
        /* ── v3.12.0 Stream A — Ctrl+D fill down ──────────────────── */
        // Copy the focused cell's value to every other selected row in
        // the SAME column. Mirrors the spreadsheet idiom; AG-Grid does
        // not define Ctrl+D so this never overrides a built-in.
        const focusedCell = api.getFocusedCell();
        if (!focusedCell) return;
        const colId = focusedCell.column.getColId();
        if (PASTE_PROTECTED_FIELDS.has(colId)) return;
        const sourceValue = getCellRawValue(api, focusedCell.rowIndex, colId);
        if (sourceValue === undefined) return;

        const selectedNodes = api.getSelectedNodes();
        const targets = selectedNodes.filter((node) => {
          const d = node.data as Record<string, unknown> | undefined;
          return d && d.id && !d._isFooter && !d._isSection && !d._isResource;
        });
        if (targets.length === 0) return;

        e.preventDefault();
        let filled = 0;
        for (const node of targets) {
          const data = node.data as Record<string, unknown>;
          if (data[colId] === sourceValue) continue;
          if (!isCellPasteable(data, colId)) continue;
          const update: UpdatePositionData = {
            [colId]: sourceValue,
          } as UpdatePositionData;
          const old: UpdatePositionData = {
            [colId]: data[colId],
          } as UpdatePositionData;
          onUpdatePosition(data.id as string, update, old);
          filled++;
        }
        if (filled > 0) {
          api.flashCells({
            rowNodes: targets,
            columns: [focusedCell.column],
          });
          addToast(
            {
              type: 'success',
              title: t('boq.fill_down_done', {
                defaultValue: 'Filled down to {{count}} rows',
                count: String(filled),
              } as Record<string, string>),
            },
            { duration: 2000 },
          );
        }
      } else if (e.key === ';' || e.key === ':') {
        /* ── v3.12.0 Stream A — Ctrl+; insert today (ISO YYYY-MM-DD) ─ */
        // Inserts only into custom-column date cells (built-in numeric
        // columns reject non-numeric pastes anyway). Free of AG-Grid
        // built-ins.
        const focusedCell = api.getFocusedCell();
        if (!focusedCell) return;
        const colId = focusedCell.column.getColId();
        if (PASTE_PROTECTED_FIELDS.has(colId)) return;
        if (NUMERIC_FIELDS.has(colId)) return;
        const rowNode = api.getDisplayedRowAtIndex(focusedCell.rowIndex);
        if (!rowNode?.data?.id) return;
        const data = rowNode.data as Record<string, unknown>;
        if (!isCellPasteable(data, colId)) return;

        const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
        if (data[colId] === today) return;

        e.preventDefault();
        const update: UpdatePositionData = {
          [colId]: today,
        } as UpdatePositionData;
        const old: UpdatePositionData = {
          [colId]: data[colId],
        } as UpdatePositionData;
        onUpdatePosition(data.id as string, update, old);
        api.flashCells({
          rowNodes: [rowNode],
          columns: [focusedCell.column],
        });
        addToast(
          {
            type: 'success',
            title: t('boq.date_inserted', {
              defaultValue: 'Inserted today ({{date}})',
              date: today,
            } as Record<string, string>),
          },
          { duration: 1500 },
        );
      }
    };

    wrapper.addEventListener('keydown', handleKeyDown);
    return () => wrapper.removeEventListener('keydown', handleKeyDown);
  }, [
    getCellRawValue,
    formatCellForClipboard,
    applyCellPaste,
    addToast,
    t,
    isCellPasteable,
    onUpdatePosition,
  ]);

  /* ── Right-click on AG Grid cells → context menu ──────────────── */
  const onCellContextMenu = useCallback(
    (event: CellContextMenuEvent) => {
      const data = event.data;
      if (!data) return;
      const e = event.event as MouseEvent;
      if (!e) return;
      e.preventDefault();
      let type: ContextMenuTarget = 'position';
      if (data._isSection) type = 'section';
      else if (data._isFooter) type = 'footer';
      else if (data._isResource) type = 'resource';
      else if (data._isAddResource) type = 'addResource';
      const x = Math.min(e.clientX, window.innerWidth - 220);
      const y = Math.min(e.clientY, window.innerHeight - 300);
      setContextMenu({ x, y, type, data });
    },
    [],
  );

  /* ── Manual resource dialog submit ────────────────────────────── */

  /** Commit a resource to the position, then close + expand + refresh.
   *  ``override`` lets the "insert existing" path supply the looked-up
   *  master definition (Issue #133) while keeping the user's quantity. */
  const finalizeManualResource = useCallback(
    (override?: Partial<ManualResource> & { code?: string }) => {
      if (!manualResourceDialog) return;
      const { positionId, name, type, unit, quantity, unitRate, currency, code } =
        manualResourceDialog;
      const effType = override?.type ?? type;
      const effUnit = (override?.unit ?? unit).trim();
      const effCurrency = override?.currency ?? currency;
      const effCode = (override?.code ?? code).trim();
      // Issue #133 — when reusing an existing code the user typically types
      // ONLY the code (that is the whole point of "insert existing"), and a
      // catalogue/variant-imported master can itself carry a blank ``name``.
      // Never silently drop the resource: fall back to the code, then the
      // unit, so it always lands in the смета.
      const effName =
        (override?.name ?? name).trim() || effCode || effUnit;
      if (!effName) return;
      const qty = parseFloat(quantity.replace(',', '.')) || 1;
      const rate =
        override?.unit_rate ?? (parseFloat(unitRate.replace(',', '.')) || 0);
      // Persist user-typed units so they show up next time app-wide.
      if (effUnit) saveCustomUnit(effUnit);
      onAddManualResource?.(positionId, {
        name: effName,
        type: effType,
        unit: effUnit,
        quantity: qty,
        unit_rate: rate,
        ...(effCurrency ? { currency: effCurrency } : {}),
        ...(effCode ? { code: effCode } : {}),
      });
      setManualResourceDialog(null);
      setExpandedPositions((prev) => new Set(prev).add(positionId));
      setTimeout(() => {
        gridApiRef.current?.refreshCells({
          columns: ['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total'],
          force: true,
        });
      }, 0);
    },
    [manualResourceDialog, onAddManualResource],
  );

  const handleManualResourceSubmit = useCallback(async () => {
    if (!manualResourceDialog) return;
    const { name, code, collision } = manualResourceDialog;
    if (!name.trim()) return;
    const trimmedCode = code.trim();
    // Issue #133 — if the code is set and not yet checked, ask the
    // backend whether it is already in use anywhere in the project.
    // When it is, switch the dialog into the collision prompt instead
    // of adding straight away.
    if (trimmedCode && !collision && onLookupResourceByCode) {
      setManualResourceDialog((prev) =>
        prev ? { ...prev, checkingCode: true } : prev,
      );
      try {
        const match = await onLookupResourceByCode(trimmedCode);
        if (match) {
          setManualResourceDialog((prev) =>
            prev ? { ...prev, checkingCode: false, collision: match } : prev,
          );
          return;
        }
      } catch {
        // Lookup failed — don't block the user; fall through to a
        // plain add (the code is still persisted on the resource).
      }
      setManualResourceDialog((prev) =>
        prev ? { ...prev, checkingCode: false } : prev,
      );
    }
    finalizeManualResource();
  }, [manualResourceDialog, onLookupResourceByCode, finalizeManualResource]);

  /** Collision resolution — reuse the existing resource's definition. */
  const handleInsertExistingResource = useCallback(() => {
    const m = manualResourceDialog?.collision;
    if (!m) return;
    finalizeManualResource({
      name: m.name || m.code,
      type: m.type || manualResourceDialog!.type,
      unit: m.unit,
      unit_rate: m.unit_rate,
      currency: m.currency || undefined,
      code: m.code,
    });
  }, [manualResourceDialog, finalizeManualResource]);

  /** Collision resolution — keep editing so the user can change the code. */
  const handleChangeResourceCode = useCallback(() => {
    setManualResourceDialog((prev) =>
      prev ? { ...prev, collision: null } : prev,
    );
    setTimeout(() => manualResCodeRef.current?.focus(), 50);
  }, []);

  /* ── Context menu action handlers ─────────────────────────────── */

  const COMMON_UNITS = getUnitsForLocale();

  /** Flatten the project currency catalog so the dialog dropdown has every option. */
  const ALL_CURRENCY_OPTIONS = useMemo(
    () =>
      CURRENCY_GROUPS.flatMap((g) => g.options).filter(
        (o) => o.value !== '__custom__',
      ),
    [],
  );

  return (
    <div
      ref={gridWrapperRef}
      className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden"
      onContextMenu={(e) => e.preventDefault()}
    >
      <div
        className={`ag-theme-quartz ${
          // Shrink header text when many columns are visible so labels
          // stop truncating before the description column has to give up
          // width. Two tiers — see index.css for the exact rules.
          columnDefs.length >= 18
            ? 'oe-header-xs'
            : columnDefs.length >= 13
              ? 'oe-header-dense'
              : ''
        }`}
        // Cap the grid at the visible viewport so AG Grid's internal
        // horizontal scrollbar (which sits at the BOTTOM of the
        // viewport) always lands inside the user's screen. The previous
        // 900px floor pushed the bottom — and the scrollbar with it —
        // below the fold on shorter laptops, so once enough custom
        // columns were added to overflow horizontally there was no way
        // to scroll right and see them. `min(...)` keeps a sensible
        // tall view on big screens and shrinks on small ones.
        style={{ height: 'min(calc(100vh - 48px), 1100px)', minHeight: 480, width: '100%', minWidth: 0 }}
      >
        <AgGridReact
          ref={gridRef}
          rowData={rowData as Record<string, unknown>[]}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          context={gridContext}
          components={components}
          getRowId={getRowId}
          getRowClass={getRowClass}
          getRowHeight={getRowHeight}
          isFullWidthRow={isFullWidthRow}
          fullWidthCellRenderer="resourceFullWidthRenderer"
          pinnedBottomRowData={pinnedBottomRowData}
          onCellClicked={(event) => {
            const field = event.colDef.field;
            const data = event.data;

            // Issue #139 — a plain click does NOT tick the selection
            // checkbox (enableClickSelection:false), so report the clicked
            // partida as the active insert anchor so "Add Position"
            // inserts directly below it. Section / resource / footer rows
            // clear the anchor (they have dedicated add-child actions).
            if (
              data &&
              data.id &&
              !data._isSection &&
              !data._isFooter &&
              !data._isResource &&
              !data._isAddResource &&
              !data._isVariantHeader
            ) {
              onActiveRowChange?.(data.id as string);
            } else {
              onActiveRowChange?.(null);
            }

            if (!data || data._isSection || data._isFooter) return;

            // Click on unit_rate/total cell with resources → expand resources
            if ((field === 'unit_rate' || field === 'total')) {
              const meta = (data.metadata ?? {}) as Record<string, unknown>;
              const res = meta.resources;
              if (Array.isArray(res) && res.length > 0) {
                toggleResources(data.id as string);
              }
            }
          }}
          onCellFocused={(event) => {
            // Keyboard navigation (arrow keys / Tab) also moves the active
            // insert anchor so Ctrl+Enter / "Add Position" follows the
            // row the user is on. Guard against the headerless / no-row
            // focus events AG-Grid emits during refresh.
            if (!onActiveRowChange) return;
            const api = event.api;
            const rowIndex = event.rowIndex;
            if (rowIndex == null) return;
            const node = api.getDisplayedRowAtIndex(rowIndex);
            const d = node?.data as Record<string, unknown> | undefined;
            if (
              d &&
              d.id &&
              !d._isSection &&
              !d._isFooter &&
              !d._isResource &&
              !d._isAddResource &&
              !d._isVariantHeader
            ) {
              onActiveRowChange(d.id as string);
            }
          }}
          onCellEditingStarted={onCellEditingStarted}
          onCellEditingStopped={onCellEditingStopped}
          onCellValueChanged={onCellValueChanged}
          onColumnResized={handleColumnResized}
          onRowDragEnd={handleRowDragEnd}
          onGridReady={onGridReady}
          onCellContextMenu={onCellContextMenu}
          rowSelection={{
            mode: 'multiRow',
            checkboxes: true,
            headerCheckbox: true,
            selectAll: 'filtered',
            enableClickSelection: false,
            isRowSelectable: (node: { data?: Record<string, unknown> }) => !node.data?._isFooter && !node.data?._isSection && !node.data?._isResource && !node.data?._isAddResource,
          }}
          onSelectionChanged={handleSelectionChanged}
          rowDragManaged
          animateRows
          singleClickEdit
          enterNavigatesVertically
          // Issue #91: after committing an edit (Unit / Quantity / etc.),
          // Enter should advance to the next column on the SAME row so the
          // user can keep filling in the row left-to-right. The previous
          // ``...AfterEdit`` setting jumped down — on the last data row
          // that landed on the footer ("Resumen"), forcing the user to
          // navigate back. Cells that DO want vertical-after-edit (rare)
          // can still call ``api.tabToNextRow()`` from a custom editor.
          enterNavigatesVerticallyAfterEdit={false}
          tabToNextCell={tabToNextCell}
          stopEditingWhenCellsLoseFocus
          suppressContextMenu
          headerHeight={36}
          rowHeight={32}
          domLayout="normal"
          enableCellTextSelection
          suppressCellFocus={false}
          tooltipShowDelay={400}
          tooltipInteraction
        />
      </div>

      {/* ── Context Menu (portal) ──────────────────────────────────── */}
      {contextMenu && createPortal(
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-[9998]" onClick={closeContextMenu} onContextMenu={(e) => { e.preventDefault(); closeContextMenu(); }} />
          {/* Menu — flip to the left if it would overflow the viewport (Bug 11). */}
          <div
            className="fixed z-[9999] min-w-[200px] rounded-lg border border-border-light bg-surface-elevated shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100"
            style={(() => {
              const MENU_WIDTH = 240;
              const MENU_HEIGHT_EST = 360;
              const overflowX = contextMenu.x + MENU_WIDTH > window.innerWidth - 8;
              const overflowY = contextMenu.y + MENU_HEIGHT_EST > window.innerHeight - 8;
              const left = overflowX
                ? Math.max(8, contextMenu.x - MENU_WIDTH)
                : contextMenu.x;
              const top = overflowY
                ? Math.max(8, contextMenu.y - MENU_HEIGHT_EST)
                : contextMenu.y;
              return { left, top };
            })()}
          >
            {/* — Position context menu — */}
            {contextMenu.type === 'position' && (() => {
              const d = contextMenu.data as Record<string, unknown>;
              const meta = d.metadata as Record<string, unknown> | undefined;
              const hasResources = Array.isArray(meta?.resources) && (meta!.resources as unknown[]).length > 0;
              const isExpanded = expandedPositions.has(d.id as string);
              const cmtCount = countComments(meta);
              const costItemId = meta?.cost_item_id as string | undefined;
              return <>
                {/* Resources section */}
                {hasResources && (
                  <CtxItem icon={isExpanded ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
                    label={isExpanded ? t('boq.collapse_resources', { defaultValue: 'Collapse Resources' }) : t('boq.expand_resources', { defaultValue: 'Expand Resources' })}
                    onClick={() => { toggleResources(d.id as string); closeContextMenu(); }}
                  />
                )}
                <CtxItem icon={<Plus size={14}/>}
                  label={t('boq.add_resource_manual', { defaultValue: 'Add Resource' })}
                  onClick={() => {
                    gridContext.onAddManualResource(d.id as string);
                    closeContextMenu();
                  }}
                />
                <CtxItem icon={<Database size={14}/>}
                  label={t('boq.add_from_database', { defaultValue: 'Add from Database' })}
                  onClick={() => { onOpenCostDbForPosition?.(d.id as string); closeContextMenu(); }}
                />
                <CtxItem icon={<Boxes size={14}/>}
                  label={t('boq.add_from_catalog', { defaultValue: 'Pick from Catalog' })}
                  onClick={() => { onOpenCatalogForPosition?.(d.id as string); closeContextMenu(); }}
                />
                <CtxSeparator />
                <CtxItem icon={<Copy size={14}/>}
                  label={t('boq.duplicate_position', { defaultValue: 'Duplicate Position' })}
                  onClick={() => { onDuplicatePosition?.(d.id as string); closeContextMenu(); }}
                />
                {/* ── Issue #136: nest a child Partida under this one ── */}
                {onAddChildPosition && (() => {
                  const capped = childWouldExceedCap(d.id as string);
                  return (
                    <CtxItem icon={<Plus size={14}/>}
                      label={t('boq.add_child_position', { defaultValue: 'Add Child Partida' })}
                      disabled={capped}
                      title={capped ? depthCapTooltip : undefined}
                      onClick={() => { onAddChildPosition(d.id as string); closeContextMenu(); }}
                    />
                  );
                })()}
                {/* ── Feature 1: live model→quantity binding ───────── */}
                {onModelLink && (
                  <CtxItem icon={<Cuboid size={14} className="text-oe-blue"/>}
                    label={t('boq.model_link_action', { defaultValue: 'Model link…' })}
                    onClick={() => { onModelLink(d.id as string); closeContextMenu(); }}
                  />
                )}
                {/* ── Issue #127: reuse / linked-positions ──────────── */}
                {onReuseCode && (
                  <CtxItem icon={<Link2 size={14}/>}
                    label={t('boq.reuse_code_action', { defaultValue: 'Reuse Existing Code…' })}
                    onClick={() => { onReuseCode(d.parent_id as string | undefined); closeContextMenu(); }}
                  />
                )}
                {(d.link_role === 'master' || d.link_role === 'instance') && (
                  <>
                    {onShowLinks && (
                      <CtxItem icon={<Link2 size={14}/>}
                        label={t('boq.show_linked', { defaultValue: 'Show Linked Positions' })}
                        onClick={() => { onShowLinks(d.id as string); closeContextMenu(); }}
                      />
                    )}
                    {onUnlinkPosition && (
                      <CtxItem icon={<Link2Off size={14}/>}
                        label={t('boq.unlink_this', { defaultValue: 'Unlink this position' })}
                        onClick={() => { onUnlinkPosition(d.id as string); closeContextMenu(); }}
                      />
                    )}
                  </>
                )}
                <CtxItem icon={<MessageSquare size={14}/>}
                  label={cmtCount > 0
                    ? t('boq.view_comments', { defaultValue: 'Comments ({{count}})', count: cmtCount })
                    : t('boq.add_comment', { defaultValue: 'Add Comment' })
                  }
                  onClick={() => { gridContext.onAddComment(d.id as string); closeContextMenu(); }}
                />
                <CtxItem icon={<BookmarkPlus size={14}/>}
                  label={t('boq.save_to_database', { defaultValue: 'Save to Catalog' })}
                  onClick={() => { onSaveToDatabase(d.id as string); closeContextMenu(); }}
                />
                {onSaveAsAssembly && (
                  <CtxItem icon={<Layers size={14}/>}
                    label={t('boq.save_as_assembly', { defaultValue: 'Save as Assembly' })}
                    onClick={() => { onSaveAsAssembly(d.id as string); closeContextMenu(); }}
                  />
                )}
                {costItemId && (
                  <CtxItem icon={<ExternalLink size={14}/>}
                    label={t('boq.view_in_cost_db', { defaultValue: 'View in Cost Database' })}
                    onClick={() => { navigate(`/costs?highlight=${costItemId}`); closeContextMenu(); }}
                  />
                )}
                {(() => {
                  const cadIds = d.cad_element_ids as string[] | undefined;
                  const bimIds = Array.isArray(cadIds) ? cadIds.filter((x) => typeof x === 'string' && x.length > 0) : [];
                  if (bimIds.length === 0) return null;
                  return (
                    <CtxItem icon={<Cuboid size={14}/>}
                      label={t('boq.view_in_bim', { defaultValue: 'View in BIM 3D ({{count}})', count: bimIds.length })}
                      onClick={() => {
                        if (bimIds.length === 1) {
                          navigate(`/bim?element=${encodeURIComponent(bimIds[0]!)}&isolate=${encodeURIComponent(bimIds[0]!)}`);
                        } else {
                          navigate(`/bim?isolate=${bimIds.map((id) => encodeURIComponent(id)).join(',')}`);
                        }
                        closeContextMenu();
                      }}
                    />
                  );
                })()}
                {/* ── Currency (multi-currency BOQ) ──────────────────
                     Sets ``metadata.currency`` on the position so it can
                     be priced in a currency other than the project base.
                     The only entry point for leaf positions (resource
                     rows set currency per resource via the inline
                     combobox). The chosen currency shows as a badge on
                     the unit-rate cell and the total rebases to base. */}
                <CtxSeparator />
                {(() => {
                  const cur = (meta?.currency as string | undefined) || currencyCode;
                  return (
                    <CtxItem icon={<Banknote size={14} className="text-amber-600"/>}
                      label={t('boq.set_position_currency', {
                        defaultValue: 'Currency: {{code}}',
                        code: cur,
                      } as Record<string, unknown>)}
                      onClick={() => {
                        setPositionCurrencyDialog({ positionId: d.id as string, code: cur });
                        closeContextMenu();
                      }}
                    />
                  );
                })()}
                {/* ── AI features ─────────────────────────────────── */}
                <CtxSeparator />
                <CtxGroupLabel label="AI" />
                <CtxItem icon={<TrendingUp size={14} className="text-violet-500"/>}
                  label={t('boq.suggest_rate', { defaultValue: 'Suggest Rate' })}
                  onClick={() => { onSuggestRate?.(d.id as string); closeContextMenu(); }}
                />
                <CtxItem icon={<Tag size={14} className="text-violet-500"/>}
                  label={t('boq.suggest_classification', { defaultValue: 'Classify' })}
                  onClick={() => { onClassify?.(d.id as string); closeContextMenu(); }}
                />
                {anomalyMap?.has(d.id as string) && (() => {
                  const anomaly = anomalyMap.get(d.id as string)!;
                  return (
                    <CtxItem icon={<AlertTriangle size={14} className="text-amber-500"/>}
                      label={`${anomaly.message.slice(0, 35)}... → Apply ${anomaly.suggestion}`}
                      onClick={() => {
                        onApplyAnomalySuggestion?.(d.id as string, anomaly.suggestion);
                        closeContextMenu();
                      }}
                    />
                  );
                })()}
                <CtxSeparator />
                <CtxItem icon={<Trash2 size={14}/>}
                  label={t('common.delete', { defaultValue: 'Delete' })}
                  danger
                  onClick={() => { onDeletePosition(d.id as string); closeContextMenu(); }}
                />
              </>;
            })()}

            {/* — Resource context menu — */}
            {contextMenu.type === 'resource' && (() => {
              const d = contextMenu.data;
              const posId = d._parentPositionId as string;
              const resIdx = d._resourceIndex as number;
              return <>
                <CtxItem icon={<BookmarkPlus size={14}/>}
                  label={t('boq.save_to_catalog', { defaultValue: 'Save to Catalog' })}
                  onClick={() => { gridContext.onSaveResourceToCatalog(posId, resIdx); closeContextMenu(); }}
                />
                <CtxSeparator />
                <CtxItem icon={<X size={14}/>}
                  label={t('boq.remove_resource', { defaultValue: 'Remove Resource' })}
                  danger
                  onClick={() => { gridContext.onRemoveResource(posId, resIdx); closeContextMenu(); }}
                />
              </>;
            })()}

            {/* — Section context menu — */}
            {contextMenu.type === 'section' && (() => {
              const d = contextMenu.data;
              const isCollapsed = collapsedSections.has(d.id as string);
              const sectionCapped = childWouldExceedCap(d.id as string);
              return <>
                <CtxItem icon={<Plus size={14}/>}
                  label={t('boq.add_position', { defaultValue: 'Add Position' })}
                  disabled={sectionCapped}
                  title={sectionCapped ? depthCapTooltip : undefined}
                  onClick={() => { onAddPosition(d.id as string); closeContextMenu(); }}
                />
                {onAddSubSection && (
                  <CtxItem icon={<Plus size={14}/>}
                    label={t('boq.add_sub_section', { defaultValue: 'Add Sub-section' })}
                    disabled={sectionCapped}
                    title={sectionCapped ? depthCapTooltip : undefined}
                    onClick={() => { onAddSubSection(d.id as string); closeContextMenu(); }}
                  />
                )}
                {onReuseCode && (
                  <CtxItem icon={<Link2 size={14}/>}
                    label={t('boq.reuse_code_action', { defaultValue: 'Reuse Existing Code…' })}
                    onClick={() => { onReuseCode(d.id as string); closeContextMenu(); }}
                  />
                )}
                <CtxItem icon={isCollapsed ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
                  label={isCollapsed ? t('boq.expand_section', { defaultValue: 'Expand Section' }) : t('boq.collapse_section', { defaultValue: 'Collapse Section' })}
                  onClick={() => { onToggleSection(d.id as string); closeContextMenu(); }}
                />
              </>;
            })()}

            {/* — Add Resource row context menu — */}
            {contextMenu.type === 'addResource' && (() => {
              const posId = contextMenu.data._parentPositionId as string;
              return <>
                <CtxItem icon={<Plus size={14}/>}
                  label={t('boq.add_resource_manual', { defaultValue: 'Add Resource' })}
                  onClick={() => { gridContext.onAddManualResource(posId); closeContextMenu(); }}
                />
                <CtxItem icon={<Database size={14}/>}
                  label={t('boq.add_from_database', { defaultValue: 'Add from Database' })}
                  onClick={() => { onOpenCostDbForPosition?.(posId); closeContextMenu(); }}
                />
                <CtxItem icon={<Boxes size={14}/>}
                  label={t('boq.add_from_catalog', { defaultValue: 'Pick from Catalog' })}
                  onClick={() => { onOpenCatalogForPosition?.(posId); closeContextMenu(); }}
                />
              </>;
            })()}
          </div>
        </>,
        document.body,
      )}

      {/* ── Manual Resource Dialog ─────────────────────────────────── */}
      {manualResourceDialog && createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setManualResourceDialog(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="boq-manual-resource-title"
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-[380px] p-5 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="boq-manual-resource-title" className="text-sm font-semibold text-content-primary mb-4 flex items-center gap-2">
              <Wrench size={16} className="text-oe-blue" />
              {t('boq.add_resource_manual', { defaultValue: 'Add Resource' })}
            </h3>

            {/* Issue #133 — code-collision prompt: insert the existing
                resource, or change the code and create a new one. */}
            {manualResourceDialog.collision && (
              <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 dark:border-amber-700/60 dark:bg-amber-900/20 p-3">
                <p className="text-[11px] text-content-primary mb-1 font-medium">
                  {t('boq.resource_code_in_use', {
                    defaultValue: "Code '{{code}}' is already in use",
                    code: manualResourceDialog.collision.code,
                  })}
                </p>
                <p className="text-[11px] text-content-secondary mb-2">
                  <span className="font-medium text-content-primary">
                    {manualResourceDialog.collision.name || manualResourceDialog.collision.code}
                  </span>
                  {manualResourceDialog.collision.position_ordinal ||
                  manualResourceDialog.collision.position_description
                    ? ` (${
                        manualResourceDialog.collision.position_ordinal ||
                        manualResourceDialog.collision.position_description
                      })`
                    : ''}
                  {'. '}
                  {t('boq.resource_code_in_use_detail', {
                    defaultValue:
                      'Insert that existing resource, or change the code to create a new one?',
                  })}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleInsertExistingResource}
                    className="h-7 px-3 rounded-md text-[11px] font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-colors"
                  >
                    {t('boq.resource_insert_existing', { defaultValue: 'Insert existing' })}
                  </button>
                  <button
                    onClick={handleChangeResourceCode}
                    className="h-7 px-3 rounded-md text-[11px] font-medium text-content-secondary bg-surface-secondary hover:bg-surface-tertiary transition-colors"
                  >
                    {t('boq.resource_change_code', { defaultValue: 'Change code' })}
                  </button>
                </div>
              </div>
            )}

            {/* Name */}
            <label className="block text-[11px] font-medium text-content-secondary mb-1">
              {t('boq.resource_name', { defaultValue: 'Name' })} *
            </label>
            <input
              ref={manualResNameRef}
              type="text"
              value={manualResourceDialog.name}
              onChange={(e) => setManualResourceDialog({ ...manualResourceDialog, name: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter') handleManualResourceSubmit(); if (e.key === 'Escape') setManualResourceDialog(null); }}
              className="w-full mb-3 h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30"
              placeholder={t('boq.resource_name_placeholder', { defaultValue: 'e.g. Concrete C30/37' })}
            />

            {/* Code (Issue #133) — reusable resource code. Typing a code
                already used in the project triggers the reuse prompt. */}
            <label className="block text-[11px] font-medium text-content-secondary mb-1">
              {t('boq.resource_code', { defaultValue: 'Code' })}
              <span className="text-content-tertiary font-normal ml-1">
                ({t('common.optional', { defaultValue: 'optional' })})
              </span>
            </label>
            <input
              ref={manualResCodeRef}
              type="text"
              value={manualResourceDialog.code}
              onChange={(e) =>
                setManualResourceDialog({
                  ...manualResourceDialog,
                  code: e.target.value,
                  // Editing the code invalidates a prior collision verdict.
                  collision: null,
                })
              }
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleManualResourceSubmit();
                if (e.key === 'Escape') setManualResourceDialog(null);
              }}
              className="w-full mb-3 h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30"
              placeholder={t('boq.resource_code_placeholder', {
                defaultValue: 'e.g. MAT-001 - reuse an existing code to link',
              })}
            />

            {/* Type + Unit row */}
            <div className="flex gap-2 mb-3">
              <div className="flex-1">
                <label className="block text-[11px] font-medium text-content-secondary mb-1">
                  {t('boq.resource_type', { defaultValue: 'Type' })}
                </label>
                <select
                  value={manualResourceDialog.type}
                  onChange={(e) => setManualResourceDialog({ ...manualResourceDialog, type: e.target.value })}
                  className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue"
                >
                  {RESOURCE_TYPES.map((rt) => (
                    <option key={rt.value} value={rt.value}>
                      {getResourceTypeLabel(rt.value, t)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-24">
                <label className="block text-[11px] font-medium text-content-secondary mb-1">
                  {t('boq.unit', { defaultValue: 'Unit' })}
                </label>
                <input
                  type="text"
                  list="resource-units"
                  value={manualResourceDialog.unit}
                  onChange={(e) => setManualResourceDialog({ ...manualResourceDialog, unit: e.target.value })}
                  className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue"
                />
                <datalist id="resource-units">
                  {COMMON_UNITS.map((u) => <option key={u} value={u} />)}
                </datalist>
              </div>
            </div>

            {/* Quantity + Rate + Currency row */}
            <div className="flex gap-2 mb-3">
              <div className="flex-1">
                <label className="block text-[11px] font-medium text-content-secondary mb-1">
                  {t('boq.quantity', { defaultValue: 'Quantity' })}
                </label>
                <input
                  type="text"
                  value={manualResourceDialog.quantity}
                  onChange={(e) => setManualResourceDialog({ ...manualResourceDialog, quantity: e.target.value })}
                  className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary tabular-nums text-right outline-none focus:border-oe-blue"
                />
              </div>
              <div className="flex-1">
                <label className="block text-[11px] font-medium text-content-secondary mb-1">
                  {t('boq.unit_rate', { defaultValue: 'Unit Rate' })}
                </label>
                <input
                  type="text"
                  value={manualResourceDialog.unitRate}
                  onChange={(e) => setManualResourceDialog({ ...manualResourceDialog, unitRate: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleManualResourceSubmit(); }}
                  className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary tabular-nums text-right outline-none focus:border-oe-blue"
                />
              </div>
              <div className="w-24">
                <label className="block text-[11px] font-medium text-content-secondary mb-1">
                  {t('boq.resource_currency', { defaultValue: 'Currency' })}
                </label>
                <select
                  value={manualResourceDialog.currency || currencyCode}
                  onChange={(e) => {
                    const v = e.target.value;
                    setManualResourceDialog({
                      ...manualResourceDialog,
                      currency: v === currencyCode ? '' : v,
                    });
                  }}
                  className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue"
                  title={t('boq.resource_currency_hint', {
                    defaultValue: 'Currency for this resource. Defaults to project base currency.',
                  })}
                >
                  {/* Base currency always first */}
                  <option value={currencyCode}>{currencyCode}</option>
                  {/* Project FX template currencies */}
                  {(fxRates ?? [])
                    .filter((fx) => fx.currency !== currencyCode)
                    .map((fx) => (
                      <option key={`fx-${fx.currency}`} value={fx.currency}>
                        {fx.currency}
                      </option>
                    ))}
                  {/* All other ISO currencies (collapsed list) */}
                  {ALL_CURRENCY_OPTIONS
                    .filter(
                      (c) =>
                        c.value !== currencyCode &&
                        !(fxRates ?? []).some((fx) => fx.currency === c.value),
                    )
                    .map((c) => (
                      <option key={`all-${c.value}`} value={c.value}>{c.value}</option>
                    ))}
                </select>
              </div>
            </div>

            {/* Total preview */}
            <div className="flex items-center justify-between mb-4 px-1">
              <span className="text-[11px] text-content-tertiary">{t('boq.total', { defaultValue: 'Total' })}</span>
              <span className="text-sm font-bold text-content-primary tabular-nums">
                {fmtWithCurrency(
                  (parseFloat(manualResourceDialog.quantity.replace(',', '.')) || 0) *
                  (parseFloat(manualResourceDialog.unitRate.replace(',', '.')) || 0),
                  locale,
                  currencyCode,
                )}
              </span>
            </div>

            {/* Actions */}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setManualResourceDialog(null)}
                className="h-8 px-3 rounded-md text-xs font-medium text-content-secondary bg-surface-secondary hover:bg-surface-tertiary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleManualResourceSubmit}
                disabled={
                  !manualResourceDialog.name.trim() ||
                  !!manualResourceDialog.checkingCode ||
                  !!manualResourceDialog.collision
                }
                className="h-8 px-4 rounded-md text-xs font-medium text-white bg-oe-blue hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {manualResourceDialog.checkingCode
                  ? t('boq.resource_checking_code', { defaultValue: 'Checking…' })
                  : t('boq.add_resource', { defaultValue: 'Add Resource' })}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* ── Position-level Variant Picker ─────────────────────────────
       *   Renders only when the description-cell "V" icon was clicked
       *   on a position whose variants live at position level (legacy
       *   CWICR position-mode applies). The picker reads the catalog
       *   directly from ``position.metadata.cost_item_variants`` and
       *   on apply patches the position's unit_rate + metadata.variant
       *   via ``onUpdatePosition``. */}
      {(() => {
        if (!positionVariantPicker) return null;
        const pos = positions.find((p) => p.id === positionVariantPicker.positionId);
        if (!pos) return null;
        const meta = (pos.metadata ?? {}) as Record<string, unknown>;
        const variants = meta.cost_item_variants as CostVariant[] | undefined;
        const stats = meta.cost_item_variant_stats as VariantStats | undefined;
        if (!Array.isArray(variants) || variants.length < 2 || !stats) return null;
        const currency = (meta.currency as string | undefined) || currencyCode;
        const currentVariant = (meta as { variant?: { index?: number } }).variant;
        return (
          <VariantPicker
            variants={variants}
            stats={stats}
            anchorEl={positionVariantPicker.anchorEl}
            unitLabel={pos.unit || ''}
            currency={currency}
            defaultStrategy="mean"
            defaultIndex={
              typeof currentVariant?.index === 'number' ? currentVariant.index : undefined
            }
            onApply={applyPositionVariant}
            onClose={closePositionVariantPicker}
          />
        );
      })()}

      {/* ── Per-position currency dialog (multi-currency BOQ) ──────────
       *   Sets ``metadata.currency`` on the position. Reached from the
       *   row context menu. Choosing the base currency clears the
       *   override. The unit-rate cell then shows the currency badge and
       *   the position total rebases to base via the project FX rate so
       *   currencies are never blended in the grand total. */}
      {positionCurrencyDialog && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setPositionCurrencyDialog(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="boq-position-currency-title"
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-[340px] p-5 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3
              id="boq-position-currency-title"
              className="text-sm font-semibold text-content-primary mb-1 flex items-center gap-2"
            >
              <Banknote size={16} className="text-amber-600" />
              {t('boq.position_currency_title', { defaultValue: 'Position currency' })}
            </h3>
            <p className="text-[11px] text-content-tertiary mb-4">
              {t('boq.position_currency_desc', {
                defaultValue:
                  'Price this position in a currency other than the project base. The total is converted back to {{base}} for the grand total.',
                base: currencyCode,
              } as Record<string, unknown>)}
            </p>
            <label className="block text-[11px] font-medium text-content-secondary mb-1">
              {t('boq.resource_currency', { defaultValue: 'Currency' })}
            </label>
            <select
              value={positionCurrencyDialog.code || currencyCode}
              onChange={(e) =>
                setPositionCurrencyDialog({
                  ...positionCurrencyDialog,
                  code: e.target.value,
                })
              }
              className="w-full h-8 rounded-md border border-border-medium bg-surface-primary px-2 text-xs text-content-primary outline-none focus:border-oe-blue"
            >
              {/* Base currency first (selecting it clears the override). */}
              <option value={currencyCode}>
                {currencyCode} {t('boq.currency_base_suffix', { defaultValue: '(base)' })}
              </option>
              {(fxRates ?? [])
                .filter((fx) => fx.currency !== currencyCode)
                .map((fx) => (
                  <option key={`fx-${fx.currency}`} value={fx.currency}>
                    {fx.currency}
                  </option>
                ))}
              {ALL_CURRENCY_OPTIONS.filter(
                (c) =>
                  c.value !== currencyCode &&
                  !(fxRates ?? []).some((fx) => fx.currency === c.value),
              ).map((c) => (
                <option key={`all-${c.value}`} value={c.value}>
                  {c.value}
                </option>
              ))}
            </select>
            <div className="flex gap-2 justify-end mt-5">
              <button
                onClick={() => setPositionCurrencyDialog(null)}
                className="h-8 px-3 rounded-md text-xs font-medium text-content-secondary bg-surface-secondary hover:bg-surface-tertiary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={commitPositionCurrency}
                className="h-8 px-3 rounded-md text-xs font-semibold text-white bg-oe-blue hover:bg-oe-blue/90 transition-colors"
              >
                {t('common.save', { defaultValue: 'Save' })}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
});

/* ── Context menu sub-components ─────────────────────────────────── */

function CtxItem({ icon, label, onClick, danger, disabled, title }: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
  /** Issue #136 — render greyed-out + non-interactive (e.g. depth cap). */
  disabled?: boolean;
  /** Native tooltip (Issue #136 — explains why an action is disabled). */
  title?: string;
}) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      aria-disabled={disabled || undefined}
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-xs text-left transition-colors ${
        disabled
          ? 'text-content-tertiary opacity-50 cursor-not-allowed'
          : danger
          ? 'text-semantic-error hover:bg-semantic-error-bg'
          : 'text-content-primary hover:bg-surface-tertiary'
      }`}
    >
      <span className={`shrink-0 ${danger && !disabled ? '' : 'text-content-tertiary'}`}>{icon}</span>
      {label}
    </button>
  );
}

function CtxSeparator() {
  return <div className="my-1 border-t border-border-light" />;
}

function CtxGroupLabel({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1 select-none">
      <Sparkles size={10} className="text-violet-500" />
      <span className="text-[10px] font-semibold text-violet-500 uppercase tracking-wider">{label}</span>
    </div>
  );
}

export default BOQGrid;

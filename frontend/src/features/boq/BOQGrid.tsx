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
} from 'lucide-react';

import {
  type Position,
  type UpdatePositionData,
  type CostAutocompleteItem,
  groupPositionsIntoSections,
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
import { fmtWithCurrency, getUnitsForLocale, saveCustomUnit } from './boqHelpers';
import { RESOURCE_TYPES, getResourceTypeLabel } from './boqResourceTypes';
import { CURRENCY_GROUPS } from '@/features/projects/CreateProjectPage';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { VariantPicker } from '@/features/costs/VariantPicker';
import type { CostVariant, VariantStats } from '@/features/costs/api';

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
  locale: string;
  footerRows: FooterRow[];
  onSelectionChanged?: (selectedIds: string[]) => void;
  onRemoveResource?: (positionId: string, resourceIndex: number) => void;
  onUpdateResource?: (positionId: string, resourceIndex: number, field: string, value: number | string) => void;
  onUpdateResourceFields?: (positionId: string, resourceIndex: number, fields: Record<string, number | string>) => void;
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
  onDuplicatePosition?: (positionId: string) => void;
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
  locale,
  footerRows,
  onSelectionChanged,
  onRemoveResource,
  onUpdateResource,
  onUpdateResourceFields,
  onSaveResourceToCatalog,
  onSaveVariantHeaderToCatalog,
  onOpenCostDbForPosition,
  onOpenCatalogForPosition,
  onRepickResourceVariant,
  onAddManualResource,
  onDuplicatePosition,
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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const gridRef = useRef<AgGridReact>(null);
  const gridApiRef = useRef<GridApi | null>(null);
  const gridWrapperRef = useRef<HTMLDivElement>(null);
  const addToast = useToastStore((s) => s.addToast);

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
  }
  const [manualResourceDialog, setManualResourceDialog] = useState<ManualResourceDialogState | null>(null);
  const manualResNameRef = useRef<HTMLInputElement>(null);

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
    setTimeout(() => {
      gridApiRef.current?.stopEditing();
      gridApiRef.current?.refreshCells({ columns: ['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total'], force: true });
    }, 0);
  }, []);

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
      setTimeout(() => {
        gridApiRef.current?.stopEditing();
        gridApiRef.current?.refreshCells({
          columns: ['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total'],
          force: true,
        });
      }, 0);
    },
    [],
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
      setTimeout(() => {
        gridApiRef.current?.stopEditing();
        gridApiRef.current?.refreshCells({
          columns: ['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total'],
          force: true,
        });
      }, 0);
    },
    [],
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
   *  Both rate AND qty edits land on ``metadata.variant`` ONLY — the
   *  position's own ``quantity`` and ``unit_rate`` stay independent so
   *  editing the variant resource never alters the parent position row,
   *  and editing the position qty never alters the variant resource qty.
   *  Per the user's spec: "Объём вариативного ресурса никак не связан
   *  с объёмом позиции". Same rule applies to price (already in place). */
  const onUpdateVariantHeader = useCallback(
    (positionId: string, fields: { quantity?: number; unit_rate?: number }) => {
      const pos = positions.find((p) => p.id === positionId);
      if (!pos) return;
      const oldMeta = (pos.metadata ?? {}) as Record<string, unknown>;
      const oldVariant = (oldMeta.variant ?? {}) as Record<string, unknown>;
      const newVariant: Record<string, unknown> = { ...oldVariant };

      if (fields.quantity != null) {
        newVariant.quantity = fields.quantity;
      }
      if (fields.unit_rate != null) {
        newVariant.price = fields.unit_rate;
      }

      if (fields.quantity == null && fields.unit_rate == null) return;

      // Manual edits stamp a label/index so the variant row still renders
      // when no catalog variant has been picked yet.
      if (typeof newVariant.label !== 'string') newVariant.label = 'manual';
      if (typeof newVariant.index !== 'number') newVariant.index = -1;

      const newMeta = { ...oldMeta, variant: newVariant };
      // ``variant_default`` (auto mean/median) is dropped — explicit edits win.
      if ('variant_default' in newMeta) {
        delete (newMeta as Record<string, unknown>).variant_default;
      }

      onUpdatePosition?.(
        pos.id,
        { metadata: newMeta },
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
      locale,
      fmt,
      t,
      collapsedSections,
      onToggleSection,
      onAddPosition,
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
    }) as FullGridContext,
    [currencySymbol, currencyCode, fxRates, locale, fmt, t, collapsedSections, onToggleSection, onAddPosition,
     expandedPositions, toggleResources, onRemoveResource, onUpdateResource, onUpdateResourceFields,
     onSaveResourceToCatalog, onSaveVariantHeaderToCatalog, onOpenCostDbForPosition, onOpenCatalogForPosition, onRepickResourceVariant,
     openVariantPickerSignal, openVariantPickerFor, clearOpenVariantPicker, openPositionVariantPicker, onUpdateVariantHeader,
     onDeletePosition, onSaveToDatabase, onAddComment,
     onDuplicatePosition, showContextMenu, anomalyMap, onApplyAnomalySuggestion, bimModelId,
     onUpdatePosition, onHighlightBIMElements, onDeleteSection, onReorderSections, onFormulaApplied],
  );

  /* ── Column defs (standard + custom) ─────────────────────────────── */
  const columnDefs = useMemo(() => {
    const defs = getColumnDefs({ currencySymbol, currencyCode, locale, fmt, t });
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
  }, [currencySymbol, currencyCode, locale, fmt, t, customColumns, positions, boqVariables]);

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

  /* ── Helper: insert resource sub-rows after an expanded position ── */
  const insertResourceRows = useCallback((rows: GridRow[], pos: Position) => {
    rows.push(pos);

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
    if (hasPositionLevelVariants) {
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
        // Variant resource qty is stored independently of the position qty
        // (per the user's spec: "Объём вариативного ресурса никак не связан
        // с объёмом позиции"). For positions imported before the decouple
        // we fall back to position.quantity so old data still renders.
        _variantHeaderQty:
          typeof posChosenVariant?.quantity === 'number'
            ? posChosenVariant.quantity
            : (pos.quantity ?? 0),
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

    let resTotal = 0;
    for (let i = 0; i < resources.length; i++) {
      const r = resources[i]!;
      const rTotal = r.total ?? r.quantity * r.unit_rate;
      resTotal += rTotal;
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
        _resourceAvailableVariants: r.available_variants,
        _resourceAvailableVariantStats: r.available_variant_stats,
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
  }, [expandedPositions, currencyCode]);

  /* ── Build row data from positions ────────────────────────────── */
  const rowData: GridRow[] = useMemo(() => {
    const { sections, ungrouped } = groupPositionsIntoSections(positions);
    const rows: GridRow[] = [];

    // Ungrouped positions first
    for (const pos of ungrouped) {
      insertResourceRows(rows, pos);
    }

    // Then sections with their children
    for (const group of sections) {
      const sectionRow: GridRow = {
        ...group.section,
        _isSection: true,
        _childCount: group.children.length,
        _subtotal: group.subtotal,
        total: group.subtotal,
      };
      rows.push(sectionRow);

      const isCollapsed = collapsedSections.has(group.section.id);
      if (!isCollapsed) {
        for (const child of group.children) {
          insertResourceRows(rows, child);
        }
      }
    }

    return rows;
  }, [positions, collapsedSections, insertResourceRows]);

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
      const { data, colDef, oldValue, newValue } = event;
      if (!data?.id || data._isFooter) return;
      if (oldValue === newValue) return;

      const field = colDef.field;
      if (!field) return;

      const update: UpdatePositionData = { [field]: newValue };
      const old: UpdatePositionData = { [field]: oldValue };

      // Position quantity is a multiplier on the per-unit unit_rate.
      // Resources are stored as PER-UNIT norms (qty per 1 unit of
      // position) — same convention as CostX, Candy, iTWO, ProEst —
      // so changing position qty must NOT touch resource qty/rate or
      // unit_rate. Backend re-derives total = qty × unit_rate.
      if (field === 'quantity') {
        const parsedNew = typeof newValue === 'number' ? newValue : parseFloat(newValue) || 0;
        const parsedOld = typeof oldValue === 'number' ? oldValue : parseFloat(oldValue) || 0;
        update.quantity = parsedNew;
        old.quantity = parsedOld;
      }

      // Handle custom column changes — store in metadata.custom_fields
      if (field?.startsWith('_custom_')) {
        const colName = field.replace('_custom_', '');
        const meta = (data.metadata as Record<string, unknown>) ?? {};
        const customFields = { ...((meta.custom_fields as Record<string, unknown>) ?? {}), [colName]: newValue };
        const updatedMeta = { ...meta, custom_fields: customFields };
        onUpdatePosition(data.id, { metadata: updatedMeta }, {});
        return;
      }

      onUpdatePosition(data.id, update, old);
    },
    [onUpdatePosition],
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
          await navigator.clipboard.writeText(text);
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
          clipboardText = await navigator.clipboard.readText();
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
              title: t('boq.paste_failed', { defaultValue: 'Could not paste — invalid data or read-only cells' }),
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
      }
    };

    wrapper.addEventListener('keydown', handleKeyDown);
    return () => wrapper.removeEventListener('keydown', handleKeyDown);
  }, [getCellRawValue, formatCellForClipboard, applyCellPaste, addToast, t]);

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
  const handleManualResourceSubmit = useCallback(() => {
    if (!manualResourceDialog) return;
    const { positionId, name, type, unit, quantity, unitRate, currency } = manualResourceDialog;
    if (!name.trim()) return;
    const qty = parseFloat(quantity.replace(',', '.')) || 1;
    const rate = parseFloat(unitRate.replace(',', '.')) || 0;
    const trimmedUnit = unit.trim();
    // Persist user-typed units so they show up next time anywhere in the app.
    if (trimmedUnit) saveCustomUnit(trimmedUnit);
    onAddManualResource?.(positionId, {
      name: name.trim(),
      type,
      unit: trimmedUnit,
      quantity: qty,
      unit_rate: rate,
      ...(currency ? { currency } : {}),
    });
    setManualResourceDialog(null);
    // Auto-expand the position's resources
    setExpandedPositions((prev) => new Set(prev).add(positionId));
    setTimeout(() => {
      gridApiRef.current?.refreshCells({ columns: ['ordinal', '_expand', 'description', 'quantity', 'unit_rate', 'total'], force: true });
    }, 0);
  }, [manualResourceDialog, onAddManualResource]);

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
        className="ag-theme-quartz"
        style={{ height: 'max(calc(100vh - 48px), 900px)', width: '100%' }}
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
              return <>
                <CtxItem icon={<Plus size={14}/>}
                  label={t('boq.add_position', { defaultValue: 'Add Position' })}
                  onClick={() => { onAddPosition(d.id as string); closeContextMenu(); }}
                />
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
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-[380px] p-5 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-content-primary mb-4 flex items-center gap-2">
              <Wrench size={16} className="text-oe-blue" />
              {t('boq.add_resource_manual', { defaultValue: 'Add Resource' })}
            </h3>

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
                disabled={!manualResourceDialog.name.trim()}
                className="h-8 px-4 rounded-md text-xs font-medium text-white bg-oe-blue hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {t('boq.add_resource', { defaultValue: 'Add Resource' })}
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
    </div>
  );
});

/* ── Context menu sub-components ─────────────────────────────────── */

function CtxItem({ icon, label, onClick, danger }: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-xs text-left transition-colors ${
        danger
          ? 'text-semantic-error hover:bg-semantic-error-bg'
          : 'text-content-primary hover:bg-surface-tertiary'
      }`}
    >
      <span className={`shrink-0 ${danger ? '' : 'text-content-tertiary'}`}>{icon}</span>
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

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
import {
  FormulaCellEditor,
  AutocompleteCellEditor,
} from './grid/cellEditors';
import {
  ActionsCellRenderer,
  OrdinalCellRenderer,
  SectionFullWidthRenderer,
  ResourceFullWidthRenderer,
  type ContextMenuTarget,
  type FullGridContext,
} from './grid/cellRenderers';
import { countComments } from './CommentDrawer';
import { fmtWithCurrency, getUnitsForLocale } from './boqHelpers';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';

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
const PASTE_PROTECTED_FIELDS = new Set(['total', '_actions', '_drag', '_checkbox']);

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

type GridRow =
  | (Position & Partial<SectionRow>)
  | (FooterRow & Record<string, unknown>)
  | (ResourceRow & Record<string, unknown>)
  | (AddResourceRow & Record<string, unknown>);

export interface ManualResource {
  name: string;
  type: string;
  unit: string;
  quantity: number;
  unit_rate: number;
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
  collapsedSections: Set<string>;
  onToggleSection: (sectionId: string) => void;
  highlightPositionId?: string;
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  footerRows: FooterRow[];
  onSelectionChanged?: (selectedIds: string[]) => void;
  onRemoveResource?: (positionId: string, resourceIndex: number) => void;
  onUpdateResource?: (positionId: string, resourceIndex: number, field: string, value: number | string) => void;
  onSaveResourceToCatalog?: (positionId: string, resourceIndex: number) => void;
  onOpenCostDbForPosition?: (positionId: string) => void;
  onOpenCatalogForPosition?: (positionId: string) => void;
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
  onFormulaApplied: _onFormulaApplied,
  onReorderSections,
  onReorderPositions,
  collapsedSections,
  onToggleSection,
  highlightPositionId,
  currencySymbol,
  currencyCode,
  locale,
  footerRows,
  onSelectionChanged,
  onRemoveResource,
  onUpdateResource,
  onSaveResourceToCatalog,
  onOpenCostDbForPosition,
  onOpenCatalogForPosition,
  onAddManualResource,
  onDuplicatePosition,
  onSuggestRate,
  onClassify,
  // onCheckAnomalies is consumed by BOQToolbar, not directly by the grid
  anomalyMap,
  onApplyAnomalySuggestion,
  onSaveAsAssembly,
  customColumns,
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
      gridApiRef.current?.refreshCells({ columns: ['ordinal'], force: true });
    }, 0);
  }, []);

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
      onSaveResourceToCatalog: onSaveResourceToCatalog ?? (() => {}),
      onOpenCostDbForPosition: onOpenCostDbForPosition ?? (() => {}),
      onOpenCatalogForPosition: onOpenCatalogForPosition ?? (() => {}),
      onDeletePosition,
      onSaveToDatabase,
      onAddComment: onAddComment ?? (() => {}),
      onAddManualResource: (positionId: string) => {
        setManualResourceDialog({
          positionId, name: '', type: 'material', unit: 'm²', quantity: '1', unitRate: '0',
        });
        setTimeout(() => manualResNameRef.current?.focus(), 50);
      },
      onDuplicatePosition: onDuplicatePosition ?? (() => {}),
      onShowContextMenu: showContextMenu,
      anomalyMap,
      onApplyAnomalySuggestion,
    }) as FullGridContext,
    [currencySymbol, currencyCode, locale, fmt, t, collapsedSections, onToggleSection, onAddPosition,
     expandedPositions, toggleResources, onRemoveResource, onUpdateResource,
     onSaveResourceToCatalog, onOpenCostDbForPosition, onOpenCatalogForPosition,
     onDeletePosition, onSaveToDatabase, onAddComment,
     onDuplicatePosition, showContextMenu, anomalyMap, onApplyAnomalySuggestion],
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
      const customDefs = getCustomColumnDefs(customColumns);
      if (actionsIdx >= 0) {
        defs.splice(actionsIdx, 0, ...customDefs);
      } else {
        defs.push(...customDefs);
      }
    }
    return defs;
  }, [currencySymbol, currencyCode, locale, fmt, t, customColumns]);

  /* ── Helper: insert resource sub-rows after an expanded position ── */
  const insertResourceRows = useCallback((rows: GridRow[], pos: Position) => {
    rows.push(pos);

    if (!expandedPositions.has(pos.id)) return;

    const resources = (pos.metadata?.resources ?? []) as Array<{
      name: string; code?: string; type: string;
      unit: string; quantity: number; unit_rate: number; total?: number;
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
  }, [expandedPositions]);

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
    if (params.data?._isResource || params.data?._isAddResource) {
      classes.push('oe-resource-row');
    }
    // Add 'group' to regular position rows so hover actions (save/delete) appear on hover
    if (!params.data?._isSection && !params.data?._isFooter && !params.data?._isResource && !params.data?._isAddResource) {
      classes.push('group');

      // Highlight unpriced positions (unit_rate is 0/empty) so the user can
      // see at a glance what still needs work. Skip resource sub-rows and
      // section headers — only real position rows.
      const rate = Number(params.data?.unit_rate ?? 0);
      const qty = Number(params.data?.quantity ?? 0);
      if ((!rate || rate === 0) && qty > 0) {
        classes.push('oe-unpriced-row');
      }
    }
    return classes.join(' ');
  }, []);

  /* ── Full-width row: sections + resource sub-rows ─────────────── */
  const isFullWidthRow = useCallback(
    (params: IsFullWidthRowParams) => {
      const d = params.rowNode.data;
      return !!d?._isSection || !!d?._isResource || !!d?._isAddResource;
    },
    [],
  );

  const getRowHeight = useCallback((params: RowHeightParams) => {
    if (params.data?._isSection) return 38;
    if (params.data?._isResource) return 28;
    if (params.data?._isAddResource) return 30;
    return 32;
  }, []);

  /* ── Cancel accidental ordinal edits from chevron clicks ─────── */
  const onCellEditingStarted = useCallback(
    (event: CellEditingStartedEvent) => {
      // If editing started on the ordinal column for a row with resources,
      // it was likely triggered by clicking the expand/collapse chevron.
      // Cancel the edit immediately to prevent data corruption.
      if (
        event.colDef.field === 'ordinal' &&
        Array.isArray(event.data?.metadata?.resources) &&
        event.data.metadata.resources.length > 0
      ) {
        event.api.stopEditing(true); // true = cancel (don't save)
        return;
      }

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

      // For quantity, scale resources proportionally if they exist
      if (field === 'quantity') {
        const parsedNew = typeof newValue === 'number' ? newValue : parseFloat(newValue) || 0;
        const parsedOld = typeof oldValue === 'number' ? oldValue : parseFloat(oldValue) || 0;
        update.quantity = parsedNew;
        old.quantity = parsedOld;

        const meta = data.metadata as Record<string, unknown> | undefined;
        const resources = meta?.resources;
        if (Array.isArray(resources) && resources.length > 0 && parsedOld > 0 && parsedNew !== parsedOld) {
          const ratio = parsedNew / parsedOld;
          const scaled = (resources as Array<Record<string, unknown>>).map((r) => {
            const newResQty = Math.round(((r.quantity as number) || 0) * ratio * 10000) / 10000;
            const resRate = (r.unit_rate as number) || 0;
            return { ...r, quantity: newResQty, total: Math.round(newResQty * resRate * 100) / 100 };
          });
          // Derive unit_rate from scaled resources
          const resourceTotal = scaled.reduce((sum, r) => sum + ((r.total as number) || 0), 0);
          const derivedRate = parsedNew > 0 ? Math.round(resourceTotal / parsedNew * 10000) / 10000 : 0;
          update.metadata = { ...meta, resources: scaled };
          update.unit_rate = derivedRate;
        }
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
      actionsCellRenderer: ActionsCellRenderer,
      sectionFullWidthRenderer: SectionFullWidthRenderer,
      resourceFullWidthRenderer: ResourceFullWidthRenderer,
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
    }),
    [],
  );

  /* ── Tab navigation: skip non-editable cells (Drag, Total, Actions) */
  const NON_EDITABLE_FIELDS = useMemo(() => new Set(['_drag', '_checkbox', 'total', '_actions']), []);

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
    const { positionId, name, type, unit, quantity, unitRate } = manualResourceDialog;
    if (!name.trim()) return;
    const qty = parseFloat(quantity.replace(',', '.')) || 1;
    const rate = parseFloat(unitRate.replace(',', '.')) || 0;
    onAddManualResource?.(positionId, { name: name.trim(), type, unit, quantity: qty, unit_rate: rate });
    setManualResourceDialog(null);
    // Auto-expand the position's resources
    setExpandedPositions((prev) => new Set(prev).add(positionId));
    setTimeout(() => {
      gridApiRef.current?.refreshCells({ columns: ['ordinal'], force: true });
    }, 0);
  }, [manualResourceDialog, onAddManualResource]);

  /* ── Context menu action handlers ─────────────────────────────── */

  const RESOURCE_TYPES = [
    { value: 'material', label: 'Material' },
    { value: 'labor', label: 'Labor' },
    { value: 'equipment', label: 'Equipment' },
    { value: 'subcontractor', label: 'Subcontractor' },
    { value: 'other', label: 'Other' },
  ];

  const COMMON_UNITS = getUnitsForLocale();

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
          enterNavigatesVerticallyAfterEdit
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
          {/* Menu */}
          <div
            className="fixed z-[9999] min-w-[200px] rounded-lg border border-border-light bg-surface-elevated shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100"
            style={{ left: contextMenu.x, top: contextMenu.y }}
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
                    <option key={rt.value} value={rt.value}>{rt.label}</option>
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

            {/* Quantity + Rate row */}
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

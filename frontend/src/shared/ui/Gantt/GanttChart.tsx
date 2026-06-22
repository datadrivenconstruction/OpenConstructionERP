// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SVG-based Gantt chart component.
 *
 * Features:
 * - Two-panel layout: fixed left table + scrollable SVG timeline
 * - Task bars with progress fill, milestones (diamond), group/summary rows
 * - Dependency arrows (Finish-to-Start)
 * - Critical path highlighting (red)
 * - Baseline overlay (gray)
 * - Today line (dashed red vertical)
 * - Zoom levels: day / week / month
 * - Drag to reschedule activities
 * - Scroll sync between panels
 * - Accessible (ARIA labels on bars)
 * - i18n via useTranslation + Intl.DateTimeFormat
 *
 * Performance: useMemo for heavy computations, renders 2000 activities < 1s.
 */
import {
  useState,
  useRef,
  useMemo,
  useCallback,
  useEffect,
  type MouseEvent as ReactMouseEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';
import {
  type GanttActivity,
  type ViewMode,
  ROW_HEIGHT,
  HEADER_HEIGHT,
  dateToPx,
  pxToDate,
  daysBetween,
  addDays,
  generateTimeHeaders,
  calculateArrowPath,
  getDateRange,
  getTimelineWidth,
} from './ganttUtils';

export type { GanttActivity };

/* ── Props ──────────────────────────────────────────────────────── */

export interface GanttProps {
  activities: GanttActivity[];
  viewMode?: ViewMode;
  startDate?: string;
  endDate?: string;
  onActivityClick?: (id: string) => void;
  onActivityDrag?: (id: string, newStart: string, newEnd: string) => void;
  onActivityResize?: (id: string, newStart: string, newEnd: string) => void | Promise<void>;
  /** Commit an inline edit of a grid cell. Each call carries exactly one
   *  changed field. ``start``/``end`` are ISO ``YYYY-MM-DD`` strings,
   *  ``durationDays`` is a working-day count, ``lag`` applies to the activity's
   *  single predecessor. When omitted, all cells are read-only. */
  onActivityFieldChange?: (
    id: string,
    patch: {
      name?: string;
      wbsCode?: string;
      durationDays?: number;
      start?: string;
      end?: string;
      progress?: number;
      lag?: number;
    },
  ) => void;
  /** Commit a structural reorder/re-parent of the rows. Receives the full
   *  desired top-to-bottom order with each row's new parent (null = root).
   *  Drives drag-and-drop and Alt+Arrow keyboard moves. Dates/dependencies are
   *  not touched. When omitted, rows are not draggable/movable. */
  onActivityReorder?: (items: Array<{ id: string; parentId: string | null }>) => void;
  className?: string;
  showBaseline?: boolean;
  showDependencies?: boolean;
  showCriticalPath?: boolean;
  todayLine?: boolean;
}

/* ── Constants ──────────────────────────────────────────────────── */

const BAR_HEIGHT = 22;
const BAR_Y_OFFSET = (ROW_HEIGHT - BAR_HEIGHT) / 2;
const BASELINE_HEIGHT = 6;
const MILESTONE_SIZE = 10;
const MIN_BAR_WIDTH = 4;
const RESIZE_HANDLE_WIDTH = 7;

/* ── Left-grid columns ──────────────────────────────────────────── */

type ColId = 'wbs' | 'name' | 'duration' | 'start' | 'end' | 'predecessors' | 'lag' | 'progress';

interface GridColumn {
  id: ColId;
  labelKey: string;
  labelDefault: string;
  align: 'left' | 'right';
  /** Minimum width (px) the column can be dragged to. */
  min: number;
  /** Default width (px) before the user resizes it. */
  def: number;
}

const GRID_COLUMNS: GridColumn[] = [
  { id: 'wbs', labelKey: 'gantt.wbs', labelDefault: 'WBS', align: 'left', min: 40, def: 60 },
  { id: 'name', labelKey: 'gantt.activity_name', labelDefault: 'Activity', align: 'left', min: 100, def: 170 },
  { id: 'duration', labelKey: 'gantt.duration', labelDefault: 'Dur.', align: 'right', min: 42, def: 52 },
  { id: 'start', labelKey: 'gantt.start', labelDefault: 'Start', align: 'right', min: 54, def: 66 },
  { id: 'end', labelKey: 'gantt.end', labelDefault: 'End', align: 'right', min: 54, def: 66 },
  { id: 'predecessors', labelKey: 'gantt.predecessors', labelDefault: 'Pred.', align: 'left', min: 60, def: 96 },
  { id: 'lag', labelKey: 'gantt.lag', labelDefault: 'Lag', align: 'right', min: 42, def: 58 },
  { id: 'progress', labelKey: 'gantt.progress_short', labelDefault: '%', align: 'right', min: 32, def: 40 },
];

const COL_WIDTHS_LS_KEY = 'oe-gantt-col-widths-v1';

/* ── Date formatting helpers ────────────────────────────────────── */

function fmtShort(date: Date, locale: string): string {
  return new Intl.DateTimeFormat(locale, { day: '2-digit', month: 'short' }).format(date);
}

function toISO(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/* ── Build activity row index map ───────────────────────────────── */

function buildRowIndex(activities: GanttActivity[]): Map<string, number> {
  const map = new Map<string, number>();
  activities.forEach((a, i) => map.set(a.id, i));
  return map;
}

/* ── Structural reorder helpers ─────────────────────────────────── */

type ReorderItem = { id: string; parentId: string | null };

interface OrderNode {
  id: string;
  parentId: string | null;
  children: OrderNode[];
}

/** Build an ordered tree from the flat (sort_order) activity list. Children
 *  keep their document order since ``activities`` is already pre-order. */
function buildOrderNodes(activities: GanttActivity[]): {
  roots: OrderNode[];
  byId: Map<string, OrderNode>;
} {
  const byId = new Map<string, OrderNode>();
  for (const a of activities) byId.set(a.id, { id: a.id, parentId: a.parentId ?? null, children: [] });
  const roots: OrderNode[] = [];
  for (const a of activities) {
    const node = byId.get(a.id)!;
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    if (parent) parent.children.push(node);
    else {
      node.parentId = null;
      roots.push(node);
    }
  }
  return { roots, byId };
}

/** Pre-order flatten back into the {id, parentId} list the API expects. */
function flattenOrder(roots: OrderNode[]): ReorderItem[] {
  const out: ReorderItem[] = [];
  const walk = (nodes: OrderNode[], parentId: string | null) => {
    for (const n of nodes) {
      out.push({ id: n.id, parentId });
      walk(n.children, n.id);
    }
  };
  walk(roots, null);
  return out;
}

function siblingArray(node: OrderNode, roots: OrderNode[], byId: Map<string, OrderNode>): OrderNode[] {
  return node.parentId ? byId.get(node.parentId)?.children ?? roots : roots;
}

/** True when ``childId`` lives inside ``ancestor``'s subtree (excludes self). */
function isWithinSubtree(ancestor: OrderNode, childId: string): boolean {
  const stack = [...ancestor.children];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.id === childId) return true;
    stack.push(...n.children);
  }
  return false;
}

type ReorderOp = 'up' | 'down' | 'indent' | 'outdent';

/** Apply a keyboard move (the whole subtree travels with the node) and return
 *  the new flat order, or null when the move is a no-op (e.g. already first). */
function computeMove(activities: GanttActivity[], id: string, op: ReorderOp): ReorderItem[] | null {
  const { roots, byId } = buildOrderNodes(activities);
  const node = byId.get(id);
  if (!node) return null;
  const sibs = siblingArray(node, roots, byId);
  const idx = sibs.findIndex((n) => n.id === id);
  if (idx < 0) return null;

  if (op === 'up') {
    if (idx === 0) return null;
    [sibs[idx - 1], sibs[idx]] = [sibs[idx]!, sibs[idx - 1]!];
  } else if (op === 'down') {
    if (idx >= sibs.length - 1) return null;
    [sibs[idx + 1], sibs[idx]] = [sibs[idx]!, sibs[idx + 1]!];
  } else if (op === 'indent') {
    if (idx === 0) return null; // needs a preceding sibling to nest under
    const prev = sibs[idx - 1]!;
    sibs.splice(idx, 1);
    node.parentId = prev.id;
    prev.children.push(node);
  } else if (op === 'outdent') {
    if (!node.parentId) return null; // already at root
    const parent = byId.get(node.parentId)!;
    const grand = parent.parentId ? byId.get(parent.parentId)?.children ?? roots : roots;
    sibs.splice(idx, 1);
    const parentIdx = grand.findIndex((n) => n.id === parent.id);
    node.parentId = parent.parentId;
    grand.splice(parentIdx + 1, 0, node);
  }
  return flattenOrder(roots);
}

/** Drop ``draggedId`` so it becomes a sibling placed just before ``targetId``
 *  (i.e. takes the target's parent + position). Null when invalid. */
function computeDrop(activities: GanttActivity[], draggedId: string, targetId: string): ReorderItem[] | null {
  if (draggedId === targetId) return null;
  const { roots, byId } = buildOrderNodes(activities);
  const dragged = byId.get(draggedId);
  const target = byId.get(targetId);
  if (!dragged || !target) return null;
  if (isWithinSubtree(dragged, targetId)) return null; // can't drop into own subtree
  const dragSibs = siblingArray(dragged, roots, byId);
  const di = dragSibs.findIndex((n) => n.id === draggedId);
  if (di >= 0) dragSibs.splice(di, 1);
  const tgtSibs = siblingArray(target, roots, byId);
  const ti = tgtSibs.findIndex((n) => n.id === targetId);
  dragged.parentId = target.parentId;
  tgtSibs.splice(Math.max(0, ti), 0, dragged);
  return flattenOrder(roots);
}

/* ── Component ──────────────────────────────────────────────────── */

export function GanttChart({
  activities,
  viewMode = 'week',
  startDate: startDateProp,
  endDate: endDateProp,
  onActivityClick,
  onActivityDrag,
  onActivityResize,
  onActivityFieldChange,
  onActivityReorder,
  className = '',
  showBaseline = false,
  showDependencies = true,
  showCriticalPath = true,
  todayLine = true,
}: GanttProps) {
  const { t } = useTranslation();
  const locale = getIntlLocale();

  // ── Resizable column widths (persisted) ──────────────────────────
  const [colWidths, setColWidths] = useState<Record<string, number>>(() => {
    const base = Object.fromEntries(GRID_COLUMNS.map((c) => [c.id, c.def]));
    try {
      const saved = JSON.parse(localStorage.getItem(COL_WIDTHS_LS_KEY) || '{}');
      return { ...base, ...saved };
    } catch {
      return base;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(COL_WIDTHS_LS_KEY, JSON.stringify(colWidths));
    } catch {
      /* storage unavailable — keep in-memory widths only */
    }
  }, [colWidths]);
  const tableWidth = GRID_COLUMNS.reduce((sum, c) => sum + (colWidths[c.id] ?? c.def), 0);

  const colResize = useRef<{ id: string; startX: number; startW: number } | null>(null);
  const startColResize = useCallback(
    (e: ReactMouseEvent, id: string) => {
      e.preventDefault();
      e.stopPropagation();
      const col = GRID_COLUMNS.find((c) => c.id === id);
      colResize.current = { id, startX: e.clientX, startW: colWidths[id] ?? col?.def ?? 60 };
      const onMove = (ev: globalThis.MouseEvent) => {
        const r = colResize.current;
        if (!r) return;
        const min = GRID_COLUMNS.find((c) => c.id === r.id)?.min ?? 32;
        setColWidths((prev) => ({ ...prev, [r.id]: Math.max(min, r.startW + (ev.clientX - r.startX)) }));
      };
      const onUp = () => {
        colResize.current = null;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [colWidths],
  );

  // ── Inline cell editing ──────────────────────────────────────────
  type EditableCol = 'name' | 'wbs' | 'duration' | 'start' | 'end' | 'progress' | 'lag';
  const [editingCell, setEditingCell] = useState<{ id: string; col: EditableCol } | null>(null);
  const [editValue, setEditValue] = useState('');
  const cancelEdit = useRef(false);

  const beginEdit = useCallback(
    (e: ReactMouseEvent, id: string, col: EditableCol, current: string) => {
      if (!onActivityFieldChange) return;
      e.stopPropagation();
      cancelEdit.current = false;
      setEditingCell({ id, col });
      setEditValue(current);
    },
    [onActivityFieldChange],
  );
  const commitEdit = useCallback(() => {
    if (!editingCell) return;
    if (cancelEdit.current) {
      cancelEdit.current = false;
      setEditingCell(null);
      return;
    }
    const { id, col } = editingCell;
    const act = activities.find((a) => a.id === id);
    const raw = editValue.trim();
    const num = Number(raw);
    let patch: Parameters<NonNullable<typeof onActivityFieldChange>>[1] | null = null;
    switch (col) {
      case 'name':
        if (raw && raw !== (act?.name ?? '')) patch = { name: raw };
        break;
      case 'wbs':
        if (raw !== (act?.wbsCode ?? '')) patch = { wbsCode: raw };
        break;
      case 'start':
        if (raw && raw !== (act?.start ?? '').slice(0, 10)) patch = { start: raw };
        break;
      case 'end':
        if (raw && raw !== (act?.end ?? '').slice(0, 10)) patch = { end: raw };
        break;
      case 'duration':
        if (raw && Number.isFinite(num) && num >= 1) patch = { durationDays: Math.round(num) };
        break;
      case 'progress':
        if (raw && Number.isFinite(num)) patch = { progress: Math.min(100, Math.max(0, Math.round(num))) };
        break;
      case 'lag':
        if (raw !== '' && Number.isFinite(num)) patch = { lag: Math.round(num) };
        break;
    }
    if (patch) onActivityFieldChange?.(id, patch);
    setEditingCell(null);
  }, [editingCell, editValue, activities, onActivityFieldChange]);
  const handleEditKey = useCallback((e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.currentTarget.blur();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit.current = true;
      e.currentTarget.blur();
    }
  }, []);

  // Shared classNames for the inline edit inputs. Date inputs need more room
  // than a narrow date column, so they overflow the cell (cells aren't clipped).
  const EDIT_INPUT_CLS =
    'w-full min-w-0 rounded border border-oe-blue bg-surface-primary px-1 py-0.5 text-2xs';
  const DATE_INPUT_CLS =
    'relative z-20 w-[128px] rounded border border-oe-blue bg-surface-primary px-1 py-0.5 text-2xs';

  // ── Collapsible summary rows ─────────────────────────────────────
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Depth of each activity in the hierarchy (0 = root)
  const depthMap = useMemo(() => {
    const parentIds = new Map<string, string>();
    for (const a of activities) {
      if (a.parentId) parentIds.set(a.id, a.parentId);
    }
    const map = new Map<string, number>();
    for (const a of activities) {
      let depth = 0;
      let cur = a.parentId;
      while (cur) { depth++; cur = parentIds.get(cur); }
      map.set(a.id, depth);
    }
    return map;
  }, [activities]);

  // Activities visible after applying collapse state
  const visibleActivities = useMemo(() => {
    if (collapsedIds.size === 0) return activities;
    const childrenOf = new Map<string, string[]>();
    for (const a of activities) {
      if (a.parentId) {
        const arr = childrenOf.get(a.parentId) ?? [];
        arr.push(a.id);
        childrenOf.set(a.parentId, arr);
      }
    }
    const hidden = new Set<string>();
    const hideDesc = (id: string) => {
      for (const c of childrenOf.get(id) ?? []) { hidden.add(c); hideDesc(c); }
    };
    for (const id of collapsedIds) hideDesc(id);
    return activities.filter((a) => !hidden.has(a.id));
  }, [activities, collapsedIds]);

  // Refs for scroll sync
  const tableBodyRef = useRef<HTMLDivElement>(null);
  const svgScrollRef = useRef<HTMLDivElement>(null);

  // ── Row drag-and-drop + keyboard reorder ─────────────────────────
  const [rowDragId, setRowDragId] = useState<string | null>(null);
  const [rowDragOverId, setRowDragOverId] = useState<string | null>(null);
  const focusRowId = useRef<string | null>(null);

  // After a reorder re-renders the list, restore keyboard focus to the row
  // that moved so the user can keep nudging it with Alt+Arrow.
  useEffect(() => {
    if (!focusRowId.current) return;
    const el = tableBodyRef.current?.querySelector<HTMLElement>(
      `[data-activity-row="${focusRowId.current}"]`,
    );
    el?.focus();
    focusRowId.current = null;
  }, [activities]);

  const emitRowMove = useCallback(
    (id: string, op: ReorderOp) => {
      if (!onActivityReorder) return;
      const items = computeMove(activities, id, op);
      if (items) {
        focusRowId.current = id;
        onActivityReorder(items);
      }
    },
    [activities, onActivityReorder],
  );

  const handleRowKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>, id: string) => {
      // Only Alt+Arrow, and never while inline-editing a cell.
      if (!onActivityReorder || editingCell || !e.altKey) return;
      const op: ReorderOp | null =
        e.key === 'ArrowUp'
          ? 'up'
          : e.key === 'ArrowDown'
            ? 'down'
            : e.key === 'ArrowRight'
              ? 'indent'
              : e.key === 'ArrowLeft'
                ? 'outdent'
                : null;
      if (!op) return;
      e.preventDefault();
      emitRowMove(id, op);
    },
    [onActivityReorder, editingCell, emitRowMove],
  );

  const handleRowDrop = useCallback(
    (targetId: string) => {
      if (!onActivityReorder || !rowDragId) return;
      const items = computeDrop(activities, rowDragId, targetId);
      setRowDragId(null);
      setRowDragOverId(null);
      if (items) onActivityReorder(items);
    },
    [activities, rowDragId, onActivityReorder],
  );

  // Drag state
  const [dragState, setDragState] = useState<{
    activityId: string;
    startMouseX: number;
    origStart: Date;
    origEnd: Date;
    currentOffsetDays: number;
  } | null>(null);

  // Resize state (edge-drag for duration). Independent of dragState so both
  // can coexist defensively, though only one is ever active at a time.
  const [resizeState, setResizeState] = useState<{
    activityId: string;
    edge: 'left' | 'right';
    startMouseX: number;
    origStart: Date;
    origEnd: Date;
    currentDeltaDays: number;
  } | null>(null);

  /* ── Compute timeline range ─────────────────────────────────── */

  const { timelineStart, timelineEnd } = useMemo(() => {
    if (startDateProp && endDateProp) {
      return {
        timelineStart: new Date(startDateProp),
        timelineEnd: new Date(endDateProp),
      };
    }
    const range = getDateRange(activities);
    return {
      timelineStart: startDateProp ? new Date(startDateProp) : range.start,
      timelineEnd: endDateProp ? new Date(endDateProp) : range.end,
    };
  }, [activities, startDateProp, endDateProp]);

  /* ── Computed values ────────────────────────────────────────── */

  const timelineWidth = useMemo(
    () => Math.max(getTimelineWidth(timelineStart, timelineEnd, viewMode), 400),
    [timelineStart, timelineEnd, viewMode],
  );

  const bodyHeight = visibleActivities.length * ROW_HEIGHT;

  const rowIndex = useMemo(() => buildRowIndex(visibleActivities), [visibleActivities]);

  const headers = useMemo(
    () => generateTimeHeaders(timelineStart, timelineEnd, viewMode, locale),
    [timelineStart, timelineEnd, viewMode, locale],
  );

  /* ── Today line position ────────────────────────────────────── */

  const todayX = useMemo(() => {
    if (!todayLine) return null;
    const now = new Date();
    const x = dateToPx(now, viewMode, timelineStart);
    if (x < 0 || x > timelineWidth) return null;
    return x;
  }, [todayLine, viewMode, timelineStart, timelineWidth]);

  /* ── Bar geometry ───────────────────────────────────────────── */

  const bars = useMemo(() => {
    return visibleActivities.map((a) => {
      const startD = new Date(a.start);
      const endD = new Date(a.end);
      const x = dateToPx(startD, viewMode, timelineStart);
      const xEnd = dateToPx(endD, viewMode, timelineStart);
      const width = Math.max(xEnd - x, MIN_BAR_WIDTH);

      let baselineX: number | undefined;
      let baselineWidth: number | undefined;
      if (showBaseline && a.baselineStart && a.baselineEnd) {
        const bsD = new Date(a.baselineStart);
        const beD = new Date(a.baselineEnd);
        baselineX = dateToPx(bsD, viewMode, timelineStart);
        const bxEnd = dateToPx(beD, viewMode, timelineStart);
        baselineWidth = Math.max(bxEnd - baselineX, MIN_BAR_WIDTH);
      }

      return { activity: a, x, width, baselineX, baselineWidth };
    });
  }, [visibleActivities, viewMode, timelineStart, showBaseline]);

  /* ── Dependency arrow paths ─────────────────────────────────── */

  const arrowPaths = useMemo(() => {
    if (!showDependencies) return [];
    const paths: Array<{ key: string; d: string }> = [];

    for (const bar of bars) {
      const deps = bar.activity.dependencies;
      if (!deps || deps.length === 0) continue;

      const toRow = rowIndex.get(bar.activity.id);
      if (toRow == null) continue;

      for (const predId of deps) {
        const fromRow = rowIndex.get(predId);
        if (fromRow == null) continue;

        const predBar = bars[fromRow];
        if (!predBar) continue;

        const fromX = predBar.x + predBar.width;
        const toX = bar.x;

        paths.push({
          key: `${predId}-${bar.activity.id}`,
          d: calculateArrowPath(fromX, fromRow, toX, toRow, ROW_HEIGHT),
        });
      }
    }

    return paths;
  }, [bars, rowIndex, showDependencies]);

  /* ── Scroll sync ────────────────────────────────────────────── */

  const handleSvgScroll = useCallback(() => {
    if (svgScrollRef.current && tableBodyRef.current) {
      tableBodyRef.current.scrollTop = svgScrollRef.current.scrollTop;
    }
  }, []);

  const handleTableScroll = useCallback(() => {
    if (tableBodyRef.current && svgScrollRef.current) {
      svgScrollRef.current.scrollTop = tableBodyRef.current.scrollTop;
    }
  }, []);

  /* ── Drag handlers ──────────────────────────────────────────── */

  const handleBarMouseDown = useCallback(
    (e: ReactMouseEvent, activityId: string) => {
      if (!onActivityDrag) return;
      e.preventDefault();
      e.stopPropagation();

      const a = activities.find((act) => act.id === activityId);
      if (!a) return;

      setDragState({
        activityId,
        startMouseX: e.clientX,
        origStart: new Date(a.start),
        origEnd: new Date(a.end),
        currentOffsetDays: 0,
      });
    },
    [activities, onActivityDrag],
  );

  useEffect(() => {
    if (!dragState) return;

    const handleMouseMove = (e: globalThis.MouseEvent) => {
      const dx = e.clientX - dragState.startMouseX;
      const newDate = pxToDate(
        dateToPx(dragState.origStart, viewMode, timelineStart) + dx,
        viewMode,
        timelineStart,
      );
      const offsetDays = daysBetween(dragState.origStart, newDate);
      setDragState((prev) => (prev ? { ...prev, currentOffsetDays: offsetDays } : null));
    };

    const handleMouseUp = () => {
      if (dragState.currentOffsetDays !== 0 && onActivityDrag) {
        const newStart = addDays(dragState.origStart, dragState.currentOffsetDays);
        const newEnd = addDays(dragState.origEnd, dragState.currentOffsetDays);
        onActivityDrag(dragState.activityId, toISO(newStart), toISO(newEnd));
      }
      setDragState(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragState, onActivityDrag, viewMode, timelineStart]);

  /* ── Resize handlers ────────────────────────────────────────── */

  const handleResizeMouseDown = useCallback(
    (e: ReactMouseEvent, activityId: string, edge: 'left' | 'right') => {
      if (!onActivityResize) return;
      e.preventDefault();
      e.stopPropagation();

      const a = activities.find((act) => act.id === activityId);
      if (!a) return;

      setResizeState({
        activityId,
        edge,
        startMouseX: e.clientX,
        origStart: new Date(a.start),
        origEnd: new Date(a.end),
        currentDeltaDays: 0,
      });
    },
    [activities, onActivityResize],
  );

  useEffect(() => {
    if (!resizeState) return;

    const handleMouseMove = (e: globalThis.MouseEvent) => {
      const dx = e.clientX - resizeState.startMouseX;
      const anchor = resizeState.edge === 'left' ? resizeState.origStart : resizeState.origEnd;
      const newDate = pxToDate(
        dateToPx(anchor, viewMode, timelineStart) + dx,
        viewMode,
        timelineStart,
      );
      let deltaDays = daysBetween(anchor, newDate);

      // Clamp so the bar stays at least 1 day wide.
      if (resizeState.edge === 'left') {
        const maxDelta = daysBetween(resizeState.origStart, resizeState.origEnd) - 1;
        if (deltaDays > maxDelta) deltaDays = maxDelta;
      } else {
        const minDelta = -(daysBetween(resizeState.origStart, resizeState.origEnd) - 1);
        if (deltaDays < minDelta) deltaDays = minDelta;
      }

      setResizeState((prev) => (prev ? { ...prev, currentDeltaDays: deltaDays } : null));
    };

    const handleMouseUp = () => {
      if (resizeState.currentDeltaDays !== 0 && onActivityResize) {
        const newStart =
          resizeState.edge === 'left'
            ? addDays(resizeState.origStart, resizeState.currentDeltaDays)
            : resizeState.origStart;
        const newEnd =
          resizeState.edge === 'right'
            ? addDays(resizeState.origEnd, resizeState.currentDeltaDays)
            : resizeState.origEnd;
        onActivityResize(resizeState.activityId, toISO(newStart), toISO(newEnd));
      }
      setResizeState(null);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setResizeState(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [resizeState, onActivityResize, viewMode, timelineStart]);

  /* ── Render helpers ─────────────────────────────────────────── */

  const renderBar = useCallback(
    (
      bar: (typeof bars)[0],
      rowIdx: number,
    ) => {
      const { activity: a, x, width, baselineX, baselineWidth } = bar;
      const y = rowIdx * ROW_HEIGHT;
      const isCritical = showCriticalPath && a.isCritical;
      const isDragging = dragState?.activityId === a.id;
      const dragOffset = isDragging
        ? dateToPx(addDays(dragState.origStart, dragState.currentOffsetDays), viewMode, timelineStart) - x
        : 0;

      // Resize preview: shift left edge or right edge while dragging that handle.
      const isResizing = resizeState?.activityId === a.id;
      let resizeLeftShift = 0;
      let resizeWidthDelta = 0;
      if (isResizing && resizeState) {
        const previewDate =
          resizeState.edge === 'left'
            ? addDays(resizeState.origStart, resizeState.currentDeltaDays)
            : addDays(resizeState.origEnd, resizeState.currentDeltaDays);
        const anchor = resizeState.edge === 'left' ? resizeState.origStart : resizeState.origEnd;
        const shift =
          dateToPx(previewDate, viewMode, timelineStart) -
          dateToPx(anchor, viewMode, timelineStart);
        if (resizeState.edge === 'left') {
          resizeLeftShift = shift;
          resizeWidthDelta = -shift;
        } else {
          resizeWidthDelta = shift;
        }
      }

      const effectiveX = x + dragOffset + resizeLeftShift;
      const effectiveWidth = Math.max(width + resizeWidthDelta, MIN_BAR_WIDTH);

      const fillColor = a.color || (isCritical ? '#ef4444' : '#3b82f6');
      const bgColor = a.color
        ? `${a.color}33`
        : isCritical
          ? '#ef444433'
          : '#3b82f633';
      const progressWidth = (a.progress / 100) * width;

      if (a.isMilestone) {
        const cx = effectiveX;
        const cy = y + ROW_HEIGHT / 2;
        return (
          <g key={a.id} role="img" aria-label={`${t('gantt.milestone', 'Milestone')}: ${a.name}`}>
            <polygon
              points={`${cx},${cy - MILESTONE_SIZE} ${cx + MILESTONE_SIZE},${cy} ${cx},${cy + MILESTONE_SIZE} ${cx - MILESTONE_SIZE},${cy}`}
              fill={isCritical ? '#ef4444' : fillColor}
              stroke={isCritical ? '#b91c1c' : '#1e40af'}
              strokeWidth={1.5}
              className={onActivityClick ? 'cursor-pointer' : ''}
              onClick={() => onActivityClick?.(a.id)}
            />
          </g>
        );
      }

      if (a.isGroup) {
        // Summary / group bar: thin bar spanning children
        const barY = y + ROW_HEIGHT / 2 - 4;
        const barH = 8;
        return (
          <g key={a.id} role="img" aria-label={`${t('gantt.group', 'Group')}: ${a.name}`}>
            {/* Baseline */}
            {baselineX != null && baselineWidth != null && (
              <rect
                x={baselineX}
                y={barY + barH + 2}
                width={baselineWidth}
                height={BASELINE_HEIGHT}
                rx={2}
                fill="#9ca3af"
                opacity={0.4}
              />
            )}
            {/* Group bar background */}
            <rect
              x={effectiveX}
              y={barY}
              width={width}
              height={barH}
              rx={2}
              fill="#6b7280"
              className={onActivityClick ? 'cursor-pointer' : ''}
              onClick={() => onActivityClick?.(a.id)}
            />
            {/* Left bracket */}
            <path
              d={`M ${effectiveX} ${barY} L ${effectiveX} ${barY + barH + 4} L ${effectiveX + 5} ${barY + barH}`}
              fill="#6b7280"
            />
            {/* Right bracket */}
            <path
              d={`M ${effectiveX + width} ${barY} L ${effectiveX + width} ${barY + barH + 4} L ${effectiveX + width - 5} ${barY + barH}`}
              fill="#6b7280"
            />
            {/* Progress fill */}
            {a.progress > 0 && (
              <rect
                x={effectiveX}
                y={barY}
                width={progressWidth}
                height={barH}
                rx={2}
                fill="#374151"
              />
            )}
          </g>
        );
      }

      // Standard task bar
      const barY = y + BAR_Y_OFFSET;
      const progressDrawWidth = (a.progress / 100) * effectiveWidth;

      return (
        <g
          key={a.id}
          role="img"
          aria-label={`${a.name}: ${fmtShort(new Date(a.start), locale)} - ${fmtShort(new Date(a.end), locale)}, ${a.progress}% ${t('gantt.complete', 'complete')}`}
        >
          {/* Baseline overlay */}
          {baselineX != null && baselineWidth != null && (
            <rect
              x={baselineX}
              y={barY + BAR_HEIGHT + 2}
              width={baselineWidth}
              height={BASELINE_HEIGHT}
              rx={2}
              fill="#9ca3af"
              opacity={0.4}
            />
          )}

          {/* Bar background */}
          <rect
            x={effectiveX}
            y={barY}
            width={effectiveWidth}
            height={BAR_HEIGHT}
            rx={4}
            fill={bgColor}
            stroke={isCritical ? '#ef4444' : 'none'}
            strokeWidth={isCritical ? 2 : 0}
            className={`${onActivityDrag ? 'cursor-grab' : onActivityClick ? 'cursor-pointer' : ''} ${isDragging || isResizing ? 'opacity-70' : ''}`}
            onMouseDown={(e) => handleBarMouseDown(e, a.id)}
            onClick={() => {
              if (!isDragging && !isResizing) onActivityClick?.(a.id);
            }}
          />

          {/* Progress fill */}
          {a.progress > 0 && (
            <rect
              x={effectiveX}
              y={barY}
              width={Math.min(progressDrawWidth, effectiveWidth)}
              height={BAR_HEIGHT}
              rx={4}
              fill={fillColor}
              opacity={0.85}
              className="pointer-events-none"
            />
          )}

          {/* Right edge clip for progress (keep rounded corners) */}
          {a.progress > 0 && a.progress < 100 && progressDrawWidth < effectiveWidth - 4 && (
            <rect
              x={effectiveX + progressDrawWidth - 1}
              y={barY}
              width={2}
              height={BAR_HEIGHT}
              fill={fillColor}
              opacity={0.85}
              className="pointer-events-none"
            />
          )}

          {/* Bar label if wide enough */}
          {effectiveWidth > 50 && (
            <text
              x={effectiveX + 6}
              y={barY + BAR_HEIGHT / 2}
              dominantBaseline="central"
              className="pointer-events-none select-none fill-current text-[11px] font-medium"
              fill={a.progress > 40 ? '#ffffff' : '#1f2937'}
            >
              {a.name.length > Math.floor(effectiveWidth / 7)
                ? a.name.slice(0, Math.floor(effectiveWidth / 7)) + '...'
                : a.name}
            </text>
          )}

          {/* BIM link indicator (3D cube icon) */}
          {a.bim_element_ids && a.bim_element_ids.length > 0 && (
            <g
              transform={`translate(${effectiveX + effectiveWidth - 16}, ${barY + 2})`}
              className="pointer-events-none"
            >
              <rect
                x={0}
                y={0}
                width={14}
                height={14}
                rx={3}
                fill="#6366f1"
                opacity={0.85}
              />
              {/* Simplified 3D cube path */}
              <path
                d="M7 3 L10.5 5 L10.5 9 L7 11 L3.5 9 L3.5 5 Z M7 7 L10.5 5 M7 7 L3.5 5 M7 7 L7 11"
                stroke="white"
                strokeWidth={0.8}
                fill="none"
              />
            </g>
          )}

          {/* Edge resize handles (rendered last so they sit above bar fill) */}
          {onActivityResize && effectiveWidth >= MIN_BAR_WIDTH * 2 && (
            <>
              <rect
                x={effectiveX - RESIZE_HANDLE_WIDTH / 2}
                y={barY}
                width={RESIZE_HANDLE_WIDTH}
                height={BAR_HEIGHT}
                fill="transparent"
                style={{ cursor: 'ew-resize' }}
                onMouseDown={(e) => handleResizeMouseDown(e, a.id, 'left')}
              />
              <rect
                x={effectiveX + effectiveWidth - RESIZE_HANDLE_WIDTH / 2}
                y={barY}
                width={RESIZE_HANDLE_WIDTH}
                height={BAR_HEIGHT}
                fill="transparent"
                style={{ cursor: 'ew-resize' }}
                onMouseDown={(e) => handleResizeMouseDown(e, a.id, 'right')}
              />
            </>
          )}
        </g>
      );
    },
    [
      showCriticalPath,
      showBaseline,
      dragState,
      resizeState,
      viewMode,
      timelineStart,
      locale,
      t,
      onActivityClick,
      onActivityDrag,
      onActivityResize,
      handleBarMouseDown,
      handleResizeMouseDown,
    ],
  );

  /* ── Render ─────────────────────────────────────────────────── */

  return (
    <div
      className={`flex overflow-hidden rounded-xl border border-border-light bg-surface-primary ${className}`}
      style={{ height: Math.min(bodyHeight + HEADER_HEIGHT + 2, 800) }}
    >
      {/* ── Left panel: activity table (resizable columns) ──────────── */}
      <div className="flex flex-col" style={{ width: tableWidth, minWidth: tableWidth }}>
        {/* Table header */}
        <div
          className="flex shrink-0 border-b border-r border-border-light bg-surface-secondary/60"
          style={{ height: HEADER_HEIGHT }}
        >
          {GRID_COLUMNS.map((col) => (
            <div
              key={col.id}
              className="relative flex shrink-0 items-end px-2 pb-1.5"
              style={{
                width: colWidths[col.id] ?? col.def,
                justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
              }}
            >
              <span className="truncate text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t(col.labelKey, col.labelDefault)}
              </span>
              <span
                role="separator"
                aria-orientation="vertical"
                aria-label={t('gantt.resize_column', 'Resize column')}
                onMouseDown={(e) => startColResize(e, col.id)}
                onClick={(e) => e.stopPropagation()}
                title={t('gantt.resize_column', 'Resize column')}
                className="group absolute right-0 top-0 flex h-full w-2 cursor-col-resize justify-center hover:bg-oe-blue/10"
              >
                <span
                  aria-hidden="true"
                  className="h-full w-px bg-border group-hover:w-0.5 group-hover:bg-oe-blue"
                />
              </span>
            </div>
          ))}
        </div>

        {/* Table body (scroll synced) */}
        <div
          ref={tableBodyRef}
          className="flex-1 overflow-y-auto overflow-x-hidden border-r border-border-light"
          onScroll={handleTableScroll}
          style={{ scrollbarWidth: 'none' }}
        >
          {visibleActivities.map((a, idx) => {
            const startD = new Date(a.start);
            const endD = new Date(a.end);
            const isCritical = showCriticalPath && a.isCritical;
            const depth = depthMap.get(a.id) ?? 0;
            const predText = (a.predecessors ?? [])
              .map((p) => `${p.label} ${p.type}`)
              .join(', ');
            const lagText = (a.predecessors ?? [])
              .map((p) => `${p.lag > 0 ? `+${p.lag}` : p.lag}${t('gantt.day_suffix', 'd')}`)
              .join(', ');
            const editable = !!onActivityFieldChange;
            const isEditing = (col: EditableCol) =>
              editingCell?.id === a.id && editingCell.col === col;
            const durationVal = a.durationDays ?? daysBetween(startD, endD);
            const startISO = (a.start ?? '').slice(0, 10);
            const endISO = (a.end ?? '').slice(0, 10);
            const singlePred = (a.predecessors?.length ?? 0) === 1;
            const hover = editable ? ' cursor-text rounded px-0.5 hover:bg-surface-secondary/70' : '';
            const editor = (type: 'text' | 'number' | 'date', cls: string, min?: number, max?: number) => (
              <input
                autoFocus
                type={type}
                value={editValue}
                min={min}
                max={max}
                step={type === 'number' ? 1 : undefined}
                inputMode={type === 'number' ? 'numeric' : undefined}
                onChange={(e) => setEditValue(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onBlur={commitEdit}
                onKeyDown={handleEditKey}
                className={cls}
              />
            );

            const renderCell = (col: GridColumn) => {
              switch (col.id) {
                case 'wbs':
                  return isEditing('wbs') ? (
                    editor('text', EDIT_INPUT_CLS)
                  ) : (
                    <span
                      className={`block w-full truncate text-2xs tabular-nums text-content-tertiary${hover}`}
                      title={a.wbsCode || undefined}
                      onClick={(e) => beginEdit(e, a.id, 'wbs', a.wbsCode ?? '')}
                    >
                      {a.wbsCode || '—'}
                    </span>
                  );
                case 'name':
                  return (
                    <div
                      className="flex w-full min-w-0 items-center gap-1"
                      style={{ paddingLeft: depth * 14 }}
                    >
                      {/* Collapse toggle for summary/group activities */}
                      {a.isGroup ? (
                        <button
                          type="button"
                          title={collapsedIds.has(a.id) ? t('gantt.expand', 'Expand') : t('gantt.collapse', 'Collapse')}
                          onClick={(e) => { e.stopPropagation(); toggleCollapse(a.id); }}
                          className="shrink-0 flex items-center justify-center w-4 h-4 rounded hover:bg-surface-secondary"
                        >
                          <ChevronRight
                            size={11}
                            className={`transition-transform duration-150 text-content-tertiary ${collapsedIds.has(a.id) ? '' : 'rotate-90'}`}
                          />
                        </button>
                      ) : a.isMilestone ? (
                        <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0 ml-0.5 mr-0.5">
                          <polygon
                            points="5,0 10,5 5,10 0,5"
                            fill={isCritical ? '#ef4444' : '#3b82f6'}
                          />
                        </svg>
                      ) : (
                        <span className="shrink-0 w-4" />
                      )}
                      {isEditing('name') ? (
                        editor(
                          'text',
                          'min-w-0 flex-1 rounded border border-oe-blue bg-surface-primary px-1 py-0.5 text-xs',
                        )
                      ) : (
                        <span
                          className={`min-w-0 truncate text-xs ${
                            a.isGroup ? 'font-bold' : 'font-medium'
                          } text-content-primary${hover}`}
                          title={a.name}
                          onClick={(e) => beginEdit(e, a.id, 'name', a.name)}
                        >
                          {a.name}
                        </span>
                      )}
                      {isCritical && (
                        <span className="shrink-0 rounded bg-red-500 px-1 py-0.5 text-[8px] font-bold leading-none text-white">
                          CP
                        </span>
                      )}
                    </div>
                  );
                case 'duration':
                  if (a.isMilestone)
                    return (
                      <span className="block w-full truncate text-right text-2xs tabular-nums text-content-tertiary">
                        —
                      </span>
                    );
                  return isEditing('duration') ? (
                    editor('number', `${EDIT_INPUT_CLS} text-right`, 1)
                  ) : (
                    <span
                      className={`block w-full truncate text-right text-2xs tabular-nums text-content-tertiary${hover}`}
                      onClick={(e) => beginEdit(e, a.id, 'duration', String(durationVal))}
                    >
                      {`${durationVal}${t('gantt.day_suffix', 'd')}`}
                    </span>
                  );
                case 'start':
                  return isEditing('start') ? (
                    editor('date', DATE_INPUT_CLS)
                  ) : (
                    <span
                      className={`block w-full truncate text-right text-2xs tabular-nums text-content-tertiary${hover}`}
                      onClick={(e) => beginEdit(e, a.id, 'start', startISO)}
                    >
                      {fmtShort(startD, locale)}
                    </span>
                  );
                case 'end':
                  return isEditing('end') ? (
                    editor('date', DATE_INPUT_CLS)
                  ) : (
                    <span
                      className={`block w-full truncate text-right text-2xs tabular-nums text-content-tertiary${hover}`}
                      onClick={(e) => beginEdit(e, a.id, 'end', endISO)}
                    >
                      {fmtShort(endD, locale)}
                    </span>
                  );
                case 'predecessors':
                  return (
                    <span
                      className="block w-full truncate text-2xs tabular-nums text-content-tertiary"
                      title={predText || undefined}
                    >
                      {predText || '—'}
                    </span>
                  );
                case 'lag':
                  return isEditing('lag') ? (
                    editor('number', `${EDIT_INPUT_CLS} text-right`)
                  ) : (
                    <span
                      className={`block w-full truncate text-right text-2xs tabular-nums text-content-tertiary${
                        singlePred ? hover : ''
                      }`}
                      title={lagText || undefined}
                      onClick={
                        singlePred
                          ? (e) => beginEdit(e, a.id, 'lag', String(a.predecessors?.[0]?.lag ?? 0))
                          : undefined
                      }
                    >
                      {lagText || '—'}
                    </span>
                  );
                case 'progress':
                  return isEditing('progress') ? (
                    editor('number', `${EDIT_INPUT_CLS} text-right`, 0, 100)
                  ) : (
                    <span
                      className={`block w-full truncate text-right text-2xs font-medium tabular-nums ${
                        a.progress >= 100
                          ? 'text-green-600'
                          : a.progress > 0
                            ? 'text-blue-600'
                            : 'text-content-tertiary'
                      }${hover}`}
                      onClick={(e) => beginEdit(e, a.id, 'progress', String(a.progress))}
                    >
                      {a.progress}
                    </span>
                  );
                default:
                  return null;
              }
            };

            return (
              <div
                key={a.id}
                data-activity-row={a.id}
                title={
                  onActivityReorder
                    ? t('gantt.reorder_hint', 'Drag to move · Alt+↑↓ reorder · Alt+→← indent/outdent')
                    : undefined
                }
                draggable={!!onActivityReorder && !editingCell}
                tabIndex={onActivityReorder ? 0 : undefined}
                onKeyDown={onActivityReorder ? (e) => handleRowKeyDown(e, a.id) : undefined}
                onDragStart={
                  onActivityReorder
                    ? (e) => {
                        setRowDragId(a.id);
                        e.dataTransfer.effectAllowed = 'move';
                      }
                    : undefined
                }
                onDragOver={
                  onActivityReorder && rowDragId && rowDragId !== a.id
                    ? (e) => {
                        e.preventDefault();
                        setRowDragOverId(a.id);
                      }
                    : undefined
                }
                onDragLeave={
                  onActivityReorder
                    ? () => setRowDragOverId((c) => (c === a.id ? null : c))
                    : undefined
                }
                onDrop={
                  onActivityReorder
                    ? (e) => {
                        e.preventDefault();
                        handleRowDrop(a.id);
                      }
                    : undefined
                }
                onDragEnd={
                  onActivityReorder
                    ? () => {
                        setRowDragId(null);
                        setRowDragOverId(null);
                      }
                    : undefined
                }
                className={`flex items-center border-b border-border-light/60 transition-colors hover:bg-surface-secondary/40 ${
                  idx % 2 === 0 ? 'bg-surface-primary' : 'bg-surface-secondary/20'
                } ${isCritical ? 'bg-red-50 dark:bg-red-950/20' : ''} ${
                  onActivityClick ? 'cursor-pointer' : ''
                } ${rowDragId === a.id ? 'opacity-50' : ''} ${
                  rowDragOverId === a.id ? 'border-t-2 border-t-oe-blue' : ''
                } ${
                  onActivityReorder
                    ? 'outline-none focus:bg-oe-blue/5 focus:ring-1 focus:ring-inset focus:ring-oe-blue/40'
                    : ''
                }`}
                style={{ height: ROW_HEIGHT }}
                onClick={() => onActivityClick?.(a.id)}
              >
                {GRID_COLUMNS.map((col) => (
                  <div
                    key={col.id}
                    className="flex min-w-0 shrink-0 items-center px-2"
                    style={{ width: colWidths[col.id] ?? col.def }}
                  >
                    {renderCell(col)}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Right panel: SVG timeline ───────────────────────────── */}
      <div
        ref={svgScrollRef}
        className="flex-1 overflow-auto"
        onScroll={handleSvgScroll}
      >
        <svg
          width={timelineWidth}
          height={bodyHeight + HEADER_HEIGHT}
          className="select-none"
          role="img"
          aria-label={t('gantt.chart_label', 'Gantt chart with {{count}} activities', {
            count: visibleActivities.length,
          })}
        >
          <defs>
            {/* Arrowhead marker */}
            <marker
              id="gantt-svg-arrowhead"
              markerWidth="8"
              markerHeight="6"
              refX="7"
              refY="3"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path d="M 0 0 L 8 3 L 0 6 Z" fill="#94a3b8" />
            </marker>
          </defs>

          {/* ── Header area ─────────────────────────────────────── */}
          <g className="gantt-header">
            {/* Header background */}
            <rect x={0} y={0} width={timelineWidth} height={HEADER_HEIGHT} fill="var(--color-surface-secondary, #f8fafc)" opacity={0.6} />
            <line x1={0} y1={HEADER_HEIGHT} x2={timelineWidth} y2={HEADER_HEIGHT} stroke="var(--color-border-light, #e2e8f0)" strokeWidth={1} />

            {/* Top row */}
            {headers.topRow.map((cell, i) => (
              <g key={`top-${i}`}>
                {i > 0 && (
                  <line
                    x1={cell.x}
                    y1={0}
                    x2={cell.x}
                    y2={HEADER_HEIGHT / 2}
                    stroke="var(--color-border-light, #e2e8f0)"
                    strokeWidth={1}
                  />
                )}
                <text
                  x={cell.x + 6}
                  y={HEADER_HEIGHT / 4 + 1}
                  dominantBaseline="central"
                  className="fill-current text-[10px] font-semibold uppercase tracking-wider"
                  fill="var(--color-content-tertiary, #94a3b8)"
                >
                  {cell.label}
                </text>
              </g>
            ))}

            {/* Separator line between top and bottom header rows */}
            <line
              x1={0}
              y1={HEADER_HEIGHT / 2}
              x2={timelineWidth}
              y2={HEADER_HEIGHT / 2}
              stroke="var(--color-border-light, #e2e8f0)"
              strokeWidth={0.5}
            />

            {/* Bottom row */}
            {headers.bottomRow.map((cell, i) => (
              <g key={`bot-${i}`}>
                <line
                  x1={cell.x}
                  y1={HEADER_HEIGHT / 2}
                  x2={cell.x}
                  y2={HEADER_HEIGHT}
                  stroke="var(--color-border-light, #e2e8f0)"
                  strokeWidth={0.5}
                />
                <text
                  x={cell.x + Math.max(cell.width / 2, 4)}
                  y={HEADER_HEIGHT * 0.75 + 1}
                  dominantBaseline="central"
                  textAnchor="middle"
                  className="fill-current text-[10px] font-medium"
                  fill="var(--color-content-tertiary, #94a3b8)"
                >
                  {cell.label}
                </text>
              </g>
            ))}
          </g>

          {/* ── Body area ───────────────────────────────────────── */}
          <g transform={`translate(0, ${HEADER_HEIGHT})`}>
            {/* Alternating row backgrounds */}
            {visibleActivities.map((_a, idx) => (
              <rect
                key={`row-bg-${idx}`}
                x={0}
                y={idx * ROW_HEIGHT}
                width={timelineWidth}
                height={ROW_HEIGHT}
                fill={idx % 2 === 0 ? 'transparent' : 'var(--color-surface-secondary, #f8fafc)'}
                opacity={0.3}
              />
            ))}

            {/* Horizontal row separators */}
            {visibleActivities.map((_a, idx) => (
              <line
                key={`row-line-${idx}`}
                x1={0}
                y1={(idx + 1) * ROW_HEIGHT}
                x2={timelineWidth}
                y2={(idx + 1) * ROW_HEIGHT}
                stroke="var(--color-border-light, #e2e8f0)"
                strokeWidth={0.5}
                opacity={0.5}
              />
            ))}

            {/* Vertical grid lines from bottom header */}
            {headers.bottomRow.map((cell, i) => (
              <line
                key={`grid-v-${i}`}
                x1={cell.x}
                y1={0}
                x2={cell.x}
                y2={bodyHeight}
                stroke="var(--color-border-light, #e2e8f0)"
                strokeWidth={0.5}
                opacity={0.4}
              />
            ))}

            {/* Today line */}
            {todayX != null && (
              <g>
                <line
                  x1={todayX}
                  y1={0}
                  x2={todayX}
                  y2={bodyHeight}
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  strokeDasharray="6 3"
                  opacity={0.7}
                />
                <rect
                  x={todayX - 18}
                  y={-2}
                  width={36}
                  height={14}
                  rx={3}
                  fill="#ef4444"
                />
                <text
                  x={todayX}
                  y={5}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="text-[9px] font-bold"
                  fill="white"
                >
                  {t('gantt.today', 'Today')}
                </text>
              </g>
            )}

            {/* Dependency arrows */}
            {arrowPaths.map((arrow) => (
              <path
                key={arrow.key}
                d={arrow.d}
                fill="none"
                stroke="#94a3b8"
                strokeWidth={1.5}
                markerEnd="url(#gantt-svg-arrowhead)"
                opacity={0.7}
              />
            ))}

            {/* Task bars, milestones, groups */}
            {bars.map((bar, idx) => renderBar(bar, idx))}
          </g>
        </svg>
      </div>
    </div>
  );
}

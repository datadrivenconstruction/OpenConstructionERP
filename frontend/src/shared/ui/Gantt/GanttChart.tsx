// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SVG-based Gantt chart component.
 *
 * Features:
 * - Two-panel layout: fixed left table + scrollable SVG timeline
 * - Task bars with progress fill, milestones (diamond), group/summary rows
 * - Dependency arrows, anchored by link type (FS, SS, FF, SF)
 * - Critical path highlighting (red)
 * - Baseline overlay (gray)
 * - Today line (dashed red vertical)
 * - Zoom levels: day / week / month
 * - Drag to reschedule activities (pointer events: mouse, pen and touch)
 * - Drag from a bar's end handle to another bar to link them (opt-in)
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
  useId,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { fmtDate, getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  type GanttActivity,
  type GanttDependencyType,
  type ViewMode,
  ROW_HEIGHT,
  HEADER_HEIGHT,
  TABLE_WIDTH,
  dateToPx,
  pxToDate,
  daysBetween,
  addDays,
  generateTimeHeaders,
  calculateLinkPath,
  getDateRange,
  getTimelineWidth,
} from './ganttUtils';

export type { GanttActivity };

/**
 * The link a drag produces, named by the two ends involved: the handle the
 * drag left from, then the end of the target it landed on. A drop on the
 * target's body counts as its start, which is what nearly every link means.
 *
 * - finish handle -> body or start handle: FS
 * - finish handle -> finish handle: FF
 * - start handle -> body or start handle: SS
 * - start handle -> finish handle: SF
 */
export type GanttLinkType = GanttDependencyType;

/* ── Props ──────────────────────────────────────────────────────── */

export interface GanttProps {
  activities: GanttActivity[];
  viewMode?: ViewMode;
  startDate?: string;
  endDate?: string;
  onActivityClick?: (id: string) => void;
  onActivityDrag?: (id: string, newStart: string, newEnd: string) => void;
  onActivityResize?: (id: string, newStart: string, newEnd: string) => void | Promise<void>;
  /**
   * Called when the user drags from one bar's end handle onto another bar.
   * Without it no link handles are drawn and the chart behaves as before.
   * Self-links and links that already exist are refused before this is called;
   * cycles are the consumer's to reject (the server does).
   */
  onCreateLink?: (fromId: string, toId: string, type: GanttLinkType) => void | Promise<void>;
  /** Called from the menu a dependency arrow opens. Without it arrows stay inert. */
  onDeleteLink?: (fromId: string, toId: string) => void | Promise<void>;
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
// Link handles sit just OUTSIDE the bar, past the resize zone, so a press can
// only ever mean one of the two. The hit circle is 24px across for a finger;
// the drawn dot is smaller so a row of them does not read as clutter.
const LINK_HANDLE_R = 5;
const LINK_HANDLE_HIT_R = 12;
const LINK_HANDLE_OFFSET = RESIZE_HANDLE_WIDTH / 2 + LINK_HANDLE_HIT_R;

/* ── Date formatting helpers ────────────────────────────────────── */

/**
 * A date for the table columns: day and month, plus the year when asked for.
 *
 * A day and a month alone are unreadable on a programme that runs past New
 * Year - two rows both reading "20 Jan" can be twelve months apart and nothing
 * on screen says which is which. The year is therefore printed exactly when the
 * dates on screen do not all fall in one calendar year; on a programme that
 * stays inside a single year it would be the same digits on every row, which is
 * noise in a 10px column somebody scans in one pass.
 *
 * When it is printed it is printed in full. Two digits saved a little width and
 * spent it on a second reading: "05 Mar 26" puts two numbers either side of a
 * month on a row whose first number is a day of that month, and the eye has to
 * be told which is which. Every other date in the product carries four digits,
 * so this was also the one place where the same day looked like a different
 * kind of thing. The column widens to hold it.
 *
 * Formatting goes through ``fmtDate`` rather than a local ``Intl`` call so a
 * date-only ``YYYY-MM-DD`` value is pinned to UTC - read in the browser's zone
 * it renders as the previous day at any negative offset.
 */
function fmtShort(iso: string, withYear: boolean): string {
  return fmtDate(iso, {
    day: '2-digit',
    month: 'short',
    ...(withYear ? { year: 'numeric' as const } : {}),
  });
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

/**
 * The horizontal extent a bar occupies on screen. A milestone is a point drawn
 * as a diamond, so its ends are the diamond's tips rather than the point.
 */
function barEdges(bar: { activity: GanttActivity; x: number; width: number }): { left: number; right: number } {
  if (bar.activity.isMilestone) {
    return { left: bar.x - MILESTONE_SIZE, right: bar.x + MILESTONE_SIZE };
  }
  return { left: bar.x, right: bar.x + bar.width };
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
  onCreateLink,
  onDeleteLink,
  className = '',
  showBaseline = false,
  showDependencies = true,
  showCriticalPath = true,
  todayLine = true,
}: GanttProps) {
  const { t } = useTranslation();
  const locale = getIntlLocale();
  const addToast = useToastStore((s) => s.addToast);

  // Prefix for the per-cell header clip paths. Two charts can share a page, and
  // their columns land at different x, so the ids have to be per instance or one
  // chart clips its labels against the other's geometry.
  const clipPrefix = useId();

  // Refs for scroll sync
  const tableBodyRef = useRef<HTMLDivElement>(null);
  const svgScrollRef = useRef<HTMLDivElement>(null);

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

  // Link state (drag from a bar's end handle to another bar). A third state
  // rather than a mode of dragState: the handles sit outside the bar and stop
  // the press, so a link can never start while a move or resize is live.
  // `pointer` is null while a keyboard link waits for its target.
  const [linkState, setLinkState] = useState<{
    fromId: string;
    fromSide: 'start' | 'finish';
    originX: number;
    originY: number;
    pointer: { x: number; y: number } | null;
    target: { id: string; side: 'start' | 'finish' | 'body' } | null;
  } | null>(null);

  // The small menu a dependency arrow opens, positioned in body coordinates.
  // `restoreFocus`: opened from the keyboard, so focus goes back to the bar.
  const [linkMenu, setLinkMenu] = useState<{
    fromId: string;
    toId: string;
    x: number;
    y: number;
    restoreFocus: boolean;
  } | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);

  // Keyboard reach of a linkable chart. The chart is one tab stop (a roving
  // bar); arrow keys move between bars, and only the active bar's handles and
  // links join the tab order, and only while focus is inside the chart. A
  // handle and an arrow per bar each would make a 300-activity schedule
  // hundreds of Tab presses long. Charts without linking stay untouched.
  const keyboardNav = !!(onCreateLink || onDeleteLink);
  const [activeBarState, setActiveBarState] = useState<string | null>(null);
  const [chartFocused, setChartFocused] = useState(false);
  const keyboardHintId = useId();

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

  const bodyHeight = activities.length * ROW_HEIGHT;

  // Does the table need to print years? Measured on the dates the table itself
  // prints, not on the timeline range: that range comes from the schedule's own
  // start/end props and is padded by a month when there are no activities, so a
  // December programme would pad into January and claim to span two years.
  const showYear = useMemo(() => {
    const years = new Set<number>();
    for (const a of activities) {
      for (const iso of [a.start, a.end]) {
        const d = new Date(iso);
        if (!isNaN(d.getTime())) years.add(d.getUTCFullYear());
      }
    }
    return years.size > 1;
  }, [activities]);

  // The year costs a few more characters, and rather more in the locales that
  // append a period or an era marker, so the two date columns grow with it and
  // the panel grows with them. Charging it to the activity name instead would
  // truncate the one column that carries the meaning.
  // 88px held "05 Mar 26"; a four-digit year needs the two characters back, and
  // a language that writes "05. Mär. 2026" needs more than that. The dateless
  // width is unchanged, so a single-year programme keeps the table it had.
  const dateColWidth = showYear ? 104 : 70;
  const tableWidth = TABLE_WIDTH + 2 * (dateColWidth - 70);

  const rowIndex = useMemo(() => buildRowIndex(activities), [activities]);

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
    return activities.map((a) => {
      const startD = new Date(a.start);
      const endD = new Date(a.end);
      const x = dateToPx(startD, viewMode, timelineStart);
      // End dates are inclusive: an activity ending on the 5th works that day,
      // so its bar runs to the start of the 6th. A milestone stays a point.
      const xEnd = a.isMilestone ? x : dateToPx(addDays(endD, 1), viewMode, timelineStart);
      const width = Math.max(xEnd - x, MIN_BAR_WIDTH);

      let baselineX: number | undefined;
      let baselineWidth: number | undefined;
      if (showBaseline && a.baselineStart && a.baselineEnd) {
        const bsD = new Date(a.baselineStart);
        const beD = new Date(a.baselineEnd);
        baselineX = dateToPx(bsD, viewMode, timelineStart);
        const bxEnd = dateToPx(addDays(beD, 1), viewMode, timelineStart);
        baselineWidth = Math.max(bxEnd - baselineX, MIN_BAR_WIDTH);
      }

      return { activity: a, x, width, baselineX, baselineWidth };
    });
  }, [activities, viewMode, timelineStart, showBaseline]);

  /* ── Dependency arrow paths ─────────────────────────────────── */

  const arrowPaths = useMemo(() => {
    if (!showDependencies) return [];
    const paths: Array<{ key: string; d: string; fromId: string; toId: string; endX: number; endY: number }> = [];

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

        // Anchors follow the link type; a link without one is FS, as before.
        const type = bar.activity.dependencyTypes?.[predId] ?? 'FS';
        const toX = type === 'FF' || type === 'SF' ? bar.x + bar.width : bar.x;

        paths.push({
          key: `${predId}-${bar.activity.id}`,
          d: calculateLinkPath(
            type,
            { left: predBar.x, right: predBar.x + predBar.width, row: fromRow },
            { left: bar.x, right: bar.x + bar.width, row: toRow },
            ROW_HEIGHT,
          ),
          fromId: predId,
          toId: bar.activity.id,
          endX: toX,
          endY: toRow * ROW_HEIGHT + ROW_HEIGHT / 2,
        });
      }
    }

    return paths;
  }, [bars, rowIndex, showDependencies]);

  /* ── Keyboard roving ────────────────────────────────────────── */

  // Bars the keyboard visits, in row order. Summary rows take no links.
  const navIds = useMemo(
    () => bars.filter((b) => !b.activity.isGroup).map((b) => b.activity.id),
    [bars],
  );
  // Re-derived every render: a refetch can drop the remembered bar, and the
  // chart must never be left without its one tab stop.
  const activeBarId =
    activeBarState && navIds.includes(activeBarState) ? activeBarState : (navIds[0] ?? null);
  const keyFocusId = keyboardNav && chartFocused ? activeBarId : null;

  const focusBar = useCallback((id: string | null) => {
    if (!id) return;
    setActiveBarState(id);
    const el = [...(svgRef.current?.querySelectorAll<SVGGElement>('[data-testid^="gantt-bar-"]') ?? [])].find(
      (g) => g.getAttribute('data-testid') === `gantt-bar-${id}`,
    );
    el?.focus();
  }, []);

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

  // Pointer events, not mouse events, so a finger on a tablet moves and
  // resizes bars the same way a mouse does. Only the primary button starts a
  // drag; a right-click stays a right-click.
  const handleBarPointerDown = useCallback(
    (e: ReactPointerEvent, activityId: string) => {
      if (!onActivityDrag || e.button !== 0) return;
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

    const handlePointerMove = (e: PointerEvent) => {
      const dx = e.clientX - dragState.startMouseX;
      const newDate = pxToDate(
        dateToPx(dragState.origStart, viewMode, timelineStart) + dx,
        viewMode,
        timelineStart,
      );
      const offsetDays = daysBetween(dragState.origStart, newDate);
      setDragState((prev) => (prev ? { ...prev, currentOffsetDays: offsetDays } : null));
    };

    const handlePointerUp = () => {
      if (dragState.currentOffsetDays !== 0 && onActivityDrag) {
        const newStart = addDays(dragState.origStart, dragState.currentOffsetDays);
        const newEnd = addDays(dragState.origEnd, dragState.currentOffsetDays);
        onActivityDrag(dragState.activityId, toISO(newStart), toISO(newEnd));
      }
      setDragState(null);
    };

    // The browser took the pointer (a scroll, a system gesture): drop the move.
    const handlePointerCancel = () => setDragState(null);

    document.addEventListener('pointermove', handlePointerMove);
    document.addEventListener('pointerup', handlePointerUp);
    document.addEventListener('pointercancel', handlePointerCancel);
    return () => {
      document.removeEventListener('pointermove', handlePointerMove);
      document.removeEventListener('pointerup', handlePointerUp);
      document.removeEventListener('pointercancel', handlePointerCancel);
    };
  }, [dragState, onActivityDrag, viewMode, timelineStart]);

  /* ── Resize handlers ────────────────────────────────────────── */

  const handleResizePointerDown = useCallback(
    (e: ReactPointerEvent, activityId: string, edge: 'left' | 'right') => {
      if (!onActivityResize || e.button !== 0) return;
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

    const handlePointerMove = (e: PointerEvent) => {
      const dx = e.clientX - resizeState.startMouseX;
      const anchor = resizeState.edge === 'left' ? resizeState.origStart : resizeState.origEnd;
      const newDate = pxToDate(
        dateToPx(anchor, viewMode, timelineStart) + dx,
        viewMode,
        timelineStart,
      );
      let deltaDays = daysBetween(anchor, newDate);

      // Clamp so the bar stays at least 1 day wide. With inclusive ends that
      // is start == end, so a one-day bar has no room to shrink at all.
      if (resizeState.edge === 'left') {
        const maxDelta = daysBetween(resizeState.origStart, resizeState.origEnd);
        if (deltaDays > maxDelta) deltaDays = maxDelta;
      } else {
        const minDelta = -daysBetween(resizeState.origStart, resizeState.origEnd);
        if (deltaDays < minDelta) deltaDays = minDelta;
      }

      setResizeState((prev) => (prev ? { ...prev, currentDeltaDays: deltaDays } : null));
    };

    const handlePointerUp = () => {
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

    const handlePointerCancel = () => setResizeState(null);

    document.addEventListener('pointermove', handlePointerMove);
    document.addEventListener('pointerup', handlePointerUp);
    document.addEventListener('pointercancel', handlePointerCancel);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointermove', handlePointerMove);
      document.removeEventListener('pointerup', handlePointerUp);
      document.removeEventListener('pointercancel', handlePointerCancel);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [resizeState, onActivityResize, viewMode, timelineStart]);

  /* ── Link handlers ──────────────────────────────────────────── */

  // Client coordinates to body coordinates (svg x, y below the header). The
  // svg's rect moves with the scroll container, so this holds while scrolled.
  const toBodyPoint = useCallback((clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    return {
      x: clientX - (rect?.left ?? 0),
      y: clientY - (rect?.top ?? 0) - HEADER_HEIGHT,
    };
  }, []);

  // Which bar a body point lands on, and on which part of it. Read from the
  // geometry rather than from the element under the pointer: on touch the
  // browser keeps sending events to the handle the finger went down on, so the
  // element under the finger is never the target bar.
  const hitTestBar = useCallback(
    (x: number, y: number): { id: string; side: 'start' | 'finish' | 'body' } | null => {
      if (y < 0) return null;
      const bar = bars[Math.floor(y / ROW_HEIGHT)];
      if (!bar || bar.activity.isGroup) return null;
      const { left, right } = barEdges(bar);
      const reach = LINK_HANDLE_OFFSET + LINK_HANDLE_HIT_R;
      if (x < left - reach || x > right + reach) return null;
      const side = x > right ? 'finish' : x < left ? 'start' : 'body';
      return { id: bar.activity.id, side };
    },
    [bars],
  );

  const commitLink = useCallback(
    (
      fromId: string,
      fromSide: 'start' | 'finish',
      target: { id: string; side: 'start' | 'finish' | 'body' } | null,
    ) => {
      setLinkState(null);
      if (!onCreateLink || !target || target.id === fromId) return;
      const to = activities.find((a) => a.id === target.id);
      if (to?.dependencies?.includes(fromId)) {
        addToast({
          type: 'info',
          title: t('gantt.link_exists', { defaultValue: 'These activities are already linked' }),
        });
        return;
      }
      const toFinish = target.side === 'finish';
      const type: GanttLinkType =
        fromSide === 'start' ? (toFinish ? 'SF' : 'SS') : toFinish ? 'FF' : 'FS';
      void onCreateLink(fromId, target.id, type);
    },
    [onCreateLink, activities, addToast, t],
  );

  const handleLinkPointerDown = useCallback(
    (
      e: ReactPointerEvent<SVGElement>,
      activityId: string,
      side: 'start' | 'finish',
      originX: number,
      originY: number,
    ) => {
      if (!onCreateLink || e.button !== 0) return;
      // preventDefault also suppresses the compatibility mousedown, so the bar
      // underneath can never pick this press up as the start of a move.
      e.preventDefault();
      e.stopPropagation();
      setLinkMenu(null);
      setLinkState({
        fromId: activityId,
        fromSide: side,
        originX,
        originY,
        pointer: { x: originX, y: originY },
        target: null,
      });
    },
    [onCreateLink],
  );

  // Keyboard: Enter on a handle arms a link from that end, Enter on another
  // bar's handle completes it, Escape (or Enter on the same bar) drops it.
  const handleLinkKeyDown = useCallback(
    (
      e: ReactKeyboardEvent<SVGElement>,
      activityId: string,
      side: 'start' | 'finish',
      originX: number,
      originY: number,
    ) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      e.stopPropagation();
      if (linkState && linkState.pointer === null) {
        if (linkState.fromId === activityId) setLinkState(null);
        else commitLink(linkState.fromId, linkState.fromSide, { id: activityId, side });
        return;
      }
      setLinkMenu(null);
      setLinkState({ fromId: activityId, fromSide: side, originX, originY, pointer: null, target: null });
    },
    [linkState, commitLink],
  );

  // Keyboard on a bar (or anything inside it): Up/Down/Home/End rove between
  // bars. Enter on the bar itself completes an armed link onto its body, or
  // otherwise opens the activity like a click.
  const handleBarKeyDown = useCallback(
    (e: ReactKeyboardEvent<SVGGElement>, activityId: string) => {
      const i = navIds.indexOf(activityId);
      let next: string | undefined;
      if (e.key === 'ArrowDown') next = navIds[i + 1];
      else if (e.key === 'ArrowUp') next = navIds[i - 1];
      else if (e.key === 'Home') next = navIds[0];
      else if (e.key === 'End') next = navIds[navIds.length - 1];
      else if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
        e.preventDefault();
        if (linkState && linkState.pointer === null) {
          if (linkState.fromId === activityId) setLinkState(null);
          else commitLink(linkState.fromId, linkState.fromSide, { id: activityId, side: 'body' });
        } else {
          onActivityClick?.(activityId);
        }
        return;
      } else {
        return;
      }
      e.preventDefault();
      if (next) focusBar(next);
    },
    [navIds, linkState, commitLink, onActivityClick, focusBar],
  );

  // Closing the arrow menu hands focus back to the bar when the menu was
  // opened from the keyboard; otherwise focus would fall to the page.
  const closeLinkMenu = useCallback(() => {
    if (linkMenu?.restoreFocus) focusBar(activeBarId);
    setLinkMenu(null);
  }, [linkMenu, activeBarId, focusBar]);

  useEffect(() => {
    if (!linkState) return;
    const { fromId, fromSide } = linkState;
    const pointerDriven = linkState.pointer !== null;

    const handlePointerMove = (e: PointerEvent) => {
      const p = toBodyPoint(e.clientX, e.clientY);
      const hit = hitTestBar(p.x, p.y);
      setLinkState((prev) =>
        prev && prev.pointer
          ? { ...prev, pointer: p, target: hit && hit.id !== prev.fromId ? hit : null }
          : prev,
      );
    };
    const handlePointerUp = (e: PointerEvent) => {
      const p = toBodyPoint(e.clientX, e.clientY);
      commitLink(fromId, fromSide, hitTestBar(p.x, p.y));
    };
    const handleCancel = () => setLinkState(null);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLinkState(null);
    };

    document.addEventListener('keydown', handleKeyDown);
    if (pointerDriven) {
      document.addEventListener('pointermove', handlePointerMove);
      document.addEventListener('pointerup', handlePointerUp);
      document.addEventListener('pointercancel', handleCancel);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointermove', handlePointerMove);
      document.removeEventListener('pointerup', handlePointerUp);
      document.removeEventListener('pointercancel', handleCancel);
    };
  }, [linkState, toBodyPoint, hitTestBar, commitLink]);

  // The arrow menu closes on Escape, like every other popover in the app.
  useEffect(() => {
    if (!linkMenu) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeLinkMenu();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [linkMenu, closeLinkMenu]);

  /* ── Render helpers ─────────────────────────────────────────── */

  // The two end handles a bar offers for linking. Hidden until the bar is
  // hovered or a handle has keyboard focus, always shown on touch screens
  // (no hover there) and while a link is being drawn, so every drop target
  // shows where its ends are.
  const renderLinkHandles = useCallback(
    (a: GanttActivity, left: number, right: number, cy: number, inset: number) => {
      if (!onCreateLink || a.isGroup) return null;
      // Hidden handles must also stop taking the pointer: their hit circles
      // cover the first and last stretch of every arrow, so a click meant to
      // open an arrow's menu would start a link drag instead. They take it
      // only while visible to a pointer: bar hovered, a touch screen, or a
      // link in progress. Keyboard focus needs no pointer events, but the
      // keyboard's active bar shows its handles so Tab has somewhere visible
      // to land.
      const keyActive = keyFocusId === a.id;
      const visibility = linkState || keyActive
        ? 'opacity-100 pointer-events-auto'
        : 'opacity-0 pointer-events-none group-hover/bar:opacity-100 group-hover/bar:pointer-events-auto ' +
          'focus-within:opacity-100 [@media(hover:none)]:opacity-70 [@media(hover:none)]:pointer-events-auto';
      return (
        <g className={`transition-opacity ${visibility}`} data-testid={`gantt-link-handles-${a.id}`}>
          {/* Bridges from the bar's edge (or the outer side of its resize
              zone, which they must not cover) to each handle, so the pointer
              keeps the bar hovered on its way out to a handle. */}
          <rect
            x={left - LINK_HANDLE_OFFSET}
            y={cy - BAR_HEIGHT / 2}
            width={Math.max(0, LINK_HANDLE_OFFSET - inset)}
            height={BAR_HEIGHT}
            fill="transparent"
          />
          <rect
            x={right + inset}
            y={cy - BAR_HEIGHT / 2}
            width={Math.max(0, LINK_HANDLE_OFFSET - inset)}
            height={BAR_HEIGHT}
            fill="transparent"
          />
          {(['start', 'finish'] as const).map((side) => {
            const cx = side === 'start' ? left - LINK_HANDLE_OFFSET : right + LINK_HANDLE_OFFSET;
            const armed = linkState?.fromId === a.id && linkState.fromSide === side;
            const label =
              side === 'start'
                ? t('gantt.link_from_start', { defaultValue: 'Link from the start of {{name}}', name: a.name })
                : t('gantt.link_from_finish', { defaultValue: 'Link from the finish of {{name}}', name: a.name });
            return (
              <g
                key={side}
                data-testid={`gantt-link-handle-${a.id}-${side}`}
                role="button"
                tabIndex={keyActive ? 0 : -1}
                aria-label={label}
                aria-pressed={armed}
                className="group/handle cursor-crosshair outline-none"
                style={{ touchAction: 'none' }}
                onPointerDown={(e) => handleLinkPointerDown(e, a.id, side, cx, cy)}
                onKeyDown={(e) => handleLinkKeyDown(e, a.id, side, cx, cy)}
              >
                <title>{label}</title>
                <circle cx={cx} cy={cy} r={LINK_HANDLE_HIT_R} fill="transparent" />
                <circle
                  cx={cx}
                  cy={cy}
                  r={armed ? LINK_HANDLE_R + 1.5 : LINK_HANDLE_R}
                  fill={armed ? '#2563eb' : '#ffffff'}
                  stroke="#2563eb"
                  strokeWidth={1.5}
                  className="pointer-events-none group-focus-visible/handle:[stroke-width:3]"
                />
              </g>
            );
          })}
        </g>
      );
    },
    [onCreateLink, linkState, keyFocusId, t, handleLinkPointerDown, handleLinkKeyDown],
  );

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
      // Children of role="img" are presentational, so a bar carrying link
      // handles (buttons) is labelled as a group instead, or the handles
      // would be unreachable to a screen reader.
      const barRole = onCreateLink ? 'group' : 'img';
      // Roving focus: one bar is the tab stop, the rest are reached by arrows.
      const barKeyProps = keyboardNav
        ? {
            'data-testid': `gantt-bar-${a.id}`,
            tabIndex: a.id === activeBarId ? 0 : -1,
            onFocus: () => setActiveBarState(a.id),
            onKeyDown: (e: ReactKeyboardEvent<SVGGElement>) => handleBarKeyDown(e, a.id),
          }
        : {};
      // Drawn rather than left to the browser: an outline on an svg <g> is
      // not reliably painted, and would wrap the handles too.
      const focusRing = (left: number, right: number, top: number, height: number) =>
        keyFocusId === a.id && (
          <rect
            data-testid="gantt-bar-focus"
            x={left - 3}
            y={top - 3}
            width={right - left + 6}
            height={height + 6}
            rx={6}
            fill="none"
            stroke="#2563eb"
            strokeWidth={2}
            className="pointer-events-none"
          />
        );

      if (a.isMilestone) {
        const cx = effectiveX;
        const cy = y + ROW_HEIGHT / 2;
        return (
          <g
            key={a.id}
            role={barRole}
            className="group/bar outline-none"
            aria-label={`${t('gantt.milestone', 'Milestone')}: ${a.name}`}
            {...barKeyProps}
          >
            {focusRing(cx - MILESTONE_SIZE, cx + MILESTONE_SIZE, cy - MILESTONE_SIZE, MILESTONE_SIZE * 2)}
            <polygon
              points={`${cx},${cy - MILESTONE_SIZE} ${cx + MILESTONE_SIZE},${cy} ${cx},${cy + MILESTONE_SIZE} ${cx - MILESTONE_SIZE},${cy}`}
              fill={isCritical ? '#ef4444' : fillColor}
              stroke={isCritical ? '#b91c1c' : '#1e40af'}
              strokeWidth={1.5}
              className={onActivityClick ? 'cursor-pointer' : ''}
              onClick={() => onActivityClick?.(a.id)}
            />
            {renderLinkHandles(a, cx - MILESTONE_SIZE, cx + MILESTONE_SIZE, cy, 0)}
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
          role={barRole}
          className="group/bar outline-none"
          aria-label={`${a.name}: ${fmtShort(a.start, showYear)} - ${fmtShort(a.end, showYear)}, ${a.progress}% ${t('gantt.complete', 'complete')}`}
          {...barKeyProps}
        >
          {focusRing(effectiveX, effectiveX + effectiveWidth, barY, BAR_HEIGHT)}

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
            // A movable bar claims the touch gesture; otherwise the browser
            // reads a finger drag as a scroll and cancels the pointer.
            style={onActivityDrag ? { touchAction: 'none' } : undefined}
            onPointerDown={(e) => handleBarPointerDown(e, a.id)}
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
                style={{ cursor: 'ew-resize', touchAction: 'none' }}
                onPointerDown={(e) => handleResizePointerDown(e, a.id, 'left')}
              />
              <rect
                x={effectiveX + effectiveWidth - RESIZE_HANDLE_WIDTH / 2}
                y={barY}
                width={RESIZE_HANDLE_WIDTH}
                height={BAR_HEIGHT}
                fill="transparent"
                style={{ cursor: 'ew-resize', touchAction: 'none' }}
                onPointerDown={(e) => handleResizePointerDown(e, a.id, 'right')}
              />
            </>
          )}

          {renderLinkHandles(
            a,
            effectiveX,
            effectiveX + effectiveWidth,
            barY + BAR_HEIGHT / 2,
            onActivityResize && effectiveWidth >= MIN_BAR_WIDTH * 2 ? RESIZE_HANDLE_WIDTH / 2 : 0,
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
      showYear,
      t,
      onActivityClick,
      onActivityDrag,
      onActivityResize,
      onCreateLink,
      handleBarPointerDown,
      handleResizePointerDown,
      renderLinkHandles,
      keyboardNav,
      activeBarId,
      keyFocusId,
      handleBarKeyDown,
    ],
  );

  /* ── Link preview geometry ──────────────────────────────────── */

  // The bar a drag is currently over, outlined so the planner sees what the
  // drop will link to before letting go.
  const linkTargetBar = useMemo(() => {
    const id = linkState?.target?.id;
    if (!id) return null;
    const row = rowIndex.get(id);
    if (row == null) return null;
    const bar = bars[row];
    if (!bar) return null;
    const { left, right } = barEdges(bar);
    return { left, right, y: row * ROW_HEIGHT + BAR_Y_OFFSET };
  }, [linkState, rowIndex, bars]);

  const linkMenuNames = useMemo(() => {
    if (!linkMenu) return null;
    const name = (id: string) => activities.find((a) => a.id === id)?.name ?? id;
    return { from: name(linkMenu.fromId), to: name(linkMenu.toId) };
  }, [linkMenu, activities]);

  /* ── Render ─────────────────────────────────────────────────── */

  return (
    <div
      className={`flex overflow-hidden rounded-xl border border-border-light bg-surface-primary ${className}`}
      style={{ height: Math.min(bodyHeight + HEADER_HEIGHT + 2, 800) }}
    >
      {/* ── Left panel: activity table ──────────────────────────── */}
      <div className="flex flex-col" style={{ width: tableWidth, minWidth: tableWidth }}>
        {/* Table header */}
        <div
          className="flex shrink-0 border-b border-r border-border-light bg-surface-secondary/60"
          style={{ height: HEADER_HEIGHT }}
        >
          <div className="flex flex-1 items-end px-3 pb-1.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('gantt.activity_name', 'Activity')}
            </span>
          </div>
          <div
            className="flex shrink-0 items-end justify-end px-2 pb-1.5"
            style={{ width: dateColWidth }}
          >
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('gantt.start', 'Start')}
            </span>
          </div>
          <div
            className="flex shrink-0 items-end justify-end px-2 pb-1.5"
            style={{ width: dateColWidth }}
          >
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('gantt.end', 'End')}
            </span>
          </div>
          <div className="flex w-[36px] items-end justify-end px-1 pb-1.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              %
            </span>
          </div>
        </div>

        {/* Table body (scroll synced) */}
        <div
          ref={tableBodyRef}
          className="flex-1 overflow-y-auto overflow-x-hidden border-r border-border-light"
          onScroll={handleTableScroll}
          style={{ scrollbarWidth: 'none' }}
        >
          {activities.map((a, idx) => {
            const isCritical = showCriticalPath && a.isCritical;

            return (
              <div
                key={a.id}
                className={`flex items-center border-b border-border-light/60 transition-colors hover:bg-surface-secondary/40 ${
                  idx % 2 === 0 ? 'bg-surface-primary' : 'bg-surface-secondary/20'
                } ${isCritical ? 'bg-red-50 dark:bg-red-950/20' : ''} ${
                  onActivityClick ? 'cursor-pointer' : ''
                }`}
                style={{ height: ROW_HEIGHT }}
                onClick={() => onActivityClick?.(a.id)}
              >
                <div className="flex min-w-0 flex-1 items-center gap-1.5 px-3">
                  {a.isMilestone && (
                    <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0">
                      <polygon
                        points="5,0 10,5 5,10 0,5"
                        fill={isCritical ? '#ef4444' : '#3b82f6'}
                      />
                    </svg>
                  )}
                  {a.isGroup && (
                    <span className="shrink-0 text-content-tertiary text-[10px] font-bold">
                      [G]
                    </span>
                  )}
                  <span
                    className={`truncate text-xs ${
                      a.isGroup ? 'font-bold' : 'font-medium'
                    } text-content-primary`}
                    title={a.name}
                  >
                    {a.name}
                  </span>
                  {isCritical && (
                    <span className="shrink-0 rounded bg-red-500 px-1 py-0.5 text-[8px] font-bold leading-none text-white">
                      CP
                    </span>
                  )}
                </div>
                <div
                  className="shrink-0 px-2 text-right"
                  data-testid={`gantt-start-${a.id}`}
                  style={{ width: dateColWidth }}
                >
                  <span className="text-2xs tabular-nums text-content-tertiary">
                    {fmtShort(a.start, showYear)}
                  </span>
                </div>
                <div
                  className="shrink-0 px-2 text-right"
                  data-testid={`gantt-end-${a.id}`}
                  style={{ width: dateColWidth }}
                >
                  <span className="text-2xs tabular-nums text-content-tertiary">
                    {fmtShort(a.end, showYear)}
                  </span>
                </div>
                <div className="w-[36px] shrink-0 px-1 text-right">
                  <span
                    className={`text-2xs font-medium tabular-nums ${
                      a.progress >= 100
                        ? 'text-green-600'
                        : a.progress > 0
                          ? 'text-blue-600'
                          : 'text-content-tertiary'
                    }`}
                  >
                    {a.progress}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Right panel: SVG timeline ───────────────────────────── */}
      <div
        ref={svgScrollRef}
        className="relative flex-1 overflow-auto"
        onScroll={handleSvgScroll}
      >
        <svg
          ref={svgRef}
          width={timelineWidth}
          height={bodyHeight + HEADER_HEIGHT}
          className="select-none"
          // An image's children are presentational, so a chart with focusable
          // bars, handles and links has to be a group.
          role={keyboardNav ? 'group' : 'img'}
          aria-label={t('gantt.chart_label', 'Gantt chart with {{count}} activities', {
            count: activities.length,
          })}
          aria-describedby={keyboardNav ? keyboardHintId : undefined}
          onFocus={keyboardNav ? () => setChartFocused(true) : undefined}
          onBlur={
            keyboardNav
              ? (e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setChartFocused(false);
                }
              : undefined
          }
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

            {/*
             * One clip per top-row cell. The label is a plain <text>, which does
             * not wrap or truncate to anything, so a cell narrower than its own
             * label used to paint straight over its neighbour: a range starting
             * mid-month gives the leading cell a few days of width while its
             * label still reads "January 2026", and the result on screen was
             * JANFEBRUARY2026 at the zoom the chart opens on.
             *
             * Clipping rather than measuring is deliberate. Deciding what fits
             * needs the rendered width of the string, and the labels come from
             * Intl in 29 locales, so any character-count estimate is right for
             * English and wrong for the CJK and Arabic ones. getComputedTextLength
             * would be exact but forces layout per cell on every render, which is
             * the cost tasks #84 and #88 went and removed elsewhere. The clip is
             * exact in every locale and costs no measurement.
             */}
            {headers.topRow.map((cell, i) => (
              <clipPath key={`top-clip-${i}`} id={`${clipPrefix}-top-${i}`}>
                {/* Inset by the same 6px the text is, so a clipped label stops
                    short of the divider instead of touching it. */}
                <rect
                  x={cell.x}
                  y={0}
                  width={Math.max(0, cell.width - 6)}
                  height={HEADER_HEIGHT / 2}
                />
              </clipPath>
            ))}
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
                  clipPath={`url(#${clipPrefix}-top-${i})`}
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
            {activities.map((_a, idx) => (
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
            {activities.map((_a, idx) => (
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
                data-testid={`gantt-arrow-${arrow.key}`}
                d={arrow.d}
                fill="none"
                stroke="#94a3b8"
                strokeWidth={1.5}
                markerEnd="url(#gantt-svg-arrowhead)"
                opacity={0.7}
              />
            ))}

            {/* Dependency arrow hit areas: the drawn stroke is 1.5px, too thin
                to click, let alone tap, so each arrow gets a wide invisible
                twin that opens the link menu. Pointer only: the keyboard
                reaches links through the active bar (below). */}
            {onDeleteLink &&
              arrowPaths.map((arrow) => (
                <path
                  key={`hit-${arrow.key}`}
                  data-testid={`gantt-link-hit-${arrow.fromId}-${arrow.toId}`}
                  d={arrow.d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={12}
                  aria-hidden="true"
                  className="cursor-pointer"
                  style={{ pointerEvents: 'stroke' }}
                  onClick={(e) => {
                    const p = toBodyPoint(e.clientX, e.clientY);
                    setLinkMenu({ fromId: arrow.fromId, toId: arrow.toId, x: p.x, y: p.y, restoreFocus: false });
                  }}
                />
              ))}

            {/* Task bars, milestones, groups */}
            {bars.map((bar, idx) => renderBar(bar, idx))}

            {/* The keyboard's way to a link: while focus is in the chart, the
                active bar's incoming and outgoing links become buttons, after
                the bar in tab order. They never take the pointer, which the
                hit areas above handle. */}
            {onDeleteLink &&
              keyFocusId &&
              arrowPaths
                .filter((arrow) => arrow.fromId === keyFocusId || arrow.toId === keyFocusId)
                .map((arrow) => (
                  <path
                    key={`key-${arrow.key}`}
                    data-testid={`gantt-link-key-${arrow.fromId}-${arrow.toId}`}
                    d={arrow.d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth={3}
                    role="button"
                    tabIndex={0}
                    aria-haspopup="menu"
                    aria-label={t('gantt.link_label', {
                      defaultValue: 'Link from {{from}} to {{to}}',
                      from: activities[rowIndex.get(arrow.fromId) ?? -1]?.name ?? arrow.fromId,
                      to: activities[rowIndex.get(arrow.toId) ?? -1]?.name ?? arrow.toId,
                    })}
                    className="outline-none focus-visible:[stroke:#2563eb]"
                    style={{ pointerEvents: 'none' }}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' && e.key !== ' ') return;
                      e.preventDefault();
                      setLinkMenu({
                        fromId: arrow.fromId,
                        toId: arrow.toId,
                        x: arrow.endX,
                        y: arrow.endY,
                        restoreFocus: true,
                      });
                    }}
                  />
                ))}

            {/* Link being drawn: outline on the bar under the pointer and a
                dashed line from the handle to the pointer. Above the bars so a
                bar never hides it; pointer-events off so it never becomes the
                drop target itself. */}
            {linkTargetBar && (
              <rect
                data-testid="gantt-link-target"
                x={linkTargetBar.left - 3}
                y={linkTargetBar.y - 3}
                width={linkTargetBar.right - linkTargetBar.left + 6}
                height={BAR_HEIGHT + 6}
                rx={6}
                fill="none"
                stroke="#2563eb"
                strokeWidth={2}
                className="pointer-events-none"
              />
            )}
            {linkState?.pointer && (
              <line
                data-testid="gantt-link-preview"
                x1={linkState.originX}
                y1={linkState.originY}
                x2={linkState.pointer.x}
                y2={linkState.pointer.y}
                stroke="#2563eb"
                strokeWidth={1.5}
                strokeDasharray="5 4"
                className="pointer-events-none"
              />
            )}
          </g>
        </svg>

        {/* Arrow menu. HTML rather than SVG so it gets real buttons, focus
            and theming; absolutely placed in the scroll content so it moves
            with the arrow it belongs to. */}
        {linkMenu && onDeleteLink && (
          <>
            <div className="fixed inset-0 z-40" onClick={closeLinkMenu} />
            <div
              role="menu"
              aria-label={t('gantt.link_label', {
                defaultValue: 'Link from {{from}} to {{to}}',
                from: linkMenuNames?.from ?? '',
                to: linkMenuNames?.to ?? '',
              })}
              className="absolute z-50 min-w-[160px] rounded-lg border border-border-light bg-surface-elevated py-1 shadow-lg"
              style={{ left: linkMenu.x + 4, top: linkMenu.y + HEADER_HEIGHT + 4 }}
            >
              <div className="max-w-[260px] truncate px-3 py-1 text-2xs text-content-tertiary">
                {linkMenuNames?.from} &rarr; {linkMenuNames?.to}
              </div>
              {/* A link's type and lag are edited where its successor's
                  predecessors are listed, which is what opening the
                  activity shows. */}
              {onActivityClick && (
                <button
                  type="button"
                  role="menuitem"
                  autoFocus
                  className="flex w-full items-center px-3 py-1.5 text-left text-xs text-content-primary hover:bg-surface-secondary"
                  onClick={() => {
                    const { toId } = linkMenu;
                    closeLinkMenu();
                    onActivityClick(toId);
                  }}
                >
                  {t('gantt.link_edit', { defaultValue: 'Edit link' })}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                autoFocus={!onActivityClick}
                className="flex w-full items-center px-3 py-1.5 text-left text-xs text-semantic-error hover:bg-semantic-error-bg"
                onClick={() => {
                  const { fromId, toId } = linkMenu;
                  closeLinkMenu();
                  void onDeleteLink(fromId, toId);
                }}
              >
                {t('gantt.link_delete', { defaultValue: 'Delete link' })}
              </button>
            </div>
          </>
        )}

        {keyboardNav && (
          <p id={keyboardHintId} className="sr-only">
            {t('gantt.keyboard_hint', {
              defaultValue:
                'Use the up and down arrow keys to move between activities and Enter to open one. Press Tab to reach the selected activity\'s link handles and links.',
            })}
          </p>
        )}

        {/* Spoken while a keyboard link waits for its target, so a screen
            reader user knows the next Enter on a handle completes it. */}
        {onCreateLink && (
          <div className="sr-only" aria-live="polite">
            {linkState && !linkState.pointer
              ? t('gantt.link_armed', {
                  defaultValue:
                    'Linking from {{name}}. Move to another activity and press Enter on it, or on one of its handles, to link it. Press Escape to cancel.',
                  name: activities[rowIndex.get(linkState.fromId) ?? -1]?.name ?? '',
                })
              : ''}
          </div>
        )}
      </div>
    </div>
  );
}

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
  useId,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { fmtDate, getIntlLocale } from '@/shared/lib/formatters';
import {
  type GanttActivity,
  type ViewMode,
  ROW_HEIGHT,
  HEADER_HEIGHT,
  TABLE_WIDTH,
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

/* ── Component ──────────────────────────────────────────────────── */

export function GanttChart({
  activities,
  viewMode = 'week',
  startDate: startDateProp,
  endDate: endDateProp,
  onActivityClick,
  onActivityDrag,
  onActivityResize,
  className = '',
  showBaseline = false,
  showDependencies = true,
  showCriticalPath = true,
  todayLine = true,
}: GanttProps) {
  const { t } = useTranslation();
  const locale = getIntlLocale();

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
          aria-label={`${a.name}: ${fmtShort(a.start, showYear)} - ${fmtShort(a.end, showYear)}, ${a.progress}% ${t('gantt.complete', 'complete')}`}
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
      showYear,
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
        className="flex-1 overflow-auto"
        onScroll={handleSvgScroll}
      >
        <svg
          width={timelineWidth}
          height={bodyHeight + HEADER_HEIGHT}
          className="select-none"
          role="img"
          aria-label={t('gantt.chart_label', 'Gantt chart with {{count}} activities', {
            count: activities.length,
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

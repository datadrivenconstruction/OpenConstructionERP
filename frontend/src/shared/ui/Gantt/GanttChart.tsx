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
} from 'react';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';
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

/* ── Component ──────────────────────────────────────────────────── */

export function GanttChart({
  activities,
  viewMode = 'week',
  startDate: startDateProp,
  endDate: endDateProp,
  onActivityClick,
  onActivityDrag,
  className = '',
  showBaseline = false,
  showDependencies = true,
  showCriticalPath = true,
  todayLine = true,
}: GanttProps) {
  const { t } = useTranslation();
  const locale = getIntlLocale();

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
      const effectiveX = x + dragOffset;

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
            width={width}
            height={BAR_HEIGHT}
            rx={4}
            fill={bgColor}
            stroke={isCritical ? '#ef4444' : 'none'}
            strokeWidth={isCritical ? 2 : 0}
            className={`${onActivityDrag ? 'cursor-grab' : onActivityClick ? 'cursor-pointer' : ''} ${isDragging ? 'opacity-70' : ''}`}
            onMouseDown={(e) => handleBarMouseDown(e, a.id)}
            onClick={() => {
              if (!isDragging) onActivityClick?.(a.id);
            }}
          />

          {/* Progress fill */}
          {a.progress > 0 && (
            <rect
              x={effectiveX}
              y={barY}
              width={Math.min(progressWidth, width)}
              height={BAR_HEIGHT}
              rx={4}
              fill={fillColor}
              opacity={0.85}
              className="pointer-events-none"
            />
          )}

          {/* Right edge clip for progress (keep rounded corners) */}
          {a.progress > 0 && a.progress < 100 && progressWidth < width - 4 && (
            <rect
              x={effectiveX + progressWidth - 1}
              y={barY}
              width={2}
              height={BAR_HEIGHT}
              fill={fillColor}
              opacity={0.85}
              className="pointer-events-none"
            />
          )}

          {/* Bar label if wide enough */}
          {width > 50 && (
            <text
              x={effectiveX + 6}
              y={barY + BAR_HEIGHT / 2}
              dominantBaseline="central"
              className="pointer-events-none select-none fill-current text-[11px] font-medium"
              fill={a.progress > 40 ? '#ffffff' : '#1f2937'}
            >
              {a.name.length > Math.floor(width / 7)
                ? a.name.slice(0, Math.floor(width / 7)) + '...'
                : a.name}
            </text>
          )}
        </g>
      );
    },
    [
      showCriticalPath,
      showBaseline,
      dragState,
      viewMode,
      timelineStart,
      locale,
      t,
      onActivityClick,
      onActivityDrag,
      handleBarMouseDown,
    ],
  );

  /* ── Render ─────────────────────────────────────────────────── */

  return (
    <div
      className={`flex overflow-hidden rounded-xl border border-border-light bg-surface-primary ${className}`}
      style={{ height: Math.min(bodyHeight + HEADER_HEIGHT + 2, 800) }}
    >
      {/* ── Left panel: activity table ──────────────────────────── */}
      <div className="flex flex-col" style={{ width: TABLE_WIDTH, minWidth: TABLE_WIDTH }}>
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
          <div className="flex w-[70px] items-end justify-end px-2 pb-1.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('gantt.start', 'Start')}
            </span>
          </div>
          <div className="flex w-[70px] items-end justify-end px-2 pb-1.5">
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
            const startD = new Date(a.start);
            const endD = new Date(a.end);
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
                <div className="w-[70px] shrink-0 px-2 text-right">
                  <span className="text-2xs tabular-nums text-content-tertiary">
                    {fmtShort(startD, locale)}
                  </span>
                </div>
                <div className="w-[70px] shrink-0 px-2 text-right">
                  <span className="text-2xs tabular-nums text-content-tertiary">
                    {fmtShort(endD, locale)}
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

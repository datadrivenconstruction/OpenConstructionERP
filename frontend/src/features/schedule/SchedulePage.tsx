import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Calendar,
  CalendarDays,
  ChevronRight,
  ArrowLeft,
  Plus,
  X,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Minus,
  Diamond,
  BarChart3,
  Zap,
  FileBarChart,
  ShieldAlert,
  RotateCcw,
  Download,
  ClipboardList,
  Users,
  Box,
  GitBranch,
  TrendingUp,
  Layers,
} from 'lucide-react';
import { Button, Card, Badge, Input, InfoHint, SkeletonTable, Breadcrumb, GanttChart as SVGGanttChart, ViewInBIMButton, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import type { GanttActivity as SVGGanttActivity, GanttViewMode } from '@/shared/ui';
import { apiGet, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { scheduleApi } from './api';
import { fetchBIMModels } from '@/features/bim/api';
import type {
  Schedule,
  Activity,
  GanttData,
  CriticalPathResponse,
  RiskAnalysisResponse,
} from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
}

interface BOQListItem {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

interface CreateScheduleForm {
  name: string;
  description: string;
  start_date: string;
  end_date: string;
}

interface CreateActivityForm {
  name: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  activity_type: 'task' | 'milestone' | 'summary';
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(getIntlLocale(), {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function daysBetween(start: string, end: string): number {
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (isNaN(s) || isNaN(e)) return 1;
  return Math.max(1, Math.ceil((e - s) / (1000 * 60 * 60 * 24)));
}

function statusColor(status: string): {
  bg: string;
  fill: string;
  text: string;
  variant: 'neutral' | 'blue' | 'success' | 'warning' | 'error';
} {
  switch (status) {
    case 'completed':
      return {
        bg: 'bg-semantic-success/20',
        fill: 'bg-semantic-success',
        text: 'text-semantic-success',
        variant: 'success',
      };
    case 'in_progress':
      return {
        bg: 'bg-oe-blue/15',
        fill: 'bg-oe-blue',
        text: 'text-oe-blue',
        variant: 'blue',
      };
    case 'delayed':
      return {
        bg: 'bg-semantic-error/15',
        fill: 'bg-semantic-error',
        text: 'text-semantic-error',
        variant: 'error',
      };
    default:
      return {
        bg: 'bg-content-tertiary/15',
        fill: 'bg-content-tertiary',
        text: 'text-content-tertiary',
        variant: 'neutral',
      };
  }
}

/* ── Work Calendar Info ────────────────────────────────────────────────── */

const WORK_CALENDAR_INFO: Record<string, { hours: number; days: number }> = {
  DACH: { hours: 8, days: 5 },
  UK: { hours: 8, days: 5 },
  US: { hours: 8, days: 5 },
  GULF: { hours: 10, days: 6 },
  RU: { hours: 8, days: 5 },
  NORDIC: { hours: 7.5, days: 5 },
  FRANCE: { hours: 7, days: 5 },
  BRAZIL: { hours: 8, days: 6 },
  CHINA: { hours: 8, days: 6 },
  INDIA: { hours: 8, days: 6 },
  CANADA: { hours: 8, days: 5 },
  SPAIN: { hours: 8, days: 5 },
};

/* ── Modal Overlay ─────────────────────────────────────────────────────── */

function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby="schedule-modal-title" className="relative z-10 w-full max-w-md rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl animate-fade-in">
        <div className="mb-5 flex items-center justify-between">
          <h2 id="schedule-modal-title" className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', 'Close')}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ── Summary Stats ─────────────────────────────────────────────────────── */

function SummaryStats({
  summary,
}: {
  summary: GanttData['summary'];
}) {
  const { t } = useTranslation();

  const stats = [
    {
      label: t('schedule.total_activities', 'Total'),
      value: summary.total_activities,
      icon: BarChart3,
      color: 'text-content-primary',
      bg: 'bg-surface-secondary',
    },
    {
      label: t('schedule.completed', 'Completed'),
      value: summary.completed,
      icon: CheckCircle2,
      color: 'text-semantic-success',
      bg: 'bg-semantic-success-bg',
    },
    {
      label: t('schedule.in_progress', 'In Progress'),
      value: summary.in_progress,
      icon: Clock,
      color: 'text-oe-blue',
      bg: 'bg-oe-blue-subtle',
    },
    {
      label: t('schedule.delayed', 'Delayed'),
      value: summary.delayed,
      icon: AlertTriangle,
      color: 'text-semantic-error',
      bg: 'bg-semantic-error-bg',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <Card key={stat.label} padding="sm" className="flex items-center gap-3">
            <div
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${stat.bg}`}
            >
              <Icon size={16} className={stat.color} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-bold tabular-nums text-content-primary">{stat.value}</p>
              <p className="text-2xs text-content-tertiary truncate">{stat.label}</p>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/* ── Dependency Arrow Types ────────────────────────────────────────────── */

interface DependencyLink {
  fromId: string;
  toId: string;
  type: string; // "FS", "SS", "FF", "SF"
}

interface ArrowPath {
  key: string;
  d: string;
  markerEnd: string;
}

/**
 * Compute SVG path data for dependency arrows between activity bars.
 * All coordinates are in pixels relative to the gantt body container.
 *
 * @param links - dependency links to draw
 * @param activityIndex - map of activity ID to its row index
 * @param barPositions - map of activity ID to { leftPct, widthPct }
 * @param rowHeight - measured height of each row in pixels
 * @param containerWidth - pixel width of the gantt right panel area
 */
function computeArrowPaths(
  links: DependencyLink[],
  activityIndex: Map<string, number>,
  barPositions: Map<string, { leftPct: number; widthPct: number }>,
  rowHeight: number,
  containerWidth: number,
): ArrowPath[] {
  const paths: ArrowPath[] = [];
  const ARROW_OFFSET = 6; // horizontal offset from bar edge
  const VERTICAL_GAP = 4; // vertical gap from row center

  for (const link of links) {
    const fromIdx = activityIndex.get(link.fromId);
    const toIdx = activityIndex.get(link.toId);
    const fromBar = barPositions.get(link.fromId);
    const toBar = barPositions.get(link.toId);

    if (fromIdx == null || toIdx == null || !fromBar || !toBar) continue;

    const fromCenterY = fromIdx * rowHeight + rowHeight / 2;
    const toCenterY = toIdx * rowHeight + rowHeight / 2;

    let startX: number;
    let endX: number;

    const depType = (link.type || 'FS').toUpperCase();

    if (depType === 'SS') {
      // Start-to-Start: arrow from start of predecessor to start of successor
      startX = (fromBar.leftPct / 100) * containerWidth;
      endX = (toBar.leftPct / 100) * containerWidth;
    } else if (depType === 'FF') {
      // Finish-to-Finish
      startX = ((fromBar.leftPct + fromBar.widthPct) / 100) * containerWidth;
      endX = ((toBar.leftPct + toBar.widthPct) / 100) * containerWidth;
    } else if (depType === 'SF') {
      // Start-to-Finish
      startX = (fromBar.leftPct / 100) * containerWidth;
      endX = ((toBar.leftPct + toBar.widthPct) / 100) * containerWidth;
    } else {
      // FS (Finish-to-Start) — default
      startX = ((fromBar.leftPct + fromBar.widthPct) / 100) * containerWidth;
      endX = (toBar.leftPct / 100) * containerWidth;
    }

    // Build an L-shaped (or S-shaped) connector path
    // The path goes: horizontal from source bar edge, then vertical, then horizontal to target
    const goingDown = toCenterY > fromCenterY;
    const startY = fromCenterY + (goingDown ? VERTICAL_GAP : -VERTICAL_GAP);
    const endY = toCenterY + (goingDown ? -VERTICAL_GAP : VERTICAL_GAP);

    // Determine the corner X for the L-shaped route
    let cornerX: number;

    if (depType === 'FS' || depType === 'SF') {
      // Route through a point offset from the source bar end
      if (startX < endX) {
        // Simple L-shape: go right from source, then turn down/up to target
        cornerX = startX + ARROW_OFFSET;
      } else {
        // Source bar ends after target starts — route around
        cornerX = Math.min(startX, endX) - ARROW_OFFSET;
      }
    } else {
      // SS or FF — route through a point offset from the aligned edges
      cornerX = Math.min(startX, endX) - ARROW_OFFSET;
    }

    // Build path: start → horizontal to corner → vertical to target row → horizontal to target
    const d =
      `M ${startX} ${startY} ` +
      `L ${cornerX} ${startY} ` +
      `L ${cornerX} ${endY} ` +
      `L ${endX} ${endY}`;

    paths.push({
      key: `${link.fromId}-${link.toId}-${depType}`,
      d,
      markerEnd: 'url(#gantt-arrowhead)',
    });
  }

  return paths;
}

/* ── Gantt Chart ───────────────────────────────────────────────────────── */

type ZoomLevel = 'day' | 'week' | 'month' | 'quarter' | 'year';

const PIXELS_PER_DAY: Record<ZoomLevel, number> = {
  day: 40,
  week: 8,
  month: 2,
  quarter: 0.9,
  year: 0.4,
};

const ROW_HEIGHT = 44;

function GanttChart({
  activities,
  onUpdateProgress,
  criticalActivityIds,
  zoomLevel = 'week',
}: {
  activities: Activity[];
  onUpdateProgress: (activityId: string, progress: number) => void;
  criticalActivityIds?: Set<string>;
  zoomLevel?: ZoomLevel;
}) {
  const { t } = useTranslation();
  const ganttBodyRef = useRef<HTMLDivElement>(null);
  const ganttScrollRef = useRef<HTMLDivElement>(null);
  // Debounced progress updates
  const [pendingProgress, setPendingProgress] = useState<Record<string, number>>({});

  useEffect(() => {
    const entries = Object.entries(pendingProgress);
    if (entries.length === 0) return;
    const timer = setTimeout(() => {
      for (const [id, pct] of entries) {
        onUpdateProgress(id, pct);
      }
      setPendingProgress({});
    }, 500);
    return () => clearTimeout(timer);
  }, [pendingProgress, onUpdateProgress]);

  // Compute timeline bounds
  const { timelineStart, timelineEnd, totalDays } = useMemo(() => {
    if (activities.length === 0) {
      const now = new Date();
      const start = new Date(now);
      start.setDate(start.getDate() - 7);
      const end = new Date(now);
      end.setDate(end.getDate() + 30);
      return {
        timelineStart: start,
        timelineEnd: end,
        totalDays: 37,
      };
    }

    const starts = activities.map((a) => new Date(a.start_date).getTime()).filter((t) => !isNaN(t));
    const ends = activities.map((a) => new Date(a.end_date).getTime()).filter((t) => !isNaN(t));
    if (starts.length === 0 || ends.length === 0) {
      const now = new Date();
      const fallbackStart = new Date(now);
      fallbackStart.setDate(fallbackStart.getDate() - 7);
      const fallbackEnd = new Date(now);
      fallbackEnd.setDate(fallbackEnd.getDate() + 30);
      return { timelineStart: fallbackStart, timelineEnd: fallbackEnd, totalDays: 37 };
    }
    const minStart = new Date(Math.min(...starts));
    const maxEnd = new Date(Math.max(...ends));

    // Add padding of 2 days on each side
    minStart.setDate(minStart.getDate() - 2);
    maxEnd.setDate(maxEnd.getDate() + 2);

    const days = daysBetween(minStart.toISOString(), maxEnd.toISOString());

    return {
      timelineStart: minStart,
      timelineEnd: maxEnd,
      totalDays: days,
    };
  }, [activities]);

  // Compute total pixel width based on zoom level
  const timelineWidthPx = totalDays * PIXELS_PER_DAY[zoomLevel];

  // Generate timeline markers based on zoom level
  const timelineMarkers = useMemo(() => {
    const markers: Array<{ label: string; offsetPct: number }> = [];
    const current = new Date(timelineStart);

    if (zoomLevel === 'day') {
      // One marker per day
      current.setDate(current.getDate() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.toLocaleDateString(getIntlLocale(), { day: '2-digit', month: 'short' }),
            offsetPct: pct,
          });
        }
        current.setDate(current.getDate() + 1);
      }
    } else if (zoomLevel === 'week') {
      // One marker per week (advance to next Monday)
      const dayOfWeek = current.getDay();
      const daysUntilMonday = dayOfWeek === 0 ? 1 : 8 - dayOfWeek;
      current.setDate(current.getDate() + daysUntilMonday);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.toLocaleDateString(getIntlLocale(), {
              day: '2-digit',
              month: 'short',
            }),
            offsetPct: pct,
          });
        }
        current.setDate(current.getDate() + 7);
      }
    } else if (zoomLevel === 'month') {
      // Month view — one marker per month
      current.setDate(1);
      current.setMonth(current.getMonth() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.toLocaleDateString(getIntlLocale(), { month: 'short', year: '2-digit' }),
            offsetPct: pct,
          });
        }
        current.setMonth(current.getMonth() + 1);
      }
    } else if (zoomLevel === 'quarter') {
      // Quarter view — one marker per quarter
      current.setDate(1);
      current.setMonth(Math.floor(current.getMonth() / 3) * 3 + 3);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          const q = Math.floor(current.getMonth() / 3) + 1;
          markers.push({
            label: `Q${q} ${current.getFullYear()}`,
            offsetPct: pct,
          });
        }
        current.setMonth(current.getMonth() + 3);
      }
    } else {
      // Year view — one marker per year
      current.setDate(1);
      current.setMonth(0);
      current.setFullYear(current.getFullYear() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.getFullYear().toString(),
            offsetPct: pct,
          });
        }
        current.setFullYear(current.getFullYear() + 1);
      }
    }

    // Filter out markers that are too close to prevent label overlap.
    // Minimum gap: 6% of timeline width (≈ label width in characters).
    const MIN_GAP_PCT = 6;
    const filtered: typeof markers = [];
    for (const m of markers) {
      const lastPct = filtered[filtered.length - 1]?.offsetPct ?? -Infinity;
      if (filtered.length === 0 || m.offsetPct - lastPct >= MIN_GAP_PCT) {
        filtered.push(m);
      }
    }
    return filtered;
  }, [timelineStart, timelineEnd, totalDays, zoomLevel]);

  // Compute bar positions
  const getBarStyle = useCallback(
    (activity: Activity) => {
      const startOffset = daysBetween(
        timelineStart.toISOString(),
        activity.start_date,
      );
      const duration = daysBetween(activity.start_date, activity.end_date);
      const leftPct = (startOffset / totalDays) * 100;
      const widthPct = (duration / totalDays) * 100;

      return {
        left: `${Math.max(0, leftPct)}%`,
        width: `${Math.max(0.5, widthPct)}%`,
      };
    },
    [timelineStart, totalDays],
  );

  // Build activity index map and bar position map for dependency arrows
  const activityIndex = useMemo(() => {
    const map = new Map<string, number>();
    activities.forEach((a, i) => map.set(a.id, i));
    return map;
  }, [activities]);

  const barPositions = useMemo(() => {
    const map = new Map<string, { leftPct: number; widthPct: number }>();
    for (const activity of activities) {
      const startOffset = daysBetween(timelineStart.toISOString(), activity.start_date);
      const duration = daysBetween(activity.start_date, activity.end_date);
      const leftPct = Math.max(0, (startOffset / totalDays) * 100);
      const widthPct = Math.max(0.5, (duration / totalDays) * 100);
      map.set(activity.id, { leftPct, widthPct });
    }
    return map;
  }, [activities, timelineStart, totalDays]);

  // Collect all dependency links from activities
  const dependencyLinks = useMemo<DependencyLink[]>(() => {
    const links: DependencyLink[] = [];
    for (const activity of activities) {
      if (activity.dependencies && activity.dependencies.length > 0) {
        for (const dep of activity.dependencies) {
          links.push({
            fromId: dep.activity_id,
            toId: activity.id,
            type: dep.type || 'FS',
          });
        }
      }
    }
    return links;
  }, [activities]);

  // Compute SVG arrow paths
  const arrowPaths = useMemo(() => {
    if (dependencyLinks.length === 0 || timelineWidthPx === 0) return [];
    return computeArrowPaths(
      dependencyLinks,
      activityIndex,
      barPositions,
      ROW_HEIGHT,
      timelineWidthPx,
    );
  }, [dependencyLinks, activityIndex, barPositions, timelineWidthPx]);

  if (activities.length === 0) {
    return (
      <Card padding="none" className="overflow-hidden">
        <div className="flex flex-col items-center justify-center py-14 px-6 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-secondary text-content-tertiary">
            <BarChart3 size={28} strokeWidth={1.5} />
          </div>
          <h3 className="text-lg font-semibold text-content-primary">
            {t('schedule.gantt_empty_title', { defaultValue: 'Gantt chart is empty' })}
          </h3>
          <p className="mt-1.5 max-w-md text-sm text-content-secondary">
            {t('schedule.gantt_empty_hint', {
              defaultValue: 'Add activities manually or generate them from a BOQ to see the timeline. Dependencies and critical path will render automatically.',
            })}
          </p>
          {/* Decorative timeline preview */}
          <div className="mt-6 w-full max-w-lg">
            <div className="flex items-center gap-2 mb-2 px-2">
              <span className="text-2xs font-medium text-content-quaternary">{t('schedule.gantt_preview_label', { defaultValue: 'Timeline preview' })}</span>
              <div className="flex-1 h-px bg-border-light" />
            </div>
            <div className="space-y-2 opacity-40">
              <div className="flex items-center gap-3">
                <span className="w-24 text-right text-2xs text-content-tertiary truncate">{t('schedule.preview_foundation', { defaultValue: 'Foundation' })}</span>
                <div className="flex-1 h-6 rounded-md bg-oe-blue/15 relative">
                  <div className="h-full w-3/5 rounded-md bg-oe-blue/30" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="w-24 text-right text-2xs text-content-tertiary truncate">{t('schedule.preview_structural', { defaultValue: 'Structural' })}</span>
                <div className="flex-1 h-6 rounded-md bg-semantic-success/15 relative ml-[15%]">
                  <div className="h-full w-2/5 rounded-md bg-semantic-success/30" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="w-24 text-right text-2xs text-content-tertiary truncate">{t('schedule.preview_mep', { defaultValue: 'MEP Install' })}</span>
                <div className="flex-1 h-6 rounded-md bg-semantic-warning/15 relative ml-[30%]">
                  <div className="h-full w-1/4 rounded-md bg-semantic-warning/30" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>
    );
  }

  // Calculate today marker position
  const todayOffset = daysBetween(timelineStart.toISOString(), new Date().toISOString());
  const todayPct = (todayOffset / totalDays) * 100;

  // Sort activities for stable rendering
  const sortedActivities = activities;

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex">
        {/* LEFT: fixed activity list */}
        <div className="w-[280px] shrink-0 border-r border-border-light">
          {/* Header labels */}
          <div className="flex h-10 items-center border-b border-border-light bg-surface-secondary/50 px-3">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('schedule.activity', 'Activity')}
            </span>
          </div>
          {/* Activity rows — left panel */}
          {sortedActivities.map((activity) => {
            const cpActive = criticalActivityIds != null && criticalActivityIds.size > 0;
            const isCritical = criticalActivityIds?.has(activity.id) ?? false;
            const sc = isCritical
              ? { bg: 'bg-semantic-error/20', fill: 'bg-semantic-error', text: 'text-semantic-error', variant: 'error' as const }
              : cpActive
                ? { bg: 'bg-oe-blue-subtle', fill: 'bg-oe-blue/30', text: 'text-oe-blue', variant: 'neutral' as const }
                : statusColor(activity.status);
            const isMilestone = activity.activity_type === 'milestone';
            const isSummary = activity.activity_type === 'summary';
            const displayProgress = pendingProgress[activity.id] ?? activity.progress_pct;

            return (
              <div
                key={activity.id}
                className="flex items-start gap-2 border-b border-border-light px-3 transition-colors hover:bg-surface-secondary/30"
                style={{ height: ROW_HEIGHT }}
              >
                <div className="flex min-w-0 flex-1 flex-col justify-center py-1.5" style={{ height: ROW_HEIGHT }}>
                  <div className="flex items-center gap-1.5">
                    {isCritical && (
                      <span className="shrink-0 rounded bg-semantic-error px-1 py-0.5 text-[9px] font-bold leading-none text-white">
                        CP
                      </span>
                    )}
                    {isMilestone && (
                      <Diamond size={10} className={`shrink-0 ${sc.text}`} fill="currentColor" />
                    )}
                    {isSummary && <Minus size={10} className="shrink-0 text-content-tertiary" />}
                    <span className="text-xs font-medium text-content-primary truncate">
                      {activity.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-2xs tabular-nums text-content-tertiary">
                      {formatDate(activity.start_date)} &mdash; {formatDate(activity.end_date)}
                    </span>
                    <Badge variant={sc.variant} size="sm">
                      {displayProgress}%
                    </Badge>
                    <ViewInBIMButton
                      elementIds={activity.bim_element_ids ?? []}
                      iconSize={9}
                      className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold bg-amber-50 dark:bg-amber-950/40 text-amber-700 border border-amber-200 dark:border-amber-900/60 hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
                    />
                  </div>
                </div>
                {/* Progress slider */}
                <div className="flex shrink-0 items-center" style={{ height: ROW_HEIGHT }}>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={displayProgress}
                    aria-label={t('schedule.progress_slider', { defaultValue: 'Progress for {{name}}', name: activity.name })}
                    onChange={(e) => {
                      const val = Number(e.target.value);
                      setPendingProgress((prev) => ({ ...prev, [activity.id]: val }));
                    }}
                    className="h-1 w-12 cursor-pointer appearance-none rounded-full bg-surface-secondary accent-oe-blue [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-oe-blue [&::-webkit-slider-thumb]:shadow-sm"
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* RIGHT: single scroll container for header + bars + arrows */}
        <div ref={ganttScrollRef} className="min-w-0 flex-1 overflow-x-auto">
          <div style={{ minWidth: timelineWidthPx }} className="relative">
            {/* Timeline header markers */}
            <div className="relative h-10 border-b border-border-light bg-surface-secondary/50">
              {timelineMarkers.map((marker) => (
                <span
                  key={marker.label + marker.offsetPct}
                  className="absolute top-2.5 text-2xs font-medium text-content-tertiary"
                  style={{ left: `${marker.offsetPct}%` }}
                >
                  {marker.label}
                </span>
              ))}
            </div>

            {/* Activity rows — gantt bars */}
            <div ref={ganttBodyRef}>
              {sortedActivities.map((activity) => {
                const cpActive = criticalActivityIds != null && criticalActivityIds.size > 0;
                const isCritical = criticalActivityIds?.has(activity.id) ?? false;
                const sc = isCritical
                  ? { bg: 'bg-semantic-error/20', fill: 'bg-semantic-error', text: 'text-semantic-error', variant: 'error' as const }
                  : cpActive
                    ? { bg: 'bg-oe-blue-subtle', fill: 'bg-oe-blue/30', text: 'text-oe-blue', variant: 'neutral' as const }
                    : statusColor(activity.status);
                const barStyle = getBarStyle(activity);
                const isMilestone = activity.activity_type === 'milestone';
                const displayProgress = pendingProgress[activity.id] ?? activity.progress_pct;

                return (
                  <div
                    key={activity.id}
                    data-gantt-row
                    className="relative border-b border-border-light"
                    style={{ height: ROW_HEIGHT }}
                  >
                    {/* Vertical grid lines */}
                    {timelineMarkers.map((marker) => (
                      <div
                        key={`grid-${marker.label}-${marker.offsetPct}`}
                        className="absolute top-0 bottom-0 w-px bg-border-light/50"
                        style={{ left: `${marker.offsetPct}%` }}
                      />
                    ))}

                    {isMilestone ? (
                      /* Diamond marker for milestones */
                      <div
                        className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
                        style={{ left: barStyle.left }}
                      >
                        <Diamond
                          size={16}
                          className={sc.text}
                          fill="currentColor"
                          strokeWidth={1.5}
                        />
                        {isCritical && (
                          <span className="absolute -top-3 left-1/2 -translate-x-1/2 flex h-4 items-center rounded bg-semantic-error px-1 text-[9px] font-bold leading-none text-white shadow-sm">
                            CP
                          </span>
                        )}
                      </div>
                    ) : (
                      /* Standard bar */
                      <div
                        className={`absolute top-1/2 -translate-y-1/2 h-7 rounded-md ${sc.bg} transition-all duration-200${isCritical ? ' ring-2 ring-semantic-error/60' : ''}`}
                        style={barStyle}
                      >
                        {/* Progress fill */}
                        <div
                          className={`h-full rounded-md ${sc.fill} transition-all duration-300`}
                          style={{ width: `${displayProgress}%` }}
                        />
                        {/* CP badge for critical path activities */}
                        {isCritical && (
                          <span className="absolute -top-2.5 -right-1 flex h-4 items-center rounded bg-semantic-error px-1 text-[9px] font-bold leading-none text-white shadow-sm">
                            CP
                          </span>
                        )}
                        {/* Label overlay */}
                        {parseFloat(barStyle.width) > 4 && (
                          <span className="absolute inset-0 flex items-center px-2 text-2xs font-medium text-content-primary truncate">
                            {activity.name}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Dependency arrow SVG overlay — same scroll context */}
            {arrowPaths.length > 0 && (
              <svg
                className="pointer-events-none absolute top-10 left-0"
                style={{ width: '100%', height: sortedActivities.length * ROW_HEIGHT }}
                overflow="visible"
              >
                <defs>
                  <marker
                    id="gantt-arrowhead"
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
                {arrowPaths.map((arrow) => (
                  <path
                    key={arrow.key}
                    d={arrow.d}
                    fill="none"
                    stroke="#94a3b8"
                    strokeWidth={1.5}
                    markerEnd={arrow.markerEnd}
                  />
                ))}
              </svg>
            )}

            {/* Today marker */}
            {todayPct >= 0 && todayPct <= 100 && (
              <div
                className="absolute top-0 bottom-0 w-px bg-red-500 z-10 pointer-events-none"
                style={{ left: `${todayPct}%` }}
              >
                <div className="absolute -top-0 left-1/2 -translate-x-1/2 rounded bg-red-500 px-1.5 py-0.5 text-[9px] font-bold text-white whitespace-nowrap">
                  {t('schedule.today', { defaultValue: 'Today' })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ── Risk Analysis Card ────────────────────────────────────────────────── */

function RiskAnalysisCard({ data }: { data: RiskAnalysisResponse }) {
  const { t } = useTranslation();

  const items = [
    {
      label: t('schedule.deterministic', 'Deterministic'),
      value: `${data.deterministic_days}d`,
      sub: t('schedule.planned_duration', 'Planned duration'),
      color: 'text-content-primary',
    },
    {
      label: 'P50',
      value: `${data.p50_days}d`,
      sub: t('schedule.fifty_pct_confidence', '50% confidence'),
      color: 'text-oe-blue',
    },
    {
      label: 'P80',
      value: `${data.p80_days}d`,
      sub: t('schedule.eighty_pct_confidence', '80% confidence'),
      color: 'text-semantic-warning',
    },
    {
      label: 'P95',
      value: `${data.p95_days}d`,
      sub: t('schedule.ninetyfive_pct_confidence', '95% confidence'),
      color: 'text-semantic-error',
    },
  ];

  return (
    <Card padding="md" className="mt-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldAlert size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('schedule.risk_analysis', 'Risk Analysis (PERT)')}
        </h3>
        <Badge variant="neutral" size="sm">
          {t('schedule.buffer', 'Buffer')}: +{data.risk_buffer_days}d
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {items.map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-border-light bg-surface-secondary/50 px-3 py-2.5"
          >
            <p className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {item.label}
            </p>
            <p className={`text-xl font-bold tabular-nums ${item.color}`}>{item.value}</p>
            <p className="text-2xs text-content-tertiary">{item.sub}</p>
          </div>
        ))}
      </div>
      {data.std_dev_days > 0 && (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('schedule.std_dev_label', 'Std. deviation')}: {data.std_dev_days}d &middot;{' '}
          {t('schedule.mean_label', 'Mean (critical path)')}: {data.mean_days}d
        </p>
      )}
    </Card>
  );
}

/* ── Schedule Detail View ──────────────────────────────────────────────── */

function ScheduleDetail({
  schedule,
  projectId,
  onBack,
}: {
  schedule: Schedule;
  projectId: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>('week');
  const [viewMode, setViewMode] = useState<'table' | 'gantt'>('gantt');
  const [showAddActivity, setShowAddActivity] = useState(false);
  const [showGenerateBOQ, setShowGenerateBOQ] = useState(false);
  const [selectedBOQId, setSelectedBOQId] = useState('');
  const [generateStartDate, setGenerateStartDate] = useState(
    () => schedule.start_date?.slice(0, 10) || new Date().toISOString().slice(0, 10),
  );
  const [activityFilter, setActivityFilter] = useState('all');
  const [activityForm, setActivityForm] = useState<CreateActivityForm>({
    name: '',
    wbs_code: '',
    start_date: '',
    end_date: '',
    activity_type: 'task',
  });

  // Fetch project data for region / work calendar
  const { data: projectData } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => apiGet<{ id: string; region: string }>(`/v1/projects/${projectId}`),
    staleTime: 300_000,
  });
  const calInfo = WORK_CALENDAR_INFO[projectData?.region ?? ''] ?? WORK_CALENDAR_INFO['DACH'] ?? { hours: 8, days: 5 };

  const { data: ganttData, isLoading } = useQuery({
    queryKey: ['gantt', schedule.id],
    queryFn: () => scheduleApi.getGantt(schedule.id),
  });

  // Fetch BOQs for the project (for Generate from BOQ dialog)
  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => apiGet<BOQListItem[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: showGenerateBOQ,
  });

  // BIM models check (for showing 4D link hint)
  const { data: bimModelsData } = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
    staleTime: 300_000,
  });
  const hasBIMModels = (bimModelsData?.items?.length ?? 0) > 0;

  // CPM state
  const [cpmResult, setCpmResult] = useState<CriticalPathResponse | null>(null);
  const [riskResult, setRiskResult] = useState<RiskAnalysisResponse | null>(null);

  const criticalActivityIds = useMemo(() => {
    if (!cpmResult) return undefined;
    return new Set(cpmResult.critical_path.map((a) => a.activity_id));
  }, [cpmResult]);

  const addActivity = useMutation({
    mutationFn: (data: CreateActivityForm) =>
      scheduleApi.createActivity(schedule.id, {
        name: data.name,
        wbs_code: data.wbs_code,
        start_date: data.start_date,
        end_date: data.end_date,
        activity_type: data.activity_type,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      setShowAddActivity(false);
      setActivityForm({
        name: '',
        wbs_code: '',
        start_date: '',
        end_date: '',
        activity_type: 'task',
      });
      addToast({ type: 'success', title: t('toasts.activity_created', { defaultValue: 'Activity created' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const generateFromBOQ = useMutation({
    mutationFn: async (boqId: string) => {
      // Update the schedule start_date before generating so activities use the chosen date
      if (generateStartDate) {
        await scheduleApi.updateSchedule(schedule.id, { start_date: generateStartDate });
      }
      return scheduleApi.generateFromBOQ(schedule.id, boqId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      setShowGenerateBOQ(false);
      setSelectedBOQId('');
      // Reset CPM/risk results since activities changed
      setCpmResult(null);
      setRiskResult(null);
      addToast({ type: 'success', title: t('toasts.schedule_generated', { defaultValue: 'Schedule generated from BOQ' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const calculateCPM = useMutation({
    mutationFn: () => scheduleApi.calculateCPM(schedule.id),
    onSuccess: (data) => {
      setCpmResult(data);
      // Refresh gantt to show updated colors
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      addToast({ type: 'success', title: t('toasts.cpm_calculated', { defaultValue: 'Critical path calculated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const fetchRiskAnalysis = useMutation({
    mutationFn: () => scheduleApi.getRiskAnalysis(schedule.id),
    onSuccess: (data) => {
      setRiskResult(data);
      // Risk analysis also recalculates CPM internally
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      addToast({ type: 'success', title: t('toasts.risk_analysis_complete', { defaultValue: 'Risk analysis complete' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const updateProgress = useMutation({
    mutationFn: ({ activityId, progress }: { activityId: string; progress: number }) =>
      scheduleApi.updateProgress(activityId, progress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.update_failed', { defaultValue: 'Update failed' }), message: error.message });
    },
  });

  const resetSchedule = useMutation({
    mutationFn: async () => {
      const activities = ganttData?.activities ?? [];
      for (const a of activities) {
        await apiDelete(`/v1/schedule/activities/${a.id}`);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      setCpmResult(null);
      setRiskResult(null);
      setActivityFilter('all');
      addToast({ type: 'success', title: t('schedule.reset_success', { defaultValue: 'Schedule reset' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleUpdateProgress = useCallback(
    (activityId: string, progress: number) => {
      updateProgress.mutate({ activityId, progress });
    },
    [updateProgress],
  );

  const hasActivities = (ganttData?.summary.total_activities ?? 0) > 0;

  // Filtered activities for the Gantt chart (Improvement #5)
  const filteredActivities = useMemo(() => {
    const activities = ganttData?.activities ?? [];
    if (activityFilter === 'all') return activities;
    if (activityFilter === 'critical') {
      return activities.filter((a) => criticalActivityIds?.has(a.id));
    }
    if (activityFilter === 'delayed') {
      return activities.filter((a) => a.status === 'delayed');
    }
    if (activityFilter === 'in_progress') {
      return activities.filter((a) => a.status === 'in_progress');
    }
    return activities;
  }, [ganttData, activityFilter, criticalActivityIds]);

  // Map activities to SVG Gantt format
  const svgGanttActivities = useMemo<SVGGanttActivity[]>(() => {
    return filteredActivities.map((a) => ({
      id: a.id,
      name: a.name,
      start: a.start_date,
      end: a.end_date,
      progress: a.progress_pct,
      isCritical: criticalActivityIds?.has(a.id) ?? false,
      isMilestone: a.activity_type === 'milestone',
      isGroup: a.activity_type === 'summary',
      parentId: a.parent_id,
      dependencies: a.dependencies?.map((d) => d.activity_id) ?? [],
      color: a.color || undefined,
    }));
  }, [filteredActivities, criticalActivityIds]);

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary transition-colors hover:text-content-primary"
      >
        <ArrowLeft size={14} />
        {t('schedule.back_to_schedules', 'Back to schedules')}
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{schedule.name}</h1>
          {schedule.description && (
            <p className="mt-1 text-sm text-content-secondary">{schedule.description}</p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Badge variant="blue" size="sm">
              {t(`schedule.status_${schedule.status}`, { defaultValue: schedule.status })}
            </Badge>
            {schedule.start_date && (
              <Badge variant="neutral" size="sm">
                {formatDate(schedule.start_date)} &ndash;{' '}
                {schedule.end_date ? formatDate(schedule.end_date) : '...'}
              </Badge>
            )}
            {cpmResult && (
              <Badge variant="error" size="sm">
                {t('schedule.critical_path_count', 'Critical: {{count}}', {
                  count: cpmResult.critical_path.length,
                })}
              </Badge>
            )}
            {/* Work calendar indicator */}
            <Badge variant="neutral" size="sm" className="flex items-center gap-1">
              <Clock size={11} />
              {t('schedule.work_calendar', {
                defaultValue: '{{hours}}h/day, {{days}} days/week',
                hours: String(calInfo.hours),
                days: String(calInfo.days),
              })}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            icon={<FileBarChart size={16} />}
            onClick={() => setShowGenerateBOQ(true)}
          >
            {t('schedule.generate_from_boq', 'Generate from BOQ')}
          </Button>
          {hasActivities && (
            <>
              {/* View mode toggle: Table vs SVG Gantt */}
              <div className="flex items-center gap-1 rounded-lg border border-border-light p-0.5">
                {([
                  { key: 'table' as const, label: t('schedule.view_table', 'Table') },
                  { key: 'gantt' as const, label: t('schedule.view_gantt', 'Gantt') },
                ]).map((v) => (
                  <button
                    key={v.key}
                    onClick={() => setViewMode(v.key)}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      viewMode === v.key
                        ? 'bg-oe-blue text-white'
                        : 'text-content-secondary hover:bg-surface-secondary'
                    }`}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1 rounded-lg border border-border-light p-0.5">
                {(['day', 'week', 'month', 'quarter', 'year'] as const).map((level) => (
                  <button
                    key={level}
                    onClick={() => setZoomLevel(level)}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      zoomLevel === level
                        ? 'bg-oe-blue text-white'
                        : 'text-content-secondary hover:bg-surface-secondary'
                    }`}
                  >
                    {t(`schedule.zoom_${level}`, { defaultValue: level.charAt(0).toUpperCase() + level.slice(1) })}
                  </button>
                ))}
              </div>
              <Button
                variant="secondary"
                icon={<Zap size={16} />}
                onClick={() => calculateCPM.mutate()}
                loading={calculateCPM.isPending}
                title={t('schedule.cpm_tooltip', { defaultValue: 'Critical Path Method calculates the longest path through the project and identifies activities that cannot be delayed' })}
              >
                {t('schedule.calculate_cpm', 'Critical Path')}
              </Button>
              <Button
                variant="secondary"
                icon={<ShieldAlert size={16} />}
                onClick={() => fetchRiskAnalysis.mutate()}
                loading={fetchRiskAnalysis.isPending}
              >
                {t('schedule.risk_analysis_btn', 'Risk Analysis')}
              </Button>
              {/* Export schedule as TSV */}
              <Button
                variant="secondary"
                size="sm"
                icon={<Download size={14} />}
                onClick={() => {
                  const activities = ganttData?.activities ?? [];
                  const rows = [
                    [
                      t('schedule.export_wbs', { defaultValue: 'WBS' }),
                      t('schedule.export_name', { defaultValue: 'Name' }),
                      t('schedule.export_type', { defaultValue: 'Type' }),
                      t('schedule.export_start', { defaultValue: 'Start' }),
                      t('schedule.export_end', { defaultValue: 'End' }),
                      t('schedule.export_duration', { defaultValue: 'Duration (days)' }),
                      t('schedule.export_progress', { defaultValue: 'Progress %' }),
                      t('schedule.export_status', { defaultValue: 'Status' }),
                    ].join('\t'),
                    ...activities.map((a) => [
                      a.wbs_code, a.name, a.activity_type, a.start_date, a.end_date,
                      a.duration_days, a.progress_pct, a.status,
                    ].join('\t')),
                  ];
                  const blob = new Blob([rows.join('\n')], { type: 'text/tab-separated-values' });
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement('a');
                  link.href = url;
                  link.download = `schedule_${schedule.name.replace(/\s+/g, '_')}.tsv`;
                  link.click();
                  URL.revokeObjectURL(url);
                  addToast({ type: 'success', title: t('schedule.exported', { defaultValue: 'Schedule exported' }) });
                }}
              >
                {t('common.export', { defaultValue: 'Export' })}
              </Button>
              {/* Reset schedule */}
              <Button
                variant="ghost"
                size="sm"
                icon={<RotateCcw size={14} />}
                onClick={async () => {
                  const ok = await confirm({
                    title: t('schedule.confirm_reset_title', { defaultValue: 'Reset schedule?' }),
                    message: t('schedule.confirm_reset', { defaultValue: 'Delete all activities and regenerate? This cannot be undone.' }),
                  });
                  if (ok) resetSchedule.mutate();
                }}
                loading={resetSchedule.isPending}
              >
                {t('schedule.reset', { defaultValue: 'Reset' })}
              </Button>
            </>
          )}
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={() => setShowAddActivity(true)}
          >
            {t('schedule.add_activity', 'Add Activity')}
          </Button>
        </div>
      </div>

      {/* Content area: either the populated schedule or the empty state */}
      {hasActivities ? (
        <>
          {/* Summary stats */}
          {ganttData && <SummaryStats summary={ganttData.summary} />}

          {/* Overall project progress bar */}
          {ganttData && ganttData.summary.total_activities > 0 && (
            <div className="mt-4 rounded-xl border border-border-light bg-surface-primary p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-content-primary">
                  {t('schedule.overall_progress', { defaultValue: 'Overall Progress' })}
                </span>
                <span className="text-sm font-bold text-oe-blue tabular-nums">
                  {Math.round((ganttData.summary.completed / Math.max(ganttData.summary.total_activities, 1)) * 100)}%
                </span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-500"
                  style={{ width: `${(ganttData.summary.completed / Math.max(ganttData.summary.total_activities, 1)) * 100}%` }}
                />
              </div>
              <div className="mt-2 flex items-center gap-4 text-xs text-content-tertiary">
                <span>{ganttData.summary.completed} {t('schedule.completed_label', { defaultValue: 'completed' })}</span>
                <span>{ganttData.summary.in_progress} {t('schedule.in_progress_label', { defaultValue: 'in progress' })}</span>
                <span>{ganttData.summary.delayed} {t('schedule.delayed_label', { defaultValue: 'delayed' })}</span>
              </div>
            </div>
          )}

          {/* Activity filter */}
          <div className="mt-4 flex items-center gap-2">
            <span className="text-xs text-content-tertiary">{t('schedule.filter_label', { defaultValue: 'Show:' })}</span>
            {[
              { key: 'all', label: t('schedule.filter_all', { defaultValue: 'All' }), count: ganttData?.summary.total_activities ?? 0 },
              { key: 'critical', label: t('schedule.filter_critical', { defaultValue: 'Critical Path' }), count: cpmResult?.critical_path.length ?? 0, show: !!cpmResult },
              { key: 'delayed', label: t('schedule.filter_delayed', { defaultValue: 'Delayed' }), count: ganttData?.summary.delayed ?? 0 },
              { key: 'in_progress', label: t('schedule.filter_in_progress', { defaultValue: 'In Progress' }), count: ganttData?.summary.in_progress ?? 0 },
            ].filter((f) => f.show !== false && (f.key === 'all' || f.count > 0)).map((f) => (
              <button
                key={f.key}
                onClick={() => setActivityFilter(f.key)}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                  activityFilter === f.key
                    ? 'bg-oe-blue text-white'
                    : 'text-content-secondary hover:bg-surface-secondary border border-border-light'
                }`}
              >
                {f.label}
                <span className="tabular-nums">{f.count}</span>
              </button>
            ))}
          </div>

          {/* Risk analysis card */}
          {riskResult && <RiskAnalysisCard data={riskResult} />}

          {/* CPM summary (when calculated but risk not yet requested) */}
          {cpmResult && !riskResult && (
            <Card padding="sm" className="mt-4">
              <div className="flex items-center gap-3">
                <Zap size={16} className="text-semantic-error" />
                <span className="text-sm font-medium text-content-primary">
                  {t('schedule.cpm_result', 'Critical Path: {{duration}} days, {{count}} critical activities', {
                    duration: cpmResult.project_duration_days,
                    count: cpmResult.critical_path.length,
                  })}
                </span>
              </div>
            </Card>
          )}

          {/* BIM hint */}
          {hasBIMModels && (
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/30 px-4 py-2.5">
              <Box size={14} className="shrink-0 text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                {t('schedule.bim_hint', {
                  defaultValue:
                    'BIM models available -- link activities to elements for 4D visualization',
                })}
              </span>
            </div>
          )}

          {/* Gantt chart */}
          <div className="mt-6">
            {isLoading ? (
              <SkeletonTable rows={4} columns={4} />
            ) : ganttData ? (
              viewMode === 'gantt' ? (
                <SVGGanttChart
                  activities={svgGanttActivities}
                  viewMode={zoomLevel as GanttViewMode}
                  showBaseline={false}
                  showDependencies={true}
                  showCriticalPath={!!cpmResult}
                  todayLine={true}
                />
              ) : (
                <GanttChart
                  activities={filteredActivities}
                  onUpdateProgress={handleUpdateProgress}
                  criticalActivityIds={criticalActivityIds}
                  zoomLevel={zoomLevel}
                />
              )
            ) : null}
          </div>
        </>
      ) : (
        /* Empty state: no activities yet */
        <div className="mt-6">
          {isLoading ? (
            <SkeletonTable rows={4} columns={4} />
          ) : (
            <Card padding="none" className="overflow-hidden">
              <div className="flex flex-col items-center justify-center py-14 px-6 text-center">
                <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-oe-blue/10 to-oe-blue/20">
                  <CalendarDays size={32} className="text-oe-blue" />
                </div>
                <h3 className="text-lg font-semibold text-content-primary">
                  {t('schedule.detail_empty_title', { defaultValue: 'Build your project timeline' })}
                </h3>
                <p className="mt-1.5 max-w-md text-sm text-content-secondary">
                  {t('schedule.detail_empty_desc', {
                    defaultValue: 'Add activities manually or generate them from an existing BOQ. The Gantt chart, dependencies, and critical path analysis will appear here.',
                  })}
                </p>

                {/* Quick-start options */}
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-lg">
                  <button
                    onClick={() => setShowGenerateBOQ(true)}
                    className="group flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border-light bg-surface-secondary/30 p-6 transition-all hover:border-oe-blue/50 hover:bg-oe-blue-subtle/30"
                  >
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue transition-transform group-hover:scale-110">
                      <FileBarChart size={24} />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('schedule.quickstart_boq_title', { defaultValue: 'Generate from BOQ' })}
                      </p>
                      <p className="mt-0.5 text-xs text-content-tertiary">
                        {t('schedule.quickstart_boq_desc', { defaultValue: 'Auto-create activities from your Bill of Quantities' })}
                      </p>
                    </div>
                  </button>
                  <button
                    onClick={() => setShowAddActivity(true)}
                    className="group flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border-light bg-surface-secondary/30 p-6 transition-all hover:border-oe-blue/50 hover:bg-oe-blue-subtle/30"
                  >
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-surface-secondary text-content-secondary transition-transform group-hover:scale-110">
                      <Plus size={24} />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('schedule.quickstart_manual_title', { defaultValue: 'Add Manually' })}
                      </p>
                      <p className="mt-0.5 text-xs text-content-tertiary">
                        {t('schedule.quickstart_manual_desc', { defaultValue: 'Create tasks, milestones, and summary activities' })}
                      </p>
                    </div>
                  </button>
                </div>

                {/* Feature hints */}
                <div className="mt-8 flex flex-wrap justify-center gap-4 text-xs text-content-tertiary">
                  <span className="flex items-center gap-1.5">
                    <Zap size={12} className="text-oe-blue" />
                    {t('schedule.hint_cpm', { defaultValue: 'CPM critical path' })}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <GitBranch size={12} className="text-oe-blue" />
                    {t('schedule.hint_deps', { defaultValue: 'FS/SS/FF/SF dependencies' })}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <ShieldAlert size={12} className="text-oe-blue" />
                    {t('schedule.hint_risk', { defaultValue: 'PERT risk analysis' })}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <TrendingUp size={12} className="text-oe-blue" />
                    {t('schedule.hint_progress', { defaultValue: 'Progress tracking' })}
                  </span>
                </div>
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Add Activity Modal */}
      <Modal
        open={showAddActivity}
        onClose={() => setShowAddActivity(false)}
        title={t('schedule.add_activity', 'Add Activity')}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addActivity.mutate(activityForm);
          }}
          className="space-y-4"
        >
          <Input
            label={t('schedule.activity_name', 'Activity Name')}
            placeholder={t('schedule.activity_name_placeholder', 'e.g. Foundation Works')}
            value={activityForm.name}
            onChange={(e) => setActivityForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
          <Input
            label={t('schedule.wbs_code', 'WBS Code')}
            placeholder={t('schedule.wbs_code_placeholder', 'e.g. 01.02.003')}
            value={activityForm.wbs_code}
            onChange={(e) => setActivityForm((f) => ({ ...f, wbs_code: e.target.value }))}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('schedule.start_date', 'Start Date')}
              type="date"
              value={activityForm.start_date}
              onChange={(e) => setActivityForm((f) => ({ ...f, start_date: e.target.value }))}
              required
            />
            <Input
              label={t('schedule.end_date', 'End Date')}
              type="date"
              value={activityForm.end_date}
              onChange={(e) => setActivityForm((f) => ({ ...f, end_date: e.target.value }))}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('schedule.activity_type', 'Type')}
            </label>
            <div className="flex gap-2">
              {(['task', 'milestone', 'summary'] as const).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setActivityForm((f) => ({ ...f, activity_type: type }))}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium capitalize transition-all ${
                    activityForm.activity_type === type
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {t(`schedule.type_${type}`, { defaultValue: type })}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" type="button" onClick={() => setShowAddActivity(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={addActivity.isPending}>
              {t('schedule.create_activity', 'Create Activity')}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Generate from BOQ Modal */}
      <Modal
        open={showGenerateBOQ}
        onClose={() => setShowGenerateBOQ(false)}
        title={t('schedule.generate_from_boq', 'Generate from BOQ')}
      >
        <div className="space-y-4">
          <p className="text-sm text-content-secondary">
            {t(
              'schedule.generate_from_boq_description',
              'Select a BOQ to auto-generate schedule activities. One activity will be created per BOQ section with cost-proportional durations.',
            )}
          </p>

          {/* Start date picker */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('schedule.project_start_date', 'Project Start Date')}
            </label>
            <input
              type="date"
              value={generateStartDate}
              onChange={(e) => setGenerateStartDate(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {t('schedule.start_date_hint', 'All activities will be scheduled relative to this date.')}
            </p>
          </div>

          {!boqs || boqs.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('schedule.no_boqs_available', 'No BOQs available for this project.')}
            </p>
          ) : (
            <div className="space-y-2">
              {boqs.map((boq) => (
                <button
                  key={boq.id}
                  type="button"
                  onClick={() => setSelectedBOQId(boq.id)}
                  className={`w-full rounded-lg border px-4 py-3 text-left transition-all ${
                    selectedBOQId === boq.id
                      ? 'border-oe-blue bg-oe-blue-subtle'
                      : 'border-border bg-surface-primary hover:bg-surface-secondary'
                  }`}
                >
                  <p className="text-sm font-medium text-content-primary">{boq.name}</p>
                  {boq.description && (
                    <p className="mt-0.5 text-xs text-content-secondary truncate">
                      {boq.description}
                    </p>
                  )}
                  <Badge
                    variant={boq.status === 'approved' ? 'success' : 'neutral'}
                    size="sm"
                    className="mt-1"
                  >
                    {t(`boq.${boq.status}`, { defaultValue: boq.status })}
                  </Badge>
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setShowGenerateBOQ(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={!selectedBOQId || !generateStartDate}
              loading={generateFromBOQ.isPending}
              onClick={() => {
                if (selectedBOQId) {
                  generateFromBOQ.mutate(selectedBOQId);
                }
              }}
            >
              {t('schedule.generate', 'Generate')}
            </Button>
          </div>
        </div>
      </Modal>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Schedule List for a Project ───────────────────────────────────────── */

function ProjectSchedules({
  project,
  onBack,
}: {
  project: Project;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateScheduleForm>({
    name: '',
    description: '',
    start_date: '',
    end_date: '',
  });

  const { data: schedules, isLoading } = useQuery({
    queryKey: ['schedules', project.id],
    queryFn: () => scheduleApi.listSchedules(project.id),
  });

  const createSchedule = useMutation({
    mutationFn: (data: CreateScheduleForm) =>
      scheduleApi.createSchedule({
        project_id: project.id,
        name: data.name,
        description: data.description || undefined,
        start_date: data.start_date || undefined,
        end_date: data.end_date || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules', project.id] });
      setShowCreate(false);
      setForm({ name: '', description: '', start_date: '', end_date: '' });
      addToast({ type: 'success', title: t('toasts.schedule_created', { defaultValue: 'Schedule created' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // If a schedule is selected, show its detail
  if (selectedSchedule) {
    return (
      <ScheduleDetail
        schedule={selectedSchedule}
        projectId={project.id}
        onBack={() => setSelectedSchedule(null)}
      />
    );
  }

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary transition-colors hover:text-content-primary"
      >
        <ArrowLeft size={14} />
        {t('schedule.back_to_projects', 'Back to projects')}
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{project.name}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('schedule.project_schedules', 'Schedules for this project')}
          </p>
        </div>
        <Button
          variant="primary"
          size="lg"
          icon={<Plus size={18} />}
          onClick={() => setShowCreate(true)}
        >
          {t('schedule.create_schedule', 'Create Schedule')}
        </Button>
      </div>

      {/* Schedule list */}
      {isLoading ? (
        <SkeletonTable rows={3} columns={4} />
      ) : !schedules || schedules.length === 0 ? (
        <div className="max-w-3xl mx-auto py-6">
          {/* Hero */}
          <div className="text-center mb-8">
            <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-oe-blue/10 to-oe-blue/20 flex items-center justify-center mb-4">
              <CalendarDays size={32} className="text-oe-blue" />
            </div>
            <h2 className="text-xl font-bold text-content-primary">
              {t('schedule.empty_hero_title', { defaultValue: '4D Schedule with Gantt Chart' })}
            </h2>
            <p className="text-sm text-content-secondary mt-2 max-w-lg mx-auto">
              {t('schedule.empty_hero_desc', {
                defaultValue: 'Plan your construction timeline with interactive Gantt charts, dependency management, and Critical Path Method analysis. Generate schedules automatically from your BOQ.',
              })}
            </p>
          </div>

          {/* Feature cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="border border-border-light rounded-lg bg-surface-primary p-5 text-center">
              <div className="mx-auto w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-950/30 flex items-center justify-center mb-3">
                <FileBarChart size={20} className="text-blue-600 dark:text-blue-400" />
              </div>
              <h3 className="text-sm font-semibold text-content-primary mb-1">
                {t('schedule.feature_boq_title', { defaultValue: 'Auto-generate from BOQ' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('schedule.feature_boq_desc', {
                  defaultValue: 'Create activities from your Bill of Quantities with cost-proportional durations.',
                })}
              </p>
            </div>
            <div className="border border-border-light rounded-lg bg-surface-primary p-5 text-center">
              <div className="mx-auto w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 flex items-center justify-center mb-3">
                <GitBranch size={20} className="text-emerald-600 dark:text-emerald-400" />
              </div>
              <h3 className="text-sm font-semibold text-content-primary mb-1">
                {t('schedule.feature_deps_title', { defaultValue: 'Dependencies & Links' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('schedule.feature_deps_desc', {
                  defaultValue: 'FS, SS, FF, SF dependency types with lag days. Arrows drawn automatically on the Gantt chart.',
                })}
              </p>
            </div>
            <div className="border border-border-light rounded-lg bg-surface-primary p-5 text-center">
              <div className="mx-auto w-10 h-10 rounded-lg bg-red-50 dark:bg-red-950/30 flex items-center justify-center mb-3">
                <Zap size={20} className="text-red-600 dark:text-red-400" />
              </div>
              <h3 className="text-sm font-semibold text-content-primary mb-1">
                {t('schedule.feature_cpm_title', { defaultValue: 'CPM Critical Path' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('schedule.feature_cpm_desc', {
                  defaultValue: 'Identify activities that directly affect the project end date. Calculate float and slack.',
                })}
              </p>
            </div>
            <div className="border border-border-light rounded-lg bg-surface-primary p-5 text-center">
              <div className="mx-auto w-10 h-10 rounded-lg bg-violet-50 dark:bg-violet-950/30 flex items-center justify-center mb-3">
                <ShieldAlert size={20} className="text-violet-600 dark:text-violet-400" />
              </div>
              <h3 className="text-sm font-semibold text-content-primary mb-1">
                {t('schedule.feature_risk_title', { defaultValue: 'Monte Carlo Risk' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('schedule.feature_risk_desc', {
                  defaultValue: 'PERT-based risk analysis with P50/P80/P95 confidence intervals and buffer calculation.',
                })}
              </p>
            </div>
          </div>

          {/* CTA */}
          <div className="text-center">
            <Button
              variant="primary"
              size="lg"
              icon={<Plus size={18} />}
              onClick={() => setShowCreate(true)}
            >
              {t('schedule.create_schedule', { defaultValue: 'Create Schedule' })}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {schedules.map((schedule) => (
            <Card
              key={schedule.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setSelectedSchedule(schedule)}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                  <CalendarDays size={18} strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary truncate">
                    {schedule.name}
                  </h2>
                  <p className="mt-0.5 text-xs text-content-secondary truncate">
                    {schedule.description ||
                      (schedule.start_date
                        ? `${formatDate(schedule.start_date)}${schedule.end_date ? ` \u2013 ${formatDate(schedule.end_date)}` : ''}`
                        : t('schedule.no_dates', 'No dates set'))}
                  </p>
                </div>
                <Badge variant={schedule.status === 'active' ? 'blue' : 'neutral'} size="sm">
                  {t(`schedule.status_${schedule.status}`, { defaultValue: schedule.status })}
                </Badge>
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create Schedule Modal */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title={t('schedule.create_schedule', 'Create Schedule')}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createSchedule.mutate(form);
          }}
          className="space-y-4"
        >
          <Input
            label={t('schedule.schedule_name', 'Schedule Name')}
            placeholder={t('schedule.schedule_name_placeholder', 'e.g. Main Construction Schedule')}
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
          <Input
            label={t('schedule.description', 'Description')}
            placeholder={t('schedule.description_placeholder', 'Optional description')}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('schedule.start_date', 'Start Date')}
              type="date"
              value={form.start_date}
              onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
            />
            <Input
              label={t('schedule.end_date', 'End Date')}
              type="date"
              value={form.end_date}
              onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
            />
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" type="button" onClick={() => setShowCreate(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={createSchedule.isPending}>
              {t('common.create', 'Create')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function SchedulePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { activeProjectId, setActiveProject } = useProjectContextStore();

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const selectedProject = useMemo(
    () => projects?.find((p) => p.id === activeProjectId) ?? null,
    [projects, activeProjectId],
  );

  // Project schedule detail view
  if (selectedProject) {
    return (
      <div className="w-full animate-fade-in">
        <Breadcrumb items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('schedule.title', '4D Schedule'), to: '/schedule' },
          { label: selectedProject.name },
        ]} className="mb-4" />

        <ProjectSchedules
          project={selectedProject}
          onBack={() => useProjectContextStore.getState().clearProject()}
        />
      </div>
    );
  }

  // Project list view
  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('schedule.title', '4D Schedule') },
      ]} className="mb-4" />

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('schedule.title', '4D Schedule')}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'schedule.subtitle',
            'Select a project to view and manage its construction schedule',
          )}
        </p>
      </div>

      {/* Cross-module links */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/tasks')}>
          <ClipboardList size={13} className="me-1" />
          {t('schedule.link_tasks', { defaultValue: 'Tasks' })}
        </Button>
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/meetings')}>
          <Users size={13} className="me-1" />
          {t('schedule.link_meetings', { defaultValue: 'Meetings' })}
        </Button>
      </div>

      {/* 4D explanation */}
      <InfoHint className="mb-6" text={t('schedule.what_is_4d', { defaultValue: '4D scheduling links your BOQ positions to a project timeline. Create activities, set dependencies, and visualize progress on a Gantt chart. The critical path analysis highlights activities that directly affect the project end date. Activity types: Task = work item, Milestone = checkpoint with zero duration, Summary = grouping header.' })} />

      {isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : !projects || projects.length === 0 ? (
        <div className="max-w-2xl mx-auto py-8">
          <div className="text-center mb-8">
            <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-oe-blue/10 to-oe-blue/20 flex items-center justify-center mb-4">
              <Calendar size={32} className="text-oe-blue" />
            </div>
            <h2 className="text-xl font-bold text-content-primary">
              {t('schedule.no_projects_title', { defaultValue: 'No projects yet' })}
            </h2>
            <p className="text-sm text-content-secondary mt-2 max-w-md mx-auto">
              {t('schedule.no_projects_desc', {
                defaultValue: 'Create a project first to start building your 4D schedule with Gantt charts, dependencies, and critical path analysis.',
              })}
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8">
            <div className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-4">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                <Layers size={16} className="text-oe-blue" />
              </div>
              <div>
                <p className="text-sm font-medium text-content-primary">{t('schedule.step_1_title', { defaultValue: 'Create a Project' })}</p>
                <p className="text-xs text-content-tertiary mt-0.5">{t('schedule.step_1_desc', { defaultValue: 'Set up your project in the Projects module' })}</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-4">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                <CalendarDays size={16} className="text-oe-blue" />
              </div>
              <div>
                <p className="text-sm font-medium text-content-primary">{t('schedule.step_2_title', { defaultValue: 'Create a Schedule' })}</p>
                <p className="text-xs text-content-tertiary mt-0.5">{t('schedule.step_2_desc', { defaultValue: 'Add timelines and milestones' })}</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-4">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                <Zap size={16} className="text-oe-blue" />
              </div>
              <div>
                <p className="text-sm font-medium text-content-primary">{t('schedule.step_3_title', { defaultValue: 'Analyze & Optimize' })}</p>
                <p className="text-xs text-content-tertiary mt-0.5">{t('schedule.step_3_desc', { defaultValue: 'Run CPM and risk analysis' })}</p>
              </div>
            </div>
          </div>
          <div className="text-center">
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => navigate('/projects')}>
              {t('schedule.go_to_projects', { defaultValue: 'Go to Projects' })}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setActiveProject(project.id, project.name)}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
                  {project.name.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary truncate">
                    {project.name}
                  </h2>
                  {project.description && (
                    <p className="mt-0.5 text-xs text-content-secondary truncate">
                      {project.description}
                    </p>
                  )}
                </div>
                <Badge variant="blue" size="sm">
                  {project.classification_standard === 'din276' ? 'DIN 276' : project.classification_standard?.toUpperCase() || '—'}
                </Badge>
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Fragment, useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
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
  Hash,
  Box,
  GitBranch,
  TrendingUp,
  Layers,
  Table2,
  Network,
  ArrowRight,
  ListPlus,
  Pencil,
} from 'lucide-react';
import { Button, Card, Badge, Input, SkeletonTable, Breadcrumb, DismissibleInfo, IntroRichText, GanttChart as SVGGanttChart, ViewInBIMButton, ConfirmDialog, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import type { GanttActivity as SVGGanttActivity, GanttViewMode } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { scheduleApi } from './api';
import { PlanningCrossLinks } from './PlanningCrossLinks';
import { EvmPanel } from './EvmPanel';
import { Snapshot4DView } from './Snapshot4DView';
import { ScheduleQualityPanel } from './ScheduleQualityPanel';
import { ScheduleRiskPanel } from './ScheduleRiskPanel';
import { ScheduleComparePanel } from './ScheduleComparePanel';
import { ScheduleInterchangePanel } from './ScheduleInterchangePanel';
import { ProgressRigorPanel } from './ProgressRigorPanel';
import { ScheduleDelayPanel } from './ScheduleDelayPanel';
import { ScheduleCodesPanel } from './ScheduleCodesPanel';
import { ScheduleResourcePanel } from './ScheduleResourcePanel';
import { ScheduleRealtimePanel } from './ScheduleRealtimePanel';
import { scheduleGuide } from './scheduleGuide';
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

type DependencyType = 'FS' | 'SS' | 'FF' | 'SF';

interface ActivityDependencyDraft {
  activity_id: string;
  type: DependencyType;
  lag_days: number;
}

interface CreateActivityForm {
  name: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  activity_type: 'task' | 'milestone' | 'summary';
  /** Predecessor links (FS/SS/FF/SF + lag). Projected into the canonical
   *  ScheduleRelationship table server-side via the activity create/update
   *  payload, so editing them here is atomic with the rest of the activity. */
  dependencies: ActivityDependencyDraft[];
}

const DEPENDENCY_TYPES: DependencyType[] = ['FS', 'SS', 'FF', 'SF'];

/** Shared tailwind classes for the native selects/inputs in the activity
 *  modal, mirroring the date inputs used elsewhere on this page. */
const FIELD_CLS =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Resolve the end date for an inline duration edit. The backend stores
 *  duration as *working* days (compute_duration), so a duration of N means the
 *  Nth working day on/after the start. We approximate with a Mon–Fri week here;
 *  the server recomputes the authoritative duration from the dates on save, so
 *  any regional-calendar nuance is reconciled on refetch. */
function addWorkingDays(startISO: string, workingDays: number): string {
  const d = new Date(`${startISO}T00:00:00`);
  if (Number.isNaN(d.getTime())) return startISO;
  let counted = 0;
  for (;;) {
    const dow = d.getDay();
    if (dow !== 0 && dow !== 6) counted++;
    if (counted >= Math.max(1, workingDays)) break;
    d.setDate(d.getDate() + 1);
  }
  return d.toISOString().slice(0, 10);
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(getIntlLocale(), {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * Neutralise a spreadsheet formula-injection vector before a value is written
 * into an exported CSV/TSV cell. If the string starts with a dangerous trigger
 * character (=, +, -, @, tab, CR, LF) a spreadsheet app evaluates it as a
 * formula, so we prefix a single apostrophe - the cell renders unchanged but
 * is treated as literal text. Mirrors the backend
 * ``app.core.csv_safety.neutralise_formula`` contract.
 *
 * @see https://owasp.org/www-community/attacks/CSV_Injection
 */
function neutraliseFormula(value: unknown): string {
  if (value === null || value === undefined) return '';
  const s = String(value);
  if (s.length === 0) return s;
  const TRIGGERS = new Set(['=', '+', '-', '@', '\t', '\r', '\n']);
  return TRIGGERS.has(s[0]!) ? `'${s}` : s;
}

function daysBetween(start: string, end: string): number {
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (isNaN(s) || isNaN(e)) return 1;
  return Math.max(1, Math.ceil((e - s) / (1000 * 60 * 60 * 24)));
}

/** Assign hierarchical WBS codes (1, 1.1, 1.2, 2, 2.1, …) to a flat ordered
 *  list of activities using their parent_id links. Returns a map id→code for
 *  every activity whose code differs from its current wbs_code. */
function buildWbsCodes(activities: Activity[]): Map<string, string> {
  const childrenOf = new Map<string | null, Activity[]>();
  for (const a of activities) {
    const key = a.parent_id ?? null;
    const arr = childrenOf.get(key) ?? [];
    arr.push(a);
    childrenOf.set(key, arr);
  }
  const result = new Map<string, string>();
  const assign = (parentId: string | null, prefix: string) => {
    const kids = childrenOf.get(parentId) ?? [];
    kids.forEach((a, i) => {
      const code = prefix ? `${prefix}.${i + 1}` : String(i + 1);
      result.set(a.id, code);
      assign(a.id, code);
    });
  };
  assign(null, '');
  return result;
}

/** True when the activity's duration was estimated from unit-based production
 *  rates (`duration_source` / `duration_method` = "estimated_fallback" in the
 *  activity metadata) instead of real labor data. */
function hasEstimatedDuration(activity: Activity): boolean {
  const md = activity.metadata;
  if (!md) return false;
  return md.duration_source === 'estimated_fallback' || md.duration_method === 'estimated_fallback';
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
  // Backend maps NORDIC -> DACH (8h/5d); keep the fallback in sync.
  NORDIC: { hours: 8, days: 5 },
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
      <div className="fixed inset-0 bg-black/70 backdrop-blur-lg" aria-hidden="true" onClick={onClose} />
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
  onEditActivity,
  criticalActivityIds,
  zoomLevel = 'week',
}: {
  activities: Activity[];
  onUpdateProgress: (activityId: string, progress: number) => void;
  onEditActivity?: (activity: Activity) => void;
  criticalActivityIds?: Set<string>;
  zoomLevel?: ZoomLevel;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
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

  // Calculate today marker position. Use a SIGNED day offset, not
  // daysBetween() (which floors at 1) - otherwise a "today" that falls before
  // the timeline start is clamped to +1 day and the marker is wrongly drawn at
  // the left edge instead of being hidden by the 0..100 guard below.
  const todayOffset = Math.round(
    (new Date().getTime() - timelineStart.getTime()) / (1000 * 60 * 60 * 24),
  );
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
                ? { bg: 'bg-oe-blue-subtle', fill: 'bg-oe-blue/30', text: 'text-oe-blue-text', variant: 'neutral' as const }
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
                    {hasEstimatedDuration(activity) && (
                      <span
                        title={t('schedule.duration_estimated_tooltip', {
                          defaultValue: 'Duration estimated from production rates',
                        })}
                        className="inline-flex shrink-0 cursor-help items-center gap-0.5 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-[9px] font-semibold text-content-tertiary"
                      >
                        <Clock size={9} className="shrink-0" />
                        {t('schedule.duration_estimated_badge', { defaultValue: 'Est.' })}
                      </span>
                    )}
                    <ViewInBIMButton
                      elementIds={activity.bim_element_ids ?? []}
                      iconSize={9}
                      className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold bg-amber-50 dark:bg-amber-950/40 text-amber-700 border border-amber-200 dark:border-amber-900/60 hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
                    />
                    {/* CONN-33: the activity already carries the BOQ positions
                        it was generated from; turn that data island into a
                        deep link. BOQListPage resolves the owning BOQ from a
                        single positionId and redirects to its editor with the
                        per-position ?highlight convention. */}
                    {(activity.boq_position_ids?.length ?? 0) > 0 && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          const pid = activity.boq_position_ids[0];
                          if (pid) navigate(`/boq?positionId=${encodeURIComponent(pid)}`);
                        }}
                        title={t('schedule.view_in_boq', {
                          defaultValue: 'View in BOQ ({{count}} position(s))',
                          count: activity.boq_position_ids.length,
                        })}
                        className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold bg-oe-blue-subtle text-oe-blue-text border border-oe-blue/30 hover:bg-oe-blue/10 transition-colors"
                      >
                        <Table2 size={9} className="shrink-0" />
                        {t('schedule.view_in_boq_short', { defaultValue: 'BOQ' })}
                      </button>
                    )}
                    {onEditActivity && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEditActivity(activity);
                        }}
                        title={t('schedule.edit_activity', { defaultValue: 'Edit activity & dependencies' })}
                        className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-semibold bg-surface-secondary text-content-secondary border border-border-light hover:bg-surface-tertiary transition-colors"
                      >
                        <Pencil size={9} className="shrink-0" />
                        {t('schedule.edit_short', { defaultValue: 'Edit' })}
                      </button>
                    )}
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
                    ? { bg: 'bg-oe-blue-subtle', fill: 'bg-oe-blue/30', text: 'text-oe-blue-text', variant: 'neutral' as const }
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
  const navigate = useNavigate();

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
      {/* Next step: turn the schedule-risk buffer into cost contingency
          and a tracked risk entry. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
        <span className="text-2xs text-content-tertiary">
          {t('schedule.risk_next_step', { defaultValue: 'Carry this buffer forward:' })}
        </span>
        <button
          type="button"
          onClick={() => navigate('/risks')}
          className="inline-flex items-center gap-1 rounded-full border border-border-light px-2.5 py-0.5 text-2xs font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue"
        >
          <ShieldAlert size={11} />
          {t('schedule.open_risk_register', { defaultValue: 'Log in Risk Register' })}
        </button>
        <button
          type="button"
          onClick={() => navigate('/5d')}
          className="inline-flex items-center gap-1 rounded-full border border-border-light px-2.5 py-0.5 text-2xs font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue"
        >
          <TrendingUp size={11} />
          {t('schedule.open_5d_contingency', { defaultValue: 'Cost contingency in 5D' })}
        </button>
      </div>
    </Card>
  );
}

/* ── Schedule Detail View ──────────────────────────────────────────────── */

function ScheduleDetail({
  schedule,
  projectId,
  onBack,
  generateBoqId,
  onConsumeGenerateBoq,
}: {
  schedule: Schedule;
  projectId: string;
  onBack: () => void;
  /** CONN-34: BOQ id to pre-load into Generate-from-BOQ (deep link). */
  generateBoqId?: string | null;
  /** Called once the generate modal has consumed the deep-link BOQ id. */
  onConsumeGenerateBoq?: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>('week');
  const [viewMode, setViewMode] = useState<
    'table' | 'gantt' | 'evm' | '4d' | 'quality' | 'risk' | 'compare' | 'progress' | 'delay' | 'codes' | 'resources' | 'realtime' | 'interchange'
  >('gantt');
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
    dependencies: [],
  });
  // When set, the activity modal edits this activity instead of creating one.
  const [editingActivityId, setEditingActivityId] = useState<string | null>(null);

  // Fetch project data for region / work calendar / currency
  const { data: projectData } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => apiGet<{ id: string; region: string; currency?: string }>(`/v1/projects/${projectId}`),
    staleTime: 300_000,
  });
  // Project ISO currency drives EVM money formatting; blank -> no symbol
  // (never mislabel a non-EUR amount). The activity cost columns are all
  // project-scoped so they share this single currency.
  const projectCurrency = projectData?.currency ?? '';
  // Resolve the work calendar from the backend so the badge matches the
  // hours-per-day / days-per-week the schedule math actually uses. The
  // client-side WORK_CALENDAR_INFO map only covers 12 exact keys and diverges
  // for stored region values like "Middle East" / "United States" / "DE_BERLIN"
  // / "NORDIC"; it is kept only as a pre-fetch fallback.
  const { data: workCalendar } = useQuery({
    queryKey: ['work-calendar', projectId],
    queryFn: () =>
      apiGet<{ region: string | null; hours_per_day: number; work_days_per_week: number; label: string }>(
        `/v1/schedule/work-calendar/?project_id=${projectId}`,
      ),
    enabled: !!projectId,
    staleTime: 300_000,
  });
  const fallbackCal =
    WORK_CALENDAR_INFO[projectData?.region ?? ''] ?? WORK_CALENDAR_INFO['DACH'] ?? { hours: 8, days: 5 };
  const calInfo = workCalendar
    ? { hours: workCalendar.hours_per_day, days: workCalendar.work_days_per_week }
    : fallbackCal;

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

  // CONN-34: when reached via the BOQ "Build schedule from this BOQ" deep
  // link, open the Generate-from-BOQ modal and pre-select that BOQ. Setting
  // selectedBOQId before the BOQ list loads is safe: the modal simply
  // highlights the matching card once the list arrives. The param is cleared
  // on the parent so a refresh or back-navigation doesn't re-open the modal.
  const generateDeepLinkRef = useRef(false);
  useEffect(() => {
    if (!generateBoqId || generateDeepLinkRef.current) return;
    generateDeepLinkRef.current = true;
    setSelectedBOQId(generateBoqId);
    setShowGenerateBOQ(true);
    onConsumeGenerateBoq?.();
  }, [generateBoqId, onConsumeGenerateBoq]);

  // CPM state
  const [cpmResult, setCpmResult] = useState<CriticalPathResponse | null>(null);
  const [riskResult, setRiskResult] = useState<RiskAnalysisResponse | null>(null);

  const criticalActivityIds = useMemo(() => {
    if (!cpmResult) return undefined;
    return new Set(cpmResult.critical_path.map((a) => a.activity_id));
  }, [cpmResult]);

  const closeActivityModal = useCallback(() => {
    setShowAddActivity(false);
    setEditingActivityId(null);
    setActivityForm({
      name: '',
      wbs_code: '',
      start_date: '',
      end_date: '',
      activity_type: 'task',
      dependencies: [],
    });
  }, []);

  // Open the activity modal in create mode (blank form, no editing target).
  const openCreateActivity = useCallback(() => {
    setEditingActivityId(null);
    setActivityForm({
      name: '',
      wbs_code: '',
      start_date: '',
      end_date: '',
      activity_type: 'task',
      dependencies: [],
    });
    setShowAddActivity(true);
  }, []);

  const saveActivity = useMutation({
    mutationFn: ({ id, data }: { id: string | null; data: CreateActivityForm }) => {
      // Drop half-filled dependency rows (no predecessor chosen yet) before
      // sending. The backend reconciles this list into the canonical
      // ScheduleRelationship table (create/update/delete), so it is the full
      // desired predecessor set for the activity.
      const payload = {
        name: data.name,
        wbs_code: data.wbs_code,
        start_date: data.start_date,
        end_date: data.end_date,
        activity_type: data.activity_type,
        dependencies: data.dependencies.filter((d) => d.activity_id),
      };
      return id
        ? scheduleApi.updateActivity(id, payload)
        : scheduleApi.createActivity(schedule.id, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      // Dependencies/dates changed → any computed critical path is now stale.
      setCpmResult(null);
      const wasEditing = editingActivityId != null;
      closeActivityModal();
      addToast({
        type: 'success',
        title: wasEditing
          ? t('toasts.activity_updated', { defaultValue: 'Activity updated' })
          : t('toasts.activity_created', { defaultValue: 'Activity created' }),
      });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // Open the activity modal in edit mode, prefilled from an existing activity.
  const openEditActivity = useCallback(
    (activity: Activity) => {
      setEditingActivityId(activity.id);
      setActivityForm({
        name: activity.name,
        wbs_code: activity.wbs_code,
        start_date: (activity.start_date ?? '').slice(0, 10),
        end_date: (activity.end_date ?? '').slice(0, 10),
        activity_type: (activity.activity_type as CreateActivityForm['activity_type']) || 'task',
        dependencies: (activity.dependencies ?? []).map((d) => ({
          activity_id: d.activity_id,
          type: (String(d.type || 'FS').toUpperCase() as DependencyType),
          lag_days: d.lag_days ?? 0,
        })),
      });
      setShowAddActivity(true);
    },
    [],
  );

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
      // The backend returns HTTP 409 when an activity cannot be completed
      // because a predecessor is still open. Surface that as a clear,
      // non-alarming hint (the message already names the blockers) rather
      // than a generic "update failed" error.
      if ((error as { status?: number }).status === 409) {
        addToast({
          type: 'warning',
          title: t('schedule.complete_blocked', { defaultValue: 'Blocked by predecessor' }),
          message: error.message,
        });
        return;
      }
      addToast({ type: 'error', title: t('toasts.update_failed', { defaultValue: 'Update failed' }), message: error.message });
    },
  });

  const resizeActivity = useMutation({
    mutationFn: ({ activityId, start_date, end_date }: { activityId: string; start_date: string; end_date: string }) =>
      scheduleApi.updateActivity(activityId, { start_date, end_date }),
    // Optimistic update: patch the cached gantt payload so the bar stays in
    // its new position while the request flies. Snapshot the previous data
    // for revert-on-error.
    onMutate: async ({ activityId, start_date, end_date }) => {
      const queryKey = ['gantt', schedule.id];
      await queryClient.cancelQueries({ queryKey });
      const prev = queryClient.getQueryData<GanttData>(queryKey);
      if (prev) {
        queryClient.setQueryData<GanttData>(queryKey, {
          ...prev,
          activities: prev.activities.map((a) =>
            a.id === activityId ? { ...a, start_date, end_date } : a,
          ),
        });
      }
      return { prev };
    },
    onError: (error: Error, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['gantt', schedule.id], ctx.prev);
      addToast({ type: 'error', title: t('toasts.update_failed', { defaultValue: 'Update failed' }), message: error.message });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
    },
  });

  const handleActivityResize = useCallback(
    (id: string, newStart: string, newEnd: string) => {
      resizeActivity.mutate({ activityId: id, start_date: newStart, end_date: newEnd });
    },
    [resizeActivity],
  );

  // Inline edit of any grid cell straight from the Gantt left grid.
  const patchActivityField = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Activity> }) =>
      scheduleApi.updateActivity(id, patch),
    onSuccess: (_data, { patch }) => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      // Timing/links changed → any computed critical path is stale.
      if ('start_date' in patch || 'end_date' in patch || 'dependencies' in patch) {
        setCpmResult(null);
      }
    },
    onError: (error: Error) => {
      // Completing an activity with an open predecessor returns 409.
      if ((error as { status?: number }).status === 409) {
        addToast({
          type: 'warning',
          title: t('schedule.complete_blocked', { defaultValue: 'Blocked by predecessor' }),
          message: error.message,
        });
        return;
      }
      addToast({ type: 'error', title: t('toasts.update_failed', { defaultValue: 'Update failed' }), message: error.message });
    },
  });

  const handleActivityFieldChange = useCallback(
    (
      id: string,
      p: {
        name?: string;
        wbsCode?: string;
        durationDays?: number;
        start?: string;
        end?: string;
        progress?: number;
        lag?: number;
      },
    ) => {
      const patch: Partial<Activity> = {};
      if (p.name !== undefined) patch.name = p.name;
      if (p.wbsCode !== undefined) patch.wbs_code = p.wbsCode;
      if (p.start !== undefined) patch.start_date = p.start;
      if (p.end !== undefined) patch.end_date = p.end;
      if (p.progress !== undefined) patch.progress_pct = p.progress;
      if (p.durationDays !== undefined) {
        const act = ganttData?.activities.find((x) => x.id === id);
        if (act) patch.end_date = addWorkingDays((act.start_date ?? '').slice(0, 10), p.durationDays);
      }
      if (p.lag !== undefined) {
        // Inline lag edit only fires for a single-predecessor activity; rebuild
        // that one edge with the new lag (multi-predecessor edits go via modal).
        const deps = ganttData?.activities.find((x) => x.id === id)?.dependencies ?? [];
        const dep = deps.length === 1 ? deps[0] : undefined;
        if (dep) {
          patch.dependencies = [{ activity_id: dep.activity_id, type: dep.type, lag_days: p.lag }];
        }
      }
      if (Object.keys(patch).length > 0) patchActivityField.mutate({ id, patch });
    },
    [ganttData, patchActivityField],
  );

  const renumberWbs = useCallback(() => {
    const acts = ganttData?.activities ?? [];
    if (acts.length === 0) return;
    const newCodes = buildWbsCodes(acts);
    for (const [id, code] of newCodes) {
      const act = acts.find((a) => a.id === id);
      if (act && act.wbs_code !== code) {
        patchActivityField.mutate({ id, patch: { wbs_code: code } });
      }
    }
    addToast({ type: 'success', title: t('schedule.renumber_wbs_done', { defaultValue: 'WBS codes updated' }) });
  }, [ganttData, patchActivityField, addToast, t]);

  const resetSchedule = useMutation({
    mutationFn: () => scheduleApi.clearActivities(schedule.id),
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

  // id -> name map so the Quality / Risk / Compare panels render readable
  // activity labels instead of raw UUIDs. Derived from the Gantt rows the
  // page already holds, so no extra fetch is needed.
  const activitiesById = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    for (const a of ganttData?.activities ?? []) map[a.id] = a.name;
    return map;
  }, [ganttData]);

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

  // Candidate predecessors for the dependency editor: every other activity
  // except the one being edited and its descendants (so the picker can't be
  // used to build an obvious cycle; the backend CPM engine is the final guard).
  const candidatePredecessors = useMemo<Activity[]>(() => {
    const all = ganttData?.activities ?? [];
    if (!editingActivityId) return all;
    // successor adjacency: predecessor id -> [successor ids]
    const succ = new Map<string, string[]>();
    for (const a of all) {
      for (const d of a.dependencies ?? []) {
        const arr = succ.get(d.activity_id) ?? [];
        arr.push(a.id);
        succ.set(d.activity_id, arr);
      }
    }
    const blocked = new Set<string>([editingActivityId]);
    const stack = [editingActivityId];
    while (stack.length) {
      const cur = stack.pop() as string;
      for (const s of succ.get(cur) ?? []) {
        if (!blocked.has(s)) {
          blocked.add(s);
          stack.push(s);
        }
      }
    }
    return all.filter((a) => !blocked.has(a.id));
  }, [ganttData, editingActivityId]);

  // Short reference (WBS code, else name) for each activity, used to label
  // predecessors in the Gantt grid's Predecessors column.
  const activityLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of ganttData?.activities ?? []) {
      map.set(a.id, a.wbs_code || a.name);
    }
    return map;
  }, [ganttData]);

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
      wbsCode: a.wbs_code || undefined,
      durationDays: a.duration_days,
      predecessors: (a.dependencies ?? []).map((d) => ({
        label: activityLabel.get(d.activity_id) ?? '?',
        type: String(d.type || 'FS').toUpperCase(),
        lag: d.lag_days ?? 0,
      })),
    }));
  }, [filteredActivities, criticalActivityIds, activityLabel]);

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
              {/* View mode toggle: Table / Gantt / EVM / 4D */}
              <div className="flex items-center gap-1 rounded-lg border border-border-light p-0.5">
                {([
                  { key: 'table' as const, label: t('schedule.view_table', 'Table') },
                  { key: 'gantt' as const, label: t('schedule.view_gantt', 'Gantt') },
                  { key: 'evm' as const, label: t('schedule.view_evm', { defaultValue: 'EVM' }) },
                  { key: '4d' as const, label: t('schedule.view_4d', { defaultValue: '4D' }) },
                  { key: 'quality' as const, label: t('schedule.view_quality', { defaultValue: 'Quality' }) },
                  { key: 'risk' as const, label: t('schedule.view_risk', { defaultValue: 'Risk' }) },
                  { key: 'compare' as const, label: t('schedule.view_compare', { defaultValue: 'Compare' }) },
                  { key: 'progress' as const, label: t('schedule.view_progress', { defaultValue: 'Progress' }) },
                  { key: 'delay' as const, label: t('schedule.view_delay', { defaultValue: 'Delay' }) },
                  { key: 'codes' as const, label: t('schedule.view_codes', { defaultValue: 'Codes' }) },
                  { key: 'resources' as const, label: t('schedule.view_resources', { defaultValue: 'Resources' }) },
                  { key: 'realtime' as const, label: t('schedule.view_realtime', { defaultValue: 'Live' }) },
                  { key: 'interchange' as const, label: t('schedule.view_interchange', { defaultValue: 'Interchange' }) },
                ]).map((v) => (
                  <button
                    key={v.key}
                    type="button"
                    aria-pressed={viewMode === v.key}
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
              {/* Zoom only applies to the timeline views (table / gantt). */}
              <div
                className={`flex items-center gap-1 rounded-lg border border-border-light p-0.5 ${
                  viewMode !== 'table' && viewMode !== 'gantt' ? 'hidden' : ''
                }`}
              >
                {(['day', 'week', 'month', 'quarter', 'year'] as const).map((level) => (
                  <button
                    key={level}
                    type="button"
                    aria-pressed={zoomLevel === level}
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
                    // String cells are run through neutraliseFormula so a
                    // user-controlled value (e.g. an activity name beginning
                    // with =, +, -, @) cannot execute as a formula when the
                    // exported file is opened in a spreadsheet app. Numeric
                    // columns pass through unchanged.
                    ...activities.map((a) => [
                      neutraliseFormula(a.wbs_code), neutraliseFormula(a.name),
                      neutraliseFormula(a.activity_type), neutraliseFormula(a.start_date),
                      neutraliseFormula(a.end_date),
                      a.duration_days, a.progress_pct, neutraliseFormula(a.status),
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
              {/* Renumber WBS */}
              <Button
                variant="secondary"
                size="sm"
                icon={<Hash size={14} />}
                onClick={renumberWbs}
                title={t('schedule.renumber_wbs_tooltip', { defaultValue: 'Reassign hierarchical WBS codes (1, 1.1, 1.2, …) based on activity order and parent relationships' })}
              >
                {t('schedule.renumber_wbs', { defaultValue: 'Renumber WBS' })}
              </Button>
              {/* Reset schedule */}
              <Button
                variant="ghost"
                size="sm"
                icon={<RotateCcw size={14} />}
                onClick={async () => {
                  const ok = await confirm({
                    title: t('schedule.confirm_reset_title', { defaultValue: 'Reset schedule?' }),
                    message: t('schedule.confirm_reset', { defaultValue: 'Delete all activities in this schedule? This cannot be undone. You can regenerate them afterwards from a BOQ.' }),
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
            onClick={openCreateActivity}
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

          {/* Overall project progress bar — mean physical progress across
              all non-summary activities (summary rows roll up their children
              and would double-count). Falls back to the completed-count ratio
              only when no activity reports progress. */}
          {ganttData && ganttData.summary.total_activities > 0 && (() => {
            const progressActivities = (ganttData.activities ?? []).filter(
              (a) => a.activity_type !== 'summary',
            );
            const meanProgress =
              progressActivities.length > 0
                ? progressActivities.reduce((sum, a) => sum + (a.progress_pct ?? 0), 0) /
                  progressActivities.length
                : (ganttData.summary.completed /
                    Math.max(ganttData.summary.total_activities, 1)) *
                  100;
            const pct = Math.round(meanProgress);
            return (
              <div className="mt-4 rounded-xl border border-border-light bg-surface-primary p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-content-primary">
                    {t('schedule.overall_progress', { defaultValue: 'Overall Progress' })}
                  </span>
                  <span className="text-sm font-bold text-oe-blue tabular-nums">
                    {pct}%
                  </span>
                </div>
                <div className="h-3 w-full overflow-hidden rounded-full bg-surface-secondary">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                  />
                </div>
                <div className="mt-2 flex items-center gap-4 text-xs text-content-tertiary">
                  <span>{ganttData.summary.completed} {t('schedule.completed_label', { defaultValue: 'completed' })}</span>
                  <span>{ganttData.summary.in_progress} {t('schedule.in_progress_label', { defaultValue: 'in progress' })}</span>
                  <span>{ganttData.summary.delayed} {t('schedule.delayed_label', { defaultValue: 'delayed' })}</span>
                </div>
              </div>
            );
          })()}

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
                type="button"
                aria-pressed={activityFilter === f.key}
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

          {/* Main content: timeline (Gantt / Table), EVM, 4D snapshot,
              schedule quality, Monte-Carlo risk, or baseline comparison */}
          <div className="mt-6">
            {viewMode === 'evm' ? (
              <EvmPanel scheduleId={schedule.id} currency={projectCurrency} />
            ) : viewMode === '4d' ? (
              <Snapshot4DView
                scheduleId={schedule.id}
                projectId={projectId}
                scheduleStart={schedule.start_date}
                scheduleEnd={schedule.end_date}
              />
            ) : viewMode === 'quality' ? (
              <ScheduleQualityPanel scheduleId={schedule.id} activitiesById={activitiesById} />
            ) : viewMode === 'risk' ? (
              <ScheduleRiskPanel scheduleId={schedule.id} activitiesById={activitiesById} />
            ) : viewMode === 'compare' ? (
              <ScheduleComparePanel
                scheduleId={schedule.id}
                projectId={projectId}
                currency={projectCurrency}
                activitiesById={activitiesById}
              />
            ) : viewMode === 'interchange' ? (
              <ScheduleInterchangePanel scheduleId={schedule.id} projectId={projectId} />
            ) : viewMode === 'progress' ? (
              <ProgressRigorPanel
                scheduleId={schedule.id}
                activities={(ganttData?.activities ?? []).map((a) => ({
                  id: a.id,
                  name: a.name,
                  progress_pct: a.progress_pct,
                  status: a.status,
                }))}
                currency={projectCurrency}
                dataDate={schedule.start_date}
              />
            ) : viewMode === 'delay' ? (
              <ScheduleDelayPanel
                scheduleId={schedule.id}
                projectId={projectId}
                activitiesById={activitiesById}
              />
            ) : viewMode === 'codes' ? (
              <ScheduleCodesPanel scheduleId={schedule.id} projectId={projectId} />
            ) : viewMode === 'resources' ? (
              <ScheduleResourcePanel
                scheduleId={schedule.id}
                projectId={projectId}
                activitiesById={activitiesById}
              />
            ) : viewMode === 'realtime' ? (
              <ScheduleRealtimePanel
                scheduleId={schedule.id}
                projectId={projectId}
                activitiesById={activitiesById}
              />
            ) : isLoading ? (
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
                  onActivityResize={handleActivityResize}
                  onActivityFieldChange={handleActivityFieldChange}
                  onActivityClick={(id) => {
                    const act = ganttData.activities.find((a) => a.id === id);
                    if (act) openEditActivity(act);
                  }}
                />
              ) : (
                <GanttChart
                  activities={filteredActivities}
                  onUpdateProgress={handleUpdateProgress}
                  onEditActivity={openEditActivity}
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
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text transition-transform group-hover:scale-110">
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
                    onClick={openCreateActivity}
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

      {/* Add / Edit Activity Modal */}
      <Modal
        open={showAddActivity}
        onClose={closeActivityModal}
        title={
          editingActivityId
            ? t('schedule.edit_activity', { defaultValue: 'Edit activity & dependencies' })
            : t('schedule.add_activity', 'Add Activity')
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveActivity.mutate({ id: editingActivityId, data: activityForm });
          }}
          className="space-y-4"
        >
          <Input
            label={t('schedule.activity_name', 'Activity Name')}
            placeholder={t('schedule.activity_name_placeholder', 'e.g. Foundation Works')}
            value={activityForm.name}
            onChange={(e) => setActivityForm((f) => ({ ...f, name: e.target.value }))}
            required aria-required="true"
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
              required aria-required="true"
            />
            <Input
              label={t('schedule.end_date', 'End Date')}
              type="date"
              value={activityForm.end_date}
              onChange={(e) => setActivityForm((f) => ({ ...f, end_date: e.target.value }))}
              required aria-required="true"
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
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {t(`schedule.type_${type}`, { defaultValue: type })}
                </button>
              ))}
            </div>
          </div>

          {/* Dependencies (predecessors): FS/SS/FF/SF + lag. Projected into the
              ScheduleRelationship table by the activity create/update endpoint. */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('schedule.dependencies', { defaultValue: 'Dependencies (predecessors)' })}
            </label>
            {candidatePredecessors.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('schedule.dependencies_none', {
                  defaultValue: 'Add at least one other activity first to link predecessors.',
                })}
              </p>
            ) : (
              <>
                {activityForm.dependencies.map((dep, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <select
                      aria-label={t('schedule.predecessor', { defaultValue: 'Predecessor' })}
                      value={dep.activity_id}
                      onChange={(e) =>
                        setActivityForm((f) => ({
                          ...f,
                          dependencies: f.dependencies.map((d, i) =>
                            i === idx ? { ...d, activity_id: e.target.value } : d,
                          ),
                        }))
                      }
                      className={`${FIELD_CLS} min-w-0 flex-1`}
                    >
                      <option value="">
                        {t('schedule.select_predecessor', { defaultValue: 'Select activity…' })}
                      </option>
                      {candidatePredecessors.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label={t('schedule.dependency_type', { defaultValue: 'Link type' })}
                      value={dep.type}
                      onChange={(e) =>
                        setActivityForm((f) => ({
                          ...f,
                          dependencies: f.dependencies.map((d, i) =>
                            i === idx ? { ...d, type: e.target.value as DependencyType } : d,
                          ),
                        }))
                      }
                      className={`${FIELD_CLS} w-20 shrink-0`}
                    >
                      {DEPENDENCY_TYPES.map((tp) => (
                        <option key={tp} value={tp}>
                          {tp}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      aria-label={t('schedule.lag_days', { defaultValue: 'Lag (days)' })}
                      title={t('schedule.lag_days', { defaultValue: 'Lag (days)' })}
                      value={dep.lag_days}
                      onChange={(e) =>
                        setActivityForm((f) => ({
                          ...f,
                          dependencies: f.dependencies.map((d, i) =>
                            i === idx ? { ...d, lag_days: Number(e.target.value) || 0 } : d,
                          ),
                        }))
                      }
                      className={`${FIELD_CLS} w-20 shrink-0`}
                    />
                    <button
                      type="button"
                      aria-label={t('schedule.remove_dependency', { defaultValue: 'Remove dependency' })}
                      onClick={() =>
                        setActivityForm((f) => ({
                          ...f,
                          dependencies: f.dependencies.filter((_, i) => i !== idx),
                        }))
                      }
                      className="shrink-0 rounded-lg border border-border p-2 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setActivityForm((f) => ({
                      ...f,
                      dependencies: [...f.dependencies, { activity_id: '', type: 'FS', lag_days: 0 }],
                    }))
                  }
                  className="self-start inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
                >
                  <Plus size={12} />
                  {t('schedule.add_dependency', { defaultValue: 'Add dependency' })}
                </button>
                <p className="text-2xs leading-relaxed text-content-tertiary">
                  {t('schedule.dependencies_hint', {
                    defaultValue:
                      'FS = Finish→Start, SS = Start→Start, FF = Finish→Finish, SF = Start→Finish. Lag in days (negative = lead).',
                  })}
                </p>
              </>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" type="button" onClick={closeActivityModal}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={saveActivity.isPending}>
              {editingActivityId
                ? t('schedule.save_activity', { defaultValue: 'Save changes' })
                : t('schedule.create_activity', 'Create Activity')}
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
  generateBoqId,
  onConsumeGenerateBoq,
}: {
  project: Project;
  onBack: () => void;
  /** CONN-34: BOQ id to pre-load into Generate-from-BOQ (deep link). */
  generateBoqId?: string | null;
  /** Called once the generate flow has consumed the deep-link BOQ id. */
  onConsumeGenerateBoq?: () => void;
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

  // CONN-34: when arriving via the BOQ "Build schedule from this BOQ" deep
  // link, drill straight to a schedule so the Generate-from-BOQ modal (which
  // lives in ScheduleDetail) can open with the BOQ pre-selected. If at least
  // one schedule exists, open the first; if none exist, open the Create modal
  // so the user makes one first — the param survives so generation continues
  // once the schedule is created and selected.
  const generateHandledRef = useRef(false);
  useEffect(() => {
    if (!generateBoqId || generateHandledRef.current) return;
    if (selectedSchedule) return;
    if (!schedules) return; // wait for the list to load
    generateHandledRef.current = true;
    if (schedules.length > 0) {
      setSelectedSchedule(schedules[0]!);
    } else {
      setShowCreate(true);
      addToast({
        type: 'info',
        title: t('schedule.create_before_generate', {
          defaultValue: 'Create a schedule first, then it generates from your BOQ.',
        }),
      });
    }
  }, [generateBoqId, schedules, selectedSchedule, addToast, t]);

  const createSchedule = useMutation({
    mutationFn: (data: CreateScheduleForm) =>
      scheduleApi.createSchedule({
        project_id: project.id,
        name: data.name,
        description: data.description || undefined,
        start_date: data.start_date || undefined,
        end_date: data.end_date || undefined,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['schedules', project.id] });
      setShowCreate(false);
      setForm({ name: '', description: '', start_date: '', end_date: '' });
      addToast({ type: 'success', title: t('toasts.schedule_created', { defaultValue: 'Schedule created' }) });
      // Continue the CONN-34 deep-link flow: drop into the freshly created
      // schedule so Generate-from-BOQ opens with the deep-link BOQ chosen.
      if (generateBoqId) setSelectedSchedule(created);
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
        generateBoqId={generateBoqId}
        onConsumeGenerateBoq={onConsumeGenerateBoq}
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
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
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
            required aria-required="true"
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

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer for the 4D Schedule: what it does and how it connects to
 * the rest of the platform. The plan is generated from a priced BOQ, resourced
 * with crews, sequenced with CPM, tracked against field progress and rolled up
 * into the portfolio - so every connected module is a link.
 */
function HowScheduleWorks() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <CalendarDays size={14} className="text-oe-blue" />,
      title: t('schedule.flow_1_title', { defaultValue: 'Create a schedule' }),
      desc: t('schedule.flow_1_desc', {
        defaultValue: 'Set up a programme for the project and give it a start date.',
      }),
    },
    {
      icon: <ListPlus size={14} className="text-oe-blue" />,
      title: t('schedule.flow_2_title', { defaultValue: 'Add or generate activities' }),
      desc: t('schedule.flow_2_desc', {
        defaultValue: 'Add activities by hand or generate them straight from a BOQ.',
      }),
    },
    {
      icon: <GitBranch size={14} className="text-oe-blue" />,
      title: t('schedule.flow_3_title', { defaultValue: 'Sequence & critical path' }),
      desc: t('schedule.flow_3_desc', {
        defaultValue: 'Link dependencies and run CPM to find the longest path and the float.',
      }),
    },
    {
      icon: <TrendingUp size={14} className="text-oe-blue" />,
      title: t('schedule.flow_4_title', { defaultValue: 'Track progress' }),
      desc: t('schedule.flow_4_desc', {
        defaultValue: 'Update percent complete as work happens and compare plan against actual.',
      }),
    },
    {
      icon: <Box size={14} className="text-oe-blue" />,
      title: t('schedule.flow_5_title', { defaultValue: 'Drive 4D on the model' }),
      desc: t('schedule.flow_5_desc', {
        defaultValue: 'Link activities to BIM elements to play back the build sequence in 4D.',
      }),
    },
  ];

  return (
    <Card padding="md">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Network size={15} className="text-oe-blue" />
        {t('schedule.flow_title', { defaultValue: 'How the 4D Schedule fits together' })}
      </h2>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('schedule.flow_intro', {
          defaultValue:
            'The schedule turns a priced estimate into a build timeline, then tracks it against what actually happens on site. This page is where that timeline is built.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('schedule.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/boq">{t('schedule.mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/resources">
            {t('schedule.mod_resources', { defaultValue: 'Resources & crew' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('schedule.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/field-reports">
            {t('schedule.mod_field', { defaultValue: 'Field reports' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/portfolio">
            {t('schedule.mod_portfolio', { defaultValue: 'Portfolio' })}
          </ModLink>
        </span>
      </div>
    </Card>
  );
}

export function SchedulePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { activeProjectId, setActiveProject } = useProjectContextStore();
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // CONN-34: deep link from a BOQ — /schedule?project_id=&generateBoqId=.
  // Pre-select the project so we drill straight into its schedules, and carry
  // the BOQ id down to ScheduleDetail which pre-opens Generate-from-BOQ with
  // that BOQ chosen. Consume project_id once projects resolve, then drop it so
  // a later project switch isn't fought by the URL. generateBoqId is cleared
  // by ScheduleDetail once the modal has opened.
  const generateBoqId = searchParams.get('generateBoqId');
  const projectIdParam = searchParams.get('project_id');
  useEffect(() => {
    if (!projectIdParam || !projects) return;
    const target = projects.find((p) => p.id === projectIdParam);
    if (target && activeProjectId !== projectIdParam) {
      setActiveProject(target.id, target.name);
    }
    // Drop project_id but keep generateBoqId for the detail view to consume.
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('project_id');
        return next;
      },
      { replace: true },
    );
  }, [projectIdParam, projects, activeProjectId, setActiveProject, setSearchParams]);

  const clearGenerateBoqParam = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('generateBoqId');
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const selectedProject = useMemo(
    () => projects?.find((p) => p.id === activeProjectId) ?? null,
    [projects, activeProjectId],
  );

  // Project schedule detail view
  if (selectedProject) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb items={[
          { label: selectedProject.name, to: `/projects/${selectedProject.id}` },
          { label: t('schedule.title', '4D Schedule') },
        ]} />

        <ProjectSchedules
          project={selectedProject}
          onBack={() => useProjectContextStore.getState().clearProject()}
          generateBoqId={generateBoqId}
          onConsumeGenerateBoq={clearGenerateBoqParam}
        />
      </div>
    );
  }

  // Project list view
  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[
        { label: t('schedule.title', '4D Schedule') },
      ]} />

      <PageHeader
        srTitle={t('schedule.title', '4D Schedule')}
        subtitle={t(
          'schedule.subtitle',
          'Plan the build timeline as a Gantt with dependencies and the critical path.',
        )}
        actions={<ModuleGuideButton content={scheduleGuide} />}
      />

      <DismissibleInfo
        storageKey="schedule"
        title={t('schedule.intro_title', {
          defaultValue: 'Build the plan straight from the estimate',
        })}
        more={
          t('schedule.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('schedule.intro_more')} />
            : undefined
        }
        links={[
          { label: t('schedule.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
          { label: t('schedule.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
          { label: t('schedule.intro_link_advanced', { defaultValue: 'Last Planner' }), onClick: () => navigate('/schedule-advanced') },
        ]}
      >
        {t('schedule.intro_body', {
          defaultValue:
            'Create a schedule, add activities by hand or generate them from a BOQ, and view the timeline as a Gantt with dependencies and the critical path. Run CPM to find the longest path and the float, and link activities to BIM elements to drive a 4D sequence on the model.',
        })}
      </DismissibleInfo>

      {/* Cross-module navigation — connects the planning value chain */}
      <PlanningCrossLinks active="schedule" />

      {/* How this module works + what it connects to */}
      <HowScheduleWorks />

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
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text font-bold">
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
                  {project.classification_standard === 'din276' ? 'DIN 276' : project.classification_standard?.toUpperCase() || '-'}
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

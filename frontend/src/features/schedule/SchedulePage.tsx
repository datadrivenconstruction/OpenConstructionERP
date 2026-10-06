// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Fragment, useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
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
  Box,
  GitBranch,
  TrendingUp,
  Layers,
  Table2,
  Network,
  ArrowRight,
  ListPlus,
  Trash2,
  PlayCircle,
  FileSpreadsheet,
} from 'lucide-react';
import { Button, Card, Badge, Input, SkeletonTable, Breadcrumb, DismissibleInfo, IntroRichText, GanttChart as SVGGanttChart, ViewInBIMButton, ConfirmDialog, ModuleGuideButton, CollapsibleSection } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import type { GanttActivity as SVGGanttActivity, GanttViewMode } from '@/shared/ui';
import type { GanttLinkType } from '@/shared/ui/Gantt';
import { scheduleErrorDetail, scheduleErrorMessage } from './errors';
import { useGanttLinking } from './useGanttLinking';
import { replaceInstalmentSentences } from './confirmations';
import { ScheduleLifecycleActions } from './ScheduleLifecycleActions';
import { ActivityDeleteDialog, activityDeleteTarget, type ActivityDeleteTarget } from './ActivityDeleteDialog';
import { GenerationPreviewPanel, isBudgetEstimate } from './GenerationPreviewPanel';
import { ApiError, apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { fmtDate, getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { scheduleApi, type GenerationPreview } from './api';
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
import { DependencyEditor } from './DependencyEditor';
import { MilestoneClientToggle } from './MilestoneClientToggle';
import { BoqLinkEditor } from './BoqLinkEditor';
import {
  generateInWindow,
  generationStamp,
  generationWarnings,
  generationWorkers,
  MAX_WORKERS_PER_POSITION,
  parseWorkers,
  previewInWindow,
  projectWindowDays,
  refreshAfterGenerate,
} from './generateWindow';
import { ActivityGrid } from './ActivityGrid';
import { ancestorsOf, hideCollapsed, orderAsTree, parentIdsOf } from './activityTree';
import { WorkCalendarManager } from './WorkCalendarManager';
import { ScheduleSpreadsheetImportDialog } from './tabularImport/ScheduleSpreadsheetImportDialog';
import { SpreadsheetImportEntry } from './tabularImport/SpreadsheetImportEntry';
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
  estimate_type?: string | null;
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
  parent_id?: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatDate(dateStr: string): string {
  return fmtDate(dateStr, { day: '2-digit', month: 'short', year: 'numeric' });
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
  const s = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(start) ? start + 'T00:00:00Z' : start);
  const e = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(end) ? end + 'T00:00:00Z' : end);
  if (isNaN(s) || isNaN(e)) return 1;
  return Math.max(1, Math.ceil((e - s) / (1000 * 60 * 60 * 24)));
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
        bg: 'bg-black/[0.06] dark:bg-white/10',
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

/**
 * Unreachable. The only render site is the final else of the viewMode chain
 * below, and every member of that union is already matched by an earlier
 * branch, so this never draws. The chart users actually see is SVGGanttChart
 * from shared/ui/Gantt.
 *
 * Flagged rather than deleted because the label-collision handling here
 * (MIN_GAP_PCT) reads like the live implementation and is not: the real one
 * clips each header label to its own cell instead. Removal is queued
 * separately.
 */
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

    const parseDate = (s: string) => Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(s) ? s + 'T00:00:00Z' : s);
    const starts = activities.map((a) => parseDate(a.start_date)).filter((t) => !isNaN(t));
    const ends = activities.map((a) => parseDate(a.end_date)).filter((t) => !isNaN(t));
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

    // Add padding of 2 days on each side — use UTC methods so the day
    // arithmetic is not shifted by the browser's local timezone offset.
    minStart.setUTCDate(minStart.getUTCDate() - 2);
    maxEnd.setUTCDate(maxEnd.getUTCDate() + 2);

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

    // All date arithmetic below uses UTC methods so the timeline stays
    // day-stable regardless of the viewer's local timezone offset.
    const utcDateOpts = { timeZone: 'UTC' as const };

    if (zoomLevel === 'day') {
      // One marker per day
      current.setUTCDate(current.getUTCDate() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.toLocaleDateString(getIntlLocale(), { day: '2-digit', month: 'short', ...utcDateOpts }),
            offsetPct: pct,
          });
        }
        current.setUTCDate(current.getUTCDate() + 1);
      }
    } else if (zoomLevel === 'week') {
      // One marker per week (advance to next Monday). Monday is deliberate
      // and stays independent of the reader's locale, for the same reason as
      // the ISO week columns in `Gantt/ganttUtils`: these gridlines sit under
      // a programme whose weeks are ISO weeks, and rotating them per language
      // would put the same task in two different weeks for two readers.
      const dayOfWeek = current.getUTCDay();
      const daysUntilMonday = dayOfWeek === 0 ? 1 : 8 - dayOfWeek;
      current.setUTCDate(current.getUTCDate() + daysUntilMonday);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.toLocaleDateString(getIntlLocale(), {
              day: '2-digit',
              month: 'short',
              ...utcDateOpts,
            }),
            offsetPct: pct,
          });
        }
        current.setUTCDate(current.getUTCDate() + 7);
      }
    } else if (zoomLevel === 'month') {
      // Month view — one marker per month
      current.setUTCDate(1);
      current.setUTCMonth(current.getUTCMonth() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            // Four digits, not two. The month markers are the only place on
            // this axis where a year is written at all, and a programme that
            // runs from 2026 into 2028 is exactly the one where "Aug 26" has
            // to be read twice - the first reading is a day of the month.
            label: current.toLocaleDateString(getIntlLocale(), { month: 'short', year: 'numeric', ...utcDateOpts }),
            offsetPct: pct,
          });
        }
        current.setUTCMonth(current.getUTCMonth() + 1);
      }
    } else if (zoomLevel === 'quarter') {
      // Quarter view — one marker per quarter
      current.setUTCDate(1);
      current.setUTCMonth(Math.floor(current.getUTCMonth() / 3) * 3 + 3);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          const q = Math.floor(current.getUTCMonth() / 3) + 1;
          markers.push({
            label: `Q${q} ${current.getUTCFullYear()}`,
            offsetPct: pct,
          });
        }
        current.setUTCMonth(current.getUTCMonth() + 3);
      }
    } else {
      // Year view — one marker per year
      current.setUTCDate(1);
      current.setUTCMonth(0);
      current.setUTCFullYear(current.getUTCFullYear() + 1);
      while (current <= timelineEnd) {
        const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
        const pct = (dayOffset / totalDays) * 100;
        if (pct >= 0 && pct <= 100) {
          markers.push({
            label: current.getUTCFullYear().toString(),
            offsetPct: pct,
          });
        }
        current.setUTCFullYear(current.getUTCFullYear() + 1);
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
                        className="absolute top-0 bottom-0 w-px bg-border-light"
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

/** Exported for the page-level tests of the Table and Gantt views. */
export function ScheduleDetail({
  schedule,
  projectId,
  onBack,
  generateBoqId,
  onConsumeGenerateBoq,
  onOpenSchedule,
}: {
  schedule: Schedule;
  projectId: string;
  onBack: () => void;
  /** CONN-34: BOQ id to pre-load into Generate-from-BOQ (deep link). */
  generateBoqId?: string | null;
  /** Called once the generate modal has consumed the deep-link BOQ id. */
  onConsumeGenerateBoq?: () => void;
  /**
   * Switch the page to another schedule of the project. Without it the
   * "generate into a new schedule" choice is not offered.
   */
  onOpenSchedule?: (schedule: Schedule) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  // A generation the server refused because the schedule already has
  // activities: the reader chooses to replace them or to use a new schedule.
  const [generateConflict, setGenerateConflict] = useState<{
    boqId: string;
    activityCount: number;
    startedCount: number;
    instalmentsRelinked: number;
    instalmentsUnlinked: number;
  } | null>(null);
  // The generation run whose warnings the reader dismissed.
  const [dismissedStamp, setDismissedStamp] = useState<string | null>(null);
  // What the generation would write, shown for the reader to confirm.
  const [generationPreview, setGenerationPreview] = useState<GenerationPreview | null>(null);
  // The activity whose delete is being confirmed.
  const [deleteTarget, setDeleteTarget] = useState<ActivityDeleteTarget | null>(null);
  // A viewer sees the plan but none of the buttons the server would refuse.
  const canEditSchedule = useHasPermission('schedule.update');
  const canDeleteSchedule = useHasPermission('schedule.delete');
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>('week');
  const [viewMode, setViewMode] = useState<
    'table' | 'gantt' | 'evm' | '4d' | 'quality' | 'risk' | 'compare' | 'progress' | 'delay' | 'codes' | 'calendars' | 'resources' | 'realtime' | 'interchange'
  >('gantt');
  const [showAddActivity, setShowAddActivity] = useState(false);
  const [showBaseline, setShowBaseline] = useState(false);
  // #348: activity whose dependency editor is open (click a Gantt bar to edit).
  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(null);
  const [showGenerateBOQ, setShowGenerateBOQ] = useState(false);
  const [selectedBOQId, setSelectedBOQId] = useState('');
  const [generateStartDate, setGenerateStartDate] = useState(
    () => schedule.start_date?.slice(0, 10) || new Date().toISOString().slice(0, 10),
  );
  const [generateEndDate, setGenerateEndDate] = useState('');
  const generateWindowDays = projectWindowDays(generateStartDate, generateEndDate);
  // An end date is optional; one that is given has to come after the start.
  const generateWindowInvalid = generateEndDate !== '' && generateWindowDays == null;
  // Workers per position where the bill gives no crew. Empty asks the server
  // for the fewest that fit the dates; a number is sent as it is.
  const [generateWorkers, setGenerateWorkers] = useState('');
  const generateWorkersValue = parseWorkers(generateWorkers);
  const generateWorkersInvalid = generateWorkers.trim() !== '' && generateWorkersValue == null;
  // A preview answers for one bill, one pair of dates and one number of
  // workers; any change asks again.
  useEffect(() => {
    setGenerationPreview(null);
  }, [selectedBOQId, generateStartDate, generateEndDate, generateWorkers]);
  const [activityFilter, setActivityFilter] = useState('all');
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);
  const [activityForm, setActivityForm] = useState<CreateActivityForm>({
    name: '',
    wbs_code: '',
    start_date: '',
    end_date: '',
    activity_type: 'task',
  });
  // Set once the user types a WBS code of their own, so choosing a section
  // afterwards does not overwrite it with the suggested one.
  const wbsTouchedRef = useRef(false);
  // A WBS code the server refused as already used, shown next to the field.
  const [wbsError, setWbsError] = useState<string | null>(null);
  const chooseParentSection = useCallback(
    (parentId: string | undefined) => {
      setActivityForm((f) => ({ ...f, parent_id: parentId }));
      setWbsError(null);
      if (wbsTouchedRef.current) return;
      scheduleApi
        .suggestWbsCode(schedule.id, parentId)
        .then(({ wbs_code }) => {
          if (wbsTouchedRef.current) return;
          // A late answer for a section the user has since changed is dropped.
          setActivityForm((f) => (f.parent_id === parentId ? { ...f, wbs_code } : f));
        })
        .catch(() => {
          // No suggestion; the field stays editable and the server fills a
          // blank code under a section on its own.
        });
    },
    [schedule.id],
  );

  // Fetch project data for region / work calendar / currency
  const { data: projectData } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () =>
      apiGet<{
        id: string;
        region: string;
        currency?: string;
        planned_start_date?: string | null;
        planned_end_date?: string | null;
      }>(`/v1/projects/${projectId}`),
    staleTime: 300_000,
  });
  // The generate dialog fits the plan between the project's planned dates.
  // They are filled in once, when the project first arrives, the start only
  // when the schedule has none of its own, so a later refetch never overwrites
  // a date the planner typed. The schedule's own end
  // date is not used: generation writes it, so it would feed a previous run's
  // result back in as the window.
  const plannedDatesAppliedRef = useRef(false);
  useEffect(() => {
    if (!projectData || plannedDatesAppliedRef.current) return;
    plannedDatesAppliedRef.current = true;
    const plannedStart = projectData.planned_start_date?.slice(0, 10);
    const plannedEnd = projectData.planned_end_date?.slice(0, 10);
    if (plannedStart && !schedule.start_date) setGenerateStartDate(plannedStart);
    if (plannedEnd) setGenerateEndDate((cur) => cur || plannedEnd);
  }, [projectData, schedule.start_date]);
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

  // The schedule as stored now: the prop is the list row it was opened from,
  // and generation writes its outcome (and any warning) onto the record.
  const { data: scheduleRecord } = useQuery({
    queryKey: ['schedule-record', schedule.id],
    queryFn: () => scheduleApi.getSchedule(schedule.id),
  });
  const planWarnings = generationWarnings(scheduleRecord);
  // Generating again starts from the workers the last generation was asked
  // for, once per opening of the dialog, so the same plan comes back.
  const workersPrefilledRef = useRef(false);
  useEffect(() => {
    if (!showGenerateBOQ) {
      workersPrefilledRef.current = false;
      return;
    }
    if (workersPrefilledRef.current) return;
    const recorded = generationWorkers(scheduleRecord);
    if (recorded == null) return;
    workersPrefilledRef.current = true;
    setGenerateWorkers((cur) => cur || String(recorded));
  }, [showGenerateBOQ, scheduleRecord]);
  const planStamp = generationStamp(scheduleRecord);
  const showPlanWarnings = planWarnings.length > 0 && dismissedStamp !== planStamp;

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
    if (canEditSchedule) {
      setSelectedBOQId(generateBoqId);
      setShowGenerateBOQ(true);
    }
    onConsumeGenerateBoq?.();
  }, [generateBoqId, onConsumeGenerateBoq, canEditSchedule]);

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
        ...(data.parent_id ? { parent_id: data.parent_id } : {}),
      }),
    onSuccess: (_created, data) => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      // Open the section the activity went into (and every section above
      // it), or the new row would be created out of sight.
      if (data.parent_id) {
        const open = ancestorsOf(data.parent_id, ganttData?.activities ?? []);
        setCollapsedIds((prev) => {
          if (!open.some((id) => prev.has(id))) return prev;
          const next = new Set(prev);
          for (const id of open) next.delete(id);
          return next;
        });
      }
      wbsTouchedRef.current = false;
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
    onError: (error: Error, data) => {
      // A code another activity already uses is the user's to fix in the
      // field, so it is said there, in their language, not in a toast.
      if (error instanceof ApiError && error.status === 409) {
        setWbsError(wbsTakenMessage(data.wbs_code));
        return;
      }
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });
  const wbsTakenMessage = (code: string) =>
    t('schedule.wbs_code_taken', {
      defaultValue: 'WBS code {{code}} is already used by another activity in this schedule.',
      code: code.trim(),
    });

  // Opening the dialog suggests the next code for the section it is set to
  // (the top level when none), as long as the user has not typed their own.
  useEffect(() => {
    if (showAddActivity && !wbsTouchedRef.current && !activityForm.wbs_code) {
      chooseParentSection(activityForm.parent_id);
    }
    // Only on opening; later section changes go through chooseParentSection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAddActivity]);

  const generateFailed = (error: unknown) =>
    addToast({
      type: 'error',
      title: t('schedule.generate_failed_title', { defaultValue: 'The schedule was not generated' }),
      message: scheduleErrorMessage(error, t),
    });

  // Generate writes the plan the preview showed: with the workers it
  // reported, even when the server chose them.
  const workersToWrite = generationPreview?.workers_per_position ?? generateWorkersValue;

  const generateFromBOQ = useMutation({
    mutationFn: ({ boqId, replace }: { boqId: string; replace: boolean }) =>
      generateInWindow(schedule.id, boqId, generateStartDate, generateEndDate, replace, workersToWrite),
    onSuccess: async () => {
      // The dialog stays open with its button spinning until the new plan is
      // loaded, so the toast lands on the generated schedule and not on the
      // empty one it replaces.
      await refreshAfterGenerate(queryClient, schedule.id);
      setShowGenerateBOQ(false);
      setGenerateConflict(null);
      setGenerationPreview(null);
      setSelectedBOQId('');
      // Reset CPM/risk results since activities changed
      setCpmResult(null);
      setRiskResult(null);
      addToast({ type: 'success', title: t('toasts.schedule_generated', { defaultValue: 'Schedule generated from BOQ' }) });
    },
    onError: (error: Error, { boqId, replace }) => {
      // A populated schedule is not overwritten unasked: the server refuses
      // and the reader chooses what happens to the activities already there.
      const detail = scheduleErrorDetail(error);
      if (detail?.error === 'schedule_has_activities' && !replace) {
        setShowGenerateBOQ(false);
        setGenerateConflict({
          boqId,
          activityCount: Number(detail.activity_count ?? 0),
          startedCount: Number(detail.started_count ?? 0),
          instalmentsRelinked: Number(detail.instalments_relinked ?? 0),
          instalmentsUnlinked: Number(detail.instalments_unlinked ?? 0),
        });
        return;
      }
      generateFailed(error);
    },
  });

  // Nothing is written until the reader has seen what would be: the counts,
  // the dates against the window and the positions whose durations are guesses.
  const previewGeneration = useMutation({
    mutationFn: (boqId: string) =>
      previewInWindow(schedule.id, boqId, generateStartDate, generateEndDate, generateWorkersValue),
    onSuccess: (preview) => setGenerationPreview(preview),
    onError: (error: Error) => generateFailed(error),
  });

  // The other answer to a populated schedule: leave it as it is and generate
  // into a new schedule of the same project, then open that one.
  const generateIntoNewSchedule = useMutation({
    mutationFn: async (boqId: string) => {
      const created = await scheduleApi.createSchedule({
        project_id: projectId,
        name: t('schedule.new_schedule_from_boq_name', { defaultValue: '{{name}} (new)', name: schedule.name }),
        start_date: generateStartDate || undefined,
      });
      try {
        await generateInWindow(created.id, boqId, generateStartDate, generateEndDate, false, workersToWrite);
      } catch (error) {
        // Retain the failed attempt in the archive; never silently purge it.
        try {
          await scheduleApi.archiveSchedule(created.id);
          addToast({ type: 'info', title: t('schedule.generation_cleanup_archived') });
        } catch {
          addToast({ type: 'warning', title: t('schedule.generation_cleanup_failed') });
        }
        await queryClient.invalidateQueries({ queryKey: ['schedules'] });
        throw error;
      }
      return created;
    },
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      setGenerateConflict(null);
      setShowGenerateBOQ(false);
      setGenerationPreview(null);
      setSelectedBOQId('');
      addToast({
        type: 'success',
        title: t('toasts.schedule_generated', { defaultValue: 'Schedule generated from BOQ' }),
        message: t('schedule.generated_into_new_schedule', {
          defaultValue: 'The plan is in the new schedule "{{name}}". The schedule you were on is unchanged.',
          name: created.name,
        }),
      });
      onOpenSchedule?.(created);
    },
    onError: (error: Error) => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      generateFailed(error);
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

  // Drawing and removing links on the Gantt (only for people who may edit the schedule).
  const ganttLinking = useGanttLinking(schedule.id, canEditSchedule);

  const resetSchedule = useMutation({
    mutationFn: () => scheduleApi.clearActivities(schedule.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      setCpmResult(null);
      setRiskResult(null);
      setActivityFilter('all');
      addToast({ type: 'success', title: t('schedule.clear_all_success', { defaultValue: 'All activities deleted' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: scheduleErrorMessage(error, t) });
    },
  });

  // Deleting from the side panel. A section asks whether its activities go
  // with it or stay, moving up to the section's own parent.
  const deleteActivity = useMutation({
    mutationFn: ({ activityId, cascade }: { activityId: string; cascade: boolean }) =>
      scheduleApi.deleteActivity(activityId, cascade),
    onSuccess: () => {
      setDeleteTarget(null);
      setSelectedActivityId(null);
      setCpmResult(null);
      setRiskResult(null);
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      queryClient.invalidateQueries({ queryKey: ['schedule-relationships', schedule.id] });
      addToast({ type: 'success', title: t('schedule.activity_deleted', { defaultValue: 'Activity deleted' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: scheduleErrorMessage(error, t) });
    },
  });
  const handleDeleteActivity = (activity: Activity) => {
    setDeleteTarget(activityDeleteTarget(activity, ganttData?.activities ?? []));
  };

  const activateSchedule = useMutation({
    mutationFn: () => scheduleApi.updateSchedule(schedule.id, { status: 'active' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      addToast({ type: 'success', title: t('schedule.activated', { defaultValue: 'Schedule activated' }) });
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

  // #348: the activity object backing the open dependency editor (or null).
  const selectedActivity = useMemo(
    () => ganttData?.activities.find((a) => a.id === selectedActivityId) ?? null,
    [ganttData, selectedActivityId],
  );

  // Filtered activities for the Gantt chart (Improvement #5)
  const filteredActivities = useMemo(() => {
    let activities = ganttData?.activities ?? [];
    if (activityFilter === 'critical') {
      activities = activities.filter((a) => criticalActivityIds?.has(a.id));
    } else if (activityFilter === 'delayed') {
      activities = activities.filter((a) => a.status === 'delayed');
    } else if (activityFilter === 'in_progress') {
      activities = activities.filter((a) => a.status === 'in_progress');
    }
    // Every child directly under its section, whatever its place in the
    // flat server order.
    return orderAsTree(activities);
  }, [ganttData, activityFilter, criticalActivityIds]);

  // Collapsing is a Table view control, so only the table hides the rows
  // under a collapsed section; the Gantt views have no toggle to reopen it.
  const gridActivities = useMemo(
    () => hideCollapsed(filteredActivities, collapsedIds),
    [filteredActivities, collapsedIds],
  );
  // Which rows can collapse is read from the whole schedule. Reading it from
  // the rows left visible lost a collapsed section's chevron with its children.
  const sectionIds = useMemo(() => parentIdsOf(ganttData?.activities ?? []), [ganttData]);

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
      // So the chart anchors each arrow by its type; an unknown type is left
      // out and drawn as FS.
      dependencyTypes: Object.fromEntries(
        (a.dependencies ?? [])
          .filter((d) => ['FS', 'SS', 'FF', 'SF'].includes(d.type))
          .map((d) => [d.activity_id, d.type as GanttLinkType]),
      ),
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
          {canEditSchedule && (
            <Button
              variant="secondary"
              icon={<FileBarChart size={16} />}
              onClick={() => setShowGenerateBOQ(true)}
              data-guide="schedule-generate"
            >
              {hasActivities
                ? t('schedule.regenerate_from_boq', { defaultValue: 'Regenerate from BOQ' })
                : t('schedule.generate_from_boq', 'Generate from BOQ')}
            </Button>
          )}
          {/* Clear all activities, next to Regenerate: the schedule itself stays */}
          {hasActivities && canDeleteSchedule && (
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw size={14} />}
              onClick={async () => {
                const ok = await confirm({
                  title: t('schedule.confirm_clear_all_title', { defaultValue: 'Clear all activities?' }),
                  message: t('schedule.confirm_clear_all', {
                    defaultValue:
                      'Delete all {{count}} activities of this schedule and the links between them? The schedule itself stays, and you can generate it again from a BOQ. This cannot be undone.',
                    count: ganttData?.summary.total_activities ?? 0,
                  }),
                  confirmLabel: t('schedule.clear_all', { defaultValue: 'Clear all' }),
                });
                if (ok) resetSchedule.mutate();
              }}
              loading={resetSchedule.isPending}
            >
              {t('schedule.clear_all_activities', { defaultValue: 'Clear all activities' })}
            </Button>
          )}
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
                  { key: 'calendars' as const, label: t('schedule.calendar.view', { defaultValue: 'Calendars' }) },
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
              {/* Zoom only applies to the Gantt timeline; the Table view is a
                  data grid with no timescale, so hide the zoom control there. */}
              <div
                className={`flex items-center gap-1 rounded-lg border border-border-light p-0.5 ${
                  viewMode !== 'gantt' ? 'hidden' : ''
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
              <button
                type="button"
                aria-pressed={showBaseline}
                onClick={() => setShowBaseline((v) => !v)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  showBaseline
                    ? 'bg-oe-blue text-white'
                    : 'text-content-secondary hover:bg-surface-secondary'
                }`}
                title={t('schedule.baseline_tooltip', { defaultValue: 'Toggle baseline comparison overlay' })}
              >
                {t('schedule.baseline', { defaultValue: 'Baseline' })}
              </button>
              <Button
                variant="secondary"
                icon={<Zap size={16} />}
                onClick={() => calculateCPM.mutate()}
                loading={calculateCPM.isPending}
                title={t('schedule.cpm_tooltip', { defaultValue: 'Critical Path Method calculates the longest path through the project and identifies activities that cannot be delayed' })}
                data-guide="schedule-cpm"
              >
                {t('schedule.calculate_cpm', 'Critical Path')}
              </Button>
              <Button
                variant="secondary"
                icon={<ShieldAlert size={16} />}
                onClick={() => fetchRiskAnalysis.mutate()}
                loading={fetchRiskAnalysis.isPending}
                data-guide="schedule-risk"
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
            </>
          )}
          {schedule.status === 'draft' && (
            <Button
              variant="secondary"
              size="sm"
              icon={<PlayCircle size={14} />}
              onClick={() => activateSchedule.mutate()}
              loading={activateSchedule.isPending}
            >
              {t('schedule.activate', { defaultValue: 'Activate' })}
            </Button>
          )}
          <ScheduleLifecycleActions schedule={{ ...schedule, ...scheduleRecord }} onChanged={onBack} />
          {canEditSchedule && (
            <Button
              variant="primary"
              icon={<Plus size={16} />}
              onClick={() => setShowAddActivity(true)}
            >
              {t('schedule.add_activity', 'Add Activity')}
            </Button>
          )}
        </div>
      </div>

      {/* What the last generation could not do as asked. It stays until the
          reader dismisses it, because the dates on screen alone do not say
          that the plan overran the window or that durations were cut. */}
      {showPlanWarnings && (
        <div
          role="status"
          data-testid="generation-warning"
          className="mb-4 flex items-start gap-3 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg px-4 py-3"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
          <div className="min-w-0 flex-1 space-y-1 text-sm text-content-primary">
            {planWarnings.map((w) =>
              w.code === 'plan_exceeds_window' ? (
                <p key={w.code}>
                  {t('schedule.warning_plan_exceeds_window', {
                    defaultValue:
                      'The plan does not fit the dates you asked for: it ends on {{planned}}, you asked for {{requested}}. Four crews work side by side and every duration is already cut to half of its estimate, the shortest a plan is squeezed to. Move the end date, or shorten the plan by hand.',
                    planned: formatDate(w.planned_end),
                    requested: formatDate(w.requested_end),
                  })}
                </p>
              ) : (
                <p key={w.code}>
                  {t('schedule.warning_durations_shortened', {
                    defaultValue:
                      'To fit the dates you asked for, every duration was shortened to {{percent}}% of its estimate. Check that the crews can keep that pace.',
                    percent: w.percent,
                  })}
                </p>
              ),
            )}
          </div>
          <button
            type="button"
            onClick={() => setDismissedStamp(planStamp)}
            className="shrink-0 rounded-md px-2 py-0.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
          >
            {t('common.dismiss', { defaultValue: 'Dismiss' })}
          </button>
        </div>
      )}

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
              <div className="space-y-4">
                <SpreadsheetImportEntry projectId={projectId} schedule={schedule} variant="card" />
                <ScheduleInterchangePanel scheduleId={schedule.id} projectId={projectId} />
              </div>
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
            ) : viewMode === 'calendars' ? (
              <WorkCalendarManager projectId={projectId} />
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
                  showBaseline={showBaseline}
                  showDependencies={true}
                  showCriticalPath={!!cpmResult}
                  todayLine={true}
                  onActivityResize={handleActivityResize}
                  onCreateLink={ganttLinking.onCreateLink}
                  onDeleteLink={ganttLinking.onDeleteLink}
                  onActivityClick={(id) => setSelectedActivityId(id)}
                />
              ) : viewMode === 'table' ? (
                <ActivityGrid
                  scheduleId={schedule.id}
                  projectId={projectId}
                  activities={gridActivities}
                  criticalActivityIds={criticalActivityIds}
                  onEditDependencies={(id) => setSelectedActivityId(id)}
                  onAddActivity={() => setShowAddActivity(true)}
                  sectionIds={sectionIds}
                  allActivities={ganttData?.activities}
                  collapsedIds={collapsedIds}
                  onToggleCollapse={toggleCollapse}
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
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-2xl">
                  <button
                    disabled={!canEditSchedule}
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
                    disabled={!canEditSchedule}
                    onClick={() => setShowAddActivity(true)}
                    className="group flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border-light bg-surface-secondary/30 p-6 transition-all hover:border-oe-blue/50 hover:bg-oe-blue-subtle/30 disabled:cursor-not-allowed disabled:opacity-50"
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
                  <SpreadsheetImportEntry projectId={projectId} schedule={schedule} variant="tile" />
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
            const code = activityForm.wbs_code.trim();
            if (code && (ganttData?.activities ?? []).some((a) => (a.wbs_code ?? '').trim() === code)) {
              setWbsError(wbsTakenMessage(code));
              return;
            }
            addActivity.mutate(activityForm);
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
          {/* Parent section - insert under a summary */}
          {(() => {
            const summaries = orderAsTree(ganttData?.activities ?? []).filter((a) => a.activity_type === 'summary');
            if (summaries.length === 0) return null;
            return (
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-content-primary">
                  {t('schedule.parent_section', { defaultValue: 'Parent section' })}
                </label>
                <select
                  className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                  value={activityForm.parent_id ?? ''}
                  onChange={(e) => chooseParentSection(e.target.value || undefined)}
                >
                  <option value="">{t('schedule.no_parent', { defaultValue: 'Top level (no parent)' })}</option>
                  {summaries.map((s) => (
                    <option key={s.id} value={s.id}>{s.wbs_code ? `${s.wbs_code} ${s.name}` : s.name}</option>
                  ))}
                </select>
              </div>
            );
          })()}
          <Input
            label={t('schedule.wbs_code', 'WBS Code')}
            placeholder={t('schedule.wbs_code_placeholder', 'e.g. 01.02.003')}
            value={activityForm.wbs_code}
            onChange={(e) => {
              wbsTouchedRef.current = e.target.value.trim() !== '';
              setWbsError(null);
              setActivityForm((f) => ({ ...f, wbs_code: e.target.value }));
            }}
            error={wbsError ?? undefined}
            hint={
              activityForm.parent_id && !wbsTouchedRef.current
                ? t('schedule.wbs_code_suggested_hint', {
                    defaultValue: 'Continues the numbering of the chosen section. You can change it.',
                  })
                : undefined
            }
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

      {/* Edit dependencies Modal (#348) - opens when a Gantt bar is clicked */}
      <Modal
        open={!!selectedActivity}
        onClose={() => setSelectedActivityId(null)}
        title={t('schedule.edit_activity_links', { defaultValue: 'Dependencies and BOQ links' })}
      >
        {selectedActivity && (
          <div className="space-y-4">
            <div>
              <p className="text-sm font-semibold text-content-primary">{selectedActivity.name}</p>
              <p className="text-xs text-content-tertiary">
                {formatDate(selectedActivity.start_date)} &ndash; {formatDate(selectedActivity.end_date)}
              </p>
            </div>
            {selectedActivity.activity_type === 'milestone' && (
              <MilestoneClientToggle scheduleId={schedule.id} activity={selectedActivity} />
            )}
            <DependencyEditor
              scheduleId={schedule.id}
              activity={selectedActivity}
              activities={ganttData?.activities ?? []}
            />
            <div className="border-t border-border-light pt-4">
              <BoqLinkEditor scheduleId={schedule.id} projectId={projectId} activity={selectedActivity} />
            </div>
            <div className="flex items-center justify-between pt-1">
              {canDeleteSchedule ? (
                <Button
                  variant="ghost"
                  type="button"
                  icon={<Trash2 size={14} />}
                  onClick={() => handleDeleteActivity(selectedActivity)}
                  loading={deleteActivity.isPending}
                  className="text-semantic-error"
                >
                  {t('schedule.delete_activity', { defaultValue: 'Delete activity' })}
                </Button>
              ) : (
                <span />
              )}
              <Button variant="ghost" type="button" onClick={() => setSelectedActivityId(null)}>
                {t('common.done', { defaultValue: 'Done' })}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Generate from BOQ Modal */}
      <Modal
        open={showGenerateBOQ}
        onClose={() => setShowGenerateBOQ(false)}
        title={
          hasActivities
            ? t('schedule.regenerate_from_boq', { defaultValue: 'Regenerate from BOQ' })
            : t('schedule.generate_from_boq', 'Generate from BOQ')
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-content-secondary">
            {t('schedule.generate_from_boq_tree_description', {
              defaultValue:
                'Select a BOQ. Every section becomes a summary and every position with a quantity one activity, sized from its labour, else from its unit with a gang of two to four people, else from its cost. Within a section up to four crews work side by side, and each next section starts once half of the work before it is done. You see the plan before anything is written.',
            })}
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

          {/* End date: the generated plan is fitted between the two dates. */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('schedule.project_end_date', { defaultValue: 'Project End Date' })}
            </label>
            <input
              type="date"
              data-testid="generate-end-date"
              value={generateEndDate}
              min={generateStartDate || undefined}
              onChange={(e) => setGenerateEndDate(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {!generateEndDate
                ? t('schedule.end_date_optional', {
                    defaultValue:
                      'No end date: the plan takes as long as the work needs and nothing is shortened. Enter one to fit the plan between the two dates.',
                  })
                : generateWindowDays == null
                  ? t('schedule.end_before_start', { defaultValue: 'The end date must be after the start date.' })
                  : t('schedule.end_date_hint', { defaultValue: 'The generated plan is fitted between these two dates.' })}
            </p>
          </div>

          {/* Workers: what a bill of hours without crews is worked by. */}
          <div>
            <label
              htmlFor="generate-workers"
              className="block text-sm font-medium text-content-primary mb-1.5"
            >
              {t('schedule.generate_workers_label', { defaultValue: 'Workers per position' })}
            </label>
            <input
              id="generate-workers"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_WORKERS_PER_POSITION}
              step={1}
              data-testid="generate-workers"
              value={generateWorkers}
              placeholder={t('schedule.generate_workers_auto', { defaultValue: 'Auto' })}
              onChange={(e) => setGenerateWorkers(e.target.value)}
              aria-invalid={generateWorkersInvalid || undefined}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {generateWorkersInvalid
                ? t('schedule.generate_workers_invalid', { defaultValue: 'Enter a whole number from 1 to 20.' })
                : t('schedule.generate_workers_hint', {
                    defaultValue:
                      'For positions whose bill gives hours but no crew. Leave it empty to use the fewest that fit the dates. A crew the bill names is kept.',
                  })}
            </p>
          </div>

          {!boqs || boqs.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('schedule.no_boqs_available', 'No BOQs available for this project.')}
            </p>
          ) : (
            <div className="space-y-2">
              {[...boqs]
                .sort((a, b) => Number(isBudgetEstimate(a.estimate_type)) - Number(isBudgetEstimate(b.estimate_type)))
                .map((boq) => (
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
                  {isBudgetEstimate(boq.estimate_type) && (
                    <Badge variant="warning" size="sm" className="mt-1 ml-1">
                      {t('schedule.boq_budget_badge', {
                        defaultValue: 'Budget estimate: one bar per lump sum',
                      })}
                    </Badge>
                  )}
                </button>
              ))}
            </div>
          )}
          {generationPreview && <GenerationPreviewPanel preview={generationPreview} />}
          {generationPreview && generationPreview.existing_activity_count > 0 && (
            <div className="space-y-1 text-sm">
              <p className="text-content-primary">
                {t('schedule.error_schedule_has_activities', {
                  defaultValue: 'This schedule already has {{count}} activities.',
                  count: generationPreview.existing_activity_count,
                })}{' '}
                {t('schedule.generate_conflict_replace_hint', {
                  defaultValue:
                    'Replacing them deletes them and their links, then builds the plan again from the BOQ. A new schedule leaves this one as it is.',
                })}
              </p>
              {generationPreview.existing_started_count > 0 && (
                <p className="flex items-start gap-2 text-semantic-warning">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  {t('schedule.generate_conflict_started', {
                    defaultValue: '{{count}} of them have progress recorded. Replacing them loses that progress.',
                    count: generationPreview.existing_started_count,
                  })}
                </p>
              )}
              {replaceInstalmentSentences(
                t,
                generationPreview.instalments_relinked,
                generationPreview.instalments_unlinked,
              ).map((line) => (
                <p key={line} className="text-content-secondary" data-testid="replace-instalments">
                  {line}
                </p>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowGenerateBOQ(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            {!generationPreview ? (
              <Button
                variant="primary"
                data-testid="generate-preview"
                disabled={!selectedBOQId || generateWindowInvalid || generateWorkersInvalid}
                loading={previewGeneration.isPending}
                onClick={() => {
                  if (selectedBOQId) previewGeneration.mutate(selectedBOQId);
                }}
              >
                {t('schedule.generate_preview', { defaultValue: 'Check the plan' })}
              </Button>
            ) : generationPreview.existing_activity_count > 0 ? (
              <>
                {onOpenSchedule && (
                  <Button
                    variant="secondary"
                    type="button"
                    loading={generateIntoNewSchedule.isPending}
                    disabled={generateFromBOQ.isPending}
                    onClick={() => generateIntoNewSchedule.mutate(generationPreview.boq_id)}
                  >
                    {t('schedule.generate_conflict_new_schedule', { defaultValue: 'Create a new schedule' })}
                  </Button>
                )}
                <Button
                  variant="danger"
                  type="button"
                  data-testid="generate-replace"
                  loading={generateFromBOQ.isPending}
                  disabled={generateIntoNewSchedule.isPending}
                  onClick={() => generateFromBOQ.mutate({ boqId: generationPreview.boq_id, replace: true })}
                >
                  {t('schedule.generate_replace_and_create', { defaultValue: 'Replace them and create the plan' })}
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                data-testid="generate-create"
                loading={generateFromBOQ.isPending}
                onClick={() => generateFromBOQ.mutate({ boqId: generationPreview.boq_id, replace: false })}
              >
                {t('schedule.generate_create', { defaultValue: 'Create the plan' })}
              </Button>
            )}
          </div>
        </div>
      </Modal>

      {/* The schedule already has activities: replace them, or generate into a new schedule */}
      <Modal
        open={!!generateConflict}
        onClose={() => setGenerateConflict(null)}
        title={t('schedule.generate_conflict_title', { defaultValue: 'This schedule already has activities' })}
      >
        {generateConflict && (
          <div className="space-y-4">
            <p className="text-sm text-content-primary">
              {t('schedule.error_schedule_has_activities', {
                defaultValue: 'This schedule already has {{count}} activities.',
                count: generateConflict.activityCount,
              })}{' '}
              {t('schedule.generate_conflict_replace_hint', {
                defaultValue:
                  'Replacing them deletes them and their links, then builds the plan again from the BOQ. A new schedule leaves this one as it is.',
              })}
            </p>
            {generateConflict.startedCount > 0 && (
              <p className="flex items-start gap-2 text-sm text-semantic-warning">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                {t('schedule.generate_conflict_started', {
                  defaultValue: '{{count}} of them have progress recorded. Replacing them loses that progress.',
                  count: generateConflict.startedCount,
                })}
              </p>
            )}
            {replaceInstalmentSentences(t, generateConflict.instalmentsRelinked, generateConflict.instalmentsUnlinked).map(
              (line) => (
                <p key={line} className="text-sm text-content-secondary">
                  {line}
                </p>
              ),
            )}
            <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
              <Button variant="ghost" type="button" onClick={() => setGenerateConflict(null)}>
                {t('common.cancel', 'Cancel')}
              </Button>
              {onOpenSchedule && (
                <Button
                  variant="secondary"
                  type="button"
                  loading={generateIntoNewSchedule.isPending}
                  disabled={generateFromBOQ.isPending}
                  onClick={() => generateIntoNewSchedule.mutate(generateConflict.boqId)}
                >
                  {t('schedule.generate_conflict_new_schedule', { defaultValue: 'Create a new schedule' })}
                </Button>
              )}
              <Button
                variant="danger"
                type="button"
                loading={generateFromBOQ.isPending}
                disabled={generateIntoNewSchedule.isPending}
                onClick={() => generateFromBOQ.mutate({ boqId: generateConflict.boqId, replace: true })}
              >
                {t('schedule.generate_conflict_replace', { defaultValue: 'Replace them' })}
              </Button>
            </div>
          </div>
        )}
      </Modal>
      <ActivityDeleteDialog
        target={deleteTarget}
        loading={deleteActivity.isPending}
        onCancel={() => setDeleteTarget(null)}
        onDelete={(cascade) => deleteTarget && deleteActivity.mutate({ activityId: deleteTarget.id, cascade })}
      />
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Schedule List for a Project ───────────────────────────────────────── */

export function ProjectSchedules({
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
  const [showSpreadsheetImport, setShowSpreadsheetImport] = useState(false);
  const [archiveState, setArchiveState] = useState<'current' | 'archived' | 'all'>('current');
  const [scheduleOffset, setScheduleOffset] = useState(0);
  const schedulePageSize = 50;
  // Creating a schedule is editor work (schedule.create). A viewer reads the
  // list; the create button stays visible but disabled, with the reason.
  const canCreateSchedule = useHasPermission('schedule.create');
  const canGenerate = useHasPermission('schedule.update');
  const createHint = canCreateSchedule
    ? undefined
    : t('errors.forbidden', { defaultValue: "You don't have permission to perform this action." });
  const [form, setForm] = useState<CreateScheduleForm>({
    name: '',
    description: '',
    start_date: '',
    end_date: '',
  });

  const { data: schedulePage, isLoading, isError: isScheduleListError } = useQuery({
    queryKey: ['schedules', project.id, archiveState, scheduleOffset],
    queryFn: () => scheduleApi.listSchedules(project.id, { archiveState, offset: scheduleOffset, limit: schedulePageSize }),
  });
  const schedules = schedulePage?.items;
  useEffect(() => {
    if (schedulePage && scheduleOffset > 0 && scheduleOffset >= schedulePage.total) {
      setScheduleOffset(Math.max(0, Math.ceil(schedulePage.total / schedulePageSize) - 1) * schedulePageSize);
    }
  }, [schedulePage, scheduleOffset]);

  // CONN-34: when arriving via the BOQ "Build schedule from this BOQ" deep
  // link, drill straight to a schedule so the Generate-from-BOQ modal (which
  // lives in ScheduleDetail) can open with the BOQ pre-selected. If at least
  // one schedule exists, open the first; if none exist, open the Create modal
  // so the user makes one first — the param survives so generation continues
  // once the schedule is created and selected.
  //
  // With schedules already there the reader picks one (or a new one): taking
  // the first silently sent the BOQ into whatever schedule sorted first, which
  // usually already had activities, and the generation was refused.
  const generateHandledRef = useRef(false);
  const [showGenerateTarget, setShowGenerateTarget] = useState(false);
  const openCreateForGenerate = useCallback(() => {
    setForm((f) =>
      f.name ? f : { ...f, name: t('schedule.default_schedule_name', { defaultValue: 'Construction schedule' }) },
    );
    setShowCreate(true);
  }, [t]);
  useEffect(() => {
    if (!generateBoqId || generateHandledRef.current) return;
    if (selectedSchedule) return;
    if (!schedules) return; // wait for the list to load
    generateHandledRef.current = true;
    if (schedules.some((item) => item.status !== 'archived')) {
      if (canGenerate) setShowGenerateTarget(true);
    } else if (canCreateSchedule) {
      openCreateForGenerate();
      addToast({
        type: 'info',
        title: t('schedule.create_before_generate', {
          defaultValue: 'Create a schedule first, then it generates from your BOQ.',
        }),
      });
    }
  }, [generateBoqId, schedules, selectedSchedule, addToast, t, canCreateSchedule, canGenerate, openCreateForGenerate]);

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
      // Keyed by id: switching to another schedule (a plan generated into a
      // new one) starts its page fresh instead of carrying this one's state.
      <ScheduleDetail
        key={selectedSchedule.id}
        schedule={selectedSchedule}
        projectId={project.id}
        onBack={() => setSelectedSchedule(null)}
        generateBoqId={generateBoqId}
        onConsumeGenerateBoq={onConsumeGenerateBoq}
        onOpenSchedule={setSelectedSchedule}
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
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="lg"
            icon={<FileSpreadsheet size={18} />}
            onClick={() => setShowSpreadsheetImport(true)}
            disabled={!canCreateSchedule}
            title={createHint}
          >
            {t('schedule.tabular_import.open', { defaultValue: 'Import spreadsheet' })}
          </Button>
          <Button
            variant="primary"
            size="lg"
            icon={<Plus size={18} />}
            onClick={() => setShowCreate(true)}
            disabled={!canCreateSchedule}
            title={createHint}
          >
            {t('schedule.create_schedule', 'Create Schedule')}
          </Button>
        </div>
      </div>

      <label className="mb-4 flex flex-wrap items-center gap-2 text-sm text-content-secondary">
        {t('schedule.archive_filter')}
        <select aria-label={t('schedule.archive_filter')} value={archiveState}
          onChange={(event) => { setArchiveState(event.target.value as typeof archiveState); setScheduleOffset(0); }}
          className="rounded-md border border-border bg-surface-primary px-3 py-2 text-content-primary">
          <option value="current">{t('schedule.archive_filter_current')}</option>
          <option value="archived">{t('schedule.status_archived')}</option>
          <option value="all">{t('common.all')}</option>
        </select>
      </label>
      {/* Schedule list */}
      {isLoading ? (
        <SkeletonTable rows={3} columns={4} />
      ) : isScheduleListError ? (
        <div className="w-full py-8 text-center">
          <p className="text-content-secondary">{t('schedule.load_error', { defaultValue: 'Failed to load schedules. Please try again.' })}</p>
        </div>
      ) : archiveState === 'archived' && !schedules?.length ? (
        <p className="py-8 text-center text-content-secondary">{t('schedule.archive_empty')}</p>
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
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button
              variant="secondary"
              size="lg"
              icon={<FileSpreadsheet size={18} />}
              onClick={() => setShowSpreadsheetImport(true)}
              disabled={!canCreateSchedule}
              title={createHint}
            >
              {t('schedule.tabular_import.hero_cta', { defaultValue: 'Import from Excel or CSV' })}
            </Button>
            <Button
              variant="primary"
              size="lg"
              icon={<Plus size={18} />}
              onClick={() => setShowCreate(true)}
              disabled={!canCreateSchedule}
              title={createHint}
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
                <ScheduleLifecycleActions schedule={schedule} compact />
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {!isScheduleListError && (scheduleOffset > 0 || (schedulePage?.total ?? 0) > schedulePageSize) && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="secondary" disabled={isLoading || scheduleOffset === 0}
            onClick={() => setScheduleOffset(Math.max(0, scheduleOffset - schedulePageSize))}>
            {t('common.previous_page')}
          </Button>
          <Button variant="secondary" disabled={isLoading || scheduleOffset + schedulePageSize >= (schedulePage?.total ?? 0)}
            onClick={() => setScheduleOffset(scheduleOffset + schedulePageSize)}>
            {t('common.next_page')}
          </Button>
        </div>
      )}

      {/* BOQ deep link: which schedule should the plan go into? */}
      <Modal
        open={showGenerateTarget}
        onClose={() => {
          setShowGenerateTarget(false);
          onConsumeGenerateBoq?.();
        }}
        title={t('schedule.generate_target_title', { defaultValue: 'Which schedule should the BOQ go into?' })}
      >
        <div className="space-y-3">
          <p className="text-sm text-content-secondary">
            {t('schedule.generate_target_hint', {
              defaultValue:
                'Pick a schedule to generate into, or start a new one. A schedule that already has activities asks before anything is replaced.',
            })}
          </p>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {(schedules ?? []).filter((item) => item.status !== 'archived').map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  setShowGenerateTarget(false);
                  setSelectedSchedule(s);
                }}
                className="flex w-full items-center gap-3 rounded-lg border border-border bg-surface-primary px-4 py-3 text-left transition-all hover:bg-surface-secondary"
              >
                <CalendarDays size={16} className="shrink-0 text-oe-blue" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-content-primary">{s.name}</span>
                <Badge variant={s.status === 'active' ? 'blue' : 'neutral'} size="sm">
                  {t(`schedule.status_${s.status}`, { defaultValue: s.status })}
                </Badge>
              </button>
            ))}
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            {(scheduleOffset > 0 || (schedulePage?.total ?? 0) > schedulePageSize) && <>
              <Button variant="secondary" type="button" disabled={isLoading || scheduleOffset === 0}
                onClick={() => setScheduleOffset(Math.max(0, scheduleOffset - schedulePageSize))}>
                {t('common.previous_page')}
              </Button>
              <Button variant="secondary" type="button"
                disabled={isLoading || scheduleOffset + schedulePageSize >= (schedulePage?.total ?? 0)}
                onClick={() => setScheduleOffset(scheduleOffset + schedulePageSize)}>
                {t('common.next_page')}
              </Button>
            </>}
            <Button
              variant="ghost"
              type="button"
              onClick={() => {
                setShowGenerateTarget(false);
                onConsumeGenerateBoq?.();
              }}
            >
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant="primary"
              type="button"
              icon={<Plus size={14} />}
              disabled={!canCreateSchedule}
              title={createHint}
              onClick={() => {
                setShowGenerateTarget(false);
                openCreateForGenerate();
              }}
            >
              {t('schedule.new_schedule', { defaultValue: 'New schedule' })}
            </Button>
          </div>
        </div>
      </Modal>
      <ScheduleSpreadsheetImportDialog
        open={showSpreadsheetImport}
        onClose={() => setShowSpreadsheetImport(false)}
        projectId={project.id}
        onImported={() => queryClient.invalidateQueries({ queryKey: ['schedules', project.id] })}
        onOpenSchedule={(result) => {
          setShowSpreadsheetImport(false);
          scheduleApi.getSchedule(result.schedule_id).then(setSelectedSchedule, (error: Error) =>
            addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message }),
          );
        }}
      />

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
    <CollapsibleSection
      storageKey="schedule.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('schedule.flow_title', { defaultValue: 'How the 4D Schedule fits together' })}
    >
      <p className="text-xs text-content-tertiary">
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
    </CollapsibleSection>
  );
}

export function SchedulePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { activeProjectId, setActiveProject } = useProjectContextStore();
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
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

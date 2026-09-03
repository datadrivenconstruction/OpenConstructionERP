// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Canonical project-detail widget registry — single source of truth shared
 * by ``ProjectDetailPage`` (which maps each id to a live React node) and
 * ``ProjectLayoutManager`` (the reorder / show-hide UI).
 *
 * Order here = the default top-to-bottom layout. The page chrome
 * (breadcrumb + tab bar + import dialog) is intentionally NOT a widget;
 * it stays pinned. Tabs other than "dashboard" are also untouched —
 * the customizer only re-arranges the always-visible top stack that
 * sits above the tab bar.
 *
 * Categories drive the visual grouping in the layout manager and the
 * default ordering (overview → work → collab → docs → analytics):
 *   - overview : at-a-glance project context (info, health, map, weather)
 *   - work     : execution surfaces (BOQ list, schedule, daily diary)
 *   - collab   : people-and-comms (team, RFI inbox, activity feed)
 *   - docs     : files, photos, compliance
 *   - analytics: charts and AI insights
 */
import type { LucideIcon } from 'lucide-react';
import {
  Info,
  Activity,
  Map,
  CloudSun,
  Users,
  UserCheck,
  Table2,
  CalendarClock,
  ClipboardList,
  GitPullRequestArrow,
  ClipboardPen,
  HardHat,
  Wallet,
  Image as ImageIcon,
  FolderOpen,
  ShieldCheck,
  Sparkles,
  Receipt,
  GitBranch,
  AlertTriangle,
  ListChecks,
  Wrench,
} from 'lucide-react';

export type ProjectWidgetCategory =
  | 'overview'
  | 'work'
  | 'collab'
  | 'docs'
  | 'analytics';

export interface ProjectWidgetMeta {
  id: string;
  /** i18n key for the widget name. */
  labelKey: string;
  labelDefault: string;
  /** i18n key for the one-line description shown in the manager. */
  descKey: string;
  descDefault: string;
  icon: LucideIcon;
  category: ProjectWidgetCategory;
}

export const PROJECT_WIDGETS: readonly ProjectWidgetMeta[] = [
  /* ── Overview ──────────────────────────────────────────────────────── */
  {
    id: 'project-info',
    labelKey: 'project.widget.project-info.title',
    labelDefault: 'Project info',
    descKey: 'project.widget.project-info.description',
    descDefault: 'Name, description, region, currency and badges',
    icon: Info,
    category: 'overview',
  },
  {
    id: 'health-bar',
    labelKey: 'project.widget.health-bar.title',
    labelDefault: 'Project health',
    descKey: 'project.widget.health-bar.description',
    descDefault: 'Composite progress ring with checkpoint dots',
    icon: Activity,
    category: 'overview',
  },
  {
    id: 'location',
    labelKey: 'project.widget.location.title',
    labelDefault: 'Map & weather',
    descKey: 'project.widget.location.description',
    descDefault: 'Site map plus today’s weather at the address',
    icon: Map,
    category: 'overview',
  },
  {
    id: 'phase-ribbon',
    labelKey: 'project.widget.phase-ribbon.title',
    labelDefault: 'Phase ribbon',
    descKey: 'project.widget.phase-ribbon.description',
    descDefault: 'Lifecycle progress strip (Concept → Handover)',
    icon: GitBranch,
    category: 'overview',
  },
  {
    id: 'summary-cards',
    labelKey: 'project.widget.summary-cards.title',
    labelDefault: 'KPI summary cards',
    descKey: 'project.widget.summary-cards.description',
    descDefault: 'Grand total, BOQ count, positions and validation score',
    icon: Table2,
    category: 'overview',
  },

  /* ── Collab ────────────────────────────────────────────────────────── */
  {
    id: 'team',
    labelKey: 'project.widget.team.title',
    labelDefault: 'Team strip',
    descKey: 'project.widget.team.description',
    descDefault: 'Horizontal avatar row of project members',
    icon: Users,
    category: 'collab',
  },
  {
    // The richer sibling of `team`: the strip says who is on the job, this
    // tile says what each of them is carrying this week. Both can be on.
    id: 'team-availability',
    labelKey: 'project.widget.team-availability.title',
    labelDefault: 'Project team',
    descKey: 'project.widget.team-availability.description',
    descDefault:
      'Who is on this job, their role, and what they are carrying this week',
    icon: UserCheck,
    category: 'collab',
  },
  {
    id: 'rfi-inbox',
    labelKey: 'project.widget.rfi-inbox.title',
    labelDefault: 'RFI inbox',
    descKey: 'project.widget.rfi-inbox.description',
    descDefault: 'Five most recent open Requests for Information',
    icon: GitPullRequestArrow,
    category: 'collab',
  },
  {
    id: 'registers',
    labelKey: 'project.widget.registers.title',
    labelDefault: 'Registers',
    descKey: 'project.widget.registers.description',
    descDefault: 'Open RFIs, RFQs, orders and variations raised on this job',
    icon: ListChecks,
    category: 'collab',
  },
  {
    id: 'work-requests',
    labelKey: 'project.widget.work-requests.title',
    labelDefault: 'Department requests',
    descKey: 'project.widget.work-requests.description',
    descDefault: 'Engineering, drafting, workshop, automation and hazardous-area requests raised on this job',
    icon: Wrench,
    category: 'collab',
  },
  {
    id: 'activity-feed',
    labelKey: 'project.widget.activity-feed.title',
    labelDefault: 'Recent activity',
    descKey: 'project.widget.activity-feed.description',
    descDefault: 'Cross-module event feed for this project',
    icon: Activity,
    category: 'collab',
  },

  /* ── Work ──────────────────────────────────────────────────────────── */
  {
    id: 'boq-list',
    labelKey: 'project.widget.boq-list.title',
    labelDefault: 'BOQ list',
    descKey: 'project.widget.boq-list.description',
    descDefault: 'All Bill of Quantities attached to this project',
    icon: Table2,
    category: 'work',
  },
  {
    id: 'schedule-strip',
    labelKey: 'project.widget.schedule-strip.title',
    labelDefault: 'Schedule summary',
    descKey: 'project.widget.schedule-strip.description',
    descDefault: 'Mini Gantt strip with milestones and percent complete',
    icon: CalendarClock,
    category: 'work',
  },
  {
    id: 'daily-diary',
    labelKey: 'project.widget.daily-diary.title',
    labelDefault: 'Daily diary',
    descKey: 'project.widget.daily-diary.description',
    descDefault: 'Latest diary entry preview and weather snapshot',
    icon: ClipboardPen,
    category: 'work',
  },
  {
    id: 'change-orders',
    labelKey: 'project.widget.change-orders.title',
    labelDefault: 'Change orders pulse',
    descKey: 'project.widget.change-orders.description',
    descDefault: 'Pending / approved this month plus dollar impact',
    icon: Receipt,
    category: 'work',
  },
  {
    id: 'variations',
    labelKey: 'project.widget.variations.title',
    labelDefault: 'Variations counter',
    descKey: 'project.widget.variations.description',
    descDefault: 'Open variations and disputed totals',
    icon: ClipboardList,
    category: 'work',
  },

  /* ── Docs ──────────────────────────────────────────────────────────── */
  {
    id: 'recent-files',
    labelKey: 'project.widget.recent-files.title',
    labelDefault: 'Recent files',
    descKey: 'project.widget.recent-files.description',
    descDefault: 'Most recent uploads with type and size',
    icon: FolderOpen,
    category: 'docs',
  },
  {
    id: 'photo-strip',
    labelKey: 'project.widget.photo-strip.title',
    labelDefault: 'Photo strip',
    descKey: 'project.widget.photo-strip.description',
    descDefault: 'Last 6 site photos uploaded to the project',
    icon: ImageIcon,
    category: 'docs',
  },
  {
    id: 'compliance-summary',
    labelKey: 'project.widget.compliance-summary.title',
    labelDefault: 'Compliance summary',
    descKey: 'project.widget.compliance-summary.description',
    descDefault: 'Insurance / permits / certifications expiry status',
    icon: ShieldCheck,
    category: 'docs',
  },

  /* ── Analytics ─────────────────────────────────────────────────────── */
  {
    id: 'hse-incidents',
    labelKey: 'project.widget.hse-incidents.title',
    labelDefault: 'HSE incidents',
    descKey: 'project.widget.hse-incidents.description',
    descDefault: 'Open safety incidents and severity heatmap',
    icon: HardHat,
    category: 'analytics',
  },
  {
    id: 'quality-ncr',
    labelKey: 'project.widget.quality-ncr.title',
    labelDefault: 'Quality NCRs',
    descKey: 'project.widget.quality-ncr.description',
    descDefault: 'Open non-conformances with severity breakdown',
    icon: AlertTriangle,
    category: 'analytics',
  },
  {
    id: 'budget-burn',
    labelKey: 'project.widget.budget-burn.title',
    labelDefault: 'Budget burn',
    descKey: 'project.widget.budget-burn.description',
    descDefault: 'Sparkline of actual-vs-planned spend over time',
    icon: Wallet,
    category: 'analytics',
  },
  {
    id: 'weather-alerts',
    labelKey: 'project.widget.weather-alerts.title',
    labelDefault: 'Weather alerts',
    descKey: 'project.widget.weather-alerts.description',
    descDefault: 'Site weather conditions with risk badges',
    icon: CloudSun,
    category: 'analytics',
  },
  {
    id: 'ai-insights',
    labelKey: 'project.widget.ai-insights.title',
    labelDefault: 'AI insights',
    descKey: 'project.widget.ai-insights.description',
    descDefault: 'Top AI agent suggestions with confidence dot',
    icon: Sparkles,
    category: 'analytics',
  },
] as const;

export const PROJECT_WIDGET_IDS: readonly string[] = PROJECT_WIDGETS.map(
  (w) => w.id,
);

export const PROJECT_WIDGET_BY_ID: Readonly<
  Record<string, ProjectWidgetMeta>
> = Object.fromEntries(PROJECT_WIDGETS.map((w) => [w.id, w]));

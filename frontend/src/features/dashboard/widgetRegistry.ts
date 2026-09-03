// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Canonical dashboard widget registry — single source of truth shared by
 * `DashboardPage` (which maps each id to a live React node) and
 * `DashboardLayoutManager` (the reorder / show-hide UI).
 *
 * Order here = the default top-to-bottom layout. The hero header
 * (greeting + primary CTAs + meta strip) is intentionally NOT a widget:
 * it's page chrome and always stays pinned at the top.
 */
import type { LucideIcon } from 'lucide-react';
import {
  Sparkles,
  AlertTriangle,
  TrendingUp,
  Building2,
  Layers,
  Globe,
  Cpu,
  Upload,
  Lightbulb,
  CheckCircle2,
  BarChart3,
  Activity,
  // Wave 2 (added 2026-05-23) — consolidated into Operations snapshot
  // on 2026-05-25; only ClipboardList + CloudSun remain in active use.
  ClipboardList,
  CloudSun,
  HardHat,
  Camera,
  Wallet,
  Inbox,
  // Delivery & quality (added 2026-07-05)
  Flag,
  HelpCircle,
  FileCheck2,
  ClipboardCheck,
  ListChecks,
  // Interoperability: dashboard <- estimate (2026-07-09)
  Package,
  // Learn-by-example cases card, folded into the registry 2026-07-21
  GraduationCap,
  // Clients rollup (one client, many projects)
  Users,
  // Department work requests (engineering, drafting, workshop, ...)
  Wrench,
} from 'lucide-react';

export interface DashboardWidgetMeta {
  id: string;
  /** i18n key for the widget name. */
  labelKey: string;
  labelDefault: string;
  /** i18n key for the one-line description shown in the manager. */
  descKey: string;
  descDefault: string;
  icon: LucideIcon;
  /** Default width in grid columns on the 6-col dashboard grid (2=third, 3=half, 4=two-thirds, 6=full). Omit = 6 (full width). */
  defaultSpan?: number;
}

export const DASHBOARD_WIDGETS: readonly DashboardWidgetMeta[] = [
  // "Start here - learn by example" cases gallery. Folded into the registry so
  // it can be hidden or narrowed like any other widget (it used to be pinned
  // full-width and could not be removed). Defaults to full width at the top.
  {
    id: 'cases_learn',
    labelKey: 'dashboard.layout.w_cases_learn',
    labelDefault: 'Start here - learn by example',
    descKey: 'dashboard.layout.w_cases_learn_desc',
    descDefault: 'Guided real-world example workflows to learn the platform',
    icon: GraduationCap,
  },
  // Which regional pack is switched on and what it set up. Sits this high on
  // purpose: it answers "is this product configured for the country I work
  // in", which is the question a new reader has before any number on the page
  // means anything, and which nothing on the dashboard answered at all until
  // now. Narrow, because it is six short rows - the dense grid flow backfills
  // the columns beside it.
  //
  // labelKey is the card's own heading key rather than a
  // dashboard.layout.w_* of its own. The layout manager lists this widget by
  // exactly the words the card is titled with, so a second key would be the
  // same sentence translated twice into forty-one languages with nothing to
  // keep the two copies agreeing.
  {
    id: 'regional_pack',
    labelKey: 'dashboard.regional_pack_title',
    labelDefault: 'Your regional pack',
    descKey: 'dashboard.layout.w_regional_pack_desc',
    descDefault: 'Which market pack is active and what it sets up for you',
    icon: Globe,
    defaultSpan: 2,
  },
  // ── Core (existing 12) ────────────────────────────────────────────────
  {
    id: 'continue_work',
    labelKey: 'dashboard.layout.w_continue',
    labelDefault: 'Continue your work',
    descKey: 'dashboard.layout.w_continue_desc',
    descDefault: 'Quick-resume strip for your most recent estimate',
    icon: Sparkles,
  },
  {
    id: 'today',
    labelKey: 'dashboard.layout.w_today',
    labelDefault: 'Today snapshot',
    descKey: 'dashboard.layout.w_today_desc',
    descDefault: 'Aggregated alerts and due items across projects',
    icon: AlertTriangle,
  },
  {
    id: 'kpi',
    labelKey: 'dashboard.layout.w_kpi',
    labelDefault: 'KPI ribbon',
    descKey: 'dashboard.layout.w_kpi_desc',
    descDefault: 'Portfolio totals - value, projects, schedules',
    icon: TrendingUp,
  },
  {
    id: 'finance_summary',
    labelKey: 'dashboard.layout.w_finance_summary',
    labelDefault: 'Finance summary',
    descKey: 'dashboard.layout.w_finance_summary_desc',
    descDefault: 'Estimated value, open change orders and budget warnings',
    icon: Wallet,
    defaultSpan: 3,
  },
  // Interoperability: surface the ESTIMATE side's resource rollup (labour
  // hours, total resource cost, distinct resource count) next to the field
  // labour-cost widget. Self-hides when the estimate has no resources.
  {
    id: 'estimate_resources',
    labelKey: 'dashboard.layout.w_estimate_resources',
    labelDefault: 'Estimate resources',
    descKey: 'dashboard.layout.w_estimate_resources_desc',
    descDefault: 'Labour hours, total resource cost and distinct resources from the estimate',
    icon: Package,
    defaultSpan: 3,
  },
  {
    id: 'projects',
    labelKey: 'dashboard.layout.w_projects',
    labelDefault: 'Project cards',
    descKey: 'dashboard.layout.w_projects_desc',
    descDefault: 'Per-project metric cards (primary content)',
    icon: Building2,
  },
  {
    id: 'portfolio',
    labelKey: 'dashboard.layout.w_portfolio',
    labelDefault: 'Portfolio overview',
    descKey: 'dashboard.layout.w_portfolio_desc',
    descDefault: 'Cross-project rollup for multi-project workspaces',
    icon: Layers,
  },
  // One client, many projects: per-client project count, active count and
  // contract value, each row deep-linking to the projects list for that
  // client. Half width - it is a short list beside the portfolio rollup.
  {
    id: 'clients',
    labelKey: 'dashboard.layout.w_clients',
    labelDefault: 'Clients',
    descKey: 'dashboard.layout.w_clients_desc',
    descDefault: 'Projects, active work and contract value per client',
    icon: Users,
    defaultSpan: 3,
  },
  // What each department (engineering, drafting, workshop, automation,
  // hazardous area) is holding across the portfolio: open, overdue, back
  // with the requester, due this week. Half width beside the clients list.
  // Always renders - a deployment without the Work requests module gets a
  // one-line "not available" rather than a vanished card.
  {
    id: 'department_requests',
    labelKey: 'dashboard.layout.w_department_requests',
    labelDefault: 'Department requests',
    descKey: 'dashboard.layout.w_department_requests_desc',
    descDefault: 'Open, overdue and due-this-week requests per department across your jobs',
    icon: Wrench,
    defaultSpan: 3,
  },
  {
    id: 'map',
    labelKey: 'dashboard.layout.w_map',
    labelDefault: 'Project map',
    descKey: 'dashboard.layout.w_map_desc',
    descDefault: 'Geographic map of project locations',
    icon: Globe,
  },
  {
    id: 'inbox',
    labelKey: 'dashboard.layout.w_inbox',
    labelDefault: 'Inbox',
    descKey: 'dashboard.layout.w_inbox_desc',
    descDefault: 'Pending approvals and alerts awaiting you, in one list',
    icon: Inbox,
    defaultSpan: 3,
  },
  {
    id: 'quick_upload',
    labelKey: 'dashboard.layout.w_upload',
    labelDefault: 'Quick upload',
    descKey: 'dashboard.layout.w_upload_desc',
    descDefault: 'Drag-and-drop a drawing or document to start',
    icon: Upload,
    defaultSpan: 3,
  },
  {
    id: 'bim_coverage',
    labelKey: 'dashboard.layout.w_bim',
    labelDefault: 'BIM coverage',
    descKey: 'dashboard.layout.w_bim_desc',
    descDefault: 'Model coverage and linked-quantity health',
    icon: Cpu,
    defaultSpan: 3,
  },
  {
    id: 'onboarding',
    labelKey: 'dashboard.layout.w_onboarding',
    labelDefault: 'Getting started',
    descKey: 'dashboard.layout.w_onboarding_desc',
    descDefault: 'Setup checklist - hides itself once complete',
    icon: Lightbulb,
  },
  {
    id: 'next_steps',
    labelKey: 'dashboard.layout.w_next',
    labelDefault: 'Suggested next steps',
    descKey: 'dashboard.layout.w_next_desc',
    descDefault: 'Context-aware recommendations for this workspace',
    icon: CheckCircle2,
  },
  {
    id: 'analytics',
    labelKey: 'dashboard.layout.w_analytics',
    labelDefault: 'Analytics',
    descKey: 'dashboard.layout.w_analytics_desc',
    descDefault: 'Charts and trend analysis across the portfolio',
    icon: BarChart3,
  },
  {
    id: 'activity',
    labelKey: 'dashboard.layout.w_activity',
    labelDefault: 'Activity & system status',
    descKey: 'dashboard.layout.w_activity_desc',
    descDefault: 'Recent cross-module activity feed and system health',
    icon: Activity,
  },

  // ── Operations snapshot (consolidates 9 wave-2 widgets, 2026-05-25) ───
  // Replaces the previous nine individual widgets (boq_summary,
  // validation_score, clash_health, schedule_critical, risk_top,
  // hse_scorecard, procurement_pipeline, budget_variance,
  // change_orders) that each rendered as a full-width empty card on
  // fresh installs. Single card with a 3-column grid of compact tiles;
  // each tile clicks through to the relevant module and lights up with
  // data automatically.
  {
    id: 'operations_snapshot',
    labelKey: 'dashboard.layout.w_operations_snapshot',
    labelDefault: 'Operations snapshot',
    descKey: 'dashboard.layout.w_operations_snapshot_desc',
    descDefault: 'BOQ · Validation · Clash · Schedule · Risks · HSE · Procurement · Budget · Change orders',
    icon: ClipboardList,
  },

  // ── Delivery & quality (added 2026-07-05) ────────────────────────────────
  // Each card self-hides when its module has no data for the active project,
  // so a fresh install never shows an empty card. They surface the delivery
  // and quality work that the operations snapshot does not consolidate.
  {
    id: 'upcoming_milestones',
    labelKey: 'dashboard.layout.w_upcoming_milestones',
    labelDefault: 'Upcoming milestones',
    descKey: 'dashboard.layout.w_upcoming_milestones_desc',
    descDefault: 'The next key schedule dates, with days remaining or overdue',
    icon: Flag,
  },
  {
    id: 'rfi_turnaround',
    labelKey: 'dashboard.layout.w_rfi_turnaround',
    labelDefault: 'RFI turnaround',
    descKey: 'dashboard.layout.w_rfi_turnaround_desc',
    descDefault: 'Open and overdue requests for information, plus average response time',
    icon: HelpCircle,
    defaultSpan: 3,
  },
  {
    id: 'submittals_pending',
    labelKey: 'dashboard.layout.w_submittals_pending',
    labelDefault: 'Submittals',
    descKey: 'dashboard.layout.w_submittals_pending_desc',
    descDefault: 'Submittals pending review, approved and overdue',
    icon: FileCheck2,
    defaultSpan: 2,
  },
  {
    id: 'inspections_quality',
    labelKey: 'dashboard.layout.w_inspections_quality',
    labelDefault: 'Inspections',
    descKey: 'dashboard.layout.w_inspections_quality_desc',
    descDefault: 'Inspection pass rate with open and failed counts',
    icon: ClipboardCheck,
    defaultSpan: 2,
  },
  {
    id: 'punch_quality',
    labelKey: 'dashboard.layout.w_punch_quality',
    labelDefault: 'Punch list',
    descKey: 'dashboard.layout.w_punch_quality_desc',
    descDefault: 'Open and overdue punch items with average time to close',
    icon: ListChecks,
    defaultSpan: 2,
  },

  // ── Field ──────────────────────────────────────────────────────────────
  {
    id: 'weather_site',
    labelKey: 'dashboard.layout.w_weather',
    labelDefault: 'Weather & Site',
    descKey: 'dashboard.layout.w_weather_desc',
    descDefault: "Today's weather at your first project site",
    icon: CloudSun,
    defaultSpan: 2,
  },
  {
    id: 'labour_cost',
    labelKey: 'dashboard.layout.w_labour_cost',
    labelDefault: 'Labour cost vs budget',
    descKey: 'dashboard.layout.w_labour_cost_desc',
    descDefault: 'Cumulative field labour cost against the labour budget',
    icon: HardHat,
    defaultSpan: 2,
  },
  {
    id: 'latest_photos',
    labelKey: 'dashboard.layout.w_latest_photos',
    labelDefault: 'Latest site photos',
    descKey: 'dashboard.layout.w_latest_photos_desc',
    descDefault: 'Recent progress photos across your projects',
    icon: Camera,
    defaultSpan: 4,
  },
] as const;

export const DASHBOARD_WIDGET_IDS: readonly string[] =
  DASHBOARD_WIDGETS.map((w) => w.id);

export const DASHBOARD_WIDGET_BY_ID: Readonly<
  Record<string, DashboardWidgetMeta>
> = Object.fromEntries(DASHBOARD_WIDGETS.map((w) => [w.id, w]));

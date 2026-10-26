// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dashboard rollup type definitions.
 *
 * Mirrors ``backend/app/modules/dashboard/schemas.py``. Two flavours of
 * widget live on the same ``/api/v1/dashboard/rollup/`` endpoint:
 *
 *   1. Wave-2 dashboard widgets (boq_summary, validation_score, …) —
 *      cross-project aggregates that power /dashboard.
 *   2. Project-detail widgets (project_rfi_inbox, project_change_orders_pulse,
 *      …) — single-project aggregates that power /projects/:id.
 *
 * Both shapes are exported from this single module so any caller (the
 * dashboard surface, the project-detail surface, future surfaces) imports
 * the same ``DashboardRollupResponse`` symbol.
 *
 * Money fields are Decimal-as-string per the architecture guide §10 — never coerce
 * them to ``Number`` until *after* the format step.
 *
 * Re-exports the legacy types from ``@/features/dashboard/hooks/useDashboardRollup``
 * so existing imports keep working.
 */

export type {
  // Legacy wave-2 widget types — keep one source of truth in the
  // dashboard feature so we don't drift.
  DashboardWidgetId,
  BOQByProject,
  LastBOQRef,
  BOQSummaryPayload,
  ValidationByProject,
  ValidationScorePayload,
  ClashByProject,
  ClashHealthPayload,
  CriticalTaskItem,
  ScheduleCriticalPayload,
  RiskItemRow,
  RiskTopPayload,
  HSEByProject,
  HSEScorecardPayload,
  ProcurementPipelinePayload,
  BudgetByProject,
  BudgetVariancePayload,
  ChangeOrderItem,
  ChangeOrdersPayload,
  WeatherSitePayload,
  DashboardRollupPayload,
  WidgetPayloadMap,
} from '@/features/dashboard/hooks/useDashboardRollup';

/* ── Project-detail widget payload types (W23 P0) ─────────────────────── */

export interface ProjectRFIItem {
  id: string;
  number: string | null;
  subject: string;
  status: string;
  created_at?: string | null;
  due_date?: string | null;
}

export interface ProjectRFIInboxPayload {
  items: ProjectRFIItem[];
}

export interface ProjectChangeOrdersPulsePayload {
  open_count: number;
  pending_count: number;
  approved_count: number;
  /** Decimal-as-string. */
  total_value: string;
  /** Decimal-as-string. */
  approved_value: string;
  currency: string;
}

/**
 * ``weather_summary`` mirrors the backend's loose JSONB column — either
 * a string or an object. The widget has ``formatWeatherSummary`` to
 * normalise both shapes.
 */
export interface ProjectDiaryItem {
  id: string;
  diary_date?: string | null;
  status?: string | null;
  weather_summary?:
    | string
    | { conditions?: string; temp_c?: number; summary?: string }
    | Record<string, unknown>
    | null;
  manpower_total?: number | null;
  narrative?: string | null;
}

export interface ProjectDailyDiaryPayload {
  items: ProjectDiaryItem[];
}

export interface ProjectHSEItem {
  id: string;
  status: string | null;
  severity: string | null;
}

export interface ProjectHSEIncidentsPayload {
  total: number;
  high: number;
  medium: number;
  low: number;
  items: ProjectHSEItem[];
}

export interface ProjectVariationItem {
  id: string;
  status: string | null;
  /** Decimal-as-string. */
  estimated_value: string;
  disputed: boolean;
}

export interface ProjectVariationsPayload {
  open: number;
  /** Decimal-as-string. */
  disputed_value: string;
  currency: string;
  items: ProjectVariationItem[];
}

export interface ProjectNCRItem {
  id: string;
  status: string | null;
  severity: string | null;
}

export interface ProjectQualityNCRPayload {
  open: number;
  major: number;
  minor: number;
  items: ProjectNCRItem[];
}

export interface ProjectComplianceItem {
  id: string;
  status: string | null;
  expires_at: string | null;
  doc_type: string | null;
}

export interface ProjectComplianceSummaryPayload {
  active: number;
  expiring: number;
  expired: number;
  items: ProjectComplianceItem[];
}

export interface ProjectBudgetBurnPayload {
  /** Decimal-as-string. */
  planned_total: string;
  /** Decimal-as-string. */
  actual_total: string;
  currency: string;
  /** Reserved for a future time-series endpoint. Empty in v1. */
  series: Array<{ date?: string; planned?: number | string; actual?: number | string }>;
}

export interface ProjectLpsPpcItem {
  project_id: string;
  master_schedule_id: string;
  name: string;
  /** Decimal-as-string, null when no week was ever committed. */
  average_ppc: string | null;
  weeks: Array<{ week_start_date: string; ppc_percent: string | null }>;
}

export interface ProjectLpsPpcPayload {
  items?: ProjectLpsPpcItem[];
  pareto?: Array<{ category: string; count: number }>;
}

export interface ProjectSubInsurancePayload {
  compliant: number;
  expiring: number;
  non_compliant: number;
  blocked_payments: number;
}

/** Canonical project-detail widget id list. */
export const PROJECT_DETAIL_WIDGET_IDS = [
  'project_rfi_inbox',
  'project_change_orders_pulse',
  'project_daily_diary',
  'project_hse_incidents',
  'project_variations',
  'project_quality_ncr',
  'project_compliance_summary',
  'project_budget_burn',
  'project_lps_ppc',
  'project_sub_insurance',
] as const;

export type ProjectDetailWidgetId = (typeof PROJECT_DETAIL_WIDGET_IDS)[number];

/**
 * Lookup map: project-detail widget id → its concrete payload type.
 *
 * Lets us write ``ProjectDetailPayloadMap['project_rfi_inbox']`` and get
 * ``ProjectRFIInboxPayload`` back, mirroring the dashboard hook.
 */
export interface ProjectDetailPayloadMap {
  project_rfi_inbox: ProjectRFIInboxPayload;
  project_change_orders_pulse: ProjectChangeOrdersPulsePayload;
  project_daily_diary: ProjectDailyDiaryPayload;
  project_hse_incidents: ProjectHSEIncidentsPayload;
  project_variations: ProjectVariationsPayload;
  project_quality_ncr: ProjectQualityNCRPayload;
  project_compliance_summary: ProjectComplianceSummaryPayload;
  project_budget_burn: ProjectBudgetBurnPayload;
  project_lps_ppc: ProjectLpsPpcPayload;
  project_sub_insurance: ProjectSubInsurancePayload;
}

/**
 * Unified rollup response — superset of the dashboard and project-detail
 * widget shapes. Only requested keys are populated; consumers use ``in``
 * (or the typed ``byWidget`` helper) to detect coverage.
 */
export interface DashboardRollupResponse {
  // Wave-2 dashboard widgets.
  boq_summary?: import('@/features/dashboard/hooks/useDashboardRollup').BOQSummaryPayload;
  validation_score?: import('@/features/dashboard/hooks/useDashboardRollup').ValidationScorePayload;
  clash_health?: import('@/features/dashboard/hooks/useDashboardRollup').ClashHealthPayload;
  schedule_critical?: import('@/features/dashboard/hooks/useDashboardRollup').ScheduleCriticalPayload;
  risk_top?: import('@/features/dashboard/hooks/useDashboardRollup').RiskTopPayload;
  hse_scorecard?: import('@/features/dashboard/hooks/useDashboardRollup').HSEScorecardPayload;
  procurement_pipeline?: import('@/features/dashboard/hooks/useDashboardRollup').ProcurementPipelinePayload;
  budget_variance?: import('@/features/dashboard/hooks/useDashboardRollup').BudgetVariancePayload;
  change_orders?: import('@/features/dashboard/hooks/useDashboardRollup').ChangeOrdersPayload;
  weather_site?: import('@/features/dashboard/hooks/useDashboardRollup').WeatherSitePayload;

  // Project-detail widgets.
  project_rfi_inbox?: ProjectRFIInboxPayload;
  project_change_orders_pulse?: ProjectChangeOrdersPulsePayload;
  project_daily_diary?: ProjectDailyDiaryPayload;
  project_hse_incidents?: ProjectHSEIncidentsPayload;
  project_variations?: ProjectVariationsPayload;
  project_quality_ncr?: ProjectQualityNCRPayload;
  project_compliance_summary?: ProjectComplianceSummaryPayload;
  project_budget_burn?: ProjectBudgetBurnPayload;
  project_lps_ppc?: ProjectLpsPpcPayload;
  project_sub_insurance?: ProjectSubInsurancePayload;

  // Envelope metadata.
  generated_at?: string;
  widgets_requested?: string[];
  project_count?: number;
}

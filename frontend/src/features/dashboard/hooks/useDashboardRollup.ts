// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useDashboardRollup — single React Query that fetches all wave-2
 * dashboard widget payloads in ONE round-trip to the backend.
 *
 * Replaces the per-widget `Promise.all(projects.map(...))` fan-out the
 * old NewWidgets.tsx hooks did (50 projects × 10 widgets = 500 HTTP
 * calls per dashboard mount). Now: exactly one call to
 * `GET /api/v1/dashboard/rollup/`.
 *
 * The hook exposes:
 *  - `data`     — the full rollup payload keyed by widget id
 *  - `byWidget` — typed shortcut: `byWidget('boq_summary')` returns
 *                 just that widget's slice (or `null` if missing)
 *  - `isLoading`, `error` — pass-through from React Query
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

export type DashboardWidgetId =
  | 'boq_summary'
  | 'validation_score'
  | 'clash_health'
  | 'schedule_critical'
  | 'risk_top'
  | 'hse_scorecard'
  | 'procurement_pipeline'
  | 'budget_variance'
  | 'change_orders'
  | 'weather_site';

/* ── Per-widget payload types (mirror backend schemas.py) ─────────────── */

export interface BOQByProject {
  project_id: string;
  project_name: string;
  boq_count: number;
  total_value: string;
  currency: string;
  position_count: number;
  positions_missing_quantity: number;
  positions_zero_price: number;
}

export interface LastBOQRef {
  id: string;
  name: string;
  project_id: string;
  project_name: string;
  currency: string;
  status: string | null;
  updated_at: string;
  position_count: number;
  grand_total: string;
}

/** Per-currency money subtotal in a cross-project rollup. */
export interface CurrencySubtotal {
  currency: string;
  total_value: string;
}

export interface BOQSummaryPayload {
  total_boqs: number;
  /** BOQs whose status is NOT archived / closed / cancelled / rejected. */
  active_boqs: number;
  total_value_eur: string;
  /** FX-correct per-currency subtotals of BOQ value (preferred over the
      legacy blended ``total_value_eur`` scalar). */
  by_currency?: CurrencySubtotal[];
  /** True when projects span more than one ISO currency. */
  multi_currency?: boolean;
  position_count: number;
  positions_missing_quantity: number;
  positions_zero_price: number;
  last_boq: LastBOQRef | null;
  by_project: BOQByProject[];
}

export interface ValidationByProject {
  project_id: string;
  project_name: string;
  avg_score: number | null;
  passed: number;
  warnings: number;
  errors: number;
}

export interface ValidationScorePayload {
  avg: number | null;
  passed: number;
  warnings: number;
  errors: number;
  by_project: ValidationByProject[];
}

export interface ClashByProject {
  project_id: string;
  project_name: string;
  total: number;
  open: number;
  high: number;
  medium: number;
  low: number;
}

export interface ClashHealthPayload {
  total: number;
  open: number;
  high: number;
  medium: number;
  low: number;
  pct_resolved: number;
  by_project: ClashByProject[];
}

export interface CriticalTaskItem {
  id: string;
  name: string;
  project_id: string;
  project_name: string;
  start_date: string | null;
  end_date: string | null;
  status: string | null;
  is_critical: boolean;
  total_float: number | null;
}

export interface ScheduleCriticalPayload {
  /** Count of schedule rows across all of the caller's projects. */
  total_schedules: number;
  top: CriticalTaskItem[];
}

export interface RiskItemRow {
  id: string;
  project_id: string;
  project_name: string;
  title: string;
  score: number;
  probability: number;
  impact_severity: string;
  status: string | null;
}

export interface RiskTopPayload {
  top: RiskItemRow[];
}

export interface HSEByProject {
  project_id: string;
  project_name: string;
  total: number;
  last_30d: number;
  near_miss: number;
  recordables: number;
  days_since_last: number | null;
}

export interface HSEScorecardPayload {
  total: number;
  last_30d: number;
  near_miss: number;
  recordables: number;
  days_since_last: number | null;
  by_project: HSEByProject[];
}

export interface ProcurementPipelinePayload {
  rfqs_pending: number;
  pos_issued: number;
  pos_received: number;
}

export interface BudgetByProject {
  project_id: string;
  project_name: string;
  currency: string;
  planned: string;
  committed: string;
  actual: string;
  /** Expected final cost: a recorded forecast, else the commitment, else spend. */
  outturn: string;
  variance: string;
  pct: number;
}

export interface BudgetVariancePayload {
  over_budget_count: number;
  top_over: BudgetByProject[];
}

export interface ChangeOrderItem {
  id: string;
  project_id: string;
  project_name: string;
  code: string | null;
  title: string | null;
  status: string | null;
  cost_impact: string;
  currency: string;
}

/** Per-currency open change-order impact subtotal. */
export interface ChangeOrderCurrencySubtotal {
  currency: string;
  total_impact: string;
}

export interface ChangeOrdersPayload {
  open_count: number;
  total_impact: string;
  currency: string;
  /** FX-correct per-currency subtotals of open change-order impact. */
  by_currency?: ChangeOrderCurrencySubtotal[];
  /** True when open change orders span more than one ISO currency. */
  multi_currency?: boolean;
  top_pending: ChangeOrderItem[];
}

export interface WeatherSitePayload {
  project_id: string | null;
  project_name: string | null;
  city: string | null;
  temperature_c: number | null;
  conditions: string | null;
  source: string | null;
}

/** Top-level rollup payload — exactly what `GET /dashboard/rollup/` returns. */
export interface DashboardRollupPayload {
  boq_summary?: BOQSummaryPayload;
  validation_score?: ValidationScorePayload;
  clash_health?: ClashHealthPayload;
  schedule_critical?: ScheduleCriticalPayload;
  risk_top?: RiskTopPayload;
  hse_scorecard?: HSEScorecardPayload;
  procurement_pipeline?: ProcurementPipelinePayload;
  budget_variance?: BudgetVariancePayload;
  change_orders?: ChangeOrdersPayload;
  weather_site?: WeatherSitePayload;
  generated_at?: string;
  widgets_requested?: string[];
  project_count?: number;
}

/** Map from widget id → its payload type (for `byWidget` lookups). */
export interface WidgetPayloadMap {
  boq_summary: BOQSummaryPayload;
  validation_score: ValidationScorePayload;
  clash_health: ClashHealthPayload;
  schedule_critical: ScheduleCriticalPayload;
  risk_top: RiskTopPayload;
  hse_scorecard: HSEScorecardPayload;
  procurement_pipeline: ProcurementPipelinePayload;
  budget_variance: BudgetVariancePayload;
  change_orders: ChangeOrdersPayload;
  weather_site: WeatherSitePayload;
}

const ALL_WIDGETS: DashboardWidgetId[] = [
  'boq_summary',
  'validation_score',
  'clash_health',
  'schedule_critical',
  'risk_top',
  'hse_scorecard',
  'procurement_pipeline',
  'budget_variance',
  'change_orders',
  'weather_site',
];

export interface UseDashboardRollupOptions {
  /** Restrict the rollup to these widget ids. Defaults to all 10. */
  widgets?: readonly DashboardWidgetId[];
  /** Restrict to these project ids. Defaults to all accessible projects. */
  projectIds?: readonly string[];
  /** Disable the query entirely (e.g. while auth is still loading). */
  enabled?: boolean;
}

export function useDashboardRollup(options: UseDashboardRollupOptions = {}) {
  const widgets = options.widgets ?? ALL_WIDGETS;
  const projectIds = options.projectIds;
  const enabled = options.enabled ?? true;

  const widgetsCsv = widgets.slice().sort().join(',');
  const projectsCsv = projectIds?.slice().sort().join(',') ?? '';

  const query = useQuery({
    queryKey: ['dashboard-rollup', widgetsCsv, projectsCsv],
    queryFn: async (): Promise<DashboardRollupPayload> => {
      const params = new URLSearchParams();
      params.set('widgets', widgetsCsv);
      if (projectsCsv) params.set('project_ids', projectsCsv);
      return apiGet<DashboardRollupPayload>(
        `/v1/dashboard/rollup/?${params.toString()}`,
      );
    },
    enabled,
    retry: false,
    // Server already sends `Cache-Control: max-age=60`; mirror that on
    // the client so we don't ping the API more than once per minute per
    // mount even with React Query's default refetch heuristics.
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const byWidget = useMemo(
    () =>
      <K extends DashboardWidgetId>(id: K): WidgetPayloadMap[K] | null => {
        const data = query.data;
        if (!data) return null;
        return (data[id] as WidgetPayloadMap[K] | undefined) ?? null;
      },
    [query.data],
  );

  return {
    ...query,
    byWidget,
  };
}

/**
 * ProjectAnalyticsGrid — 2x3 grid of cost analytics widgets (RFC 25).
 *
 * Widgets:
 *   1. Cost drivers (Pareto bar, top 5)
 *   2. Price volatility (bid spread bar)
 *   3. Schedule <-> cost correlation (stacked area, labour cost by phase)
 *   4. Vendor concentration (top 3 bidders' share)
 *   5. Scope coverage (% line count vs baseline)
 *   6. Real-time validation (live rule pass count)
 */

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  ResponsiveContainer,
} from 'recharts';
import { apiGet } from '@/shared/lib/api';
import { buildPareto, type ParetoInput } from './ParetoHelper';

export const PI_QUERY_STALE_MS = 60_000;

interface LineItemRow {
  position_id: string;
  description: string;
  total_cost: number;
  share_of_total: number;
}

interface BidVendor {
  company_name: string;
  total: number;
  currency: string;
  bid_count: number;
}

interface BidSpread {
  min: number;
  max: number;
  p25: number;
  p50: number;
  p75: number;
  mean: number;
  std: number;
  sample_size: number;
}

interface BidAnalysis {
  vendors: BidVendor[];
  outliers: Array<{ bid_id: string; company_name: string; total: number; reason: string }>;
  spread: BidSpread;
}

interface LaborCostPhase {
  phase: string;
  activity_count: number;
  labor_cost: number;
  total_cost: number;
  start_date: string | null;
  end_date: string | null;
}

interface LaborCostByPhase {
  phases: LaborCostPhase[];
  currency: string;
}

interface AnomalyRow {
  position_id: string;
  type: 'outlier' | 'jump' | 'format';
  severity: 'info' | 'warning' | 'error';
}

interface SummaryState {
  boq?: {
    position_count?: number;
    baseline_position_count?: number;
  };
  validation?: {
    rules_passed?: number;
    rules_total?: number;
    errors?: number;
    warnings?: number;
  };
}

interface SummaryResponse {
  state?: SummaryState;
}

interface ProjectAnalyticsGridProps {
  projectId: string;
}

const COLORS = ['#58a6ff', '#bc8cff', '#3fb950', '#f0883e', '#ffa657', '#8b949e'];

function WidgetCard({
  testId,
  title,
  subtitle,
  children,
}: {
  testId: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4 h-64 flex flex-col"
    >
      <div className="mb-2">
        <h4 className="text-xs font-semibold text-content-primary">{title}</h4>
        {subtitle && (
          <p className="text-2xs text-content-tertiary">{subtitle}</p>
        )}
      </div>
      <div className="flex-1 min-h-0">{children}</div>
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="h-full flex items-center justify-center text-2xs text-content-tertiary">
      {label}
    </div>
  );
}

export function ProjectAnalyticsGrid({ projectId }: ProjectAnalyticsGridProps) {
  const { t } = useTranslation();

  const lineItemsQ = useQuery({
    queryKey: ['pi', 'line-items', projectId],
    queryFn: () =>
      apiGet<LineItemRow[]>(
        `/v1/boq/line-items/?project_id=${projectId}&group=cost&top_n=20`,
      ),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const bidAnalysisQ = useQuery({
    queryKey: ['pi', 'bid-analysis', projectId],
    queryFn: () =>
      apiGet<BidAnalysis>(`/v1/tendering/bid-analysis/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const laborCostQ = useQuery({
    queryKey: ['pi', 'labor-cost-by-phase', projectId],
    queryFn: () =>
      apiGet<LaborCostByPhase>(
        `/v1/schedule/labor-cost-by-phase/?project_id=${projectId}`,
      ),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const anomaliesQ = useQuery({
    queryKey: ['pi', 'anomalies', projectId],
    queryFn: () => apiGet<AnomalyRow[]>(`/v1/boq/anomalies/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const summaryQ = useQuery({
    queryKey: ['pi', 'summary', projectId],
    queryFn: () =>
      apiGet<SummaryResponse>(`/v1/project_intelligence/summary/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  // ── Widget 1: Cost drivers (Pareto) ────────────────────────────────────
  const pareto = useMemo(() => {
    const rows = (lineItemsQ.data ?? []) as ParetoInput[];
    return buildPareto(rows, 5);
  }, [lineItemsQ.data]);

  // ── Widget 2: Price volatility (bid spread) ────────────────────────────
  const volatility = useMemo(() => {
    const s = bidAnalysisQ.data?.spread;
    if (!s || s.sample_size === 0) return [];
    return [
      { name: 'min', value: s.min },
      { name: 'p25', value: s.p25 },
      { name: 'p50', value: s.p50 },
      { name: 'p75', value: s.p75 },
      { name: 'max', value: s.max },
    ];
  }, [bidAnalysisQ.data]);

  // ── Widget 3: Schedule <-> cost correlation ────────────────────────────
  const laborPhases = laborCostQ.data?.phases ?? [];

  // ── Widget 4: Vendor concentration (top 3 share) ───────────────────────
  const vendorPie = useMemo(() => {
    const vendors = bidAnalysisQ.data?.vendors ?? [];
    if (vendors.length === 0) return [];
    const top3 = vendors.slice(0, 3);
    const rest = vendors.slice(3);
    const pieData = top3.map((v) => ({ name: v.company_name, value: v.total }));
    if (rest.length > 0) {
      pieData.push({
        name: 'other',
        value: rest.reduce((acc, v) => acc + v.total, 0),
      });
    }
    return pieData;
  }, [bidAnalysisQ.data]);

  // ── Widget 5: Scope coverage ──────────────────────────────────────────
  const coverage = useMemo(() => {
    const boq = summaryQ.data?.state?.boq;
    const current = boq?.position_count ?? 0;
    const baseline = boq?.baseline_position_count ?? current;
    const pct = baseline > 0 ? Math.min(100, (current / baseline) * 100) : 0;
    return { current, baseline, pct };
  }, [summaryQ.data]);

  // ── Widget 6: Real-time validation ─────────────────────────────────────
  const validation = useMemo(() => {
    const v = summaryQ.data?.state?.validation;
    const anomalies = anomaliesQ.data ?? [];
    const passed = v?.rules_passed ?? 0;
    const total = v?.rules_total ?? passed + anomalies.length;
    const errors = (v?.errors ?? 0) + anomalies.filter((a) => a.severity === 'error').length;
    const warnings =
      (v?.warnings ?? 0) + anomalies.filter((a) => a.severity === 'warning').length;
    return { passed, total, errors, warnings };
  }, [summaryQ.data, anomaliesQ.data]);

  const emptyLabel = t('project_intelligence.analytics.no_data', {
    defaultValue: 'No data yet',
  });

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {/* 1. Cost drivers (Pareto) */}
      <WidgetCard
        testId="pi-widget-cost-drivers"
        title={t('project_intelligence.analytics.cost_drivers', {
          defaultValue: 'Cost drivers',
        })}
        subtitle={t('project_intelligence.analytics.cost_drivers_sub', {
          defaultValue: 'Top 5 line items by total cost',
        })}
      >
        {pareto.length === 0 ? (
          <Empty label={emptyLabel} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={pareto} margin={{ left: 0, right: 8, top: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#8b949e22" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 9 }}
                interval={0}
                angle={-20}
                textAnchor="end"
                height={36}
              />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#58a6ff" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </WidgetCard>

      {/* 2. Price volatility */}
      <WidgetCard
        testId="pi-widget-price-volatility"
        title={t('project_intelligence.analytics.price_volatility', {
          defaultValue: 'Price volatility',
        })}
        subtitle={t('project_intelligence.analytics.price_volatility_sub', {
          defaultValue: 'Bid total spread across vendors',
        })}
      >
        {volatility.length === 0 ? (
          <Empty label={emptyLabel} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={volatility} margin={{ left: 0, right: 8, top: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#8b949e22" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#bc8cff" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </WidgetCard>

      {/* 3. Schedule <-> cost correlation */}
      <WidgetCard
        testId="pi-widget-schedule-cost"
        title={t('project_intelligence.analytics.schedule_cost', {
          defaultValue: 'Schedule ↔ cost',
        })}
        subtitle={t('project_intelligence.analytics.schedule_cost_sub', {
          defaultValue: 'Labour cost by phase',
        })}
      >
        {laborPhases.length === 0 ? (
          <Empty label={emptyLabel} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={laborPhases}
              margin={{ left: 0, right: 8, top: 4, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#8b949e22" />
              <XAxis dataKey="phase" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="labor_cost"
                stackId="1"
                stroke="#3fb950"
                fill="#3fb95033"
              />
              <Area
                type="monotone"
                dataKey="total_cost"
                stackId="1"
                stroke="#58a6ff"
                fill="#58a6ff33"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </WidgetCard>

      {/* 4. Vendor concentration */}
      <WidgetCard
        testId="pi-widget-vendor-concentration"
        title={t('project_intelligence.analytics.vendor_concentration', {
          defaultValue: 'Vendor concentration',
        })}
        subtitle={t('project_intelligence.analytics.vendor_concentration_sub', {
          defaultValue: 'Top 3 bidders\u2019 share',
        })}
      >
        {vendorPie.length === 0 ? (
          <Empty label={emptyLabel} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={vendorPie}
                dataKey="value"
                nameKey="name"
                innerRadius="45%"
                outerRadius="75%"
              >
                {vendorPie.map((_entry, idx) => (
                  <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        )}
      </WidgetCard>

      {/* 5. Scope coverage */}
      <WidgetCard
        testId="pi-widget-scope-coverage"
        title={t('project_intelligence.analytics.scope_coverage', {
          defaultValue: 'Scope coverage',
        })}
        subtitle={t('project_intelligence.analytics.scope_coverage_sub', {
          defaultValue: 'BOQ line count vs baseline',
        })}
      >
        <div className="h-full flex flex-col items-center justify-center">
          <div className="text-3xl font-bold text-content-primary tabular-nums">
            {coverage.pct.toFixed(0)}%
          </div>
          <div className="text-2xs text-content-tertiary mt-1">
            {t('project_intelligence.analytics.scope_coverage_ratio', {
              defaultValue: '{{current}} of {{baseline}} lines',
              current: coverage.current,
              baseline: coverage.baseline,
            })}
          </div>
        </div>
      </WidgetCard>

      {/* 6. Real-time validation */}
      <WidgetCard
        testId="pi-widget-validation"
        title={t('project_intelligence.analytics.validation_live', {
          defaultValue: 'Real-time validation',
        })}
        subtitle={t('project_intelligence.analytics.validation_live_sub', {
          defaultValue: 'Rule pass count (updates every 60s)',
        })}
      >
        <div className="h-full flex flex-col items-center justify-center gap-1">
          <div className="text-3xl font-bold text-content-primary tabular-nums">
            {validation.passed}
            <span className="text-lg text-content-tertiary font-normal">
              {' '}
              / {validation.total}
            </span>
          </div>
          <div className="flex items-center gap-3 text-2xs mt-1">
            <span className="text-rose-500">
              {validation.errors}{' '}
              {t('project_intelligence.analytics.errors', {
                defaultValue: 'errors',
              })}
            </span>
            <span className="text-amber-500">
              {validation.warnings}{' '}
              {t('project_intelligence.analytics.warnings', {
                defaultValue: 'warnings',
              })}
            </span>
          </div>
        </div>
      </WidgetCard>
    </div>
  );
}

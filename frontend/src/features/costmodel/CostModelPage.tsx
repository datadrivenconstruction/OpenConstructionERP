import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ChevronRight,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Camera,
  BarChart3,
  Banknote,
  Activity,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import {
  costModelApi,
  type SCurvePoint,
  type BudgetCategorySummary,
} from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
  currency: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency || 'EUR',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatCompact(amount: number, currency: string): string {
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) {
    return `${(amount / 1_000_000).toFixed(1)}M ${currency}`;
  }
  if (abs >= 1_000) {
    return `${(amount / 1_000).toFixed(0)}K ${currency}`;
  }
  return formatCurrency(amount, currency);
}

function varianceColor(variance: number): string {
  if (variance < 0) return 'text-[#15803d]';
  if (variance > 0) return 'text-semantic-error';
  return 'text-content-secondary';
}

function varianceBg(variance: number): string {
  if (variance < 0) return 'bg-semantic-success-bg';
  if (variance > 0) return 'bg-semantic-error-bg';
  return 'bg-surface-secondary';
}

/* ── KPI Card ──────────────────────────────────────────────────────────── */

function KPICard({
  label,
  amount,
  currency,
  variance,
  icon,
}: {
  label: string;
  amount: number;
  currency: string;
  variance?: number;
  icon: React.ReactNode;
}) {
  return (
    <Card padding="none" className="flex-1 min-w-[200px]">
      <div className="p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
            {label}
          </span>
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
            {icon}
          </div>
        </div>
        <div className="text-2xl font-bold tabular-nums text-content-primary">
          {formatCurrency(amount, currency)}
        </div>
        {variance !== undefined && variance !== 0 && (
          <div className="mt-2 flex items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${varianceBg(variance)} ${varianceColor(variance)}`}
            >
              {variance > 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {variance > 0 ? '+' : ''}
              {formatCompact(variance, currency)}
            </span>
            <span className="text-2xs text-content-tertiary">vs budget</span>
          </div>
        )}
      </div>
    </Card>
  );
}

/* ── SPI / CPI Indicator ───────────────────────────────────────────────── */

function PerformanceIndicator({
  label,
  value,
  description,
}: {
  label: string;
  value: number;
  description: string;
}) {
  const isHealthy = value >= 1.0;
  const displayValue = value.toFixed(2);

  return (
    <div className="flex items-center gap-4">
      <div
        className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-lg font-bold tabular-nums ${
          isHealthy
            ? 'bg-semantic-success-bg text-[#15803d]'
            : 'bg-semantic-error-bg text-semantic-error'
        }`}
      >
        {displayValue}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">{label}</span>
          <Badge variant={isHealthy ? 'success' : 'error'} size="sm">
            {isHealthy ? 'On Track' : 'At Risk'}
          </Badge>
        </div>
        <p className="mt-0.5 text-xs text-content-secondary">{description}</p>
      </div>
    </div>
  );
}

/* ── S-Curve Chart (SVG) ───────────────────────────────────────────────── */

function SCurveChart({ data }: { data: SCurvePoint[] }) {
  const { t } = useTranslation();

  const chartDimensions = useMemo(() => {
    const width = 720;
    const height = 320;
    const padding = { top: 24, right: 24, bottom: 48, left: 72 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    return { width, height, padding, plotWidth, plotHeight };
  }, []);

  const { scales, gridLines } = useMemo(() => {
    const allValues = data.flatMap((d) => [d.planned, d.earned, d.actual]);
    const maxVal = Math.max(...allValues, 1);
    const niceMax = Math.ceil(maxVal / 100_000) * 100_000 || maxVal;

    const xScale = (i: number): number =>
      chartDimensions.padding.left +
      (i / Math.max(data.length - 1, 1)) * chartDimensions.plotWidth;
    const yScale = (v: number): number =>
      chartDimensions.padding.top +
      chartDimensions.plotHeight -
      (v / niceMax) * chartDimensions.plotHeight;

    const gridCount = 5;
    const gridLinesArr = Array.from({ length: gridCount + 1 }, (_, i) => ({
      value: (niceMax / gridCount) * i,
      y: yScale((niceMax / gridCount) * i),
    }));

    return { scales: { x: xScale, y: yScale, maxVal: niceMax }, gridLines: gridLinesArr };
  }, [data, chartDimensions]);

  function buildPath(values: number[]): string {
    return values
      .map(
        (v, i) =>
          `${i === 0 ? 'M' : 'L'} ${scales.x(i).toFixed(1)} ${scales.y(v).toFixed(1)}`,
      )
      .join(' ');
  }

  const plannedPath = buildPath(data.map((d) => d.planned));
  const earnedPath = buildPath(data.map((d) => d.earned));
  const actualPath = buildPath(data.map((d) => d.actual));

  const { padding, width, height, plotWidth, plotHeight } = chartDimensions;

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ minWidth: 480 }}
        aria-label={t('costmodel.s_curve_chart', 'S-Curve Chart')}
      >
        {/* Grid lines */}
        {gridLines.map((line) => (
          <g key={line.value}>
            <line
              x1={padding.left}
              y1={line.y}
              x2={padding.left + plotWidth}
              y2={line.y}
              stroke="currentColor"
              className="text-border-light"
              strokeWidth={0.5}
              strokeDasharray={line.value === 0 ? undefined : '4 4'}
            />
            <text
              x={padding.left - 8}
              y={line.y + 4}
              textAnchor="end"
              className="fill-content-tertiary"
              fontSize={10}
              fontFamily="system-ui"
            >
              {formatCompact(line.value, '')}
            </text>
          </g>
        ))}

        {/* X axis labels */}
        {data.map((d, i) => {
          const showLabel =
            data.length <= 12 || i % Math.ceil(data.length / 12) === 0;
          if (!showLabel) return null;
          return (
            <text
              key={d.period}
              x={scales.x(i)}
              y={padding.top + plotHeight + 24}
              textAnchor="middle"
              className="fill-content-tertiary"
              fontSize={10}
              fontFamily="system-ui"
            >
              {d.period}
            </text>
          );
        })}

        {/* Axis lines */}
        <line
          x1={padding.left}
          y1={padding.top}
          x2={padding.left}
          y2={padding.top + plotHeight}
          stroke="currentColor"
          className="text-border-light"
          strokeWidth={1}
        />
        <line
          x1={padding.left}
          y1={padding.top + plotHeight}
          x2={padding.left + plotWidth}
          y2={padding.top + plotHeight}
          stroke="currentColor"
          className="text-border-light"
          strokeWidth={1}
        />

        {/* Data lines */}
        <path
          d={plannedPath}
          fill="none"
          stroke="#2563eb"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={earnedPath}
          fill="none"
          stroke="#16a34a"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={actualPath}
          fill="none"
          stroke="#dc2626"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Data points */}
        {data.map((d, i) => (
          <g key={`dots-${d.period}`}>
            <circle cx={scales.x(i)} cy={scales.y(d.planned)} r={3} fill="#2563eb" />
            <circle cx={scales.x(i)} cy={scales.y(d.earned)} r={3} fill="#16a34a" />
            <circle cx={scales.x(i)} cy={scales.y(d.actual)} r={3} fill="#dc2626" />
          </g>
        ))}

        {/* Legend */}
        <g transform={`translate(${padding.left + 16}, ${padding.top + 8})`}>
          <rect
            x={-8}
            y={-6}
            width={240}
            height={24}
            rx={6}
            fill="white"
            fillOpacity={0.85}
          />
          <circle cx={4} cy={6} r={4} fill="#2563eb" />
          <text
            x={14}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.planned', 'Planned')}
          </text>
          <circle cx={80} cy={6} r={4} fill="#16a34a" />
          <text
            x={90}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.earned', 'Earned')}
          </text>
          <circle cx={154} cy={6} r={4} fill="#dc2626" />
          <text
            x={164}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.actual', 'Actual')}
          </text>
        </g>
      </svg>
    </div>
  );
}

/* ── Budget Category Table ─────────────────────────────────────────────── */

function BudgetTable({
  categories,
  currency,
}: {
  categories: BudgetCategorySummary[];
  currency: string;
}) {
  const { t } = useTranslation();

  const totals = useMemo(() => {
    return categories.reduce(
      (acc, cat) => ({
        planned: acc.planned + cat.planned,
        committed: acc.committed + cat.committed,
        actual: acc.actual + cat.actual,
        forecast: acc.forecast + cat.forecast,
        variance: acc.variance + cat.variance,
      }),
      { planned: 0, committed: 0, actual: 0, forecast: 0, variance: 0 },
    );
  }, [categories]);

  const categoryLabels: Record<string, string> = {
    material: t('costmodel.cat_material', 'Material'),
    labor: t('costmodel.cat_labor', 'Labor'),
    equipment: t('costmodel.cat_equipment', 'Equipment'),
    subcontractor: t('costmodel.cat_subcontractor', 'Subcontractor'),
    overhead: t('costmodel.cat_overhead', 'Overhead'),
    contingency: t('costmodel.cat_contingency', 'Contingency'),
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light">
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.category', 'Category')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.planned', 'Planned')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.committed', 'Committed')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.actual', 'Actual')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.forecast', 'Forecast')}
            </th>
            <th className="py-3 pl-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.variance', 'Variance')}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {categories.map((cat) => (
            <tr key={cat.category} className="transition-colors hover:bg-surface-secondary/50">
              <td className="py-3 pr-4 font-medium text-content-primary">
                {categoryLabels[cat.category] || cat.category}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.planned, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.committed, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.actual, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.forecast, currency)}
              </td>
              <td
                className={`py-3 pl-4 text-right tabular-nums font-medium ${varianceColor(cat.variance)}`}
              >
                {cat.variance > 0 ? '+' : ''}
                {formatCurrency(cat.variance, currency)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border font-semibold">
            <td className="py-3 pr-4 text-content-primary">
              {t('costmodel.total', 'Total')}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.planned, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.committed, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.actual, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.forecast, currency)}
            </td>
            <td
              className={`py-3 pl-4 text-right tabular-nums font-bold ${varianceColor(totals.variance)}`}
            >
              {totals.variance > 0 ? '+' : ''}
              {formatCurrency(totals.variance, currency)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/* ── 5D Dashboard ──────────────────────────────────────────────────────── */

function FiveDDashboard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: dashboard, isLoading: dashboardLoading } = useQuery({
    queryKey: ['costmodel', 'dashboard', project.id],
    queryFn: () => costModelApi.getDashboard(project.id),
    retry: false,
  });

  const { data: sCurveData, isLoading: sCurveLoading } = useQuery({
    queryKey: ['costmodel', 's-curve', project.id],
    queryFn: () => costModelApi.getSCurve(project.id),
    retry: false,
  });

  const { data: budgetData, isLoading: budgetLoading } = useQuery({
    queryKey: ['costmodel', 'budget', project.id],
    queryFn: () => costModelApi.getBudgetSummary(project.id),
    retry: false,
  });

  const { data: boqs } = useQuery({
    queryKey: ['boqs', project.id],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${project.id}`),
    retry: false,
  });

  const generateBudget = useMutation({
    mutationFn: (boqId: string) => costModelApi.generateBudgetFromBoq(project.id, boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
  });

  const createSnapshot = useMutation({
    mutationFn: () => {
      const now = new Date();
      const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      return costModelApi.createSnapshot(project.id, { period });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
  });

  const generateCashFlow = useMutation({
    mutationFn: () => costModelApi.generateCashFlow(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
  });

  const currency = dashboard?.currency || project.currency || 'EUR';

  return (
    <div className="space-y-6">
      {/* Actions bar */}
      <div className="flex flex-wrap items-center gap-3">
        {boqs && boqs.length > 0 && (
          <Button
            variant="primary"
            size="sm"
            icon={<BarChart3 size={14} />}
            loading={generateBudget.isPending}
            onClick={() => { const firstBoq = boqs?.[0]; if (firstBoq) generateBudget.mutate(firstBoq.id); }}
          >
            {t('costmodel.generate_budget', 'Generate Budget from BOQ')}
          </Button>
        )}
        <Button
          variant="secondary"
          size="sm"
          icon={<Camera size={14} />}
          loading={createSnapshot.isPending}
          onClick={() => createSnapshot.mutate()}
        >
          {t('costmodel.create_snapshot', 'Create Snapshot')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<Banknote size={14} />}
          loading={generateCashFlow.isPending}
          onClick={() => generateCashFlow.mutate()}
        >
          {t('costmodel.generate_cash_flow', 'Generate Cash Flow')}
        </Button>
      </div>

      {/* KPI Cards */}
      {dashboardLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={120} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : dashboard ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KPICard
            label={t('costmodel.total_budget', 'Total Budget')}
            amount={dashboard.total_budget}
            currency={currency}
            icon={<DollarSign size={16} />}
          />
          <KPICard
            label={t('costmodel.committed', 'Committed')}
            amount={dashboard.total_committed}
            currency={currency}
            variance={dashboard.total_committed - dashboard.total_budget}
            icon={<Banknote size={16} />}
          />
          <KPICard
            label={t('costmodel.actual_spent', 'Actual Spent')}
            amount={dashboard.total_actual}
            currency={currency}
            variance={dashboard.total_actual - dashboard.total_budget}
            icon={<TrendingUp size={16} />}
          />
          <KPICard
            label={t('costmodel.forecast_eac', 'Forecast (EAC)')}
            amount={dashboard.total_forecast}
            currency={currency}
            variance={dashboard.total_forecast - dashboard.total_budget}
            icon={<Activity size={16} />}
          />
        </div>
      ) : (
        <EmptyState
          icon={<DollarSign size={24} strokeWidth={1.5} />}
          title={t('costmodel.no_budget', 'No budget data yet')}
          description={t(
            'costmodel.no_budget_hint',
            'Generate a budget from your BOQ to see cost metrics',
          )}
          action={
            boqs && boqs.length > 0 ? (
              <Button
                variant="primary"
                size="sm"
                icon={<BarChart3 size={14} />}
                loading={generateBudget.isPending}
                onClick={() => { const firstBoq = boqs?.[0]; if (firstBoq) generateBudget.mutate(firstBoq.id); }}
              >
                {t('costmodel.generate_budget', 'Generate Budget from BOQ')}
              </Button>
            ) : undefined
          }
        />
      )}

      {/* Performance Indicators + S-Curve row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* SPI / CPI */}
        <div>
          <Card>
            <CardHeader title={t('costmodel.performance', 'Performance')} />
            <CardContent>
              {dashboardLoading ? (
                <div className="space-y-4">
                  <Skeleton height={56} className="w-full" rounded="lg" />
                  <Skeleton height={56} className="w-full" rounded="lg" />
                </div>
              ) : dashboard ? (
                <div className="space-y-5">
                  <PerformanceIndicator
                    label="SPI"
                    value={dashboard.spi}
                    description={t(
                      'costmodel.spi_desc',
                      'Schedule Performance Index',
                    )}
                  />
                  <div className="border-t border-border-light" />
                  <PerformanceIndicator
                    label="CPI"
                    value={dashboard.cpi}
                    description={t('costmodel.cpi_desc', 'Cost Performance Index')}
                  />
                  {dashboard.variance !== 0 && (
                    <>
                      <div className="border-t border-border-light" />
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-content-secondary">
                          {t('costmodel.overall_variance', 'Overall Variance')}
                        </span>
                        <span
                          className={`text-sm font-semibold tabular-nums ${varianceColor(dashboard.variance)}`}
                        >
                          {dashboard.variance > 0 ? '+' : ''}
                          {dashboard.variance_pct.toFixed(1)}%
                        </span>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <p className="py-6 text-center text-sm text-content-secondary">
                  {t('costmodel.no_performance_data', 'No performance data available')}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* S-Curve */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader title={t('costmodel.s_curve', 'S-Curve (EVM)')} />
            <CardContent>
              {sCurveLoading ? (
                <Skeleton height={320} className="w-full" rounded="lg" />
              ) : sCurveData && sCurveData.periods.length > 0 ? (
                <SCurveChart data={sCurveData.periods} />
              ) : (
                <EmptyState
                  icon={<TrendingUp size={24} strokeWidth={1.5} />}
                  title={t('costmodel.no_s_curve', 'No S-Curve data')}
                  description={t(
                    'costmodel.no_s_curve_hint',
                    'Generate budget from BOQ and create snapshots to build the S-Curve',
                  )}
                  action={
                    boqs && boqs.length > 0 ? (
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<BarChart3 size={14} />}
                        loading={generateBudget.isPending}
                        onClick={() => { const firstBoq = boqs?.[0]; if (firstBoq) generateBudget.mutate(firstBoq.id); }}
                      >
                        {t('costmodel.generate_budget', 'Generate Budget from BOQ')}
                      </Button>
                    ) : undefined
                  }
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Budget by Category */}
      <Card>
        <CardHeader title={t('costmodel.budget_by_category', 'Budget by Category')} />
        <CardContent>
          {budgetLoading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} height={40} className="w-full" rounded="md" />
              ))}
            </div>
          ) : budgetData && budgetData.categories.length > 0 ? (
            <BudgetTable categories={budgetData.categories} currency={currency} />
          ) : (
            <div className="py-8 text-center">
              <p className="text-sm text-content-secondary">
                {t(
                  'costmodel.no_categories',
                  'No budget categories yet. Generate a budget from BOQ to populate this table.',
                )}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CostModelPage() {
  const { t } = useTranslation();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const selectedProject = selectedProjectId
    ? projects?.find((p) => p.id === selectedProjectId)
    : null;

  // Project detail view with 5D dashboard
  if (selectedProject) {
    return (
      <div className="max-w-content mx-auto animate-fade-in">
        <button
          onClick={() => setSelectedProjectId(null)}
          className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
        >
          <ArrowLeft size={14} />
          {t('costmodel.back_to_projects', 'Back to projects')}
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-content-primary">{selectedProject.name}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('costmodel.dashboard_subtitle', '5D Cost Model Dashboard')}
          </p>
        </div>

        <FiveDDashboard project={selectedProject} />
      </div>
    );
  }

  // Project selector view
  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('costmodel.title', '5D Cost Model')}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'costmodel.subtitle',
            'Select a project to view its 5D cost management dashboard',
          )}
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<DollarSign size={24} strokeWidth={1.5} />}
          title={t('costmodel.no_projects', 'No projects available')}
          description={t(
            'costmodel.no_projects_hint',
            'Create a project first, then come back to manage its 5D cost model',
          )}
        />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setSelectedProjectId(project.id)}
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
                  {project.currency || 'EUR'}
                </Badge>
                <Badge variant="neutral" size="sm">
                  {project.classification_standard}
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

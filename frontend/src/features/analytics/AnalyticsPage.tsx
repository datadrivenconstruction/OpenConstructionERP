import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { fmtCurrency, fmtNumber, getIntlLocale } from '@/shared/lib/formatters';
import {
  FolderOpen,
  DollarSign,
  TrendingDown,
  AlertTriangle,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  Download,
} from 'lucide-react';
import { Breadcrumb, Button, Card, Badge, Skeleton } from '@/shared/ui';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function compactCurrency(value: number, currency = 'EUR'): string {
  const safe = currency && /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: safe,
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(value);
  } catch {
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M ${safe}`;
    if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(0)}K ${safe}`;
    return `${value.toFixed(0)} ${safe}`;
  }
}

/* ── Types ────────────────────────────────────────────────────────────── */

interface ProjectAnalytics {
  id: string;
  name: string;
  region: string;
  currency: string;
  budget: number;
  actual: number;
  variance: number;
  variance_pct: number;
  boq_count: number;
  status: 'on_budget' | 'over_budget';
}

interface AnalyticsOverview {
  total_projects: number;
  projects_with_budget: number;
  total_planned: number;
  total_actual: number;
  total_variance: number;
  over_budget_count: number;
  projects: ProjectAnalytics[];
}

type SortField = 'name' | 'budget' | 'actual' | 'variance' | 'variance_pct';
type SortDir = 'asc' | 'desc';

/* ── Component ────────────────────────────────────────────────────────── */

export function AnalyticsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [sortField, setSortField] = useState<SortField>('budget');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [regionFilter, setRegionFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery<AnalyticsOverview>({
    queryKey: ['analytics', 'overview'],
    queryFn: () => apiGet<AnalyticsOverview>('/v1/projects/analytics/overview'),
  });

  const regions = useMemo(() => {
    if (!data?.projects) return [];
    return [...new Set(data.projects.map(p => p.region).filter(Boolean))].sort();
  }, [data?.projects]);

  const sortedProjects = useMemo(() => {
    if (!data?.projects) return [];
    let filtered = data.projects;
    if (regionFilter) filtered = filtered.filter(p => p.region === regionFilter);
    if (statusFilter) filtered = filtered.filter(p => p.status === statusFilter);
    if (search) {
      const q = search.toLowerCase();
      filtered = filtered.filter(p => p.name.toLowerCase().includes(q));
    }
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') {
        cmp = a.name.localeCompare(b.name);
      } else {
        cmp = (a[sortField] ?? 0) - (b[sortField] ?? 0);
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data?.projects, sortField, sortDir, regionFilter, statusFilter, search]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const handleExportCSV = useCallback(() => {
    if (!sortedProjects.length) return;
    const headers = ['Project', 'Region', 'Currency', 'Budget', 'Actual', 'Variance', 'Variance %', 'Status'];
    const rows = sortedProjects.map(p => [
      `"${p.name.replace(/"/g, '""')}"`,
      p.region,
      p.currency,
      p.budget.toFixed(0),
      p.actual.toFixed(0),
      p.variance.toFixed(0),
      `${p.variance_pct.toFixed(1)}%`,
      p.status,
    ].join(','));
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'analytics_export.csv';
    a.click();
    URL.revokeObjectURL(url);
  }, [sortedProjects]);

  // Find the max budget for bar chart scaling
  const maxBudget = useMemo(() => {
    if (!sortedProjects.length) return 1;
    return Math.max(...sortedProjects.map((p) => Math.max(p.budget, p.actual)), 1);
  }, [sortedProjects]);

  const totalVariancePct =
    data && data.total_planned > 0
      ? ((data.total_variance / data.total_planned) * 100).toFixed(1)
      : '0.0';

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-8 w-64 mb-2" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <Skeleton className="h-4 w-24 mb-3" />
              <Skeleton className="h-8 w-32" />
            </Card>
          ))}
        </div>
        <Card>
          <Skeleton className="h-6 w-48 mb-4" />
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('analytics.title', { defaultValue: 'Analytics' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('analytics.title', { defaultValue: 'Cross-Project Analytics' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('analytics.subtitle', {
              defaultValue: 'Aggregated KPIs across all projects',
            })}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download size={14} />}
          onClick={handleExportCSV}
          disabled={!sortedProjects.length}
        >
          {t('analytics.export_csv', { defaultValue: 'Export CSV' })}
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          icon={<FolderOpen size={20} />}
          iconBg="bg-oe-blue-subtle"
          iconColor="text-oe-blue"
          label={t('analytics.total_projects', { defaultValue: 'Total Projects' })}
          value={String(data?.total_projects ?? 0)}
          sub={t('analytics.with_budget', {
            defaultValue: '{{count}} with budget',
            count: data?.projects_with_budget ?? 0,
          })}
        />
        <KPICard
          icon={<DollarSign size={20} />}
          iconBg="bg-semantic-success-bg"
          iconColor="text-semantic-success"
          label={t('analytics.total_budget', { defaultValue: 'Total Budget' })}
          value={compactCurrency(data?.total_planned ?? 0)}
          sub={t('analytics.actual_spend', {
            defaultValue: '{{amount}} actual',
            amount: compactCurrency(data?.total_actual ?? 0),
          })}
        />
        <KPICard
          icon={<TrendingDown size={20} />}
          iconBg={
            (data?.total_variance ?? 0) >= 0
              ? 'bg-semantic-success-bg'
              : 'bg-semantic-error-bg'
          }
          iconColor={
            (data?.total_variance ?? 0) >= 0 ? 'text-semantic-success' : 'text-semantic-error'
          }
          label={t('analytics.overall_variance', { defaultValue: 'Overall Variance' })}
          value={compactCurrency(data?.total_variance ?? 0)}
          badge={
            <Badge
              variant={(data?.total_variance ?? 0) >= 0 ? 'success' : 'error'}
              size="sm"
            >
              {totalVariancePct}%
            </Badge>
          }
        />
        <KPICard
          icon={<AlertTriangle size={20} />}
          iconBg={
            (data?.over_budget_count ?? 0) > 0
              ? 'bg-semantic-error-bg'
              : 'bg-semantic-success-bg'
          }
          iconColor={
            (data?.over_budget_count ?? 0) > 0 ? 'text-semantic-error' : 'text-semantic-success'
          }
          label={t('analytics.at_risk', { defaultValue: 'Projects at Risk' })}
          value={String(data?.over_budget_count ?? 0)}
          sub={t('analytics.over_budget_label', { defaultValue: 'over budget' })}
        />
      </div>

      {/* Projects Comparison Table */}
      <Card padding="none">
        <div className="px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('analytics.project_comparison', { defaultValue: 'Project Comparison' })}
          </h2>
        </div>
        <div className="px-6 py-3 border-b border-border-light flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('analytics.search_placeholder', { defaultValue: 'Search projects...' })}
            className="h-8 w-48 rounded-lg border border-border-light bg-surface-primary px-3 text-xs focus:outline-none focus:ring-1 focus:ring-oe-blue"
            aria-label={t('analytics.search_placeholder', { defaultValue: 'Search projects...' })}
          />
          <select
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
            className="h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs focus:outline-none focus:ring-1 focus:ring-oe-blue"
            aria-label={t('analytics.filter_region', { defaultValue: 'Filter by region' })}
          >
            <option value="">{t('analytics.all_regions', { defaultValue: 'All Regions' })}</option>
            {regions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs focus:outline-none focus:ring-1 focus:ring-oe-blue"
            aria-label={t('analytics.filter_status', { defaultValue: 'Filter by status' })}
          >
            <option value="">{t('analytics.all_statuses', { defaultValue: 'All Statuses' })}</option>
            <option value="on_budget">{t('analytics.on_budget', { defaultValue: 'On Budget' })}</option>
            <option value="over_budget">{t('analytics.over_budget', { defaultValue: 'Over Budget' })}</option>
          </select>
          <span className="text-2xs text-content-tertiary ml-auto">
            {sortedProjects.length} {t('analytics.of_total', { defaultValue: 'of' })} {data?.projects.length ?? 0}
          </span>
        </div>
        {sortedProjects.length === 0 ? (
          <div className="px-6 py-12 text-center text-content-tertiary text-sm">
            {t('analytics.no_projects', {
              defaultValue: 'No projects found. Create a project to see analytics.',
            })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary/50">
                  <SortHeader
                    field="name"
                    label={t('analytics.col_project', { defaultValue: 'Project' })}
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                  <th className="px-4 py-3 text-left text-xs font-medium text-content-tertiary uppercase tracking-wider">
                    {t('analytics.col_region', { defaultValue: 'Region' })}
                  </th>
                  <SortHeader
                    field="budget"
                    label={t('analytics.col_budget', { defaultValue: 'Budget' })}
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                    align="right"
                  />
                  <SortHeader
                    field="actual"
                    label={t('analytics.col_actual', { defaultValue: 'Actual' })}
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                    align="right"
                  />
                  <SortHeader
                    field="variance"
                    label={t('analytics.col_variance', { defaultValue: 'Variance' })}
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                    align="right"
                  />
                  <SortHeader
                    field="variance_pct"
                    label={t('analytics.col_variance_pct', { defaultValue: 'Var. %' })}
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                    align="right"
                  />
                  <th className="px-4 py-3 text-center text-xs font-medium text-content-tertiary uppercase tracking-wider">
                    {t('analytics.col_status', { defaultValue: 'Status' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {sortedProjects.map((p) => (
                  <tr
                    key={p.id}
                    className="hover:bg-surface-secondary/30 transition-colors cursor-pointer"
                    onClick={() => navigate(`/projects/${p.id}`)}
                  >
                    <td className="px-4 py-3 font-medium text-content-primary whitespace-nowrap">
                      {p.name}
                    </td>
                    <td className="px-4 py-3 text-content-secondary whitespace-nowrap">
                      {p.region}
                    </td>
                    <td className="px-4 py-3 text-right text-content-primary tabular-nums whitespace-nowrap">
                      {fmtCurrency(p.budget, p.currency)}
                    </td>
                    <td className="px-4 py-3 text-right text-content-secondary tabular-nums whitespace-nowrap">
                      {fmtCurrency(p.actual, p.currency)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums font-medium whitespace-nowrap ${
                        p.variance >= 0 ? 'text-semantic-success' : 'text-semantic-error'
                      }`}
                    >
                      {p.variance >= 0 ? '+' : ''}
                      {fmtCurrency(p.variance, p.currency)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums whitespace-nowrap ${
                        p.variance_pct >= 0 ? 'text-semantic-success' : 'text-semantic-error'
                      }`}
                    >
                      {p.variance_pct >= 0 ? '+' : ''}
                      {fmtNumber(p.variance_pct, 1)}%
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Badge
                        variant={p.status === 'on_budget' ? 'success' : 'error'}
                        size="sm"
                        dot
                      >
                        {p.status === 'on_budget'
                          ? t('analytics.on_budget', { defaultValue: 'On Budget' })
                          : t('analytics.over_budget', { defaultValue: 'Over Budget' })}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Budget Breakdown Chart */}
      {sortedProjects.length > 0 && (
        <Card>
          <h2 className="text-lg font-semibold text-content-primary mb-4">
            {t('analytics.budget_breakdown', { defaultValue: 'Budget Breakdown' })}
          </h2>
          <div className="space-y-4">
            {[...sortedProjects]
              .filter(p => p.budget > 0 || p.actual > 0)
              .sort((a, b) => b.budget - a.budget)
              .map((p) => {
                const plannedPct = (p.budget / maxBudget) * 100;
                const actualPct = (p.actual / maxBudget) * 100;
                return (
                  <div key={p.id}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-sm font-medium text-content-primary truncate max-w-[200px]">
                        {p.name}
                      </span>
                      <span className="text-xs text-content-tertiary tabular-nums">
                        {fmtCurrency(p.budget, p.currency)}
                      </span>
                    </div>
                    {/* Planned bar */}
                    <div className="relative h-5 w-full rounded bg-surface-secondary overflow-hidden">
                      <div
                        className="absolute inset-y-0 left-0 rounded bg-oe-blue/20"
                        style={{ width: `${plannedPct}%` }}
                      />
                      <div
                        className={`absolute inset-y-0 left-0 rounded ${
                          p.status === 'over_budget'
                            ? 'bg-semantic-error/70'
                            : 'bg-oe-blue/60'
                        }`}
                        style={{ width: `${actualPct}%` }}
                      />
                      {/* Labels inside bar */}
                      <div className="absolute inset-0 flex items-center px-2">
                        <span className="text-2xs font-medium text-content-primary drop-shadow-sm">
                          {t('analytics.actual_short', { defaultValue: 'Actual' })}:{' '}
                          {fmtCurrency(p.actual, p.currency)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
          {/* Legend */}
          <div className="mt-4 flex items-center gap-4 text-xs text-content-tertiary">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded bg-oe-blue/20" />
              {t('analytics.legend_planned', { defaultValue: 'Planned' })}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded bg-oe-blue/60" />
              {t('analytics.legend_actual', { defaultValue: 'Actual' })}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded bg-semantic-error/70" />
              {t('analytics.legend_over', { defaultValue: 'Over Budget' })}
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────── */

function KPICard({
  icon,
  iconBg,
  iconColor,
  label,
  value,
  sub,
  badge,
}: {
  icon: React.ReactNode;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
  sub?: string;
  badge?: React.ReactNode;
}) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${iconBg} ${iconColor}`}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-content-tertiary">{label}</p>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-xl font-bold text-content-primary truncate">{value}</span>
            {badge}
          </div>
          {sub && <p className="mt-0.5 text-xs text-content-secondary">{sub}</p>}
        </div>
      </div>
    </Card>
  );
}

function SortHeader({
  field,
  label,
  current,
  dir,
  onClick,
  align = 'left',
}: {
  field: SortField;
  label: string;
  current: SortField;
  dir: SortDir;
  onClick: (f: SortField) => void;
  align?: 'left' | 'right';
}) {
  const isActive = current === field;
  return (
    <th
      className={`px-4 py-3 text-xs font-medium text-content-tertiary uppercase tracking-wider cursor-pointer select-none hover:text-content-secondary transition-colors ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
      onClick={() => onClick(field)}
      aria-sort={isActive ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      role="columnheader"
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {isActive ? (
          dir === 'asc' ? (
            <ChevronUp size={12} />
          ) : (
            <ChevronDown size={12} />
          )
        ) : (
          <ArrowUpDown size={10} className="opacity-40" />
        )}
      </span>
    </th>
  );
}

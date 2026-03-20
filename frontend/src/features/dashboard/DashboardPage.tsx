import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '@/shared/lib/api';
import {
  FolderPlus,
  ArrowRight,
  Layers,
  Globe,
  Zap,
  ShieldCheck,
  BarChart3,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, Skeleton } from '@/shared/ui';

/* ── Types ────────────────────────────────────────────────────────────── */

interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  region: string;
  classification_standard: string;
  currency: string;
  created_at: string;
}

interface BOQWithTotal {
  id: string;
  project_id: string;
  name: string;
  status: string;
  grand_total: number;
  positions: { total: number }[];
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, string> = {
  draft: '#2563eb',
  final: '#16a34a',
  archived: '#6b7280',
};

const BAR_COLORS = ['#2563eb', '#7c3aed', '#0891b2', '#dc2626', '#ca8a04', '#16a34a'];

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/').catch(() => []),
    retry: false,
  });

  return (
    <div className="max-w-content mx-auto">
      {/* Hero — gradient animated heading */}
      <div
        className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between animate-card-in"
        style={{ animationDelay: '0ms' }}
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight gradient-text">
            {t('dashboard.welcome')}
          </h1>
          <p
            className="mt-2 text-base text-content-secondary animate-stagger-in"
            style={{ animationDelay: '100ms' }}
          >
            {t('dashboard.subtitle')}
          </p>
        </div>
        <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
          <Button
            variant="primary"
            size="lg"
            icon={<FolderPlus size={18} />}
            onClick={() => navigate('/projects/new')}
            className="btn-shimmer"
          >
            {t('projects.new_project')}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Projects — staggered card entrance */}
        <div className="lg:col-span-2 animate-card-in" style={{ animationDelay: '150ms' }}>
          <Card padding="none">
            <div className="p-6 pb-0">
              <CardHeader
                title={t('dashboard.recent_projects')}
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<ArrowRight size={14} />}
                    iconPosition="right"
                    onClick={() => navigate('/projects')}
                  >
                    {t('projects.title')}
                  </Button>
                }
              />
            </div>
            <CardContent className="!mt-0">
              <ProjectsList projects={projects} />
            </CardContent>
          </Card>
        </div>

        {/* System Status — staggered card entrance */}
        <div className="animate-card-in" style={{ animationDelay: '300ms' }}>
          <Card>
            <CardHeader title={t('dashboard.system_status')} />
            <CardContent>
              <SystemStatus />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Analytics Section */}
      {projects && projects.length > 0 && (
        <div className="mt-8 animate-card-in" style={{ animationDelay: '450ms' }}>
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 size={18} className="text-content-tertiary" strokeWidth={1.75} />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('dashboard.analytics', 'Analytics')}
            </h2>
          </div>
          <AnalyticsSection projects={projects} />
        </div>
      )}
    </div>
  );
}

/* ── Projects List ────────────────────────────────────────────────────── */

function ProjectsList({ projects }: { projects?: ProjectSummary[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (!projects || projects.length === 0) {
    return (
      <div className="px-6 py-10 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
          <FolderPlus size={22} className="text-content-tertiary" strokeWidth={1.5} />
        </div>
        <p className="text-sm font-medium text-content-primary">{t('projects.no_projects')}</p>
        <p className="mt-1 text-xs text-content-tertiary">
          Create your first project to get started
        </p>
        <div className="mt-4">
          <Button variant="primary" size="sm" onClick={() => navigate('/projects/new')}>
            {t('projects.new_project')}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border-light">
      {projects.map((p, index) => (
        <button
          key={p.id}
          onClick={() => navigate(`/projects/${p.id}`)}
          className="flex w-full items-center gap-4 px-6 py-3.5 text-left transition-all duration-normal ease-oe hover:bg-surface-secondary animate-stagger-in"
          style={{ animationDelay: `${300 + index * 60}ms` }}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue text-xs font-bold">
            {p.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-content-primary truncate">{p.name}</div>
            <div className="text-xs text-content-tertiary truncate">
              {p.description || `${p.classification_standard.toUpperCase()} · ${p.currency}`}
            </div>
          </div>
          <div className="text-xs text-content-tertiary">
            {new Date(p.created_at).toLocaleDateString()}
          </div>
          <ArrowRight size={14} className="text-content-tertiary" />
        </button>
      ))}
    </div>
  );
}

/* ── Analytics Section ────────────────────────────────────────────────── */

function AnalyticsSection({ projects }: { projects: ProjectSummary[] }) {
  const { t } = useTranslation();

  // Fetch all BOQs for each project
  const { data: allBoqs } = useQuery({
    queryKey: ['dashboard-analytics-boqs', projects.map((p) => p.id).join(',')],
    queryFn: async () => {
      const results: BOQWithTotal[] = [];
      for (const project of projects) {
        try {
          const boqs = await apiGet<BOQWithTotal[]>(
            `/v1/boq/boqs/?project_id=${project.id}`,
          );
          results.push(...boqs);
        } catch {
          // Skip projects with no BOQs
        }
      }
      return results;
    },
    enabled: projects.length > 0,
    retry: false,
  });

  const stats = useMemo(() => {
    if (!allBoqs) return null;

    const totalBoqs = allBoqs.length;
    const totalValue = allBoqs.reduce((sum, b) => sum + (b.grand_total || 0), 0);

    // Value per project
    const projectValues: { name: string; value: number }[] = projects
      .map((p) => ({
        name: p.name,
        value: allBoqs
          .filter((b) => b.project_id === p.id)
          .reduce((sum, b) => sum + (b.grand_total || 0), 0),
      }))
      .sort((a, b) => b.value - a.value);

    // BOQ status distribution
    const statusCounts: Record<string, number> = {};
    for (const boq of allBoqs) {
      const s = boq.status || 'draft';
      statusCounts[s] = (statusCounts[s] || 0) + 1;
    }

    return {
      totalProjects: projects.length,
      totalBoqs,
      totalValue,
      projectValues,
      statusCounts,
    };
  }, [allBoqs, projects]);

  if (!stats) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Skeleton height={280} className="w-full" rounded="lg" />
        <Skeleton height={280} className="w-full" rounded="lg" />
      </div>
    );
  }

  const maxValue = Math.max(...stats.projectValues.map((p) => p.value), 1);

  // Status donut segments
  const statusEntries = Object.entries(stats.statusCounts);
  const totalForDonut = statusEntries.reduce((sum, [, c]) => sum + c, 0) || 1;

  return (
    <Card>
      <CardHeader title={t('dashboard.project_overview', 'Project Overview')} />
      <CardContent>
        {/* Aggregate Stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 mb-6">
          <div className="rounded-lg bg-surface-secondary p-3">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_projects', 'Total Projects')}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalProjects}
            </div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-3">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_boqs', 'Total BOQs')}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalBoqs}
            </div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-3 sm:col-span-2">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_value', 'Total Value')}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalValue >= 1_000_000
                ? `${(stats.totalValue / 1_000_000).toFixed(1)}M`
                : stats.totalValue >= 1_000
                  ? `${(stats.totalValue / 1_000).toFixed(0)}K`
                  : stats.totalValue.toLocaleString('en-US', {
                      minimumFractionDigits: 0,
                      maximumFractionDigits: 0,
                    })}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Bar chart — value by project */}
          <div className="lg:col-span-2">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
              {t('dashboard.value_by_project', 'Value by Project')}
            </div>
            <div className="space-y-2.5">
              {stats.projectValues.map((pv, i) => {
                const barWidth = maxValue > 0 ? (pv.value / maxValue) * 100 : 0;
                const color = BAR_COLORS[i % BAR_COLORS.length];
                const formattedValue =
                  pv.value >= 1_000_000
                    ? `${(pv.value / 1_000_000).toFixed(1)}M`
                    : pv.value >= 1_000
                      ? `${(pv.value / 1_000).toFixed(0)}K`
                      : pv.value.toLocaleString();
                return (
                  <div key={pv.name} className="flex items-center gap-3">
                    <div className="w-24 shrink-0 text-xs text-content-secondary truncate text-right">
                      {pv.name}
                    </div>
                    <div className="flex-1 h-6 bg-surface-secondary rounded overflow-hidden">
                      <div
                        className="h-full rounded transition-all duration-500 ease-out"
                        style={{
                          width: `${Math.max(barWidth, 1)}%`,
                          backgroundColor: color,
                        }}
                      />
                    </div>
                    <div className="w-16 shrink-0 text-xs font-medium tabular-nums text-content-primary text-right">
                      {formattedValue}
                    </div>
                  </div>
                );
              })}
              {stats.projectValues.length === 0 && (
                <p className="text-xs text-content-tertiary text-center py-4">
                  {t('dashboard.no_boq_data', 'No BOQ data available')}
                </p>
              )}
            </div>
          </div>

          {/* Status donut */}
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
              {t('dashboard.boq_status', 'BOQ Status')}
            </div>
            <div className="flex items-center gap-4">
              <StatusDonut statusCounts={stats.statusCounts} total={totalForDonut} />
              <div className="space-y-2">
                {statusEntries.map(([status, count]) => (
                  <div key={status} className="flex items-center gap-2">
                    <div
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: STATUS_COLORS[status] || '#6b7280' }}
                    />
                    <span className="text-xs text-content-secondary capitalize">{status}:</span>
                    <span className="text-xs font-semibold tabular-nums text-content-primary">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Status Donut (SVG) ───────────────────────────────────────────────── */

function StatusDonut({
  statusCounts,
  total,
}: {
  statusCounts: Record<string, number>;
  total: number;
}) {
  const size = 100;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = 42;
  const innerR = 28;

  const entries = Object.entries(statusCounts);
  let cumulative = 0;

  function polarToCartesian(radius: number, angleInDegrees: number) {
    const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0;
    return {
      x: cx + radius * Math.cos(angleInRadians),
      y: cy + radius * Math.sin(angleInRadians),
    };
  }

  function describeArc(startAngle: number, endAngle: number) {
    const sweep = Math.min(endAngle - startAngle, 359.999);
    const largeArc = sweep > 180 ? 1 : 0;
    const outerStart = polarToCartesian(outerR, startAngle);
    const outerEnd = polarToCartesian(outerR, startAngle + sweep);
    const innerStart = polarToCartesian(innerR, startAngle + sweep);
    const innerEnd = polarToCartesian(innerR, startAngle);

    return [
      `M ${outerStart.x} ${outerStart.y}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
      `L ${innerStart.x} ${innerStart.y}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerEnd.x} ${innerEnd.y}`,
      'Z',
    ].join(' ');
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {entries.map(([status, count]) => {
        const pct = count / total;
        const startAngle = cumulative * 360;
        cumulative += pct;
        const endAngle = cumulative * 360;
        const color = STATUS_COLORS[status] || '#6b7280';
        return <path key={status} d={describeArc(startAngle, endAngle)} fill={color} />;
      })}
      <circle cx={cx} cy={cy} r={innerR - 1} fill="var(--color-surface-primary, white)" />
      <text
        x={cx}
        y={cy + 4}
        textAnchor="middle"
        fontSize={16}
        fontWeight="bold"
        className="fill-content-primary"
        fontFamily="system-ui"
      >
        {total}
      </text>
    </svg>
  );
}

/* ── System Status ────────────────────────────────────────────────────── */

function SystemStatus() {
  const { t } = useTranslation();

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['health'],
    queryFn: () => fetch('/api/health').then((r) => r.json()),
    retry: false,
    refetchInterval: 30000,
  });

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => fetch('/api/system/modules').then((r) => r.json()),
    retry: false,
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () => fetch('/api/system/validation-rules').then((r) => r.json()),
    retry: false,
  });

  const isHealthy = health?.status === 'healthy';

  return (
    <div className="space-y-4">
      {/* API status with live dot */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '400ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          API
          {isHealthy && <span className="live-dot" aria-label="Live" />}
        </span>
        {healthLoading ? (
          <Skeleton width={80} height={20} rounded="full" />
        ) : (
          <Badge variant={isHealthy ? 'success' : 'error'} dot size="sm">
            {isHealthy ? 'Healthy' : 'Offline'}
          </Badge>
        )}
      </div>

      {/* Version */}
      {health?.version && (
        <div
          className="flex items-center justify-between animate-stagger-in"
          style={{ animationDelay: '460ms' }}
        >
          <span className="text-sm text-content-secondary">Version</span>
          <span
            className="text-sm font-mono text-content-primary inline-block animate-count-up"
            style={{ animationDelay: '500ms' }}
          >
            {health.version}
          </span>
        </div>
      )}

      {/* Modules loaded */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '520ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Layers size={14} strokeWidth={1.75} />
          {t('dashboard.modules_loaded')}
        </span>
        <span
          className="text-sm font-semibold text-content-primary inline-block animate-count-up"
          style={{ animationDelay: '600ms' }}
        >
          {modules?.modules?.length ?? '\u2014'}
        </span>
      </div>

      {/* Validation rules */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '580ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <ShieldCheck size={14} strokeWidth={1.75} />
          {t('dashboard.validation_rules')}
        </span>
        <span
          className="text-sm font-semibold text-content-primary inline-block animate-count-up"
          style={{ animationDelay: '680ms' }}
        >
          {rules?.rules?.length ?? '\u2014'}
        </span>
      </div>

      {/* Languages */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '640ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Globe size={14} strokeWidth={1.75} />
          {t('dashboard.languages')}
        </span>
        <span
          className="text-sm font-semibold text-content-primary inline-block animate-count-up"
          style={{ animationDelay: '760ms' }}
        >
          20
        </span>
      </div>

      {/* Phase indicator */}
      <div
        className="border-t border-border-light pt-3 animate-stagger-in"
        style={{ animationDelay: '700ms' }}
      >
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <Zap size={12} />
          <span>Phase 1 — Core Estimation</span>
        </div>
      </div>
    </div>
  );
}

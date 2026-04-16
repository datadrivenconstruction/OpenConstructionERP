import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  BarChart3,
  Briefcase,
  Calculator,
  HardHat,
  Wallet,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  TrendingUp,
  TrendingDown,
  Loader2,
  FileText,
  ClipboardList,
  Activity,
} from 'lucide-react';
import { Breadcrumb, Card, CardContent, Skeleton } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import { projectsApi, type Project } from '@/features/projects/api';

/* ── Types ─────────────────────────────────────────────────────────────────── */

type DashboardTab = 'executive' | 'pm' | 'estimator' | 'site' | 'finance';

interface KPISnapshot {
  id: string;
  project_id: string;
  snapshot_date: string;
  cpi: string | null;
  spi: string | null;
  budget_consumed_pct: string | null;
  open_defects: number;
  open_observations: number;
  schedule_progress_pct: string | null;
  open_rfis: number;
  open_submittals: number;
  risk_score_avg: string | null;
}

interface FinanceDashboard {
  total_payable: number;
  total_receivable: number;
  overdue_payable: number;
  overdue_receivable: number;
  total_budget: number;
  total_actual: number;
  budget_consumed_pct: number;
  budget_warning: string;
  cash_flow_net: number;
  invoices_due_this_week: number;
  invoices_due_this_month: number;
  currency: string;
}

interface SafetyStats {
  total_incidents: number;
  total_observations: number;
  open_corrective_actions: number;
  days_since_last_incident: number;
}

interface TaskStats {
  total: number;
  by_status: Record<string, number>;
  overdue: number;
}

interface RFIStats {
  total: number;
  open: number;
  overdue: number;
  avg_response_days: number;
}

interface ScheduleStats {
  total_activities: number;
  completed: number;
  in_progress: number;
  delayed: number;
  on_track: number;
  progress_pct: number;
}

interface ProcurementStats {
  total_pos: number;
  by_status: Record<string, number>;
  total_committed: number;
  pending_delivery: number;
}

/* ── KPI helpers ───��───────────────────────────────────────────────────────── */

type TrafficLight = 'green' | 'yellow' | 'red' | 'gray';

function kpiColor(value: number | null | undefined, thresholds: [number, number]): TrafficLight {
  if (value === null || value === undefined) return 'gray';
  if (value >= thresholds[1]) return 'green';
  if (value >= thresholds[0]) return 'yellow';
  return 'red';
}

const trafficClasses: Record<TrafficLight, string> = {
  green: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400',
  yellow: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  red: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  gray: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
};

function fmt(v: string | number | null | undefined, suffix = ''): string {
  if (v === null || v === undefined || v === '') return 'N/A';
  return `${v}${suffix}`;
}

function fmtNum(v: number | null | undefined, decimals = 0): string {
  if (v === null || v === undefined) return 'N/A';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/* ── KPI Card component ────────────────────────────────────────────────────── */

function KPICard({
  label,
  value,
  color = 'gray',
  icon: Icon,
}: {
  label: string;
  value: string;
  color?: TrafficLight;
  icon?: React.ElementType;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border-light bg-surface-primary p-4 shadow-xs">
      {Icon && (
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${trafficClasses[color]}`}>
          <Icon size={18} />
        </div>
      )}
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-content-secondary">{label}</p>
        <p className="text-lg font-semibold text-content-primary">{value}</p>
      </div>
    </div>
  );
}

/* ── Project status badge ──────────────────────────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    active: { color: 'bg-emerald-100 text-emerald-700', label: 'Active' },
    on_hold: { color: 'bg-amber-100 text-amber-700', label: 'On Hold' },
    completed: { color: 'bg-blue-100 text-blue-700', label: 'Completed' },
    archived: { color: 'bg-gray-100 text-gray-500', label: 'Archived' },
  };
  const s = map[status] ?? { color: 'bg-gray-100 text-gray-500', label: status };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`}>{s.label}</span>;
}

/* ── Tab buttons ─────��─────────────────────────────────────────────────────── */

const TABS: { key: DashboardTab; labelKey: string; defaultLabel: string; icon: React.ElementType }[] = [
  { key: 'executive', labelKey: 'reporting.tab_executive', defaultLabel: 'Executive', icon: Briefcase },
  { key: 'pm', labelKey: 'reporting.tab_pm', defaultLabel: 'Project Manager', icon: ClipboardList },
  { key: 'estimator', labelKey: 'reporting.tab_estimator', defaultLabel: 'Estimator', icon: Calculator },
  { key: 'site', labelKey: 'reporting.tab_site', defaultLabel: 'Site Engineer', icon: HardHat },
  { key: 'finance', labelKey: 'reporting.tab_finance', defaultLabel: 'Finance', icon: Wallet },
];

/* ── Main component ────────────────────────────────────────────────────────── */

export function ReportingPage() {
  const { t } = useTranslation();
  const { activeProjectId, activeProjectName } = useProjectContextStore();

  const [tab, setTab] = useState<DashboardTab>('executive');
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);

  // Data
  const [projects, setProjects] = useState<Project[]>([]);
  const [kpiMap, setKpiMap] = useState<Record<string, KPISnapshot>>({});
  const [financeDash, setFinanceDash] = useState<FinanceDashboard | null>(null);
  const [safetyStats, setSafetyStats] = useState<SafetyStats | null>(null);
  const [taskStats, setTaskStats] = useState<TaskStats | null>(null);
  const [rfiStats, setRfiStats] = useState<RFIStats | null>(null);
  const [scheduleStats, setScheduleStats] = useState<ScheduleStats | null>(null);
  const [procurementStats, setProcurementStats] = useState<ProcurementStats | null>(null);

  const selectedProjectId = activeProjectId ?? '';

  const loadProjectStats = useCallback(async (pid: string) => {
    const results = await Promise.allSettled([
      apiGet<FinanceDashboard>(`/v1/finance/dashboard/?project_id=${pid}`).then(setFinanceDash),
      apiGet<SafetyStats>(`/v1/safety/stats/?project_id=${pid}`).then(setSafetyStats),
      apiGet<TaskStats>(`/v1/tasks/stats/?project_id=${pid}`).then(setTaskStats),
      apiGet<RFIStats>(`/v1/rfi/stats/?project_id=${pid}`).then(setRfiStats),
      apiGet<ScheduleStats>(`/v1/schedule/stats/?project_id=${pid}`).then(setScheduleStats),
      apiGet<ProcurementStats>(`/v1/procurement/stats/?project_id=${pid}`).then(setProcurementStats),
    ]);

    // Clear data for rejected promises to avoid stale state
    if (results[0].status === 'rejected') setFinanceDash(null);
    if (results[1].status === 'rejected') setSafetyStats(null);
    if (results[2].status === 'rejected') setTaskStats(null);
    if (results[3].status === 'rejected') setRfiStats(null);
    if (results[4].status === 'rejected') setScheduleStats(null);
    if (results[5].status === 'rejected') setProcurementStats(null);
  }, []);

  // Load everything
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const projs = await projectsApi.list();
      setProjects(projs);

      // Load KPI for each project
      const kpis: Record<string, KPISnapshot> = {};
      await Promise.allSettled(
        projs.map(async (p) => {
          try {
            const kpi = await apiGet<KPISnapshot | null>(
              `/v1/reporting/kpi?project_id=${p.id}`,
            );
            if (kpi) kpis[p.id] = kpi;
          } catch {
            // no KPI for this project yet
          }
        }),
      );
      setKpiMap(kpis);

      // Project-scoped stats (use selected project or first)
      const pid = selectedProjectId || projs[0]?.id;
      if (pid) {
        await loadProjectStats(pid);
      }
    } catch {
      // swallow — individual sections degrade gracefully
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId, loadProjectStats]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Reload project-specific stats when selected project changes
  useEffect(() => {
    if (selectedProjectId) {
      loadProjectStats(selectedProjectId);
    }
  }, [selectedProjectId, loadProjectStats]);

  const handleRecalculate = async () => {
    setRecalculating(true);
    try {
      await apiPost('/v1/reporting/kpi/recalculate-all/', {});
      await loadData();
    } catch {
      // handled by error boundary
    } finally {
      setRecalculating(false);
    }
  };

  // Active / total counts
  const activeProjects = projects.filter((p) => p.status === 'active');
  const totalPortfolioValue = projects.reduce((sum, p) => {
    const meta = p.metadata as Record<string, unknown> | undefined;
    const budget = meta?.budget_estimate ?? (p as unknown as Record<string, unknown>).budget_estimate;
    return sum + (budget ? Number(budget) || 0 : 0);
  }, 0);

  const selectedProject = projects.find((p) => p.id === selectedProjectId);
  const selectedKpi = selectedProjectId ? kpiMap[selectedProjectId] : undefined;

  /* ── Render ─────────────────────────────────────────────────────────────── */

  return (
    <div className="w-full space-y-6 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('reporting.title', { defaultValue: 'Reporting Dashboards' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">
            {t('reporting.title', { defaultValue: 'Reporting Dashboards' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('reporting.subtitle', {
              defaultValue: 'Role-based KPI dashboards with real-time project data',
            })}
          </p>
        </div>
        <button
          onClick={handleRecalculate}
          disabled={recalculating}
          className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {recalculating ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {t('reporting.recalculate', { defaultValue: 'Recalculate KPIs' })}
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 rounded-xl border border-border-light bg-surface-secondary p-1">
        {TABS.map(({ key, labelKey, defaultLabel, icon: TabIcon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              tab === key
                ? 'bg-surface-primary text-content-primary shadow-sm'
                : 'text-content-secondary hover:text-content-primary hover:bg-surface-primary/50'
            }`}
          >
            <TabIcon size={16} />
            {t(labelKey, { defaultValue: defaultLabel })}
          </button>
        ))}
      </div>

      {/* Project selector for PM / Estimator / Site / Finance tabs */}
      {tab !== 'executive' && (
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-content-secondary">
            {t('reporting.select_project', { defaultValue: 'Project' })}
          </label>
          <select
            value={selectedProjectId}
            onChange={(e) => {
              const id = e.target.value;
              const name = projects.find((p) => p.id === id)?.name ?? '';
              if (id) {
                useProjectContextStore.getState().setActiveProject(id, name);
              }
            }}
            className="h-9 min-w-[240px] rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      )}

      {/* Tab content */}
      {!loading && tab === 'executive' && (
        <ExecutiveDashboard
          projects={projects}
          activeProjects={activeProjects}
          totalValue={totalPortfolioValue}
          kpiMap={kpiMap}
        />
      )}
      {!loading && tab === 'pm' && (
        <PMDashboard
          project={selectedProject}
          kpi={selectedKpi}
          taskStats={taskStats}
          rfiStats={rfiStats}
          scheduleStats={scheduleStats}
        />
      )}
      {!loading && tab === 'estimator' && (
        <EstimatorDashboard
          project={selectedProject}
          kpi={selectedKpi}
        />
      )}
      {!loading && tab === 'site' && (
        <SiteDashboard
          project={selectedProject}
          safetyStats={safetyStats}
          scheduleStats={scheduleStats}
        />
      )}
      {!loading && tab === 'finance' && (
        <FinanceDashboardView
          project={selectedProject}
          financeDash={financeDash}
          procurementStats={procurementStats}
        />
      )}
    </div>
  );
}

/* ── Executive Dashboard ──────────────────────────────────────────────────── */

function ExecutiveDashboard({
  projects,
  activeProjects,
  totalValue,
  kpiMap,
}: {
  projects: Project[];
  activeProjects: Project[];
  totalValue: number;
  kpiMap: Record<string, KPISnapshot>;
}) {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      {/* Portfolio KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('reporting.total_projects', { defaultValue: 'Total Projects' })}
          value={String(projects.length)}
          color="gray"
          icon={FileText}
        />
        <KPICard
          label={t('reporting.active_projects', { defaultValue: 'Active Projects' })}
          value={String(activeProjects.length)}
          color="green"
          icon={Activity}
        />
        <KPICard
          label={t('reporting.portfolio_value', { defaultValue: 'Portfolio Value' })}
          value={totalValue > 0 ? fmtNum(totalValue) : 'N/A'}
          color="gray"
          icon={BarChart3}
        />
        <KPICard
          label={t('reporting.projects_with_kpi', { defaultValue: 'Projects with KPI' })}
          value={`${Object.keys(kpiMap).length} / ${projects.length}`}
          color={Object.keys(kpiMap).length >= projects.length ? 'green' : 'yellow'}
          icon={TrendingUp}
        />
      </div>

      {/* Project table with KPI traffic lights */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary text-left text-xs font-medium text-content-secondary">
                  <th className="px-4 py-3">{t('reporting.col_project', { defaultValue: 'Project' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_cpi', { defaultValue: 'CPI' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_spi', { defaultValue: 'SPI' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_budget', { defaultValue: 'Budget %' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_schedule', { defaultValue: 'Schedule %' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_risk', { defaultValue: 'Risk Score' })}</th>
                  <th className="px-4 py-3">{t('reporting.col_open_items', { defaultValue: 'Open Items' })}</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => {
                  const kpi = kpiMap[p.id];
                  const cpiVal = kpi?.cpi ? parseFloat(kpi.cpi) : null;
                  const spiVal = kpi?.spi ? parseFloat(kpi.spi) : null;
                  const budgetVal = kpi?.budget_consumed_pct ? parseFloat(kpi.budget_consumed_pct) : null;
                  const schedVal = kpi?.schedule_progress_pct ? parseFloat(kpi.schedule_progress_pct) : null;
                  const riskVal = kpi?.risk_score_avg ? parseFloat(kpi.risk_score_avg) : null;
                  const openItems = (kpi?.open_rfis ?? 0) + (kpi?.open_submittals ?? 0) + (kpi?.open_defects ?? 0) + (kpi?.open_observations ?? 0);

                  return (
                    <tr key={p.id} className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50">
                      <td className="px-4 py-3 font-medium text-content-primary">{p.name}</td>
                      <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                      <td className="px-4 py-3">
                        <TrafficDot color={kpiColor(cpiVal, [0.9, 1.0])} label={fmt(kpi?.cpi)} />
                      </td>
                      <td className="px-4 py-3">
                        <TrafficDot color={kpiColor(spiVal, [0.9, 1.0])} label={fmt(kpi?.spi)} />
                      </td>
                      <td className="px-4 py-3">
                        <TrafficDot color={budgetVal !== null ? kpiColor(100 - budgetVal, [5, 20]) : 'gray'} label={fmt(kpi?.budget_consumed_pct, '%')} />
                      </td>
                      <td className="px-4 py-3">
                        <TrafficDot color={kpiColor(schedVal, [50, 80])} label={fmt(kpi?.schedule_progress_pct, '%')} />
                      </td>
                      <td className="px-4 py-3">
                        <TrafficDot color={riskVal !== null ? kpiColor(10 - riskVal, [3, 7]) : 'gray'} label={fmt(kpi?.risk_score_avg)} />
                      </td>
                      <td className="px-4 py-3 text-content-secondary">{kpi ? openItems : 'N/A'}</td>
                    </tr>
                  );
                })}
                {projects.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-content-secondary">
                      {t('reporting.no_projects', { defaultValue: 'No projects found' })}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* ── Traffic dot component ─────────────────────────────────────────────────── */

function TrafficDot({ color, label }: { color: TrafficLight; label: string }) {
  const dotColors: Record<TrafficLight, string> = {
    green: 'bg-emerald-500',
    yellow: 'bg-amber-500',
    red: 'bg-red-500',
    gray: 'bg-gray-300 dark:bg-gray-600',
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotColors[color]}`} />
      <span className="text-sm text-content-primary">{label}</span>
    </span>
  );
}

/* ── PM Dashboard ──────────────────────────────────────────────────────────── */

function PMDashboard({
  project,
  kpi,
  taskStats,
  rfiStats,
  scheduleStats,
}: {
  project?: Project;
  kpi?: KPISnapshot;
  taskStats: TaskStats | null;
  rfiStats: RFIStats | null;
  scheduleStats: ScheduleStats | null;
}) {
  const { t } = useTranslation();
  if (!project) {
    return <EmptyState message={t('reporting.select_project_prompt', { defaultValue: 'Select a project to view PM dashboard' })} />;
  }

  const budgetPct = kpi?.budget_consumed_pct ? parseFloat(kpi.budget_consumed_pct) : null;
  const spiVal = kpi?.spi ? parseFloat(kpi.spi) : null;
  const cpiVal = kpi?.cpi ? parseFloat(kpi.cpi) : null;

  return (
    <div className="space-y-6">
      {/* Project KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('reporting.budget_consumed', { defaultValue: 'Budget Consumed' })}
          value={fmt(kpi?.budget_consumed_pct, '%')}
          color={budgetPct !== null ? kpiColor(100 - budgetPct, [5, 20]) : 'gray'}
          icon={Wallet}
        />
        <KPICard
          label={t('reporting.spi', { defaultValue: 'Schedule SPI' })}
          value={fmt(kpi?.spi)}
          color={kpiColor(spiVal, [0.9, 1.0])}
          icon={spiVal !== null && spiVal >= 1 ? TrendingUp : TrendingDown}
        />
        <KPICard
          label={t('reporting.cpi', { defaultValue: 'Cost CPI' })}
          value={fmt(kpi?.cpi)}
          color={kpiColor(cpiVal, [0.9, 1.0])}
          icon={cpiVal !== null && cpiVal >= 1 ? TrendingUp : TrendingDown}
        />
        <KPICard
          label={t('reporting.schedule_progress', { defaultValue: 'Schedule Progress' })}
          value={fmt(kpi?.schedule_progress_pct, '%')}
          color={kpiColor(
            kpi?.schedule_progress_pct ? parseFloat(kpi.schedule_progress_pct) : null,
            [50, 80],
          )}
          icon={BarChart3}
        />
      </div>

      {/* Open items row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('reporting.open_rfis', { defaultValue: 'Open RFIs' })}
          value={rfiStats ? String(rfiStats.open) : fmt(kpi?.open_rfis)}
          color={kpiColor(rfiStats?.open !== undefined ? (rfiStats.open === 0 ? 10 : 10 - rfiStats.open) : null, [0, 5])}
          icon={FileText}
        />
        <KPICard
          label={t('reporting.open_submittals', { defaultValue: 'Open Submittals' })}
          value={String(kpi?.open_submittals ?? 'N/A')}
          color="gray"
          icon={ClipboardList}
        />
        <KPICard
          label={t('reporting.overdue_tasks', { defaultValue: 'Overdue Tasks' })}
          value={taskStats ? String(taskStats.overdue) : 'N/A'}
          color={taskStats?.overdue ? (taskStats.overdue > 5 ? 'red' : 'yellow') : 'gray'}
          icon={AlertTriangle}
        />
        <KPICard
          label={t('reporting.total_tasks', { defaultValue: 'Total Tasks' })}
          value={taskStats ? String(taskStats.total) : 'N/A'}
          color="gray"
          icon={CheckCircle2}
        />
      </div>

      {/* Schedule summary */}
      {scheduleStats && (
        <Card>
          <CardContent>
            <h3 className="mb-3 text-sm font-semibold text-content-primary">
              {t('reporting.schedule_summary', { defaultValue: 'Schedule Summary' })}
            </h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              <StatBlock label={t('reporting.total_activities', { defaultValue: 'Total' })} value={scheduleStats.total_activities} />
              <StatBlock label={t('reporting.completed', { defaultValue: 'Completed' })} value={scheduleStats.completed} color="emerald" />
              <StatBlock label={t('reporting.in_progress', { defaultValue: 'In Progress' })} value={scheduleStats.in_progress} color="blue" />
              <StatBlock label={t('reporting.delayed', { defaultValue: 'Delayed' })} value={scheduleStats.delayed} color="red" />
              <StatBlock label={t('reporting.on_track', { defaultValue: 'On Track' })} value={scheduleStats.on_track} color="emerald" />
            </div>
          </CardContent>
        </Card>
      )}

      {/* RFI details */}
      {rfiStats && (
        <Card>
          <CardContent>
            <h3 className="mb-3 text-sm font-semibold text-content-primary">
              {t('reporting.rfi_summary', { defaultValue: 'RFI Summary' })}
            </h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatBlock label={t('reporting.total', { defaultValue: 'Total' })} value={rfiStats.total} />
              <StatBlock label={t('reporting.open', { defaultValue: 'Open' })} value={rfiStats.open} color="amber" />
              <StatBlock label={t('reporting.overdue', { defaultValue: 'Overdue' })} value={rfiStats.overdue} color="red" />
              <StatBlock
                label={t('reporting.avg_response', { defaultValue: 'Avg Response (days)' })}
                value={rfiStats.avg_response_days?.toFixed(1) ?? 'N/A'}
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ── Estimator Dashboard ─────────��─────────────────────────────────────────── */

function EstimatorDashboard({
  project,
  kpi,
}: {
  project?: Project;
  kpi?: KPISnapshot;
}) {
  const { t } = useTranslation();
  const [boqs, setBoqs] = useState<Array<{ id: string; name: string; status: string; grand_total: number; currency: string; position_count: number }>>([]);
  const [loadingBoqs, setLoadingBoqs] = useState(false);
  const projectId = project?.id;

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoadingBoqs(true);
    (async () => {
      try {
        const data = await apiGet<Array<{ id: string; name: string; status: string; grand_total: number; currency: string; position_count: number }>>(
          `/v1/boq/boqs/?project_id=${projectId}`,
        );
        if (!cancelled) setBoqs(data);
      } catch {
        if (!cancelled) setBoqs([]);
      } finally {
        if (!cancelled) setLoadingBoqs(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  if (!project) {
    return <EmptyState message={t('reporting.select_project_prompt_estimator', { defaultValue: 'Select a project to view Estimator dashboard' })} />;
  }

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KPICard
          label={t('reporting.cpi', { defaultValue: 'CPI' })}
          value={fmt(kpi?.cpi)}
          color={kpiColor(kpi?.cpi ? parseFloat(kpi.cpi) : null, [0.9, 1.0])}
          icon={TrendingUp}
        />
        <KPICard
          label={t('reporting.budget_consumed', { defaultValue: 'Budget Consumed' })}
          value={fmt(kpi?.budget_consumed_pct, '%')}
          color="gray"
          icon={Wallet}
        />
        <KPICard
          label={t('reporting.boq_count', { defaultValue: 'BOQs' })}
          value={String(boqs.length)}
          color="gray"
          icon={Calculator}
        />
      </div>

      {/* BOQ table */}
      <Card>
        <CardContent className="p-0">
          {loadingBoqs ? (
            <div className="p-4">
              <Skeleton className="h-20 w-full rounded-lg" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary text-left text-xs font-medium text-content-secondary">
                    <th className="px-4 py-3">{t('reporting.boq_name', { defaultValue: 'BOQ Name' })}</th>
                    <th className="px-4 py-3">{t('reporting.col_status', { defaultValue: 'Status' })}</th>
                    <th className="px-4 py-3 text-right">{t('reporting.positions', { defaultValue: 'Positions' })}</th>
                    <th className="px-4 py-3 text-right">{t('reporting.grand_total', { defaultValue: 'Grand Total' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {boqs.map((b) => (
                    <tr key={b.id} className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50">
                      <td className="px-4 py-3 font-medium text-content-primary">{b.name}</td>
                      <td className="px-4 py-3"><StatusBadge status={b.status} /></td>
                      <td className="px-4 py-3 text-right text-content-secondary">{b.position_count ?? 0}</td>
                      <td className="px-4 py-3 text-right font-medium text-content-primary">
                        {fmtNum(b.grand_total, 2)} {b.currency}
                      </td>
                    </tr>
                  ))}
                  {boqs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-content-secondary">
                        {t('reporting.no_boqs', { defaultValue: 'No BOQs in this project' })}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ── Site Engineer Dashboard ───────────────────────────────────────────────── */

function SiteDashboard({
  project,
  safetyStats,
  scheduleStats,
}: {
  project?: Project;
  safetyStats: SafetyStats | null;
  scheduleStats: ScheduleStats | null;
}) {
  const { t } = useTranslation();

  if (!project) {
    return <EmptyState message={t('reporting.select_project_prompt_site', { defaultValue: 'Select a project to view Site Engineer dashboard' })} />;
  }

  return (
    <div className="space-y-6">
      {/* Schedule KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          label={t('reporting.today_activities', { defaultValue: 'Total Activities' })}
          value={scheduleStats ? String(scheduleStats.total_activities) : 'N/A'}
          color="gray"
          icon={ClipboardList}
        />
        <KPICard
          label={t('reporting.in_progress', { defaultValue: 'In Progress' })}
          value={scheduleStats ? String(scheduleStats.in_progress) : 'N/A'}
          color="green"
          icon={Activity}
        />
        <KPICard
          label={t('reporting.delayed_activities', { defaultValue: 'Delayed' })}
          value={scheduleStats ? String(scheduleStats.delayed) : 'N/A'}
          color={scheduleStats?.delayed ? (scheduleStats.delayed > 3 ? 'red' : 'yellow') : 'gray'}
          icon={AlertTriangle}
        />
        <KPICard
          label={t('reporting.progress', { defaultValue: 'Progress' })}
          value={scheduleStats ? `${scheduleStats.progress_pct?.toFixed(0) ?? 0}%` : 'N/A'}
          color={kpiColor(scheduleStats?.progress_pct ?? null, [50, 80])}
          icon={BarChart3}
        />
      </div>

      {/* Safety stats */}
      {safetyStats ? (
        <Card>
          <CardContent>
            <h3 className="mb-3 text-sm font-semibold text-content-primary">
              {t('reporting.safety_overview', { defaultValue: 'Safety Overview' })}
            </h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatBlock
                label={t('reporting.incidents', { defaultValue: 'Incidents' })}
                value={safetyStats.total_incidents}
                color={safetyStats.total_incidents > 0 ? 'red' : 'emerald'}
              />
              <StatBlock
                label={t('reporting.observations', { defaultValue: 'Observations' })}
                value={safetyStats.total_observations}
              />
              <StatBlock
                label={t('reporting.open_actions', { defaultValue: 'Open Actions' })}
                value={safetyStats.open_corrective_actions}
                color={safetyStats.open_corrective_actions > 0 ? 'amber' : 'emerald'}
              />
              <StatBlock
                label={t('reporting.days_safe', { defaultValue: 'Days Since Incident' })}
                value={safetyStats.days_since_last_incident}
                color="emerald"
              />
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent>
            <p className="text-sm text-content-secondary">
              {t('reporting.no_safety_data', { defaultValue: 'No safety data available for this project.' })}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ���─ Finance Dashboard ───────���─────────────────────────────────────────────── */

function FinanceDashboardView({
  project,
  financeDash,
  procurementStats,
}: {
  project?: Project;
  financeDash: FinanceDashboard | null;
  procurementStats: ProcurementStats | null;
}) {
  const { t } = useTranslation();

  if (!project) {
    return <EmptyState message={t('reporting.select_project_prompt_finance', { defaultValue: 'Select a project to view Finance dashboard' })} />;
  }

  return (
    <div className="space-y-6">
      {/* Finance KPIs */}
      {financeDash ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KPICard
              label={t('reporting.payable', { defaultValue: 'Total Payable' })}
              value={`${fmtNum(financeDash.total_payable, 2)} ${financeDash.currency}`}
              color="gray"
              icon={Wallet}
            />
            <KPICard
              label={t('reporting.receivable', { defaultValue: 'Total Receivable' })}
              value={`${fmtNum(financeDash.total_receivable, 2)} ${financeDash.currency}`}
              color="gray"
              icon={TrendingUp}
            />
            <KPICard
              label={t('reporting.overdue_payable', { defaultValue: 'Overdue Payable' })}
              value={`${fmtNum(financeDash.overdue_payable, 2)} ${financeDash.currency}`}
              color={financeDash.overdue_payable > 0 ? 'red' : 'green'}
              icon={AlertTriangle}
            />
            <KPICard
              label={t('reporting.cash_flow_net', { defaultValue: 'Net Cash Flow' })}
              value={`${fmtNum(financeDash.cash_flow_net, 2)} ${financeDash.currency}`}
              color={financeDash.cash_flow_net >= 0 ? 'green' : 'red'}
              icon={financeDash.cash_flow_net >= 0 ? TrendingUp : TrendingDown}
            />
          </div>

          {/* Invoices and budget */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KPICard
              label={t('reporting.invoices_week', { defaultValue: 'Invoices Due (Week)' })}
              value={String(financeDash.invoices_due_this_week)}
              color={financeDash.invoices_due_this_week > 0 ? 'yellow' : 'green'}
              icon={Clock}
            />
            <KPICard
              label={t('reporting.invoices_month', { defaultValue: 'Invoices Due (Month)' })}
              value={String(financeDash.invoices_due_this_month)}
              color="gray"
              icon={Clock}
            />
            <KPICard
              label={t('reporting.budget_total', { defaultValue: 'Total Budget' })}
              value={`${fmtNum(financeDash.total_budget, 2)} ${financeDash.currency}`}
              color="gray"
              icon={Wallet}
            />
            <KPICard
              label={t('reporting.budget_consumed', { defaultValue: 'Budget Consumed' })}
              value={`${financeDash.budget_consumed_pct?.toFixed(1) ?? 'N/A'}%`}
              color={
                financeDash.budget_warning === 'critical'
                  ? 'red'
                  : financeDash.budget_warning === 'caution'
                    ? 'yellow'
                    : 'green'
              }
              icon={BarChart3}
            />
          </div>
        </>
      ) : (
        <Card>
          <CardContent>
            <p className="text-sm text-content-secondary">
              {t('reporting.no_finance_data', { defaultValue: 'No finance data available for this project. Create invoices and budgets first.' })}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Procurement summary */}
      {procurementStats && (
        <Card>
          <CardContent>
            <h3 className="mb-3 text-sm font-semibold text-content-primary">
              {t('reporting.procurement_summary', { defaultValue: 'Procurement Summary' })}
            </h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatBlock label={t('reporting.total_pos', { defaultValue: 'Total POs' })} value={procurementStats.total_pos} />
              <StatBlock
                label={t('reporting.committed', { defaultValue: 'Committed' })}
                value={fmtNum(procurementStats.total_committed, 2)}
              />
              <StatBlock
                label={t('reporting.pending_delivery', { defaultValue: 'Pending Delivery' })}
                value={procurementStats.pending_delivery}
                color={procurementStats.pending_delivery > 0 ? 'amber' : 'emerald'}
              />
              <StatBlock
                label={t('reporting.approved_pos', { defaultValue: 'Approved' })}
                value={procurementStats.by_status?.approved ?? 0}
                color="emerald"
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ── Shared sub-components ─────────────────────────────────────────────────── */

function StatBlock({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  const textColor = color ? `text-${color}-600 dark:text-${color}-400` : 'text-content-primary';
  return (
    <div>
      <p className="text-xs font-medium text-content-secondary">{label}</p>
      <p className={`text-xl font-semibold ${textColor}`}>{value}</p>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <Card>
      <CardContent>
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <BarChart3 size={40} className="mb-3 text-content-tertiary" />
          <p className="text-sm text-content-secondary">{message}</p>
        </div>
      </CardContent>
    </Card>
  );
}

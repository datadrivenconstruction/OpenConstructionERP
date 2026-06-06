import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  LayoutDashboard,
  Activity,
  FileText,
  CalendarClock,
  Bell,
  Plus,
  X,
  Play,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  AlertOctagon,
  Sparkles,
  Download,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listKpis,
  getKpiHistory,
  computeKpi,
  listDashboards,
  renderDashboard,
  evaluateDashboard,
  createDashboard,
  installStarterPack,
  createWidget,
  deleteWidget,
  listReports,
  runReport,
  createReport,
  downloadReportRun,
  downloadWidgetExport,
  listSchedules,
  createSchedule,
  updateSchedule,
  runScheduleNow,
  listAlerts,
  toggleAlert,
  createAlert,
  evaluateAlertsNow,
  type AlertCondition,
  type AlertRule,
  type AlertSeverity,
  type Dashboard,
  type DashboardScope,
  type DrillPath,
  type KpiDefinition,
  type ReportDefinition,
  type ReportFrequency,
  type ReportSchedule,
  type WidgetEvaluateResult,
  type WidgetRenderResult,
  type WidgetType,
} from './api';
import { useDashboardFilters } from '@/stores/useDashboardFilters';

type Tab = 'dashboards' | 'kpis' | 'reports' | 'schedules' | 'alerts';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
// Legacy `labelCls` removed when CreateModal moved to <WideModalField>.

const SEVERITY_VARIANT: Record<AlertSeverity, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  info: 'blue',
  warning: 'warning',
  critical: 'error',
};

const SCOPE_VARIANT: Record<DashboardScope, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  personal: 'neutral',
  role: 'blue',
  global: 'success',
  project: 'warning',
};

/* ─── helpers ─── */

function toNumber(v: number | string | null | undefined): number {
  if (v == null) return 0;
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function formatValue(
  value: number,
  unit: string | null | undefined,
  currency?: string | null,
): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 1_000_000) formatted = `${(value / 1_000_000).toFixed(2)}M`;
  else if (abs >= 1_000) formatted = `${(value / 1_000).toFixed(1)}k`;
  else if (Number.isInteger(value)) formatted = String(value);
  else formatted = value.toFixed(2);
  if (unit === 'percent') return `${formatted}%`;
  if (unit === 'currency') {
    // Money rule: a currency amount must always carry its ISO code. When the
    // backend resolved the project's base currency it ships it in
    // ``breakdown.currency``; render e.g. "USD 1.2M". If the code is unknown
    // (portfolio rollups with no single base currency) show the amount with
    // a neutral marker rather than an unattributable bare number.
    const code = (currency ?? '').trim().toUpperCase();
    return code ? `${code} ${formatted}` : `${formatted}`;
  }
  return formatted;
}

/** Pull the ISO currency code a money widget resolved, if any. */
function widgetCurrency(breakdown: Record<string, unknown> | undefined): string | null {
  const c = breakdown?.['currency'];
  return typeof c === 'string' && c.trim() ? c.trim().toUpperCase() : null;
}

/**
 * Portfolio money KPIs (CV/SV/EAC/ETC/VAC/COPQ/cash-in/out across projects)
 * never blend mixed currencies: the headline value is the dominant
 * currency's subtotal and the full per-currency split rides in
 * ``breakdown.by_currency`` with a ``breakdown.multi_currency`` flag. This
 * parses that map into a sorted ``[code, amount]`` list (empty when the KPI
 * is single-currency).
 */
function widgetByCurrency(
  breakdown: Record<string, unknown> | undefined,
): Array<{ currency: string; amount: number }> {
  const raw = breakdown?.['by_currency'];
  if (!raw || typeof raw !== 'object') return [];
  return Object.entries(raw as Record<string, unknown>)
    .map(([currency, v]) => ({
      currency,
      amount: typeof v === 'number' ? v : Number(v),
    }))
    .filter((e) => Number.isFinite(e.amount))
    .sort((a, b) => a.currency.localeCompare(b.currency));
}

function widgetMultiCurrency(breakdown: Record<string, unknown> | undefined): boolean {
  return breakdown?.['multi_currency'] === true;
}

/**
 * Renders the "+ N other · CODES" multi-currency hint plus the full
 * per-currency subtotal list, so a portfolio money tile is honest about the
 * fact that its headline figure is only the dominant currency's slice.
 */
function MultiCurrencyHint({
  breakdown,
  unit,
}: {
  breakdown: Record<string, unknown> | undefined;
  unit: string | null | undefined;
}) {
  const { t } = useTranslation();
  const groups = widgetByCurrency(breakdown);
  if (!widgetMultiCurrency(breakdown) || groups.length < 2) return null;
  return (
    <div className="mt-1">
      <span className="rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-medium text-content-tertiary">
        {t('bi.multi_currency', { defaultValue: 'multi-currency' })}
      </span>
      <div className="mt-1 flex flex-col gap-0.5 text-2xs text-content-tertiary">
        {groups.map((g) => (
          <div key={g.currency} className="flex justify-between gap-3 tabular-nums">
            <span className="font-medium">{g.currency}</span>
            <span>{formatValue(g.amount, unit, g.currency)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Page ─── */

export function BIDashboardsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<Tab>('dashboards');
  const [createOpen, setCreateOpen] = useState(false);
  const [activeDashboardId, setActiveDashboardId] = useState<string | null>(null);

  const dashboardsQ = useQuery({
    queryKey: ['bi', 'dashboards'],
    queryFn: listDashboards,
    enabled: tab === 'dashboards',
  });

  // Wave 1 — one-click starter pack install for fresh tenants. Wired
  // into the DashboardsGrid empty-state CTA so the user can go from "no
  // dashboards yet" to 5 role-based dashboards with widgets + KPI
  // history without leaving the page.
  const installStarterM = useMutation({
    mutationFn: installStarterPack,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['bi'] });
      addToast({
        type: 'success',
        title: t('bi.starter_installed_title', {
          defaultValue: 'Starter pack installed',
        }),
        message: t('bi.starter_installed_body', {
          defaultValue:
            '{{d}} dashboards · {{k}} KPIs · {{r}} reports · {{a}} alerts',
          d: r.dashboards,
          k: r.kpi_definitions,
          r: r.reports,
          a: r.alerts,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('bi.starter_failed', {
          defaultValue: 'Could not install starter pack',
        }),
        message: getErrorMessage(e),
      }),
  });
  const kpisQ = useQuery({
    queryKey: ['bi', 'kpis'],
    queryFn: () => listKpis(),
    // Also load on the Alerts tab so the "New Alert" modal can offer a
    // real KPI dropdown instead of degrading to a free-text code field.
    enabled: tab === 'kpis' || tab === 'alerts',
  });
  const reportsQ = useQuery({
    queryKey: ['bi', 'reports'],
    queryFn: listReports,
    enabled: tab === 'reports' || tab === 'schedules',
  });
  const alertsQ = useQuery({
    queryKey: ['bi', 'alerts'],
    queryFn: listAlerts,
    enabled: tab === 'alerts',
  });

  const activeQuery =
    tab === 'dashboards'
      ? dashboardsQ
      : tab === 'kpis'
        ? kpisQ
        : tab === 'reports' || tab === 'schedules'
          ? reportsQ
          : alertsQ;
  const isLoading = activeQuery.isLoading;
  // A failed list query must NOT fall through to the "nothing here yet"
  // empty state — that hides real backend/permission failures behind a
  // success-looking screen. Surface it with a retry instead.
  const loadError = activeQuery.isError ? activeQuery.error : null;

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          { label: t('nav.bi_dashboards', { defaultValue: 'BI Dashboards' }) },
        ]}
      />

      {/* Header — module name + icon live in the global top bar; this page
          renders only the muted subtitle + actions (canon §2). */}
      <PageHeader
        srTitle={t('nav.bi_dashboards', { defaultValue: 'BI Dashboards' })}
        subtitle={t('bi.subtitle', {
          defaultValue:
            'KPIs, scheduled reports, executive dashboards and alert rules, all in one place.',
        })}
        actions={
          (tab === 'dashboards' || tab === 'reports' || tab === 'alerts') ? (
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setCreateOpen(true)}
            >
              {tab === 'dashboards'
                ? t('bi.new_dashboard', { defaultValue: 'New Dashboard' })
                : tab === 'reports'
                  ? t('bi.new_report', { defaultValue: 'New Report' })
                  : t('bi.new_alert', { defaultValue: 'New Alert' })}
            </Button>
          ) : undefined
        }
      />

      <DismissibleInfo
        storageKey="bi-dashboards"
        title={t('bi.intro_title', {
          defaultValue: 'Stop rebuilding the same board every week',
        })}
        links={[
          {
            label: t('nav.project_controls', { defaultValue: 'Project Controls' }),
            onClick: () => navigate('/project-controls'),
          },
          {
            label: t('nav.reporting', { defaultValue: 'Reporting' }),
            onClick: () => navigate('/reporting'),
          },
          {
            label: t('nav.notifications', { defaultValue: 'Notifications' }),
            onClick: () => navigate('/notifications'),
          },
        ]}
      >
        {t('bi.intro_body', {
          defaultValue:
            'Install the starter pack in one click to get role-based dashboards, system KPIs with history, reports and alert rules, or build your own from the KPI library. Schedule any report to deliver itself to recipients on a cadence, and set alerts that fire when a KPI crosses a threshold. KPIs are computed live from your project data, so the boards stay current without manual updates.',
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              { id: 'dashboards', label: t('bi.dashboards', { defaultValue: 'My Dashboards' }), icon: LayoutDashboard },
              { id: 'kpis', label: t('bi.kpis', { defaultValue: 'KPIs' }), icon: Activity },
              { id: 'reports', label: t('bi.reports', { defaultValue: 'Reports' }), icon: FileText },
              { id: 'schedules', label: t('bi.schedules', { defaultValue: 'Schedules' }), icon: CalendarClock },
              { id: 'alerts', label: t('bi.alerts', { defaultValue: 'Alerts' }), icon: Bell },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            return (
              <button
                key={tabItem.id}
                type="button"
                onClick={() => setTab(tabItem.id)}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === tabItem.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {tabItem.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Body */}
      {isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={6} columns={4} />
        </Card>
      ) : loadError ? (
        <Card padding="md">
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('bi.load_error', { defaultValue: 'Could not load BI data' })}
            description={getErrorMessage(loadError)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => activeQuery.refetch(),
            }}
          />
        </Card>
      ) : tab === 'dashboards' ? (
        <DashboardsGrid
          rows={dashboardsQ.data ?? []}
          onOpen={(id) => setActiveDashboardId(id)}
          onCreate={() => setCreateOpen(true)}
          onInstallStarter={() => installStarterM.mutate()}
          installingStarter={installStarterM.isPending}
        />
      ) : tab === 'kpis' ? (
        <KpiLibrary rows={kpisQ.data ?? []} />
      ) : tab === 'reports' ? (
        <ReportList rows={reportsQ.data ?? []} onCreate={() => setCreateOpen(true)} />
      ) : tab === 'schedules' ? (
        <SchedulesList reports={reportsQ.data ?? []} />
      ) : (
        <AlertsList rows={alertsQ.data ?? []} onCreate={() => setCreateOpen(true)} />
      )}

      {/* Dashboard render drawer */}
      {activeDashboardId && (
        <DashboardRenderPanel
          dashboardId={activeDashboardId}
          onClose={() => setActiveDashboardId(null)}
        />
      )}

      {/* Create modal */}
      {createOpen && (
        <CreateModal
          kind={tab as 'dashboards' | 'reports' | 'alerts'}
          kpis={kpisQ.data ?? []}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Dashboards grid ─── */

function DashboardsGrid({
  rows,
  onOpen,
  onCreate,
  onInstallStarter,
  installingStarter,
}: {
  rows: Dashboard[];
  onOpen: (id: string) => void;
  onCreate: () => void;
  onInstallStarter: () => void;
  installingStarter: boolean;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <Card padding="md">
        <div className="flex flex-col items-center text-center py-8 px-4 max-w-lg mx-auto">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600 dark:bg-sky-900/30 dark:text-sky-300">
            <Sparkles size={22} />
          </div>
          <h3 className="mt-3 text-base font-semibold text-content-primary">
            {t('bi.starter_title', {
              defaultValue: 'Install the starter pack to see your data live',
            })}
          </h3>
          <p className="mt-1.5 text-sm text-content-secondary">
            {t('bi.starter_desc', {
              defaultValue:
                'One click installs 5 role-based dashboards (CEO · CFO · PM · Site · Safety), 14 system KPIs with 12-week history, 3 reports, 2 schedules and 4 alert rules. Idempotent - safe to re-run.',
            })}
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <Button
              variant="primary"
              icon={
                installingStarter ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Sparkles size={14} />
                )
              }
              onClick={onInstallStarter}
              disabled={installingStarter}
            >
              {installingStarter
                ? t('bi.starter_installing', { defaultValue: 'Installing…' })
                : t('bi.starter_install_cta', {
                    defaultValue: 'Install starter pack',
                  })}
            </Button>
            <Button
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={onCreate}
            >
              {t('bi.new_dashboard', { defaultValue: 'New Dashboard' })}
            </Button>
          </div>
        </div>
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map((d) => {
        const widgets = Array.isArray((d.layout_json as { widgets?: unknown[] } | null)?.widgets)
          ? ((d.layout_json as { widgets?: unknown[] }).widgets as unknown[]).length
          : 0;
        return (
          <Card key={d.id} padding="md" hoverable>
            <button
              type="button"
              onClick={() => onOpen(d.id)}
              className="text-left w-full focus:outline-none"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold text-content-primary truncate">{d.name}</h3>
                <Badge variant={SCOPE_VARIANT[d.scope]}>{d.scope}</Badge>
              </div>
              {d.description && (
                <p className="mt-1 text-xs text-content-secondary line-clamp-2">{d.description}</p>
              )}
              <div className="mt-3 flex items-center justify-between text-xs text-content-tertiary">
                <span>
                  {t('bi.widgets_count', {
                    defaultValue: '{{count}} widgets',
                    count: widgets,
                  })}
                </span>
                <span>
                  <DateDisplay value={d.updated_at} />
                </span>
              </div>
              {d.is_default && (
                <div className="mt-2">
                  <Badge variant="success">
                    {t('bi.default', { defaultValue: 'Default' })}
                  </Badge>
                </div>
              )}
            </button>
          </Card>
        );
      })}
    </div>
  );
}

/* ─── KPI library with sparklines ─── */

function KpiLibrary({ rows }: { rows: KpiDefinition[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Activity size={22} />}
          title={t('bi.empty_kpis', { defaultValue: 'No KPIs registered' })}
          description={t('bi.empty_kpis_desc', {
            defaultValue:
              'KPIs (CPI, SPI, cost variance, schedule health…) are provisioned per role. None are available for your account yet - an administrator can enable the relevant KPI pack.',
          })}
        />
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map((k) => (
        <KpiLibraryCard key={k.id} kpi={k} />
      ))}
    </div>
  );
}

function KpiLibraryCard({ kpi }: { kpi: KpiDefinition }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const historyQ = useQuery({
    queryKey: ['bi', 'kpi-history', kpi.code],
    queryFn: () => getKpiHistory(kpi.code, { limit: 12 }),
    staleTime: 60_000,
  });
  const history = historyQ.data?.history ?? [];
  const values = history.map((p) => toNumber(p.value));

  // Live value computed on demand. When a KPI has no persisted history
  // (KPIs registered but never computed) the history-derived headline
  // would otherwise read "—" as if the KPI were broken. The Compute
  // action calls the real /compute endpoint, persists a fresh snapshot,
  // and refetches so the card lights up.
  const [liveValue, setLiveValue] = useState<{ value: number; unit: string } | null>(null);
  const computeMut = useMutation({
    mutationFn: () => computeKpi(kpi.code, { persist: true }),
    onSuccess: (data) => {
      setLiveValue({ value: toNumber(data.value), unit: data.unit });
      qc.invalidateQueries({ queryKey: ['bi', 'kpi-history', kpi.code] });
      addToast({
        type: 'success',
        title: t('bi.kpi_computed', { defaultValue: 'KPI computed' }),
        message: `${formatValue(toNumber(data.value), data.unit)} · ${data.source_record_count} ${t('bi.records', { defaultValue: 'records' })}`,
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const historyLatest = values.length > 0 ? values[values.length - 1] : null;
  const latest = historyLatest != null ? historyLatest : liveValue?.value ?? null;
  const previous = values.length > 1 ? values[values.length - 2] : null;
  const delta =
    historyLatest != null && previous != null && previous !== 0
      ? ((historyLatest - previous) / Math.abs(previous)) * 100
      : null;
  const isLive = historyLatest == null && liveValue != null;

  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold text-content-primary truncate" title={kpi.name}>
            {kpi.name}
          </h3>
          <p className="mt-0.5 text-xs font-mono text-content-tertiary">{kpi.code}</p>
        </div>
        <Badge variant="neutral">{kpi.category}</Badge>
      </div>
      <div className="mt-3 flex items-end justify-between gap-2">
        <div>
          <p className="text-2xl font-semibold text-content-primary leading-none">
            {latest != null ? formatValue(latest, liveValue?.unit ?? kpi.unit) : '—'}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {kpi.unit}
            {isLive && (
              <span className="ml-1 rounded bg-surface-tertiary px-1 py-0.5 text-2xs font-medium text-content-tertiary">
                {t('bi.live', { defaultValue: 'live' })}
              </span>
            )}
          </p>
        </div>
        {delta != null && (
          <DeltaChip delta={delta} />
        )}
      </div>
      <div className="mt-3">
        <Sparkline values={values} loading={historyQ.isLoading} />
      </div>
      {kpi.description && (
        <p className="mt-3 text-xs text-content-secondary line-clamp-2">{kpi.description}</p>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
          {t('bi.last_n_periods', { defaultValue: 'Last {{n}} periods', n: values.length })}
        </p>
        <Button
          variant="ghost"
          size="sm"
          icon={
            computeMut.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <RefreshCw size={12} />
            )
          }
          onClick={() => computeMut.mutate()}
          loading={computeMut.isPending}
          title={t('bi.compute_now_hint', {
            defaultValue: 'Compute this KPI now from live data and save a snapshot.',
          })}
        >
          {t('bi.compute_now', { defaultValue: 'Compute' })}
        </Button>
      </div>
    </Card>
  );
}

function Sparkline({ values, loading }: { values: number[]; loading?: boolean }) {
  if (loading) {
    return <div className="h-10 w-full animate-pulse rounded bg-surface-secondary" />;
  }
  if (values.length === 0) {
    return <div className="h-10 w-full rounded bg-surface-secondary/40" />;
  }
  const W = 200;
  const H = 40;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? W / (values.length - 1) : 0;
  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = H - ((v - min) / range) * (H - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  const last = values[values.length - 1] ?? 0;
  const lastX = (values.length - 1) * step;
  const lastY = H - ((last - min) / range) * (H - 4) - 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-10 w-full">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        points={points}
        className="text-oe-blue"
      />
      {values.map((v, i) => {
        const x = i * step;
        const y = H - ((v - min) / range) * (H - 4) - 2;
        return (
          <circle key={i} cx={x} cy={y} r={1.5} className="fill-oe-blue/60" />
        );
      })}
      <circle cx={lastX} cy={lastY} r={2.5} className="fill-oe-blue" />
    </svg>
  );
}

function DeltaChip({ delta }: { delta: number }) {
  const Icon = delta > 0.5 ? TrendingUp : delta < -0.5 ? TrendingDown : Minus;
  const variant: 'success' | 'error' | 'neutral' =
    delta > 0.5 ? 'success' : delta < -0.5 ? 'error' : 'neutral';
  const sign = delta > 0 ? '+' : '';
  return (
    <Badge variant={variant}>
      <span className="flex items-center gap-1">
        <Icon size={10} />
        {sign}
        {delta.toFixed(1)}%
      </span>
    </Badge>
  );
}

/* ─── Reports ─── */

/** Pull the report-run UUID out of a ``…/report-runs/{id}/file`` URL. */
function runIdFromFileUrl(fileUrl: string | null | undefined): string | null {
  if (!fileUrl) return null;
  const m = /report-runs\/([0-9a-fA-F-]{36})\/file/.exec(fileUrl);
  return m?.[1] ?? null;
}

function ReportList({
  rows,
  onCreate,
}: {
  rows: ReportDefinition[];
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Remember the most recent run's downloadable file per report so the row
  // can offer a "Download" action instead of discarding the generated file.
  const [lastRun, setLastRun] = useState<Record<string, { runId: string; format: string }>>({});
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const runMut = useMutation({
    mutationFn: (id: string) => runReport(id),
    onSuccess: (data) => {
      const runId = runIdFromFileUrl(data.file_url);
      if (runId) {
        setLastRun((prev) => ({
          ...prev,
          [data.report_id]: { runId, format: data.output_format },
        }));
      }
      addToast({
        type: 'success',
        title: t('bi.report_run_ok', { defaultValue: 'Report generated' }),
        message: runId
          ? t('bi.report_run_ok_download', {
              defaultValue: '{{count}} rows - use Download to open the file.',
              count: data.row_count,
            })
          : `${data.row_count} ${t('bi.rows', { defaultValue: 'rows' })}`,
      });
      qc.invalidateQueries({ queryKey: ['bi', 'reports'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const downloadRun = async (reportName: string, runId: string, format: string) => {
    setDownloadingId(runId);
    try {
      await downloadReportRun(runId, `${reportName || 'report'}.${format}`);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setDownloadingId(null);
    }
  };

  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<FileText size={22} />}
          title={t('bi.empty_reports', { defaultValue: 'No reports yet' })}
          description={t('bi.empty_reports_desc', {
            defaultValue:
              'Define a report (PDF/Excel/CSV) and schedule it for stakeholders.',
          })}
          action={{
            label: t('bi.new_report', { defaultValue: 'New Report' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5 text-left">{t('bi.code', { defaultValue: 'Code' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.name', { defaultValue: 'Name' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.scope', { defaultValue: 'Scope' })}</th>
              <th className="px-4 py-2.5 text-left">{t('common.format')}</th>
              <th className="px-4 py-2.5 text-right">{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-border-light">
                <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
                <td className="px-4 py-2 font-medium">{r.name}</td>
                <td className="px-4 py-2"><Badge variant="neutral">{r.scope}</Badge></td>
                <td className="px-4 py-2 text-xs text-content-secondary uppercase">{r.output_format}</td>
                <td className="px-4 py-2">
                  <div className="flex items-center justify-end gap-2">
                    {lastRun[r.id] && (
                      <Button
                        variant="ghost"
                        icon={<Download size={12} />}
                        onClick={() =>
                          downloadRun(
                            r.name,
                            lastRun[r.id]!.runId,
                            lastRun[r.id]!.format,
                          )
                        }
                        loading={downloadingId === lastRun[r.id]!.runId}
                        title={t('bi.download_report', {
                          defaultValue: 'Download the last generated file',
                        })}
                      >
                        {t('bi.download', { defaultValue: 'Download' })}
                      </Button>
                    )}
                    <Button
                      variant="secondary"
                      icon={<Play size={12} />}
                      onClick={() => runMut.mutate(r.id)}
                      loading={runMut.isPending && runMut.variables === r.id}
                    >
                      {t('bi.run_now', { defaultValue: 'Run now' })}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ─── Schedules ─── */

const FREQUENCY_LABELS: Record<ReportFrequency, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
};

function SchedulesList({ reports }: { reports: ReportDefinition[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [newOpen, setNewOpen] = useState(false);

  // Real schedules — the backend GET /report-schedules resolves them from
  // the reports the caller can see, so frequency / next-run / recipients
  // are no longer fabricated.
  const schedulesQ = useQuery({
    queryKey: ['bi', 'schedules'],
    queryFn: listSchedules,
  });
  const schedules = schedulesQ.data ?? [];

  const reportName = (id: string) =>
    reports.find((r) => r.id === id)?.name ??
    t('bi.report', { defaultValue: 'Report' });

  const toggleMut = useMutation({
    mutationFn: (args: { id: string; enabled: boolean }) =>
      updateSchedule(args.id, { enabled: args.enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bi', 'schedules'] });
      addToast({
        type: 'success',
        title: t('bi.schedule_updated', { defaultValue: 'Schedule updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const runMut = useMutation({
    mutationFn: (id: string) => runScheduleNow(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['bi', 'schedules'] });
      addToast({
        type: 'success',
        title: t('bi.schedule_ran', { defaultValue: 'Schedule run' }),
        message: `${data.row_count} ${t('bi.rows', { defaultValue: 'rows' })}`,
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const recipientCount = (s: ReportSchedule) =>
    Array.isArray(s.recipients_json) ? s.recipients_json.length : 0;

  const freqLabel = (f: string) =>
    t(`bi.freq_${f}`, {
      defaultValue: FREQUENCY_LABELS[f as ReportFrequency] ?? f,
    });

  if (schedulesQ.isError) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<AlertOctagon size={22} />}
          title={t('bi.load_error', { defaultValue: 'Could not load BI data' })}
          description={getErrorMessage(schedulesQ.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => schedulesQ.refetch(),
          }}
        />
      </Card>
    );
  }

  if (!schedulesQ.isLoading && schedules.length === 0) {
    return (
      <>
        <Card padding="md">
          <EmptyState
            icon={<CalendarClock size={22} />}
            title={t('bi.empty_schedules', { defaultValue: 'No scheduled reports' })}
            description={
              reports.length === 0
                ? t('bi.empty_schedules_desc', {
                    defaultValue:
                      'Create a report first, then attach a recurring schedule with recipients.',
                  })
                : t('bi.empty_schedules_have_reports', {
                    defaultValue:
                      'Attach a recurring schedule to one of your reports to deliver it automatically.',
                  })
            }
            action={
              reports.length > 0
                ? {
                    label: t('bi.new_schedule', { defaultValue: 'New schedule' }),
                    onClick: () => setNewOpen(true),
                  }
                : undefined
            }
          />
        </Card>
        {newOpen && (
          <NewScheduleModal reports={reports} onClose={() => setNewOpen(false)} />
        )}
      </>
    );
  }

  return (
    <>
      <div className="flex justify-end">
        <Button
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setNewOpen(true)}
          disabled={reports.length === 0}
          title={
            reports.length === 0
              ? t('bi.new_schedule_needs_report', {
                  defaultValue: 'Create a report first to schedule it.',
                })
              : undefined
          }
        >
          {t('bi.new_schedule', { defaultValue: 'New schedule' })}
        </Button>
      </div>
      <Card padding="none" className="mt-3">
        {schedulesQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={4} columns={5} />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">{t('bi.report', { defaultValue: 'Report' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('bi.frequency', { defaultValue: 'Frequency' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('bi.next_run', { defaultValue: 'Next run' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('bi.recipients', { defaultValue: 'Recipients' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('bi.enabled', { defaultValue: 'Enabled' })}</th>
                  <th className="px-4 py-2.5 text-right">{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((s) => (
                  <tr key={s.id} className="border-t border-border-light">
                    <td className="px-4 py-2 font-medium">
                      {reportName(s.report_definition_id)}
                    </td>
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      {freqLabel(s.frequency)}{' '}
                      <span className="text-content-tertiary">· {s.time_of_day} {s.timezone}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      {s.next_run_at ? <DateDisplay value={s.next_run_at} format="datetime" /> : '—'}
                    </td>
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      {recipientCount(s) > 0
                        ? t('bi.recipients_count', {
                            defaultValue: '{{count}} recipients',
                            count: recipientCount(s),
                          })
                        : '—'}
                    </td>
                    <td className="px-4 py-2">
                      <label className="inline-flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={s.enabled}
                          disabled={toggleMut.isPending}
                          onChange={(e) =>
                            toggleMut.mutate({ id: s.id, enabled: e.target.checked })
                          }
                          className="h-4 w-4 rounded border-border accent-oe-blue"
                          aria-label={t('bi.schedule_enable_aria', {
                            defaultValue: 'Enable schedule for {{name}}',
                            name: reportName(s.report_definition_id),
                          })}
                        />
                        <span className="text-xs text-content-tertiary">
                          {s.enabled
                            ? t('bi.on', { defaultValue: 'On' })
                            : t('bi.off', { defaultValue: 'Off' })}
                        </span>
                      </label>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Button
                        variant="secondary"
                        icon={<Play size={12} />}
                        onClick={() => runMut.mutate(s.id)}
                        loading={runMut.isPending && runMut.variables === s.id}
                      >
                        {t('bi.run_now', { defaultValue: 'Run now' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-border-light px-4 py-2.5 text-xs text-content-tertiary">
          {t('bi.schedules_hint', {
            defaultValue:
              'Schedules deliver a report automatically on the chosen cadence. "Run now" generates it immediately.',
          })}
        </div>
      </Card>
      {newOpen && (
        <NewScheduleModal reports={reports} onClose={() => setNewOpen(false)} />
      )}
    </>
  );
}

/* ─── New schedule modal ─── */

function NewScheduleModal({
  reports,
  onClose,
}: {
  reports: ReportDefinition[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    report_definition_id: reports[0]?.id ?? '',
    frequency: 'weekly' as ReportFrequency,
    time_of_day: '08:00',
    timezone: 'UTC',
    enabled: true,
  });

  const submit = async () => {
    setBusy(true);
    try {
      if (!form.report_definition_id) throw new Error('Report required');
      if (!/^\d{2}:\d{2}$/.test(form.time_of_day)) {
        throw new Error('Time must be HH:MM');
      }
      await createSchedule({
        report_definition_id: form.report_definition_id,
        frequency: form.frequency,
        time_of_day: form.time_of_day,
        timezone: form.timezone || 'UTC',
        enabled: form.enabled,
      });
      addToast({
        type: 'success',
        title: t('bi.schedule_created', { defaultValue: 'Schedule created' }),
      });
      qc.invalidateQueries({ queryKey: ['bi', 'schedules'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bi.new_schedule', { defaultValue: 'New schedule' })}
      subtitle={t('bi.new_schedule_subtitle', {
        defaultValue:
          'Deliver a report automatically on a recurring cadence. Times are interpreted in the chosen timezone.',
      })}
      size="md"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('bi.report', { defaultValue: 'Report' })}
          required
          span={2}
        >
          <select
            value={form.report_definition_id}
            onChange={(e) => setForm({ ...form, report_definition_id: e.target.value })}
            className={inputCls}
          >
            {reports.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('bi.frequency', { defaultValue: 'Frequency' })}>
          <select
            value={form.frequency}
            onChange={(e) =>
              setForm({ ...form, frequency: e.target.value as ReportFrequency })
            }
            className={inputCls}
          >
            <option value="daily">{t('bi.freq_daily', { defaultValue: 'Daily' })}</option>
            <option value="weekly">{t('bi.freq_weekly', { defaultValue: 'Weekly' })}</option>
            <option value="monthly">{t('bi.freq_monthly', { defaultValue: 'Monthly' })}</option>
            <option value="quarterly">{t('bi.freq_quarterly', { defaultValue: 'Quarterly' })}</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('bi.time_of_day', { defaultValue: 'Time of day (HH:MM)' })}
          hint={t('bi.time_of_day_hint', {
            defaultValue: '24-hour clock in the timezone below.',
          })}
        >
          <input
            type="time"
            value={form.time_of_day}
            onChange={(e) => setForm({ ...form, time_of_day: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('bi.timezone', { defaultValue: 'Timezone' })} span={2}>
          <input
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            className={inputCls}
            placeholder="UTC"
          />
        </WideModalField>
        <WideModalField label={t('bi.enabled', { defaultValue: 'Enabled' })} span={2}>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="h-4 w-4 rounded border-border accent-oe-blue"
            />
            {t('bi.schedule_enabled_label', {
              defaultValue: 'Start delivering on this schedule immediately',
            })}
          </label>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Alerts ─── */

function AlertsList({
  rows,
  onCreate,
}: {
  rows: AlertRule[];
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const toggleMut = useMutation({
    mutationFn: (args: { id: string; enabled: boolean }) => toggleAlert(args.id, args.enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bi', 'alerts'] });
      addToast({ type: 'success', title: t('bi.alert_toggled', { defaultValue: 'Alert updated' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const evalMut = useMutation({
    mutationFn: () => evaluateAlertsNow(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['bi', 'alerts'] });
      addToast({
        type: 'success',
        title: t('bi.alerts_checked', { defaultValue: 'Alert checks complete' }),
        message: t('bi.alerts_fired', {
          defaultValue: '{{count}} alerts fired',
          count: data.fired,
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Bell size={22} />}
          title={t('bi.empty_alerts', { defaultValue: 'No alert rules' })}
          description={t('bi.empty_alerts_desc', {
            defaultValue: 'Watch a KPI and notify your team when it crosses a threshold.',
          })}
          action={{
            label: t('bi.new_alert', { defaultValue: 'New Alert' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  return (
    <>
    <div className="flex justify-end">
      <Button
        variant="secondary"
        icon={
          evalMut.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )
        }
        onClick={() => evalMut.mutate()}
        loading={evalMut.isPending}
        title={t('bi.run_alert_checks_hint', {
          defaultValue: 'Evaluate every enabled alert now and fire any that breach.',
        })}
      >
        {t('bi.run_alert_checks', { defaultValue: 'Run checks now' })}
      </Button>
    </div>
    <Card padding="none" className="mt-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5 text-left">{t('bi.name', { defaultValue: 'Name' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.kpi', { defaultValue: 'KPI' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.condition', { defaultValue: 'Condition' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.severity', { defaultValue: 'Severity' })}</th>
              <th className="px-4 py-2.5 text-left">{t('bi.last_triggered', { defaultValue: 'Last fired' })}</th>
              <th className="px-4 py-2.5 text-right">{t('bi.enabled', { defaultValue: 'Enabled' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className="border-t border-border-light">
                <td className="px-4 py-2 font-medium">{a.name}</td>
                <td className="px-4 py-2 font-mono text-xs text-content-secondary">{a.kpi_code}</td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {a.condition} {String(a.threshold_value)}
                </td>
                <td className="px-4 py-2">
                  <Badge variant={SEVERITY_VARIANT[a.severity]} dot>
                    {a.severity}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {a.last_triggered_at ? <DateDisplay value={a.last_triggered_at} /> : '—'}
                </td>
                <td className="px-4 py-2 text-right">
                  <label
                    className="inline-flex items-center gap-2 cursor-pointer"
                    title={
                      a.enabled
                        ? t('bi.alert_disable_aria', {
                            defaultValue: 'Disable {{name}}',
                            name: a.name,
                          })
                        : t('bi.alert_enable_aria', {
                            defaultValue: 'Enable {{name}}',
                            name: a.name,
                          })
                    }
                  >
                    <input
                      type="checkbox"
                      checked={a.enabled}
                      disabled={toggleMut.isPending}
                      onChange={(e) =>
                        toggleMut.mutate({ id: a.id, enabled: e.target.checked })
                      }
                      className="h-4 w-4 rounded border-border accent-oe-blue"
                      aria-label={t('bi.alert_enable_aria', {
                        defaultValue: 'Enable {{name}}',
                        name: a.name,
                      })}
                    />
                    <span className="text-xs text-content-tertiary">
                      {a.enabled
                        ? t('bi.on', { defaultValue: 'On' })
                        : t('bi.off', { defaultValue: 'Off' })}
                    </span>
                  </label>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
    </>
  );
}

/* ─── Dashboard render panel ─── */

/** Close a drawer when the user presses Escape (matches WideModal UX). */
function useEscapeToClose(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

function DashboardRenderPanel({
  dashboardId,
  onClose,
}: {
  dashboardId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [addWidgetOpen, setAddWidgetOpen] = useState(false);
  useEscapeToClose(onClose);

  // Wave 4 / T11 — cross-filter wiring. The store is keyed by the active
  // dashboard so opening a different board starts with a clean slate.
  const { activeDashboardId, filters, setActiveDashboard, setFilter, removeFilter, clearFilters } =
    useDashboardFilters();
  useEffect(() => {
    setActiveDashboard(dashboardId);
    // Wipe on unmount so closing the drawer doesn't leak filters into the next open.
    return () => setActiveDashboard(null);
  }, [dashboardId, setActiveDashboard]);

  // Two query paths:
  //  * /render — the legacy static path, used for the dashboard header
  //    (name + cross_filter_enabled flag).
  //  * /evaluate — the new path that honours cross-filter chips. Keyed on
  //    the active filter dict so React Query re-fetches whenever the user
  //    adds / removes a chip.
  const renderQ = useQuery({
    queryKey: ['bi', 'dashboard-render', dashboardId],
    queryFn: () => renderDashboard(dashboardId),
  });

  const filtersForQuery = activeDashboardId === dashboardId ? filters : {};
  const filterKeysJson = JSON.stringify(
    Object.keys(filtersForQuery).sort().reduce<Record<string, unknown>>((acc, k) => {
      acc[k] = filtersForQuery[k];
      return acc;
    }, {}),
  );
  const evaluateQ = useQuery({
    queryKey: ['bi', 'dashboard-evaluate', dashboardId, filterKeysJson],
    queryFn: () => evaluateDashboard(dashboardId, filtersForQuery),
    enabled: Boolean(renderQ.data),
  });

  const data = renderQ.data;
  const evalData = evaluateQ.data;
  const widgetMap = new Map(data?.widgets.map((w) => [w.widget.id, w.widget]) ?? []);
  const evaluatedWidgets = evalData?.widgets ?? [];

  const handleCellClick = (widget: WidgetEvaluateResult, row?: Record<string, unknown>) => {
    if (!data?.dashboard.cross_filter_enabled || !widget.drill_path) return;
    const path = widget.drill_path;
    const value = resolveDrillValue(path, row, widget);
    if (value == null || value === '') return;
    setFilter(path.filter_field, value);
  };

  // Owners can author the board in place. Both mutations invalidate the
  // render + evaluate queries so the grid reflects the change immediately.
  const refreshBoard = () => {
    qc.invalidateQueries({ queryKey: ['bi', 'dashboard-render', dashboardId] });
    qc.invalidateQueries({ queryKey: ['bi', 'dashboard-evaluate', dashboardId] });
    qc.invalidateQueries({ queryKey: ['bi', 'dashboards'] });
  };
  const deleteWidgetMut = useMutation({
    mutationFn: (widgetId: string) => deleteWidget(widgetId),
    onSuccess: () => {
      refreshBoard();
      addToast({
        type: 'success',
        title: t('bi.widget_removed', { defaultValue: 'Widget removed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const [exportingId, setExportingId] = useState<string | null>(null);
  const exportWidget = async (widgetId: string, format: 'csv' | 'svg') => {
    setExportingId(widgetId);
    try {
      await downloadWidgetExport(widgetId, format);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setExportingId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="bi-dashboard-drawer-title"
        className="relative h-full w-full max-w-3xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <div>
            <h2 id="bi-dashboard-drawer-title" className="text-base font-semibold">
              {data?.dashboard.name ?? t('bi.dashboard', { defaultValue: 'Dashboard' })}
            </h2>
            {data?.rendered_at && (
              <p className="text-xs text-content-tertiary">
                <DateDisplay value={data.rendered_at} format="datetime" />
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() => setAddWidgetOpen(true)}
            >
              {t('bi.add_widget', { defaultValue: 'Add widget' })}
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 hover:bg-surface-secondary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="space-y-3 p-5">
          {data?.dashboard.cross_filter_enabled && Object.keys(filtersForQuery).length > 0 && (
            <CrossFilterChips
              filters={filtersForQuery}
              onRemove={removeFilter}
              onClear={clearFilters}
            />
          )}
          {renderQ.isLoading && <SkeletonTable rows={4} columns={3} />}
          {renderQ.isError && (
            <p className="text-sm text-rose-600">{getErrorMessage(renderQ.error)}</p>
          )}
          {evaluateQ.isError && !renderQ.isError && (
            <p className="text-sm text-rose-600">{getErrorMessage(evaluateQ.error)}</p>
          )}
          {data && data.widgets.length === 0 && (
            <EmptyState
              icon={<LayoutDashboard size={22} />}
              title={t('bi.empty_widgets', { defaultValue: 'No widgets pinned' })}
              description={t('bi.empty_widgets_desc_v2', {
                defaultValue:
                  'Add a KPI card, chart or gauge to start building this dashboard.',
              })}
              action={{
                label: t('bi.add_widget', { defaultValue: 'Add widget' }),
                onClick: () => setAddWidgetOpen(true),
              }}
            />
          )}
          {data && data.widgets.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {evaluatedWidgets.length > 0
                ? evaluatedWidgets.map((w) => {
                    const widgetMeta = widgetMap.get(w.id);
                    if (!widgetMeta) return null;
                    // Map evaluate result to the WidgetRenderResult shape the
                    // existing <WidgetCard> understands so we don't fork the
                    // chart rendering code.
                    const mapped: WidgetRenderResult = {
                      widget: widgetMeta,
                      value: w.value,
                      unit: w.unit,
                      breakdown: {
                        ...w.breakdown,
                        // Inject the series into ``trend`` so the line/bar
                        // charts pick it up via their existing extraction.
                        ...(w.series.length > 0 ? { trend: w.series } : {}),
                      },
                      from_cache: false,
                    };
                    return (
                      <WidgetTile
                        key={w.id}
                        widgetId={w.id}
                        spanFull={widgetMeta.widget_type === 'table'}
                        exporting={exportingId === w.id}
                        onExport={(fmt) => exportWidget(w.id, fmt)}
                        onDelete={() => deleteWidgetMut.mutate(w.id)}
                        deleting={deleteWidgetMut.isPending && deleteWidgetMut.variables === w.id}
                      >
                        <WidgetCard
                          widget={mapped}
                          crossFilterEnabled={data.dashboard.cross_filter_enabled}
                          drillPath={w.drill_path}
                          onCellClick={(row) => handleCellClick(w, row)}
                        />
                      </WidgetTile>
                    );
                  })
                : data.widgets.map((w) => (
                    <WidgetTile
                      key={w.widget.id}
                      widgetId={w.widget.id}
                      spanFull={w.widget.widget_type === 'table'}
                      exporting={exportingId === w.widget.id}
                      onExport={(fmt) => exportWidget(w.widget.id, fmt)}
                      onDelete={() => deleteWidgetMut.mutate(w.widget.id)}
                      deleting={deleteWidgetMut.isPending && deleteWidgetMut.variables === w.widget.id}
                    >
                      <WidgetCard widget={w} />
                    </WidgetTile>
                  ))}
            </div>
          )}
        </div>
      </div>
      {addWidgetOpen && (
        <AddWidgetModal
          dashboardId={dashboardId}
          onClose={() => setAddWidgetOpen(false)}
          onCreated={refreshBoard}
        />
      )}
    </div>
  );
}

/**
 * Wraps a rendered widget with owner controls (export CSV/SVG, remove).
 * The ``WidgetCard`` already returns a ``<Card>`` per widget type; this
 * adds a thin hover-revealed action row beneath it so the chart code
 * itself stays untouched. ``table`` widgets span both columns, so the
 * wrapper mirrors that to keep the grid intact.
 */
function WidgetTile({
  widgetId,
  spanFull,
  exporting,
  deleting,
  onExport,
  onDelete,
  children,
}: {
  widgetId: string;
  spanFull?: boolean;
  exporting?: boolean;
  deleting?: boolean;
  onExport: (format: 'csv' | 'svg') => void;
  onDelete: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className={clsx('group relative', spanFull && 'md:col-span-2')}>
      {children}
      <div className="mt-1 flex items-center justify-end gap-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          onClick={() => onExport('csv')}
          disabled={exporting}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50"
          title={t('bi.export_csv', { defaultValue: 'Export data as CSV' })}
          data-widget-id={widgetId}
        >
          {exporting ? <Loader2 size={11} className="animate-spin" /> : <Download size={11} />}
          CSV
        </button>
        <button
          type="button"
          onClick={() => onExport('svg')}
          disabled={exporting}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50"
          title={t('bi.export_svg', { defaultValue: 'Export chart as SVG' })}
        >
          <Download size={11} />
          SVG
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:hover:bg-rose-900/20"
          title={t('bi.remove_widget', { defaultValue: 'Remove widget' })}
        >
          {deleting ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
          {t('bi.remove', { defaultValue: 'Remove' })}
        </button>
      </div>
    </div>
  );
}

/* ─── Add widget modal ─── */

const ADD_WIDGET_TYPES: WidgetType[] = [
  'kpi_card',
  'line_chart',
  'bar_chart',
  'gauge',
  'table',
];

function AddWidgetModal({
  dashboardId,
  onClose,
  onCreated,
}: {
  dashboardId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  // The modal needs the KPI catalogue to bind a widget to a KPI code.
  const kpisQ = useQuery({ queryKey: ['bi', 'kpis'], queryFn: () => listKpis() });
  const kpis = kpisQ.data ?? [];
  const [form, setForm] = useState({
    widget_type: 'kpi_card' as WidgetType,
    kpi_code: '',
  });

  // Default the KPI code to the first available once the list loads.
  useEffect(() => {
    if (!form.kpi_code && kpis.length > 0) {
      setForm((f) => ({ ...f, kpi_code: kpis[0]!.code }));
    }
  }, [kpis, form.kpi_code]);

  const submit = async () => {
    setBusy(true);
    try {
      if (!form.kpi_code) throw new Error('KPI required');
      await createWidget({
        dashboard_id: dashboardId,
        widget_type: form.widget_type,
        kpi_code: form.kpi_code,
      });
      addToast({
        type: 'success',
        title: t('bi.widget_added', { defaultValue: 'Widget added' }),
      });
      onCreated();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bi.add_widget', { defaultValue: 'Add widget' })}
      subtitle={t('bi.add_widget_subtitle', {
        defaultValue: 'Pick a KPI and how it should be displayed on the dashboard.',
      })}
      size="md"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            disabled={busy || kpis.length === 0}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('bi.add_widget', { defaultValue: 'Add widget' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('bi.kpi', { defaultValue: 'KPI' })}
          required
          span={2}
        >
          {kpisQ.isLoading ? (
            <div className="h-9 w-full animate-pulse rounded-lg bg-surface-secondary" />
          ) : kpis.length > 0 ? (
            <select
              value={form.kpi_code}
              onChange={(e) => setForm({ ...form, kpi_code: e.target.value })}
              className={inputCls}
            >
              {kpis.map((k) => (
                <option key={k.id} value={k.code}>
                  {k.code} — {k.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-content-tertiary">
              {t('bi.no_kpis_for_widget', {
                defaultValue:
                  'No KPIs are registered yet. Install the starter pack or register a KPI first.',
              })}
            </p>
          )}
        </WideModalField>
        <WideModalField
          label={t('bi.widget_type', { defaultValue: 'Display as' })}
          span={2}
        >
          <select
            value={form.widget_type}
            onChange={(e) =>
              setForm({ ...form, widget_type: e.target.value as WidgetType })
            }
            className={inputCls}
          >
            {ADD_WIDGET_TYPES.map((wt) => (
              <option key={wt} value={wt}>
                {t(`bi.widget_type_${wt}`, {
                  defaultValue: WIDGET_TYPE_LABELS[wt],
                })}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

const WIDGET_TYPE_LABELS: Record<string, string> = {
  kpi_card: 'KPI card',
  line_chart: 'Line chart',
  bar_chart: 'Bar chart',
  gauge: 'Gauge',
  table: 'Table',
};

/**
 * Pull the per-click value off either the row (table/chart row click) or a
 * literal value the widget config carries. ``filter_value_from`` is a
 * lightweight expression — ``"row.<field>"`` reaches into the clicked row,
 * any other string is treated as a literal.
 */
function resolveDrillValue(
  path: DrillPath,
  row: Record<string, unknown> | undefined,
  widget: WidgetEvaluateResult,
): unknown {
  const expr = path.filter_value_from;
  if (!expr) {
    // No expression — fall back to the widget's kpi_code so a card click
    // can at least filter "this KPI" out of the dashboard.
    return widget.kpi_code ?? widget.id;
  }
  if (expr.startsWith('row.') && row) {
    const key = expr.slice(4);
    return row[key];
  }
  return expr;
}

function CrossFilterChips({
  filters,
  onRemove,
  onClear,
}: {
  filters: Record<string, unknown>;
  onRemove: (key: string) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const entries = Object.entries(filters);
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <span className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
        {t('bi.active_filters', { defaultValue: 'Active filters' })}
      </span>
      {entries.map(([key, value]) => (
        <button
          key={key}
          type="button"
          onClick={() => onRemove(key)}
          className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2.5 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue/20"
        >
          <span>{key}: {String(value)}</span>
          <X size={10} />
        </button>
      ))}
      {entries.length > 1 && (
        <button
          type="button"
          onClick={onClear}
          className="ml-auto text-xs text-content-tertiary hover:text-content-primary"
        >
          {t('bi.clear_filters', { defaultValue: 'Clear all' })}
        </button>
      )}
    </div>
  );
}

function WidgetCard({
  widget,
  crossFilterEnabled = false,
  drillPath = null,
  onCellClick,
}: {
  widget: WidgetRenderResult;
  crossFilterEnabled?: boolean;
  drillPath?: DrillPath | null;
  onCellClick?: (row?: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const type = widget.widget.widget_type;
  const value = toNumber(widget.value);
  const currency = widgetCurrency(widget.breakdown);
  const trend = (widget.breakdown?.['trend'] as unknown[]) || [];
  const trendValues = Array.isArray(trend)
    ? trend.map((p) => toNumber((p as { value?: number | string }).value ?? 0))
    : [];
  const tableRows = (widget.breakdown?.['rows'] as unknown[]) || [];

  // A widget is "drillable" only when the dashboard is opted in and the
  // widget defines a drill_path. Otherwise we render the static card so
  // we don't bait the user with a clickable cursor for nothing.
  const drillable = crossFilterEnabled && !!drillPath;
  const cardClickable = drillable && Boolean(onCellClick);
  const cardOnClick = cardClickable ? () => onCellClick?.() : undefined;

  if (type === 'kpi_card') {
    const prev =
      trendValues.length > 1 ? trendValues[trendValues.length - 2] : null;
    const delta =
      prev != null && prev !== 0 ? ((value - prev) / Math.abs(prev)) * 100 : null;
    return (
      <Card
        padding="md"
        hoverable={cardClickable || undefined}
        onClick={cardOnClick}
        className={cardClickable ? 'cursor-pointer' : undefined}
      >
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {widget.widget.kpi_code || t('bi.kpi', { defaultValue: 'KPI' })}
        </p>
        <div className="mt-2 flex items-end justify-between">
          <p className="text-3xl font-semibold">
            {formatValue(value, widget.unit ?? null, currency)}
          </p>
          {delta != null && <DeltaChip delta={delta} />}
        </div>
        <p className="mt-1 text-xs text-content-tertiary">{widget.unit ?? ''}</p>
        <MultiCurrencyHint breakdown={widget.breakdown} unit={widget.unit} />
      </Card>
    );
  }

  if (type === 'line_chart' || type === 'bar_chart') {
    return (
      <Card
        padding="md"
        hoverable={cardClickable || undefined}
        onClick={cardOnClick}
        className={cardClickable ? 'cursor-pointer' : undefined}
      >
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {widget.widget.kpi_code || t('bi.chart', { defaultValue: 'Chart' })}
        </p>
        <div className="mt-2">
          {type === 'line_chart' ? (
            <Sparkline values={trendValues.length ? trendValues : [value]} />
          ) : (
            <MiniBarChart values={trendValues.length ? trendValues : [value]} />
          )}
        </div>
      </Card>
    );
  }

  if (type === 'gauge') {
    const threshold = toNumber(widget.breakdown?.['threshold'] as number | string);
    return (
      <Card
        padding="md"
        hoverable={cardClickable || undefined}
        onClick={cardOnClick}
        className={cardClickable ? 'cursor-pointer' : undefined}
      >
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {widget.widget.kpi_code || t('bi.gauge', { defaultValue: 'Gauge' })}
        </p>
        <HalfGauge value={value} threshold={threshold || Math.max(1, value * 1.5)} />
        <p className="mt-1 text-center text-sm font-semibold">
          {formatValue(value, widget.unit ?? null, currency)}
        </p>
        <MultiCurrencyHint breakdown={widget.breakdown} unit={widget.unit} />
      </Card>
    );
  }

  if (type === 'table') {
    const rows = Array.isArray(tableRows) ? (tableRows as Array<Record<string, unknown>>) : [];
    const cols = rows.length > 0 ? Object.keys(rows[0] ?? {}) : [];
    const rowClickable = drillable && Boolean(onCellClick);
    return (
      <Card padding="md" className="md:col-span-2">
        <p className="text-xs uppercase tracking-wide text-content-tertiary mb-2">
          {widget.widget.kpi_code || t('bi.table', { defaultValue: 'Table' })}
        </p>
        {rows.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('bi.no_rows', { defaultValue: 'No rows' })}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-content-tertiary">
                <tr>
                  {cols.map((c) => (
                    <th key={c} className="px-2 py-1 text-left font-medium">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 10).map((row, i) => (
                  <tr
                    key={i}
                    onClick={rowClickable ? () => onCellClick?.(row) : undefined}
                    className={clsx(
                      'border-t border-border-light',
                      rowClickable && 'cursor-pointer hover:bg-surface-secondary/60',
                    )}
                  >
                    {cols.map((c) => (
                      <td key={c} className="px-2 py-1">{String(row[c] ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    );
  }

  return (
    <Card
      padding="md"
      hoverable={cardClickable || undefined}
      onClick={cardOnClick}
      className={cardClickable ? 'cursor-pointer' : undefined}
    >
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{type}</p>
      <p className="mt-2 text-lg font-semibold">{formatValue(value, widget.unit ?? null, currency)}</p>
      <MultiCurrencyHint breakdown={widget.breakdown} unit={widget.unit} />
    </Card>
  );
}

function MiniBarChart({ values }: { values: number[] }) {
  if (values.length === 0) return <div className="h-16 w-full bg-surface-secondary/40" />;
  const W = 200;
  const H = 60;
  const max = Math.max(...values, 1);
  const bw = W / values.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-16 w-full">
      {values.map((v, i) => {
        const h = (v / max) * (H - 4);
        return (
          <rect
            key={i}
            x={i * bw + 1}
            y={H - h - 2}
            width={Math.max(1, bw - 2)}
            height={Math.max(1, h)}
            className="fill-oe-blue/70"
          />
        );
      })}
    </svg>
  );
}

function HalfGauge({ value, threshold }: { value: number; threshold: number }) {
  const t = Math.max(0.001, threshold);
  const pct = Math.max(0, Math.min(1, value / t));
  // Half circle from -180° to 0°. Needle angle:
  const angle = -Math.PI + Math.PI * pct;
  const cx = 60;
  const cy = 50;
  const r = 40;
  const nx = cx + Math.cos(angle) * (r - 4);
  const ny = cy + Math.sin(angle) * (r - 4);
  const arc = (theta: number) => ({
    x: cx + Math.cos(theta) * r,
    y: cy + Math.sin(theta) * r,
  });
  const start = arc(Math.PI);
  const end = arc(0);
  return (
    <svg viewBox="0 0 120 60" className="mx-auto h-20 w-full">
      <path
        d={`M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${end.x} ${end.y}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={6}
        className="text-surface-secondary"
      />
      <path
        d={`M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${arc(-Math.PI + Math.PI * pct).x} ${arc(-Math.PI + Math.PI * pct).y}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={6}
        className={pct > 0.85 ? 'text-rose-500' : pct > 0.6 ? 'text-amber-500' : 'text-oe-blue'}
      />
      <line x1={cx} y1={cy} x2={nx} y2={ny} strokeWidth={2} className="stroke-content-primary" />
      <circle cx={cx} cy={cy} r={3} className="fill-content-primary" />
    </svg>
  );
}

/* ─── Create modal ─── */

function CreateModal({
  kind,
  kpis,
  onClose,
}: {
  kind: 'dashboards' | 'reports' | 'alerts';
  kpis: KpiDefinition[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const [dashForm, setDashForm] = useState({
    name: '',
    description: '',
    scope: 'personal' as DashboardScope,
    cross_filter_enabled: false,
  });
  const [reportForm, setReportForm] = useState({
    code: '',
    name: '',
    description: '',
    output_format: 'pdf' as 'pdf' | 'xlsx' | 'csv' | 'json',
  });
  const [alertForm, setAlertForm] = useState({
    name: '',
    kpi_code: kpis[0]?.code ?? '',
    condition: 'below' as AlertCondition,
    threshold_value: '0',
    severity: 'warning' as AlertSeverity,
  });

  const submit = async () => {
    setBusy(true);
    try {
      if (kind === 'dashboards') {
        if (!dashForm.name.trim()) throw new Error('Name required');
        await createDashboard(dashForm);
        addToast({ type: 'success', title: t('bi.dashboard_created', { defaultValue: 'Dashboard created' }) });
        qc.invalidateQueries({ queryKey: ['bi', 'dashboards'] });
      } else if (kind === 'reports') {
        if (!reportForm.code.trim() || !reportForm.name.trim()) throw new Error('Code & name required');
        await createReport(reportForm);
        addToast({ type: 'success', title: t('bi.report_created', { defaultValue: 'Report created' }) });
        qc.invalidateQueries({ queryKey: ['bi', 'reports'] });
      } else {
        if (!alertForm.name.trim() || !alertForm.kpi_code.trim()) throw new Error('Name & KPI required');
        await createAlert({
          name: alertForm.name,
          kpi_code: alertForm.kpi_code,
          condition: alertForm.condition,
          threshold_value: Number(alertForm.threshold_value) || 0,
          severity: alertForm.severity,
        });
        addToast({ type: 'success', title: t('bi.alert_created', { defaultValue: 'Alert created' }) });
        qc.invalidateQueries({ queryKey: ['bi', 'alerts'] });
      }
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const titleByKind: Record<typeof kind, string> = {
    dashboards: t('bi.new_dashboard', { defaultValue: 'New dashboard' }),
    reports: t('bi.new_report', { defaultValue: 'New scheduled report' }),
    alerts: t('bi.new_alert', { defaultValue: 'New KPI alert rule' }),
  };
  const subtitleByKind: Record<typeof kind, string> = {
    dashboards: t('bi.new_dashboard_subtitle', {
      defaultValue:
        'Start with the basics - you can add KPI cards, charts and gauges after the dashboard is created.',
    }),
    reports: t('bi.new_report_subtitle', {
      defaultValue:
        'Define a report once, then schedule it for recurring delivery or run it on demand.',
    }),
    alerts: t('bi.new_alert_subtitle', {
      defaultValue:
        'Trigger a notification whenever a KPI crosses a threshold. Throttling is on by default.',
    }),
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={titleByKind[kind]}
      subtitle={subtitleByKind[kind]}
      size={kind === 'alerts' ? 'lg' : 'md'}
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {kind === 'dashboards' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('bi.name', { defaultValue: 'Name' })}
            required
            span={2}
          >
            <input
              value={dashForm.name}
              onChange={(e) => setDashForm({ ...dashForm, name: e.target.value })}
              className={inputCls}
              placeholder={t('bi.dashboard_name_placeholder', {
                defaultValue: 'PM weekly overview',
              })}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.description', { defaultValue: 'Description' })}
            hint={t('bi.description_hint', {
              defaultValue: 'Shown in the dashboard tile and the share link.',
            })}
            span={2}
          >
            <textarea
              value={dashForm.description}
              onChange={(e) => setDashForm({ ...dashForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2 resize-y')}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.scope', { defaultValue: 'Visibility scope' })}
            hint={t('bi.scope_hint', {
              defaultValue:
                'Personal = only you. Role = everyone in your role. Project = all members. Global = company-wide.',
            })}
            span={2}
          >
            <select
              value={dashForm.scope}
              onChange={(e) => setDashForm({ ...dashForm, scope: e.target.value as DashboardScope })}
              className={inputCls}
            >
              <option value="personal">{t('bi.scope_personal', { defaultValue: 'Personal - only me' })}</option>
              <option value="role">{t('bi.scope_role', { defaultValue: 'Role - my team' })}</option>
              <option value="project">{t('bi.scope_project', { defaultValue: 'Project - project members' })}</option>
              <option value="global">{t('bi.scope_global', { defaultValue: 'Global - entire company' })}</option>
            </select>
          </WideModalField>
          <WideModalField
            label={t('bi.cross_filter', { defaultValue: 'Cross-filter on click' })}
            hint={t('bi.cross_filter_hint', {
              defaultValue:
                'Power BI-style. When a tile defines a drill-path, clicking it scopes every other tile on the board to the clicked value.',
            })}
            span={2}
          >
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={dashForm.cross_filter_enabled}
                onChange={(e) =>
                  setDashForm({ ...dashForm, cross_filter_enabled: e.target.checked })
                }
                className="h-4 w-4 rounded border-border accent-oe-blue"
              />
              {t('bi.cross_filter_enable', {
                defaultValue: 'Enable click-to-filter for this dashboard',
              })}
            </label>
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'reports' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('bi.code', { defaultValue: 'Report code' })}
            required
            hint={t('bi.code_hint', {
              defaultValue: 'Short identifier used in URLs and webhooks. Lowercase + underscores.',
            })}
          >
            <input
              value={reportForm.code}
              onChange={(e) => setReportForm({ ...reportForm, code: e.target.value })}
              className={inputCls}
              placeholder="weekly_cost_summary"
            />
          </WideModalField>
          <WideModalField
            label={t('bi.name', { defaultValue: 'Display name' })}
            required
          >
            <input
              value={reportForm.name}
              onChange={(e) => setReportForm({ ...reportForm, name: e.target.value })}
              className={inputCls}
              placeholder={t('bi.report_name_placeholder', {
                defaultValue: 'Weekly cost summary',
              })}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.description', { defaultValue: 'Description' })}
            span={2}
          >
            <textarea
              value={reportForm.description}
              onChange={(e) => setReportForm({ ...reportForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2 resize-y')}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.format', { defaultValue: 'Output format' })}
            hint={t('bi.format_hint', {
              defaultValue: 'PDF for executives, XLSX for analysts, CSV/JSON for integrations.',
            })}
            span={2}
          >
            <select
              value={reportForm.output_format}
              onChange={(e) =>
                setReportForm({
                  ...reportForm,
                  output_format: e.target.value as 'pdf' | 'xlsx' | 'csv' | 'json',
                })
              }
              className={inputCls}
            >
              <option value="pdf">PDF</option>
              <option value="xlsx">Excel (XLSX)</option>
              <option value="csv">CSV</option>
              <option value="json">JSON</option>
            </select>
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'alerts' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('bi.name', { defaultValue: 'Rule name' })}
            required
            span={2}
          >
            <input
              value={alertForm.name}
              onChange={(e) => setAlertForm({ ...alertForm, name: e.target.value })}
              className={inputCls}
              placeholder={t('bi.alert_name_placeholder', {
                defaultValue: 'CPI dropped below 0.9',
              })}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.kpi', { defaultValue: 'KPI to monitor' })}
            required
            span={2}
          >
            {kpis.length > 0 ? (
              <select
                value={alertForm.kpi_code}
                onChange={(e) => setAlertForm({ ...alertForm, kpi_code: e.target.value })}
                className={inputCls}
              >
                {kpis.map((k) => (
                  <option key={k.id} value={k.code}>
                    {k.code} — {k.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={alertForm.kpi_code}
                onChange={(e) => setAlertForm({ ...alertForm, kpi_code: e.target.value })}
                className={inputCls}
                placeholder="cost_variance_pct"
              />
            )}
          </WideModalField>
          <WideModalField label={t('bi.condition', { defaultValue: 'Trigger when value is' })}>
            <select
              value={alertForm.condition}
              onChange={(e) =>
                setAlertForm({ ...alertForm, condition: e.target.value as AlertCondition })
              }
              className={inputCls}
            >
              <option value="above">{t('bi.cond_above', { defaultValue: 'Above threshold' })}</option>
              <option value="below">{t('bi.cond_below', { defaultValue: 'Below threshold' })}</option>
              <option value="equals">{t('bi.cond_equals', { defaultValue: 'Equal to threshold' })}</option>
              <option value="not_equals">{t('bi.cond_not_equals', { defaultValue: 'Not equal to threshold' })}</option>
              <option value="changed_by_more_than">{t('bi.cond_change', { defaultValue: 'Changed by more than' })}</option>
            </select>
          </WideModalField>
          <WideModalField label={t('bi.threshold', { defaultValue: 'Threshold value' })}>
            <input
              type="number"
              value={alertForm.threshold_value}
              onChange={(e) =>
                setAlertForm({ ...alertForm, threshold_value: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('bi.severity', { defaultValue: 'Severity' })}
            hint={t('bi.severity_hint_v2', {
              defaultValue:
                'Sets the priority of the in-app notification when the rule fires. Delivery channels and recipients are configured server-side.',
            })}
            span={2}
          >
            <select
              value={alertForm.severity}
              onChange={(e) =>
                setAlertForm({ ...alertForm, severity: e.target.value as AlertSeverity })
              }
              className={inputCls}
            >
              <option value="info">{t('bi.sev_info_v2', { defaultValue: 'Info - informational' })}</option>
              <option value="warning">{t('bi.sev_warning_v2', { defaultValue: 'Warning - needs attention' })}</option>
              <option value="critical">{t('bi.sev_critical_v2', { defaultValue: 'Critical - urgent' })}</option>
            </select>
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}


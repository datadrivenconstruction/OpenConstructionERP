// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Value Realized - one read surface that turns figures the platform already
// computes into a defensible "what has this bought us" view. The summary tab
// shows the headline value (overrun exposure now managed rather than discovered
// late, cost recovered and the recovery rate, admin hours given back, and a
// documented dispute-risk-reduction proxy), each carrying its own confidence so
// a low-evidence number is never dressed up as a firm one, plus a per-currency
// breakdown that never blends currencies. The adoption tab contrasts the firm's
// high- and low-adoption projects on its own data. A "value case" button prints
// the page for sharing. Money and rates arrive as strings and go straight to
// MoneyDisplay.

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Trophy,
  ShieldCheck,
  Clock,
  Wallet,
  TrendingUp,
  AlertTriangle,
  Inbox,
  Printer,
  Building2,
  Layers,
  Scale,
  ListChecks,
  CheckCircle2,
  Circle,
  MapPin,
  SlidersHorizontal,
} from 'lucide-react';
import {
  Card,
  Badge,
  EmptyState,
  SkeletonTable,
  DismissibleInfo,
  TabBar,
  tabIds,
  ModuleGuideButton,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  getValueSummary,
  getPortfolioSummary,
  getAdoptionBenchmark,
  getAdoptionChecklist,
  getRegionalBenchmark,
  recordValueReport,
} from './api';
import { TimeFactorsEditor } from './TimeFactorsEditor';
import { valueGuide } from './valueGuide';
import type { Confidence, ValueSummary } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

interface ProjectLite {
  id: string;
  name?: string;
}

type Scope = 'project' | 'portfolio';
type Tab = 'summary' | 'adoption' | 'checklist' | 'regional';

// The dimensionless ratio metrics the regional benchmark surfaces (cost-per-m2
// lives on the dedicated /benchmarks page). Lower overrun is better; higher
// recovery is better - the view states this rather than colouring it.
const REGIONAL_METRICS = ['overrun_pct', 'recovery_rate'] as const;

// The role lenses the adoption-checklist engine scopes its steps to. Labels are
// brand-neutral generic roles the operator maps onto its real titles.
const CHECKLIST_ROLES = ['manager', 'estimator', 'field', 'reviewer'] as const;
const ROLE_LABELS: Record<(typeof CHECKLIST_ROLES)[number], string> = {
  manager: 'Project lead',
  estimator: 'Estimator',
  field: 'Field',
  reviewer: 'Reviewer',
};

// --- Small shared helpers ---------------------------------------------------

const CONFIDENCE_VARIANT: Record<Confidence, BadgeVariant> = {
  high: 'success',
  medium: 'warning',
  low: 'warning',
  none: 'neutral',
};

const METRIC_LABEL: Record<string, string> = {
  recovery_rate: 'Recovery rate',
  overrun_pct: 'Overrun',
  avg_cycle_days: 'Change cycle time',
};

/** Best-effort title-case of an engine token like "avg_cycle_days". */
function humanize(token: string): string {
  return (token || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/** A rate string in [0,1] (e.g. "0.6900") rendered as a percent, or a dash. */
function ratePct(rate: string | null | undefined): string {
  if (rate == null || rate === '') return '-';
  const n = parseFloat(rate);
  if (Number.isNaN(n)) return '-';
  return `${Math.round(n * 100)}%`;
}

/** A float in [0,1] (or null) rendered as a percent string, or a dash. */
function floatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '-';
  return `${Math.round(value * 100)}%`;
}

/** Translated confidence label for one of high/medium/low/none. */
function useConfidenceLabel() {
  const { t } = useTranslation();
  return (level: Confidence): string => {
    if (level === 'none') {
      return t('value.confidence_none', { defaultValue: 'No data yet' });
    }
    return t(`confidence_badge.${level}`, {
      defaultValue:
        level === 'high' ? 'High confidence' : level === 'medium' ? 'Medium confidence' : 'Low confidence',
    });
  };
}

function ConfidenceTag({ level }: { level: Confidence }) {
  const label = useConfidenceLabel();
  return (
    <Badge variant={CONFIDENCE_VARIANT[level]} size="sm" dot>
      {label(level)}
    </Badge>
  );
}

/** A headline value tile with an optional sub-line and confidence badge. */
function ValueTile({
  label,
  icon,
  value,
  sub,
  confidence,
}: {
  label: string;
  icon: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  confidence?: Confidence;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
        <span className="text-content-secondary">{icon}</span>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-content-primary">{value}</div>
      {sub != null && <div className="mt-0.5 text-sm text-content-secondary">{sub}</div>}
      {confidence && (
        <div className="mt-2">
          <ConfidenceTag level={confidence} />
        </div>
      )}
    </Card>
  );
}

function PanelState({
  loading,
  error,
  empty,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  children,
}: {
  loading: boolean;
  error: unknown;
  empty: boolean;
  emptyIcon: React.ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  children: React.ReactNode;
}) {
  if (loading) return <SkeletonTable />;
  if (error) {
    return (
      <Card className="p-4">
        <div className="flex items-center gap-2 text-sm text-semantic-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{getErrorMessage(error)}</span>
        </div>
      </Card>
    );
  }
  if (empty) return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />;
  return <>{children}</>;
}

// --- Summary (headline value + per-currency breakdown) ----------------------

function SummaryView({ summary }: { summary: ValueSummary }) {
  const { t } = useTranslation();
  const primary = summary.by_currency.find((c) => c.currency === summary.primary_currency) ?? summary.by_currency[0];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ValueTile
          label={t('value.exposure_managed', { defaultValue: 'Exposure managed' })}
          icon={<TrendingUp className="h-4 w-4" />}
          value={
            <MoneyDisplay
              amount={primary?.overrun_exposure_managed ?? '0'}
              currency={summary.primary_currency}
              showCode
            />
          }
          sub={t('value.exposure_managed_sub', {
            defaultValue: '{{count}} approved change(s)',
            count: summary.impact_count,
          })}
          confidence={summary.exposure_confidence}
        />
        <ValueTile
          label={t('value.recovered', { defaultValue: 'Recovered' })}
          icon={<Wallet className="h-4 w-4" />}
          value={
            <MoneyDisplay amount={primary?.recovered_total ?? '0'} currency={summary.primary_currency} showCode />
          }
          sub={t('value.recovery_rate_sub', {
            defaultValue: 'Recovery rate {{rate}}',
            rate: ratePct(primary?.recovery_rate),
          })}
          confidence={summary.recovery_confidence}
        />
        <ValueTile
          label={t('value.hours_saved', { defaultValue: 'Admin hours saved' })}
          icon={<Clock className="h-4 w-4" />}
          value={summary.estimated_hours_saved}
          sub={t('value.hours_saved_sub', {
            defaultValue: 'Across {{count}} logged action(s)',
            count: summary.activity_count,
          })}
          confidence={summary.hours_confidence}
        />
        <ValueTile
          label={t('value.dispute_risk', { defaultValue: 'Dispute-risk reduction' })}
          icon={<ShieldCheck className="h-4 w-4" />}
          value={ratePct(summary.dispute_risk_reduction)}
          sub={t('value.dispute_risk_sub', { defaultValue: 'Traceability + recovery proxy' })}
          confidence={summary.risk_confidence}
        />
      </div>

      <PanelState
        loading={false}
        error={null}
        empty={summary.by_currency.length === 0}
        emptyIcon={<Layers className="h-6 w-6" />}
        emptyTitle={t('value.no_currency_title', { defaultValue: 'No value recorded yet' })}
        emptyDescription={t('value.no_currency_desc', {
          defaultValue:
            'Approve a change or record a back-charge to start building this project value case.',
        })}
      >
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">{t('value.col_currency', { defaultValue: 'Currency' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_exposure', { defaultValue: 'Exposure managed' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_chargeable', { defaultValue: 'Chargeable' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_recovered', { defaultValue: 'Recovered' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_rate', { defaultValue: 'Rate' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_days', { defaultValue: 'Schedule (d)' })}</th>
              </tr>
            </thead>
            <tbody>
              {summary.by_currency.map((row) => (
                <tr key={row.currency} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-content-primary">{row.currency || '-'}</td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={row.overrun_exposure_managed} currency={row.currency} showCode />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={row.chargeable_total} currency={row.currency} showCode />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={row.recovered_total} currency={row.currency} showCode />
                  </td>
                  <td className="px-3 py-2 text-right">{ratePct(row.recovery_rate)}</td>
                  <td className="px-3 py-2 text-right">{row.schedule_days_managed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        {summary.by_currency.length > 1 && (
          <p className="text-xs text-content-tertiary">
            {t('value.multi_currency_note', {
              defaultValue:
                'Figures are kept per currency and never blended; the headline uses {{currency}}.',
              currency: summary.primary_currency || t('value.primary_currency', { defaultValue: 'the primary currency' }),
            })}
          </p>
        )}
      </PanelState>
    </div>
  );
}

// --- Adoption benchmark (high vs low) ---------------------------------------

function AdoptionView() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['value', 'adoption-benchmark'],
    queryFn: () => getAdoptionBenchmark(),
    retry: false,
    staleTime: 60_000,
  });
  const benchmark = q.data;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <ValueTile
          label={t('value.adopters', { defaultValue: 'High-adoption projects' })}
          icon={<Trophy className="h-4 w-4" />}
          value={benchmark?.high_count ?? 0}
        />
        <ValueTile
          label={t('value.non_adopters', { defaultValue: 'Low-adoption projects' })}
          icon={<Building2 className="h-4 w-4" />}
          value={benchmark?.low_count ?? 0}
        />
        <ValueTile
          label={t('value.benchmark_confidence', { defaultValue: 'Benchmark confidence' })}
          icon={<Scale className="h-4 w-4" />}
          value={<ConfidenceTag level={benchmark?.confidence ?? 'none'} />}
        />
      </div>

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!benchmark || benchmark.comparisons.length === 0}
        emptyIcon={<Trophy className="h-6 w-6" />}
        emptyTitle={t('value.no_benchmark_title', { defaultValue: 'No benchmark yet' })}
        emptyDescription={t('value.no_benchmark_desc', {
          defaultValue: 'Run change work across a few projects to compare adopters with non-adopters.',
        })}
      >
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2">{t('value.col_metric', { defaultValue: 'Outcome metric' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_adopters', { defaultValue: 'Adopters' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_others', { defaultValue: 'Others' })}</th>
                <th className="px-3 py-2 text-center">{t('value.col_favours', { defaultValue: 'Favours' })}</th>
                <th className="px-3 py-2 text-right">{t('value.col_confidence', { defaultValue: 'Confidence' })}</th>
              </tr>
            </thead>
            <tbody>
              {benchmark?.comparisons.map((c) => {
                const isRate = c.metric === 'recovery_rate' || c.metric === 'overrun_pct';
                const fmt = (v: number | null) =>
                  v == null ? '-' : isRate ? floatPct(v) : `${fmtFixed(v, 1)}d`;
                return (
                  <tr key={c.metric} className="border-t border-border-light">
                    <td className="px-3 py-2 font-medium text-content-primary">
                      {METRIC_LABEL[c.metric] ?? humanize(c.metric)}
                    </td>
                    <td className="px-3 py-2 text-right">{fmt(c.high_mean)}</td>
                    <td className="px-3 py-2 text-right">{fmt(c.low_mean)}</td>
                    <td className="px-3 py-2 text-center">
                      {c.favours_high == null ? (
                        <span className="text-content-tertiary">-</span>
                      ) : c.favours_high ? (
                        <Badge variant="success" size="sm">
                          {t('value.favours_adopters', { defaultValue: 'Adopters' })}
                        </Badge>
                      ) : (
                        <Badge variant="neutral" size="sm">
                          {t('value.favours_others', { defaultValue: 'Others' })}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <ConfidenceTag level={c.confidence} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        <p className="text-xs text-content-tertiary">
          {t('value.benchmark_note', {
            defaultValue:
              'Adoption is scored from assisted-activity density and the share of changes with a traceable owner. A comparison is only as strong as its smaller cohort.',
          })}
        </p>
      </PanelState>
    </div>
  );
}

// --- Regional benchmarks (overrun / recovery by region, #21) ----------------

function RegionalBenchmarksView() {
  const { t } = useTranslation();
  const [metric, setMetric] = useState<(typeof REGIONAL_METRICS)[number]>('overrun_pct');
  const [region, setRegion] = useState('');
  const trimmedRegion = region.trim();
  const q = useQuery({
    queryKey: ['value', 'regional-benchmark', metric, trimmedRegion],
    queryFn: () => getRegionalBenchmark(metric, trimmedRegion || undefined),
    retry: false,
    staleTime: 60_000,
  });
  const port = q.data?.own_portfolio ?? null;
  const isOverrun = metric === 'overrun_pct';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-content-secondary">
          {t('value.benchmark_metric', { defaultValue: 'Metric' })}
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value as (typeof REGIONAL_METRICS)[number])}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
          >
            {REGIONAL_METRICS.map((m) => (
              <option key={m} value={m}>
                {m === 'overrun_pct'
                  ? t('value.metric_overrun_pct', { defaultValue: 'Cost overrun' })
                  : t('value.metric_recovery_rate', { defaultValue: 'Recovery rate' })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-content-secondary">
          {t('value.benchmark_region', { defaultValue: 'Region' })}
          <input
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder={t('value.benchmark_region_all', { defaultValue: 'All regions' })}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
          />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <ValueTile
          label={t('value.benchmark_projects', { defaultValue: 'Projects compared' })}
          icon={<Building2 className="h-4 w-4" />}
          value={port?.project_count ?? 0}
        />
        <ValueTile
          label={t('value.benchmark_median', { defaultValue: 'Portfolio median' })}
          icon={<Scale className="h-4 w-4" />}
          value={ratePct(port?.median)}
        />
        <ValueTile
          label={t('value.benchmark_confidence', { defaultValue: 'Benchmark confidence' })}
          icon={<MapPin className="h-4 w-4" />}
          value={<ConfidenceTag level={port?.confidence ?? 'none'} />}
        />
      </div>

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!port}
        emptyIcon={<MapPin className="h-6 w-6" />}
        emptyTitle={t('value.no_regional_title', { defaultValue: 'No regional benchmark yet' })}
        emptyDescription={t('value.no_regional_desc', {
          defaultValue:
            'Record approved budgets and back-charges across a few projects to benchmark overrun and recovery by region.',
        })}
      >
        {port && (
          <Card className="space-y-3 p-4">
            <div className="grid grid-cols-5 gap-2 text-center">
              {(
                [
                  ['value.bench_min', 'Min', port.min],
                  ['value.bench_p25', 'P25', port.p25],
                  ['value.bench_median', 'Median', port.median],
                  ['value.bench_p75', 'P75', port.p75],
                  ['value.bench_max', 'Max', port.max],
                ] as const
              ).map(([key, label, val]) => (
                <div key={key} className="rounded-md bg-surface-secondary px-2 py-2">
                  <div className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t(key, { defaultValue: label })}
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-content-primary">{ratePct(val)}</div>
                </div>
              ))}
            </div>
            <p className="text-xs text-content-tertiary">{port.note}</p>
          </Card>
        )}
        <p className="text-xs text-content-tertiary">
          {isOverrun
            ? t('value.benchmark_overrun_note', {
                defaultValue:
                  'Overrun compares the priced scope against the approved budget, project by project. Lower is better, and a negative figure means under budget. Benchmarked across your own projects, by region when set.',
              })
            : t('value.benchmark_recovery_note', {
                defaultValue:
                  'Recovery rate is the share of chargeable cost actually recovered, project by project. Higher is better. Benchmarked across your own projects, by region when set.',
              })}
        </p>
      </PanelState>
    </div>
  );
}

// --- Adoption checklist (guided first-value) --------------------------------

function ChecklistView({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [role, setRole] = useState<(typeof CHECKLIST_ROLES)[number]>('manager');
  const q = useQuery({
    queryKey: ['value', 'adoption-checklist', projectId, role],
    queryFn: () => getAdoptionChecklist(projectId, role),
    enabled: !!projectId,
    retry: false,
    staleTime: 60_000,
  });
  const checklist = q.data;
  const doneCount = checklist ? checklist.steps.filter((s) => s.done).length : 0;
  const nextKeys = new Set(checklist?.next_actions.map((a) => a.key) ?? []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid grid-cols-2 gap-3">
          <ValueTile
            label={t('value.adoption_score', { defaultValue: 'Adoption score' })}
            icon={<ListChecks className="h-4 w-4" />}
            value={`${checklist?.adoption_score ?? 0}%`}
          />
          <ValueTile
            label={t('value.steps_done', { defaultValue: 'Steps done' })}
            icon={<CheckCircle2 className="h-4 w-4" />}
            value={checklist ? `${doneCount}/${checklist.steps.length}` : '0/0'}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-content-secondary">
          {t('value.checklist_role', { defaultValue: 'Role' })}
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as (typeof CHECKLIST_ROLES)[number])}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
          >
            {CHECKLIST_ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`value.role_${r}`, { defaultValue: ROLE_LABELS[r] })}
              </option>
            ))}
          </select>
        </label>
      </div>

      <PanelState
        loading={q.isLoading}
        error={q.isError ? q.error : null}
        empty={!checklist || checklist.steps.length === 0}
        emptyIcon={<ListChecks className="h-6 w-6" />}
        emptyTitle={t('value.no_checklist_title', { defaultValue: 'No checklist for this role' })}
        emptyDescription={t('value.no_checklist_desc', {
          defaultValue: 'This role has no first-value steps on its path. Try another role.',
        })}
      >
        <Card className="overflow-hidden p-0">
          <ul className="divide-y divide-border-light">
            {checklist?.steps.map((step) => (
              <li key={step.key} className="flex items-center gap-3 px-4 py-3">
                {step.done ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-semantic-success" aria-hidden="true" />
                ) : (
                  <Circle className="h-5 w-5 shrink-0 text-content-tertiary" aria-hidden="true" />
                )}
                <span
                  className={
                    step.done
                      ? 'flex-1 text-sm text-content-tertiary line-through'
                      : 'flex-1 text-sm font-medium text-content-primary'
                  }
                >
                  {step.label}
                </span>
                {!step.done && nextKeys.has(step.key) && (
                  <Badge variant="blue" size="sm">
                    {t('value.do_next', { defaultValue: 'Do next' })}
                  </Badge>
                )}
                {step.done && (
                  <span className="text-xs font-medium text-semantic-success">
                    {t('value.step_done', { defaultValue: 'Done' })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
        <p className="text-xs text-content-tertiary">
          {t('value.checklist_note', {
            defaultValue:
              'Steps are marked done from what this project actually contains - a bill of quantities, a takeoff, a routed approval, a logged change, an AI run and its recorded verdict, an assembled evidence pack. The score is weighted by how much first-value each step carries and counts only the steps this role is asked to do.',
          })}
        </p>
      </PanelState>
    </div>
  );
}

// --- Page -------------------------------------------------------------------

export function ValueDashboardPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectLite[]>(),
    staleTime: 5 * 60_000,
  });
  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';

  const [scope, setScope] = useState<Scope>('project');
  const [tab, setTab] = useState<Tab>('summary');
  const [factorsOpen, setFactorsOpen] = useState(false);
  const ids = tabIds('value');

  // The hours-saved minute factors are admin-tunable; the editor is only offered
  // to admins (the backend also gates the GET/PUT with RequireRole("admin")).
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';

  // The summary query follows the active scope: a single project or the whole
  // portfolio. The portfolio summary needs no project id, so it is always
  // enabled; the project summary waits for a resolved project.
  const summaryQ = useQuery({
    queryKey: ['value', 'summary', scope, scope === 'project' ? projectId : 'portfolio'],
    queryFn: () => (scope === 'portfolio' ? getPortfolioSummary() : getValueSummary(projectId)),
    enabled: scope === 'portfolio' || !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const needsProject = scope === 'project' && !projectId;

  return (
    <div className="space-y-5 animate-fade-in print:space-y-3">
      <header className="flex flex-wrap items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <Trophy className="h-5 w-5" />
        </span>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-content-primary">
            {t('value.title', { defaultValue: 'Value Realized' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('value.subtitle', {
              defaultValue: 'What disciplined, assisted change management has bought - on your own data.',
            })}
          </p>
        </div>
        <ModuleGuideButton content={valueGuide} className="print:hidden" />
        {isAdmin ? (
          <button
            type="button"
            onClick={() => setFactorsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary print:hidden"
          >
            <SlidersHorizontal className="h-4 w-4" />
            {t('value.edit_factors', { defaultValue: 'Hours-saved factors' })}
          </button>
        ) : null}
        <button
          type="button"
          onClick={async () => {
            // Exporting the value case is the "generate a value report" action:
            // record it (project scope only) so the adoption checklist can flip
            // that step to done, then print. Recording is best-effort and never
            // blocks the print.
            if (scope === 'project' && projectId) {
              try {
                await recordValueReport(projectId);
                void queryClient.invalidateQueries({
                  queryKey: ['value', 'adoption-checklist', projectId],
                });
              } catch {
                /* best-effort: fall through to print */
              }
            }
            window.print();
          }}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary print:hidden"
        >
          <Printer className="h-4 w-4" />
          {t('value.print_case', { defaultValue: 'Value case' })}
        </button>
      </header>

      {isAdmin ? (
        <TimeFactorsEditor open={factorsOpen} onClose={() => setFactorsOpen(false)} />
      ) : null}

      <DismissibleInfo
        storageKey="value-realized"
        title={t('value.intro_title', { defaultValue: 'The value case, with its evidence' })}
      >
        {t('value.intro_body', {
          defaultValue:
            'This view composes figures the platform already computes: the budget movement approved changes now control rather than discovering late, the cost you recovered and your recovery rate, the admin hours assisted actions gave back, and a documented dispute-risk-reduction proxy. Every headline carries a confidence label, currencies are never blended, and the adoption tab contrasts your high- and low-adoption projects.',
        })}
      </DismissibleInfo>

      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <TabBar
          idPrefix="value-scope"
          ariaLabel={t('value.scope', { defaultValue: 'Scope' })}
          activeId={scope}
          onChange={(next) => setScope(next as Scope)}
          tabs={[
            { id: 'project', label: t('value.scope_project', { defaultValue: 'This project' }), icon: <Building2 className="h-4 w-4" /> },
            { id: 'portfolio', label: t('value.scope_portfolio', { defaultValue: 'Portfolio' }), icon: <Layers className="h-4 w-4" /> },
          ]}
        />
      </div>

      {needsProject ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('value.no_project', { defaultValue: 'No project selected' })}
          description={t('value.no_project_desc', {
            defaultValue: 'Select a project to see its value case, or switch to the portfolio view.',
          })}
        />
      ) : (
        <>
          <TabBar
            idPrefix="value"
            ariaLabel={t('value.title', { defaultValue: 'Value Realized' })}
            activeId={tab}
            onChange={(next) => setTab(next as Tab)}
            tabs={[
              { id: 'summary', label: t('value.tab_summary', { defaultValue: 'Value summary' }), icon: <Trophy className="h-4 w-4" /> },
              { id: 'checklist', label: t('value.tab_checklist', { defaultValue: 'Getting started' }), icon: <ListChecks className="h-4 w-4" /> },
              { id: 'adoption', label: t('value.tab_adoption', { defaultValue: 'Adoption benchmark' }), icon: <Scale className="h-4 w-4" /> },
              { id: 'regional', label: t('value.tab_regional', { defaultValue: 'Regional benchmarks' }), icon: <MapPin className="h-4 w-4" /> },
            ]}
          />
          <div role="tabpanel" id={ids.panelId(tab)} aria-labelledby={ids.tabId(tab)}>
            {tab === 'summary' && (
              <PanelState
                loading={summaryQ.isLoading}
                error={summaryQ.isError ? summaryQ.error : null}
                empty={!summaryQ.data}
                emptyIcon={<Trophy className="h-6 w-6" />}
                emptyTitle={t('value.no_summary_title', { defaultValue: 'No value yet' })}
                emptyDescription={t('value.no_summary_desc', {
                  defaultValue: 'Nothing has been recorded to value yet for this scope.',
                })}
              >
                {summaryQ.data && <SummaryView summary={summaryQ.data} />}
              </PanelState>
            )}
            {tab === 'checklist' && <ChecklistView projectId={projectId} />}
            {tab === 'adoption' && <AdoptionView />}
            {tab === 'regional' && <RegionalBenchmarksView />}
          </div>
        </>
      )}
    </div>
  );
}

export default ValueDashboardPage;

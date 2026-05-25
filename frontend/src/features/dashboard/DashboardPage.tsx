import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { uploadDocument, fetchDocuments, type DocumentItem } from '@/features/documents/api';
import {
  FolderPlus,
  ArrowRight,
  Layers,
  Globe,
  Zap,
  ShieldCheck,
  BarChart3,
  Database,
  Sparkles,
  Cpu,
  FileSpreadsheet,
  CheckCircle2,
  Download,
  X,
  Building2,
  Loader2,
  DollarSign,
  FileText,
  Calendar,
  Upload,
  ExternalLink,
  AlertTriangle,
  TrendingUp,
  Users,
  Lightbulb,
  CircleDashed,
  Activity,
  LayoutGrid,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, Skeleton, ActivityFeed as CrossModuleActivityFeed, EmptyState, ModuleHelpButton } from '@/shared/ui';
import { WhatsNewCard } from '@/shared/ui/WhatsNewCard';
import BIMCoverageCard from './BIMCoverageCard';
import { CompactProjectCard } from './components/CompactProjectCard';
import { DashboardProjectsMap } from './components/DashboardProjectsMap';
import { ShowAllProjectsCard } from './components/ShowAllProjectsCard';
import { WeatherSiteWidget } from './components/NewWidgets';
import { OperationsSnapshotCard } from './components/OperationsSnapshotCard';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { DashboardLayoutManager } from './DashboardLayoutManager';
import { DASHBOARD_WIDGET_IDS } from './widgetRegistry';
import {
  useDashboardLayoutStore,
  reconcileOrder,
  hydrateDashboardLayoutFromServer,
} from '@/stores/useDashboardLayoutStore';
import {
  DashboardRollupProvider,
  useDashboardRollupContext,
} from './context/DashboardRollupContext';

/* ── Types ────────────────────────────────────────────────────────────── */

interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  region: string;
  classification_standard: string;
  currency: string;
  locale?: string;
  created_at: string;
  // Optional location fields — only present on /v1/projects/ payload
  // when the project has been geocoded. The map widget needs them.
  address?: {
    street?: string | null;
    city?: string | null;
    country?: string | null;
    lat?: number | null;
    lng?: number | null;
  } | null;
}

interface ProjectCardMetrics {
  id: string;
  name: string;
  description: string;
  region: string;
  currency: string;
  classification_standard: string;
  status: string;
  phase: string | null;
  created_at: string | null;
  updated_at: string | null;
  boq_total_value: number;
  boq_count: number;
  position_count: number;
  open_tasks: number;
  open_rfis: number;
  safety_incidents: number;
  progress_pct: number;
}

interface BOQWithTotal {
  id: string;
  project_id: string;
  name: string;
  status: string;
  grand_total: number;
  positions: { total: number }[];
}

interface RegionStat {
  region: string;
  count: number;
}

interface OnboardingStep {
  id: number;
  icon: React.ReactNode;
  titleKey: string;
  titleDefault: string;
  descKey: string;
  descDefault: string;
  buttonKey: string;
  buttonDefault: string;
  done: boolean;
  disabled: boolean;
  onClick: () => void;
}

interface SystemStatusData {
  api: { status: string; version: string };
  database: { status: string; engine?: string; error?: string };
  vector_db: { status: string; engine: string; collections?: number; vectors?: number };
  ai: { providers: { name: string; configured: boolean }[]; configured: boolean };
}

interface DemoCatalogEntry {
  demo_id: string;
  name: string;
  description: string;
  country: string;
  currency: string;
  budget: string;
  type: string;
  sections: number;
  positions: number;
}

interface DemoInstallResult {
  project_id: string;
  project_name: string;
  demo_id: string;
  sections: number;
  positions: number;
  markups: number;
  grand_total: number;
  currency: string;
  schedule_months: number;
}

const COUNTRY_FLAGS: Record<string, string> = {
  DE: '\uD83C\uDDE9\uD83C\uDDEA',
  GB: '\uD83C\uDDEC\uD83C\uDDE7',
  AE: '\uD83C\uDDE6\uD83C\uDDEA',
  FR: '\uD83C\uDDEB\uD83C\uDDF7',
};

const DEMO_TYPE_COLORS: Record<string, string> = {
  Residential: '#2563eb',
  Commercial: '#7c3aed',
  Healthcare: '#dc2626',
  Industrial: '#ca8a04',
  Education: '#16a34a',
};

/* ── Import Demo Modal ─────────────────────────────────────────────────── */

function ImportDemoModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [installingId, setInstallingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const { data: catalog } = useQuery({
    queryKey: ['demo-catalog'],
    queryFn: () => apiGet<DemoCatalogEntry[]>('/demo/catalog'),
    enabled: open,
    retry: false,
  });

  const installMutation = useMutation({
    mutationFn: (demoId: string) =>
      apiPost<DemoInstallResult>(`/demo/install/${demoId}`),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      onClose();
      navigate(`/projects/${result.project_id}`);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('demo.install_failed', { defaultValue: 'Failed to install demo' }), message: err.message });
    },
    onSettled: () => {
      setInstallingId(null);
    },
  });

  const handleInstall = useCallback(
    (demoId: string) => {
      setInstallingId(demoId);
      installMutation.mutate(demoId);
    },
    [installMutation],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg"
        aria-hidden="true"
        onClick={onClose}
      />

      {/* Modal */}
      <div role="dialog" aria-modal="true" aria-labelledby="demo-modal-title" className="relative z-10 w-full max-w-2xl mx-4 rounded-xl bg-surface-primary shadow-2xl border border-border-light animate-card-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle">
              <Download size={16} className="text-oe-blue" strokeWidth={2} />
            </div>
            <div>
              <h3 id="demo-modal-title" className="text-base font-semibold text-content-primary">
                {t('demo.modal_title', 'Import Demo Project')}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('demo.modal_subtitle', 'Install a complete project with BOQ, schedule, budget, and tendering')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Demo cards */}
        <div className="p-6 space-y-3 max-h-[60vh] overflow-y-auto">
          {!catalog ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} height={80} className="w-full" rounded="lg" />
              ))}
            </div>
          ) : (
            catalog.map((demo) => {
              const isInstalling = installingId === demo.demo_id;
              const typeColor = DEMO_TYPE_COLORS[demo.type] || '#6b7280';
              return (
                <div
                  key={demo.demo_id}
                  className="flex items-center gap-4 rounded-lg border border-border-light p-4 transition-all hover:border-oe-blue/30 hover:bg-surface-secondary/50"
                >
                  {/* Icon + flag */}
                  <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                    <Building2
                      size={20}
                      strokeWidth={1.5}
                      style={{ color: typeColor }}
                    />
                    <span className="absolute -bottom-1 -right-1 text-sm leading-none">
                      {COUNTRY_FLAGS[demo.country] || ''}
                    </span>
                  </div>

                  {/* Info */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-content-primary truncate">
                        {demo.name}
                      </span>
                      <Badge variant="blue" size="sm">
                        {demo.budget}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-content-tertiary line-clamp-1">
                      {demo.description}
                    </p>
                    <div className="mt-1 flex items-center gap-3 text-2xs text-content-quaternary">
                      <span>{demo.type}</span>
                      <span>{demo.sections} {t('demo.sections', { defaultValue: 'sections' })}</span>
                      <span>{demo.positions} {t('demo.positions', { defaultValue: 'positions' })}</span>
                      <span>{demo.currency}</span>
                    </div>
                  </div>

                  {/* Install button */}
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={installingId !== null}
                    onClick={() => handleInstall(demo.demo_id)}
                    icon={
                      isInstalling ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Download size={13} />
                      )
                    }
                  >
                    {isInstalling
                      ? t('demo.installing', 'Installing...')
                      : t('demo.install', 'Install')}
                  </Button>
                </div>
              );
            })
          )}

          {installMutation.isError && (
            <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
              {t('demo.install_error', 'Failed to install demo project. Please try again.')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Onboarding Steps ──────────────────────────────────────────────────── */

function OnboardingSteps({
  projects,
  regionStats,
  boqs,
  vectorCount,
}: {
  projects?: ProjectSummary[];
  regionStats?: RegionStat[];
  boqs?: BOQWithTotal[];
  vectorCount?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [demoModalOpen, setDemoModalOpen] = useState(false);

  const hasDatabase = Boolean(regionStats && regionStats.length > 0);
  const hasProjects = Boolean(projects && projects.length > 0);
  const hasBoqs = Boolean(boqs && boqs.length > 0);
  const hasVectors = Boolean(vectorCount && vectorCount > 0);
  const hasQuantities = Boolean(
    boqs && boqs.some((b) => b.positions && b.positions.some((p) => p.total > 0)),
  );

  const aiConfigured = (() => {
    try {
      return Boolean(localStorage.getItem('oe_ai_provider'));
    } catch {
      return false;
    }
  })();

  const completedCount = [
    hasDatabase,
    hasVectors,
    aiConfigured,
    hasProjects,
    hasBoqs,
    hasQuantities,
  ].filter(Boolean).length;

  const TOTAL_STEPS = 6;

  const steps: OnboardingStep[] = [
    {
      id: 1,
      icon: <Database size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_load_db',
      titleDefault: 'Load Cost Database',
      descKey: 'dashboard.step_load_db_desc',
      descDefault: 'Import regional pricing data with 55,000+ items',
      buttonKey: 'dashboard.import_database',
      buttonDefault: 'Import Database',
      done: hasDatabase,
      disabled: false,
      onClick: () => navigate('/costs/import'),
    },
    {
      id: 2,
      icon: <Sparkles size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_ai_search',
      titleDefault: 'Enable AI Search',
      descKey: 'dashboard.step_ai_search_desc',
      descDefault: 'Generate vector embeddings for semantic cost matching',
      buttonKey: 'dashboard.configure',
      buttonDefault: 'Configure',
      done: hasVectors,
      disabled: !hasDatabase,
      onClick: () => navigate('/costs/import'),
    },
    {
      id: 3,
      icon: <Cpu size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_connect_ai',
      titleDefault: 'Connect AI',
      descKey: 'dashboard.step_connect_ai_desc',
      descDefault: 'Add your API keys for AI-powered estimation',
      buttonKey: 'dashboard.add_api_keys',
      buttonDefault: 'Add API Keys',
      done: aiConfigured,
      disabled: false,
      onClick: () => navigate('/settings'),
    },
    {
      id: 4,
      icon: <FolderPlus size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_create_project',
      titleDefault: 'Create Project',
      descKey: 'dashboard.step_create_project_desc',
      descDefault: 'Start your first construction estimation project',
      buttonKey: 'dashboard.new_project',
      buttonDefault: 'New Project',
      done: hasProjects,
      disabled: false,
      onClick: () => navigate('/projects/new'),
    },
    {
      id: 5,
      icon: <FileSpreadsheet size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_build_boq',
      titleDefault: 'Build Your BOQ',
      descKey: 'dashboard.step_build_boq_desc',
      descDefault: 'Create a Bill of Quantities with AI assistance',
      buttonKey: 'dashboard.create_boq',
      buttonDefault: 'Create BOQ',
      done: hasBoqs,
      disabled: !hasProjects,
      onClick: () => navigate(hasProjects ? '/projects' : '/projects/new'),
    },
    {
      id: 6,
      icon: <BarChart3 size={22} strokeWidth={1.5} />,
      titleKey: 'dashboard.step_set_quantities',
      titleDefault: 'Set Quantities',
      descKey: 'dashboard.step_set_quantities_desc',
      descDefault: 'Add quantities and unit rates to your BOQ positions',
      buttonKey: 'dashboard.open_boq',
      buttonDefault: 'Open BOQ',
      done: hasQuantities,
      disabled: !hasBoqs,
      onClick: () => {
        if (boqs && boqs.length > 0) {
          navigate(`/boq/${boqs[0]!.id}`);
        } else {
          navigate('/projects');
        }
      },
    },
  ];

  return (
    <div>
      {/* Section header */}
      <div
        className="mb-5 flex items-center justify-between animate-card-in"
        style={{ animationDelay: '80ms' }}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue-subtle">
            <Zap size={14} className="text-oe-blue" strokeWidth={2} />
          </div>
          <h2 className="text-lg font-semibold text-content-primary">
            {t('dashboard.getting_started', { defaultValue: 'Getting Started' })}
          </h2>
          <Badge variant="blue" size="sm">
            {completedCount}/{TOTAL_STEPS}
          </Badge>
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="mb-5 animate-card-in"
        style={{ animationDelay: '100ms' }}
      >
        <div className="h-1.5 w-full rounded-full bg-surface-secondary overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-slow ease-oe"
            style={{
              width: `${(completedCount / TOTAL_STEPS) * 100}%`,
              background: 'linear-gradient(90deg, var(--oe-blue), #5856d6)',
            }}
          />
        </div>
      </div>

      {/* Step cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {steps.map((step, index) => (
          <div
            key={step.id}
            className="animate-card-in"
            style={{ animationDelay: `${120 + index * 60}ms` }}
          >
            <Card
              padding="none"
              hoverable={!step.disabled}
              className={`relative overflow-hidden h-full flex flex-col ${step.done ? 'opacity-75' : ''} ${step.disabled ? 'opacity-50' : ''}`}
            >
              {/* Completed overlay checkmark */}
              {step.done && (
                <div className="absolute top-3 right-3 z-10">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-semantic-success">
                    <CheckCircle2 size={14} className="text-content-inverse" strokeWidth={2.5} />
                  </div>
                </div>
              )}

              <div className="flex flex-1 flex-col p-5">
                {/* Step number + icon row */}
                <div className="mb-4 flex items-center gap-3">
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      step.done
                        ? 'bg-semantic-success-bg text-semantic-success'
                        : 'bg-oe-blue-subtle text-oe-blue'
                    }`}
                  >
                    {step.id}
                  </div>
                  <div
                    className={`${step.done ? 'text-semantic-success' : 'text-content-tertiary'}`}
                  >
                    {step.icon}
                  </div>
                </div>

                {/* Title */}
                <h4 className="text-sm font-semibold text-content-primary leading-snug">
                  {t(step.titleKey, { defaultValue: step.titleDefault })}
                </h4>

                {/* Description */}
                <p className="mt-1.5 flex-1 text-xs leading-relaxed text-content-tertiary">
                  {t(step.descKey, { defaultValue: step.descDefault })}
                </p>

                {/* CTA button(s) */}
                <div className="mt-4">
                  {step.id === 4 && !step.done ? (
                    <div className="flex gap-1.5">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={step.onClick}
                        className="flex-[3]"
                        icon={<ArrowRight size={13} strokeWidth={2} />}
                        iconPosition="right"
                      >
                        {t(step.buttonKey, { defaultValue: step.buttonDefault })}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDemoModalOpen(true)}
                        className="flex-1 !px-2"
                        title={t('demo.import_demo', 'Import Demo')}
                        icon={<Download size={13} strokeWidth={2} />}
                      >
                        {t('dashboard.demo', { defaultValue: 'Demo' })}
                      </Button>
                    </div>
                  ) : (
                    <Button
                      variant={step.done ? 'ghost' : 'secondary'}
                      size="sm"
                      disabled={step.disabled}
                      onClick={step.onClick}
                      className="w-full"
                      icon={
                        step.done ? (
                          <CheckCircle2 size={13} strokeWidth={2} />
                        ) : (
                          <ArrowRight size={13} strokeWidth={2} />
                        )
                      }
                      iconPosition="right"
                    >
                      {step.done
                        ? t('dashboard.completed', { defaultValue: 'Completed' })
                        : t(step.buttonKey, { defaultValue: step.buttonDefault })}
                    </Button>
                  )}
                </div>
              </div>

              {/* Bottom accent line */}
              <div
                className="h-0.5 w-full"
                style={{
                  background: step.done
                    ? 'var(--oe-success)'
                    : step.disabled
                      ? 'var(--oe-border-light)'
                      : 'linear-gradient(90deg, var(--oe-blue), #5856d6)',
                  opacity: step.done ? 1 : step.disabled ? 0.3 : 0.6,
                }}
              />
            </Card>
          </div>
        ))}
      </div>

      {/* Demo import modal */}
      <ImportDemoModal open={demoModalOpen} onClose={() => setDemoModalOpen(false)} />
    </div>
  );
}

/* ── KPI Ribbon ────────────────────────────────────────────────────────── */

interface ScheduleSummary {
  id: string;
  project_id: string;
  name: string;
  status: string;
}

function KpiRibbon({
  boqs,
  schedules,
  projects,
}: {
  boqs?: BOQWithTotal[];
  schedules?: ScheduleSummary[];
  projects?: ProjectSummary[];
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const totalValue = useMemo(() => {
    if (!boqs || boqs.length === 0) return 0;
    // Backend serialises money as a Decimal-string ("1234.56") per the
    // project-wide contract. Coerce every leg before summing so a stray
    // string doesn't trigger JS string concatenation ("01234.565678") +
    // a downstream `.toFixed is not a function` crash in formatMoney.
    return boqs.reduce((sum, b) => {
      const n = Number(b.grand_total);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
  }, [boqs]);

  const activeEstimates = useMemo(() => {
    if (!boqs) return 0;
    // "Active" = anything not archived/closed/cancelled. Previously this
    // counted only `draft` and silently dropped tendered/in-review BOQs,
    // which made the tile misleading for late-stage projects.
    const INACTIVE = new Set(['archived', 'closed', 'cancelled', 'rejected']);
    return boqs.filter((b) => !INACTIVE.has((b.status ?? '').toLowerCase())).length;
  }, [boqs]);

  const scheduleCount = schedules?.length ?? 0;

  const qualityScore = useMemo(() => {
    if (!boqs || boqs.length === 0) return null;
    // Compute average validation "completeness" from positions that have totals > 0
    const withPositions = boqs.filter((b) => b.positions && b.positions.length > 0);
    if (withPositions.length === 0) return null;
    const totalPositions = withPositions.reduce((s, b) => s + b.positions.length, 0);
    const positionsWithPrice = withPositions.reduce(
      (s, b) => s + b.positions.filter((p) => p.total > 0).length,
      0,
    );
    if (totalPositions === 0) return null;
    return Math.round((positionsWithPrice / totalPositions) * 100);
  }, [boqs]);

  const currency = projects?.[0]?.currency ?? 'EUR';

  // Compact currency formatter using Intl.NumberFormat \u2014 handles every ISO
  // 4217 code natively (BRL, INR, JPY, etc.). For values \u2265 1M we use the
  // built-in compact notation; below that, two decimals. Previously this
  // had an ad-hoc switch covering only EUR/GBP/USD/AED.
  const formatMoney = (raw: number | string | null | undefined) => {
    // Harden against backend Decimal-strings sneaking past TypeScript: any
    // string that can't be parsed degrades to 0 rather than crashing.
    const value = typeof raw === 'number' ? raw : Number(raw ?? 0);
    if (!Number.isFinite(value)) return `0 ${currency}`;
    try {
      const compact = value >= 1_000;
      return new Intl.NumberFormat(getIntlLocale(), {
        style: 'currency',
        currency,
        notation: compact ? 'compact' : 'standard',
        maximumFractionDigits: compact ? 1 : 2,
      }).format(value);
    } catch {
      // Unknown currency code \u2014 fall back to raw number with code suffix.
      return `${value.toFixed(2)} ${currency}`;
    }
  };

  const cards = [
    {
      icon: <DollarSign size={20} strokeWidth={1.75} />,
      value: boqs ? formatMoney(totalValue) : null,
      label: t('dashboard.kpi_total_value', { defaultValue: 'Total Value' }),
      color: 'text-oe-blue',
      bg: 'bg-oe-blue-subtle',
    },
    {
      icon: <FileText size={20} strokeWidth={1.75} />,
      value: boqs ? `${activeEstimates}` : null,
      sublabel: boqs
        ? t('dashboard.kpi_estimates_unit', {
            defaultValue: 'estimate{{s}}',
            s: activeEstimates === 1 ? '' : 's',
          }).replace('{{s}}', activeEstimates === 1 ? '' : 's')
        : '',
      label: t('dashboard.kpi_active_estimates', { defaultValue: 'Active Estimates' }),
      color: 'text-violet-600 dark:text-violet-400',
      bg: 'bg-violet-500/10',
    },
    {
      icon: <Calendar size={20} strokeWidth={1.75} />,
      value: schedules ? `${scheduleCount}` : null,
      sublabel: schedules
        ? scheduleCount > 0
          ? t('dashboard.kpi_schedule_active', { defaultValue: 'active' })
          : t('dashboard.kpi_no_schedules', { defaultValue: 'No schedules' })
        : '',
      label: t('dashboard.kpi_schedule', { defaultValue: 'Schedule Status' }),
      color: 'text-cyan-600 dark:text-cyan-400',
      bg: 'bg-cyan-500/10',
    },
    {
      icon: <ShieldCheck size={20} strokeWidth={1.75} />,
      // When no validation report exists yet we swap the "N/A" string for a
      // dashed-circle icon — reads as "not measured" and doesn't compete
      // with the percentage on validated tiles. The sublabel keeps the CTA.
      value: qualityScore !== null
        ? `${qualityScore}%`
        : (<CircleDashed size={18} strokeWidth={1.75} className="text-content-quaternary opacity-70" />),
      sublabel: qualityScore !== null
        ? t('dashboard.kpi_priced_label', { defaultValue: 'priced' })
        : t('dashboard.kpi_run_validation', { defaultValue: 'run validation' }),
      // Renamed 2026-05-11 from "Quality Score" → "Priced positions".
      // Previously the label implied DIN/NRM validation but the math was
      // just `positions_with_unit_rate / total_positions`. The renamed tile
      // is accurate to what it measures.
      label: t('dashboard.kpi_priced_positions', { defaultValue: 'Priced positions' }),
      color: qualityScore !== null && qualityScore >= 80 ? 'text-semantic-success' : qualityScore !== null && qualityScore >= 50 ? 'text-[#b45309]' : 'text-content-tertiary',
      bg: qualityScore !== null && qualityScore >= 80 ? 'bg-semantic-success-bg' : qualityScore !== null && qualityScore >= 50 ? 'bg-semantic-warning-bg' : 'bg-surface-secondary',
      onClick: qualityScore === null ? () => navigate('/validation') : undefined,
    },
  ];

  return (
    <div
      className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4 animate-card-in"
      style={{ animationDelay: '50ms' }}
      data-testid="dashboard-tour-kpi-ribbon"
    >
      {cards.map((card, i) => {
        const clickable = 'onClick' in card && typeof card.onClick === 'function';
        const TileTag = clickable ? 'button' : 'div';
        return (
          <TileTag
            key={card.label}
            type={clickable ? 'button' : undefined}
            onClick={clickable ? card.onClick : undefined}
            className={`group flex w-full items-center gap-3 rounded-xl border border-border-light bg-surface-primary p-4 text-left transition-all duration-normal ease-oe hover:border-oe-blue/20 hover:shadow-sm animate-stagger-in ${
              clickable ? 'cursor-pointer focus:outline-none focus:ring-2 focus:ring-oe-blue/30' : ''
            }`}
            style={{ animationDelay: `${80 + i * 50}ms` }}
          >
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${card.bg} ${card.color} transition-transform duration-normal ease-oe group-hover:scale-105`}>
              {card.icon}
            </div>
            <div className="min-w-0">
              <div className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold tabular-nums text-content-primary leading-tight truncate">
                  {card.value ?? <span className="inline-block h-5 w-14 animate-pulse rounded bg-surface-tertiary" />}
                </span>
                {'sublabel' in card && card.sublabel && (
                  <span className="text-xs text-content-tertiary">{card.sublabel}</span>
                )}
              </div>
              <div className="text-xs text-content-tertiary mt-0.5 truncate">{card.label}</div>
            </div>
          </TileTag>
        );
      })}
    </div>
  );
}

/* ── Portfolio Overview ────────────────────────────────────────────────── */

interface AnalyticsOverview {
  total_projects: number;
  projects_with_budget: number;
  total_planned: number;
  total_actual: number;
  total_variance: number;
  over_budget_count: number;
  projects: {
    id: string;
    name: string;
    budget: number;
    actual: number;
    variance: number;
    variance_pct: number;
    status: string;
  }[];
}

function PortfolioOverview({ projects: _projects }: { projects: ProjectSummary[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: analytics } = useQuery({
    queryKey: ['portfolio-analytics', _projects.length],
    queryFn: () => apiGet<AnalyticsOverview>('/v1/projects/analytics/overview/'),
    retry: false,
    staleTime: 60_000,
  });

  if (!analytics) return null;

  const hasWarnings = analytics.over_budget_count > 0;
  const totalPlannedNum = Number(analytics.total_planned ?? 0);
  const totalBudgetFormatted = totalPlannedNum >= 1_000_000
    ? `${(totalPlannedNum / 1_000_000).toFixed(1)}M`
    : totalPlannedNum >= 1_000
      ? `${(totalPlannedNum / 1_000).toFixed(0)}K`
      : totalPlannedNum.toLocaleString();

  const overBudgetProjects = (analytics.projects || []).filter(
    (p) => p.status === 'over_budget',
  );

  return (
    <div
      className="rounded-xl border border-border-light bg-surface-primary p-4 animate-card-in"
      style={{ animationDelay: '70ms' }}
    >
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp size={16} className="text-content-tertiary" strokeWidth={1.75} />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('dashboard.portfolio_overview', { defaultValue: 'Portfolio Overview' })}
        </h3>
        {hasWarnings && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-2xs font-medium text-amber-700">
            <AlertTriangle size={10} />
            {analytics.over_budget_count} {t('dashboard.over_budget', { defaultValue: 'over budget' })}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg bg-surface-secondary p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('dashboard.active_projects', { defaultValue: 'Active Projects' })}
          </div>
          <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
            {analytics.total_projects}
          </div>
        </div>
        <div className="rounded-lg bg-surface-secondary p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('dashboard.total_budget_all', { defaultValue: 'Total Budget' })}
          </div>
          <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
            {totalBudgetFormatted}
          </div>
        </div>
        <div className="rounded-lg bg-surface-secondary p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('dashboard.with_budget', { defaultValue: 'With Budget' })}
          </div>
          <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
            {analytics.projects_with_budget}
          </div>
        </div>
        <div className={`rounded-lg p-3 ${hasWarnings ? 'bg-amber-50 dark:bg-amber-900/10' : 'bg-surface-secondary'}`}>
          <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('dashboard.budget_warnings', { defaultValue: 'Budget Warnings' })}
          </div>
          <div className={`mt-1 text-xl font-bold tabular-nums ${hasWarnings ? 'text-amber-600' : 'text-content-primary'}`}>
            {analytics.over_budget_count}
          </div>
        </div>
      </div>
      {overBudgetProjects.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border-light">
          <p className="text-2xs font-medium text-amber-600 uppercase tracking-wider mb-2">
            {t('dashboard.projects_over_budget', { defaultValue: 'Projects Over Budget' })}
          </p>
          <div className="space-y-1.5">
            {overBudgetProjects.slice(0, 3).map((p) => (
              <button
                key={p.id}
                onClick={() => navigate(`/projects/${p.id}`)}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs hover:bg-surface-secondary transition-colors text-left"
              >
                <span className="text-content-primary font-medium truncate">{p.name}</span>
                <span className="text-amber-600 tabular-nums shrink-0 ml-2">
                  {p.variance_pct > 0 ? '+' : ''}{p.variance_pct}%
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Today widget — action items, scoped to the active project ────────
   Source data is `/v1/projects/dashboard/cards/` (per-project aggregates).
   The destination pages (/tasks, /rfi, /safety) are project-scoped via
   `useProjectContextStore.activeProjectId`. To prevent the dashboard
   widget from showing a portfolio total that doesn't match the next
   page, we scope this widget the same way:
     · activeProjectId set → that project's counts, /tasks etc. land
       on the same data.
     · not set            → portfolio aggregate as a read-only summary;
       clicks route to /projects so the user can pick a project first. */

function TodaySnapshot({ cards }: { cards?: ProjectCardMetrics[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  // Scope to the active project's row if there is one; otherwise sum.
  const activeCard = activeProjectId
    ? cards?.find((c) => c.id === activeProjectId)
    : undefined;

  const totals = useMemo(() => {
    if (activeCard) {
      return {
        tasks:     activeCard.open_tasks ?? 0,
        rfis:      activeCard.open_rfis ?? 0,
        incidents: activeCard.safety_incidents ?? 0,
        projects:  1,
      };
    }
    if (!cards || cards.length === 0) {
      return { tasks: 0, rfis: 0, incidents: 0, projects: 0 };
    }
    return cards.reduce(
      (acc, c) => ({
        tasks:     acc.tasks     + (c.open_tasks ?? 0),
        rfis:      acc.rfis      + (c.open_rfis ?? 0),
        incidents: acc.incidents + (c.safety_incidents ?? 0),
        projects:  acc.projects  + 1,
      }),
      { tasks: 0, rfis: 0, incidents: 0, projects: 0 },
    );
  }, [activeCard, cards]);

  const everythingClear = totals.tasks === 0 && totals.rfis === 0 && totals.incidents === 0;
  if (everythingClear || !cards || cards.length === 0) return null;

  type ItemTone = 'urgent' | 'attention' | 'info';
  const tone = (count: number, urgentAt: number, attentionAt: number): ItemTone =>
    count >= urgentAt ? 'urgent' : count >= attentionAt ? 'attention' : 'info';

  // When we're in portfolio mode, clicking a tile sends the user to the
  // project list so they can pick one — the destination pages need a
  // project context to render anything meaningful.
  const tileUrl = (singleProjectUrl: string) =>
    activeCard ? singleProjectUrl : '/projects';

  const items: Array<{
    id: string;
    value: number;
    label: string;
    sublabel: string;
    icon: React.ReactNode;
    tone: ItemTone;
    url: string;
  }> = [
    {
      id: 'tasks',
      value: totals.tasks,
      label: t('dashboard.today_tasks', { defaultValue: 'Open tasks' }),
      sublabel: t('dashboard.today_tasks_sub', { defaultValue: 'awaiting your attention' }),
      icon: <CheckCircle2 size={18} strokeWidth={1.75} />,
      tone: tone(totals.tasks, 10, 3),
      url: tileUrl('/tasks'),
    },
    {
      id: 'rfis',
      value: totals.rfis,
      label: t('dashboard.today_rfis', { defaultValue: 'Open RFIs' }),
      sublabel: t('dashboard.today_rfis_sub', { defaultValue: 'awaiting response' }),
      icon: <FileText size={18} strokeWidth={1.75} />,
      tone: tone(totals.rfis, 5, 1),
      url: tileUrl('/rfi'),
    },
    {
      id: 'incidents',
      value: totals.incidents,
      label: t('dashboard.today_incidents', { defaultValue: 'Safety incidents' }),
      sublabel: t('dashboard.today_incidents_sub', { defaultValue: 'open this week' }),
      icon: <AlertTriangle size={18} strokeWidth={1.75} />,
      tone: tone(totals.incidents, 1, 1),
      url: tileUrl('/safety'),
    },
  ];

  const toneStyles: Record<ItemTone, { dot: string; value: string; iconColor: string }> = {
    urgent: {
      dot:       'bg-semantic-error',
      value:     'text-semantic-error',
      iconColor: 'text-semantic-error',
    },
    attention: {
      dot:       'bg-semantic-warning',
      value:     'text-[#b45309] dark:text-amber-400',
      iconColor: 'text-[#b45309] dark:text-amber-400',
    },
    info: {
      dot:       'bg-content-quaternary',
      value:     'text-content-secondary',
      iconColor: 'text-content-tertiary',
    },
  };

  return (
    <div
      className="rounded-xl border border-border-light bg-surface-primary p-4 animate-card-in"
      style={{ animationDelay: '80ms' }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Activity size={14} className="text-oe-blue" strokeWidth={2} />
        <h3 className="text-sm font-semibold text-content-primary">
          {activeCard
            ? t('dashboard.today_title_single', { defaultValue: 'Today · {{project}}', project: activeProjectName || activeCard.name })
            : t('dashboard.today_title', { defaultValue: 'Today across your portfolio' })}
        </h3>
        <span className="text-2xs text-content-tertiary tabular-nums">
          {activeCard
            ? t('dashboard.today_meta_single', { defaultValue: 'this project' })
            : t('dashboard.today_meta', { defaultValue: '{{count}} projects · pick one to drill in', count: totals.projects })}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {items.map((it) => {
          const s = toneStyles[it.tone];
          const hasItems = it.value > 0;
          return (
            <button
              key={it.id}
              onClick={() => navigate(it.url)}
              className="group flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3 text-left transition-all duration-normal ease-oe hover:border-oe-blue/30 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            >
              <span className={`${s.iconColor} shrink-0`}>{it.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className={`text-xl font-bold tabular-nums ${hasItems ? s.value : 'text-content-tertiary'}`}>
                    {it.value}
                  </span>
                  <span className="text-xs text-content-tertiary truncate">{it.label}</span>
                </div>
                <div className="text-2xs text-content-tertiary mt-0.5 truncate">{it.sublabel}</div>
              </div>
              {hasItems && (
                <span className={`relative flex h-1.5 w-1.5 shrink-0 ${s.dot} rounded-full`}>
                  {it.tone === 'urgent' && (
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-semantic-error opacity-60" />
                  )}
                </span>
              )}
              <ArrowRight size={14} className="shrink-0 text-content-quaternary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── Next Steps (context-aware suggestions) ───────────────────────────── */

interface NextStepSuggestion {
  id: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  actionLabel: string;
  url: string;
}

function NextSteps({
  projects,
  boqs,
  schedules,
  allContacts,
}: {
  projects?: ProjectSummary[];
  boqs?: BOQWithTotal[];
  schedules?: ScheduleSummary[];
  allContacts?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const suggestions = useMemo(() => {
    const items: NextStepSuggestion[] = [];

    const hasProjects = Boolean(projects && projects.length > 0);
    const hasBoqs = Boolean(boqs && boqs.length > 0);
    const hasPositions = Boolean(
      boqs && boqs.some((b) => b.positions && b.positions.length > 0),
    );
    const hasRates = Boolean(
      boqs && boqs.some((b) => b.positions && b.positions.some((p) => p.total > 0)),
    );
    const hasSchedules = Boolean(schedules && schedules.length > 0);
    const hasContacts = Boolean(allContacts && allContacts > 0);

    // If no BOQ -- suggest creating one
    if (hasProjects && !hasBoqs) {
      items.push({
        id: 'create-boq',
        icon: <FileSpreadsheet size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_create_boq', { defaultValue: 'Create your first Bill of Quantities' }),
        description: t('dashboard.next_create_boq_desc', { defaultValue: 'A BOQ is the foundation of your estimate. Add sections and positions to start building your cost breakdown.' }),
        actionLabel: t('dashboard.next_create_boq_action', { defaultValue: 'Create BOQ' }),
        url: `/projects/${projects![0]!.id}`,
      });
    }

    // If BOQ has no positions -- suggest adding them
    if (hasBoqs && !hasPositions) {
      const firstBoq = boqs!.find((b) => !b.positions || b.positions.length === 0) ?? boqs![0];
      items.push({
        id: 'add-positions',
        icon: <FileText size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_add_positions', { defaultValue: 'Add positions to your estimate' }),
        description: t('dashboard.next_add_positions_desc', { defaultValue: 'Your BOQ is empty. Add trade sections and work item positions with quantities and unit descriptions.' }),
        actionLabel: t('dashboard.next_add_positions_action', { defaultValue: 'Open BOQ Editor' }),
        url: `/boq/${firstBoq!.id}`,
      });
    }

    // If positions have no rates -- suggest importing cost database
    if (hasPositions && !hasRates) {
      items.push({
        id: 'import-costs',
        icon: <Database size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_import_costs', { defaultValue: 'Import cost database to auto-fill rates' }),
        description: t('dashboard.next_import_costs_desc', { defaultValue: 'Load regional pricing data with 55,000+ items to automatically match unit rates to your BOQ positions.' }),
        actionLabel: t('dashboard.next_import_costs_action', { defaultValue: 'Import Database' }),
        url: '/costs/import',
      });
    }

    // If BOQ has rates but not validated -- suggest validation
    if (hasRates) {
      items.push({
        id: 'run-validation',
        icon: <ShieldCheck size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_validate', { defaultValue: 'Run validation to check quality' }),
        description: t('dashboard.next_validate_desc', { defaultValue: 'Check your estimate for missing quantities, zero prices, duplicates, and compliance with industry standards.' }),
        actionLabel: t('dashboard.next_validate_action', { defaultValue: 'Run Validation' }),
        url: '/validation',
      });
    }

    // If no schedule -- suggest creating one
    if (hasProjects && !hasSchedules) {
      items.push({
        id: 'create-schedule',
        icon: <Calendar size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_create_schedule', { defaultValue: 'Create a project schedule' }),
        description: t('dashboard.next_create_schedule_desc', { defaultValue: 'Plan your project timeline with activities, dependencies, and milestones. The Gantt chart updates automatically.' }),
        actionLabel: t('dashboard.next_create_schedule_action', { defaultValue: 'Go to Schedule' }),
        url: '/schedule',
      });
    }

    // If no contacts -- suggest adding them
    if (!hasContacts) {
      items.push({
        id: 'add-contacts',
        icon: <Users size={18} strokeWidth={1.75} />,
        title: t('dashboard.next_add_contacts', { defaultValue: 'Add your team contacts' }),
        description: t('dashboard.next_add_contacts_desc', { defaultValue: 'Store clients, subcontractors, and suppliers in your contacts directory. Import from CSV or add manually.' }),
        actionLabel: t('dashboard.next_add_contacts_action', { defaultValue: 'Add Contacts' }),
        url: '/contacts',
      });
    }

    // Evergreen filler — always-on suggestions added at the END so they
    // only surface when the conditional state-aware ones leave space.
    // Guarantees the 3-card grid stays visually complete regardless of
    // the user's setup. (Added 2026-05-11.)
    items.push({
      id: 'try-ai-estimate',
      icon: <Sparkles size={18} strokeWidth={1.75} />,
      title: t('dashboard.next_ai_estimate', { defaultValue: 'Try the AI Quick Estimate' }),
      description: t('dashboard.next_ai_estimate_desc', { defaultValue: 'Describe a project in plain language and get a draft BOQ in seconds — review, adjust, and ship.' }),
      actionLabel: t('dashboard.next_ai_estimate_action', { defaultValue: 'Open AI Estimate' }),
      url: '/ai-estimate',
    });

    items.push({
      id: 'upload-cad',
      icon: <Layers size={18} strokeWidth={1.75} />,
      title: t('dashboard.next_upload_cad', { defaultValue: 'Upload a CAD or BIM model' }),
      description: t('dashboard.next_upload_cad_desc', { defaultValue: 'Drop a RVT, IFC, DWG or DGN file — the converter extracts quantities and matches elements to cost positions.' }),
      actionLabel: t('dashboard.next_upload_cad_action', { defaultValue: 'Open BIM' }),
      url: '/bim',
    });

    items.push({
      id: 'explore-costs',
      icon: <Database size={18} strokeWidth={1.75} />,
      title: t('dashboard.next_explore_costs', { defaultValue: 'Explore the cost database' }),
      description: t('dashboard.next_explore_costs_desc', { defaultValue: 'Browse 55,000+ regional unit rates with semantic search across CWICR / RSMeans / GAEB sources.' }),
      actionLabel: t('dashboard.next_explore_costs_action', { defaultValue: 'Open Costs' }),
      url: '/costs',
    });

    return items.slice(0, 3);
  }, [projects, boqs, schedules, allContacts, t]);

  if (suggestions.length === 0) return null;

  return (
    <div
      className="animate-card-in"
      style={{ animationDelay: '90ms' }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb size={16} className="text-amber-500" strokeWidth={1.75} />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('dashboard.next_steps', { defaultValue: 'Suggested Next Steps' })}
        </h3>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {suggestions.map((s, i) => (
          <button
            key={s.id}
            onClick={() => navigate(s.url)}
            className="group flex flex-col items-start gap-2 rounded-xl border border-border-light bg-surface-primary p-4 text-left transition-all duration-normal ease-oe hover:border-oe-blue/30 hover:bg-oe-blue-subtle/20 hover:shadow-sm animate-stagger-in"
            style={{ animationDelay: `${100 + i * 60}ms` }}
          >
            {/* Plain Stroke per 2026-05-11 design-system: icon-only, no chip.
                Amber accent comes from the icon color, not a fill block. */}
            <div className="text-amber-600 transition-transform group-hover:scale-110">
              {s.icon}
            </div>
            <div>
              <h4 className="text-sm font-semibold text-content-primary leading-snug">
                {s.title}
              </h4>
              <p className="mt-1 text-xs leading-relaxed text-content-tertiary line-clamp-2">
                {s.description}
              </p>
            </div>
            <span className="mt-auto flex items-center gap-1 text-xs font-medium text-oe-blue">
              {s.actionLabel}
              <ArrowRight size={12} strokeWidth={2} />
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Project Metric Cards ─────────────────────────────────────────────── */

function ProjectMetricCards({
  cards,
  loading,
}: {
  cards?: ProjectCardMetrics[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div className="animate-card-in" style={{ animationDelay: '130ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-content-tertiary" strokeWidth={1.75} />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboard.project_cards_title', { defaultValue: 'Projects' })}
            </h3>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={160} className="w-full" rounded="lg" />
          ))}
        </div>
      </div>
    );
  }

  if (!cards || cards.length === 0) return null;

  return (
    <div
      className="animate-card-in"
      style={{ animationDelay: '130ms' }}
      data-testid="dashboard-tour-projects-list"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Layers size={16} className="text-content-tertiary" strokeWidth={1.75} />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboard.project_cards_title', { defaultValue: 'Projects' })}
          </h3>
          <Badge variant="blue" size="sm">{cards.length}</Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowRight size={14} />}
          iconPosition="right"
          onClick={() => navigate('/projects')}
        >
          {t('dashboard.view_all', { defaultValue: 'View All' })}
        </Button>
      </div>

      {/* No partial rows: cap visible cards so (visible + 1 CTA) is a
          full multiple of 4 (the widest breakpoint). Examples:
          5 projects → show 3 + CTA = 4 (1 row), 2 hidden behind CTA
          7 projects → show 7 + CTA = 8 (2 rows), 0 hidden
          8 projects → show 7 + CTA = 8, 1 hidden
          11+ projects → show 11 + CTA = 12 (3 rows), rest hidden.
          For ≤2 projects we keep the partial last row (capping to 0
          would just show the CTA alone). Grid drops the lg=3 step so
          the tile math always works. */}
      {(() => {
        const visibleCount =
          cards.length <= 2
            ? cards.length
            : Math.max(0, Math.floor((cards.length + 1) / 4) * 4 - 1);
        const visible = cards.slice(0, visibleCount);
        const hidden = Math.max(0, cards.length - visibleCount);
        return (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {visible.map((card, index) => (
              <CompactProjectCard
                key={card.id}
                id={card.id}
                name={card.name}
                description={card.description}
                region={card.region}
                currency={card.currency}
                classificationStandard={card.classification_standard}
                status={card.status}
                boqCount={card.boq_count}
                boqTotalValue={card.boq_total_value}
                updatedAt={card.updated_at}
                createdAt={card.created_at}
                style={{ animationDelay: `${150 + index * 50}ms` }}
              />
            ))}
            <ShowAllProjectsCard
              totalCount={cards.length}
              hiddenCount={hidden}
              style={{ animationDelay: `${150 + visible.length * 50}ms` }}
            />
          </div>
        );
      })()}
    </div>
  );
}

/* ── System Status Summary (compact badges) ──────────────────────────── */

/* ── System Status Summary (compact badges) ──────────────────────────── */

function SystemStatusSummary({
  projects,
  boqs,
}: {
  projects?: ProjectSummary[];
  boqs?: BOQWithTotal[];
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => apiGet<{ modules: unknown[] }>('/system/modules').catch(() => ({ modules: [] })),
    retry: false,
    staleTime: 60_000,
  });

  // `/v1/users/` requires the `users.list` permission which viewers don't
  // have (v2.0.0 BUG-327/386 security hardening). Skip the fetch for them
  // so the team-count badge doesn't log a red 403 in the browser console.
  const userRole = useAuthStore((s) => s.userRole);
  const canListUsers = userRole === 'admin' || userRole === 'editor';
  const { data: usersList } = useQuery({
    queryKey: ['dashboard-users-count'],
    queryFn: () => apiGet<{ id: string }[]>('/v1/users/').catch(() => []),
    retry: false,
    staleTime: 60_000,
    enabled: canListUsers,
  });

  const moduleCount = modules?.modules?.length ?? 0;
  const projectCount = projects?.length ?? 0;
  const boqCount = boqs?.length ?? 0;
  const userCount = usersList?.length ?? 0;

  const badges = [
    {
      icon: <Layers size={12} strokeWidth={2} />,
      value: projectCount,
      label: t('dashboard.ss_projects', { defaultValue: 'Projects' }),
      color: 'text-oe-blue',
      bg: 'bg-oe-blue-subtle',
      to: '/projects',
    },
    {
      icon: <FileSpreadsheet size={12} strokeWidth={2} />,
      value: boqCount,
      label: t('dashboard.ss_boqs', { defaultValue: 'BOQs' }),
      color: 'text-[#7c3aed]',
      bg: 'bg-[#7c3aed]/10',
      to: '/boq',
    },
    {
      icon: <Cpu size={12} strokeWidth={2} />,
      value: moduleCount,
      label: t('dashboard.ss_modules', { defaultValue: 'Modules' }),
      color: 'text-[#0891b2]',
      bg: 'bg-[#0891b2]/10',
      to: '/modules',
    },
    {
      icon: <Users size={12} strokeWidth={2} />,
      value: userCount,
      label: t('dashboard.ss_users', { defaultValue: 'Users' }),
      color: 'text-[#16a34a]',
      bg: 'bg-[#16a34a]/10',
      to: '/users',
    },
  ];

  return (
    <div
      className="flex flex-wrap items-center gap-2 animate-card-in"
      style={{ animationDelay: '40ms' }}
    >
      {badges.map((b) => (
        <button
          key={b.label}
          type="button"
          onClick={() => navigate(b.to)}
          className={`inline-flex items-center gap-1.5 rounded-lg ${b.bg} px-2.5 py-1.5 transition-colors hover:brightness-95 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 cursor-pointer`}
          aria-label={`${b.value} ${b.label}`}
        >
          <span className={b.color}>{b.icon}</span>
          <span className={`text-xs font-bold tabular-nums ${b.color}`}>{b.value}</span>
          <span className="text-2xs text-content-tertiary">{b.label}</span>
        </button>
      ))}
    </div>
  );
}

/* ── Quick Upload Card ────────────────────────────────────────────────── */

function QuickUploadCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);

  const { data: documents } = useQuery({
    queryKey: ['documents', activeProjectId],
    queryFn: () => fetchDocuments(activeProjectId ?? ''),
    enabled: !!activeProjectId,
    staleTime: 30_000,
  });

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!activeProjectId) {
        addToast({
          type: 'warning',
          title: t('dashboard.upload_no_project', {
            defaultValue: 'Select a project first',
          }),
          message: t('dashboard.upload_no_project_desc', {
            defaultValue: 'Choose an active project to upload files.',
          }),
        });
        return;
      }
      const fileArray = Array.from(files);
      if (fileArray.length === 0) return;

      const validFiles = fileArray;
      if (validFiles.length === 0) return;

      setUploading(true);
      let successCount = 0;
      let failCount = 0;

      for (const file of validFiles) {
        try {
          await uploadDocument(activeProjectId, file, 'other');
          successCount += 1;
        } catch (err) {
          failCount += 1;
          addToast({
            type: 'error',
            title: t('dashboard.upload_failed', { defaultValue: 'Upload failed' }),
            message: err instanceof Error ? err.message : file.name,
          });
        }
      }

      setUploading(false);
      await queryClient.invalidateQueries({ queryKey: ['documents', activeProjectId] });
      await queryClient.invalidateQueries({ queryKey: ['documents'] });

      if (successCount > 0) {
        addToast({
          type: 'success',
          title: t('dashboard.upload_success', {
            defaultValue: '{{count}} file(s) uploaded',
            count: successCount,
          }),
          message: failCount > 0
            ? t('dashboard.upload_partial', {
                defaultValue: '{{failed}} failed',
                failed: failCount,
              })
            : undefined,
        });
      }
    },
    [activeProjectId, addToast, queryClient, t],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        void handleFiles(e.dataTransfer.files);
      }
    },
    [handleFiles],
  );

  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const documentCount = (documents as DocumentItem[] | undefined)?.length ?? 0;
  const hasProject = !!activeProjectId;

  return (
    <div className="animate-card-in" style={{ animationDelay: '120ms' }}>
      <Card padding="none">
        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          className={[
            'relative flex items-center gap-4 rounded-xl border-2 border-dashed px-5 py-5 transition-all',
            dragOver
              ? 'border-oe-blue bg-oe-blue-subtle/40'
              : 'border-border-light bg-surface-secondary/30 hover:border-oe-blue/40',
            !hasProject ? 'opacity-60' : '',
          ].join(' ')}
          style={{ minHeight: 160 }}
          role="region"
          aria-label={t('dashboard.upload_zone', { defaultValue: 'File upload area' })}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                void handleFiles(e.target.files);
                e.target.value = '';
              }
            }}
          />
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
            {uploading ? (
              <Loader2 size={22} className="animate-spin" />
            ) : (
              <Upload size={22} strokeWidth={1.75} />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-content-primary">
              {t('dashboard.upload_title', {
                defaultValue: 'Drop files here',
              })}
            </div>
            <p className="mt-0.5 text-xs text-content-tertiary line-clamp-1">
              {hasProject
                ? t('dashboard.upload_desc', {
                    defaultValue: 'Upload to {{project}} — PDF, DWG, IFC, RVT, images.',
                    project: activeProjectName || t('dashboard.active_project', { defaultValue: 'active project' }),
                  })
                : t('dashboard.upload_select_project', {
                    defaultValue: 'Select an active project to upload files.',
                  })}
            </p>
            <div className="mt-2 flex items-center gap-3 text-2xs text-content-tertiary">
              <button
                type="button"
                className="inline-flex items-center gap-1 text-oe-blue hover:text-oe-blue-dark transition-colors"
                onClick={() => navigate('/documents')}
                disabled={!hasProject}
              >
                <FileText size={11} />
                <span>
                  {t('dashboard.upload_count_link', {
                    defaultValue: '{{count}} documents · open in Documents →',
                    count: documentCount,
                  })}
                </span>
              </button>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              icon={<Upload size={13} />}
              disabled={!hasProject || uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              {t('dashboard.upload_browse', { defaultValue: 'Upload Files' })}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function DashboardPage() {
  // Mount the rollup provider ONCE so every wave-2 widget — and the inner
  // page's KPI ribbon / lastBoq / Analytics — reads from the same single
  // ``GET /api/v1/dashboard/rollup/`` instead of fanning out per-project.
  // The previous build fired 7×``/v1/boq/boqs/`` + 7×``/v1/schedule/
  // schedules/`` at 7 projects (≈100 at 50). v4.6.2 N+1 nuke 2026-05-24:
  // ≤ 2 dashboard requests on a render now.
  return (
    <DashboardRollupProvider>
      <DashboardPageInner />
    </DashboardRollupProvider>
  );
}

function DashboardPageInner() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [showAllActivity, setShowAllActivity] = useState(false);
  const [customizing, setCustomizing] = useState(false);

  // Single rollup-context read — every widget on this page shares this one
  // fetch via the provider mounted above. Replaces the per-project fan-out
  // for BOQs + schedules below.
  const rollup = useDashboardRollupContext();
  const boqSummary = rollup.byWidget('boq_summary');
  const scheduleCritical = rollup.byWidget('schedule_critical');

  const widgetOrder = useDashboardLayoutStore((s) => s.order);
  const widgetHidden = useDashboardLayoutStore((s) => s.hidden);
  const resolvedWidgets = useMemo(
    () => reconcileOrder(widgetOrder, DASHBOARD_WIDGET_IDS),
    [widgetOrder],
  );

  // Pull the server-side layout once at mount so a user who customised on
  // another browser sees the same dashboard here. Idempotent: only the
  // first call actually fires.
  useEffect(() => {
    void hydrateDashboardLayoutFromServer();
  }, []);

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/').catch(() => []),
    retry: false,
    staleTime: 5 * 60_000,
  });

  // First launch: redirect to onboarding wizard ONLY when the workspace
  // is genuinely empty.  When the server already has projects (demo seed,
  // or any tenant with real data), short-circuit by writing the completed
  // flag so the wizard doesn't ambush returning users on a new browser.
  // Skip is also honoured when the user pressed the `g d` chord.
  useEffect(() => {
    try {
      const skip = sessionStorage.getItem('oe_skip_onboarding_redirect') === '1';
      if (skip) {
        sessionStorage.removeItem('oe_skip_onboarding_redirect');
        return;
      }
      if (localStorage.getItem('oe_onboarding_completed') === 'true') return;
      if (projects === undefined) return; // wait for fetch
      if (projects.length > 0) {
        localStorage.setItem('oe_onboarding_completed', 'true');
        return;
      }
      navigate('/onboarding', { replace: true });
    } catch { /* storage unavailable */ }
  }, [navigate, projects]);

  // Fetch lightweight per-project summary metrics for dashboard cards (single endpoint)
  const { data: projectCards, isLoading: cardsLoading } = useQuery({
    queryKey: ['dashboard-project-cards'],
    queryFn: () => apiGet<ProjectCardMetrics[]>('/v1/projects/dashboard/cards/').catch(() => []),
    retry: false,
    staleTime: 30_000,
  });

  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/').catch(() => []),
    retry: false,
  });

  // Fetch system status for vector DB count (used in onboarding steps)
  const { data: systemStatus } = useQuery({
    queryKey: ['system-status'],
    queryFn: () => fetch('/api/system/status').then((r) => r.json()) as Promise<SystemStatusData>,
    retry: false,
    staleTime: 30_000,
  });

  const vectorCount = systemStatus?.vector_db?.vectors ?? 0;

  // ── allBoqs / allSchedules — derived from the rollup payload, NOT a
  // per-project fan-out (v4.6.2 N+1 nuke 2026-05-24). The wave-2 widgets
  // consume their slices directly via context; KPI ribbon + Analytics +
  // OnboardingSteps still expect ``BOQWithTotal[]`` / ``ScheduleSummary[]``
  // shapes, so we synthesize lite stubs from ``boq_summary.by_project`` +
  // ``boq_summary.last_boq`` + ``schedule_critical.total_schedules`` that
  // carry only the fields those consumers actually read. Anything beyond
  // counts / aggregates was never used here — full position arrays + per-
  // schedule rows live in the dedicated pages (``/boq`` / ``/schedule``).
  const allBoqs = useMemo<BOQWithTotal[] | undefined>(() => {
    if (!boqSummary) return undefined;
    const stubs: BOQWithTotal[] = boqSummary.by_project.map((row) => ({
      id: `summary-${row.project_id}`,
      project_id: row.project_id,
      name: row.project_name,
      // KpiRibbon counts non-archived BOQs — without per-row status we mark
      // the synthesized stub as ``active`` so it lands in the bucket. The
      // accurate count for the tile comes from ``boqSummary.active_boqs``
      // below; this stub only matters for legacy length-based checks.
      status: 'active',
      // Per-project total in project currency, as Number — KpiRibbon and
      // AnalyticsSection sum these.
      grand_total: Number(row.total_value) || 0,
      // Synthetic position list — one entry per ``position_count`` would
      // bloat memory, so we mark a single representative position carrying
      // the rolled-up total. OnboardingSteps + SystemStatusSummary only
      // check ``positions.length > 0`` + ``positions.some(p => p.total > 0)``.
      positions:
        row.position_count > 0
          ? [{ total: row.position_count - row.positions_zero_price > 0 ? 1 : 0 }]
          : [],
    }));
    // If the user has at least one real BOQ but no per-project rollup row
    // covered it (defensive — should be impossible), insert a single fall-
    // back so OnboardingSteps "Build your BOQ" step still ticks.
    if (stubs.length === 0 && boqSummary.total_boqs > 0) {
      stubs.push({
        id: 'summary-fallback',
        project_id: '',
        name: '',
        status: 'active',
        grand_total: Number(boqSummary.total_value_eur) || 0,
        positions: boqSummary.position_count > 0 ? [{ total: 1 }] : [],
      });
    }
    return stubs;
  }, [boqSummary]);

  const allSchedules = useMemo<ScheduleSummary[] | undefined>(() => {
    if (!scheduleCritical) return undefined;
    const n = scheduleCritical.total_schedules ?? 0;
    return Array.from({ length: n }, (_unused, i) => ({
      id: `summary-sched-${i}`,
      project_id: '',
      name: '',
      status: 'active',
    }));
  }, [scheduleCritical]);

  // Fetch contacts count for NextSteps suggestions
  const { data: contactsList } = useQuery({
    queryKey: ['dashboard-contacts-count'],
    queryFn: () => apiGet<{ id: string }[]>('/v1/contacts/').catch(() => []),
    retry: false,
    staleTime: 60_000,
  });
  const contactsCount = contactsList?.length ?? 0;

  // Most-recently updated BOQ for "Continue your work" — sourced from the
  // rollup's pre-computed ``boq_summary.last_boq`` so we don't need to
  // fan out a ``/v1/boq/boqs/?project_id=…`` per project just to sort by
  // ``updated_at`` client-side.
  const lastBoq = useMemo(() => {
    const lb = boqSummary?.last_boq;
    if (!lb) return null;
    return {
      id: lb.id,
      name: lb.name,
      status: lb.status ?? '',
      projectName: lb.project_name,
      positionCount: lb.position_count,
      grandTotal: Number(lb.grand_total) || 0,
      currency: lb.currency,
      updatedAt: lb.updated_at,
    };
  }, [boqSummary]);

  // ── Widget node map — keyed by registry id. The dashboard renders these
  //    in the user's saved order (`resolvedWidgets`), skipping hidden ones.
  //    Conditional widgets resolve to `null` (and contribute nothing) just
  //    as they did when they were inline. */
  const widgetNodes: Record<string, ReactNode> = {
    continue_work: lastBoq ? (
      <button
        type="button"
        onClick={() => navigate(`/boq/${lastBoq.id}`)}
        className="group flex w-full items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3 text-left transition-all duration-normal ease-oe hover:border-oe-blue/40 hover:bg-oe-blue-subtle/20 hover:shadow-sm animate-card-in focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        style={{ animationDelay: '60ms' }}
        title={t('dashboard.continue_work', { defaultValue: 'Continue your work' })}
      >
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-oe-blue/40 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-oe-blue" />
        </span>
        <span className="text-2xs uppercase tracking-wider font-semibold text-oe-blue shrink-0">
          {t('dashboard.continue_work', { defaultValue: 'Resume' })}
        </span>
        <span className="text-sm font-semibold text-content-primary truncate min-w-0">
          {lastBoq.name}
        </span>
        {lastBoq.projectName && (
          <>
            <span aria-hidden className="text-content-quaternary shrink-0">·</span>
            <span className="text-xs text-content-tertiary truncate min-w-0 hidden sm:inline">
              {lastBoq.projectName}
            </span>
          </>
        )}
        <span className="ml-auto flex items-center gap-3 shrink-0">
          {lastBoq.positionCount > 0 && (
            <span className="text-xs text-content-secondary tabular-nums hidden md:inline">
              <strong className="text-content-primary">{lastBoq.positionCount}</strong>{' '}
              {t('boq.positions', { defaultValue: 'positions' })}
            </span>
          )}
          {lastBoq.grandTotal > 0 && (
            <span className="text-xs font-semibold text-content-primary tabular-nums">
              {lastBoq.currency} {lastBoq.grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          )}
          <ArrowRight size={16} className="text-content-tertiary group-hover:text-oe-blue group-hover:translate-x-0.5 transition-all" />
        </span>
      </button>
    ) : null,

    today: <TodaySnapshot cards={projectCards} />,

    kpi: <KpiRibbon boqs={allBoqs} schedules={allSchedules} projects={projects} />,

    projects: (
      <>
        <ProjectMetricCards cards={projectCards} loading={cardsLoading} />
        {(!projectCards || projectCards.length === 0) && (
          <div className="animate-card-in" style={{ animationDelay: '150ms' }}>
            <Card padding="none">
              <div className="p-6 pb-0">
                <CardHeader
                  title={t('dashboard.recent_projects')}
                  action={
                    <Button variant="ghost" size="sm" icon={<ArrowRight size={14} />} iconPosition="right" onClick={() => navigate('/projects')}>
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
        )}
      </>
    ),

    portfolio:
      projects && projects.length > 1 ? (
        <PortfolioOverview projects={projects} />
      ) : null,

    map:
      projects && projects.length > 0 ? (
        <div className="animate-card-in" style={{ animationDelay: '220ms' }}>
          <DashboardProjectsMap
            projects={projects.slice(0, 30).map((p) => ({
              id: p.id,
              name: p.name,
              region: p.region,
              lat: p.address?.lat ?? null,
              lng: p.address?.lng ?? null,
              address: p.address?.street ?? null,
              city: p.address?.city ?? null,
              country: p.address?.country ?? null,
            }))}
          />
        </div>
      ) : null,

    bim_coverage: <BIMCoverageCard />,

    quick_upload: <QuickUploadCard />,

    onboarding: (
      <OnboardingSteps projects={projects} regionStats={regionStats} boqs={allBoqs} vectorCount={vectorCount} />
    ),

    next_steps: (
      <NextSteps
        projects={projects}
        boqs={allBoqs}
        schedules={allSchedules}
        allContacts={contactsCount}
      />
    ),

    analytics:
      projects && projects.length > 0 ? (
        <div className="animate-card-in" style={{ animationDelay: '180ms' }}>
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 size={18} className="text-content-tertiary" strokeWidth={1.75} />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('dashboard.analytics', { defaultValue: 'Analytics' })}
            </h2>
          </div>
          <AnalyticsSection projects={projects} />
        </div>
      ) : null,

    activity: (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {projects && projects.length > 0 && (
          <div className="lg:col-span-2 animate-card-in" style={{ animationDelay: '200ms' }}>
            <Card className="h-full">
              <CardHeader
                title={t('dashboard.activity', { defaultValue: 'Recent Activity' })}
                action={
                  <Button variant="ghost" size="sm" icon={<ArrowRight size={14} />} iconPosition="right" onClick={() => setShowAllActivity((prev) => !prev)}>
                    {showAllActivity ? t('common.show_less', { defaultValue: 'Show less' }) : t('common.show_more', { defaultValue: 'Show more' })}
                  </Button>
                }
              />
              <CardContent>
                <CrossModuleActivityFeed limit={showAllActivity ? 25 : 6} />
              </CardContent>
            </Card>
          </div>
        )}
        <div className={`${projects && projects.length > 0 ? 'lg:col-start-3' : ''} animate-card-in`} style={{ animationDelay: '220ms' }}>
          <Card className="h-full">
            <CardHeader title={t('dashboard.system_status')} />
            <CardContent>
              <SystemStatus />
            </CardContent>
          </Card>
        </div>
      </div>
    ),

    // ── Wave 2 operations widgets (2026-05-23) — consolidated 2026-05-25
    //    into a single OperationsSnapshotCard. The 9 individual widgets
    //    still exist in NewWidgets.tsx (importable for projects that
    //    want to embed them elsewhere) but no longer have IDs in the
    //    registry, so the dashboard never renders them inline.
    operations_snapshot: <OperationsSnapshotCard projects={projects} />,
    weather_site: <WeatherSiteWidget projects={projects} />,
  };

  return (
    <DashboardRollupProvider>
    <div className="space-y-5 animate-fade-in">
      {/* "What's new in vX.Y.Z" release-notes card. Self-gates on a
          localStorage `oe_whats_new_seen_<version>` flag so it only
          appears once per release per browser. Sits above the hero so
          the user sees release highlights before the dashboard hero. */}
      <WhatsNewCard />
      {/* ─── 1. Hero · row A — greeting + primary actions ────────────────
          Compressed from the previous 6-row hero (audit 2026-05-11): the
          greeting and the 3 CTAs share a single line on desktop; row B
          below merges DDC attribution + OSS badge + status pills into a
          thin meta-strip. Saves ~180px above the fold. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between animate-card-in">
        <h1 className="text-2xl font-semibold tracking-tight gradient-text pl-2">
          {(() => {
            const h = new Date().getHours();
            const key =
              h < 5  ? 'dashboard.greet_night'
            : h < 12 ? 'dashboard.greet_morning'
            : h < 18 ? 'dashboard.greet_afternoon'
            :          'dashboard.greet_evening';
            const fallback =
              h < 5  ? 'Welcome back'
            : h < 12 ? 'Good morning'
            : h < 18 ? 'Good afternoon'
            :          'Good evening';
            return t(key, { defaultValue: fallback });
          })()}
        </h1>
        <div
          className="flex items-center gap-2 flex-wrap animate-stagger-in"
          style={{ animationDelay: '100ms' }}
          data-testid="dashboard-tour-hero-actions"
        >
          <Button
            variant="primary"
            size="md"
            icon={<FolderPlus size={16} />}
            onClick={() => navigate('/projects/new')}
          >
            {t('projects.new_project')}
          </Button>
          <Button
            variant="secondary"
            size="md"
            icon={<FileSpreadsheet size={15} />}
            onClick={() => {
              const firstProject = projects?.[0];
              if (firstProject) {
                navigate(`/projects/${firstProject.id}/boq/new`);
              } else {
                navigate('/projects/new');
              }
            }}
            title={t('dashboard.new_estimate_hint', { defaultValue: 'Start a new Bill of Quantities for an existing project' })}
          >
            {t('dashboard.new_estimate', { defaultValue: 'New Estimate' })}
          </Button>
          <Button
            variant="ghost"
            size="md"
            icon={<Sparkles size={14} />}
            onClick={() => {
              if (lastBoq) { navigate(`/boq/${lastBoq.id}`); return; }
              const firstProject = projects?.[0];
              if (firstProject) navigate(`/projects/${firstProject.id}/boq/new`);
              else navigate('/projects/new');
            }}
            title={
              lastBoq
                ? t('dashboard.quick_start_resume_hint', { defaultValue: 'Continue your most recent estimate: {{name}}', name: lastBoq.name })
                : t('dashboard.quick_start_hint', { defaultValue: 'Jump into an estimate — resumes the latest or starts a new one' })
            }
          >
            {lastBoq
              ? t('dashboard.quick_resume', { defaultValue: 'Resume last estimate' })
              : t('dashboard.quick_start', { defaultValue: 'Quick Start' })}
          </Button>
          <Button
            variant={customizing ? 'primary' : 'ghost'}
            size="md"
            icon={<LayoutGrid size={15} />}
            onClick={() => setCustomizing((v) => !v)}
            aria-pressed={customizing}
            title={t('dashboard.layout.customize_hint', {
              defaultValue: 'Reorder, show or hide dashboard sections',
            })}
            data-testid="dashboard-tour-customize-button"
          >
            {customizing
              ? t('dashboard.layout.done', { defaultValue: 'Done' })
              : t('dashboard.layout.customize', { defaultValue: 'Customize' })}
          </Button>
          {/* Per-module Tour CTA — launches the Dashboard guided tour. */}
          <ModuleHelpButton tourId="dashboard" />
        </div>
      </div>

      {/* ─── 2. Hero · row B — thin meta-strip ───────────────────────── */}
      <div className="flex items-center flex-wrap gap-x-4 gap-y-2 pl-2 animate-stagger-in" style={{ animationDelay: '140ms' }}>
        {/* DDC attribution — slim inline link with tiny logo */}
        <a
          href="https://datadrivenconstruction.io/?utm_source=erp"
          target="_blank"
          rel="noopener noreferrer"
          className="group/ddc inline-flex items-center gap-1.5 text-[11px] text-content-tertiary hover:text-content-secondary transition-colors"
        >
          <img
            src="/brand/ddc-logo.webp"
            alt="DataDrivenConstruction"
            className="h-3.5 w-auto opacity-60 group-hover/ddc:opacity-100 transition-opacity"
          />
          <span className="hidden sm:inline">
            {t('dashboard.developed_by_short', { defaultValue: 'by DataDrivenConstruction' })}
          </span>
        </a>

        <span aria-hidden className="h-3 w-px bg-border-light" />

        {/* Open-source pill — slimmer (was a heavy gradient card) */}
        <a
          href="https://github.com/datadrivenconstruction/OpenConstructionERP"
          target="_blank"
          rel="noopener noreferrer"
          className="group/oss inline-flex items-center gap-2 text-xs font-medium text-content-secondary hover:text-content-primary transition-colors"
        >
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <span>{t('dashboard.open_source_badge', { defaultValue: 'Open-source construction ERP' })}</span>
          <ExternalLink size={11} className="text-content-quaternary group-hover/oss:text-oe-blue transition-colors" />
        </a>

        <span aria-hidden className="h-3 w-px bg-border-light" />

        {/* System status pills */}
        <SystemStatusSummary projects={projects} boqs={allBoqs} />
      </div>

      {/* ─── Customize panel (collapsible) — same manager as Settings ─── */}
      {customizing && (
        <Card className="animate-card-in border-oe-blue/30">
          <CardHeader
            title={t('dashboard.layout.title', { defaultValue: 'Customize dashboard' })}
            subtitle={t('dashboard.layout.subtitle', {
              defaultValue:
                'Reorder, show or hide the sections below. Your layout is saved to this browser.',
            })}
          />
          <CardContent>
            <DashboardLayoutManager onClose={() => setCustomizing(false)} />
          </CardContent>
        </Card>
      )}

      {/* ─── Widgets — rendered in the user's saved order, hidden ones
          skipped. Conditional widgets resolve to null and contribute
          nothing (same behaviour as when they were inline). ──────────── */}
      {resolvedWidgets.map((id) => {
        if (widgetHidden.includes(id)) return null;
        const node = widgetNodes[id];
        return node ? <Fragment key={id}>{node}</Fragment> : null;
      })}
    </div>
    </DashboardRollupProvider>
  );
}

/* ── Projects List ────────────────────────────────────────────────────── */

function ProjectsList({ projects }: { projects?: ProjectSummary[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // BUG-UI01: install-demo mutation removed alongside the 3-tile empty
  // state. Demo installation now lives under Settings → Demo data.

  if (!projects || projects.length === 0) {
    // BUG-UI01: clean centered empty-state for fresh tenants. The earlier
    // 3-tile grid felt like a chooser; the user just wants a clear
    // "create your first project" CTA with the demo path as a secondary hint.
    return (
      <div className="flex h-full min-h-[60vh] items-center justify-center px-6 py-8">
        <EmptyState
          icon={<FolderPlus size={28} strokeWidth={1.5} />}
          title={t('dashboard.empty.title', {
            defaultValue: "Welcome — let's start with your first project",
          })}
          description={t('dashboard.empty.desc', {
            defaultValue: 'Projects organise your BOQs, schedules, and reports.',
          })}
          action={
            <div className="flex flex-col items-center gap-3">
              <Button onClick={() => navigate('/projects/new')}>
                <FolderPlus size={16} strokeWidth={1.75} />
                {t('dashboard.empty.cta_create', { defaultValue: 'Create project' })}
              </Button>
              <p className="text-xs text-content-tertiary">
                {t('dashboard.empty.demo_hint', {
                  defaultValue: 'Or load a demo project from Settings → Demo data',
                })}
              </p>
            </div>
          }
        />
      </div>
    );
  }

  // Deduplicate by ID, then pin `en` + `de` projects to the top so the
  // US and German demos anchor the dashboard's "recent projects" tile.
  // Same priority rule as ProjectsPage; keep them in sync if you change it.
  const seen = new Set<string>();
  const localePriority = (loc?: string) => (loc === 'en' ? 0 : loc === 'de' ? 1 : 2);
  const unique = projects
    .filter((p) => {
      if (seen.has(p.id)) return false;
      seen.add(p.id);
      return true;
    })
    .sort((a, b) => localePriority(a.locale) - localePriority(b.locale))
    .slice(0, 6);

  return (
    <div className="divide-y divide-border-light">
      {unique.map((p, index) => (
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
            <DateDisplay value={p.created_at} />
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

  // Source aggregates from the dashboard rollup the parent provider already
  // fetched — eliminates the per-project ``/v1/boq/boqs/?project_id=…`` fan
  // -out this component used to do (v4.6.2 N+1 nuke 2026-05-24).
  const { byWidget } = useDashboardRollupContext();
  const boqSummary = byWidget('boq_summary');

  const stats = useMemo(() => {
    if (!boqSummary) return null;

    const totalBoqs = boqSummary.total_boqs;
    const totalValue = Number(boqSummary.total_value_eur) || 0;

    // Per-project total values come directly from the rollup. Dedup by
    // display name so two same-named projects merge (legacy behaviour the
    // analytics chart relied on).
    const valueByName = new Map<string, number>();
    for (const row of boqSummary.by_project) {
      const v = Number(row.total_value) || 0;
      valueByName.set(row.project_name, (valueByName.get(row.project_name) ?? 0) + v);
    }
    const projectValues: { name: string; value: number }[] = Array.from(valueByName.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);

    // We no longer have per-BOQ status (we'd need a BOQ list call for
    // that) — present a binary active vs inactive split derived from
    // the active-count the rollup exposes. The donut chart consumer just
    // wants ratio-shaped buckets, so this preserves the visual.
    const inactive = Math.max(0, totalBoqs - (boqSummary.active_boqs ?? totalBoqs));
    const statusCounts: Record<string, number> = {};
    if (boqSummary.active_boqs > 0) statusCounts.active = boqSummary.active_boqs;
    if (inactive > 0) statusCounts.archived = inactive;

    return {
      totalProjects: projects.length,
      totalBoqs,
      totalValue,
      projectValues,
      statusCounts,
    };
  }, [boqSummary, projects.length]);

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

  return (
    <Card>
      <CardHeader title={t('dashboard.project_overview', { defaultValue: 'Project Overview' })} />
      <CardContent>
        {/* Aggregate Stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 mb-6">
          <div className="rounded-lg bg-surface-secondary p-3">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_projects', { defaultValue: 'Total Projects' })}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalProjects}
            </div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-3">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_boqs', { defaultValue: 'Total BOQs' })}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalBoqs}
            </div>
          </div>
          <div className="rounded-lg bg-surface-secondary p-3 sm:col-span-2">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('dashboard.total_value', { defaultValue: 'Total Value' })}
            </div>
            <div className="mt-1 text-xl font-bold tabular-nums text-content-primary">
              {stats.totalValue >= 1_000_000
                ? `${(stats.totalValue / 1_000_000).toFixed(1)}M`
                : stats.totalValue >= 1_000
                  ? `${(stats.totalValue / 1_000).toFixed(0)}K`
                  : stats.totalValue.toLocaleString('de-DE', {
                      minimumFractionDigits: 0,
                      maximumFractionDigits: 0,
                    })}
            </div>
          </div>
        </div>

        {/* Cleaned per audit 2026-05-11: removed the BOQ-status donut
            (vanity metric — nobody asks "how many of my BOQs are drafts?").
            Bars now span full-width with slimmer height (h-2 vs h-6) and
            use the oe-blue brand color instead of a 10-colour rainbow. */}
        <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
          {t('dashboard.value_by_project', 'Value by Project')}
        </div>
        <div className="space-y-3">
          {stats.projectValues.filter((pv) => pv.value > 0).slice(0, 10).map((pv, i) => {
            const barWidth = maxValue > 0 ? (pv.value / maxValue) * 100 : 0;
            const formattedValue =
              pv.value >= 1_000_000
                ? `${(pv.value / 1_000_000).toFixed(1)}M`
                : pv.value >= 1_000
                  ? `${(pv.value / 1_000).toFixed(0)}K`
                  : pv.value.toLocaleString();
            const shareLabel = `${Math.round(barWidth)}%`;
            return (
              <div key={`${pv.name}-${i}`}>
                <div className="flex items-baseline justify-between gap-3 mb-1">
                  <span className="text-xs font-medium text-content-primary truncate">
                    {pv.name}
                  </span>
                  <span className="flex items-baseline gap-2 shrink-0">
                    <span className="text-2xs text-content-tertiary tabular-nums">{shareLabel}</span>
                    <span className="text-xs font-semibold tabular-nums text-content-primary">
                      {formattedValue}
                    </span>
                  </span>
                </div>
                <div className="h-2 w-full bg-surface-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-oe-blue to-oe-blue-hover transition-all duration-500 ease-out"
                    style={{ width: `${Math.max(barWidth, 2)}%` }}
                  />
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
      </CardContent>
    </Card>
  );
}

/* ── System Status ────────────────────────────────────────────────────── */

function StatusDot({ status }: { status: 'connected' | 'healthy' | 'offline' | 'error' | string }) {
  const color =
    status === 'connected' || status === 'healthy'
      ? 'bg-semantic-success'
      : status === 'offline'
        ? 'bg-content-quaternary'
        : 'bg-semantic-error';
  const pulse = status === 'connected' || status === 'healthy';
  return (
    <span className="relative flex h-2 w-2">
      {pulse && <span className={`absolute inset-0 rounded-full ${color} opacity-50 animate-ping`} />}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${color}`} />
    </span>
  );
}

function SystemStatus() {
  const { t } = useTranslation();

  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: () => fetch('/api/system/status').then((r) => r.json()) as Promise<SystemStatusData>,
    retry: false,
    refetchInterval: 15000,
  });

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => apiGet<{ modules: unknown[] }>('/system/modules').catch(() => ({ modules: [] })),
    retry: false,
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () =>
      apiGet<{ rule_sets: unknown[]; rules: unknown[] }>('/system/validation-rules').catch(() => ({
        rule_sets: [],
        rules: [],
      })),
    retry: false,
  });

  // Check user AI keys from localStorage
  const hasUserAiKey = typeof window !== 'undefined' && (
    !!localStorage.getItem('oe_ai_provider') ||
    !!localStorage.getItem('oe_openai_key') ||
    !!localStorage.getItem('oe_anthropic_key')
  );

  const apiStatus = status?.api?.status ?? 'offline';
  const dbStatus = status?.database?.status ?? 'offline';
  const vectorStatus = status?.vector_db?.status ?? 'offline';
  const vectorVectors = status?.vector_db?.vectors ?? 0;
  const aiConfigured = status?.ai?.configured || hasUserAiKey;

  const services = [
    {
      name: t('dashboard.api_server', { defaultValue: 'API Server' }),
      status: apiStatus,
      detail: status?.api?.version ? `v${status.api.version}` : '',
      icon: <Zap size={13} />,
      delay: 400,
    },
    {
      name: t('dashboard.database', { defaultValue: 'Database' }),
      status: dbStatus,
      detail: status?.database?.engine === 'sqlite' ? 'SQLite' : status?.database?.engine ?? '',
      icon: <Layers size={13} />,
      delay: 460,
    },
    {
      name: t('dashboard.vector_db', { defaultValue: 'Vector DB' }),
      status: vectorStatus,
      detail: [status?.vector_db?.engine, vectorVectors > 0 ? `${vectorVectors.toLocaleString()} vectors` : ''].filter(Boolean).join(' · '),
      icon: <Globe size={13} />,
      delay: 520,
    },
    {
      name: t('dashboard.ai_providers', { defaultValue: 'AI Providers' }),
      status: aiConfigured ? 'connected' : 'offline',
      detail: status?.ai?.providers?.map((p) => p.name).join(', ') || (hasUserAiKey ? 'User keys' : t('dashboard.not_configured', { defaultValue: 'Not configured' })),
      icon: <ShieldCheck size={13} />,
      delay: 580,
    },
  ];

  return (
    <div className="space-y-3">
      {/* Service indicators */}
      {services.map((svc) => (
        <div
          key={svc.name}
          className="flex items-center justify-between animate-stagger-in"
          style={{ animationDelay: `${svc.delay}ms` }}
        >
          <span className="flex items-center gap-2 text-sm text-content-secondary">
            {svc.icon}
            {svc.name}
          </span>
          <div className="flex items-center gap-2">
            {svc.detail && (
              <span className="text-2xs text-content-quaternary">{svc.detail}</span>
            )}
            <StatusDot status={svc.status} />
          </div>
        </div>
      ))}

      {/* Divider */}
      <div className="h-px bg-border-light" />

      {/* Modules & Rules */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '180ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.modules_loaded')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {modules?.modules?.length ?? '\u2014'}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '200ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.validation_rules')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {rules?.rules?.length ?? '\u2014'}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '220ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.languages')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">{SUPPORTED_LANGUAGES.length}</span>
      </div>
    </div>
  );
}

/* ── Activity Feed ───────────────────────────────────────────────────── */

/* ActivityFeed is now provided by @/shared/ui/ActivityFeed (cross-module, audit-log-based) */

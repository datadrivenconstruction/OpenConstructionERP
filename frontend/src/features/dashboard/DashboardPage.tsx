import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiGet, apiPost } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
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
  Star,
  Loader2,
  DollarSign,
  FileText,
  Calendar,
  Upload,
  ExternalLink,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, Skeleton, InfoHint } from '@/shared/ui';

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

/* ── Constants ─────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, string> = {
  draft: '#2563eb',
  final: '#16a34a',
  archived: '#6b7280',
};

const BAR_COLORS = ['#2563eb', '#7c3aed', '#0891b2', '#dc2626', '#ca8a04', '#16a34a'];

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
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
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
}: {
  projects?: ProjectSummary[];
  regionStats?: RegionStat[];
  boqs?: BOQWithTotal[];
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [demoModalOpen, setDemoModalOpen] = useState(false);

  const hasDatabase = Boolean(regionStats && regionStats.length > 0);
  const hasProjects = Boolean(projects && projects.length > 0);
  const hasBoqs = Boolean(boqs && boqs.length > 0);

  const aiConfigured = (() => {
    try {
      return Boolean(localStorage.getItem('oe_ai_provider'));
    } catch {
      return false;
    }
  })();

  const completedCount = [hasDatabase, hasDatabase, aiConfigured, hasProjects, hasBoqs].filter(
    Boolean,
  ).length;

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
      done: hasDatabase,
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
            {completedCount}/5
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
              width: `${(completedCount / 5) * 100}%`,
              background: 'linear-gradient(90deg, var(--oe-blue), #5856d6)',
            }}
          />
        </div>
      </div>

      {/* Step cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
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
                        ? 'bg-semantic-success-bg text-[#15803d]'
                        : 'bg-oe-blue-subtle text-oe-blue'
                    }`}
                  >
                    {step.id}
                  </div>
                  <div
                    className={`${step.done ? 'text-[#15803d]' : 'text-content-tertiary'}`}
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

  const totalValue = useMemo(() => {
    if (!boqs || boqs.length === 0) return 0;
    return boqs.reduce((sum, b) => sum + (b.grand_total ?? 0), 0);
  }, [boqs]);

  const activeEstimates = useMemo(() => {
    if (!boqs) return 0;
    return boqs.filter((b) => b.status === 'draft').length;
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

  const formatCurrency = (value: number) => {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
    return new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  };

  const cards = [
    {
      icon: <DollarSign size={20} strokeWidth={1.75} />,
      value: boqs ? `${currency === 'EUR' ? '\u20AC' : currency === 'GBP' ? '\u00A3' : currency === 'USD' ? '$' : currency === 'AED' ? 'AED ' : ''}${formatCurrency(totalValue)}` : null,
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
      color: 'text-[#7c3aed]',
      bg: 'bg-[#7c3aed]/10',
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
      color: 'text-[#0891b2]',
      bg: 'bg-[#0891b2]/10',
    },
    {
      icon: <ShieldCheck size={20} strokeWidth={1.75} />,
      value: qualityScore !== null ? `${qualityScore}%` : t('dashboard.kpi_not_validated', { defaultValue: 'N/A' }),
      sublabel: qualityScore !== null
        ? t('dashboard.kpi_quality_score_label', { defaultValue: 'score' })
        : t('dashboard.kpi_run_validation', { defaultValue: 'run validation' }),
      label: t('dashboard.kpi_quality', { defaultValue: 'Quality Score' }),
      color: qualityScore !== null && qualityScore >= 80 ? 'text-[#16a34a]' : qualityScore !== null && qualityScore >= 50 ? 'text-[#ca8a04]' : 'text-content-tertiary',
      bg: qualityScore !== null && qualityScore >= 80 ? 'bg-[#16a34a]/10' : qualityScore !== null && qualityScore >= 50 ? 'bg-[#ca8a04]/10' : 'bg-surface-secondary',
    },
  ];

  return (
    <div
      className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4 animate-card-in"
      style={{ animationDelay: '50ms' }}
    >
      {cards.map((card, i) => (
        <div
          key={card.label}
          className="group flex items-center gap-3 rounded-xl border border-border-light bg-surface-primary p-4 transition-all duration-normal ease-oe hover:border-oe-blue/20 hover:shadow-sm animate-stagger-in"
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
        </div>
      ))}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // First launch: redirect to onboarding wizard
  useEffect(() => {
    try {
      if (localStorage.getItem('oe_onboarding_completed') !== 'true') {
        navigate('/onboarding', { replace: true });
      }
    } catch { /* storage unavailable */ }
  }, [navigate]);

  // Show welcome/support modal (after onboarding is done, first dashboard visit)
  const [showWelcome, setShowWelcome] = useState(() => !localStorage.getItem('oe_welcome_dismissed'));
  const dismissWelcome = useCallback(() => {
    setShowWelcome(false);
    localStorage.setItem('oe_welcome_dismissed', '1');
  }, []);

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/').catch(() => []),
    retry: false,
  });

  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats').catch(() => []),
    retry: false,
  });

  // Fetch all BOQs across projects for KPI ribbon + analytics
  const { data: allBoqs } = useQuery({
    queryKey: ['dashboard-all-boqs', projects?.map((p) => p.id).join(',')],
    queryFn: async () => {
      const results: BOQWithTotal[] = [];
      for (const project of projects ?? []) {
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
    enabled: Boolean(projects && projects.length > 0),
    retry: false,
  });

  // Fetch schedules across projects for KPI ribbon
  const { data: allSchedules } = useQuery({
    queryKey: ['dashboard-all-schedules', projects?.map((p) => p.id).join(',')],
    queryFn: async () => {
      const results: ScheduleSummary[] = [];
      for (const project of projects ?? []) {
        try {
          const schedules = await apiGet<ScheduleSummary[]>(
            `/v1/schedule/schedules/?project_id=${project.id}`,
          );
          results.push(...schedules);
        } catch {
          // Skip
        }
      }
      return results;
    },
    enabled: Boolean(projects && projects.length > 0),
    retry: false,
  });

  // Determine the most recently updated BOQ for "Continue last estimate"
  const lastBoqId = useMemo(() => {
    if (!allBoqs || allBoqs.length === 0) return null;
    // BOQs are returned from API in order; pick the first draft, or just the first
    const drafts = allBoqs.filter((b) => b.status === 'draft');
    return drafts.length > 0 ? drafts[0]!.id : allBoqs[0]!.id;
  }, [allBoqs]);

  return (
    <div className="max-w-content mx-auto space-y-6">
      {/* Hero — gradient animated heading */}
      <div
        className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between animate-card-in"
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
          {/* Open-source banner */}
          <a
            href="https://github.com/datadrivenconstruction/OpenConstructionERP"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 flex items-center gap-3 rounded-xl bg-gradient-to-r from-oe-blue/8 via-violet-500/8 to-emerald-500/8 border border-oe-blue/15 px-4 py-2.5 hover:shadow-md hover:border-oe-blue/30 transition-all animate-stagger-in"
            style={{ animationDelay: '150ms' }}
          >
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
            <span className="text-sm font-bold bg-gradient-to-r from-oe-blue via-violet-600 to-emerald-600 bg-clip-text text-transparent">
              {t('dashboard.open_source_badge', { defaultValue: 'The #1 open-source construction ERP' })}
            </span>
            <ExternalLink size={13} className="text-oe-blue opacity-50 shrink-0" />
          </a>
        </div>
        <div className="flex items-center gap-2 animate-stagger-in" style={{ animationDelay: '200ms' }}>
          {lastBoqId && (
            <Button
              variant="secondary"
              size="lg"
              icon={<ArrowRight size={16} />}
              iconPosition="right"
              onClick={() => navigate(`/boq/${lastBoqId}`)}
            >
              {t('dashboard.continue_estimate', { defaultValue: 'Continue last estimate' })}
            </Button>
          )}
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

      {/* Welcome banner — shown once on first launch, dismissable */}
      {/* Welcome modal — first launch only */}
      {showWelcome && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={dismissWelcome} />
          <div className="relative w-full max-w-lg rounded-2xl border border-border-light bg-surface-elevated shadow-2xl overflow-hidden">
            {/* Header gradient */}
            <div className="bg-gradient-to-r from-oe-blue to-violet-600 px-6 py-5 text-white text-center">
              <h2 className="text-lg font-bold">{t('dashboard.welcome_title', { defaultValue: 'Welcome to OpenConstructionERP' })}</h2>
              <p className="mt-1 text-sm text-white/80">{t('dashboard.welcome_sub', { defaultValue: 'Free & open-source construction cost estimation' })}</p>
            </div>

            {/* Content */}
            <div className="px-6 py-5">
              <p className="text-sm text-content-secondary text-center mb-5 leading-relaxed">
                {t('dashboard.welcome_body', { defaultValue: 'This project is built and maintained by the community. Your support helps us add new features, regional databases, and keep it free for everyone.' })}
              </p>

              {/* 3 CTA cards */}
              <div className="space-y-2.5">
                <a
                  href="https://github.com/datadrivenconstruction/OpenConstructionERP"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-xl border border-amber-200 dark:border-amber-800/40 bg-amber-50/50 dark:bg-amber-900/10 px-4 py-3 hover:shadow-md transition-all group"
                >
                  <Star size={22} className="text-amber-500 shrink-0 group-hover:scale-110 transition-transform" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-content-primary">{t('dashboard.welcome_star', { defaultValue: 'Star on GitHub' })}</div>
                    <div className="text-2xs text-content-tertiary">{t('dashboard.welcome_star_desc', { defaultValue: 'Help others discover the project — takes 2 seconds' })}</div>
                  </div>
                  <ExternalLink size={14} className="text-content-quaternary shrink-0" />
                </a>

                <a
                  href="https://github.com/sponsors/datadrivenconstruction"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-xl border border-rose-200 dark:border-rose-800/40 bg-rose-50/50 dark:bg-rose-900/10 px-4 py-3 hover:shadow-md transition-all group"
                >
                  <Sparkles size={22} className="text-rose-500 shrink-0 group-hover:scale-110 transition-transform" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-content-primary">{t('dashboard.welcome_sponsor', { defaultValue: 'Become a Sponsor' })}</div>
                    <div className="text-2xs text-content-tertiary">{t('dashboard.welcome_sponsor_desc', { defaultValue: 'Fund new features and keep the project free for everyone' })}</div>
                  </div>
                  <ExternalLink size={14} className="text-content-quaternary shrink-0" />
                </a>

                <a
                  href="https://datadrivenconstruction.io/contact-support/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-xl border border-oe-blue/20 dark:border-blue-800/40 bg-oe-blue/[0.03] dark:bg-blue-900/10 px-4 py-3 hover:shadow-md transition-all group"
                >
                  <Building2 size={22} className="text-oe-blue shrink-0 group-hover:scale-110 transition-transform" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-content-primary">{t('dashboard.welcome_consult', { defaultValue: 'Professional Consulting' })}</div>
                    <div className="text-2xs text-content-tertiary">{t('dashboard.welcome_consult_desc', { defaultValue: 'Custom deployment, training, and enterprise solutions worldwide' })}</div>
                  </div>
                  <ExternalLink size={14} className="text-content-quaternary shrink-0" />
                </a>
              </div>
            </div>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-border-light bg-surface-secondary/30 flex items-center justify-between">
              <span className="text-2xs text-content-quaternary">datadrivenconstruction.io</span>
              <button
                onClick={dismissWelcome}
                className="rounded-lg bg-oe-blue px-4 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 transition-colors"
              >
                {t('dashboard.welcome_start', { defaultValue: 'Get Started' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* KPI hint */}
      <InfoHint text={t('dashboard.kpi_hint', { defaultValue: 'Summary across all projects. Values update as you add estimates and schedule activities.' })} />

      {/* KPI Ribbon */}
      <KpiRibbon boqs={allBoqs} schedules={allSchedules} projects={projects} />

      {/* Quick Actions */}
      {projects && projects.length > 0 && (
        <div className="flex flex-wrap sm:flex-nowrap sm:overflow-x-auto sm:scrollbar-none items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 animate-card-in" style={{ animationDelay: '80ms' }}>
          <span className="text-xs font-medium text-content-tertiary mr-1">
            {t('dashboard.quick_actions', { defaultValue: 'Quick Actions' })}:
          </span>
          <Button
            variant="secondary"
            size="sm"
            icon={<FolderPlus size={14} />}
            onClick={() => navigate('/projects/new')}
          >
            {t('dashboard.new_project', { defaultValue: 'New Project' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<FileText size={14} />}
            onClick={() => navigate('/boq/new')}
          >
            {t('dashboard.create_boq', { defaultValue: 'New BOQ' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<ShieldCheck size={14} />}
            onClick={() => navigate('/validation')}
          >
            {t('nav.validation', { defaultValue: 'Validate' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            onClick={() => navigate('/costs/import')}
          >
            {t('costs.import_title', { defaultValue: 'Import Database' })}
          </Button>
        </div>
      )}

      {/* Onboarding Steps */}
      <OnboardingSteps projects={projects} regionStats={regionStats} boqs={allBoqs} />

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

        {/* System Status + Activity — staggered card entrance */}
        <div className="space-y-6 animate-card-in" style={{ animationDelay: '300ms' }}>
          <Card>
            <CardHeader title={t('dashboard.system_status')} />
            <CardContent>
              <SystemStatus />
            </CardContent>
          </Card>

          {/* Activity Feed */}
          {projects && projects.length > 0 && (
            <Card>
              <CardHeader title={t('dashboard.activity', { defaultValue: 'Recent Activity' })} />
              <CardContent>
                <ActivityFeed projects={projects} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Analytics Section */}
      {projects && projects.length > 0 && (
        <div className="animate-card-in" style={{ animationDelay: '450ms' }}>
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 size={18} className="text-content-tertiary" strokeWidth={1.75} />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('dashboard.analytics', { defaultValue: 'Analytics' })}
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
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const installDemoMutation = useMutation({
    mutationFn: () => apiPost<DemoInstallResult>('/demo/install/residential-berlin'),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${result.project_id}`);
    },
  });

  if (!projects || projects.length === 0) {
    return (
      <div className="px-6 py-8">
        <div className="text-center mb-6">
          <p className="text-sm font-semibold text-content-primary">
            {t('dashboard.welcome_title', { defaultValue: 'Welcome to OpenConstructionERP' })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('dashboard.welcome_desc', { defaultValue: 'Start by installing a demo project or creating your own.' })}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {/* Install Demo Project */}
          <button
            onClick={() => installDemoMutation.mutate()}
            disabled={installDemoMutation.isPending}
            className="group relative flex flex-col items-center gap-2 rounded-xl border border-border-light bg-surface-primary p-5 text-center transition-all duration-normal ease-oe hover:border-oe-blue/40 hover:bg-oe-blue-subtle/30 disabled:opacity-60"
          >
            <span className="absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold">1</span>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue transition-transform group-hover:scale-110">
              {installDemoMutation.isPending ? (
                <Loader2 size={20} className="animate-spin" strokeWidth={1.5} />
              ) : (
                <Download size={20} strokeWidth={1.5} />
              )}
            </div>
            <span className="text-sm font-medium text-content-primary">
              {t('dashboard.install_demo', { defaultValue: 'Install Demo Project' })}
            </span>
            <span className="text-[11px] leading-snug text-content-tertiary">
              {t('dashboard.install_demo_desc', { defaultValue: 'Pre-built residential project with realistic data' })}
            </span>
          </button>

          {/* Create First Project */}
          <button
            onClick={() => navigate('/projects/new')}
            className="group relative flex flex-col items-center gap-2 rounded-xl border border-border-light bg-surface-primary p-5 text-center transition-all duration-normal ease-oe hover:border-oe-blue/40 hover:bg-oe-blue-subtle/30"
          >
            <span className="absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold">2</span>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue transition-transform group-hover:scale-110">
              <FolderPlus size={20} strokeWidth={1.5} />
            </div>
            <span className="text-sm font-medium text-content-primary">
              {t('dashboard.create_first_project', { defaultValue: 'Create First Project' })}
            </span>
            <span className="text-[11px] leading-snug text-content-tertiary">
              {t('dashboard.create_first_project_desc', { defaultValue: 'Set up a new estimation from scratch' })}
            </span>
          </button>

          {/* Import Existing BOQ */}
          <button
            onClick={() => navigate('/ai-estimate')}
            className="group relative flex flex-col items-center gap-2 rounded-xl border border-border-light bg-surface-primary p-5 text-center transition-all duration-normal ease-oe hover:border-oe-blue/40 hover:bg-oe-blue-subtle/30"
          >
            <span className="absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold">3</span>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue transition-transform group-hover:scale-110">
              <Upload size={20} strokeWidth={1.5} />
            </div>
            <span className="text-sm font-medium text-content-primary">
              {t('dashboard.import_existing_boq', { defaultValue: 'Import Existing BOQ' })}
            </span>
            <span className="text-[11px] leading-snug text-content-tertiary">
              {t('dashboard.import_existing_boq_desc', { defaultValue: 'Use AI to estimate from an existing document' })}
            </span>
          </button>
        </div>
      </div>
    );
  }

  // Deduplicate by ID and show only latest 10
  const seen = new Set<string>();
  const unique = projects.filter((p) => {
    if (seen.has(p.id)) return false;
    seen.add(p.id);
    return true;
  }).slice(0, 6);

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
            {new Date(p.created_at).toLocaleDateString(i18n.language)}
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
    const totalValue = allBoqs.reduce((sum, b) => sum + (b.grand_total ?? 0), 0);

    // Value per project
    // Deduplicate projects by name (merge values for same-named projects)
    const valueByName = new Map<string, number>();
    for (const p of projects) {
      const val = allBoqs
        .filter((b) => b.project_id === p.id)
        .reduce((sum, b) => sum + (b.grand_total ?? 0), 0);
      valueByName.set(p.name, (valueByName.get(p.name) ?? 0) + val);
    }
    const projectValues: { name: string; value: number }[] = Array.from(valueByName.entries())
      .map(([name, value]) => ({ name, value }))
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

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Bar chart — value by project */}
          <div className="lg:col-span-2">
            <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
              {t('dashboard.value_by_project', 'Value by Project')}
            </div>
            <div className="space-y-2.5">
              {stats.projectValues.filter((pv) => pv.value > 0).slice(0, 10).map((pv, i) => {
                const barWidth = maxValue > 0 ? (pv.value / maxValue) * 100 : 0;
                const color = BAR_COLORS[i % BAR_COLORS.length];
                const formattedValue =
                  pv.value >= 1_000_000
                    ? `${(pv.value / 1_000_000).toFixed(1)}M`
                    : pv.value >= 1_000
                      ? `${(pv.value / 1_000).toFixed(0)}K`
                      : pv.value.toLocaleString();
                return (
                  <div key={`${pv.name}-${i}`} className="flex items-center gap-3">
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

interface SystemStatusData {
  api: { status: string; version: string };
  database: { status: string; engine?: string; error?: string };
  vector_db: { status: string; engine: string; collections?: number; vectors?: number };
  ai: { providers: { name: string; configured: boolean }[]; configured: boolean };
}

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
    queryFn: () => fetch('/api/system/modules').then((r) => r.json()),
    retry: false,
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () => fetch('/api/system/validation-rules').then((r) => r.json()),
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
      detail: vectorVectors > 0 ? `${vectorVectors.toLocaleString()} vectors` : '',
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
        style={{ animationDelay: '640ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.modules_loaded')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {modules?.modules?.length ?? 17}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '700ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.validation_rules')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {rules?.rules?.length ?? 42}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '760ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.languages')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">20</span>
      </div>
    </div>
  );
}

/* ── Activity Feed ───────────────────────────────────────────────────── */

function ActivityFeed({ projects }: { projects: ProjectSummary[] }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  // Fetch real activity from all projects (up to 3 projects, 5 entries each)
  const projectIds = useMemo(() => projects.slice(0, 3).map((p) => p.id), [projects]);
  const projectMap = useMemo(
    () => Object.fromEntries(projects.map((p) => [p.id, p.name])),
    [projects],
  );

  const { data: activityData } = useQuery({
    queryKey: ['dashboard-activity', projectIds],
    queryFn: async () => {
      const results = await Promise.all(
        projectIds.map((id) =>
          apiGet<{ items: Array<{ id: string; project_id: string | null; action: string; description: string; created_at: string }>; total: number }>(
            `/v1/boq/projects/${id}/activity?limit=5`,
          ).catch(() => ({ items: [], total: 0 })),
        ),
      );
      const all = results.flatMap((r) => r.items);
      all.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      return all.slice(0, 8);
    },
    enabled: projectIds.length > 0,
    staleTime: 30_000,
  });

  const activities = activityData ?? [];

  // Icon + color by action type
  const actionMeta = useCallback((action: string) => {
    if (action.includes('added') || action.includes('created'))
      return { icon: <FolderPlus size={12} />, bg: 'bg-emerald-100 dark:bg-emerald-900/30', fg: 'text-emerald-600 dark:text-emerald-400' };
    if (action.includes('updated') || action.includes('changed'))
      return { icon: <FileText size={12} />, bg: 'bg-oe-blue-subtle', fg: 'text-oe-blue' };
    if (action.includes('deleted'))
      return { icon: <X size={12} />, bg: 'bg-red-100 dark:bg-red-900/30', fg: 'text-red-500' };
    if (action.includes('import'))
      return { icon: <Download size={12} />, bg: 'bg-amber-100 dark:bg-amber-900/30', fg: 'text-amber-600 dark:text-amber-400' };
    if (action.includes('validation'))
      return { icon: <CheckCircle2 size={12} />, bg: 'bg-purple-100 dark:bg-purple-900/30', fg: 'text-purple-600 dark:text-purple-400' };
    return { icon: <Zap size={12} />, bg: 'bg-oe-blue-subtle', fg: 'text-oe-blue' };
  }, []);

  if (activities.length === 0) {
    return (
      <p className="text-xs text-content-tertiary text-center py-4">
        {t('dashboard.no_activity', { defaultValue: 'No recent activity' })}
      </p>
    );
  }

  return (
    <div className="space-y-1">
      {activities.map((a, i) => {
        const meta = actionMeta(a.action);
        const projName = a.project_id ? projectMap[a.project_id] : null;
        return (
          <button
            key={`${a.id}-${i}`}
            onClick={() => a.project_id ? navigate(`/projects/${a.project_id}`) : undefined}
            className="flex items-center gap-3 w-full text-left px-2 py-1.5 rounded-lg hover:bg-surface-secondary transition-colors group"
          >
            <div className={`flex h-6 w-6 items-center justify-center rounded-md shrink-0 ${meta.bg} ${meta.fg}`}>
              {meta.icon}
            </div>
            <div className="flex-1 min-w-0">
              <span className="text-xs font-medium text-content-primary truncate block group-hover:text-oe-blue transition-colors">
                {a.description}
              </span>
              <span className="text-2xs text-content-tertiary">
                {projName && <>{projName} · </>}
                {formatRelativeTime(a.created_at, i18n.language)}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** Format a date as relative time (e.g. "2 hours ago") */
function formatRelativeTime(dateStr: string, locale: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diffMs = now - date;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  try {
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (diffMin < 1) return rtf.format(0, 'second');
    if (diffMin < 60) return rtf.format(-diffMin, 'minute');
    if (diffHr < 24) return rtf.format(-diffHr, 'hour');
    if (diffDay < 30) return rtf.format(-diffDay, 'day');
    return new Date(dateStr).toLocaleDateString(locale);
  } catch {
    return new Date(dateStr).toLocaleDateString(locale);
  }
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
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
  ClipboardList,
  MessageSquare,
  HardHat,
  Percent,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, Skeleton, InfoHint, ActivityFeed as CrossModuleActivityFeed } from '@/shared/ui';
import BIMCoverageCard from './BIMCoverageCard';
import { DateDisplay } from '@/shared/ui/DateDisplay';

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
  const totalBudgetFormatted = analytics.total_planned >= 1_000_000
    ? `${(analytics.total_planned / 1_000_000).toFixed(1)}M`
    : analytics.total_planned >= 1_000
      ? `${(analytics.total_planned / 1_000).toFixed(0)}K`
      : analytics.total_planned.toLocaleString();

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
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 transition-transform group-hover:scale-110">
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

const STATUS_INDICATOR_COLORS: Record<string, string> = {
  active: '#16a34a',
  draft: '#2563eb',
  archived: '#6b7280',
  template: '#7c3aed',
};

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

  const formatValue = (value: number, currency: string) => {
    const symbol =
      currency === 'EUR' ? '\u20AC' :
      currency === 'GBP' ? '\u00A3' :
      currency === 'USD' ? '$' :
      currency === 'AED' ? 'AED ' :
      `${currency} `;
    if (value >= 1_000_000) return `${symbol}${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${symbol}${(value / 1_000).toFixed(1)}K`;
    if (value > 0)
      return `${symbol}${value.toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      })}`;
    return `${symbol}0`;
  };

  return (
    <div className="animate-card-in" style={{ animationDelay: '130ms' }}>
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cards.slice(0, 6).map((card, index) => {
          const indicatorColor = STATUS_INDICATOR_COLORS[card.status] || '#6b7280';
          const hasProgress = card.progress_pct > 0;
          const hasSafetyAlert = card.safety_incidents > 0;

          return (
            <button
              key={card.id}
              onClick={() => navigate(`/projects/${card.id}`)}
              className="group relative flex flex-col rounded-xl border border-border-light bg-surface-primary p-5 text-left transition-all duration-normal ease-oe hover:border-oe-blue/30 hover:shadow-md animate-stagger-in"
              style={{ animationDelay: `${150 + index * 60}ms` }}
            >
              {/* Status indicator dot */}
              <div className="absolute top-4 right-4 flex items-center gap-1.5">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: indicatorColor }}
                  title={card.status}
                />
                <ArrowRight
                  size={14}
                  className="text-content-quaternary opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-normal"
                />
              </div>

              {/* Project name + initial badge */}
              <div className="flex items-start gap-3 mb-3 pr-10">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue text-sm font-bold transition-transform group-hover:scale-105">
                  {card.name.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h4 className="text-sm font-semibold text-content-primary truncate leading-snug">
                    {card.name}
                  </h4>
                  <p className="text-2xs text-content-tertiary truncate mt-0.5">
                    {card.description ||
                      [card.classification_standard?.toUpperCase(), card.region, card.currency]
                        .filter(Boolean)
                        .join(' \u00B7 ')}
                  </p>
                </div>
              </div>

              {/* Progress bar (if schedule data exists) */}
              {hasProgress && (
                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-2xs text-content-tertiary">
                      {t('dashboard.card_progress', { defaultValue: 'Progress' })}
                    </span>
                    <span className="text-2xs font-semibold tabular-nums text-content-secondary">
                      {card.progress_pct}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-surface-secondary overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500 ease-out"
                      style={{
                        width: `${Math.min(card.progress_pct, 100)}%`,
                        background:
                          card.progress_pct >= 80
                            ? '#16a34a'
                            : card.progress_pct >= 40
                              ? '#2563eb'
                              : '#ca8a04',
                      }}
                    />
                  </div>
                </div>
              )}

              {/* KPI chips */}
              <div className="flex flex-wrap gap-2 mt-auto">
                {/* BOQ Total Value */}
                <div
                  className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue-subtle/60 px-2.5 py-1.5 text-2xs font-medium text-oe-blue"
                  title={t('dashboard.card_boq_value', { defaultValue: 'BOQ Total Value' })}
                >
                  <DollarSign size={12} strokeWidth={2} />
                  <span className="tabular-nums">{formatValue(card.boq_total_value, card.currency)}</span>
                </div>

                {/* Open Tasks */}
                <div
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-2xs font-medium ${
                    card.open_tasks > 0
                      ? 'bg-[#7c3aed]/10 text-[#7c3aed]'
                      : 'bg-surface-secondary text-content-tertiary'
                  }`}
                  title={t('dashboard.card_open_tasks', { defaultValue: 'Open Tasks' })}
                >
                  <ClipboardList size={12} strokeWidth={2} />
                  <span className="tabular-nums">{card.open_tasks}</span>
                </div>

                {/* Open RFIs */}
                <div
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-2xs font-medium ${
                    card.open_rfis > 0
                      ? 'bg-[#0891b2]/10 text-[#0891b2]'
                      : 'bg-surface-secondary text-content-tertiary'
                  }`}
                  title={t('dashboard.card_open_rfis', { defaultValue: 'Open RFIs' })}
                >
                  <MessageSquare size={12} strokeWidth={2} />
                  <span className="tabular-nums">{card.open_rfis}</span>
                </div>

                {/* Safety Incidents */}
                <div
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-2xs font-medium ${
                    hasSafetyAlert
                      ? 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400'
                      : 'bg-surface-secondary text-content-tertiary'
                  }`}
                  title={t('dashboard.card_safety', { defaultValue: 'Safety Incidents' })}
                >
                  <HardHat size={12} strokeWidth={2} />
                  <span className="tabular-nums">{card.safety_incidents}</span>
                </div>

                {/* Schedule Progress (compact chip, shown if progress exists) */}
                {hasProgress && (
                  <div
                    className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-2xs font-medium ${
                      card.progress_pct >= 80
                        ? 'bg-[#16a34a]/10 text-[#16a34a]'
                        : card.progress_pct >= 40
                          ? 'bg-[#2563eb]/10 text-[#2563eb]'
                          : 'bg-[#ca8a04]/10 text-[#ca8a04]'
                    }`}
                    title={t('dashboard.card_schedule_progress', { defaultValue: 'Schedule Progress' })}
                  >
                    <Percent size={12} strokeWidth={2} />
                    <span className="tabular-nums">{card.progress_pct}%</span>
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
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

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => fetch('/api/system/modules').then((r) => r.json()),
    retry: false,
    staleTime: 60_000,
  });

  const { data: usersList } = useQuery({
    queryKey: ['dashboard-users-count'],
    queryFn: () => apiGet<{ id: string }[]>('/v1/users/').catch(() => []),
    retry: false,
    staleTime: 60_000,
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
    },
    {
      icon: <FileSpreadsheet size={12} strokeWidth={2} />,
      value: boqCount,
      label: t('dashboard.ss_boqs', { defaultValue: 'BOQs' }),
      color: 'text-[#7c3aed]',
      bg: 'bg-[#7c3aed]/10',
    },
    {
      icon: <Cpu size={12} strokeWidth={2} />,
      value: moduleCount,
      label: t('dashboard.ss_modules', { defaultValue: 'Modules' }),
      color: 'text-[#0891b2]',
      bg: 'bg-[#0891b2]/10',
    },
    {
      icon: <Users size={12} strokeWidth={2} />,
      value: userCount,
      label: t('dashboard.ss_users', { defaultValue: 'Users' }),
      color: 'text-[#16a34a]',
      bg: 'bg-[#16a34a]/10',
    },
  ];

  return (
    <div
      className="flex flex-wrap items-center gap-2 animate-card-in"
      style={{ animationDelay: '40ms' }}
    >
      {badges.map((b) => (
        <div
          key={b.label}
          className={`inline-flex items-center gap-1.5 rounded-lg ${b.bg} px-2.5 py-1.5 transition-colors`}
        >
          <span className={b.color}>{b.icon}</span>
          <span className={`text-xs font-bold tabular-nums ${b.color}`}>{b.value}</span>
          <span className="text-2xs text-content-tertiary">{b.label}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Quick Upload Card ────────────────────────────────────────────────── */

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100 MB

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

      const oversized = fileArray.filter((f) => f.size > MAX_UPLOAD_BYTES);
      if (oversized.length > 0) {
        addToast({
          type: 'warning',
          title: t('dashboard.upload_too_large', { defaultValue: 'Files too large' }),
          message: t('dashboard.upload_too_large_desc', {
            defaultValue:
              '{{count}} file(s) exceed 100 MB and were skipped: {{names}}',
            count: oversized.length,
            names: oversized.map((f) => f.name).join(', '),
          }),
        });
      }

      const validFiles = fileArray.filter((f) => f.size <= MAX_UPLOAD_BYTES);
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
                    defaultValue: 'Upload to {{project}} — PDF, DWG, IFC, RVT, images (max 100 MB).',
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
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  // First launch: redirect to onboarding wizard
  useEffect(() => {
    try {
      if (localStorage.getItem('oe_onboarding_completed') !== 'true') {
        navigate('/onboarding', { replace: true });
      }
    } catch { /* storage unavailable */ }
  }, [navigate]);

  const [showAllActivity, setShowAllActivity] = useState(false);

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/').catch(() => []),
    retry: false,
    staleTime: 5 * 60_000,
  });

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

  // Fetch contacts count for NextSteps suggestions
  const { data: contactsList } = useQuery({
    queryKey: ['dashboard-contacts-count'],
    queryFn: () => apiGet<{ id: string }[]>('/v1/contacts/').catch(() => []),
    retry: false,
    staleTime: 60_000,
  });
  const contactsCount = contactsList?.length ?? 0;

  // Determine the most recently updated BOQ for "Continue your work"
  const lastBoq = useMemo(() => {
    if (!allBoqs || allBoqs.length === 0) return null;
    // Sort by updated_at descending (most recent first)
    const sorted = [...allBoqs].sort((a, b) => {
      const da = new Date((a as unknown as { updated_at?: string }).updated_at ?? 0).getTime();
      const db = new Date((b as unknown as { updated_at?: string }).updated_at ?? 0).getTime();
      return db - da;
    });
    const picked = sorted[0]!;
    const project = projects?.find((p) => p.id === picked.project_id);
    return {
      id: picked.id,
      name: picked.name,
      status: picked.status,
      projectName: project?.name ?? '',
      positionCount: (picked as unknown as { position_count?: number }).position_count ?? 0,
      grandTotal: (picked as unknown as { grand_total?: number }).grand_total ?? 0,
      currency: project?.currency ?? 'EUR',
      updatedAt: (picked as unknown as { updated_at?: string }).updated_at,
    };
  }, [allBoqs, projects]);

  return (
    <div className="space-y-5 animate-fade-in pt-4">
      {/* ─── 1. Hero row ─────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between animate-card-in">
        <div>
          <h1 className="text-3xl font-bold tracking-tight gradient-text">
            {t('dashboard.welcome')}
          </h1>
          <a
            href="https://datadrivenconstruction.io/?utm_source=erp"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 mt-2.5 animate-stagger-in group/ddc"
            style={{ animationDelay: '100ms' }}
          >
            <img
              src="https://datadrivenconstruction.io/wp-content/uploads/2023/07/DataDrivenConstruction-1-1.png.webp"
              alt="DataDrivenConstruction"
              className="h-[34px] w-auto opacity-75 group-hover/ddc:opacity-100 transition-opacity shrink-0"
            />
            <div className="flex flex-col leading-tight">
              <span className="text-xs font-semibold text-content-secondary">
                {t('dashboard.subtitle')}
              </span>
              <span className="text-[11px] text-content-tertiary">
                {t('dashboard.subtitle_2', { defaultValue: 'Smart resource planning for your construction projects' })}
              </span>
            </div>
          </a>
        </div>
        <div className="flex items-center gap-2 animate-stagger-in" style={{ animationDelay: '150ms' }}>
          <Button
            variant="primary"
            size="lg"
            icon={<FolderPlus size={18} />}
            onClick={() => navigate('/projects/new')}
            className="btn-shimmer"
          >
            {t('projects.new_project')}
          </Button>
          <Button
            variant="secondary"
            size="lg"
            icon={<Sparkles size={14} />}
            onClick={async () => {
              try {
                const proj = await apiPost<{id:string}>('/v1/projects/', {
                  name: `Estimate ${new Date().toLocaleDateString()}`,
                  region: 'DACH', currency: 'EUR', classification_standard: 'din276',
                });
                const boq = await apiPost<{id:string}>('/v1/boq/boqs/', {
                  project_id: proj.id, name: 'Bill of Quantities',
                });
                navigate(`/boq/${boq.id}`);
              } catch {
                addToast({ type: 'error', title: t('dashboard.quick_start_failed', { defaultValue: 'Failed to create quick start estimate' }) });
              }
            }}
          >
            {t('dashboard.quick_start', { defaultValue: 'Quick Start' })}
          </Button>
        </div>
      </div>

      {/* ─── 2. Stats row ────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Open-source badge */}
        <a
          href="https://github.com/datadrivenconstruction/OpenConstructionERP"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2.5 rounded-xl bg-gradient-to-r from-oe-blue/8 via-violet-500/8 to-emerald-500/8 border border-oe-blue/15 py-1.5 px-3 hover:shadow-md hover:border-oe-blue/30 transition-all animate-stagger-in shrink-0"
          style={{ animationDelay: '200ms' }}
        >
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
          </span>
          <span className="text-sm font-bold bg-gradient-to-r from-oe-blue via-violet-600 to-emerald-600 bg-clip-text text-transparent">
            {t('dashboard.open_source_erp', { defaultValue: 'Erste Open-Source Bau-ERP' })}
          </span>
          <ExternalLink size={12} className="text-oe-blue opacity-50 shrink-0" />
        </a>
        {/* Stat pills */}
        <SystemStatusSummary projects={projects} boqs={allBoqs} />
      </div>
      <InfoHint text={t('dashboard.kpi_hint', { defaultValue: 'Summary across all projects. Values update as you add estimates and schedule activities.' })} />

      {/* ─── 3. Continue Your Work — full-width banner ────────────────── */}
      {lastBoq && (
        <div
          className="group relative overflow-hidden rounded-xl border-2 border-oe-blue/30 bg-gradient-to-br from-oe-blue-subtle/40 via-surface-elevated to-violet-500/5 p-5 cursor-pointer hover:border-oe-blue/60 hover:shadow-lg transition-all animate-card-in"
          style={{ animationDelay: '60ms' }}
          onClick={() => navigate(`/boq/${lastBoq.id}`)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/boq/${lastBoq.id}`); }}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-2xs font-semibold text-oe-blue uppercase tracking-wider">
                  {t('dashboard.continue_work', { defaultValue: 'Continue your work' })}
                </span>
                <span className="text-2xs text-content-quaternary">&middot;</span>
                <span className="text-2xs text-content-tertiary">
                  {lastBoq.status === 'draft' ? t('boq.status_draft', { defaultValue: 'Draft' }) : lastBoq.status}
                </span>
              </div>
              <h2 className="text-lg font-bold text-content-primary truncate">{lastBoq.name}</h2>
              {lastBoq.projectName && (
                <p className="text-xs text-content-tertiary truncate mt-0.5">{lastBoq.projectName}</p>
              )}
              <div className="mt-3 flex items-center gap-4 text-xs text-content-secondary">
                {lastBoq.positionCount > 0 && (
                  <span className="tabular-nums">
                    <strong className="text-content-primary">{lastBoq.positionCount}</strong> {t('boq.positions', { defaultValue: 'positions' })}
                  </span>
                )}
                {lastBoq.grandTotal > 0 && (
                  <span className="tabular-nums">
                    <strong className="text-content-primary">{lastBoq.currency} {lastBoq.grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
                  </span>
                )}
              </div>
            </div>
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue text-white shadow-md group-hover:scale-110 transition-transform">
              <ArrowRight size={22} />
            </div>
          </div>
        </div>
      )}

      {/* ─── 4. KPI Ribbon ───────────────────────────────────────────── */}
      <KpiRibbon boqs={allBoqs} schedules={allSchedules} projects={projects} />

      {/* ─── 4. Project Cards (primary content) ──────────────────────── */}
      <ProjectMetricCards cards={projectCards} loading={cardsLoading} />

      {/* Fallback project list when no metric cards available */}
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

      {/* ─── 5. Portfolio Overview (multi-project users) ─────────────── */}
      {projects && projects.length > 1 && (
        <PortfolioOverview projects={projects} />
      )}

      {/* ─── 6. BIM Coverage ─────────────────────────────────────────── */}
      <BIMCoverageCard />

      {/* ─── 6b. Quick Upload ─────────────────────────────────────────── */}
      <QuickUploadCard />

      {/* ─── 7. Getting Started (onboarding — hidden once all done) ─── */}
      <OnboardingSteps projects={projects} regionStats={regionStats} boqs={allBoqs} vectorCount={vectorCount} />

      {/* ─── 8. Context-aware suggestions ────────────────────────────── */}
      <NextSteps
        projects={projects}
        boqs={allBoqs}
        schedules={allSchedules}
        allContacts={contactsCount}
      />

      {/* ─── 9. Analytics + Activity + System Status ─────────────────── */}
      {projects && projects.length > 0 && (
        <div className="animate-card-in" style={{ animationDelay: '350ms' }}>
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 size={18} className="text-content-tertiary" strokeWidth={1.75} />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('dashboard.analytics', { defaultValue: 'Analytics' })}
            </h2>
          </div>
          <AnalyticsSection projects={projects} />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {projects && projects.length > 0 && (
          <div className="lg:col-span-2 animate-card-in" style={{ animationDelay: '400ms' }}>
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
        <div className={`${projects && projects.length > 0 ? 'lg:col-start-3' : ''} animate-card-in`} style={{ animationDelay: '450ms' }}>
          <Card className="h-full">
            <CardHeader title={t('dashboard.system_status')} />
            <CardContent>
              <SystemStatus />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ── Projects List ────────────────────────────────────────────────────── */

function ProjectsList({ projects }: { projects?: ProjectSummary[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const installDemoMutation = useMutation({
    mutationFn: () => apiPost<DemoInstallResult>('/demo/install/residential-berlin'),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${result.project_id}`);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('demo.install_failed', { defaultValue: 'Failed to install demo' }), message: err.message });
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
          {modules?.modules?.length ?? '\u2014'}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '700ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.validation_rules')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {rules?.rules?.length ?? '\u2014'}
        </span>
      </div>
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '760ms' }}
      >
        <span className="text-sm text-content-secondary">{t('dashboard.languages')}</span>
        <span className="text-sm font-semibold text-content-primary tabular-nums">{SUPPORTED_LANGUAGES.length}</span>
      </div>
    </div>
  );
}

/* ── Activity Feed ───────────────────────────────────────────────────── */

/* ActivityFeed is now provided by @/shared/ui/ActivityFeed (cross-module, audit-log-based) */

import React, { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '@/app/i18n';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Table2,
  DollarSign,
  Layers,
  ShieldCheck,
  Upload,
  FileSpreadsheet,
  X,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Clock,
  Sparkles,
  CalendarClock,
  Wallet,
  Gavel,
  RefreshCw,
  Plus,
  ExternalLink,
  Pencil,
  Save,
  LayoutDashboard,
  MessageSquare,
  FileCheck,
  Package,
  Activity,
  ClipboardList,
  FolderOpen,
  HardHat,
  Calendar,
  Image as ImageIcon,
  LayoutGrid,
  Receipt,
} from 'lucide-react';
import {
  Button, Card, CardHeader, CardContent, Badge, Skeleton, EmptyState, Breadcrumb,
  ProjectMap, ProjectWeather,
} from '@/shared/ui';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { ProjectLayoutManager } from './ProjectLayoutManager';
import { useProjectDetailLayoutStore } from '@/stores/useProjectDetailLayoutStore';
import {
  RFIInboxWidget,
  ChangeOrdersPulseWidget,
  DailyDiaryWidget,
  HSEIncidentsWidget,
  VariationsWidget,
  AIInsightsWidget,
  RecentFilesWidget,
  PhotoStripWidget,
  ActivityFeedWidget,
  QualityNCRWidget,
  BudgetBurnWidget,
  ComplianceSummaryWidget,
  ScheduleStripWidget,
  ProjectWidgetsRollupProvider,
} from './components/ProjectWidgets';
import { useWidgetSettingsStore } from '@/stores/useWidgetSettingsStore';
import { apiGet, apiPatch, ApiError, extractErrorMessageFromBody } from '@/shared/lib/api';
import clsx from 'clsx';
import { projectsApi, type Project } from './api';
import { PhotosTab } from './PhotosTab';
import { CompliancePage } from '@/features/compliance-docs/CompliancePage';
import { TeamStrip } from './components/TeamStrip';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useRecentStore } from '@/stores/useRecentStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BOQSummary {
  id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface BOQDetail {
  id: string;
  name: string;
  description: string;
  status: string;
  positions: PositionSummary[];
  grand_total: number;
  created_at: string;
  updated_at: string;
}

interface PositionSummary {
  id: string;
  description: string;
  quantity: number;
  unit_rate: number;
  total: number;
  validation_status: string;
}

interface ImportResult {
  imported: number;
  skipped?: number;
  errors: { row?: number; item?: string; error: string; data?: Record<string, string> }[];
  total_rows?: number;
  total_items?: number;
  method?: 'direct' | 'ai' | 'cad_ai';
  model_used?: string | null;
  cad_format?: string;
  cad_elements?: number;
}

// ---------------------------------------------------------------------------
// Tab types
// ---------------------------------------------------------------------------

type ProjectTab = 'dashboard' | 'overview' | 'schedule' | 'budget' | 'tendering' | 'photos' | 'compliance';

interface ScheduleItem {
  id: string;
  name: string;
  status: string;
  created_at: string;
}

interface BudgetDashboard {
  total_budget: number;
  total_committed: number;
  total_actual: number;
  total_forecast: number;
  variance: number;
  variance_pct: number;
  spi: number;
  cpi: number;
  status: string;
  currency: string;
  // Legacy fields (may be absent depending on API version)
  total_spent?: number;
  remaining?: number;
  items?: { name: string; planned: number; actual: number }[];
}

interface TenderPackage {
  id: string;
  name: string;
  status: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getAuthHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchBoqs(projectId: string): Promise<BOQSummary[]> {
  try {
    return await apiGet<BOQSummary[]>(`/v1/boq/boqs/?project_id=${projectId}`);
  } catch {
    return [];
  }
}

async function fetchBoqDetail(boqId: string): Promise<BOQDetail> {
  return apiGet<BOQDetail>(`/v1/boq/boqs/${boqId}`);
}

async function smartImportFile(boqId: string, file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api/v1/boq/boqs/${boqId}/import/smart/`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(extractErrorMessageFromBody(body) ?? 'Import failed');
  }
  return res.json();
}

function formatCurrency(value: number, currency?: string): string {
  // Strict-currency policy (mirrors <MoneyDisplay>): never guess EUR when
  // the project has no currency configured, which would silently mislabel
  // a Saudi/UK/US project's money in Euros. Surface an em-dash instead so
  // the configuration gap is visible.
  const trimmed = typeof currency === 'string' ? currency.trim() : '';
  if (!/^[A-Z]{3}$/.test(trimmed)) {
    return '—';
  }
  try {
    return new Intl.NumberFormat(i18n.language, {
      style: 'currency',
      currency: trimmed,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${trimmed}`;
  }
}

function formatDate(iso: string, locale = 'en-US'): string {
  return new Date(iso).toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

const statusVariant: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  active: 'blue',
  final: 'success',
  archived: 'warning',
};

const standardLabels: Record<string, string> = {
  din276: 'DIN 276',
  nrm: 'NRM',
  masterformat: 'MasterFormat',
};

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

interface HealthCheck {
  key: string;
  label: string;
  done: boolean;
}

interface NextStep {
  label: string;
  description: string;
  to: string;
  variant: 'primary' | 'success';
}

/**
 * Compute project health checkpoints + the most relevant "next step" to take.
 *
 * Checkpoints (in execution order — done from top to bottom):
 *   1. has_boq            — at least one BOQ exists
 *   2. has_positions      — at least one BOQ has positions
 *   3. all_priced         — every position has a non-zero unit_rate
 *   4. validation_run     — validation has been run on at least one position
 *   5. no_errors          — no positions have validation_status === 'error'
 *
 * `nextStep` always points at the FIRST incomplete checkpoint, so the user
 * always has a clear, single action to take next.
 */
function computeProjectHealth(
  projectId: string,
  boqs: BOQSummary[] | undefined,
  boqDetails: BOQDetail[] | undefined,
  t: ReturnType<typeof useTranslation>['t'],
): { checks: HealthCheck[]; nextStep: NextStep | null; completeness: number } {
  // Find the largest BOQ to use as the deep-link target for "next step" actions
  const largestBoq =
    boqDetails && boqDetails.length > 0
      ? [...boqDetails].sort((a, b) => b.positions.length - a.positions.length)[0]
      : null;

  let unpricedCount = 0;
  let errorCount = 0;
  let validatedCount = 0;
  let totalPositions = 0;

  if (boqDetails) {
    for (const detail of boqDetails) {
      for (const pos of detail.positions) {
        totalPositions++;
        if (!pos.unit_rate || pos.unit_rate === 0) unpricedCount++;
        if (pos.validation_status === 'error') errorCount++;
        if (pos.validation_status && pos.validation_status !== 'pending') {
          validatedCount++;
        }
      }
    }
  }

  const hasBoq = (boqs?.length ?? 0) > 0;
  const hasPositions = totalPositions > 0;
  const allPriced = hasPositions && unpricedCount === 0;
  const validationRun = validatedCount > 0;
  const noErrors = validationRun && errorCount === 0;

  const checks: HealthCheck[] = [
    { key: 'has_boq', label: t('projects.health_has_boq', { defaultValue: 'BOQ created' }), done: hasBoq },
    { key: 'has_positions', label: t('projects.health_has_positions', { defaultValue: 'Positions added' }), done: hasPositions },
    { key: 'all_priced', label: t('projects.health_all_priced', { defaultValue: 'All positions priced' }), done: allPriced },
    { key: 'validation_run', label: t('projects.health_validation_run', { defaultValue: 'Validation run' }), done: validationRun },
    { key: 'no_errors', label: t('projects.health_no_errors', { defaultValue: 'No validation errors' }), done: noErrors },
  ];

  const doneCount = checks.filter((c) => c.done).length;
  const completeness = doneCount / checks.length;

  // Pick the next step from the first incomplete check
  let nextStep: NextStep | null = null;
  if (!hasBoq) {
    nextStep = {
      label: t('projects.health_action_create_boq', { defaultValue: 'Create BOQ' }),
      description: t('projects.health_next_create_boq', {
        defaultValue: 'Start by creating your first Bill of Quantities for this project.',
      }),
      to: `/projects/${projectId}/boq/new`,
      variant: 'primary',
    };
  } else if (!hasPositions && largestBoq) {
    nextStep = {
      label: t('projects.health_action_add_positions', { defaultValue: 'Add positions' }),
      description: t('projects.health_next_add_positions', {
        defaultValue: 'Open the BOQ editor and add your first positions - manually, from Excel, or with AI.',
      }),
      to: `/boq/${largestBoq.id}`,
      variant: 'primary',
    };
  } else if (!allPriced && largestBoq) {
    nextStep = {
      label: t('projects.health_action_price_positions', {
        defaultValue: 'Price {{count}} positions',
        count: unpricedCount,
      }),
      description: t('projects.health_next_price_positions', {
        defaultValue: '{{count}} positions are missing unit rates. Add prices manually or pick from the cost catalog.',
        count: unpricedCount,
      }),
      to: `/boq/${largestBoq.id}`,
      variant: 'primary',
    };
  } else if (!validationRun) {
    nextStep = {
      label: t('projects.health_action_run_validation', { defaultValue: 'Run validation' }),
      description: t('projects.health_next_run_validation', {
        defaultValue: 'Check your BOQ against classification and quality rules to catch issues early.',
      }),
      to: '/validation',
      variant: 'primary',
    };
  } else if (!noErrors) {
    nextStep = {
      label: t('projects.health_action_fix_errors', {
        defaultValue: 'Fix {{count}} errors',
        count: errorCount,
      }),
      description: t('projects.health_next_fix_errors', {
        defaultValue: '{{count}} positions have validation errors. Resolve them to clean the project.',
        count: errorCount,
      }),
      to: '/validation',
      variant: 'primary',
    };
  } else {
    nextStep = {
      label: t('projects.health_action_export', { defaultValue: 'Export & report' }),
      description: t('projects.health_next_export', {
        defaultValue: 'Project is ready. Export to GAEB, Excel, or PDF - or distribute as a tender package.',
      }),
      to: '/reports',
      variant: 'success',
    };
  }

  return { checks, nextStep, completeness };
}

/**
 * Compact health bar shown above the project summary cards.
 *
 * One row, dense, action-oriented. Shows the user instantly:
 *   - "How complete is this project?" (progress bar + percentage)
 *   - "What should I do next?" (one prominent button + description)
 *   - "Where am I in the workflow?" (5 checkpoint dots, hover for label)
 */
/* Construction lifecycle phases — canonical 5-step ribbon. We compare
   the project's free-text `phase` to known tokens case-insensitively so a
   project saved as "Construction" or "construction-phase" still highlights
   the right step. Unmatched values fall back to a single chip. */
const PHASE_STEPS = [
  { key: 'planning', match: ['planning', 'pre', 'feasibility'] },
  { key: 'design', match: ['design', 'concept', 'detailed'] },
  { key: 'procurement', match: ['procurement', 'tender', 'bidding'] },
  { key: 'construction', match: ['construction', 'execution', 'build'] },
  { key: 'closeout', match: ['closeout', 'handover', 'commission', 'turnover'] },
] as const;

function ProjectPhaseRibbon({ phase }: { phase: string | null }) {
  const { t } = useTranslation();
  if (!phase || !phase.trim()) return null;

  const norm = phase.toLowerCase();
  const activeIdx = PHASE_STEPS.findIndex((s) => s.match.some((m) => norm.includes(m)));

  // Unknown phase — show single chip instead of a fake stepper.
  if (activeIdx < 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs">
        <span className="font-medium uppercase tracking-wider text-content-tertiary">
          {t('projects.phase_label', { defaultValue: 'Phase' })}
        </span>
        <span className="font-semibold text-content-primary">{phase}</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
      <div className="flex items-center gap-1.5 overflow-x-auto">
        {PHASE_STEPS.map((step, idx) => {
          const isActive = idx === activeIdx;
          const isPast = idx < activeIdx;
          const label = t(`projects.phase_${step.key}`, {
            defaultValue: step.key.charAt(0).toUpperCase() + step.key.slice(1),
          });
          return (
            <React.Fragment key={step.key}>
              <div className="flex items-center gap-1.5 shrink-0">
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold tabular-nums ${
                    isActive
                      ? 'bg-oe-blue text-white ring-2 ring-oe-blue/30'
                      : isPast
                        ? 'bg-oe-blue/20 text-oe-blue'
                        : 'bg-surface-tertiary text-content-quaternary'
                  }`}
                  aria-current={isActive ? 'step' : undefined}
                >
                  {isPast ? '✓' : idx + 1}
                </span>
                <span
                  className={`text-xs font-medium whitespace-nowrap ${
                    isActive
                      ? 'text-content-primary'
                      : isPast
                        ? 'text-content-secondary'
                        : 'text-content-quaternary'
                  }`}
                >
                  {label}
                </span>
              </div>
              {idx < PHASE_STEPS.length - 1 && (
                <div
                  className={`h-px flex-1 min-w-[12px] ${
                    idx < activeIdx ? 'bg-oe-blue/40' : 'bg-border-light'
                  }`}
                  aria-hidden="true"
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

/**
 * ProjectLocationPanel — full-width panel combining an interactive OSM
 * map (left, 60%) with an 18-day weather forecast (right, 40%).  Each
 * half is independently toggleable via widget settings, and the panel
 * collapses entirely if the project has no address and both widgets
 * are off.
 */
function ProjectLocationPanel({ project }: { project: Project }) {
  const mapEnabled = useWidgetSettingsStore((s) => s.projectMapEnabled);
  const weatherEnabled = useWidgetSettingsStore((s) => s.projectWeatherEnabled);
  const queryClient = useQueryClient();
  const [resolved, setResolved] = useState<{ lat: number; lng: number } | null>(
    project.address?.lat && project.address?.lng
      ? { lat: project.address.lat, lng: project.address.lng }
      : null,
  );

  // Persist the resolved lat/lng back to the project so subsequent
  // renders (and other users of the same project) don't re-hit
  // Nominatim.  Only fires when we have an address but no stored
  // coords yet, and stops after the first successful write.
  const [persisted, setPersisted] = useState(
    !!(project.address?.lat && project.address?.lng),
  );
  const persistCoords = useMutation({
    mutationFn: (coords: { lat: number; lng: number }) =>
      apiPatch(`/v1/projects/${project.id}`, {
        address: {
          ...(project.address ?? {}),
          lat: coords.lat,
          lng: coords.lng,
        },
      }),
    onSuccess: () => {
      setPersisted(true);
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const hasAddress = !!(
    project.address &&
    (project.address.street || project.address.city || project.address.country)
  );

  if (!hasAddress || (!mapEnabled && !weatherEnabled)) return null;

  const addressLabel = [
    project.address?.street,
    project.address?.city,
    project.address?.country,
  ]
    .filter(Boolean)
    .join(', ');

  const handleResolved = (coords: { lat: number; lng: number }) => {
    setResolved(coords);
    if (!persisted && !persistCoords.isPending) {
      persistCoords.mutate(coords);
    }
  };

  return (
    <div
      className={clsx(
        'grid gap-3 items-stretch',
        mapEnabled && weatherEnabled
          ? 'grid-cols-1 lg:grid-cols-[3fr_2fr]'
          : 'grid-cols-1',
      )}
    >
      {mapEnabled && (
        <ProjectMap
          variant="detail"
          lat={project.address?.lat ?? null}
          lng={project.address?.lng ?? null}
          address={project.address?.street}
          city={project.address?.city}
          country={project.address?.country}
          label={addressLabel}
          onResolved={handleResolved}
          className={clsx(
            // When weather is also visible, let the grid stretch the map
            // to match the (now 3-row) weather block. When the map is
            // shown alone, fall back to a fixed height so it doesn't
            // collapse to zero.
            weatherEnabled ? 'h-full min-h-[20rem]' : 'h-[32rem]',
          )}
        />
      )}
      {weatherEnabled && (
        <ProjectWeather lat={resolved?.lat} lng={resolved?.lng} />
      )}
    </div>
  );
}

function ProjectHealthBar({
  projectId,
  boqs,
  boqDetails,
}: {
  projectId: string;
  boqs: BOQSummary[] | undefined;
  boqDetails: BOQDetail[] | undefined;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { checks, nextStep, completeness } = useMemo(
    () => computeProjectHealth(projectId, boqs, boqDetails, t),
    [projectId, boqs, boqDetails, t],
  );

  const doneCount = checks.filter((c) => c.done).length;
  const isComplete = completeness === 1;
  const percent = Math.round(completeness * 100);

  // Color-code the progress ring based on completeness
  const ringColor = isComplete
    ? 'text-emerald-500'
    : completeness >= 0.6
    ? 'text-oe-blue'
    : 'text-amber-500';

  return (
    <Card padding="md" className="h-full flex flex-col justify-center">
      <div className="flex items-center gap-5">
        {/* Circular progress ring */}
        <div className="relative shrink-0">
          <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64">
            <circle
              cx="32"
              cy="32"
              r="28"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              className="text-surface-secondary"
            />
            <circle
              cx="32"
              cy="32"
              r="28"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${completeness * 175.93} 175.93`}
              className={`transition-all duration-500 ${ringColor}`}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-sm font-bold text-content-primary tabular-nums">{percent}%</span>
          </div>
        </div>

        {/* Text + checkpoints */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('projects.health_label', { defaultValue: 'Project Health' })}
            </span>
            <span className="text-2xs text-content-quaternary">·</span>
            <span className="text-2xs text-content-tertiary tabular-nums">
              {doneCount}/{checks.length} {t('projects.health_complete', { defaultValue: 'complete' })}
            </span>
          </div>
          {nextStep && (
            <p className="text-sm text-content-primary truncate">
              <span className="font-semibold">
                {t('projects.health_next', { defaultValue: 'Next:' })}
              </span>{' '}
              <span className="text-content-secondary">{nextStep.description}</span>
            </p>
          )}
          {/* Checkpoint dots — hover shows label */}
          <div className="mt-2 flex items-center gap-1.5">
            {checks.map((check) => (
              <div
                key={check.key}
                title={check.label + (check.done ? ' (done)' : '')}
                className={`h-1.5 flex-1 max-w-[60px] rounded-full transition-colors ${
                  check.done ? (isComplete ? 'bg-emerald-500' : 'bg-oe-blue') : 'bg-surface-secondary'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Next action button */}
        {nextStep && (
          <Button
            variant={nextStep.variant === 'success' ? 'secondary' : 'primary'}
            size="sm"
            onClick={() => navigate(nextStep.to)}
            className="shrink-0"
          >
            {nextStep.label}
          </Button>
        )}
      </div>
    </Card>
  );
}

function SummaryCard({
  label,
  value,
  icon,
  variant = 'default',
  subtitle,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  variant?: 'default' | 'success' | 'blue';
  subtitle?: string;
}) {
  const bgMap = {
    default: 'bg-surface-secondary text-content-tertiary',
    success: 'bg-semantic-success-bg text-semantic-success',
    blue: 'bg-oe-blue-subtle text-oe-blue-text',
  };

  return (
    <div className="flex-1 min-w-[180px] rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide truncate">
            {label}
          </p>
          <p className="mt-0.5 text-xl font-bold text-content-primary tabular-nums leading-tight">
            {value}
          </p>
          {subtitle && (
            <p className="text-2xs text-content-secondary tabular-nums truncate">{subtitle}</p>
          )}
        </div>
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${bgMap[variant]}`}
        >
          {icon}
        </div>
      </div>
    </div>
  );
}

/**
 * WidgetSection — a labelled group of project-overview cards.
 *
 * The /projects/:id pulse widgets used to render in one flat 4-column grid
 * where a few cards forced ``col-span-2`` / full-row spans. That left ragged
 * rows with big empty cells and made the page feel sparse. We now bucket the
 * cards into a handful of themed sections (Commercial, Field, Quality and
 * compliance, Planning, Activity and files) and give each section its own
 * tight responsive grid. ``auto-rows-fr`` keeps the cards in a row the same
 * height so the block reads as a clean, even mosaic instead of a stack.
 *
 * Sections self-hide when they have no visible children (every widget in the
 * group is toggled off in the layout manager), so the header never dangles
 * above an empty grid.
 */
function WidgetSection({
  icon,
  title,
  children,
  className,
}: {
  icon: React.ReactNode;
  title: string;
  /** Tailwind grid-template-columns classes for this section's card grid. */
  className: string;
  children: React.ReactNode;
}) {
  // Drop sections whose every child rendered ``false`` (all widgets hidden).
  const visible = React.Children.toArray(children).filter(Boolean);
  if (visible.length === 0) return null;
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-content-tertiary">{icon}</span>
        <h2 className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
          {title}
        </h2>
        <div className="h-px flex-1 bg-border-light" aria-hidden="true" />
      </div>
      <div className={clsx('grid gap-3 items-stretch auto-rows-fr', className)}>
        {visible}
      </div>
    </section>
  );
}

function DropZone({
  onFileSelect,
  disabled,
}: {
  onFileSelect: (file: File) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect, disabled],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFileSelect(file);
      // Reset input so re-selecting the same file triggers change
      e.target.value = '';
    },
    [onFileSelect],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`
        flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed
        px-6 py-10 text-center cursor-pointer transition-all duration-200
        ${dragOver ? 'border-oe-blue bg-oe-blue-subtle/30 scale-[1.01]' : 'border-border-light hover:border-content-tertiary hover:bg-surface-secondary'}
        ${disabled ? 'opacity-50 pointer-events-none' : ''}
      `}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-surface-secondary">
        <Upload size={22} className="text-content-tertiary" strokeWidth={1.5} />
      </div>
      <div>
        <p className="text-sm font-medium text-content-primary">
          {t('import.drop_or_browse', { defaultValue: 'Drop your file here, or click to browse' })}
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          {t('import.supported_formats', { defaultValue: 'Supports Excel, CSV, PDF, photos, and CAD/BIM files (Revit, IFC, DWG, DGN)' })}
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.csv,.pdf,.jpg,.jpeg,.png,.tiff,.rvt,.ifc,.dwg,.dgn"
        className="hidden"
        onChange={handleChange}
        disabled={disabled}
      />
    </div>
  );
}

function ImportDialog({
  boqId,
  boqName,
  onClose,
  onSuccess,
}: {
  boqId: string;
  boqName: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const SUPPORTED_EXTENSIONS = [
    '.xlsx', '.csv', '.pdf', '.jpg', '.jpeg', '.png', '.tiff',
    '.rvt', '.ifc', '.dwg', '.dgn',
  ];

  const mutation = useMutation({
    mutationFn: (file: File) => smartImportFile(boqId, file),
    onSuccess: (data) => {
      setResult(data);
      onSuccess();
      addToast({ type: 'success', title: t('toasts.import_success', { defaultValue: 'Import completed' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.import_failed', { defaultValue: 'Import failed' }), message: error.message });
    },
  });

  const handleFileSelect = useCallback(
    (file: File) => {
      const name = file.name.toLowerCase();
      if (!SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
        return;
      }
      setSelectedFile(file);
      setResult(null);
      mutation.reset();
    },
    [mutation],
  );

  const handleImport = useCallback(() => {
    if (selectedFile) {
      mutation.mutate(selectedFile);
    }
  }, [selectedFile, mutation]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative w-full max-w-lg mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-2">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('import.import_document', { defaultValue: 'Import Document' })}
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                <Sparkles size={10} />
                {t('import.ai_powered', { defaultValue: 'AI-powered' })}
              </span>
            </div>
            <p className="mt-0.5 text-sm text-content-secondary">
              {t('import.into_boq', { defaultValue: 'Into: {{name}}', name: boqName })}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4">
          {!result ? (
            <>
              <DropZone onFileSelect={handleFileSelect} disabled={mutation.isPending} />

              {selectedFile && (
                <div className="mt-4 flex items-center gap-3 rounded-lg bg-surface-secondary px-4 py-3">
                  <FileSpreadsheet
                    size={20}
                    className="shrink-0 text-oe-blue"
                    strokeWidth={1.5}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-content-primary truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-xs text-content-tertiary">
                      {(selectedFile.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  {!mutation.isPending && (
                    <button
                      onClick={() => {
                        setSelectedFile(null);
                        mutation.reset();
                      }}
                      className="text-content-tertiary hover:text-content-primary transition-colors"
                    >
                      <X size={16} />
                    </button>
                  )}
                </div>
              )}

              {mutation.isError && (
                <div className="mt-3 flex items-start gap-2 rounded-lg bg-semantic-error-bg px-4 py-3">
                  <AlertCircle size={16} className="shrink-0 mt-0.5 text-semantic-error" />
                  <div className="text-sm text-semantic-error">
                    {(() => {
                      const msg =
                        mutation.error instanceof Error
                          ? mutation.error.message
                          : 'Import failed. Please try again.';
                      // Show a link when DDC converter is not found
                      if (msg.includes('DDC converter') || msg.includes('no DDC converter')) {
                        return (
                          <div className="space-y-1.5">
                            <p>{t('import.cad_converter_missing', { defaultValue: 'CAD converter not installed.' })}</p>
                            <p className="text-xs text-semantic-error/80">
                              Download DDC converters from{' '}
                              <a
                                href="https://github.com/datadrivenconstruction/ddc-community-toolkit/releases"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline font-medium hover:text-semantic-error"
                              >
                                GitHub
                              </a>{' '}
                              and place .exe files in{' '}
                              <code className="bg-semantic-error/10 px-1 rounded">
                                {navigator.platform?.startsWith('Win') ? '%USERPROFILE%\\.openestimator\\converters\\' : '~/.openestimator/converters/'}
                              </code>
                            </p>
                          </div>
                        );
                      }
                      return <p>{msg}</p>;
                    })()}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="space-y-4">
              {/* Success summary */}
              <div className="flex items-center gap-3 rounded-lg bg-semantic-success-bg px-4 py-3">
                <CheckCircle2 size={20} className="shrink-0 text-semantic-success" />
                <div>
                  <p className="text-sm font-medium text-semantic-success">{t('import.complete', { defaultValue: 'Import complete' })}</p>
                  <p className="text-xs text-semantic-success/80">
                    {t('import.positions_imported', { defaultValue: '{{count}} positions imported', count: result.imported })}
                    {(result.skipped ?? 0) > 0 && `, ${t('import.rows_skipped', { defaultValue: '{{count}} rows skipped', count: result.skipped })}`}
                  </p>
                </div>
                {(result.method === 'ai' || result.method === 'cad_ai') && (
                  <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                    <Sparkles size={10} />
                    {result.method === 'cad_ai'
                      ? `CAD + ${result.model_used ?? 'AI'}`
                      : (result.model_used ?? 'AI')}
                  </span>
                )}
                {result.method === 'direct' && (
                  <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-tertiary">
                    {t('import.method_direct', { defaultValue: 'Direct' })}
                  </span>
                )}
              </div>

              {/* CAD info banner */}
              {result.method === 'cad_ai' && result.cad_elements != null && (
                <div className="flex items-center gap-2 rounded-lg bg-oe-blue-subtle/50 px-4 py-2.5 text-xs text-oe-blue-text">
                  <span className="font-medium">
                    {t('import.cad_elements_count', { defaultValue: '{{count}} CAD elements', count: result.cad_elements })}
                  </span>
                  <span className="text-oe-blue/60">
                    {t('import.cad_extracted', { defaultValue: 'extracted from .{{format}} file via DDC converter', format: result.cad_format })}
                  </span>
                </div>
              )}

              {/* Stats grid */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">{result.imported}</p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                    {t('import.stat_imported', { defaultValue: 'Imported' })}
                  </p>
                </div>
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">
                    {result.total_items ?? result.total_rows ?? 0}
                  </p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                    {t('import.stat_total_items', { defaultValue: 'Total items' })}
                  </p>
                </div>
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">{result.errors.length}</p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">{t('import.stat_errors', { defaultValue: 'Errors' })}</p>
                </div>
              </div>

              {/* Error details */}
              {result.errors.length > 0 && (
                <div className="rounded-lg border border-semantic-error/20 bg-semantic-error-bg/50 px-4 py-3">
                  <p className="text-xs font-medium text-semantic-error mb-2">{t('import.error_details', { defaultValue: 'Error details:' })}</p>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {result.errors.map((err, i) => (
                      <p key={`${err.row || err.item || ''}-${i}`} className="text-xs text-semantic-error/80">
                        {err.row ? `${t('import.error_row', { defaultValue: 'Row {{row}}', row: err.row })}: ` : err.item ? `${err.item}: ` : ''}
                        {err.error}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 pb-6 pt-2">
          {!result ? (
            <>
              <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
                {t('common.cancel')}
              </Button>
              <Button
                variant="primary"
                icon={<Upload size={16} />}
                onClick={handleImport}
                disabled={!selectedFile}
                loading={mutation.isPending}
              >
                {t('common.import')}
              </Button>
            </>
          ) : (
            <Button variant="primary" onClick={onClose}>
              {t('common.done', { defaultValue: 'Done' })}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error Boundary
// ---------------------------------------------------------------------------

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackDescription?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class TabErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) console.error('[TabErrorBoundary] Caught error:', error, info);
  }

  private handleRetry = (): void => {
    this.setState({ hasError: false });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <AlertTriangle className="text-semantic-warning mb-3" size={32} />
          <h3 className="text-base font-semibold text-content-primary">
            {this.props.fallbackTitle || i18n.t('common.something_went_wrong', { defaultValue: 'Something went wrong' })}
          </h3>
          <p className="mt-1 text-sm text-content-secondary max-w-md">
            {this.props.fallbackDescription ||
              i18n.t('common.unable_to_load', { defaultValue: 'Unable to load this section. Please try again.' })}
          </p>
          <button
            onClick={this.handleRetry}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-surface-secondary px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-tertiary transition-colors"
          >
            <RefreshCw size={14} />
            {i18n.t('common.retry', { defaultValue: 'Retry' })}
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

const INITIAL_PROJECT_EDIT_FORM = { name: '', description: '', region: '', currency: '' };

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [importTarget, setImportTarget] = useState<{
    boqId: string;
    boqName: string;
  } | null>(null);

  const [activeTab, setActiveTab] = useState<ProjectTab>('dashboard');
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState(INITIAL_PROJECT_EDIT_FORM);
  const [customizing, setCustomizing] = useState(false);

  // Layout customisation (per-user, localStorage-persisted). The order/
  // hidden state is read here so the top-of-page widget stack can be
  // re-arranged or trimmed live. Tab content below the tab bar is NOT
  // affected — only the always-visible header stack.
  const layoutHidden = useProjectDetailLayoutStore((s) => s.hidden);
  const isWidgetHidden = useCallback(
    (id: string) => layoutHidden.includes(id),
    [layoutHidden],
  );

  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  const updateMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; region?: string; currency?: string }) =>
      projectsApi.update(projectId!, data),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setActiveProject(projectId!, updated.name);
      setIsEditing(false);
      addToast({ type: 'success', title: t('toasts.project_updated', { defaultValue: 'Project updated successfully' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.project_update_failed', { defaultValue: 'Failed to update project' }), message: error.message });
    },
  });

  // Fetch project
  const {
    data: project,
    isLoading: projectLoading,
    isError: projectError,
    error: projectQueryError,
    refetch: refetchProject,
  } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
    // Retry on network errors (1x) but not on 4xx — a real 404 shouldn't
    // spin while the user waits.
    retry: (count, err) => {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
      return navigator.onLine && count < 1;
    },
    networkMode: 'offlineFirst',
  });

  // Distinguish "the project is truly gone" (404 from server) from
  // "we can't reach the server right now" (offline or 5xx). Only the
  // 404 case should clear sidebar recents — otherwise a transient
  // network blip wipes the user's navigation history.
  const is404 = projectQueryError instanceof ApiError && projectQueryError.status === 404;
  const isServerError =
    projectQueryError instanceof ApiError && projectQueryError.status >= 500;
  const isOffline =
    projectError && !is404 && !isServerError && typeof navigator !== 'undefined' && !navigator.onLine;
  const isNetworkError = projectError && !is404 && !isServerError && !isOffline;

  // Auto-clean stale references only when the project is actually gone.
  const clearProject = useProjectContextStore((s) => s.clearProject);
  const activeProjectIdInStore = useProjectContextStore((s) => s.activeProjectId);
  const recentItems = useRecentStore((s) => s.items);
  const clearRecent = useRecentStore((s) => s.clearRecent);
  useEffect(() => {
    if (!is404 || !projectId) return;
    if (activeProjectIdInStore === projectId) clearProject();
    if (recentItems.some((it) => it.id === projectId)) {
      const remaining = recentItems.filter((it) => it.id !== projectId);
      clearRecent();
      remaining.forEach((it) => {
        useRecentStore.getState().addRecent({
          type: it.type, id: it.id, title: it.title, url: it.url,
        });
      });
    }
  }, [is404, projectId, activeProjectIdInStore, clearProject, recentItems, clearRecent]);

  const addRecent = useRecentStore((s) => s.addRecent);

  // Set as active project in global context + track in recent items
  useEffect(() => {
    if (project && projectId) {
      setActiveProject(projectId, project.name);
      addRecent({
        type: 'project',
        id: projectId,
        title: project.name,
        url: `/projects/${projectId}`,
      });
    }
  }, [project, projectId, setActiveProject, addRecent]);

  // Fetch BOQ list
  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => fetchBoqs(projectId!),
    enabled: !!projectId,
  });

  // Fetch details for each BOQ (positions count, grand total)
  const { data: boqDetails } = useQuery({
    queryKey: ['boqDetails', projectId, boqs?.map((b) => b.id)],
    queryFn: async () => {
      if (!boqs || boqs.length === 0) return [];
      const results = await Promise.allSettled(boqs.map((b) => fetchBoqDetail(b.id)));
      return results
        .filter((r): r is PromiseFulfilledResult<BOQDetail> => r.status === 'fulfilled')
        .map((r) => r.value);
    },
    enabled: !!boqs && boqs.length > 0,
  });

  // Aggregate stats
  const stats = useMemo(() => {
    if (!boqDetails || boqDetails.length === 0) {
      return {
        totalBudget: 0,
        boqCount: boqs?.length ?? 0,
        totalPositions: 0,
        avgValidationScore: 0,
      };
    }

    let totalBudget = 0;
    let totalPositions = 0;
    let validatedCount = 0;
    let passedCount = 0;

    for (const detail of boqDetails) {
      totalBudget += detail.grand_total;
      totalPositions += detail.positions.length;
      for (const pos of detail.positions) {
        if (pos.validation_status && pos.validation_status !== 'pending') {
          validatedCount++;
          if (pos.validation_status === 'passed') {
            passedCount++;
          }
        }
      }
    }

    const avgValidationScore = validatedCount > 0 ? passedCount / validatedCount : 0;

    return {
      totalBudget,
      boqCount: boqDetails.length,
      totalPositions,
      avgValidationScore,
    };
  }, [boqDetails, boqs]);

  // Map BOQ details by id for quick lookup
  const detailMap = useMemo(() => {
    const map = new Map<string, BOQDetail>();
    if (boqDetails) {
      for (const d of boqDetails) {
        map.set(d.id, d);
      }
    }
    return map;
  }, [boqDetails]);

  const handleImportSuccess = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['boqs', projectId] });
    queryClient.invalidateQueries({ queryKey: ['boqDetails', projectId] });
  }, [queryClient, projectId]);

  // ── Tab data queries ──────────────────────────────────────────────────

  const { data: schedules, isLoading: schedulesLoading } = useQuery({
    queryKey: ['schedules', projectId],
    queryFn: () => apiGet<ScheduleItem[]>(`/v1/schedule/schedules/?project_id=${projectId}`),
    enabled: !!projectId && activeTab === 'schedule',
  });

  const { data: budgetDashboard, isLoading: budgetLoading } = useQuery({
    queryKey: ['budget', projectId],
    queryFn: () => apiGet<BudgetDashboard>(`/v1/costmodel/projects/${projectId}/5d/dashboard/`),
    enabled: !!projectId && activeTab === 'budget',
  });

  const { data: tenderPackages, isLoading: tenderingLoading } = useQuery({
    queryKey: ['tenderPackages', projectId],
    queryFn: () => apiGet<TenderPackage[]>(`/v1/tendering/packages/?project_id=${projectId}`),
    enabled: !!projectId && activeTab === 'tendering',
  });

  // Unified dashboard data
  const { data: dashboardData, isLoading: dashboardLoading } = useQuery({
    queryKey: ['project-dashboard', projectId],
    queryFn: () => projectsApi.dashboard(projectId!),
    enabled: !!projectId && activeTab === 'dashboard',
    staleTime: 30_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────
  if (projectLoading) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Skeleton height={20} width={120} />
        <Skeleton height={80} className="w-full" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} height={88} className="w-full" />
          ))}
        </div>
        <Skeleton height={200} className="w-full" />
      </div>
    );
  }

  // ── Offline / network error — the project may still exist server-side ──
  if (!project && (isOffline || isNetworkError || isServerError)) {
    return (
      <div className="w-full">
        <EmptyState
          title={
            isOffline
              ? t('projects.offline_title', { defaultValue: 'You appear to be offline' })
              : t('projects.network_error_title', { defaultValue: "Can't reach the server" })
          }
          description={
            isOffline
              ? t('projects.offline_desc', {
                  defaultValue:
                    "We'll load this project as soon as your connection returns. Your sidebar bookmarks are kept intact.",
                })
              : t('projects.network_error_desc', {
                  defaultValue:
                    'The server is not responding right now. This does not mean the project is deleted - try again in a moment.',
                })
          }
          action={
            <Button variant="primary" onClick={() => refetchProject()}>
              {t('common.retry', { defaultValue: 'Retry' })}
            </Button>
          }
        />
      </div>
    );
  }

  // ── Not found (true 404) ───────────────────────────────────────────────
  if (!project) {
    return (
      <div className="w-full">
        <EmptyState
          title={t('projects.not_found', { defaultValue: 'Project not found' })}
          description={t('projects.not_found_desc', {
            defaultValue:
              'The project you are looking for does not exist or has been deleted. Stale bookmarks have been cleared - pick an active project below.',
          })}
          action={
            <Button variant="primary" onClick={() => navigate('/projects')}>
              {t('projects.browse_projects', { defaultValue: 'Browse projects' })}
            </Button>
          }
        />
      </div>
    );
  }

  // No silent EUR fallback — when the project has no currency configured
  // formatCurrency() renders an em-dash so the gap is visible (the user
  // can set the currency via the inline editor in the header).
  const currency = project.currency || undefined;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb + Customize toggle */}
      <div className="flex items-start justify-between gap-3">
        <Breadcrumb
          items={[
            { label: t('projects.title', 'Projects'), to: '/projects' },
            { label: project.name },
          ]}
        />
        <Button
          variant={customizing ? 'primary' : 'ghost'}
          size="sm"
          icon={<LayoutGrid size={14} />}
          onClick={() => setCustomizing((v) => !v)}
          aria-pressed={customizing}
          title={t('project.layout.customize_hint', {
            defaultValue: 'Reorder, show or hide widgets on this page',
          })}
          data-testid="project-customize-button"
        >
          {customizing
            ? t('project.layout.done', { defaultValue: 'Done' })
            : t('project.layout.customize', { defaultValue: 'Customize' })}
        </Button>
      </div>

      <DismissibleInfo
        storageKey="project-detail"
        title={t('projects.detail_intro_title', {
          defaultValue: 'Every part of one project in reach',
        })}
        links={[
          {
            label: t('project.settings.title', { defaultValue: 'Project Settings' }),
            onClick: () => navigate(`/projects/${project.id}/settings`),
          },
          {
            label: t('nav.boq', { defaultValue: 'BOQ' }),
            onClick: () => navigate(`/projects/${project.id}/boq`),
          },
        ]}
      >
        {t('projects.detail_intro_body', {
          defaultValue:
            'This is the project hub: its BOQs, 4D schedule, 5D budget, tendering and key stats sit on one page so you do not hunt through the sidebar to find where the work lives. Jump straight into a cost work-product or open Project Settings to change region, currency or active modules. Edits to BOQs and costs roll up into the totals shown across Analytics and Reporting.',
        })}
      </DismissibleInfo>

      {/* ─── Customize panel (collapsible) — mirrors Dashboard pattern ─── */}
      {customizing && (
        <Card className="animate-card-in border-oe-blue/30">
          <CardHeader
            title={t('project.layout.title', { defaultValue: 'Customize project page' })}
            subtitle={t('project.layout.subtitle', {
              defaultValue:
                'Reorder, show or hide the widgets below. Your layout is saved to this browser.',
            })}
          />
          <CardContent>
            <ProjectLayoutManager onClose={() => setCustomizing(false)} />
          </CardContent>
        </Card>
      )}

      {/* ── Top row: Project Info (left) + Health ring (right) ─────────────
          The two cards end up roughly the same height, so pairing them
          side-by-side kills a big chunk of vertical whitespace and gives
          the page a calmer opening grid. Collapses to a stacked single
          column below `lg`. `items-stretch` + `h-full` on both children
          keeps their outer borders aligned; the inner Health content
          vertically centers so the ring doesn't hug the top. */}
      {(!isWidgetHidden('project-info') || !isWidgetHidden('health-bar')) && (
      <div
        className={clsx(
          'grid gap-3 items-stretch',
          !isWidgetHidden('project-info') && !isWidgetHidden('health-bar')
            ? 'grid-cols-1 lg:grid-cols-[3fr_2fr]'
            : 'grid-cols-1',
        )}
      >
      {!isWidgetHidden('project-info') && (
      /* ── Project Info Card ───────────────────────────────────────────── */
      <Card padding="md" className="h-full">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            {isEditing ? (
              <div className="space-y-3">
                <input
                  value={editForm.name}
                  onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full text-2xl font-bold text-content-primary bg-transparent border-b-2 border-oe-blue focus:outline-none pb-1"
                  placeholder={t('projects.project_name', 'Project name')}
                  autoFocus
                />
                <textarea
                  value={editForm.description}
                  onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                  className="w-full text-sm text-content-secondary bg-surface-secondary rounded-lg p-2 border border-border-light focus:outline-none focus:ring-2 focus:ring-oe-blue/30 resize-none"
                  rows={2}
                  placeholder={t('projects.description', 'Description')}
                />
                <div className="flex items-center gap-3">
                  <input
                    value={editForm.region}
                    onChange={(e) => setEditForm((f) => ({ ...f, region: e.target.value }))}
                    className="text-sm bg-surface-secondary rounded-lg px-3 py-1.5 border border-border-light focus:outline-none focus:ring-2 focus:ring-oe-blue/30 w-40"
                    placeholder={t('projects.region', 'Region')}
                  />
                  <input
                    value={editForm.currency}
                    onChange={(e) => setEditForm((f) => ({ ...f, currency: e.target.value.toUpperCase() }))}
                    className="text-sm bg-surface-secondary rounded-lg px-3 py-1.5 border border-border-light focus:outline-none focus:ring-2 focus:ring-oe-blue/30 w-24 uppercase"
                    placeholder="EUR"
                    maxLength={3}
                  />
                  <Button
                    size="sm"
                    onClick={() =>
                      updateMutation.mutate({
                        name: editForm.name,
                        description: editForm.description,
                        region: editForm.region,
                        currency: editForm.currency,
                      })
                    }
                    disabled={!editForm.name.trim() || updateMutation.isPending}
                  >
                    <Save size={14} className="mr-1" />
                    {t('common.save')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setIsEditing(false)}
                  >
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold text-content-primary">{project.name}</h1>
                  <Badge variant={statusVariant[project.status] ?? 'neutral'} size="md" dot>
                    {t(`projects.${project.status}`, { defaultValue: project.status })}
                  </Badge>
                  <button
                    onClick={() => {
                      setEditForm({
                        name: project.name,
                        description: project.description || '',
                        region: project.region || '',
                        // Don't pre-fill a guessed EUR — leave blank when the
                        // project has no currency so a click-Save doesn't
                        // silently stamp EUR. The input placeholder hints the
                        // ISO-4217 format.
                        currency: project.currency || '',
                      });
                      setIsEditing(true);
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                    title={t('common.edit')}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={() => navigate(`/projects/${project.id}/settings`)}
                    className="flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                    title={t('project.settings.title', { defaultValue: 'Project Settings' })}
                  >
                    <ClipboardList size={13} />
                    {t('project.settings.link', { defaultValue: 'Settings' })}
                  </button>
                </div>
                {project.description && (
                  <p className="mt-2 text-sm text-content-secondary max-w-2xl leading-relaxed">
                    {project.description}
                  </p>
                )}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <Badge variant="blue" size="sm">
                    {standardLabels[project.classification_standard] ??
                      project.classification_standard}
                  </Badge>
                  <Badge variant="neutral" size="sm">
                    {currency ?? t('projects.currency_not_set', { defaultValue: 'Currency not set' })}
                  </Badge>
                  <Badge variant="neutral" size="sm">
                    {project.region}
                  </Badge>
                  <span className="text-xs text-content-tertiary ml-2">
                    {t('projects.created', { date: formatDate(project.created_at, i18n.language) })}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </Card>
      )}

      {!isWidgetHidden('health-bar') && (
        /* Health block moves into the top grid (right column). */
        <ProjectHealthBar projectId={projectId!} boqs={boqs} boqDetails={boqDetails} />
      )}
      </div>
      )}

      {!isWidgetHidden('location') && (
        /* ── Location map + weather (toggleable in widget settings) ───── */
        <ProjectLocationPanel project={project} />
      )}

      {!isWidgetHidden('phase-ribbon') && (
        /* ── Phase Ribbon ────────────────────────────────────────────── */
        <ProjectPhaseRibbon phase={project.phase ?? null} />
      )}

      {/* ── New widgets — grouped pulse sections ───────────────────────
          Cards are bucketed into themed sections (Commercial, Field,
          Quality and compliance, Planning, Activity and files), each with
          its own tight equal-height grid. This replaces the old flat
          4-column grid where a few cards forced col-span-2 / full-row
          spans and left ragged rows with big empty cells. Every section
          self-hides when all of its widgets are toggled off in the layout
          manager.

          W23 P0: the provider fires ONE rollup request that feeds 8 of
          the 13 widgets below. The 5 widgets whose endpoints don't yet
          exist on the backend (photo strip, activity feed, schedule
          strip, AI insights, recent files) keep their own
          ``useGracefulQuery`` — adding them to the rollup would require
          new backend endpoints. */}
      <ProjectWidgetsRollupProvider projectId={projectId!}>
        {/* Commercial: requests, change orders, variations. */}
        <WidgetSection
          icon={<Receipt size={14} />}
          title={t('project.section.commercial', { defaultValue: 'Commercial' })}
          className="grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        >
          {!isWidgetHidden('rfi-inbox') && (
            <RFIInboxWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('change-orders') && (
            <ChangeOrdersPulseWidget projectId={projectId!} currency={currency ?? ''} />
          )}
          {!isWidgetHidden('variations') && (
            <VariationsWidget projectId={projectId!} currency={currency ?? ''} />
          )}
        </WidgetSection>

        {/* Field: what's happening on site today. */}
        <WidgetSection
          icon={<HardHat size={14} />}
          title={t('project.section.field', { defaultValue: 'Field' })}
          className="grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        >
          {!isWidgetHidden('daily-diary') && (
            <DailyDiaryWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('hse-incidents') && (
            <HSEIncidentsWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('photo-strip') && (
            <PhotoStripWidget projectId={projectId!} />
          )}
        </WidgetSection>

        {/* Quality and compliance: two-up counters. */}
        <WidgetSection
          icon={<ShieldCheck size={14} />}
          title={t('project.section.quality_compliance', {
            defaultValue: 'Quality & compliance',
          })}
          className="grid-cols-1 lg:grid-cols-2"
        >
          {!isWidgetHidden('quality-ncr') && (
            <QualityNCRWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('compliance-summary') && (
            <ComplianceSummaryWidget projectId={projectId!} />
          )}
        </WidgetSection>

        {/* Planning and cost: schedule progress + budget burn, side by
            side so the timeline and the spend history each get the width
            they need to read well. */}
        <WidgetSection
          icon={<CalendarClock size={14} />}
          title={t('project.section.planning_cost', {
            defaultValue: 'Planning & cost',
          })}
          className="grid-cols-1 lg:grid-cols-2"
        >
          {!isWidgetHidden('schedule-strip') && (
            <ScheduleStripWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('budget-burn') && (
            <BudgetBurnWidget projectId={projectId!} currency={currency ?? ''} />
          )}
        </WidgetSection>

        {/* Activity, files and AI: the cross-module event stream gets the
            widest column so its log doesn't cramp. */}
        <WidgetSection
          icon={<Activity size={14} />}
          title={t('project.section.activity_files', {
            defaultValue: 'Activity, files & AI',
          })}
          className="grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        >
          {!isWidgetHidden('recent-files') && (
            <RecentFilesWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('ai-insights') && (
            <AIInsightsWidget projectId={projectId!} />
          )}
          {!isWidgetHidden('activity-feed') && (
            <ActivityFeedWidget projectId={projectId!} />
          )}
        </WidgetSection>
      </ProjectWidgetsRollupProvider>
      {/* ``weather-alerts`` is a thin pointer to ProjectWeather (already
          rendered inside the location panel) — no separate render needed
          here, but the manager still exposes the toggle for future use. */}

      {!isWidgetHidden('team') && (
      <>
      {/* ── Team Strip ──────────────────────────────────────────────────── */}
      {/* Horizontal avatar row positioned above the tab bar (see modern
          project collaboration tools). Only the owner / admin sees the manage controls — for
          other authenticated users the strip is read-only. The owner
          check below leans on the JWT ``sub`` claim because the auth
          store doesn't keep ``userId`` separately yet. */}
      <div data-testid="team-strip-host">
        <TeamStrip
          projectId={projectId!}
          canManage={(() => {
            const token = useAuthStore.getState().accessToken;
            if (!token) return false;
            try {
              const parts = token.split('.');
              if (parts.length !== 3) return false;
              const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
              const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
              const json = JSON.parse(atob(padded)) as {
                sub?: string;
                role?: string;
              };
              if (json.role === 'admin') return true;
              return !!json.sub && json.sub === project.owner_id;
            } catch {
              return false;
            }
          })()}
        />
      </div>
      </>
      )}

      {!isWidgetHidden('summary-cards') && (
      /* ── Summary Cards ───────────────────────────────────────────────── */
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {(() => {
          const areaMatch = project.description?.match(/(\d[\d.,]*)\s*m[²2]/i);
          const area = areaMatch ? parseFloat((areaMatch[1] ?? '0').replace(',', '')) : null;
          const costPerM2 = area && stats.totalBudget > 0 ? stats.totalBudget / area : null;
          const costPerM2Str = costPerM2
            ? `${formatCurrency(costPerM2, currency)}/m\u00b2`
            : undefined;
          return (
            <SummaryCard
              label={t('boq.grand_total')}
              value={formatCurrency(stats.totalBudget, currency)}
              icon={<DollarSign size={20} strokeWidth={1.75} />}
              variant="blue"
              subtitle={costPerM2Str}
            />
          );
        })()}
        <SummaryCard
          label="BOQs"
          value={String(stats.boqCount)}
          icon={<Table2 size={20} strokeWidth={1.75} />}
        />
        <SummaryCard
          label={t('projects.positions')}
          value={String(stats.totalPositions)}
          icon={<Layers size={20} strokeWidth={1.75} />}
        />
        <SummaryCard
          label={t('validation.score')}
          value={
            stats.avgValidationScore > 0
              ? `${(stats.avgValidationScore * 100).toFixed(0)}%`
              : 'N/A'
          }
          icon={<ShieldCheck size={20} strokeWidth={1.75} />}
          variant={stats.avgValidationScore >= 0.8 ? 'success' : 'default'}
        />
      </div>
      )}

      {/* ── Tab Bar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-border-light">
        {([
          { key: 'dashboard' as ProjectTab, label: t('projects.dashboard', { defaultValue: 'Dashboard' }), icon: <LayoutDashboard size={15} /> },
          { key: 'overview' as ProjectTab, label: t('projects.overview'), icon: <Table2 size={15} /> },
          { key: 'schedule' as ProjectTab, label: t('projects.4d_schedule'), icon: <CalendarClock size={15} /> },
          { key: 'budget' as ProjectTab, label: t('projects.5d_budget'), icon: <Wallet size={15} /> },
          { key: 'tendering' as ProjectTab, label: t('projects.tendering'), icon: <Gavel size={15} /> },
          { key: 'photos' as ProjectTab, label: t('projects.photos.tab_label', { defaultValue: 'Photos' }), icon: <ImageIcon size={15} /> },
          { key: 'compliance' as ProjectTab, label: t('compliance.tab_label', { defaultValue: 'Compliance' }), icon: <ShieldCheck size={15} /> },
        ]).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`
              flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all
              ${
                activeTab === tab.key
                  ? 'border-oe-blue text-oe-blue'
                  : 'border-transparent text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
              }
            `}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}

      {/* Dashboard Tab — Unified KPI view */}
      {activeTab === 'dashboard' && (
        <TabErrorBoundary fallbackTitle="Dashboard data failed to load">
          {dashboardLoading ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} height={88} className="w-full" rounded="lg" />
                ))}
              </div>
              <Skeleton height={120} className="w-full" rounded="lg" />
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Skeleton height={200} className="w-full" rounded="lg" />
                <Skeleton height={200} className="w-full" rounded="lg" />
              </div>
            </div>
          ) : dashboardData ? (
            <div className="space-y-4 animate-fade-in">
              {/* KPI Cards Row */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {/* Budget consumed */}
                <div
                  className="relative overflow-hidden cursor-pointer rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  role="button"
                  tabIndex={0}
                  aria-label={t('projects.dash_budget_consumed', { defaultValue: 'Budget Consumed' })}
                  onClick={() => setActiveTab('budget')}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab('budget'); } }}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_budget_consumed', { defaultValue: 'Budget Consumed' })}
                      </p>
                      <p className="mt-0.5 text-xl font-bold text-content-primary tabular-nums leading-tight">
                        {parseFloat(dashboardData.budget.consumed_pct).toFixed(1)}%
                      </p>
                      <p className="text-xs text-content-secondary mt-1 tabular-nums">
                        {formatCurrency(parseFloat(dashboardData.budget.actual), currency)}{' '}
                        {t('projects.dash_of', { defaultValue: 'of' })}{' '}
                        {formatCurrency(parseFloat(dashboardData.budget.revised), currency)}
                      </p>
                    </div>
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                      dashboardData.budget.warning_level === 'critical'
                        ? 'bg-semantic-error-bg text-semantic-error'
                        : dashboardData.budget.warning_level === 'warning'
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-oe-blue-subtle text-oe-blue-text'
                    }`}>
                      <DollarSign size={20} strokeWidth={1.75} />
                    </div>
                  </div>
                  {/* Budget bar */}
                  <div className="mt-3 h-1.5 w-full rounded-full bg-surface-secondary overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(parseFloat(dashboardData.budget.consumed_pct), 100)}%`,
                        background: dashboardData.budget.warning_level === 'critical'
                          ? 'var(--oe-error, #dc2626)'
                          : dashboardData.budget.warning_level === 'warning'
                          ? '#ca8a04'
                          : 'var(--oe-blue)',
                      }}
                    />
                  </div>
                </div>

                {/* Schedule progress */}
                <div
                  className="cursor-pointer rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  role="button"
                  tabIndex={0}
                  aria-label={t('projects.dash_schedule_progress', { defaultValue: 'Schedule Progress' })}
                  onClick={() => setActiveTab('schedule')}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab('schedule'); } }}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_schedule_progress', { defaultValue: 'Schedule Progress' })}
                      </p>
                      <p className="mt-0.5 text-xl font-bold text-content-primary tabular-nums leading-tight">
                        {parseFloat(dashboardData.schedule.progress_pct).toFixed(1)}%
                      </p>
                      <p className="text-xs text-content-secondary mt-1">
                        {dashboardData.schedule.completed}/{dashboardData.schedule.total_activities}{' '}
                        {t('projects.dash_activities', { defaultValue: 'activities' })}
                        {dashboardData.schedule.delayed > 0 && (
                          <span className="text-semantic-error ml-1">
                            ({dashboardData.schedule.delayed} {t('projects.dash_delayed', { defaultValue: 'delayed' })})
                          </span>
                        )}
                      </p>
                    </div>
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#0891b2]/10 text-[#0891b2]">
                      <CalendarClock size={20} strokeWidth={1.75} />
                    </div>
                  </div>
                </div>

                {/* Quality score */}
                <div
                  className="cursor-pointer rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  role="button"
                  tabIndex={0}
                  aria-label={t('projects.dash_quality', { defaultValue: 'Quality Score' })}
                  onClick={() => navigate('/validation')}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/validation'); } }}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_quality', { defaultValue: 'Quality Score' })}
                      </p>
                      <p className="mt-0.5 text-xl font-bold text-content-primary tabular-nums leading-tight">
                        {(parseFloat(dashboardData.quality.validation_score) * 100).toFixed(0)}%
                      </p>
                      <p className="text-xs text-content-secondary mt-1">
                        {dashboardData.quality.open_defects > 0
                          ? `${dashboardData.quality.open_defects} ${t('projects.dash_open_defects', { defaultValue: 'open defects' })}`
                          : t('projects.dash_no_defects', { defaultValue: 'No open defects' })}
                      </p>
                    </div>
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                      parseFloat(dashboardData.quality.validation_score) >= 0.8
                        ? 'bg-semantic-success-bg text-semantic-success'
                        : parseFloat(dashboardData.quality.validation_score) >= 0.5
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-surface-secondary text-content-tertiary'
                    }`}>
                      <ShieldCheck size={20} strokeWidth={1.75} />
                    </div>
                  </div>
                </div>

                {/* Open items count */}
                <div
                  className="cursor-pointer rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                  role="button"
                  tabIndex={0}
                  aria-label={t('projects.dash_open_items', { defaultValue: 'Open Items' })}
                  onClick={() => navigate('/tasks')}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/tasks'); } }}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_open_items', { defaultValue: 'Open Items' })}
                      </p>
                      <p className="mt-0.5 text-xl font-bold text-content-primary tabular-nums leading-tight">
                        {dashboardData.communication.open_rfis +
                          dashboardData.communication.open_submittals +
                          dashboardData.communication.open_tasks +
                          dashboardData.quality.ncrs_open}
                      </p>
                      <p className="text-xs text-content-secondary mt-1">
                        {dashboardData.communication.open_rfis} RFIs,{' '}
                        {dashboardData.communication.open_tasks} {t('projects.dash_tasks', { defaultValue: 'tasks' })}
                      </p>
                    </div>
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#7c3aed]/10 text-[#7c3aed]">
                      <ClipboardList size={20} strokeWidth={1.75} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Budget section — horizontal stacked bar */}
              <Card
                padding="md"
                hoverable
                className="cursor-pointer"
                role="button"
                tabIndex={0}
                aria-label={t('projects.dash_budget_overview', { defaultValue: 'Budget Overview' })}
                onClick={() => setActiveTab('budget')}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab('budget'); } }}
              >
                <div className="flex items-center gap-2 mb-4">
                  <DollarSign size={16} className="text-content-tertiary" />
                  <h3 className="text-sm font-semibold text-content-primary">
                    {t('projects.dash_budget_overview', { defaultValue: 'Budget Overview' })}
                  </h3>
                  {dashboardData.budget.warning_level !== 'normal' && (
                    <Badge
                      variant={dashboardData.budget.warning_level === 'critical' ? 'error' : 'warning'}
                      size="sm"
                    >
                      {dashboardData.budget.warning_level === 'critical'
                        ? t('projects.dash_over_budget', { defaultValue: 'Over Budget' })
                        : t('projects.dash_at_risk', { defaultValue: 'At Risk' })}
                    </Badge>
                  )}
                </div>
                <div className="space-y-3">
                  {/* Stacked bar */}
                  <div className="relative h-8 w-full rounded-lg bg-surface-secondary overflow-hidden">
                    {(() => {
                      const forecast = parseFloat(dashboardData.budget.forecast) || 1;
                      const actual = parseFloat(dashboardData.budget.actual);
                      const committed = parseFloat(dashboardData.budget.committed);
                      const original = parseFloat(dashboardData.budget.original);
                      return (
                        <>
                          <div
                            className="absolute inset-y-0 left-0 bg-oe-blue/20 rounded-lg"
                            style={{ width: `${Math.min((original / forecast) * 100, 100)}%` }}
                            title={`${t('projects.dash_original', { defaultValue: 'Original' })}: ${formatCurrency(original, currency)}`}
                          />
                          <div
                            className="absolute inset-y-0 left-0 bg-oe-blue/40 rounded-l-lg"
                            style={{ width: `${Math.min((committed / forecast) * 100, 100)}%` }}
                            title={`${t('projects.dash_committed', { defaultValue: 'Committed' })}: ${formatCurrency(committed, currency)}`}
                          />
                          <div
                            className="absolute inset-y-0 left-0 bg-oe-blue rounded-l-lg"
                            style={{ width: `${Math.min((actual / forecast) * 100, 100)}%` }}
                            title={`${t('projects.dash_actual', { defaultValue: 'Actual' })}: ${formatCurrency(actual, currency)}`}
                          />
                        </>
                      );
                    })()}
                  </div>
                  {/* Legend */}
                  <div className="flex flex-wrap items-center gap-4 text-xs text-content-secondary">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm bg-oe-blue" />
                      {t('projects.dash_actual', { defaultValue: 'Actual' })}: {formatCurrency(parseFloat(dashboardData.budget.actual), currency)}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm bg-oe-blue/40" />
                      {t('projects.dash_committed', { defaultValue: 'Committed' })}: {formatCurrency(parseFloat(dashboardData.budget.committed), currency)}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm bg-oe-blue/20" />
                      {t('projects.dash_original', { defaultValue: 'Original' })}: {formatCurrency(parseFloat(dashboardData.budget.original), currency)}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm border border-content-tertiary" />
                      {t('projects.dash_forecast', { defaultValue: 'Forecast' })}: {formatCurrency(parseFloat(dashboardData.budget.forecast), currency)}
                    </span>
                  </div>
                </div>
              </Card>

              {/* Middle row: Schedule + Open Items */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* Schedule section */}
                <Card
                  padding="md"
                  hoverable
                  className="cursor-pointer"
                  role="button"
                  tabIndex={0}
                  aria-label={t('projects.dash_schedule', { defaultValue: 'Schedule' })}
                  onClick={() => setActiveTab('schedule')}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab('schedule'); } }}
                >
                  <div className="flex items-center gap-2 mb-3">
                    <CalendarClock size={16} className="text-content-tertiary" />
                    <h3 className="text-sm font-semibold text-content-primary">
                      {t('projects.dash_schedule', { defaultValue: 'Schedule' })}
                    </h3>
                  </div>
                  <div className="flex items-center gap-6">
                    {/* Progress ring */}
                    <div className="relative shrink-0">
                      <svg className="h-20 w-20 -rotate-90" viewBox="0 0 80 80">
                        <circle cx="40" cy="40" r="34" fill="none" stroke="currentColor" strokeWidth="7" className="text-surface-secondary" />
                        <circle
                          cx="40" cy="40" r="34" fill="none" stroke="currentColor" strokeWidth="7"
                          strokeLinecap="round"
                          strokeDasharray={`${(parseFloat(dashboardData.schedule.progress_pct) / 100) * 213.63} 213.63`}
                          className="text-oe-blue transition-all duration-500"
                        />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center">
                        <span className="text-base font-bold text-content-primary tabular-nums">
                          {parseFloat(dashboardData.schedule.progress_pct).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                    <div className="flex-1 space-y-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-content-secondary">{t('projects.dash_completed', { defaultValue: 'Completed' })}</span>
                        <span className="font-medium text-content-primary tabular-nums">{dashboardData.schedule.completed}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-content-secondary">{t('projects.dash_in_progress', { defaultValue: 'In Progress' })}</span>
                        <span className="font-medium text-content-primary tabular-nums">{dashboardData.schedule.in_progress}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-content-secondary">{t('projects.dash_delayed', { defaultValue: 'Delayed' })}</span>
                        <span className={`font-medium tabular-nums ${dashboardData.schedule.delayed > 0 ? 'text-semantic-error' : 'text-content-primary'}`}>
                          {dashboardData.schedule.delayed}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-content-secondary">{t('projects.dash_critical_path', { defaultValue: 'Critical Path' })}</span>
                        <span className="font-medium text-content-primary tabular-nums">{dashboardData.schedule.critical_activities}</span>
                      </div>
                      {dashboardData.schedule.next_milestone && (
                        <div className="mt-2 pt-2 border-t border-border-light">
                          <p className="text-2xs text-content-tertiary uppercase tracking-wider">
                            {t('projects.dash_next_milestone', { defaultValue: 'Next Milestone' })}
                          </p>
                          <p className="text-xs font-medium text-content-primary mt-0.5">
                            {dashboardData.schedule.next_milestone.name}
                          </p>
                          <p className="text-2xs text-content-tertiary">
                            {formatDate(dashboardData.schedule.next_milestone.date, i18n.language)}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </Card>

                {/* Open Items Grid */}
                <Card padding="md">
                  <div className="flex items-center gap-2 mb-3">
                    <MessageSquare size={16} className="text-content-tertiary" />
                    <h3 className="text-sm font-semibold text-content-primary">
                      {t('projects.dash_open_items_detail', { defaultValue: 'Open Items' })}
                    </h3>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      {
                        label: t('projects.dash_rfis', { defaultValue: 'RFIs' }),
                        count: dashboardData.communication.open_rfis,
                        alert: dashboardData.communication.overdue_rfis,
                        alertLabel: t('projects.dash_overdue', { defaultValue: 'overdue' }),
                        icon: <MessageSquare size={14} />,
                        color: 'text-oe-blue',
                        bg: 'bg-oe-blue-subtle',
                        to: '/rfi',
                      },
                      {
                        label: t('projects.dash_submittals', { defaultValue: 'Submittals' }),
                        count: dashboardData.communication.open_submittals,
                        icon: <FileCheck size={14} />,
                        color: 'text-[#7c3aed]',
                        bg: 'bg-[#7c3aed]/10',
                        to: '/submittals',
                      },
                      {
                        label: t('projects.dash_tasks', { defaultValue: 'Tasks' }),
                        count: dashboardData.communication.open_tasks,
                        icon: <ClipboardList size={14} />,
                        color: 'text-[#0891b2]',
                        bg: 'bg-[#0891b2]/10',
                        to: '/tasks',
                      },
                      {
                        label: t('projects.dash_ncrs', { defaultValue: 'NCRs' }),
                        count: dashboardData.quality.ncrs_open,
                        icon: <AlertTriangle size={14} />,
                        color: dashboardData.quality.ncrs_open > 0 ? 'text-semantic-error' : 'text-content-tertiary',
                        bg: dashboardData.quality.ncrs_open > 0 ? 'bg-semantic-error-bg' : 'bg-surface-secondary',
                        to: '/punchlist',
                      },
                    ].map((item) => (
                      <button
                        key={item.label}
                        type="button"
                        onClick={() => navigate(item.to)}
                        className="rounded-lg border border-border-light p-3 text-left transition-all hover:border-oe-blue/40 hover:bg-surface-secondary hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                        aria-label={`${item.label}: ${item.count}`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <div className={`flex h-6 w-6 items-center justify-center rounded-md ${item.bg} ${item.color}`}>
                            {item.icon}
                          </div>
                          <span className="text-xs text-content-secondary">{item.label}</span>
                        </div>
                        <p className="text-lg font-bold text-content-primary tabular-nums">{item.count}</p>
                        {'alert' in item && item.alert != null && item.alert > 0 && (
                          <p className="text-2xs text-semantic-error mt-0.5">
                            {item.alert} {item.alertLabel}
                          </p>
                        )}
                      </button>
                    ))}
                  </div>
                  {/* Procurement summary */}
                  <div className="mt-3 pt-3 border-t border-border-light">
                    <button
                      type="button"
                      onClick={() => navigate('/procurement')}
                      className="block w-full text-left rounded-md transition-colors hover:bg-surface-secondary -mx-2 px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                      aria-label={t('projects.dash_procurement', { defaultValue: 'Procurement' })}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <Package size={14} className="text-content-tertiary" />
                        <span className="text-xs font-medium text-content-secondary">
                          {t('projects.dash_procurement', { defaultValue: 'Procurement' })}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-content-secondary">
                        <span>
                          <strong className="text-content-primary">{dashboardData.procurement.active_pos}</strong>{' '}
                          {t('projects.dash_active_pos', { defaultValue: 'active POs' })}
                        </span>
                        <span>
                          <strong className="text-content-primary">{dashboardData.procurement.pending_delivery}</strong>{' '}
                          {t('projects.dash_pending_delivery', { defaultValue: 'pending delivery' })}
                        </span>
                      </div>
                    </button>
                  </div>
                </Card>
              </div>

              {/* Bottom row: Recent Activity + Quick Actions */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {/* Recent Activity Feed */}
                <Card padding="none" className="lg:col-span-2">
                  <div className="px-5 pt-5 pb-2">
                    <div className="flex items-center gap-2">
                      <Activity size={16} className="text-content-tertiary" />
                      <h3 className="text-sm font-semibold text-content-primary">
                        {t('projects.dash_recent_activity', { defaultValue: 'Recent Activity' })}
                      </h3>
                    </div>
                  </div>
                  {dashboardData.recent_activity.length === 0 ? (
                    <div className="px-5 pb-5">
                      <p className="text-xs text-content-tertiary text-center py-6">
                        {t('projects.dash_no_activity', { defaultValue: 'No recent activity in this project.' })}
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-border-light">
                      {dashboardData.recent_activity.map((item, idx) => {
                        const typeLabels: Record<string, string> = {
                          rfi_created: 'RFI',
                          task_created: t('projects.dash_task', { defaultValue: 'Task' }),
                          change_order: t('projects.dash_change_order', { defaultValue: 'Change Order' }),
                          document_uploaded: t('projects.dash_document', { defaultValue: 'Document' }),
                          punch_item: t('projects.dash_punch_item', { defaultValue: 'Punch Item' }),
                          field_report: t('projects.dash_field_report', { defaultValue: 'Field Report' }),
                        };
                        const typeColors: Record<string, string> = {
                          rfi_created: 'bg-oe-blue-subtle text-oe-blue-text',
                          task_created: 'bg-[#0891b2]/10 text-[#0891b2]',
                          change_order: 'bg-amber-100 text-amber-600',
                          document_uploaded: 'bg-[#7c3aed]/10 text-[#7c3aed]',
                          punch_item: 'bg-semantic-error-bg text-semantic-error',
                          field_report: 'bg-semantic-success-bg text-semantic-success',
                        };
                        const typeRoutes: Record<string, string> = {
                          rfi_created: '/rfi',
                          task_created: '/tasks',
                          change_order: '/changeorders',
                          document_uploaded: '/files',
                          punch_item: '/punchlist',
                          field_report: '/field-reports',
                        };
                        const to = typeRoutes[item.type] ?? '/dashboard';
                        return (
                          <button
                            key={`${item.type}-${item.title.slice(0, 30)}-${idx}`}
                            type="button"
                            onClick={() => navigate(to)}
                            className="flex items-center gap-3 px-5 py-3 w-full text-left transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue/40"
                            aria-label={`${typeLabels[item.type] || item.type}: ${item.title}`}
                          >
                            <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-2xs font-bold ${typeColors[item.type] || 'bg-surface-secondary text-content-tertiary'}`}>
                              {(typeLabels[item.type] || item.type).charAt(0).toUpperCase()}
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-sm text-content-primary truncate">{item.title}</p>
                              <p className="text-2xs text-content-tertiary">
                                {typeLabels[item.type] || item.type}
                              </p>
                            </div>
                            <span className="text-2xs text-content-tertiary shrink-0 tabular-nums">
                              {formatDate(item.date, i18n.language)}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </Card>

                {/* Quick Actions — flex column so the card stretches to match
                    Recent Activity height; Documents stats are pushed to the
                    bottom via mt-auto. */}
                <Card padding="md" className="h-full flex flex-col">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles size={16} className="text-content-tertiary" />
                    <h3 className="text-sm font-semibold text-content-primary">
                      {t('projects.dash_quick_actions', { defaultValue: 'Quick Actions' })}
                    </h3>
                  </div>
                  <div className="space-y-2.5">
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<Plus size={14} />}
                      onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                    >
                      {t('projects.new_boq', { defaultValue: 'New BOQ' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<MessageSquare size={14} />}
                      onClick={() => navigate('/rfi')}
                    >
                      {t('projects.dash_new_rfi', { defaultValue: 'New RFI' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<ClipboardList size={14} />}
                      onClick={() => navigate('/tasks')}
                    >
                      {t('projects.dash_new_task', { defaultValue: 'New Task' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<ShieldCheck size={14} />}
                      onClick={() => navigate('/validation')}
                    >
                      {t('projects.dash_run_validation', { defaultValue: 'Run Validation' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<FileSpreadsheet size={14} />}
                      onClick={() => navigate('/reports')}
                    >
                      {t('projects.dash_generate_report', { defaultValue: 'Generate Report' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<FolderOpen size={14} />}
                      onClick={() => navigate('/documents')}
                    >
                      {t('projects.dash_documents_link', { defaultValue: 'Documents' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<Calendar size={14} />}
                      onClick={() => navigate('/schedule')}
                    >
                      {t('projects.dash_schedule_link', { defaultValue: 'Schedule' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<Wallet size={14} />}
                      onClick={() => navigate('/finance')}
                    >
                      {t('projects.dash_finance_link', { defaultValue: 'Finance' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<HardHat size={14} />}
                      onClick={() => navigate('/safety')}
                    >
                      {t('projects.dash_safety_link', { defaultValue: 'Safety' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="md"
                      className="w-full justify-start"
                      icon={<Package size={14} />}
                      onClick={() => navigate('/procurement')}
                    >
                      {t('projects.dash_procurement_link', { defaultValue: 'Procurement' })}
                    </Button>
                  </div>
                  {/* Document stats — pushed to the bottom via mt-auto so the
                      Quick Actions card visually balances against Recent
                      Activity height. Numbers promoted to text-lg for parity
                      with the activity-feed weight. */}
                  <div className="mt-auto pt-4">
                    <button
                      type="button"
                      onClick={() => navigate('/files')}
                      className="block w-full text-left rounded-lg border border-border-light bg-surface-secondary/40 transition-colors hover:bg-surface-secondary hover:border-border px-3 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                      aria-label={t('projects.dash_documents', { defaultValue: 'Documents' })}
                    >
                      <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <FolderOpen size={12} className="text-content-quaternary" />
                        {t('projects.dash_documents', { defaultValue: 'Documents' })}
                      </p>
                      <div className="flex items-center gap-4 text-xs text-content-secondary">
                        <span className="flex flex-col">
                          <strong className="text-lg leading-none text-content-primary">{dashboardData.documents.total}</strong>
                          <span className="mt-0.5 text-2xs text-content-tertiary uppercase tracking-wide">{t('projects.dash_total', { defaultValue: 'total' })}</span>
                        </span>
                        <span className="flex flex-col">
                          <strong className="text-lg leading-none text-content-primary">{dashboardData.documents.published}</strong>
                          <span className="mt-0.5 text-2xs text-content-tertiary uppercase tracking-wide">{t('projects.dash_published', { defaultValue: 'published' })}</span>
                        </span>
                        {dashboardData.documents.pending_transmittals > 0 && (
                          <span className="flex flex-col">
                            <strong className="text-lg leading-none text-amber-600">{dashboardData.documents.pending_transmittals}</strong>
                            <span className="mt-0.5 text-2xs text-amber-700/80 uppercase tracking-wide">{t('projects.dash_pending', { defaultValue: 'pending' })}</span>
                          </span>
                        )}
                      </div>
                    </button>
                  </div>
                </Card>
              </div>
            </div>
          ) : (
            <EmptyState
              icon={<LayoutDashboard size={28} strokeWidth={1.5} />}
              title={t('projects.dash_empty', { defaultValue: 'No dashboard data' })}
              description={t('projects.dash_empty_desc', { defaultValue: 'Start adding BOQs, schedules, and documents to see project KPIs here.' })}
            />
          )}
        </TabErrorBoundary>
      )}

      {/* Overview Tab — BOQ List */}
      {activeTab === 'overview' && (
        <Card padding="none">
          <div className="px-6 pt-6 pb-2">
            <CardHeader
              title={t('boq.title')}
              subtitle={t('projects.boqs_for_project')}
              action={
                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Table2 size={14} />}
                    onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                  >
                    {t('projects.new_boq')}
                  </Button>
                </div>
              }
            />
          </div>

          <div className="mt-2">
            {boqsLoading ? (
              <div className="px-6 pb-6 space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} height={72} className="w-full" />
                ))}
              </div>
            ) : !boqs || boqs.length === 0 ? (
              <div className="px-6 pb-6">
                <EmptyState
                  icon={<Table2 size={28} strokeWidth={1.5} />}
                  title={t('projects.no_boqs')}
                  description={t('projects.no_boqs_desc')}
                  action={
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Table2 size={14} />}
                      onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                    >
                      {t('projects.create_boq')}
                    </Button>
                  }
                />
              </div>
            ) : (
              <div className="divide-y divide-border-light">
                {boqs.map((boq) => {
                  const detail = detailMap.get(boq.id);
                  const posCount = detail?.positions.length ?? 0;
                  const grandTotal = detail?.grand_total ?? 0;

                  return (
                    <div
                      key={boq.id}
                      className="flex items-center gap-4 px-6 py-4 transition-colors hover:bg-surface-secondary group"
                    >
                      {/* Icon */}
                      <button
                        onClick={() => navigate(`/boq/${boq.id}`)}
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text transition-transform group-hover:scale-105"
                      >
                        <Table2 size={18} strokeWidth={1.75} />
                      </button>

                      {/* Info */}
                      <button
                        onClick={() => navigate(`/boq/${boq.id}`)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <div className="text-sm font-medium text-content-primary truncate">
                          {boq.name}
                        </div>
                        <div className="mt-0.5 flex items-center gap-3 text-xs text-content-tertiary">
                          <span>{posCount} {t('projects.positions').toLowerCase()}</span>
                          <span className="text-border">|</span>
                          <span className="font-medium tabular-nums">
                            {formatCurrency(grandTotal, currency)}
                          </span>
                          {boq.updated_at && (
                            <>
                              <span className="text-border">|</span>
                              <span className="flex items-center gap-1">
                                <Clock size={11} />
                                {formatDate(boq.updated_at, i18n.language)}
                              </span>
                            </>
                          )}
                        </div>
                      </button>

                      {/* Actions */}
                      <div className="flex items-center gap-2">
                        <Badge variant={statusVariant[boq.status] ?? 'neutral'} size="sm">
                          {boq.status}
                        </Badge>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Upload size={14} />}
                          title={t('boq.import_tooltip', { defaultValue: 'Import GAEB, Excel, or CSV into this BOQ' })}
                          onClick={(e) => {
                            e.stopPropagation();
                            setImportTarget({ boqId: boq.id, boqName: boq.name });
                          }}
                        >
                          {t('boq.import_file', { defaultValue: 'Import File' })}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Card>
      )}

      {/* 4D Schedule Tab */}
      {activeTab === 'schedule' && (
        <TabErrorBoundary fallbackTitle="Schedule data failed to load">
        <Card padding="lg">
          <CardHeader title={t('projects.4d_schedule')} subtitle={t('projects.schedule_subtitle', { defaultValue: 'Project schedules and timeline' })} />
          <div className="mt-4">
            {schedulesLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} height={56} className="w-full" />
                ))}
              </div>
            ) : !schedules || schedules.length === 0 ? (
              <EmptyState
                icon={<CalendarClock size={28} strokeWidth={1.5} />}
                title={t('projects.no_schedules', { defaultValue: 'No schedules yet' })}
                description={t('projects.no_schedules_desc', { defaultValue: 'Create a schedule to manage project timelines.' })}
              />
            ) : (
              <div className="divide-y divide-border-light rounded-lg border border-border-light">
                {schedules.map((sched) => (
                  <div key={sched.id} className="flex items-center gap-4 px-5 py-3.5">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                      <CalendarClock size={16} className="text-content-tertiary" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-content-primary truncate">
                        {sched.name}
                      </p>
                      <p className="text-xs text-content-tertiary">{formatDate(sched.created_at, i18n.language)}</p>
                    </div>
                    <Badge variant={statusVariant[sched.status] ?? 'neutral'} size="sm">
                      {sched.status}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
        </TabErrorBoundary>
      )}

      {/* 5D Budget Tab */}
      {activeTab === 'budget' && (
        <TabErrorBoundary fallbackTitle="Budget data failed to load">
        <Card padding="lg">
          <CardHeader title={t('projects.5d_budget')} subtitle={t('projects.budget_subtitle', { defaultValue: 'Cost model and budget tracking' })} />
          <div className="mt-4">
            {budgetLoading ? (
              <div className="space-y-3">
                <Skeleton height={88} className="w-full" />
                <Skeleton height={200} className="w-full" />
              </div>
            ) : !budgetDashboard ? (
              <EmptyState
                icon={<Wallet size={28} strokeWidth={1.5} />}
                title={t('projects.no_budget', { defaultValue: 'No budget data' })}
                description={t('projects.no_budget_desc', { defaultValue: 'Set up a 5D cost model to track planned vs actual costs.' })}
              />
            ) : (
              <div className="space-y-5">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <SummaryCard
                    label={t('projects.total_budget', { defaultValue: 'Total Budget' })}
                    value={formatCurrency(budgetDashboard.total_budget ?? 0, currency)}
                    icon={<DollarSign size={18} strokeWidth={1.75} />}
                    variant="blue"
                  />
                  <SummaryCard
                    label={t('projects.total_spent', { defaultValue: 'Total Spent' })}
                    value={formatCurrency(budgetDashboard.total_actual ?? budgetDashboard.total_spent ?? 0, currency)}
                    icon={<DollarSign size={18} strokeWidth={1.75} />}
                  />
                  <SummaryCard
                    label={t('projects.remaining', { defaultValue: 'Remaining' })}
                    value={formatCurrency(
                      budgetDashboard.remaining ?? (budgetDashboard.total_budget ?? 0) - (budgetDashboard.total_actual ?? 0),
                      currency,
                    )}
                    icon={<DollarSign size={18} strokeWidth={1.75} />}
                    variant={
                      (budgetDashboard.remaining ?? (budgetDashboard.total_budget ?? 0) - (budgetDashboard.total_actual ?? 0)) >= 0
                        ? 'success'
                        : 'default'
                    }
                  />
                </div>
                {(budgetDashboard.items?.length ?? 0) > 0 && (
                  <div className="rounded-lg border border-border-light overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border-light bg-surface-tertiary text-left">
                          <th className="px-4 py-2.5 font-medium text-content-secondary">{t('common.item', { defaultValue: 'Item' })}</th>
                          <th className="px-4 py-2.5 font-medium text-content-secondary text-right">
                            {t('projects.planned', { defaultValue: 'Planned' })}
                          </th>
                          <th className="px-4 py-2.5 font-medium text-content-secondary text-right">
                            {t('projects.actual', { defaultValue: 'Actual' })}
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-light">
                        {budgetDashboard.items!.map((item) => (
                          <tr key={item.name} className="hover:bg-surface-secondary transition-colors">
                            <td className="px-4 py-2.5 text-content-primary">{item.name}</td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">
                              {formatCurrency(item.planned ?? 0, currency)}
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                              {formatCurrency(item.actual ?? 0, currency)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
        </TabErrorBoundary>
      )}

      {/* Tendering Tab */}
      {activeTab === 'tendering' && (
        <TabErrorBoundary fallbackTitle="Tendering data failed to load">
        <Card padding="lg">
          <CardHeader
            title={t('projects.tendering')}
            subtitle={t('projects.tendering_subtitle', { defaultValue: 'Tender packages and bid management' })}
            action={
              <Button
                variant="ghost"
                size="sm"
                icon={<ExternalLink size={14} />}
                iconPosition="right"
                onClick={() => navigate('/tendering')}
              >
                {t('projects.open_tendering', { defaultValue: 'Open Tendering' })}
              </Button>
            }
          />
          <div className="mt-4">
            {tenderingLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} height={56} className="w-full" />
                ))}
              </div>
            ) : !tenderPackages || tenderPackages.length === 0 ? (
              <EmptyState
                icon={<Gavel size={28} strokeWidth={1.5} />}
                title={t('projects.no_tenders', { defaultValue: 'No tender packages' })}
                description={t('projects.no_tenders_desc', { defaultValue: 'Create tender packages to manage bidding for this project.' })}
                action={
                  <Button
                    variant="primary"
                    size="md"
                    icon={<Plus size={16} />}
                    onClick={() => navigate('/tendering')}
                  >
                    {t('tendering.new_package', { defaultValue: 'New Tender Package' })}
                  </Button>
                }
              />
            ) : (
              <div className="divide-y divide-border-light rounded-lg border border-border-light">
                {tenderPackages.map((pkg) => (
                  <div key={pkg.id} className="flex items-center gap-4 px-5 py-3.5">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                      <Gavel size={16} className="text-content-tertiary" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-content-primary truncate">
                        {pkg.name}
                      </p>
                      <p className="text-xs text-content-tertiary">{formatDate(pkg.created_at, i18n.language)}</p>
                    </div>
                    <Badge variant={statusVariant[pkg.status] ?? 'neutral'} size="sm">
                      {pkg.status}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
        </TabErrorBoundary>
      )}

      {/* Photos Tab — gallery of all photo uploads for the project */}
      {activeTab === 'photos' && (
        <TabErrorBoundary fallbackTitle="Photos failed to load">
          <PhotosTab projectId={projectId ?? null} />
        </TabErrorBoundary>
      )}

      {/* Compliance Tab — insurance / permits / bonds / certifications tracker */}
      {activeTab === 'compliance' && (
        <TabErrorBoundary fallbackTitle="Compliance failed to load">
          <CompliancePage projectId={projectId ?? null} />
        </TabErrorBoundary>
      )}

      {/* ── Import Dialog ───────────────────────────────────────────────── */}
      {importTarget && (
        <ImportDialog
          boqId={importTarget.boqId}
          boqName={importTarget.boqName}
          onClose={() => setImportTarget(null)}
          onSuccess={handleImportSuccess}
        />
      )}
    </div>
  );
}

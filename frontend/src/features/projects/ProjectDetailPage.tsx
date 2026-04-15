import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
} from 'lucide-react';
import { Button, Card, CardHeader, Badge, Skeleton, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { projectsApi } from './api';
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

type ProjectTab = 'dashboard' | 'overview' | 'schedule' | 'budget' | 'tendering';

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
    throw new Error(body.detail || 'Import failed');
  }
  return res.json();
}

function formatCurrency(value: number, currency = 'EUR'): string {
  // Validate currency code — must be 3 uppercase ASCII letters (ISO 4217)
  const safeCurrency = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(i18n.language, {
      style: 'currency',
      currency: safeCurrency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${safeCurrency}`;
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
        defaultValue: 'Open the BOQ editor and add your first positions — manually, from Excel, or with AI.',
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
        defaultValue: 'Check your BOQ against DIN 276, GAEB, and quality rules to catch issues early.',
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
        defaultValue: 'Project is ready. Export to GAEB, Excel, or PDF — or distribute as a tender package.',
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
    <Card padding="md" className="mb-6">
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
                title={check.label + (check.done ? ' ✓' : '')}
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
    success: 'bg-semantic-success-bg text-[#15803d]',
    blue: 'bg-oe-blue-subtle text-oe-blue',
  };

  return (
    <Card padding="md" className="flex-1 min-w-[180px]">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
            {label}
          </p>
          <p className="mt-1.5 text-2xl font-bold text-content-primary tabular-nums">{value}</p>
          {subtitle && (
            <p className="text-xs text-content-secondary mt-1 tabular-nums">{subtitle}</p>
          )}
        </div>
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${bgMap[variant]}`}
        >
          {icon}
        </div>
      </div>
    </Card>
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
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
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
        className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative w-full max-w-lg mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-2">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('import.import_document', { defaultValue: 'Import Document' })}
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue">
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
                <CheckCircle2 size={20} className="shrink-0 text-[#15803d]" />
                <div>
                  <p className="text-sm font-medium text-[#15803d]">{t('import.complete', { defaultValue: 'Import complete' })}</p>
                  <p className="text-xs text-[#15803d]/80">
                    {t('import.positions_imported', { defaultValue: '{{count}} positions imported', count: result.imported })}
                    {(result.skipped ?? 0) > 0 && `, ${t('import.rows_skipped', { defaultValue: '{{count}} rows skipped', count: result.skipped })}`}
                  </p>
                </div>
                {(result.method === 'ai' || result.method === 'cad_ai') && (
                  <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue">
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
                <div className="flex items-center gap-2 rounded-lg bg-oe-blue-subtle/50 px-4 py-2.5 text-xs text-oe-blue">
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
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

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
      <div className="w-full space-y-6 animate-fade-in">
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

  // ── Not found ──────────────────────────────────────────────────────────
  if (!project) {
    return (
      <div className="w-full">
        <EmptyState
          title={t('projects.not_found', { defaultValue: 'Project not found' })}
          description={t('projects.not_found_desc', { defaultValue: 'The project you are looking for does not exist or has been deleted.' })}
          action={
            <Button variant="secondary" onClick={() => navigate('/projects')}>
              {t('projects.title')}
            </Button>
          }
        />
      </div>
    );
  }

  const currency = project.currency || 'EUR';

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        className="mb-4"
        items={[
          { label: t('projects.title', 'Projects'), to: '/projects' },
          { label: project.name },
        ]}
      />

      {/* ── Project Info Card ───────────────────────────────────────────── */}
      <Card padding="lg" className="mb-6">
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
                        currency: project.currency || 'EUR',
                      });
                      setIsEditing(true);
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                    title={t('common.edit')}
                  >
                    <Pencil size={14} />
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
                    {currency}
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

      {/* ── Project Health & Next Step ──────────────────────────────────── */}
      <ProjectHealthBar projectId={projectId!} boqs={boqs} boqDetails={boqDetails} />

      {/* ── Summary Cards ───────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
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

      {/* ── Tab Bar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 mb-6 border-b border-border-light">
        {([
          { key: 'dashboard' as ProjectTab, label: t('projects.dashboard', { defaultValue: 'Dashboard' }), icon: <LayoutDashboard size={15} /> },
          { key: 'overview' as ProjectTab, label: t('projects.overview'), icon: <Table2 size={15} /> },
          { key: 'schedule' as ProjectTab, label: t('projects.4d_schedule'), icon: <CalendarClock size={15} /> },
          { key: 'budget' as ProjectTab, label: t('projects.5d_budget'), icon: <Wallet size={15} /> },
          { key: 'tendering' as ProjectTab, label: t('projects.tendering'), icon: <Gavel size={15} /> },
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
            <div className="space-y-6 animate-fade-in">
              {/* KPI Cards Row */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Budget consumed */}
                <Card padding="md" className="relative overflow-hidden">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_budget_consumed', { defaultValue: 'Budget Consumed' })}
                      </p>
                      <p className="mt-1.5 text-2xl font-bold text-content-primary tabular-nums">
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
                        : 'bg-oe-blue-subtle text-oe-blue'
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
                </Card>

                {/* Schedule progress */}
                <Card padding="md">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_schedule_progress', { defaultValue: 'Schedule Progress' })}
                      </p>
                      <p className="mt-1.5 text-2xl font-bold text-content-primary tabular-nums">
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
                </Card>

                {/* Quality score */}
                <Card padding="md">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_quality', { defaultValue: 'Quality Score' })}
                      </p>
                      <p className="mt-1.5 text-2xl font-bold text-content-primary tabular-nums">
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
                        ? 'bg-semantic-success-bg text-[#15803d]'
                        : parseFloat(dashboardData.quality.validation_score) >= 0.5
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-surface-secondary text-content-tertiary'
                    }`}>
                      <ShieldCheck size={20} strokeWidth={1.75} />
                    </div>
                  </div>
                </Card>

                {/* Open items count */}
                <Card padding="md">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                        {t('projects.dash_open_items', { defaultValue: 'Open Items' })}
                      </p>
                      <p className="mt-1.5 text-2xl font-bold text-content-primary tabular-nums">
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
                </Card>
              </div>

              {/* Budget section — horizontal stacked bar */}
              <Card padding="md">
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
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Schedule section */}
                <Card padding="md">
                  <div className="flex items-center gap-2 mb-4">
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
                  <div className="flex items-center gap-2 mb-4">
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
                      },
                      {
                        label: t('projects.dash_submittals', { defaultValue: 'Submittals' }),
                        count: dashboardData.communication.open_submittals,
                        icon: <FileCheck size={14} />,
                        color: 'text-[#7c3aed]',
                        bg: 'bg-[#7c3aed]/10',
                      },
                      {
                        label: t('projects.dash_tasks', { defaultValue: 'Tasks' }),
                        count: dashboardData.communication.open_tasks,
                        icon: <ClipboardList size={14} />,
                        color: 'text-[#0891b2]',
                        bg: 'bg-[#0891b2]/10',
                      },
                      {
                        label: t('projects.dash_ncrs', { defaultValue: 'NCRs' }),
                        count: dashboardData.quality.ncrs_open,
                        icon: <AlertTriangle size={14} />,
                        color: dashboardData.quality.ncrs_open > 0 ? 'text-semantic-error' : 'text-content-tertiary',
                        bg: dashboardData.quality.ncrs_open > 0 ? 'bg-semantic-error-bg' : 'bg-surface-secondary',
                      },
                    ].map((item) => (
                      <div key={item.label} className="rounded-lg border border-border-light p-3">
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
                      </div>
                    ))}
                  </div>
                  {/* Procurement summary */}
                  <div className="mt-3 pt-3 border-t border-border-light">
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
                  </div>
                </Card>
              </div>

              {/* Bottom row: Recent Activity + Quick Actions */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
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
                          rfi_created: 'bg-oe-blue-subtle text-oe-blue',
                          task_created: 'bg-[#0891b2]/10 text-[#0891b2]',
                          change_order: 'bg-amber-100 text-amber-600',
                          document_uploaded: 'bg-[#7c3aed]/10 text-[#7c3aed]',
                          punch_item: 'bg-semantic-error-bg text-semantic-error',
                          field_report: 'bg-semantic-success-bg text-[#15803d]',
                        };
                        return (
                          <div key={`${item.type}-${item.title.slice(0, 30)}-${idx}`} className="flex items-center gap-3 px-5 py-3">
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
                          </div>
                        );
                      })}
                    </div>
                  )}
                </Card>

                {/* Quick Actions */}
                <Card padding="md">
                  <div className="flex items-center gap-2 mb-4">
                    <Sparkles size={16} className="text-content-tertiary" />
                    <h3 className="text-sm font-semibold text-content-primary">
                      {t('projects.dash_quick_actions', { defaultValue: 'Quick Actions' })}
                    </h3>
                  </div>
                  <div className="space-y-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<Plus size={14} />}
                      onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                    >
                      {t('projects.new_boq', { defaultValue: 'New BOQ' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<MessageSquare size={14} />}
                      onClick={() => navigate('/rfi')}
                    >
                      {t('projects.dash_new_rfi', { defaultValue: 'New RFI' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<ClipboardList size={14} />}
                      onClick={() => navigate('/tasks')}
                    >
                      {t('projects.dash_new_task', { defaultValue: 'New Task' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<ShieldCheck size={14} />}
                      onClick={() => navigate('/validation')}
                    >
                      {t('projects.dash_run_validation', { defaultValue: 'Run Validation' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<FileSpreadsheet size={14} />}
                      onClick={() => navigate('/reports')}
                    >
                      {t('projects.dash_generate_report', { defaultValue: 'Generate Report' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<FolderOpen size={14} />}
                      onClick={() => navigate('/documents')}
                    >
                      {t('projects.dash_documents_link', { defaultValue: 'Documents' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<Calendar size={14} />}
                      onClick={() => navigate('/schedule')}
                    >
                      {t('projects.dash_schedule_link', { defaultValue: 'Schedule' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<Wallet size={14} />}
                      onClick={() => navigate('/finance')}
                    >
                      {t('projects.dash_finance_link', { defaultValue: 'Finance' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<HardHat size={14} />}
                      onClick={() => navigate('/safety')}
                    >
                      {t('projects.dash_safety_link', { defaultValue: 'Safety' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="w-full justify-start"
                      icon={<Package size={14} />}
                      onClick={() => navigate('/procurement')}
                    >
                      {t('projects.dash_procurement_link', { defaultValue: 'Procurement' })}
                    </Button>
                  </div>
                  {/* Document stats */}
                  <div className="mt-4 pt-3 border-t border-border-light">
                    <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider mb-2">
                      {t('projects.dash_documents', { defaultValue: 'Documents' })}
                    </p>
                    <div className="flex items-center gap-3 text-xs text-content-secondary">
                      <span><strong className="text-content-primary">{dashboardData.documents.total}</strong> {t('projects.dash_total', { defaultValue: 'total' })}</span>
                      <span><strong className="text-content-primary">{dashboardData.documents.published}</strong> {t('projects.dash_published', { defaultValue: 'published' })}</span>
                      {dashboardData.documents.pending_transmittals > 0 && (
                        <span className="text-amber-600">
                          <strong>{dashboardData.documents.pending_transmittals}</strong> {t('projects.dash_pending', { defaultValue: 'pending' })}
                        </span>
                      )}
                    </div>
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
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue transition-transform group-hover:scale-105"
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

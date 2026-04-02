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
} from 'lucide-react';
import { Button, Card, CardHeader, Badge, Skeleton, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { projectsApi } from './api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
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

type ProjectTab = 'overview' | 'schedule' | 'budget' | 'tendering';

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
  const res = await fetch(`/api/v1/boq/boqs/${boqId}/import/smart`, {
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
          Drop your file here, or click to browse
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          Supports Excel, CSV, PDF, photos, and CAD/BIM files (Revit, IFC, DWG, DGN)
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
                {t('common.import', { defaultValue: 'Import' })} Document
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue">
                <Sparkles size={10} />
                AI-powered
              </span>
            </div>
            <p className="mt-0.5 text-sm text-content-secondary">
              Into: {boqName}
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
                            <p>CAD converter not installed.</p>
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
                  <p className="text-sm font-medium text-[#15803d]">Import complete</p>
                  <p className="text-xs text-[#15803d]/80">
                    {result.imported} positions imported
                    {(result.skipped ?? 0) > 0 && `, ${result.skipped} rows skipped`}
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
                    Direct
                  </span>
                )}
              </div>

              {/* CAD info banner */}
              {result.method === 'cad_ai' && result.cad_elements != null && (
                <div className="flex items-center gap-2 rounded-lg bg-oe-blue-subtle/50 px-4 py-2.5 text-xs text-oe-blue">
                  <span className="font-medium">
                    {result.cad_elements} CAD elements
                  </span>
                  <span className="text-oe-blue/60">
                    extracted from .{result.cad_format} file via DDC converter
                  </span>
                </div>
              )}

              {/* Stats grid */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">{result.imported}</p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                    Imported
                  </p>
                </div>
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">
                    {result.total_items ?? result.total_rows ?? 0}
                  </p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                    Total items
                  </p>
                </div>
                <div className="rounded-lg bg-surface-secondary px-3 py-2 text-center">
                  <p className="text-lg font-bold text-content-primary">{result.errors.length}</p>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">Errors</p>
                </div>
              </div>

              {/* Error details */}
              {result.errors.length > 0 && (
                <div className="rounded-lg border border-semantic-error/20 bg-semantic-error-bg/50 px-4 py-3">
                  <p className="text-xs font-medium text-semantic-error mb-2">Error details:</p>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {result.errors.map((err, i) => (
                      <p key={i} className="text-xs text-semantic-error/80">
                        {err.row ? `Row ${err.row}: ` : err.item ? `${err.item}: ` : ''}
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
              Done
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
            {this.props.fallbackTitle || 'Something went wrong'}
          </h3>
          <p className="mt-1 text-sm text-content-secondary max-w-md">
            {this.props.fallbackDescription ||
              'Unable to load this section. Please try again.'}
          </p>
          <button
            onClick={this.handleRetry}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-surface-secondary px-4 py-2 text-sm font-medium text-content-primary hover:bg-surface-tertiary transition-colors"
          >
            <RefreshCw size={14} />
            Retry
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

  const [activeTab, setActiveTab] = useState<ProjectTab>('overview');
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({ name: '', description: '', region: '', currency: '' });

  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  const updateMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; region?: string; currency?: string }) =>
      projectsApi.update(projectId!, data),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setActiveProject(projectId!, updated.name);
      setIsEditing(false);
      addToast({ type: 'success', title: t('toasts.project_updated', { defaultValue: 'Project updated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // Fetch project
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

  // Set as active project in global context
  useEffect(() => {
    if (project && projectId) {
      setActiveProject(projectId, project.name);
    }
  }, [project, projectId, setActiveProject]);

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
    queryFn: () => apiGet<BudgetDashboard>(`/v1/costmodel/projects/${projectId}/5d/dashboard`),
    enabled: !!projectId && activeTab === 'budget',
  });

  const { data: tenderPackages, isLoading: tenderingLoading } = useQuery({
    queryKey: ['tenderPackages', projectId],
    queryFn: () => apiGet<TenderPackage[]>(`/v1/tendering/packages/?project_id=${projectId}`),
    enabled: !!projectId && activeTab === 'tendering',
  });

  // ── Loading state ──────────────────────────────────────────────────────
  if (projectLoading) {
    return (
      <div className="max-w-content mx-auto space-y-6 animate-fade-in">
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
      <div className="max-w-content mx-auto">
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
    <div className="max-w-content mx-auto animate-fade-in">
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
                  icon={<Table2 size={24} strokeWidth={1.5} />}
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
                icon={<CalendarClock size={24} strokeWidth={1.5} />}
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
                icon={<Wallet size={24} strokeWidth={1.5} />}
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
                        {budgetDashboard.items!.map((item, idx) => (
                          <tr key={idx} className="hover:bg-surface-secondary transition-colors">
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
                icon={<Gavel size={24} strokeWidth={1.5} />}
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

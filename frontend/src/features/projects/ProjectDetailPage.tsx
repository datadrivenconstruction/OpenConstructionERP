import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Table2,
  DollarSign,
  Layers,
  ShieldCheck,
  Upload,
  FileSpreadsheet,
  X,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
} from 'lucide-react';
import { Button, Card, CardHeader, Badge, Skeleton, EmptyState } from '@/shared/ui';
import { projectsApi } from './api';

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
// Helpers
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'oe_access_token';

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchBoqs(projectId: string): Promise<BOQSummary[]> {
  const res = await fetch(`/api/v1/boq/boqs/?project_id=${projectId}`, {
    headers: { ...getAuthHeaders(), Accept: 'application/json' },
  });
  if (!res.ok) return [];
  return res.json();
}

async function fetchBoqDetail(boqId: string): Promise<BOQDetail> {
  const res = await fetch(`/api/v1/boq/boqs/${boqId}`, {
    headers: { ...getAuthHeaders(), Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`Failed to fetch BOQ ${boqId}`);
  return res.json();
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
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
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
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  variant?: 'default' | 'success' | 'blue';
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
                                href="https://github.com/datadrivenconstructionIO/ddc-community-toolkit/releases"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline font-medium hover:text-semantic-error"
                              >
                                GitHub
                              </a>{' '}
                              and place .exe files in{' '}
                              <code className="bg-semantic-error/10 px-1 rounded">
                                ~/.openestimator/converters/
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
// Main Page
// ---------------------------------------------------------------------------

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [importTarget, setImportTarget] = useState<{
    boqId: string;
    boqName: string;
  } | null>(null);

  // Fetch project
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

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
          title="Project not found"
          description="The project you are looking for does not exist or has been deleted."
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
      {/* Back link */}
      <button
        onClick={() => navigate('/projects')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('projects.title')}
      </button>

      {/* ── Project Info Card ───────────────────────────────────────────── */}
      <Card padding="lg" className="mb-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-content-primary">{project.name}</h1>
              <Badge variant={statusVariant[project.status] ?? 'neutral'} size="md" dot>
                {project.status}
              </Badge>
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
                Created {formatDate(project.created_at)}
              </span>
            </div>
          </div>
        </div>
      </Card>

      {/* ── Summary Cards ───────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <SummaryCard
          label={t('boq.grand_total')}
          value={formatCurrency(stats.totalBudget, currency)}
          icon={<DollarSign size={20} strokeWidth={1.75} />}
          variant="blue"
        />
        <SummaryCard
          label="BOQs"
          value={String(stats.boqCount)}
          icon={<Table2 size={20} strokeWidth={1.75} />}
        />
        <SummaryCard
          label="Positions"
          value={String(stats.totalPositions)}
          icon={<Layers size={20} strokeWidth={1.75} />}
        />
        <SummaryCard
          label={t('validation.score')}
          value={
            stats.avgValidationScore > 0
              ? `${(stats.avgValidationScore * 100).toFixed(0)}%`
              : '--'
          }
          icon={<ShieldCheck size={20} strokeWidth={1.75} />}
          variant={stats.avgValidationScore >= 0.8 ? 'success' : 'default'}
        />
      </div>

      {/* ── BOQ List ────────────────────────────────────────────────────── */}
      <Card padding="none">
        <div className="px-6 pt-6 pb-2">
          <CardHeader
            title={t('boq.title')}
            subtitle="Bills of Quantities for this project"
            action={
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Table2 size={14} />}
                  onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                >
                  New BOQ
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
                title="No BOQs yet"
                description="Create a Bill of Quantities to start estimating costs for this project."
                action={
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Table2 size={14} />}
                    onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                  >
                    Create BOQ
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
                        <span>{posCount} positions</span>
                        <span className="text-border">|</span>
                        <span className="font-medium tabular-nums">
                          {formatCurrency(grandTotal, currency)}
                        </span>
                        {boq.updated_at && (
                          <>
                            <span className="text-border">|</span>
                            <span className="flex items-center gap-1">
                              <Clock size={11} />
                              {formatDate(boq.updated_at)}
                            </span>
                          </>
                        )}
                      </div>
                    </button>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={statusVariant[boq.status] ?? 'neutral'}
                        size="sm"
                      >
                        {boq.status}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Upload size={14} />}
                        onClick={(e) => {
                          e.stopPropagation();
                          setImportTarget({ boqId: boq.id, boqName: boq.name });
                        }}
                      >
                        {t('common.import')}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

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

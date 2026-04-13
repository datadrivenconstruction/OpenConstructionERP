import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  ClipboardCheck,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Download,
  Loader2,
  Columns3,
  Zap,
  Droplets,
  Flame,
  Box,
  Droplet,
  Eye,
  MapPin,
  Calendar,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchInspections,
  createInspection,
  completeInspection,
  type Inspection,
  type InspectionType,
  type InspectionResult,
  type InspectionStatus,
  type CreateInspectionPayload,
} from './api';

/* -- Constants ------------------------------------------------------------- */

interface Project {
  id: string;
  name: string;
}

const INSPECTION_TYPE_COLORS: Record<
  InspectionType,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  structural: 'blue',
  electrical: 'warning',
  plumbing: 'neutral',
  fire_safety: 'error',
  concrete: 'blue',
  concrete_pour: 'blue',
  waterproofing: 'neutral',
  mep: 'warning',
  fire_stopping: 'error',
  handover: 'success',
  general: 'neutral',
};

const RESULT_CONFIG: Record<
  InspectionResult,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  pass: { variant: 'success', cls: '' },
  fail: { variant: 'error', cls: '' },
  partial: { variant: 'warning', cls: '' },
};

const STATUS_CONFIG: Record<
  InspectionStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  scheduled: { variant: 'blue', cls: '' },
  in_progress: { variant: 'warning', cls: '' },
  completed: { variant: 'success', cls: '' },
  cancelled: {
    variant: 'neutral',
    cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  },
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const INSPECTION_TYPES: InspectionType[] = [
  'structural',
  'electrical',
  'plumbing',
  'fire_safety',
  'concrete',
  'waterproofing',
  'general',
];

const TYPE_CARD_CONFIG: Record<InspectionType, { icon: React.ElementType; color: string }> = {
  concrete: { icon: Box, color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800' },
  concrete_pour: { icon: Box, color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800' },
  waterproofing: { icon: Droplet, color: 'text-cyan-600 bg-cyan-50 border-cyan-200 dark:text-cyan-400 dark:bg-cyan-950/30 dark:border-cyan-800' },
  mep: { icon: Zap, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  electrical: { icon: Zap, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  plumbing: { icon: Droplets, color: 'text-indigo-600 bg-indigo-50 border-indigo-200 dark:text-indigo-400 dark:bg-indigo-950/30 dark:border-indigo-800' },
  fire_safety: { icon: Flame, color: 'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800' },
  fire_stopping: { icon: Flame, color: 'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800' },
  structural: { icon: Columns3, color: 'text-purple-600 bg-purple-50 border-purple-200 dark:text-purple-400 dark:bg-purple-950/30 dark:border-purple-800' },
  handover: { icon: Eye, color: 'text-green-600 bg-green-50 border-green-200 dark:text-green-400 dark:bg-green-950/30 dark:border-green-800' },
  general: { icon: Eye, color: 'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700' },
};

const INSPECTION_STATUSES: InspectionStatus[] = [
  'scheduled',
  'in_progress',
  'completed',
  'cancelled',
];

/* -- Create Inspection Modal ----------------------------------------------- */

interface InspectionFormData {
  title: string;
  inspection_type: InspectionType;
  date: string;
  inspector: string;
  location: string;
}

const todayStr = () => new Date().toISOString().slice(0, 10);

const EMPTY_FORM: InspectionFormData = {
  title: '',
  inspection_type: 'general',
  date: todayStr(),
  inspector: '',
  location: '',
};

function CreateInspectionModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
}: {
  onClose: () => void;
  onSubmit: (data: InspectionFormData) => void;
  isPending: boolean;
  projectName?: string;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<InspectionFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof InspectionFormData>(key: K, value: InspectionFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const dateError = touched && form.date.trim().length === 0;
  const canSubmit = form.title.trim().length > 0 && form.date.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('inspections.new_inspection', { defaultValue: 'New Inspection' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('inspections.new_inspection', { defaultValue: 'New Inspection' })}
            </h2>
            {projectName && (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('common.creating_in_project', {
                  defaultValue: 'In {{project}}',
                  project: projectName,
                })}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-5">
          {/* ── Inspection Type ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('inspections.field_type', { defaultValue: 'Inspection Type' })}
            </label>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {INSPECTION_TYPES.map((it) => {
                const cfg = TYPE_CARD_CONFIG[it];
                const TypeIcon = cfg.icon;
                const selected = form.inspection_type === it;
                return (
                  <button
                    key={it}
                    type="button"
                    onClick={() => set('inspection_type', it)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                      selected
                        ? cfg.color + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <TypeIcon size={18} />
                    <span className="text-2xs font-medium leading-tight">
                      {t(`inspections.type_${it}`, {
                        defaultValue: it.replace(/_/g, ' '),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Details Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <ClipboardCheck size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('inspections.section_details', { defaultValue: 'Inspection Details' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('inspections.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('inspections.title_placeholder', {
                defaultValue: 'e.g. Foundation Concrete Pour - Grid A1-A5',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('inspections.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* ── Schedule & Assignment Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <Calendar size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('inspections.section_schedule', { defaultValue: 'Schedule & Assignment' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Two-column: Date + Inspector */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('inspections.field_date', { defaultValue: 'Planned Date' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                type="date"
                value={form.date}
                onChange={(e) => {
                  set('date', e.target.value);
                  setTouched(true);
                }}
                className={clsx(
                  inputCls,
                  dateError &&
                    'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
              />
              {dateError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('inspections.date_required', { defaultValue: 'Date is required' })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('inspections.field_inspector', { defaultValue: 'Inspector' })}
              </label>
              <input
                value={form.inspector}
                onChange={(e) => set('inspector', e.target.value)}
                className={inputCls}
                placeholder={t('inspections.inspector_placeholder', {
                  defaultValue: 'Name of the inspector',
                })}
              />
            </div>
          </div>

          {/* ── Location Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <MapPin size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('inspections.section_location', { defaultValue: 'Location' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('inspections.field_location', { defaultValue: 'Location' })}
            </label>
            <input
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              className={inputCls}
              placeholder={t('inspections.location_placeholder', {
                defaultValue: 'e.g. Building A, Level 3, Zone C',
              })}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {t('inspections.create_inspection', { defaultValue: 'Create Inspection' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Inspection Row (expandable) ------------------------------------------- */

const InspectionRow = React.memo(function InspectionRow({
  inspection,
  onComplete,
  onCreateDefect,
}: {
  inspection: Inspection;
  onComplete: (id: string) => void;
  onCreateDefect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[inspection.status] ?? STATUS_CONFIG.scheduled;
  const typeCfg = INSPECTION_TYPE_COLORS[inspection.inspection_type] ?? 'neutral';
  const resultCfg = inspection.result ? RESULT_CONFIG[inspection.result] : null;

  return (
    <div className="border-b border-border-light last:border-b-0">
      {/* Main row */}
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* Inspection # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          INS-{String(inspection.inspection_number).padStart(3, '0')}
        </span>

        {/* Title */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {inspection.title}
        </span>

        {/* Type badge */}
        <Badge variant={typeCfg} size="sm">
          {t(`inspections.type_${inspection.inspection_type}`, {
            defaultValue: inspection.inspection_type.replace(/_/g, ' '),
          })}
        </Badge>

        {/* Inspector */}
        <span className="text-xs text-content-tertiary w-28 truncate shrink-0 hidden md:block">
          {inspection.inspector || '\u2014'}
        </span>

        {/* Date */}
        <span className="text-xs text-content-tertiary w-24 shrink-0 hidden lg:block">
          <DateDisplay value={inspection.date} />
        </span>

        {/* Result badge */}
        {resultCfg ? (
          <Badge variant={resultCfg.variant} size="sm" className={resultCfg.cls}>
            {t(`inspections.result_${inspection.result}`, {
              defaultValue:
                inspection.result
                  ? inspection.result.charAt(0).toUpperCase() + inspection.result.slice(1)
                  : '',
            })}
          </Badge>
        ) : (
          <span className="text-xs text-content-tertiary w-16 text-center">{'\u2014'}</span>
        )}

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`inspections.status_${inspection.status}`, {
            defaultValue: inspection.status.replace(/_/g, ' '),
          })}
        </Badge>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Checklist */}
          {inspection.checklist && inspection.checklist.length > 0 && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
                {t('inspections.label_checklist', { defaultValue: 'Checklist' })}
              </p>
              <div className="space-y-1.5">
                {inspection.checklist.map((item) => (
                  <div
                    key={item.id}
                    className={clsx(
                      'flex items-start gap-2 text-sm rounded-md px-2 py-1',
                      item.critical && !item.passed && 'bg-red-50 dark:bg-red-950/20',
                    )}
                  >
                    {item.passed ? (
                      <CheckCircle2 size={14} className="text-semantic-success mt-0.5 shrink-0" />
                    ) : (
                      <XCircle size={14} className="text-semantic-error mt-0.5 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <span
                        className={clsx(
                          'text-content-primary',
                          item.critical && 'font-medium',
                        )}
                      >
                        {item.description}
                      </span>
                      {item.critical && (
                        <Badge variant="error" size="sm" className="ml-2">
                          <AlertTriangle size={10} className="mr-0.5" />
                          {t('inspections.critical', { defaultValue: 'Critical' })}
                        </Badge>
                      )}
                      {item.notes && (
                        <p className="text-xs text-content-tertiary mt-0.5">{item.notes}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notes */}
          {inspection.notes && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('inspections.label_notes', { defaultValue: 'Notes' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {inspection.notes}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {(inspection.status === 'scheduled' || inspection.status === 'in_progress') && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onComplete(inspection.id);
                }}
              >
                <CheckCircle2 size={14} className="mr-1.5" />
                {t('inspections.action_complete', { defaultValue: 'Complete Inspection' })}
              </Button>
            )}
            {inspection.result && (inspection.result === 'fail' || inspection.result === 'partial') && (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCreateDefect(inspection.id);
                  }}
                >
                  <XCircle size={14} className="mr-1.5" />
                  {t('inspections.create_defect', { defaultValue: 'Create Punchlist Item' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate('/ncr');
                  }}
                >
                  <AlertTriangle size={14} className="mr-1.5" />
                  {t('inspections.create_ncr', { defaultValue: 'Create NCR' })}
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

/* -- Export helper --------------------------------------------------------- */

async function downloadExcelExport(url: string, fallbackFilename: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`/api${url}`, { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || fallbackFilename;
  triggerDownload(blob, filename);
}

/* -- Main Page ------------------------------------------------------------- */

export function InspectionsPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<InspectionStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: inspections = [], isLoading } = useQuery({
    queryKey: ['inspections', projectId, statusFilter],
    queryFn: () =>
      fetchInspections({
        project_id: projectId,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return inspections;
    const q = searchQuery.toLowerCase();
    return inspections.filter(
      (ins) =>
        ins.title.toLowerCase().includes(q) ||
        String(ins.inspection_number).includes(q) ||
        (ins.inspector && ins.inspector.toLowerCase().includes(q)),
    );
  }, [inspections, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = inspections.length;
    const scheduled = inspections.filter((i) => i.status === 'scheduled').length;
    const passed = inspections.filter((i) => i.result === 'pass').length;
    const failed = inspections.filter((i) => i.result === 'fail').length;
    return { total, scheduled, passed, failed };
  }, [inspections]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['inspections'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateInspectionPayload) => createInspection(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('inspections.created', { defaultValue: 'Inspection created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) => completeInspection(id),
    onSuccess: (data) => {
      invalidateAll();
      const isFail = data?.result === 'fail' || data?.result === 'partial';
      addToast(
        {
          type: 'success',
          title: t('inspections.completed', { defaultValue: 'Inspection completed' }),
          message: isFail
            ? t('inspections.completed_fail_hint', { defaultValue: 'Inspection failed. Create a punchlist item?' })
            : undefined,
          action: isFail && data?.id
            ? {
                label: t('inspections.create_defect', { defaultValue: 'Create Punchlist Item' }),
                onClick: () => createDefectMut.mutate(data.id),
              }
            : undefined,
        },
        isFail ? { duration: 8000 } : undefined,
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: InspectionFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        inspection_type: formData.inspection_type,
        inspection_date: formData.date,
        inspector_id: formData.inspector || undefined,
        location: formData.location || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/inspections/export?project_id=${projectId}`,
        'inspections.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('inspections.export_success', { defaultValue: 'Export complete' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const { confirm, ...confirmProps } = useConfirm();

  const handleComplete = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('inspections.confirm_complete_title', { defaultValue: 'Complete inspection?' }),
        message: t('inspections.confirm_complete_msg', { defaultValue: 'This inspection will be marked as completed.' }),
        confirmLabel: t('inspections.mark_complete', { defaultValue: 'Complete' }),
        variant: 'warning',
      });
      if (ok) completeMut.mutate(id);
    },
    [completeMut, confirm, t],
  );

  const createDefectMut = useMutation({
    mutationFn: (inspectionId: string) =>
      apiPost<{ punch_item_id: string; title: string }>(
        `/v1/inspections/${inspectionId}/create-defect`,
        {},
      ),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('inspections.defect_created', { defaultValue: 'Punchlist item created' }),
        message: data.title,
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateDefect = useCallback(
    (id: string) => {
      createDefectMut.mutate(id);
    },
    [createDefectMut],
  );

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('inspections.title', { defaultValue: 'Inspections' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('inspections.page_title', { defaultValue: 'Quality Inspections' })}
        </h1>

        <div className="flex items-center gap-2 shrink-0">
          {!routeProjectId && projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              <option value="" disabled>
                {t('inspections.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="secondary"
            size="sm"
            icon={
              exportMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )
            }
            onClick={() => exportMut.mutate()}
            disabled={exportMut.isPending || !projectId}
          >
            {t('common.export_excel', { defaultValue: 'Export Excel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            icon={<Plus size={14} />}
          >
            {t('inspections.new_inspection', { defaultValue: 'New Inspection' })}
          </Button>
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-4 py-3">
          <AlertTriangle size={18} className="text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{t('common.no_project_selected', { defaultValue: 'No project selected' })}</p>
            <p className="text-xs text-amber-600 dark:text-amber-400">{t('common.select_project_hint', { defaultValue: 'Select a project from the header to view and manage items.' })}</p>
          </div>
        </div>
      )}

      {projectId ? (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('inspections.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('inspections.stat_scheduled', { defaultValue: 'Scheduled' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-oe-blue">{stats.scheduled}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('inspections.stat_passed', { defaultValue: 'Passed' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-semantic-success">
            {stats.passed}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('inspections.stat_failed', { defaultValue: 'Failed' })}
          </p>
          <p
            className={clsx(
              'text-2xl font-bold mt-1 tabular-nums',
              stats.failed > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.failed}
          </p>
        </Card>
      </div>

      {/* Toolbar */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('inspections.search_placeholder', {
              defaultValue: 'Search inspections...',
            })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as InspectionStatus | '')}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('inspections.filter_all_statuses', { defaultValue: 'All Statuses' })}
            </option>
            {INSPECTION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`inspections.status_${s}`, {
                  defaultValue: s.replace(/_/g, ' '),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('inspections.no_results', { defaultValue: 'No matching inspections' })
                : t('inspections.no_inspections', { defaultValue: 'No inspections yet' })
            }
            description={
              searchQuery || statusFilter
                ? t('inspections.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('inspections.no_inspections_hint', {
                    defaultValue: 'Schedule your first quality inspection',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('inspections.new_inspection', {
                      defaultValue: 'New Inspection',
                    }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('inspections.showing_count', {
                defaultValue: '{{count}} inspections',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('inspections.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-24 text-center">
                  {t('inspections.col_type', { defaultValue: 'Type' })}
                </span>
                <span className="w-28 hidden md:block">
                  {t('inspections.col_inspector', { defaultValue: 'Inspector' })}
                </span>
                <span className="w-24 hidden lg:block">
                  {t('inspections.col_date', { defaultValue: 'Date' })}
                </span>
                <span className="w-16 text-center">
                  {t('inspections.col_result', { defaultValue: 'Result' })}
                </span>
                <span className="w-24 text-center">
                  {t('inspections.col_status', { defaultValue: 'Status' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((inspection) => (
                <InspectionRow
                  key={inspection.id}
                  inspection={inspection}
                  onComplete={handleComplete}
                  onCreateDefect={handleCreateDefect}
                />
              ))}
            </Card>
          </>
        )}
      </div>
      </>
      ) : (
        <EmptyState
          icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
          title={t('inspections.no_project', { defaultValue: 'No project selected' })}
          description={t('inspections.select_project', { defaultValue: 'Open a project first to view and manage inspections.' })}
        />
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateInspectionModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          projectName={projectName}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

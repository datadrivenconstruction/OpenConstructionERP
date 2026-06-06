import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
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
  Pencil,
  Trash2,
  Play,
  Info,
  ListChecks,
  MinusCircle,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, RecoveryCard, SkeletonTable, IntroRichText } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { SectionIntro } from '@/features/validation';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchInspections,
  createInspection,
  completeInspection,
  createNcrFromInspection,
  updateInspection,
  deleteInspection,
  type Inspection,
  type InspectionType,
  type InspectionResult,
  type InspectionStatus,
  type CreateInspectionPayload,
  type UpdateInspectionPayload,
  type ChecklistEntryPayload,
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
  failed: { variant: 'error', cls: '' },
  cancelled: {
    variant: 'neutral',
    cls: '',
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

interface ChecklistRow {
  question: string;
  critical: boolean;
  notes: string;
}

interface InspectionFormData {
  title: string;
  inspection_type: InspectionType;
  date: string;
  inspector: string;
  location: string;
  checklist: ChecklistRow[];
}

const todayStr = () => new Date().toISOString().slice(0, 10);

const EMPTY_FORM: InspectionFormData = {
  title: '',
  inspection_type: 'general',
  date: todayStr(),
  inspector: '',
  location: '',
  checklist: [],
};

/**
 * Map the modal's checklist rows to the wire payload (drops blank rows).
 *
 * Items are created without a pass/fail response — they describe what to verify
 * on site. The overall inspection result (pass/fail/partial) is captured when the
 * inspection is completed.
 */
function checklistToPayload(rows: ChecklistRow[]): ChecklistEntryPayload[] {
  return rows
    .filter((r) => r.question.trim().length > 0)
    .map((r) => ({
      question: r.question.trim(),
      response_type: 'pass_fail',
      critical: r.critical,
      notes: r.notes.trim() || undefined,
    }));
}

function CreateInspectionModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
  initialData,
}: {
  onClose: () => void;
  onSubmit: (data: InspectionFormData) => void;
  isPending: boolean;
  projectName?: string;
  initialData?: InspectionFormData | null;
}) {
  const { t } = useTranslation();
  const isEdit = !!initialData;
  const [form, setForm] = useState<InspectionFormData>(initialData ?? EMPTY_FORM);
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label={
          isEdit
            ? t('inspections.edit_inspection', { defaultValue: 'Edit Inspection' })
            : t('inspections.new_inspection', { defaultValue: 'New Inspection' })
        }
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {isEdit
                ? t('inspections.edit_inspection', { defaultValue: 'Edit Inspection' })
                : t('inspections.new_inspection', { defaultValue: 'New Inspection' })}
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
            <label htmlFor="inspection-title" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('inspections.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              id="inspection-title"
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
              <label htmlFor="inspection-date" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('inspections.field_date', { defaultValue: 'Planned Date' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                id="inspection-date"
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
              <label htmlFor="inspection-inspector" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('inspections.field_inspector', { defaultValue: 'Inspector' })}
              </label>
              <input
                id="inspection-inspector"
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
            <label htmlFor="inspection-location" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('inspections.field_location', { defaultValue: 'Location' })}
            </label>
            <input
              id="inspection-location"
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              className={inputCls}
              placeholder={t('inspections.location_placeholder', {
                defaultValue: 'e.g. Building A, Level 3, Zone C',
              })}
            />
          </div>

          {/* ── Checklist Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <ListChecks size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('inspections.section_checklist', { defaultValue: 'Checklist' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>
          <p className="-mt-2 text-xs text-content-tertiary">
            {t('inspections.checklist_help', {
              defaultValue:
                'Add the items to verify on site. When you complete the inspection you mark each item pass/fail; failed items pre-fill any Punch List item or NCR you raise.',
            })}
          </p>
          <div className="space-y-2">
            {form.checklist.map((row, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-border bg-surface-primary p-3 space-y-2"
              >
                <div className="flex items-start gap-2">
                  <input
                    value={row.question}
                    onChange={(e) =>
                      set(
                        'checklist',
                        form.checklist.map((r, i) =>
                          i === idx ? { ...r, question: e.target.value } : r,
                        ),
                      )
                    }
                    className={inputCls}
                    placeholder={t('inspections.checklist_item_placeholder', {
                      defaultValue: 'e.g. Rebar spacing per drawing',
                    })}
                    aria-label={t('inspections.checklist_item_label', {
                      defaultValue: 'Checklist item',
                    })}
                  />
                  <button
                    type="button"
                    onClick={() =>
                      set(
                        'checklist',
                        form.checklist.filter((_, i) => i !== idx),
                      )
                    }
                    className="flex h-10 w-9 items-center justify-center rounded-lg text-content-tertiary hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 transition-colors shrink-0"
                    aria-label={t('inspections.checklist_remove', {
                      defaultValue: 'Remove checklist item',
                    })}
                  >
                    <MinusCircle size={16} />
                  </button>
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={row.critical}
                      onChange={(e) =>
                        set(
                          'checklist',
                          form.checklist.map((r, i) =>
                            i === idx ? { ...r, critical: e.target.checked } : r,
                          ),
                        )
                      }
                      className="rounded border-border text-oe-blue focus:ring-oe-blue/30"
                    />
                    <AlertTriangle size={12} className="text-semantic-error" />
                    {t('inspections.checklist_critical', { defaultValue: 'Critical (hold point)' })}
                  </label>
                  <input
                    value={row.notes}
                    onChange={(e) =>
                      set(
                        'checklist',
                        form.checklist.map((r, i) =>
                          i === idx ? { ...r, notes: e.target.value } : r,
                        ),
                      )
                    }
                    className={inputCls + ' !h-8 flex-1 text-xs'}
                    placeholder={t('inspections.checklist_notes_placeholder', {
                      defaultValue: 'Notes / acceptance criteria (optional)',
                    })}
                    aria-label={t('inspections.checklist_notes_label', {
                      defaultValue: 'Checklist item notes',
                    })}
                  />
                </div>
              </div>
            ))}
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={() =>
                set('checklist', [...form.checklist, { question: '', critical: false, notes: '' }])
              }
            >
              <Plus size={14} className="mr-1.5" />
              {t('inspections.checklist_add', { defaultValue: 'Add checklist item' })}
            </Button>
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
            ) : isEdit ? (
              <Pencil size={16} className="mr-1.5 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {isEdit
                ? t('inspections.save_changes', { defaultValue: 'Save Changes' })
                : t('inspections.create_inspection', { defaultValue: 'Create Inspection' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Record-result Dialog -------------------------------------------------- */

const RESULT_OPTIONS: {
  value: InspectionResult;
  icon: React.ElementType;
  iconCls: string;
  ringCls: string;
}[] = [
  {
    value: 'pass',
    icon: CheckCircle2,
    iconCls: 'text-semantic-success',
    ringCls: 'border-green-300 bg-green-50 ring-2 ring-green-300 dark:border-green-700 dark:bg-green-950/30',
  },
  {
    value: 'partial',
    icon: AlertTriangle,
    iconCls: 'text-amber-500',
    ringCls: 'border-amber-300 bg-amber-50 ring-2 ring-amber-300 dark:border-amber-700 dark:bg-amber-950/30',
  },
  {
    value: 'fail',
    icon: XCircle,
    iconCls: 'text-semantic-error',
    ringCls: 'border-red-300 bg-red-50 ring-2 ring-red-300 dark:border-red-700 dark:bg-red-950/30',
  },
];

function CompleteInspectionDialog({
  inspection,
  onClose,
  onConfirm,
  isPending,
}: {
  inspection: Inspection;
  onClose: () => void;
  onConfirm: (result: InspectionResult) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState<InspectionResult>('pass');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const resultLabels: Record<InspectionResult, string> = {
    pass: t('inspections.result_pass', { defaultValue: 'Pass' }),
    partial: t('inspections.result_partial', { defaultValue: 'Partial' }),
    fail: t('inspections.result_fail', { defaultValue: 'Fail' }),
  };
  const resultDescriptions: Record<InspectionResult, string> = {
    pass: t('inspections.result_pass_desc', { defaultValue: 'All checks met. No follow-up needed.' }),
    partial: t('inspections.result_partial_desc', {
      defaultValue: 'Mostly compliant with minor issues to resolve.',
    }),
    fail: t('inspections.result_fail_desc', {
      defaultValue: 'Did not meet acceptance criteria. Raise a Punch List item or NCR.',
    }),
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-md bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4"
        role="dialog"
        aria-modal="true"
        aria-label={t('inspections.record_result_title', { defaultValue: 'Record inspection result' })}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('inspections.record_result_title', { defaultValue: 'Record inspection result' })}
            </h2>
            <p className="text-xs text-content-tertiary mt-0.5 truncate">
              {inspection.inspection_number} · {inspection.title}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors shrink-0"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-2">
          <p className="text-sm text-content-secondary mb-2">
            {t('inspections.record_result_prompt', {
              defaultValue: 'Choose the outcome. A fail or partial result lets you raise a Punch List item or NCR.',
            })}
          </p>
          {RESULT_OPTIONS.map((opt) => {
            const OptIcon = opt.icon;
            const selected = result === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setResult(opt.value)}
                className={clsx(
                  'flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-all',
                  selected
                    ? opt.ringCls
                    : 'border-border bg-surface-primary hover:bg-surface-secondary',
                )}
                aria-pressed={selected}
              >
                <OptIcon size={18} className={clsx('mt-0.5 shrink-0', opt.iconCls)} />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-content-primary">
                    {resultLabels[opt.value]}
                  </span>
                  <span className="block text-xs text-content-tertiary">
                    {resultDescriptions[opt.value]}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => onConfirm(result)}
            disabled={isPending}
          >
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <CheckCircle2 size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('inspections.record_result_confirm', { defaultValue: 'Record Result' })}</span>
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
  onStart,
  onCreateDefect,
  onCreateNcr,
  onEdit,
  onDelete,
  highlight,
}: {
  inspection: Inspection;
  onComplete: (id: string) => void;
  onStart: (id: string) => void;
  onCreateDefect: (id: string) => void;
  onCreateNcr: (id: string) => void;
  onEdit: (inspection: Inspection) => void;
  onDelete: (id: string) => void;
  /** When this matches the row id (from a ?highlight deep-link) the row
   *  auto-expands, scrolls into view and flashes a highlight ring. */
  highlight?: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  // Temporary visual flash that fades out after the deep-link lands the user
  // on the right inspection. Cleared once it has fired so re-renders are calm.
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (!highlight) return;
    setExpanded(true);
    setFlash(true);
    const node = rowRef.current;
    if (node) {
      node.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    const timer = window.setTimeout(() => setFlash(false), 2400);
    return () => window.clearTimeout(timer);
  }, [highlight]);

  const statusCfg = STATUS_CONFIG[inspection.status] ?? STATUS_CONFIG.scheduled;
  const typeCfg = INSPECTION_TYPE_COLORS[inspection.inspection_type] ?? 'neutral';
  const resultCfg = inspection.result ? RESULT_CONFIG[inspection.result] : null;
  // Backend edit guard rejects (HTTP 400) when an inspection has reached a
  // terminal state. Disable the Edit button with an explanatory tooltip so we
  // never ship a control that returns an error.
  const editDisabled =
    inspection.status === 'completed' || inspection.status === 'failed';

  return (
    <div
      ref={rowRef}
      className={clsx(
        'border-b border-border-light last:border-b-0 scroll-mt-24 transition-colors duration-500',
        flash && 'bg-oe-blue/10 ring-2 ring-inset ring-oe-blue/40',
      )}
    >
      {/* Main row */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={t('inspections.toggle_details', { defaultValue: 'Toggle inspection details' })}
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((prev) => !prev)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded((prev) => !prev); } }}
      >
        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* Inspection # — backend already returns it formatted (e.g. "INS-001"). */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          {inspection.inspection_number}
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
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {inspection.status === 'scheduled' && (
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onStart(inspection.id);
                }}
              >
                <Play size={14} className="mr-1.5" />
                {t('inspections.action_start', { defaultValue: 'Start Inspection' })}
              </Button>
            )}
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
                {t('inspections.action_record_result', { defaultValue: 'Record Result' })}
              </Button>
            )}
            {inspection.result && (inspection.result === 'fail' || inspection.result === 'partial') && (
              <div className="flex flex-wrap items-center gap-2">
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
                    onCreateNcr(inspection.id);
                  }}
                >
                  <AlertTriangle size={14} className="mr-1.5" />
                  {t('inspections.create_ncr', { defaultValue: 'Create NCR' })}
                </Button>
                <span
                  className="inline-flex items-center gap-1 text-2xs text-content-tertiary"
                  title={t('inspections.punch_vs_ncr_help', {
                    defaultValue:
                      'Punch List: minor defects to fix and re-check. NCR: a formal non-conformance needing root-cause analysis, corrective action and signoff.',
                  })}
                >
                  <Info size={12} />
                  {t('inspections.punch_vs_ncr_short', {
                    defaultValue: 'Punch List for minor defects, NCR for formal non-conformances.',
                  })}
                </span>
              </div>
            )}

            {/* Edit / Delete — always available (Delete is unguarded). */}
            <div className="ml-auto flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                disabled={editDisabled}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!editDisabled) onEdit(inspection);
                }}
                className="!p-1.5 text-content-quaternary hover:text-oe-blue h-auto"
                title={
                  editDisabled
                    ? t('inspections.edit_locked', {
                        defaultValue: 'Completed or failed inspections cannot be edited',
                      })
                    : t('common.edit', { defaultValue: 'Edit' })
                }
              >
                <Pencil size={14} />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(inspection.id);
                }}
                className="!p-1.5 text-content-quaternary hover:text-red-500 h-auto"
                title={t('common.delete', { defaultValue: 'Delete' })}
              >
                <Trash2 size={14} />
              </Button>
            </div>
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
    let detail = fallbackFilename;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? 'export_failed';
    } catch {
      detail = 'export_failed';
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
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Deep-link target (e.g. from an NCR's "View Inspection"). The matching row
  // auto-expands, scrolls into view and flashes once the data has loaded.
  const highlightId = searchParams.get('highlight');

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingInspection, setEditingInspection] = useState<Inspection | null>(null);
  const [completingId, setCompletingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<InspectionStatus | ''>('');
  const [typeFilter, setTypeFilter] = useState<InspectionType | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';
  // Genuinely-selected project (route param or shared context) — used for
  // the breadcrumb so the trail never shows a first-project guess.
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const breadcrumbProjectName =
    projects.find((p) => p.id === selectedProjectId)?.name || '';

  const { data: inspections = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['inspections', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchInspections({
        project_id: projectId,
        status: statusFilter || undefined,
        type: typeFilter || undefined,
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
        ins.inspection_number.toLowerCase().includes(q) ||
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
    mutationFn: ({ id, result }: { id: string; result: InspectionResult }) =>
      completeInspection(id, result),
    onSuccess: (data) => {
      invalidateAll();
      setCompletingId(null);
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
      const checklist = checklistToPayload(formData.checklist);
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        inspection_type: formData.inspection_type,
        inspection_date: formData.date,
        inspector_id: formData.inspector || undefined,
        location: formData.location || undefined,
        checklist_data: checklist.length > 0 ? checklist : undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateInspectionPayload }) =>
      updateInspection(id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingInspection(null);
      addToast({
        type: 'success',
        title: t('inspections.updated', { defaultValue: 'Inspection updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleEditSubmit = useCallback(
    (formData: InspectionFormData) => {
      if (!editingInspection) return;
      editMut.mutate({
        id: editingInspection.id,
        data: {
          title: formData.title,
          inspection_type: formData.inspection_type,
          inspection_date: formData.date || null,
          inspector_id: formData.inspector || null,
          location: formData.location || null,
          checklist_data: checklistToPayload(formData.checklist),
        },
      });
    },
    [editMut, editingInspection],
  );

  const handleEditInspection = useCallback((inspection: Inspection) => {
    setEditingInspection(inspection);
  }, []);

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteInspection(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('inspections.deleted', { defaultValue: 'Inspection deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/inspections/export/?project_id=${projectId}`,
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

  // Opening the completion flow no longer auto-passes the inspection — it
  // opens a Pass / Fail / Partial picker so a failed inspection is recordable
  // (which unlocks the Punch List / NCR follow-up flow).
  const handleComplete = useCallback((id: string) => {
    setCompletingId(id);
  }, []);

  const handleDeleteInspection = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('inspections.confirm_delete_title', { defaultValue: 'Delete inspection?' }),
        message: t('inspections.confirm_delete_msg', {
          defaultValue: 'This inspection will be permanently deleted.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(id);
    },
    [deleteMut, confirm, t],
  );

  const createDefectMut = useMutation({
    mutationFn: (inspectionId: string) =>
      apiPost<{ punch_item_id: string; title: string }>(
        `/v1/inspections/${inspectionId}/create-defect/`,
        {},
      ),
    onSuccess: (data) => {
      addToast(
        {
          type: 'success',
          title: t('inspections.defect_created', { defaultValue: 'Punchlist item created' }),
          message: data.title,
          // Deep-link straight to the new punch item so the user opens it
          // rather than hunting the register.
          action: data.punch_item_id
            ? {
                label: t('inspections.open_punch_item', { defaultValue: 'Open punch item' }),
                onClick: () => navigate(`/punchlist?highlight=${data.punch_item_id}`),
              }
            : undefined,
        },
        { duration: 8000 },
      );
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

  // Raise a formal NCR pre-filled from the failed inspection via the real
  // backend endpoint (idempotent), then deep-link to the created NCR.
  const createNcrMut = useMutation({
    mutationFn: (inspectionId: string) => createNcrFromInspection(inspectionId),
    onSuccess: (data) => {
      addToast(
        {
          type: 'success',
          title: data.created
            ? t('inspections.ncr_created', { defaultValue: 'NCR raised' })
            : t('inspections.ncr_exists', { defaultValue: 'NCR already exists for this inspection' }),
          message: data.ncr_number,
          // Deep-link to the exact created NCR (highlight the row) rather than
          // the whole register.
          action: {
            label: t('inspections.view_ncr', { defaultValue: 'Open NCR' }),
            onClick: () =>
              navigate(data.ncr_id ? `/ncr?highlight=${data.ncr_id}` : '/ncr'),
          },
        },
        { duration: 8000 },
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateNcr = useCallback(
    (id: string) => {
      createNcrMut.mutate(id);
    },
    [createNcrMut],
  );

  // Walk a scheduled inspection into in_progress so the in_progress state is
  // actually reachable from the UI (the FSM allows scheduled -> in_progress).
  const startMut = useMutation({
    mutationFn: (id: string) => updateInspection(id, { status: 'in_progress' }),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('inspections.started', { defaultValue: 'Inspection started' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleStart = useCallback((id: string) => startMut.mutate(id), [startMut]);

  const completingInspection = completingId
    ? inspections.find((i) => i.id === completingId) ?? null
    : null;

  // Once the highlighted inspection is present in the loaded set, let the row
  // flash, then clear the ?highlight param so a refresh or back-navigation does
  // not re-trigger the highlight. Replace (no history entry) and preserve any
  // other query params.
  useEffect(() => {
    if (!highlightId) return;
    if (!inspections.some((i) => i.id === highlightId)) return;
    const timer = window.setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('highlight');
          return next;
        },
        { replace: true },
      );
    }, 2600);
    return () => window.clearTimeout(timer);
  }, [highlightId, inspections, setSearchParams]);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(selectedProjectId && breadcrumbProjectName
            ? [{ label: breadcrumbProjectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('inspections.title', { defaultValue: 'Inspections' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        subtitle={t('inspections.subtitle', {
          defaultValue: 'Schedule and record quality inspections, then raise punch items or NCRs',
        })}
        actions={
          <>
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
          </>
        }
      />

      <SectionIntro
        storageKey="inspections"
        title={t('inspections.intro_title', {
          defaultValue: 'Close the inspect-to-fix loop',
        })}
        more={
          <IntroRichText
            text={t('inspections.intro_more', {
              defaultValue:
                'Quality on site is won or lost at the inspection. A pour is checked before the concrete goes in, a fire-stopping run is verified before it is boarded over, a unit is walked at handover. The problem is what happens after a fail: the note gets lost, the defect is never tracked, and the same issue turns up at the final account. This page makes the inspection the start of a loop, not a dead end, so every fail becomes a tracked defect that someone has to close.\n\n**You put in:**\n- A scheduled inspection with a type (structural, electrical, plumbing, fire safety, concrete, waterproofing, MEP, handover and more)\n- A planned date, an inspector and a location\n- A checklist of items to verify on site, with critical items flagged as hold points\n- The outcome when the work is checked: pass, partial or fail\n\n**You get out:**\n- An inspection register with status from scheduled through in-progress to completed, plus a clear pass/fail/partial result\n- Counts of total, scheduled, passed and failed inspections at the top of the page\n- One-click creation of a Punch List item or a formal NCR from any failed or partial result, pre-filled from the inspection\n- An Excel export of the full inspection log for records and client reporting\n\n**How it works day to day:**\n1. Schedule the inspection, choose its type and add the checklist of things to verify.\n2. Start it when the inspector goes to site, then record the result as pass, partial or fail.\n3. On a fail or partial, raise a Punch List item for a minor snag, or an NCR for a formal non-conformance.\n4. The follow-up record is pre-filled from the inspection, so the defect traces straight back to the check.\n5. Re-inspect once the fix is done and the trail shows the full inspect-defect-close cycle.\n\nFailed inspections feed directly into the Punch List for minor defects and into NCRs for non-conformances needing root-cause analysis, and the same control points can be tied to ITP hold points in the QMS overview. That keeps the inspect, defect and close-out loop fully traceable across the quality cluster rather than scattered across separate tools.',
            })}
          />
        }
        links={[
          {
            label: t('inspections.intro_link_punch', { defaultValue: 'Punch List' }),
            onClick: () => navigate('/punchlist'),
          },
          {
            label: t('inspections.intro_link_ncr', { defaultValue: 'NCRs' }),
            onClick: () => navigate('/ncr'),
          },
          {
            label: t('inspections.intro_link_qms', { defaultValue: 'QMS overview' }),
            onClick: () => navigate('/qms'),
          },
        ]}
      >
        {t('inspections.intro_body', {
          defaultValue:
            'Schedule and record quality inspections (structural, MEP, concrete, handover and more) against a project. A fail or partial result lets you raise a Punch List item or an NCR in one click, keeping the inspect, defect and close-out loop fully traceable back to the QMS overview.',
        })}
      </SectionIntro>

      {projectId ? (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('inspections.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('inspections.stat_scheduled', { defaultValue: 'Scheduled' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-oe-blue">{stats.scheduled}</p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('inspections.stat_passed', { defaultValue: 'Passed' })}
          </p>
          <p className="text-lg font-semibold mt-1 tabular-nums text-semantic-success">
            {stats.passed}
          </p>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('inspections.stat_failed', { defaultValue: 'Failed' })}
          </p>
          <p
            className={clsx(
              'text-lg font-semibold mt-1 tabular-nums',
              stats.failed > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.failed}
          </p>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
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
            aria-label={t('inspections.search_placeholder', { defaultValue: 'Search inspections...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as InspectionStatus | '')}
            aria-label={t('inspections.filter_all_statuses', { defaultValue: 'All Statuses' })}
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

        {/* Type filter */}
        <div className="relative">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as InspectionType | '')}
            aria-label={t('inspections.filter_all_types', { defaultValue: 'All Types' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('inspections.filter_all_types', { defaultValue: 'All Types' })}
            </option>
            {INSPECTION_TYPES.map((it) => (
              <option key={it} value={it}>
                {t(`inspections.type_${it}`, {
                  defaultValue: it.replace(/_/g, ' '),
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
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter || typeFilter
                ? t('inspections.no_results', { defaultValue: 'No matching inspections' })
                : t('inspections.no_inspections', { defaultValue: 'No inspections yet' })
            }
            description={
              searchQuery || statusFilter || typeFilter
                ? t('inspections.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('inspections.no_inspections_hint', {
                    defaultValue: 'Schedule your first quality inspection',
                  })
            }
            action={
              !searchQuery && !statusFilter && !typeFilter
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
                  onStart={handleStart}
                  onCreateDefect={handleCreateDefect}
                  onCreateNcr={handleCreateNcr}
                  onEdit={handleEditInspection}
                  onDelete={handleDeleteInspection}
                  highlight={highlightId === inspection.id}
                />
              ))}
            </Card>
          </>
        )}
      </div>
      </>
      ) : (
        <RequiresProject
          emptyHint={t('inspections.select_project', { defaultValue: 'Open a project first to view and manage inspections.' })}
        >{null}</RequiresProject>
      )}

      {/* Create / Edit Modal — same form, prefilled in edit mode */}
      {(showCreateModal || editingInspection) && (
        <CreateInspectionModal
          onClose={() => {
            setShowCreateModal(false);
            setEditingInspection(null);
          }}
          onSubmit={editingInspection ? handleEditSubmit : handleCreateSubmit}
          isPending={editingInspection ? editMut.isPending : createMut.isPending}
          projectName={projectName}
          initialData={
            editingInspection
              ? {
                  title: editingInspection.title,
                  inspection_type: editingInspection.inspection_type,
                  date: editingInspection.date || todayStr(),
                  inspector: editingInspection.inspector || '',
                  location: editingInspection.location || '',
                  checklist: editingInspection.checklist.map((c) => ({
                    question: c.description,
                    critical: c.critical,
                    notes: c.notes,
                  })),
                }
              : null
          }
        />
      )}

      {/* Record-result Dialog (Pass / Fail / Partial) */}
      {completingInspection && (
        <CompleteInspectionDialog
          inspection={completingInspection}
          onClose={() => {
            if (!completeMut.isPending) setCompletingId(null);
          }}
          onConfirm={(result) =>
            completeMut.mutate({ id: completingInspection.id, result })
          }
          isPending={completeMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

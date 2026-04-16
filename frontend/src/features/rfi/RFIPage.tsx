import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  HelpCircle,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  DollarSign,
  Clock,
  FileText,
  Download,
  Loader2,
  MessageSquare,
  User,
  CalendarClock,
  AlertTriangle,
  Paperclip,
  ArrowRightLeft,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useCreateShortcut } from '@/shared/hooks/useCreateShortcut';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchRFIs,
  createRFI,
  respondToRFI,
  closeRFI,
  type RFI,
  type RFIStatus,
  type CreateRFIPayload,
  type RespondRFIPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const STATUS_CONFIG: Record<
  RFIStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  draft: { variant: 'neutral', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  open: { variant: 'blue', cls: '' },
  answered: { variant: 'success', cls: '' },
  closed: { variant: 'neutral', cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300' },
  void: { variant: 'error', cls: '' },
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function daysOpen(createdAt: string, closedAt: string | null): number {
  const start = new Date(createdAt);
  const end = closedAt ? new Date(closedAt) : new Date();
  return Math.max(0, Math.floor((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)));
}

/* ── Create RFI Modal ──────────────────────────────────────────────────── */

interface RFIFormData {
  subject: string;
  question: string;
  ball_in_court: string;
  due_date: string;
  cost_impact: boolean;
  schedule_impact: boolean;
}

const EMPTY_FORM: RFIFormData = {
  subject: '',
  question: '',
  ball_in_court: '',
  due_date: '',
  cost_impact: false,
  schedule_impact: false,
};

function CreateRFIModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
}: {
  onClose: () => void;
  onSubmit: (data: RFIFormData) => void;
  isPending: boolean;
  projectName?: string;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RFIFormData>(EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = <K extends keyof RFIFormData>(key: K, value: RFIFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });
  };

  const canSubmit = form.subject.trim().length > 0 && form.question.trim().length > 0;

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.subject.trim()) e.subject = t('validation.required', { defaultValue: 'This field is required' });
    if (!form.question.trim()) e.question = t('validation.required', { defaultValue: 'This field is required' });
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    onSubmit(form);
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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[85vh] flex flex-col" role="dialog" aria-modal="true" aria-label={t('rfi.new_rfi', { defaultValue: 'New RFI' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light sticky top-0 z-10 bg-surface-elevated rounded-t-xl">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('rfi.new_rfi', { defaultValue: 'New RFI' })}
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
        <div className="px-6 py-4 space-y-5 overflow-y-auto flex-1">
          {/* ── Request Details ── */}
          <div className="flex items-center gap-2 pb-1">
            <MessageSquare size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('rfi.section_request', { defaultValue: 'Request Details' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Subject */}
          <div>
            <label htmlFor="rfi-subject" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('rfi.field_subject', { defaultValue: 'Subject' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              id="rfi-subject"
              value={form.subject}
              onChange={(e) => set('subject', e.target.value)}
              placeholder={t('rfi.subject_placeholder', {
                defaultValue: 'e.g. Clarification on foundation depth at Grid Line A-3',
              })}
              className={clsx(
                'h-12 w-full rounded-lg border border-border bg-surface-primary px-3 text-base font-medium focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                errors.subject &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {errors.subject && (
              <p className="mt-1 text-xs text-semantic-error">
                {errors.subject}
              </p>
            )}
          </div>

          {/* Question */}
          <div>
            <label htmlFor="rfi-question" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('rfi.field_question', { defaultValue: 'Question' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <textarea
              id="rfi-question"
              value={form.question}
              onChange={(e) => set('question', e.target.value)}
              rows={5}
              className={clsx(
                textareaCls,
                errors.question &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              placeholder={t('rfi.question_placeholder', {
                defaultValue: 'Describe the information you need...',
              })}
            />
            {errors.question && (
              <p className="mt-1 text-xs text-semantic-error">
                {errors.question}
              </p>
            )}
          </div>

          {/* ── Assignment & Schedule ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <User size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('rfi.section_assignment', { defaultValue: 'Assignment & Schedule' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Two-column: Ball in Court + Due Date */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="rfi-ball-in-court" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('rfi.field_ball_in_court', { defaultValue: 'Assigned To' })}
              </label>
              <input
                id="rfi-ball-in-court"
                value={form.ball_in_court}
                onChange={(e) => set('ball_in_court', e.target.value)}
                className={inputCls}
                placeholder={t('rfi.bic_placeholder', {
                  defaultValue: 'Person responsible for response',
                })}
              />
            </div>
            <div>
              <label htmlFor="rfi-due-date" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('rfi.field_due_date', { defaultValue: 'Response Due Date' })}
              </label>
              <input
                id="rfi-due-date"
                type="date"
                value={form.due_date}
                onChange={(e) => set('due_date', e.target.value)}
                className={inputCls}
              />
              <p className="mt-1 text-xs text-content-quaternary">
                {t('rfi.response_due_date_hint', { defaultValue: 'Typical: 14 business days from submission' })}
              </p>
            </div>
          </div>

          {/* ── Impact Assessment ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <AlertTriangle size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('rfi.section_impact', { defaultValue: 'Impact Assessment' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Impact toggles as visual cards */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => set('cost_impact', !form.cost_impact)}
              className={clsx(
                'flex items-center gap-3 rounded-lg border-2 px-4 py-3 transition-all text-left',
                form.cost_impact
                  ? 'border-amber-400 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-600'
                  : 'border-border bg-surface-primary hover:bg-surface-secondary',
              )}
            >
              <div className={clsx(
                'flex h-8 w-8 items-center justify-center rounded-full shrink-0',
                form.cost_impact
                  ? 'bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400'
                  : 'bg-surface-tertiary text-content-quaternary',
              )}>
                <DollarSign size={16} />
              </div>
              <div>
                <p className={clsx('text-sm font-medium', form.cost_impact ? 'text-amber-700 dark:text-amber-400' : 'text-content-secondary')}>
                  {t('rfi.cost_impact', { defaultValue: 'Cost Impact' })}
                </p>
                <p className="text-xs text-content-quaternary">
                  {form.cost_impact
                    ? t('rfi.impact_yes', { defaultValue: 'Yes' })
                    : t('rfi.impact_no', { defaultValue: 'No' })}
                </p>
              </div>
            </button>
            <button
              type="button"
              onClick={() => set('schedule_impact', !form.schedule_impact)}
              className={clsx(
                'flex items-center gap-3 rounded-lg border-2 px-4 py-3 transition-all text-left',
                form.schedule_impact
                  ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-600'
                  : 'border-border bg-surface-primary hover:bg-surface-secondary',
              )}
            >
              <div className={clsx(
                'flex h-8 w-8 items-center justify-center rounded-full shrink-0',
                form.schedule_impact
                  ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400'
                  : 'bg-surface-tertiary text-content-quaternary',
              )}>
                <CalendarClock size={16} />
              </div>
              <div>
                <p className={clsx('text-sm font-medium', form.schedule_impact ? 'text-blue-700 dark:text-blue-400' : 'text-content-secondary')}>
                  {t('rfi.schedule_impact', { defaultValue: 'Schedule Impact' })}
                </p>
                <p className="text-xs text-content-quaternary">
                  {form.schedule_impact
                    ? t('rfi.impact_yes', { defaultValue: 'Yes' })
                    : t('rfi.impact_no', { defaultValue: 'No' })}
                </p>
              </div>
            </button>
          </div>

          {/* ── Linked Drawings (optional) ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <Paperclip size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('rfi.section_references', { defaultValue: 'References' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          <div className="rounded-lg border border-dashed border-border p-4 text-center">
            <Paperclip size={18} className="mx-auto text-content-quaternary mb-1" />
            <p className="text-xs text-content-tertiary">
              {t('rfi.linked_drawing_ids_hint', { defaultValue: 'Linked drawings and references can be added after creation' })}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light sticky bottom-0 z-10 bg-surface-elevated rounded-b-xl">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('rfi.create_rfi', { defaultValue: 'Create RFI' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Respond Modal ─────────────────────────────────────────────────────── */

function RespondModal({
  rfi,
  onClose,
  onSubmit,
  isPending,
}: {
  rfi: RFI;
  onClose: () => void;
  onSubmit: (data: RespondRFIPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [response, setResponse] = useState('');

  const handleSubmit = () => {
    if (response.trim()) onSubmit({ official_response: response.trim() });
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
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4" role="dialog" aria-modal="true" aria-label={t('rfi.respond_title', { defaultValue: 'Respond to RFI #{{number}}', number: rfi.rfi_number })}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('rfi.respond_title', { defaultValue: 'Respond to RFI #{{number}}', number: rfi.rfi_number })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1">{t('rfi.original_question', { defaultValue: 'Question' })}</p>
            <p className="text-sm text-content-primary">{rfi.question}</p>
          </div>
          <div>
            <label htmlFor="rfi-response" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('rfi.field_response', { defaultValue: 'Response' })}
            </label>
            <textarea
              id="rfi-response"
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              rows={4}
              className={textareaCls}
              placeholder={t('rfi.response_placeholder', { defaultValue: 'Enter your response...' })}
              autoFocus
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isPending || !response.trim()}
          >
            {t('rfi.submit_response', { defaultValue: 'Submit Response' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── RFI Row (expandable) ──────────────────────────────────────────────── */

const RFIRow = React.memo(function RFIRow({
  rfi,
  onRespond,
  onClose,
  onCreateVariation,
}: {
  rfi: RFI;
  onRespond: (rfi: RFI) => void;
  onClose: (id: string) => void;
  onCreateVariation: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const days = rfi.days_open ?? daysOpen(rfi.created_at, null);
  const isOverdue = rfi.is_overdue ?? (rfi.response_due_date && rfi.status === 'open' && new Date(rfi.response_due_date) < new Date());
  const statusCfg = STATUS_CONFIG[rfi.status] ?? STATUS_CONFIG.draft;

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

        {/* RFI # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-16 shrink-0">
          #{rfi.rfi_number}
        </span>

        {/* Subject */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {rfi.subject}
        </span>

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`rfi.status_${rfi.status}`, {
            defaultValue: rfi.status.charAt(0).toUpperCase() + rfi.status.slice(1),
          })}
        </Badge>

        {/* Ball in Court */}
        <span className="text-xs text-content-tertiary w-28 truncate shrink-0 hidden md:block">
          {rfi.ball_in_court || '-'}
        </span>

        {/* Days Open */}
        <span
          className={clsx(
            'text-xs w-16 text-right shrink-0 tabular-nums hidden sm:block',
            isOverdue ? 'text-semantic-error font-semibold' : 'text-content-tertiary',
          )}
        >
          {days}d
        </span>

        {/* Due Date */}
        <span
          className={clsx(
            'text-xs w-20 shrink-0 hidden lg:block',
            isOverdue ? 'text-semantic-error font-semibold' : 'text-content-tertiary',
          )}
        >
          {rfi.response_due_date
            ? new Date(rfi.response_due_date).toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
              })
            : '-'}
        </span>

        {/* Impact indicators */}
        <div className="flex items-center gap-1.5 w-14 shrink-0 justify-end">
          {rfi.cost_impact && (
            <span title={t('rfi.cost_impact', { defaultValue: 'Cost Impact' })}>
              <DollarSign size={13} className="text-amber-500" />
            </span>
          )}
          {rfi.schedule_impact && (
            <span title={t('rfi.schedule_impact', { defaultValue: 'Schedule Impact' })}>
              <Clock size={13} className="text-orange-500" />
            </span>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Question */}
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
              {t('rfi.label_question', { defaultValue: 'Question' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">{rfi.question}</p>
          </div>

          {/* Response */}
          {rfi.official_response && (
            <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3">
              <p className="text-xs text-green-700 dark:text-green-400 mb-1 font-medium uppercase tracking-wide">
                {t('rfi.label_response', { defaultValue: 'Response' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{rfi.official_response}</p>
              {rfi.responded_at && (
                <p className="text-xs text-content-tertiary mt-2">
                  {new Date(rfi.responded_at).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </p>
              )}
            </div>
          )}

          {/* Linked drawings */}
          {rfi.linked_drawing_ids && rfi.linked_drawing_ids.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <FileText size={13} className="text-content-tertiary" />
              {rfi.linked_drawing_ids.map((d) => (
                <Badge key={d} variant="neutral" size="sm">
                  {d}
                </Badge>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {rfi.status === 'open' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onRespond(rfi);
                }}
              >
                {t('rfi.action_respond', { defaultValue: 'Respond' })}
              </Button>
            )}
            {(rfi.status === 'answered' || rfi.status === 'open') && (
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(rfi.id);
                }}
              >
                {t('rfi.action_close', { defaultValue: 'Close RFI' })}
              </Button>
            )}
            {rfi.cost_impact && (rfi.status === 'answered' || rfi.status === 'closed') && (
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onCreateVariation(rfi.id);
                }}
              >
                <DollarSign size={14} className="mr-1" />
                {t('rfi.create_variation', { defaultValue: 'Create Variation' })}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Export helper ─────────────────────────────────────────────────────── */

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

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RFIPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [respondingRfi, setRespondingRfi] = useState<RFI | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<RFIStatus | ''>('');

  // "n" shortcut → open new RFI form
  useCreateShortcut(
    useCallback(() => setShowCreateModal(true), []),
    !showCreateModal,
  );

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: rfis = [], isLoading } = useQuery({
    queryKey: ['rfis', projectId, statusFilter],
    queryFn: () =>
      fetchRFIs({
        project_id: projectId,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return rfis;
    const q = searchQuery.toLowerCase();
    return rfis.filter(
      (r) =>
        r.subject.toLowerCase().includes(q) ||
        r.question.toLowerCase().includes(q) ||
        String(r.rfi_number).includes(q) ||
        (r.ball_in_court && r.ball_in_court.toLowerCase().includes(q)),
    );
  }, [rfis, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = rfis.length;
    const open = rfis.filter((r) => r.status === 'open').length;
    const overdue = rfis.filter(
      (r) => r.is_overdue ?? (r.status === 'open' && r.response_due_date && new Date(r.response_due_date) < new Date()),
    ).length;
    const avgDays =
      rfis.length > 0
        ? Math.round(rfis.reduce((sum, r) => sum + (r.days_open ?? daysOpen(r.created_at, null)), 0) / rfis.length)
        : 0;
    return { total, open, overdue, avgDays };
  }, [rfis]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['rfis'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateRFIPayload) => createRFI(data),
    onSuccess: (newRfi) => {
      // Optimistically add the new RFI to the cache so it appears immediately,
      // then also invalidate to ensure eventual consistency with the server.
      qc.setQueryData<RFI[]>(
        ['rfis', projectId, statusFilter],
        (old) => (old ? [newRfi, ...old] : [newRfi]),
      );
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('rfi.created', { defaultValue: 'RFI created successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.create_failed', { defaultValue: 'Failed to create RFI' }),
        message: e.message,
      }),
  });

  const respondMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: RespondRFIPayload }) =>
      respondToRFI(id, data),
    onSuccess: () => {
      invalidateAll();
      setRespondingRfi(null);
      addToast({
        type: 'success',
        title: t('rfi.responded', { defaultValue: 'Response submitted successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.respond_failed', { defaultValue: 'Failed to submit response' }),
        message: e.message,
      }),
  });

  const closeMut = useMutation({
    mutationFn: (id: string) => closeRFI(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('rfi.closed', { defaultValue: 'RFI closed successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.close_failed', { defaultValue: 'Failed to close RFI' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/rfi/export?project_id=${projectId}`,
        'rfi_log.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('rfi.export_success', { defaultValue: 'RFI log exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.export_failed', { defaultValue: 'Failed to export RFI log' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: RFIFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('rfi.no_project_error', { defaultValue: 'No project selected' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        subject: formData.subject,
        question: formData.question,
        ball_in_court: formData.ball_in_court || undefined,
        response_due_date: formData.due_date || undefined,
        cost_impact: formData.cost_impact,
        schedule_impact: formData.schedule_impact,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const handleRespond = useCallback(
    (rfi: RFI) => {
      setRespondingRfi(rfi);
    },
    [],
  );

  const handleRespondSubmit = useCallback(
    (data: RespondRFIPayload) => {
      if (!respondingRfi) return;
      respondMut.mutate({ id: respondingRfi.id, data });
    },
    [respondMut, respondingRfi],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleClose = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('rfi.confirm_close_title', { defaultValue: 'Close RFI?' }),
        message: t('rfi.confirm_close_msg', { defaultValue: 'This RFI will be closed and no further responses can be added.' }),
        confirmLabel: t('rfi.action_close', { defaultValue: 'Close RFI' }),
        variant: 'warning',
      });
      if (ok) closeMut.mutate(id);
    },
    [closeMut, confirm, t],
  );

  const createVariationMut = useMutation({
    mutationFn: (rfiId: string) =>
      apiPost<{ change_order_id: string; code: string; title: string }>(
        `/v1/rfi/${rfiId}/create-variation`,
        {},
      ),
    onSuccess: (data) => {
      addToast(
        {
          type: 'success',
          title: t('rfi.variation_created', { defaultValue: 'Variation created' }),
          message: `${data.code}: ${data.title}`,
          action: {
            label: t('rfi.view_change_orders', { defaultValue: 'View Change Orders' }),
            onClick: () => {
              window.location.href = '/changeorders';
            },
          },
        },
        { duration: 8000 },
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('rfi.variation_failed', { defaultValue: 'Failed to create variation from RFI' }),
        message: e.message,
      }),
  });

  const handleCreateVariation = useCallback(
    (id: string) => {
      createVariationMut.mutate(id);
    },
    [createVariationMut],
  );

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('rfi.title', { defaultValue: 'RFIs' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('rfi.page_title', { defaultValue: 'Requests for Information' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('rfi.subtitle', { defaultValue: 'Submit, track, and resolve design and construction queries' })}
          </p>
        </div>

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
              aria-label={t('rfi.select_project', { defaultValue: 'Project...' })}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              <option value="" disabled>
                {t('rfi.select_project', { defaultValue: 'Project...' })}
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
            {t('rfi.export_rfi_log', { defaultValue: 'Export RFI Log' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            icon={<Plus size={14} />}
          >
            {t('rfi.new_rfi', { defaultValue: 'New RFI' })}
          </Button>
        </div>
      </div>

      {/* Cross-module link */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/changeorders')}>
          <ArrowRightLeft size={13} className="me-1" />
          {t('rfi.link_change_orders', { defaultValue: 'View Change Orders' })}
        </Button>
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
            {t('rfi.stat_total', { defaultValue: 'Total RFIs' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">
            {stats.total}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('rfi.stat_open', { defaultValue: 'Open' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-oe-blue">{stats.open}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('rfi.stat_overdue', { defaultValue: 'Overdue' })}
          </p>
          <p
            className={clsx(
              'text-2xl font-bold mt-1 tabular-nums',
              stats.overdue > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {stats.overdue}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('rfi.stat_avg_days', { defaultValue: 'Avg. Days Open' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">
            {stats.avgDays}
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
            placeholder={t('rfi.search_placeholder', {
              defaultValue: 'Search RFIs...',
            })}
            aria-label={t('rfi.search_placeholder', { defaultValue: 'Search RFIs...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RFIStatus | '')}
            aria-label={t('rfi.filter_all', { defaultValue: 'All Statuses' })}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('rfi.filter_all', { defaultValue: 'All Statuses' })}
            </option>
            {(['draft', 'open', 'answered', 'closed', 'void'] as RFIStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(`rfi.status_${s}`, {
                  defaultValue: s.charAt(0).toUpperCase() + s.slice(1),
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
            icon={<HelpCircle size={28} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('rfi.no_results', { defaultValue: 'No matching RFIs' })
                : t('rfi.no_rfis', { defaultValue: 'No RFIs yet' })
            }
            description={
              searchQuery || statusFilter
                ? t('rfi.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters to find what you are looking for.',
                  })
                : t('rfi.no_rfis_hint', {
                    defaultValue: 'Create your first RFI to track design queries, clarifications, and responses between project stakeholders.',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('rfi.new_rfi', { defaultValue: 'New RFI' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('rfi.showing_count', {
                defaultValue: '{{count}} RFIs',
                count: filtered.length,
              })}
            </p>

            {/* Desktop table */}
            <div className="hidden md:block">
              <Card padding="none" className="overflow-x-auto">
                {/* Table header */}
                <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                  <span className="w-5" /> {/* Chevron space */}
                  <span className="w-16">#</span>
                  <span className="flex-1">
                    {t('rfi.col_subject', { defaultValue: 'Subject' })}
                  </span>
                  <span className="w-20 text-center">
                    {t('rfi.col_status', { defaultValue: 'Status' })}
                  </span>
                  <span className="w-28">
                    {t('rfi.col_bic', { defaultValue: 'Ball in Court' })}
                  </span>
                  <span className="w-16 text-right">
                    {t('rfi.col_days', { defaultValue: 'Days' })}
                  </span>
                  <span className="w-20">
                    {t('rfi.col_due', { defaultValue: 'Due' })}
                  </span>
                  <span className="w-14 text-right">
                    {t('rfi.col_impact', { defaultValue: 'Impact' })}
                  </span>
                </div>

                {/* Rows */}
                {filtered.map((rfi) => (
                  <RFIRow
                    key={rfi.id}
                    rfi={rfi}
                    onRespond={handleRespond}
                    onClose={handleClose}
                    onCreateVariation={handleCreateVariation}
                  />
                ))}
              </Card>
            </div>

            {/* Mobile card view */}
            <div className="md:hidden space-y-3">
              {filtered.map((rfi) => {
                const days = rfi.days_open ?? daysOpen(rfi.created_at, null);
                const isOverdue = rfi.is_overdue ?? (rfi.response_due_date && rfi.status === 'open' && new Date(rfi.response_due_date) < new Date());
                const statusCfg = STATUS_CONFIG[rfi.status] ?? STATUS_CONFIG.draft;
                return (
                  <Card key={rfi.id} className="p-4">
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-mono text-content-tertiary">#{rfi.rfi_number}</span>
                        <h4 className="text-sm font-semibold text-content-primary truncate">{rfi.subject}</h4>
                      </div>
                      <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
                        {t(`rfi.status_${rfi.status}`, { defaultValue: rfi.status.charAt(0).toUpperCase() + rfi.status.slice(1) })}
                      </Badge>
                    </div>
                    <div className="text-xs text-content-tertiary space-y-1">
                      {(rfi.ball_in_court) && (
                        <div>{t('rfi.col_bic', { defaultValue: 'Ball in Court' })}: {rfi.ball_in_court}</div>
                      )}
                      <div className="flex items-center gap-3">
                        <span className={isOverdue ? 'text-semantic-error font-semibold' : ''}>{days}d {t('rfi.col_days', { defaultValue: 'open' })}</span>
                        {rfi.response_due_date && (
                          <span className={isOverdue ? 'text-semantic-error font-semibold' : ''}>
                            {t('rfi.col_due', { defaultValue: 'Due' })}: {new Date(rfi.response_due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        {rfi.cost_impact && (
                          <span className="flex items-center gap-0.5 text-amber-500"><DollarSign size={12} /> {t('rfi.cost_impact', { defaultValue: 'Cost' })}</span>
                        )}
                        {rfi.schedule_impact && (
                          <span className="flex items-center gap-0.5 text-orange-500"><Clock size={12} /> {t('rfi.schedule_impact', { defaultValue: 'Schedule' })}</span>
                        )}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </>
        )}
      </div>
      </>
      ) : (
        <EmptyState
          icon={<HelpCircle size={28} strokeWidth={1.5} />}
          title={t('rfi.no_project', { defaultValue: 'No project selected' })}
          description={t('rfi.select_project_hint', { defaultValue: 'Select a project from the header to submit, track, and resolve requests for information.' })}
        />
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateRFIModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          projectName={projectName}
        />
      )}

      {/* Respond Modal */}
      {respondingRfi && (
        <RespondModal
          rfi={respondingRfi}
          onClose={() => setRespondingRfi(null)}
          onSubmit={handleRespondSubmit}
          isPending={respondMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

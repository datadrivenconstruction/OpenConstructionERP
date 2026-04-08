import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Send,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  Lock,
  CheckCircle2,
  Users,
  FileText,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, DateDisplay, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchTransmittals,
  createTransmittal,
  issueTransmittal,
  type Transmittal,
  type TransmittalStatus,
  type TransmittalPurpose,
  type CreateTransmittalPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const STATUS_CONFIG: Record<
  TransmittalStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'warning'; cls: string }
> = {
  draft: {
    variant: 'neutral',
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  },
  issued: { variant: 'blue', cls: '' },
  acknowledged: { variant: 'success', cls: '' },
  closed: {
    variant: 'neutral',
    cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  },
};

const STATUS_LABELS: Record<TransmittalStatus, string> = {
  draft: 'Draft',
  issued: 'Issued',
  acknowledged: 'Acknowledged',
  closed: 'Closed',
};

const PURPOSE_LABELS: Record<TransmittalPurpose, string> = {
  for_approval: 'For Approval',
  for_information: 'For Information',
  for_construction: 'For Construction',
  for_review: 'For Review',
  for_record: 'For Record',
  as_requested: 'As Requested',
};

const PURPOSE_COLORS: Record<TransmittalPurpose, string> = {
  for_approval: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  for_information: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  for_construction: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  for_review: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  for_record: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  as_requested: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface TransmittalFormData {
  subject: string;
  purpose: TransmittalPurpose;
  cover_note: string;
  response_due: string;
  recipients: string;
  items: string;
}

const EMPTY_FORM: TransmittalFormData = {
  subject: '',
  purpose: 'for_information',
  cover_note: '',
  response_due: '',
  recipients: '',
  items: '',
};

function CreateTransmittalModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: TransmittalFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<TransmittalFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof TransmittalFormData>(key: K, value: TransmittalFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const subjectError = touched && form.subject.trim().length === 0;
  const canSubmit = form.subject.trim().length > 0;

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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('transmittals.new_transmittal', { defaultValue: 'New Transmittal' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('transmittals.new_transmittal', { defaultValue: 'New Transmittal' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Subject */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('transmittals.field_subject', { defaultValue: 'Subject' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.subject}
              onChange={(e) => {
                set('subject', e.target.value);
                setTouched(true);
              }}
              placeholder={t('transmittals.subject_placeholder', {
                defaultValue: 'e.g. Structural drawings for approval - Rev C',
              })}
              className={clsx(
                inputCls,
                subjectError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {subjectError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('transmittals.subject_required', { defaultValue: 'Subject is required' })}
              </p>
            )}
          </div>

          {/* Two-column: Purpose + Response Due */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('transmittals.field_purpose', { defaultValue: 'Purpose' })}
              </label>
              <div className="relative">
                <select
                  value={form.purpose}
                  onChange={(e) => set('purpose', e.target.value as TransmittalPurpose)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  {(Object.keys(PURPOSE_LABELS) as TransmittalPurpose[]).map((p) => (
                    <option key={p} value={p}>
                      {t(`transmittals.purpose_${p}`, { defaultValue: PURPOSE_LABELS[p] })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('transmittals.field_response_due', { defaultValue: 'Response Due' })}
              </label>
              <input
                type="date"
                value={form.response_due}
                onChange={(e) => set('response_due', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Recipients */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('transmittals.field_recipients', { defaultValue: 'Recipients' })}
            </label>
            <input
              value={form.recipients}
              onChange={(e) => set('recipients', e.target.value)}
              placeholder={t('transmittals.recipients_placeholder', {
                defaultValue: 'Names, comma-separated',
              })}
              className={inputCls}
            />
          </div>

          {/* Items */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('transmittals.field_items', { defaultValue: 'Document Items' })}
            </label>
            <input
              value={form.items}
              onChange={(e) => set('items', e.target.value)}
              placeholder={t('transmittals.items_placeholder', {
                defaultValue: 'Document titles, comma-separated',
              })}
              className={inputCls}
            />
          </div>

          {/* Cover Note */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('transmittals.field_cover_note', { defaultValue: 'Cover Note' })}
            </label>
            <textarea
              value={form.cover_note}
              onChange={(e) => set('cover_note', e.target.value)}
              rows={3}
              className={textareaCls}
              placeholder={t('transmittals.cover_note_placeholder', {
                defaultValue: 'Cover letter or transmission notes...',
              })}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {t('transmittals.create_transmittal', { defaultValue: 'Create Transmittal' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Transmittal Row (expandable) ─────────────────────────────────────── */

const TransmittalRow = React.memo(function TransmittalRow({
  transmittal,
  onIssue,
}: {
  transmittal: Transmittal;
  onIssue: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[transmittal.status] ?? STATUS_CONFIG.draft;
  const purposeCls = PURPOSE_COLORS[transmittal.purpose] ?? PURPOSE_COLORS.for_information;

  const acknowledgedCount = transmittal.recipients.filter((r) => r.acknowledged).length;
  const isOverdue =
    transmittal.response_due &&
    transmittal.status === 'issued' &&
    new Date(transmittal.response_due) < new Date();

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

        {/* TR # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          {transmittal.transmittal_number}
        </span>

        {/* Subject */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {transmittal.subject}
        </span>

        {/* Purpose badge */}
        <Badge variant="neutral" size="sm" className={clsx(purposeCls, 'hidden md:inline-flex')}>
          {t(`transmittals.purpose_${transmittal.purpose}`, {
            defaultValue: PURPOSE_LABELS[transmittal.purpose],
          })}
        </Badge>

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`transmittals.status_${transmittal.status}`, {
            defaultValue: STATUS_LABELS[transmittal.status],
          })}
        </Badge>

        {/* Issued Date */}
        <span className="text-xs w-20 shrink-0 hidden sm:block">
          <DateDisplay
            value={transmittal.issued_date}
            className="text-xs text-content-tertiary"
          />
        </span>

        {/* Response Due */}
        <span
          className={clsx(
            'text-xs w-20 shrink-0 hidden lg:block',
            isOverdue ? 'text-semantic-error font-semibold' : '',
          )}
        >
          <DateDisplay
            value={transmittal.response_due}
            className={clsx(
              'text-xs',
              isOverdue ? 'text-semantic-error' : 'text-content-tertiary',
            )}
          />
        </span>

        {/* Recipients count */}
        <span className="flex items-center gap-1 text-xs text-content-tertiary w-12 shrink-0 hidden sm:flex">
          <Users size={12} />
          {transmittal.recipients.length}
        </span>

        {/* Locked indicator */}
        {transmittal.locked && (
          <Lock size={13} className="text-content-tertiary shrink-0" />
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Cover note */}
          {transmittal.cover_note && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('transmittals.label_cover_note', { defaultValue: 'Cover Note' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">
                {transmittal.cover_note}
              </p>
            </div>
          )}

          {/* Recipients list */}
          {transmittal.recipients.length > 0 && (
            <div>
              <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
                {t('transmittals.label_recipients', {
                  defaultValue: 'Recipients ({{ack}}/{{total}} acknowledged)',
                  ack: acknowledgedCount,
                  total: transmittal.recipients.length,
                })}
              </p>
              <div className="space-y-1">
                {transmittal.recipients.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center gap-2 rounded-lg bg-surface-secondary p-2 text-sm"
                  >
                    {r.acknowledged ? (
                      <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
                    ) : (
                      <div className="h-3.5 w-3.5 rounded-full border border-border shrink-0" />
                    )}
                    <span className="text-content-primary">{r.name}</span>
                    {r.company && (
                      <span className="text-xs text-content-tertiary">({r.company})</span>
                    )}
                    {r.acknowledged_at && (
                      <DateDisplay
                        value={r.acknowledged_at}
                        className="text-xs text-content-tertiary ml-auto"
                      />
                    )}
                    {r.response && (
                      <span className="text-xs text-content-secondary ml-auto truncate max-w-xs">
                        {r.response}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Items list */}
          {transmittal.items.length > 0 && (
            <div>
              <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
                {t('transmittals.label_items', {
                  defaultValue: 'Documents ({{count}})',
                  count: transmittal.items.length,
                })}
              </p>
              <div className="space-y-1">
                {transmittal.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-2 rounded-lg bg-surface-secondary p-2 text-sm"
                  >
                    <FileText size={13} className="text-content-tertiary shrink-0" />
                    <span className="text-content-primary truncate">
                      {item.document_title}
                    </span>
                    {item.document_ref && (
                      <span className="text-xs text-content-tertiary font-mono">
                        {item.document_ref}
                      </span>
                    )}
                    {item.revision && (
                      <Badge variant="neutral" size="sm">
                        {item.revision}
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {transmittal.status === 'draft' && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onIssue(transmittal.id);
                }}
              >
                <Send size={13} className="mr-1" />
                {t('transmittals.action_issue', { defaultValue: 'Issue Transmittal' })}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TransmittalsPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<TransmittalStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: transmittals = [], isLoading } = useQuery({
    queryKey: ['transmittals', projectId, statusFilter],
    queryFn: () =>
      fetchTransmittals({
        project_id: projectId,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return transmittals;
    const q = searchQuery.toLowerCase();
    return transmittals.filter(
      (tr) =>
        tr.subject.toLowerCase().includes(q) ||
        tr.transmittal_number.toLowerCase().includes(q),
    );
  }, [transmittals, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = transmittals.length;
    const draft = transmittals.filter((tr) => tr.status === 'draft').length;
    const issued = transmittals.filter((tr) => tr.status === 'issued').length;
    const acknowledged = transmittals.filter((tr) => tr.status === 'acknowledged').length;
    const closed = transmittals.filter((tr) => tr.status === 'closed').length;
    return { total, draft, issued, acknowledged, closed };
  }, [transmittals]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['transmittals'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateTransmittalPayload) => createTransmittal(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('transmittals.created', { defaultValue: 'Transmittal created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const issueMut = useMutation({
    mutationFn: (id: string) => issueTransmittal(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('transmittals.issued', { defaultValue: 'Transmittal issued' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: TransmittalFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        subject: formData.subject,
        purpose: formData.purpose,
        cover_note: formData.cover_note || undefined,
        response_due: formData.response_due || undefined,
        recipients: formData.recipients
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .map((name) => ({ name })),
        items: formData.items
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .map((title) => ({ document_title: title })),
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleIssue = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('transmittals.confirm_issue_title', { defaultValue: 'Issue transmittal?' }),
        message: t('transmittals.confirm_issue_msg', { defaultValue: 'Once issued, this transmittal will be locked and sent to recipients.' }),
        confirmLabel: t('transmittals.action_issue', { defaultValue: 'Issue' }),
        variant: 'warning',
      });
      if (ok) issueMut.mutate(id);
    },
    [issueMut, confirm, t],
  );

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('transmittals.title', { defaultValue: 'Transmittals' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold text-content-primary shrink-0">
          {t('transmittals.page_title', { defaultValue: 'Transmittals' })}
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
                {t('transmittals.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            className="shrink-0 whitespace-nowrap"
          >
            <Plus size={14} className="mr-1 shrink-0" />
            <span>
              {t('transmittals.new_transmittal', { defaultValue: 'New Transmittal' })}
            </span>
          </Button>
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_first', { defaultValue: 'Please select a project to continue.' })}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('transmittals.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-content-primary">
            {stats.total}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('transmittals.stat_draft', { defaultValue: 'Draft' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-content-tertiary">
            {stats.draft}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('transmittals.stat_issued', { defaultValue: 'Issued' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-oe-blue">{stats.issued}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('transmittals.stat_acknowledged', { defaultValue: 'Acknowledged' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-semantic-success">
            {stats.acknowledged}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('transmittals.stat_closed', { defaultValue: 'Closed' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-content-primary">
            {stats.closed}
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
            placeholder={t('transmittals.search_placeholder', {
              defaultValue: 'Search transmittals...',
            })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as TransmittalStatus | '')}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
          >
            <option value="">
              {t('transmittals.filter_all', { defaultValue: 'All Statuses' })}
            </option>
            {(Object.keys(STATUS_LABELS) as TransmittalStatus[]).map((s) => (
              <option key={s} value={s}>
                {t(`transmittals.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
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
            icon={<Send size={24} strokeWidth={1.5} />}
            title={
              searchQuery || statusFilter
                ? t('transmittals.no_results', {
                    defaultValue: 'No matching transmittals',
                  })
                : t('transmittals.no_transmittals', {
                    defaultValue: 'No transmittals yet',
                  })
            }
            description={
              searchQuery || statusFilter
                ? t('transmittals.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('transmittals.no_transmittals_hint', {
                    defaultValue:
                      'Create your first transmittal to track document distribution',
                  })
            }
            action={
              !searchQuery && !statusFilter
                ? {
                    label: t('transmittals.new_transmittal', {
                      defaultValue: 'New Transmittal',
                    }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('transmittals.showing_count', {
                defaultValue: '{{count}} transmittals',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface-secondary/50 text-xs font-medium text-content-tertiary uppercase tracking-wide min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('transmittals.col_subject', { defaultValue: 'Subject' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('transmittals.col_purpose', { defaultValue: 'Purpose' })}
                </span>
                <span className="w-24 text-center">
                  {t('transmittals.col_status', { defaultValue: 'Status' })}
                </span>
                <span className="w-20 hidden sm:block">
                  {t('transmittals.col_issued', { defaultValue: 'Issued' })}
                </span>
                <span className="w-20 hidden lg:block">
                  {t('transmittals.col_due', { defaultValue: 'Due' })}
                </span>
                <span className="w-12 hidden sm:block">
                  {t('transmittals.col_recipients', { defaultValue: 'Rcpt' })}
                </span>
                <span className="w-5" />
              </div>

              {/* Rows */}
              {filtered.map((tr) => (
                <TransmittalRow
                  key={tr.id}
                  transmittal={tr}
                  onIssue={handleIssue}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateTransmittalModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

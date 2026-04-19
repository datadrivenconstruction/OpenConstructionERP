import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
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
  Info,
  Pencil,
  Trash2,
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
  updateTransmittal,
  deleteTransmittal,
  type Transmittal,
  type TransmittalStatus,
  type TransmittalPurpose,
  type CreateTransmittalPayload,
  type CreateItemPayload,
  type UpdateTransmittalPayload,
} from './api';
import {
  fetchCDEContainers,
  fetchContainerRevisions,
  type CDEContainer,
  type CDERevision,
} from '@/features/cde/api';

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
  for_tender: 'For Tender',
  for_review: 'For Review',
  for_record: 'For Record',
};

const PURPOSE_DESCRIPTIONS: Record<TransmittalPurpose, string> = {
  for_approval: 'Requires formal response',
  for_information: 'No response required',
  for_construction: 'Issued for use on site',
  for_tender: 'Issued for tender/bidding',
  for_review: 'Review and comment expected',
  for_record: 'Archived for documentation',
};

const PURPOSE_COLORS: Record<TransmittalPurpose, string> = {
  for_approval: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  for_information: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  for_construction: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  for_tender: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
  for_review: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  for_record: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const LS_INFO_DISMISSED = 'oe_transmittals_info_dismissed';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface SelectedRevision {
  container_id: string;
  container_code: string;
  revision_id: string;
  revision_code: string;
}

interface TransmittalFormData {
  subject: string;
  purpose: TransmittalPurpose;
  cover_note: string;
  response_due: string;
  recipients: string;
  items: string;
  revisions: SelectedRevision[];
}

const EMPTY_FORM: TransmittalFormData = {
  subject: '',
  purpose: 'for_information',
  cover_note: '',
  response_due: '',
  recipients: '',
  items: '',
  revisions: [],
};

function CreateTransmittalModal({
  onClose,
  onSubmit,
  isPending,
  initialItems,
  projectId,
  initialContainerId,
}: {
  onClose: () => void;
  onSubmit: (data: TransmittalFormData) => void;
  isPending: boolean;
  initialItems?: string;
  projectId: string;
  initialContainerId?: string | null;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<TransmittalFormData>({
    ...EMPTY_FORM,
    items: initialItems || '',
  });
  const [touched, setTouched] = useState(false);
  const [pickerContainerId, setPickerContainerId] = useState<string>(
    initialContainerId || '',
  );

  // Load containers for the picker (CDE revision selection).
  const { data: containers = [] } = useQuery({
    queryKey: ['transmittals-cde-containers', projectId],
    queryFn: () => fetchCDEContainers({ project_id: projectId }),
    enabled: !!projectId,
  });
  const { data: revisions = [] } = useQuery({
    queryKey: ['transmittals-cde-revisions', pickerContainerId],
    queryFn: () => fetchContainerRevisions(pickerContainerId),
    enabled: !!pickerContainerId,
  });

  const addRevision = (rev: CDERevision) => {
    if (form.revisions.some((r) => r.revision_id === rev.id)) return;
    const container = containers.find((c: CDEContainer) => c.id === pickerContainerId);
    if (!container) return;
    setForm((prev) => ({
      ...prev,
      revisions: [
        ...prev.revisions,
        {
          container_id: container.id,
          container_code: container.container_code,
          revision_id: rev.id,
          revision_code: rev.revision_code,
        },
      ],
    }));
  };
  const removeRevision = (revision_id: string) => {
    setForm((prev) => ({
      ...prev,
      revisions: prev.revisions.filter((r) => r.revision_id !== revision_id),
    }));
  };

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in" role="dialog" aria-modal="true" aria-label={t('transmittals.new_transmittal', { defaultValue: 'New Transmittal' })}>
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
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
            <label htmlFor="tr-subject" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('transmittals.field_subject', { defaultValue: 'Subject' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              id="tr-subject"
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
              <label htmlFor="tr-purpose" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('transmittals.field_purpose', { defaultValue: 'Purpose' })}
              </label>
              <div className="relative">
                <select
                  id="tr-purpose"
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
              <p className="mt-1 text-2xs text-content-tertiary">
                {t(`transmittals.purpose_desc_${form.purpose}`, { defaultValue: PURPOSE_DESCRIPTIONS[form.purpose] })}
              </p>
            </div>
            <div>
              <label htmlFor="tr-response-due" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('transmittals.field_response_due', { defaultValue: 'Response Due' })}
              </label>
              <input
                id="tr-response-due"
                type="date"
                value={form.response_due}
                onChange={(e) => set('response_due', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Recipients */}
          <div>
            <label htmlFor="tr-recipients" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('transmittals.field_recipients', { defaultValue: 'Recipients' })}
            </label>
            <input
              id="tr-recipients"
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
            <label htmlFor="tr-items" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('transmittals.field_items', { defaultValue: 'Document Items' })}
            </label>
            <input
              id="tr-items"
              value={form.items}
              onChange={(e) => set('items', e.target.value)}
              placeholder={t('transmittals.items_placeholder', {
                defaultValue: 'Document titles, comma-separated',
              })}
              className={inputCls}
            />
          </div>

          {/* CDE Revision picker */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('transmittals.field_link_revision', {
                defaultValue: 'Link CDE Revision',
              })}
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="relative">
                <select
                  aria-label={t('transmittals.picker_container_label', { defaultValue: 'Container' })}
                  value={pickerContainerId}
                  onChange={(e) => setPickerContainerId(e.target.value)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  <option value="">
                    {t('transmittals.picker_select_container', { defaultValue: 'Select container…' })}
                  </option>
                  {containers.map((c: CDEContainer) => (
                    <option key={c.id} value={c.id}>
                      {c.container_code}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
              <div className="relative">
                <select
                  aria-label={t('transmittals.picker_revision_label', { defaultValue: 'Revision' })}
                  value=""
                  onChange={(e) => {
                    const rev = revisions.find((r) => r.id === e.target.value);
                    if (rev) addRevision(rev);
                  }}
                  className={inputCls + ' appearance-none pr-9'}
                  disabled={!pickerContainerId}
                >
                  <option value="">
                    {t('transmittals.picker_select_revision', { defaultValue: 'Select revision…' })}
                  </option>
                  {revisions.map((r: CDERevision) => (
                    <option key={r.id} value={r.id}>
                      {r.revision_code} — {r.file_name}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
            {form.revisions.length > 0 && (
              <div className="mt-2 space-y-1">
                {form.revisions.map((r) => (
                  <div
                    key={r.revision_id}
                    className="flex items-center justify-between rounded-lg bg-surface-secondary px-3 py-2 text-sm"
                  >
                    <span className="font-mono">
                      {r.container_code} · {r.revision_code}
                    </span>
                    <button
                      type="button"
                      className="text-content-tertiary hover:text-semantic-error"
                      onClick={() => removeRevision(r.revision_id)}
                      aria-label={t('common.remove', { defaultValue: 'Remove' })}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Cover Note */}
          <div>
            <label htmlFor="tr-cover-note" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('transmittals.field_cover_note', { defaultValue: 'Cover Note' })}
            </label>
            <textarea
              id="tr-cover-note"
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
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
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
  onEdit,
  onDelete,
}: {
  transmittal: Transmittal;
  onIssue: (id: string) => void;
  onEdit: (tr: Transmittal) => void;
  onDelete: (tr: Transmittal) => void;
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
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={t('transmittals.toggle_row', { defaultValue: 'Toggle details for {{num}}', num: transmittal.transmittal_number })}
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
                {transmittal.items.map((item, idx) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-2 rounded-lg bg-surface-secondary p-2 text-sm"
                  >
                    <span className="text-2xs text-content-quaternary font-mono w-5 text-center shrink-0">
                      {idx + 1}
                    </span>
                    <FileText size={13} className="text-content-tertiary shrink-0" />
                    <span className="text-content-primary truncate">
                      {item.document_title}
                    </span>
                    {item.document_ref && (
                      <Badge variant="neutral" size="sm" className="font-mono shrink-0">
                        {item.document_ref}
                      </Badge>
                    )}
                    {item.revision && (
                      <Badge variant="blue" size="sm" className="shrink-0">
                        {t('transmittals.revision_prefix', { defaultValue: 'Rev {{rev}}', rev: item.revision })}
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
              <>
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
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid={`transmittal-edit-${transmittal.id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit(transmittal);
                  }}
                >
                  <Pencil size={13} className="mr-1" />
                  {t('common.edit', { defaultValue: 'Edit' })}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
                  data-testid={`transmittal-delete-${transmittal.id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(transmittal);
                  }}
                >
                  <Trash2 size={13} className="mr-1" />
                  {t('common.delete', { defaultValue: 'Delete' })}
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Edit Transmittal Modal ───────────────────────────────────────────── */

function EditTransmittalModal({
  transmittal,
  onClose,
  onSubmit,
  isPending,
}: {
  transmittal: Transmittal;
  onClose: () => void;
  onSubmit: (data: UpdateTransmittalPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [subject, setSubject] = useState(transmittal.subject);
  const [purpose, setPurpose] = useState<TransmittalPurpose>(transmittal.purpose);
  const [coverNote, setCoverNote] = useState(transmittal.cover_note ?? '');
  const [responseDue, setResponseDue] = useState(transmittal.response_due ?? '');

  const canSave = subject.trim().length > 0 && !isPending;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    // Only send fields that actually changed — keeps the audit trail clean.
    const data: UpdateTransmittalPayload = {};
    if (subject.trim() !== transmittal.subject) data.subject = subject.trim();
    if (purpose !== transmittal.purpose) data.purpose_code = purpose;
    if ((coverNote || null) !== (transmittal.cover_note ?? null)) {
      data.cover_note = coverNote.trim() || null;
    }
    if ((responseDue || null) !== (transmittal.response_due ?? null)) {
      data.response_due_date = responseDue || null;
    }
    onSubmit(data);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-xl bg-surface-primary rounded-2xl shadow-xl border border-border"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-transmittal-title"
      >
        <form onSubmit={handleSubmit}>
          <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
            <h2 id="edit-transmittal-title" className="text-base font-semibold text-content-primary">
              {t('transmittals.edit_title', {
                defaultValue: 'Edit {{number}}',
                number: transmittal.transmittal_number,
              })}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={18} />
            </button>
          </div>

          <div className="px-5 py-4 space-y-4">
            <div>
              <label className="block text-xs font-medium text-content-secondary mb-1">
                {t('transmittals.field_subject', { defaultValue: 'Subject' })}
                <span className="text-semantic-error ml-0.5">*</span>
              </label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                data-testid="edit-transmittal-subject"
                className="w-full px-3 py-2 text-sm bg-surface-secondary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-oe-blue"
                required
                maxLength={500}
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-content-secondary mb-1">
                {t('transmittals.field_purpose', { defaultValue: 'Purpose' })}
              </label>
              <select
                value={purpose}
                onChange={(e) => setPurpose(e.target.value as TransmittalPurpose)}
                data-testid="edit-transmittal-purpose"
                className="w-full px-3 py-2 text-sm bg-surface-secondary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                {(Object.keys(PURPOSE_LABELS) as TransmittalPurpose[]).map((k) => (
                  <option key={k} value={k}>
                    {t(`transmittals.purpose_${k}`, { defaultValue: PURPOSE_LABELS[k] })}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-content-secondary mb-1">
                {t('transmittals.field_response_due', { defaultValue: 'Response due' })}
              </label>
              <input
                type="date"
                value={responseDue}
                onChange={(e) => setResponseDue(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-surface-secondary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-content-secondary mb-1">
                {t('transmittals.field_cover_note', { defaultValue: 'Cover note' })}
              </label>
              <textarea
                value={coverNote}
                onChange={(e) => setCoverNote(e.target.value)}
                rows={4}
                maxLength={5000}
                className="w-full px-3 py-2 text-sm bg-surface-secondary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-oe-blue resize-y"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-secondary/30 rounded-b-2xl">
            <Button type="button" variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={!canSave}>
              {isPending
                ? t('common.saving', { defaultValue: 'Saving…' })
                : t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TransmittalsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Auto-open create modal when navigated from Documents with ?create=true
  const autoCreate = searchParams.get('create') === 'true';
  const docIdsParam = searchParams.get('doc_ids') || '';

  // State
  const [showCreateModal, setShowCreateModal] = useState(autoCreate);
  const [editTarget, setEditTarget] = useState<Transmittal | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<TransmittalStatus | ''>('');
  const [infoDismissed, setInfoDismissed] = useState(
    () => localStorage.getItem(LS_INFO_DISMISSED) === '1',
  );

  // Clear URL params after opening modal
  const hasCleanedParams = useRef(false);
  useEffect(() => {
    if (hasCleanedParams.current) return;
    hasCleanedParams.current = true;
    if (autoCreate) {
      const next = new URLSearchParams(searchParams);
      next.delete('create');
      next.delete('doc_ids');
      next.delete('container_id');
      setSearchParams(next, { replace: true });
    }
  }, [autoCreate, searchParams, setSearchParams]);

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
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

  const updateMut = useMutation({
    mutationKey: ['transmittals', 'update'],
    mutationFn: ({ id, data }: { id: string; data: UpdateTransmittalPayload }) =>
      updateTransmittal(id, data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['transmittals'] });
      setEditTarget(null);
      addToast({
        type: 'success',
        title: t('transmittals.updated', { defaultValue: 'Transmittal updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const deleteMut = useMutation({
    mutationKey: ['transmittals', 'delete'],
    mutationFn: (id: string) => deleteTransmittal(id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['transmittals'] });
      addToast({
        type: 'success',
        title: t('transmittals.deleted', { defaultValue: 'Transmittal deleted' }),
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
      // Map selected CDE revisions into TransmittalItem payloads (RFC 33 §3.3).
      const items: CreateItemPayload[] = formData.revisions.map((r, idx) => ({
        revision_id: r.revision_id,
        item_number: idx + 1,
        description: `${r.container_code} · ${r.revision_code}`,
      }));
      createMut.mutate({
        project_id: projectId,
        subject: formData.subject,
        purpose_code: formData.purpose,
        cover_note: formData.cover_note || undefined,
        response_due_date: formData.response_due || undefined,
        items: items.length > 0 ? items : undefined,
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

  const handleEdit = useCallback((tr: Transmittal) => {
    setEditTarget(tr);
  }, []);

  const handleDelete = useCallback(
    async (tr: Transmittal) => {
      const ok = await confirm({
        title: t('transmittals.confirm_delete_title', {
          defaultValue: 'Delete transmittal?',
        }),
        message: t('transmittals.confirm_delete_msg', {
          defaultValue:
            'This permanently removes the draft "{{subject}}". Issued transmittals cannot be deleted.',
          subject: tr.subject,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(tr.id);
    },
    [deleteMut, confirm, t],
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
          { label: t('transmittals.title', { defaultValue: 'Transmittals' }) },
        ]}
        className="mb-4"
      />

      {/* Document flow */}
      <div className="flex items-center gap-2 text-2xs text-content-quaternary mb-4">
        <span className="text-content-tertiary">
          {t('transmittals.flow_label', { defaultValue: 'Document flow:' })}
        </span>
        <button onClick={() => navigate('/documents')} className="hover:text-oe-blue transition-colors" aria-label={t('transmittals.flow_upload', { defaultValue: 'Upload' })}>
          {t('transmittals.flow_upload', { defaultValue: 'Upload' })}
        </button>
        <span aria-hidden="true">&#8594;</span>
        <button onClick={() => navigate('/cde')} className="hover:text-oe-blue transition-colors" aria-label={t('transmittals.flow_organize', { defaultValue: 'Organize (CDE)' })}>
          {t('transmittals.flow_organize', { defaultValue: 'Organize (CDE)' })}
        </button>
        <span aria-hidden="true">&#8594;</span>
        <span className="text-oe-blue font-medium">
          {t('transmittals.flow_distribute', { defaultValue: 'Distribute' })}
        </span>
      </div>

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
              aria-label={t('transmittals.select_project', { defaultValue: 'Project...' })}
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
            icon={<Plus size={14} />}
          >
            {t('transmittals.new_transmittal', { defaultValue: 'New Transmittal' })}
          </Button>
        </div>
      </div>

      {/* Info banner */}
      {!infoDismissed && (
        <div className="mb-6 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-300 relative">
          <button
            onClick={() => {
              setInfoDismissed(true);
              localStorage.setItem(LS_INFO_DISMISSED, '1');
            }}
            className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded text-blue-400 hover:text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/40 dark:hover:text-blue-200 transition-colors"
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
          >
            <X size={14} />
          </button>
          <div className="flex items-center gap-2 mb-1">
            <Info size={16} />
            <span className="font-semibold">
              {t('transmittals.info_title', { defaultValue: 'About Transmittals' })}
            </span>
          </div>
          <p className="text-xs pr-6">
            {t('transmittals.info_body', {
              defaultValue:
                'A transmittal is a formal document distribution record. When you send drawings, specifications, or other documents to a subcontractor or consultant, create a transmittal to track: what was sent, to whom, when, and whether they acknowledged receipt.',
            })}
            <br />
            <strong>
              {t('transmittals.info_purpose_codes', {
                defaultValue:
                  'Purpose codes: For Approval, For Information, For Construction, For Review.',
              })}
            </strong>
          </p>
        </div>
      )}

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('transmittals.stat_total', { defaultValue: 'Total' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">
            {stats.total}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('transmittals.stat_draft', { defaultValue: 'Draft' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-tertiary">
            {stats.draft}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('transmittals.stat_issued', { defaultValue: 'Issued' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-oe-blue">{stats.issued}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('transmittals.stat_acknowledged', { defaultValue: 'Acknowledged' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-semantic-success">
            {stats.acknowledged}
          </p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('transmittals.stat_closed', { defaultValue: 'Closed' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">
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
            aria-label={t('transmittals.search_placeholder', { defaultValue: 'Search transmittals...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as TransmittalStatus | '')}
            aria-label={t('transmittals.filter_all', { defaultValue: 'All Statuses' })}
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
            icon={<Send size={28} strokeWidth={1.5} />}
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
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
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
                  onEdit={handleEdit}
                  onDelete={handleDelete}
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
          initialItems={docIdsParam}
          projectId={projectId}
          initialContainerId={searchParams.get('container_id')}
        />
      )}

      {/* Edit Modal */}
      {editTarget && (
        <EditTransmittalModal
          transmittal={editTarget}
          onClose={() => setEditTarget(null)}
          onSubmit={(data) => updateMut.mutate({ id: editTarget.id, data })}
          isPending={updateMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

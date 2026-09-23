// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  FileStack,
  Plus,
  Search,
  ShieldCheck,
  Clock,
  AlertOctagon,
  ListChecks,
  Pencil,
  Trash2,
  Mail,
  CheckCircle2,
  Ban,
  Circle,
  ExternalLink,
} from 'lucide-react';
import {
  Button,
  Badge,
  Card,
  CardHeader,
  CardContent,
  EmptyState,
  Breadcrumb,
  DateDisplay,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fetchProjectList } from '@/shared/lib/projectList';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchSourceDataMeta,
  fetchSourceDocuments,
  fetchExpiringSoon,
  fetchBlockingSchedule,
  fetchDefectiveInputsNotice,
  fetchChecklistSummary,
  fetchChecklist,
  createSourceDocument,
  updateSourceDocument,
  verifySourceDocument,
  deleteSourceDocument,
  createChecklistItem,
  updateChecklistItem,
  deleteChecklistItem,
  type SourceDocument,
  type SourceDocType,
  type SourceDocStatus,
  type SourceDocManualStatus,
  type SourceChecklistItem,
  type ChecklistItemStatus,
  type CreateSourceDocumentPayload,
  type UpdateSourceDocumentPayload,
} from './api';
import { sourceDataGuide } from './sourceDataGuide';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const DOC_TYPE_LABELS: Record<SourceDocType, string> = {
  permit: 'Permit',
  survey: 'Survey',
  geotech: 'Geotechnical report',
  tech_conditions: 'Technical conditions',
  title_deed: 'Title deed',
  approval: 'Approval',
  technical_spec: 'Technical specification',
  other: 'Other',
};

const DOC_TYPES_LIST: SourceDocType[] = [
  'permit',
  'survey',
  'geotech',
  'tech_conditions',
  'title_deed',
  'approval',
  'technical_spec',
  'other',
];

const MANUAL_STATUSES: SourceDocManualStatus[] = ['requested', 'received', 'verified', 'superseded'];

const STATUS_LABELS: Record<SourceDocStatus, string> = {
  requested: 'Requested',
  received: 'Received',
  verified: 'Verified',
  expiring_soon: 'Expiring soon',
  expired: 'Expired',
  superseded: 'Superseded',
};

function statusVariant(s: SourceDocStatus): 'blue' | 'warning' | 'success' | 'neutral' | 'error' {
  switch (s) {
    case 'verified':
      return 'success';
    case 'expiring_soon':
      return 'warning';
    case 'expired':
      return 'error';
    case 'superseded':
      return 'neutral';
    default:
      return 'blue';
  }
}

const CHECKLIST_STATUS_LABELS: Record<ChecklistItemStatus, string> = {
  pending: 'Pending',
  satisfied: 'Satisfied',
  waived: 'Waived',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Document Create/Edit Modal ───────────────────────────────────────── */

interface DocumentFormData {
  name: string;
  doc_type: SourceDocType;
  owner: string;
  authority: string;
  identifier: string;
  issued_at: string;
  valid_until: string;
  notify_days_before: number;
  blocks_schedule: boolean;
  status: SourceDocManualStatus;
  notes: string;
}

const EMPTY_DOC_FORM: DocumentFormData = {
  name: '',
  doc_type: 'permit',
  owner: '',
  authority: '',
  identifier: '',
  issued_at: '',
  valid_until: '',
  notify_days_before: 30,
  blocks_schedule: false,
  status: 'requested',
  notes: '',
};

/**
 * The form state a document opens with.
 *
 * Pure and module-level so the edit handler can rebuild the same baseline the
 * modal started from and send only what the user actually changed. Prefilling
 * from a row and then PATCHing every field back rewrites fields nobody opened
 * with the values they held when the register was last read, quietly undoing an
 * edit somebody else made in between.
 *
 * The status is narrowed against the manually settable set here rather than
 * trusted from the row, because a derived status (expired, expiring) has no
 * option in the select; doing that narrowing a second way would make an
 * untouched status read as edited.
 */
export function documentFormData(item: SourceDocument): DocumentFormData {
  return {
    name: item.name,
    doc_type: item.doc_type,
    owner: item.owner ?? '',
    authority: item.authority ?? '',
    identifier: item.identifier ?? '',
    issued_at: item.issued_at ?? '',
    valid_until: item.valid_until ?? '',
    notify_days_before: item.notify_days_before,
    blocks_schedule: item.blocks_schedule,
    status: MANUAL_STATUSES.includes(item.status as SourceDocManualStatus)
      ? (item.status as SourceDocManualStatus)
      : 'requested',
    notes: item.notes,
  };
}

function DocumentModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
}: {
  onClose: () => void;
  onSubmit: (data: DocumentFormData) => void;
  isPending: boolean;
  initialData?: DocumentFormData | null;
  isEdit?: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<DocumentFormData>(initialData ?? EMPTY_DOC_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof DocumentFormData>(key: K, value: DocumentFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const nameError = touched && form.name.trim().length === 0;
  const canSubmit = form.name.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="lg"
      title={
        isEdit
          ? t('source_data.edit_document', { defaultValue: 'Edit Document' })
          : t('source_data.new_document', { defaultValue: 'Register Document' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : !isEdit ? (
              <Plus size={16} className="mr-1.5 shrink-0" />
            ) : null}
            <span>
              {isEdit
                ? t('source_data.save_document', { defaultValue: 'Save Changes' })
                : t('source_data.create_document', { defaultValue: 'Register Document' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('source_data.section_details', { defaultValue: 'Document Details' })}
        columns={2}
      >
        <WideModalField
          label={t('source_data.field_name', { defaultValue: 'Name' })}
          required
          span={2}
          htmlFor="sd-name"
          error={
            nameError
              ? t('source_data.name_required', { defaultValue: 'Name is required' })
              : undefined
          }
        >
          <input
            id="sd-name"
            value={form.name}
            onChange={(e) => {
              set('name', e.target.value);
              setTouched(true);
            }}
            placeholder={t('source_data.name_placeholder', {
              defaultValue: 'e.g. Building permit no. 2026-0417',
            })}
            className={clsx(
              inputCls,
              nameError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
          />
        </WideModalField>

        <WideModalField label={t('source_data.field_type', { defaultValue: 'Type' })} htmlFor="sd-type">
          <select
            id="sd-type"
            value={form.doc_type}
            onChange={(e) => set('doc_type', e.target.value as SourceDocType)}
            className={inputCls}
          >
            {DOC_TYPES_LIST.map((tp) => (
              <option key={tp} value={tp}>
                {t(`source_data.doc_type_${tp}`, { defaultValue: DOC_TYPE_LABELS[tp] })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('source_data.field_status', { defaultValue: 'Status' })} htmlFor="sd-status">
          <select
            id="sd-status"
            value={form.status}
            onChange={(e) => set('status', e.target.value as SourceDocManualStatus)}
            className={inputCls}
          >
            {MANUAL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`source_data.status_${s}`, { defaultValue: STATUS_LABELS[s] })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('source_data.field_owner', { defaultValue: 'Owner' })} htmlFor="sd-owner">
          <input
            id="sd-owner"
            value={form.owner}
            onChange={(e) => set('owner', e.target.value)}
            className={inputCls}
            placeholder={t('source_data.owner_placeholder', { defaultValue: 'Who is responsible' })}
          />
        </WideModalField>

        <WideModalField
          label={t('source_data.field_authority', { defaultValue: 'Issuing authority' })}
          htmlFor="sd-authority"
        >
          <input
            id="sd-authority"
            value={form.authority}
            onChange={(e) => set('authority', e.target.value)}
            className={inputCls}
            placeholder={t('source_data.authority_placeholder', {
              defaultValue: 'Who issues or approves it',
            })}
          />
        </WideModalField>

        <WideModalField
          label={t('source_data.field_identifier', { defaultValue: 'Identifier' })}
          htmlFor="sd-identifier"
        >
          <input
            id="sd-identifier"
            value={form.identifier}
            onChange={(e) => set('identifier', e.target.value)}
            className={inputCls}
            placeholder={t('source_data.identifier_placeholder', { defaultValue: 'Reference number' })}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('source_data.section_validity', { defaultValue: 'Validity' })}
        columns={2}
      >
        <WideModalField label={t('source_data.field_issued_at', { defaultValue: 'Issued on' })} htmlFor="sd-issued">
          <input
            id="sd-issued"
            type="date"
            value={form.issued_at}
            onChange={(e) => set('issued_at', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('source_data.field_valid_until', { defaultValue: 'Valid until' })}
          htmlFor="sd-valid-until"
          hint={t('source_data.hint_valid_until', {
            defaultValue: 'Leave blank for a document with no expiry.',
          })}
        >
          <input
            id="sd-valid-until"
            type="date"
            value={form.valid_until}
            onChange={(e) => set('valid_until', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('source_data.field_notify_days', { defaultValue: 'Notify before (days)' })}
          htmlFor="sd-notify"
          hint={t('source_data.hint_notify_days', {
            defaultValue: 'How many days ahead of expiry to flag it as expiring soon.',
          })}
        >
          <input
            id="sd-notify"
            type="number"
            min={0}
            max={365}
            value={form.notify_days_before}
            onChange={(e) => set('notify_days_before', Number(e.target.value) || 0)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField label={t('source_data.field_blocks_schedule', { defaultValue: 'Schedule impact' })}>
          <label className="flex h-10 items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={form.blocks_schedule}
              onChange={(e) => set('blocks_schedule', e.target.checked)}
              className="shrink-0 accent-oe-blue"
            />
            {t('source_data.blocks_schedule_label', {
              defaultValue: 'Work cannot start without this document',
            })}
          </label>
        </WideModalField>

        <WideModalField
          label={t('source_data.field_notes', { defaultValue: 'Notes' })}
          span={2}
          htmlFor="sd-notes"
        >
          <textarea
            id="sd-notes"
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('source_data.notes_placeholder', { defaultValue: 'Additional notes...' })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Document Row ──────────────────────────────────────────────────────── */

function DocumentRow({
  item,
  onEdit,
  onDelete,
  onVerify,
  verifying,
}: {
  item: SourceDocument;
  onEdit: (item: SourceDocument) => void;
  onDelete: (item: SourceDocument) => void;
  onVerify: (item: SourceDocument) => void;
  verifying: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-border-light last:border-b-0 hover:bg-surface-secondary/50 transition-colors">
      <Link
        to={`/files?q=${encodeURIComponent(item.name)}`}
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1 text-sm font-medium text-content-primary truncate flex-1 min-w-0 hover:text-oe-blue hover:underline"
        title={t('source_data.open_document', {
          defaultValue: 'Find "{{name}}" in Project Files',
          name: item.name,
        })}
      >
        <span className="truncate">{item.name}</span>
        <ExternalLink size={11} className="shrink-0 opacity-60" aria-hidden="true" />
        {item.blocks_schedule && (
          <AlertOctagon
            size={12}
            className="inline-block ml-1 -mt-0.5 shrink-0 text-semantic-error"
            aria-label={t('source_data.blocks_schedule_badge', { defaultValue: 'Blocks schedule' })}
          />
        )}
      </Link>

      <Badge variant="neutral" size="sm" className="hidden md:inline-flex shrink-0">
        {t(`source_data.doc_type_${item.doc_type}`, {
          defaultValue: DOC_TYPE_LABELS[item.doc_type] ?? item.doc_type,
        })}
      </Badge>

      <Badge variant={statusVariant(item.status)} size="sm" className="shrink-0">
        {t(`source_data.status_${item.status}`, {
          defaultValue: STATUS_LABELS[item.status] ?? item.status,
        })}
      </Badge>

      {item.days_until_expiry !== null && (
        <span
          className={clsx(
            'hidden sm:inline text-xs tabular-nums w-20 text-right shrink-0',
            item.days_until_expiry < 0
              ? 'text-semantic-error font-medium'
              : item.days_until_expiry <= 14
                ? 'text-semantic-warning font-medium'
                : 'text-content-tertiary',
          )}
        >
          {item.days_until_expiry < 0
            ? t('source_data.expired_days_ago', {
                defaultValue: 'Expired {{count}}d ago',
                count: Math.abs(item.days_until_expiry),
              })
            : t('source_data.expires_in_days', {
                defaultValue: '{{count}}d left',
                count: item.days_until_expiry,
              })}
        </span>
      )}

      <span className="hidden lg:block text-xs text-content-tertiary w-28 truncate shrink-0" title={item.owner ?? ''}>
        {item.owner || '—'}
      </span>

      <span className="hidden sm:block text-xs w-24 shrink-0">
        <DateDisplay value={item.valid_until} className="text-xs text-content-tertiary" />
      </span>

      <div className="flex items-center gap-1 shrink-0">
        {item.status !== 'verified' && (
          <Button
            variant="secondary"
            size="sm"
            icon={<ShieldCheck size={13} />}
            disabled={verifying}
            onClick={() => onVerify(item)}
            data-testid={`source-data-verify-${item.id}`}
          >
            {t('source_data.verify', { defaultValue: 'Verify' })}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          icon={<Pencil size={13} />}
          onClick={() => onEdit(item)}
          aria-label={t('common.edit', { defaultValue: 'Edit' })}
          data-testid={`source-data-edit-${item.id}`}
        />
        <Button
          variant="ghost"
          size="sm"
          className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
          icon={<Trash2 size={13} />}
          onClick={() => onDelete(item)}
          aria-label={t('common.delete', { defaultValue: 'Delete' })}
          data-testid={`source-data-delete-${item.id}`}
        />
      </div>
    </div>
  );
}

/* ── Checklist item row ───────────────────────────────────────────────── */

function ChecklistRow({
  item,
  onCycleStatus,
  onDelete,
}: {
  item: SourceChecklistItem;
  onCycleStatus: (item: SourceChecklistItem) => void;
  onDelete: (item: SourceChecklistItem) => void;
}) {
  const { t } = useTranslation();
  const StatusIcon =
    item.status === 'satisfied' ? CheckCircle2 : item.status === 'waived' ? Ban : Circle;
  const iconColor =
    item.status === 'satisfied'
      ? 'text-semantic-success'
      : item.status === 'waived'
        ? 'text-content-tertiary'
        : 'text-content-quaternary';

  return (
    <div className="flex items-center gap-3 px-3 py-2 border-b border-border-light last:border-b-0">
      <button
        type="button"
        onClick={() => onCycleStatus(item)}
        className="shrink-0"
        title={t('source_data.cycle_status', { defaultValue: 'Cycle status' })}
        data-testid={`source-data-checklist-cycle-${item.id}`}
      >
        <StatusIcon size={16} className={iconColor} />
      </button>
      <span
        className={clsx(
          'text-sm flex-1 min-w-0 truncate',
          item.status === 'satisfied' && 'text-content-tertiary line-through',
        )}
      >
        {item.label}
      </span>
      {item.required && (
        <Badge variant="neutral" size="sm" className="shrink-0">
          {t('source_data.required', { defaultValue: 'Required' })}
        </Badge>
      )}
      <Badge variant={item.status === 'satisfied' ? 'success' : item.status === 'waived' ? 'neutral' : 'warning'} size="sm" className="shrink-0">
        {t(`source_data.checklist_status_${item.status}`, {
          defaultValue: CHECKLIST_STATUS_LABELS[item.status],
        })}
      </Badge>
      <Button
        variant="ghost"
        size="sm"
        icon={<Trash2 size={12} />}
        onClick={() => onDelete(item)}
        aria-label={t('common.delete', { defaultValue: 'Delete' })}
        data-testid={`source-data-checklist-delete-${item.id}`}
      />
    </div>
  );
}

/* ── Defective inputs notice panel ────────────────────────────────────── */

function DefectiveInputsPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ['source-data-defective-notice', projectId],
    queryFn: () => fetchDefectiveInputsNotice(projectId),
    enabled: !!projectId,
  });

  if (!data || !data.has_defects) return null;

  return (
    <Card padding="sm" className="border-semantic-error/30 bg-semantic-error-bg/40">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          <Mail size={16} className="mt-0.5 shrink-0 text-semantic-error" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-content-primary">
              {t('source_data.defective_notice_title', {
                defaultValue: 'Defective or missing source data',
              })}
            </p>
            <p className="mt-0.5 text-xs text-content-secondary">{data.summary}</p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)}>
          {open
            ? t('common.hide', { defaultValue: 'Hide' })
            : t('source_data.view_details', { defaultValue: 'View details' })}
        </Button>
      </div>
      {open && (
        <div className="mt-3 space-y-2 border-t border-border-light/60 pt-3 text-xs">
          {data.missing_items.length > 0 && (
            <div>
              <p className="font-medium text-content-secondary mb-1">
                {t('source_data.missing_items', { defaultValue: 'Missing prerequisites' })}
              </p>
              <ul className="list-disc pl-4 space-y-0.5 text-content-tertiary">
                {data.missing_items.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {data.expired_documents.length > 0 && (
            <div>
              <p className="font-medium text-content-secondary mb-1">
                {t('source_data.expired_documents', { defaultValue: 'Expired documents' })}
              </p>
              <ul className="list-disc pl-4 space-y-0.5 text-content-tertiary">
                {data.expired_documents.map((d, i) => (
                  <li key={i}>{typeof d.name === 'string' ? d.name : JSON.stringify(d)}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-content-tertiary">
            {t('source_data.defective_notice_hint', {
              defaultValue:
                'This is structured data only. Use Correspondence to draft the actual notice from it.',
            })}
          </p>
        </div>
      )}
    </Card>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function SourceDataPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingItem, setEditingItem] = useState<SourceDocument | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<SourceDocStatus | ''>('');
  const [typeFilter, setTypeFilter] = useState<SourceDocType | ''>('');
  const [newChecklistLabel, setNewChecklistLabel] = useState('');
  const { confirm, ...confirmProps } = useConfirm();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const projectName = projects.find((p) => p.id === selectedProjectId)?.name || '';

  const { data: meta } = useQuery({
    queryKey: ['source-data-meta'],
    queryFn: () => fetchSourceDataMeta(),
    staleTime: 10 * 60_000,
  });

  const {
    data: documents = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['source-data-documents', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchSourceDocuments({
        project_id: projectId,
        status: statusFilter || undefined,
        doc_type: typeFilter || undefined,
      }),
    enabled: !!projectId,
  });

  const { data: expiringSoon = [] } = useQuery({
    queryKey: ['source-data-expiring-soon', projectId],
    queryFn: () => fetchExpiringSoon(projectId),
    enabled: !!projectId,
  });

  const { data: blocking = [] } = useQuery({
    queryKey: ['source-data-blocking', projectId],
    queryFn: () => fetchBlockingSchedule(projectId),
    enabled: !!projectId,
  });

  const { data: checklistSummary } = useQuery({
    queryKey: ['source-data-checklist-summary', projectId],
    queryFn: () => fetchChecklistSummary(projectId),
    enabled: !!projectId,
  });

  const { data: checklist = [] } = useQuery({
    queryKey: ['source-data-checklist', projectId],
    queryFn: () => fetchChecklist(projectId),
    enabled: !!projectId,
  });

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return documents;
    const q = searchQuery.toLowerCase();
    return documents.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        (d.owner ?? '').toLowerCase().includes(q) ||
        (d.authority ?? '').toLowerCase().includes(q) ||
        (d.identifier ?? '').toLowerCase().includes(q),
    );
  }, [documents, searchQuery]);

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['source-data-documents'] });
    qc.invalidateQueries({ queryKey: ['source-data-expiring-soon'] });
    qc.invalidateQueries({ queryKey: ['source-data-blocking'] });
    qc.invalidateQueries({ queryKey: ['source-data-defective-notice'] });
  }, [qc]);

  const invalidateChecklist = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['source-data-checklist'] });
    qc.invalidateQueries({ queryKey: ['source-data-checklist-summary'] });
  }, [qc]);

  const createMut = useMutation({
    mutationFn: (data: CreateSourceDocumentPayload) => createSourceDocument(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({ type: 'success', title: t('source_data.created', { defaultValue: 'Document registered' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateSourceDocumentPayload }) =>
      updateSourceDocument(id, data),
    onSuccess: () => {
      invalidateAll();
      setEditingItem(null);
      addToast({ type: 'success', title: t('source_data.updated', { defaultValue: 'Document updated' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const verifyMut = useMutation({
    mutationFn: (id: string) => verifySourceDocument(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('source_data.verified', { defaultValue: 'Document verified' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSourceDocument(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('source_data.deleted', { defaultValue: 'Document deleted' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const createChecklistMut = useMutation({
    mutationFn: (label: string) =>
      createChecklistItem({ project_id: projectId, label, required: true }),
    onSuccess: () => {
      invalidateChecklist();
      setNewChecklistLabel('');
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const updateChecklistMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: ChecklistItemStatus }) =>
      updateChecklistItem(id, { status }),
    onSuccess: () => invalidateChecklist(),
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const deleteChecklistMut = useMutation({
    mutationFn: (id: string) => deleteChecklistItem(id),
    onSuccess: () => invalidateChecklist(),
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const buildPayload = useCallback(
    (formData: DocumentFormData): CreateSourceDocumentPayload => ({
      project_id: projectId,
      name: formData.name,
      doc_type: formData.doc_type,
      owner: formData.owner || undefined,
      authority: formData.authority || undefined,
      identifier: formData.identifier || undefined,
      issued_at: formData.issued_at || undefined,
      valid_until: formData.valid_until || undefined,
      notify_days_before: formData.notify_days_before,
      blocks_schedule: formData.blocks_schedule,
      status: formData.status,
      notes: formData.notes,
    }),
    [projectId],
  );

  const handleCreate = (formData: DocumentFormData) => {
    createMut.mutate(buildPayload(formData));
  };

  const handleUpdate = (formData: DocumentFormData) => {
    if (!editingItem) return;
    const { project_id: _pid, ...rest } = buildPayload(formData);
    // Rebuild the baseline the modal started from, so the save carries only
    // what the user actually edited. See `documentFormData`.
    updateMut.mutate({
      id: editingItem.id,
      data: onlyChangedFields(rest, formData, documentFormData(editingItem)),
    });
  };

  const handleDelete = async (item: SourceDocument) => {
    const ok = await confirm({
      title: t('source_data.confirm_delete_title', { defaultValue: 'Delete document?' }),
      message: t('source_data.confirm_delete_message', {
        defaultValue: 'This removes "{{name}}" from the register. This cannot be undone.',
        name: item.name,
      }),
    });
    if (ok) deleteMut.mutate(item.id);
  };

  const handleDeleteChecklistItem = async (item: SourceChecklistItem) => {
    const ok = await confirm({
      title: t('source_data.confirm_delete_checklist_title', { defaultValue: 'Delete checklist item?' }),
      message: t('source_data.confirm_delete_checklist_message', {
        defaultValue: 'This removes "{{label}}" from the checklist.',
        label: item.label,
      }),
    });
    if (ok) deleteChecklistMut.mutate(item.id);
  };

  const cycleChecklistStatus = (item: SourceChecklistItem) => {
    const next: ChecklistItemStatus =
      item.status === 'pending' ? 'satisfied' : item.status === 'satisfied' ? 'waived' : 'pending';
    updateChecklistMut.mutate({ id: item.id, status: next });
  };

  const editFormData: DocumentFormData | null = editingItem ? documentFormData(editingItem) : null;

  const breadcrumbItems = selectedProjectId
    ? [
        { label: t('nav.projects', { defaultValue: 'Projects' }), to: '/projects' },
        { label: projectName || t('common.project', { defaultValue: 'Project' }) },
        { label: t('source_data.title', { defaultValue: 'Source Data Register' }) },
      ]
    : [];

  return (
    <div className="space-y-5">
      <Breadcrumb items={breadcrumbItems} />

      <PageHeader
        srTitle={t('source_data.title', { defaultValue: 'Source Data Register' })}
        subtitle={t('source_data.subtitle', {
          defaultValue:
            'Track prerequisite documents, validity windows, renewal reminders and what is blocking the schedule.',
        })}
        actions={
          <>
            <ModuleGuideButton content={sourceDataGuide} />
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              data-testid="source-data-new-document"
            >
              {t('source_data.new_document', { defaultValue: 'Register Document' })}
            </Button>
          </>
        }
      />

      {!projectId ? (
        <EmptyState
          icon={<FileStack size={24} />}
          title={t('source_data.no_project_title', { defaultValue: 'No project selected' })}
          description={t('source_data.no_project_description', {
            defaultValue: 'Pick a project to see its source data register.',
          })}
        />
      ) : (
        <>
          <DefectiveInputsPanel projectId={projectId} />

          {/* Summary panels */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Card padding="sm">
              <div className="flex items-center gap-2">
                <Clock size={15} className="text-semantic-warning shrink-0" />
                <span className="text-sm font-semibold text-content-primary">
                  {t('source_data.expiring_soon_title', { defaultValue: 'Expiring soon' })}
                </span>
                <Badge variant="warning" size="sm" className="ml-auto">
                  {expiringSoon.length}
                </Badge>
              </div>
              {expiringSoon.length === 0 ? (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('source_data.expiring_soon_empty', { defaultValue: 'Nothing due for renewal.' })}
                </p>
              ) : (
                <ul className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                  {expiringSoon.slice(0, 6).map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-2 text-xs">
                      <span className="truncate text-content-secondary">{d.name}</span>
                      <span
                        className={clsx(
                          'shrink-0 tabular-nums',
                          (d.days_until_expiry ?? 0) < 0 ? 'text-semantic-error' : 'text-semantic-warning',
                        )}
                      >
                        {d.days_until_expiry !== null
                          ? d.days_until_expiry < 0
                            ? t('source_data.expired_days_ago', {
                                defaultValue: 'Expired {{count}}d ago',
                                count: Math.abs(d.days_until_expiry),
                              })
                            : t('source_data.expires_in_days', {
                                defaultValue: '{{count}}d left',
                                count: d.days_until_expiry,
                              })
                          : '—'}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card padding="sm">
              <div className="flex items-center gap-2">
                <AlertOctagon size={15} className="text-semantic-error shrink-0" />
                {blocking.length > 0 ? (
                  <Link
                    to="/schedule"
                    className="inline-flex items-center gap-1 text-sm font-semibold text-content-primary hover:text-oe-blue hover:underline"
                    title={t('source_data.open_schedule', { defaultValue: 'Open the project schedule' })}
                  >
                    {t('source_data.blocking_title', { defaultValue: 'Blocking the schedule' })}
                    <ExternalLink size={11} className="shrink-0 opacity-60" aria-hidden="true" />
                  </Link>
                ) : (
                  <span className="text-sm font-semibold text-content-primary">
                    {t('source_data.blocking_title', { defaultValue: 'Blocking the schedule' })}
                  </span>
                )}
                <Badge variant="error" size="sm" className="ml-auto">
                  {blocking.length}
                </Badge>
              </div>
              {blocking.length === 0 ? (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('source_data.blocking_empty', { defaultValue: 'Nothing is blocking the schedule.' })}
                </p>
              ) : (
                <ul className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                  {blocking.slice(0, 6).map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-2 text-xs">
                      <span className="truncate text-content-secondary">{d.name}</span>
                      <Badge variant={statusVariant(d.status)} size="sm">
                        {t(`source_data.status_${d.status}`, {
                          defaultValue: STATUS_LABELS[d.status] ?? d.status,
                        })}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card padding="sm">
              <div className="flex items-center gap-2">
                <ListChecks size={15} className="text-oe-blue shrink-0" />
                <span className="text-sm font-semibold text-content-primary">
                  {t('source_data.checklist_title', { defaultValue: 'Checklist completeness' })}
                </span>
                {checklistSummary && (
                  <Badge variant={checklistSummary.complete ? 'success' : 'warning'} size="sm" className="ml-auto">
                    {checklistSummary.satisfied + checklistSummary.waived}/{checklistSummary.required}
                  </Badge>
                )}
              </div>
              {checklistSummary ? (
                checklistSummary.missing_required.length === 0 ? (
                  <p className="mt-2 text-xs text-content-tertiary">
                    {checklistSummary.complete
                      ? t('source_data.checklist_complete', { defaultValue: 'All required items satisfied.' })
                      : t('source_data.checklist_none', { defaultValue: 'No checklist items yet.' })}
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                    {checklistSummary.missing_required.slice(0, 6).map((label) => (
                      <li key={label} className="text-xs text-content-secondary truncate">
                        {label}
                      </li>
                    ))}
                  </ul>
                )
              ) : (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('common.loading', { defaultValue: 'Loading…' })}
                </p>
              )}
            </Card>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search size={14} className="absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('source_data.search_placeholder', { defaultValue: 'Search documents...' })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as SourceDocType | '')}
              className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
            >
              <option value="">{t('source_data.filter_all_types', { defaultValue: 'All types' })}</option>
              {(meta?.doc_types ?? DOC_TYPES_LIST.map((c) => ({ code: c, label: DOC_TYPE_LABELS[c] }))).map(
                (o) => (
                  <option key={o.code} value={o.code}>
                    {o.label}
                  </option>
                ),
              )}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as SourceDocStatus | '')}
              className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
            >
              <option value="">{t('source_data.filter_all_statuses', { defaultValue: 'All statuses' })}</option>
              {(meta?.statuses ?? Object.entries(STATUS_LABELS).map(([code, label]) => ({ code, label }))).map(
                (o) => (
                  <option key={o.code} value={o.code}>
                    {o.label}
                  </option>
                ),
              )}
            </select>
          </div>

          {/* Document register */}
          {isLoading ? (
            <SkeletonTable rows={6} columns={5} />
          ) : isError ? (
            <EmptyState
              icon={<FileStack size={24} />}
              title={t('source_data.load_error_title', { defaultValue: 'Could not load documents' })}
              description={error instanceof Error ? error.message : undefined}
              action={{ label: t('common.retry', { defaultValue: 'Retry' }), onClick: () => refetch() }}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<FileStack size={24} />}
              title={t('source_data.empty_title', { defaultValue: 'No source documents yet' })}
              description={t('source_data.empty_description', {
                defaultValue: 'Register the first prerequisite document for this project.',
              })}
              action={{
                label: t('source_data.new_document', { defaultValue: 'Register Document' }),
                onClick: () => setShowCreateModal(true),
              }}
            />
          ) : (
            <Card padding="none">
              {filtered.map((item) => (
                <DocumentRow
                  key={item.id}
                  item={item}
                  onEdit={setEditingItem}
                  onDelete={handleDelete}
                  onVerify={(d) => verifyMut.mutate(d.id)}
                  verifying={verifyMut.isPending}
                />
              ))}
            </Card>
          )}

          {/* Checklist */}
          <Card padding="sm">
            <CardHeader
              title={t('source_data.checklist_section_title', { defaultValue: 'Completeness checklist' })}
              subtitle={t('source_data.checklist_section_subtitle', {
                defaultValue: 'Track everything this project needs before work can proceed.',
              })}
            />
            <CardContent>
              {checklist.length === 0 ? (
                <p className="py-3 text-xs text-content-tertiary">
                  {t('source_data.checklist_none', { defaultValue: 'No checklist items yet.' })}
                </p>
              ) : (
                <div className="rounded-lg border border-border-light overflow-hidden">
                  {checklist.map((item) => (
                    <ChecklistRow
                      key={item.id}
                      item={item}
                      onCycleStatus={cycleChecklistStatus}
                      onDelete={handleDeleteChecklistItem}
                    />
                  ))}
                </div>
              )}
              <div className="mt-3 flex items-center gap-2">
                <input
                  value={newChecklistLabel}
                  onChange={(e) => setNewChecklistLabel(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newChecklistLabel.trim()) {
                      createChecklistMut.mutate(newChecklistLabel.trim());
                    }
                  }}
                  placeholder={t('source_data.checklist_add_placeholder', {
                    defaultValue: 'Add a checklist item...',
                  })}
                  className={clsx(inputCls, 'flex-1')}
                  data-testid="source-data-checklist-input"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Plus size={13} />}
                  disabled={!newChecklistLabel.trim() || createChecklistMut.isPending}
                  onClick={() => createChecklistMut.mutate(newChecklistLabel.trim())}
                  data-testid="source-data-checklist-add"
                >
                  {t('common.add', { defaultValue: 'Add' })}
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {showCreateModal && (
        <DocumentModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreate}
          isPending={createMut.isPending}
        />
      )}

      {editingItem && editFormData && (
        <DocumentModal
          onClose={() => setEditingItem(null)}
          onSubmit={handleUpdate}
          isPending={updateMut.isPending}
          initialData={editFormData}
          isEdit
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

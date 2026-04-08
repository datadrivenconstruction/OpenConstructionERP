import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Mail,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  ArrowDownLeft,
  ArrowUpRight,
  FileText,
  Cloud,
  Webhook,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, DateDisplay, SkeletonTable } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchCorrespondence,
  createCorrespondence,
  type Correspondence,
  type CorrespondenceDirection,
  type CorrespondenceType,
  type CreateCorrespondencePayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const TYPE_LABELS: Record<CorrespondenceType, string> = {
  letter: 'Letter',
  email: 'Email',
  notice: 'Notice',
  memo: 'Memo',
  other: 'Other',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface CorrespondenceFormData {
  subject: string;
  direction: CorrespondenceDirection;
  type: CorrespondenceType;
  from_contact: string;
  to_contacts: string;
  date_sent: string;
  date_received: string;
  notes: string;
}

const EMPTY_FORM: CorrespondenceFormData = {
  subject: '',
  direction: 'outgoing',
  type: 'email',
  from_contact: '',
  to_contacts: '',
  date_sent: '',
  date_received: '',
  notes: '',
};

function CreateCorrespondenceModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: CorrespondenceFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CorrespondenceFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof CorrespondenceFormData>(
    key: K,
    value: CorrespondenceFormData[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  const subjectError = touched && form.subject.trim().length === 0;
  const fromError = touched && form.from_contact.trim().length === 0;
  const canSubmit = form.subject.trim().length > 0 && form.from_contact.trim().length > 0;

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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('correspondence.new_entry', { defaultValue: 'New Entry' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('correspondence.new_entry', { defaultValue: 'New Entry' })}
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
              {t('correspondence.field_subject', { defaultValue: 'Subject' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.subject}
              onChange={(e) => {
                set('subject', e.target.value);
                setTouched(true);
              }}
              placeholder={t('correspondence.subject_placeholder', {
                defaultValue: 'e.g. Notice of delay - Foundation works',
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
                {t('correspondence.subject_required', { defaultValue: 'Subject is required' })}
              </p>
            )}
          </div>

          {/* Two-column: Direction + Type */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_direction', { defaultValue: 'Direction' })}
              </label>
              <div className="relative">
                <select
                  value={form.direction}
                  onChange={(e) => set('direction', e.target.value as CorrespondenceDirection)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  <option value="incoming">
                    {t('correspondence.dir_incoming', { defaultValue: 'Incoming' })}
                  </option>
                  <option value="outgoing">
                    {t('correspondence.dir_outgoing', { defaultValue: 'Outgoing' })}
                  </option>
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_type', { defaultValue: 'Type' })}
              </label>
              <div className="relative">
                <select
                  value={form.type}
                  onChange={(e) => set('type', e.target.value as CorrespondenceType)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  {(Object.keys(TYPE_LABELS) as CorrespondenceType[]).map((tp) => (
                    <option key={tp} value={tp}>
                      {t(`correspondence.type_${tp}`, { defaultValue: TYPE_LABELS[tp] })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
          </div>

          {/* Two-column: From + To */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_from', { defaultValue: 'From' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                value={form.from_contact}
                onChange={(e) => {
                  set('from_contact', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('correspondence.from_placeholder', {
                  defaultValue: 'Sender name or company',
                })}
                className={clsx(
                  inputCls,
                  fromError &&
                    'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
              />
              {fromError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('correspondence.from_required', { defaultValue: 'From is required' })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_to', { defaultValue: 'To' })}
              </label>
              <input
                value={form.to_contacts}
                onChange={(e) => set('to_contacts', e.target.value)}
                placeholder={t('correspondence.to_placeholder', {
                  defaultValue: 'Recipient(s), comma-separated',
                })}
                className={inputCls}
              />
            </div>
          </div>

          {/* Two-column: Date Sent + Date Received */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_date_sent', { defaultValue: 'Date Sent' })}
              </label>
              <input
                type="date"
                value={form.date_sent}
                onChange={(e) => set('date_sent', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('correspondence.field_date_received', { defaultValue: 'Date Received' })}
              </label>
              <input
                type="date"
                value={form.date_received}
                onChange={(e) => set('date_received', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('correspondence.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
              rows={3}
              className={textareaCls}
              placeholder={t('correspondence.notes_placeholder', {
                defaultValue: 'Additional notes...',
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
              {t('correspondence.create_entry', { defaultValue: 'Create Entry' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Correspondence Row (expandable) ──────────────────────────────────── */

const CorrespondenceRow = React.memo(function CorrespondenceRow({ item }: { item: Correspondence }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

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

        {/* Ref # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          {item.ref_number}
        </span>

        {/* Subject */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {item.subject}
        </span>

        {/* Direction badge */}
        <Badge
          variant={item.direction === 'incoming' ? 'blue' : 'success'}
          size="sm"
          className="shrink-0"
        >
          {item.direction === 'incoming' ? (
            <ArrowDownLeft size={11} className="mr-1" />
          ) : (
            <ArrowUpRight size={11} className="mr-1" />
          )}
          {t(`correspondence.dir_${item.direction}`, {
            defaultValue: item.direction === 'incoming' ? 'Incoming' : 'Outgoing',
          })}
        </Badge>

        {/* Type */}
        <Badge variant="neutral" size="sm" className="hidden md:inline-flex">
          {t(`correspondence.type_${item.type}`, { defaultValue: TYPE_LABELS[item.type] })}
        </Badge>

        {/* From */}
        <span className="text-xs text-content-tertiary w-24 truncate shrink-0 hidden lg:block">
          {item.from_contact}
        </span>

        {/* To */}
        <span className="text-xs text-content-tertiary w-24 truncate shrink-0 hidden lg:block">
          {item.to_contacts.length > 0 ? item.to_contacts.join(', ') : '-'}
        </span>

        {/* Date */}
        <span className="text-xs w-20 shrink-0 hidden sm:block">
          <DateDisplay
            value={item.direction === 'outgoing' ? item.date_sent : item.date_received}
            className="text-xs text-content-tertiary"
          />
        </span>

        {/* Linked docs count */}
        {item.linked_docs_count > 0 && (
          <span className="flex items-center gap-1 text-xs text-content-tertiary shrink-0">
            <FileText size={12} />
            {item.linked_docs_count}
          </span>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          <div className="flex items-center gap-4 text-xs text-content-tertiary flex-wrap">
            <span>
              {t('correspondence.label_from', { defaultValue: 'From' })}: {item.from_contact}
            </span>
            <span>
              {t('correspondence.label_to', { defaultValue: 'To' })}:{' '}
              {item.to_contacts.length > 0 ? item.to_contacts.join(', ') : '-'}
            </span>
            <span>
              {t('correspondence.label_sent', { defaultValue: 'Sent' })}:{' '}
              <DateDisplay value={item.date_sent} className="text-xs" />
            </span>
            <span>
              {t('correspondence.label_received', { defaultValue: 'Received' })}:{' '}
              <DateDisplay value={item.date_received} className="text-xs" />
            </span>
          </div>

          {item.notes && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('correspondence.label_notes', { defaultValue: 'Notes' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{item.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

/* ── Connector Card ───────────────────────────────────────────────────── */

function ConnectorCard({
  name,
  status,
  icon: Icon,
  description,
}: {
  name: string;
  status: 'available' | 'coming_soon';
  icon: React.ElementType;
  description: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border-light bg-surface-primary p-3 transition-colors hover:border-border-medium">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={16} className="shrink-0 text-content-tertiary" />
          <span className="text-sm font-medium text-content-primary truncate">{name}</span>
        </div>
        <Badge
          variant={status === 'available' ? 'success' : 'neutral'}
          size="sm"
          className="shrink-0"
        >
          {status === 'available'
            ? t('correspondence.connector_available', { defaultValue: 'Available' })
            : t('correspondence.connector_coming_soon', { defaultValue: 'Coming Soon' })}
        </Badge>
      </div>
      <p className="text-xs text-content-tertiary leading-relaxed">{description}</p>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CorrespondencePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [directionFilter, setDirectionFilter] = useState<CorrespondenceDirection | ''>('');
  const [typeFilter, setTypeFilter] = useState<CorrespondenceType | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['correspondence', projectId, directionFilter, typeFilter],
    queryFn: () =>
      fetchCorrespondence({
        project_id: projectId,
        direction: directionFilter || undefined,
        type: typeFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const q = searchQuery.toLowerCase();
    return items.filter(
      (c) =>
        c.subject.toLowerCase().includes(q) ||
        c.ref_number.toLowerCase().includes(q) ||
        c.from_contact.toLowerCase().includes(q) ||
        c.to_contacts.some((tc) => tc.toLowerCase().includes(q)),
    );
  }, [items, searchQuery]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['correspondence'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateCorrespondencePayload) => createCorrespondence(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('correspondence.created', { defaultValue: 'Entry created' }),
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
    (formData: CorrespondenceFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        subject: formData.subject,
        direction: formData.direction,
        type: formData.type,
        from_contact: formData.from_contact,
        to_contacts: formData.to_contacts
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        date_sent: formData.date_sent || undefined,
        date_received: formData.date_received || undefined,
        notes: formData.notes || undefined,
      });
    },
    [createMut, projectId, addToast, t],
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
          { label: t('correspondence.title', { defaultValue: 'Correspondence' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold text-content-primary shrink-0">
          {t('correspondence.page_title', { defaultValue: 'Correspondence' })}
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
                {t('correspondence.select_project', { defaultValue: 'Project...' })}
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
            <span>{t('correspondence.new_entry', { defaultValue: 'New Entry' })}</span>
          </Button>
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_first', { defaultValue: 'Please select a project to continue.' })}
        </div>
      )}

      {/* Connectors */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <ConnectorCard
          name={t('correspondence.connector_email', { defaultValue: 'Email (IMAP/SMTP)' })}
          status="available"
          icon={Mail}
          description={t('correspondence.connector_email_desc', { defaultValue: 'Auto-import incoming/outgoing project emails' })}
        />
        <ConnectorCard
          name={t('correspondence.connector_m365', { defaultValue: 'Microsoft 365' })}
          status="coming_soon"
          icon={Cloud}
          description={t('correspondence.connector_m365_desc', { defaultValue: 'Outlook emails & Teams messages' })}
        />
        <ConnectorCard
          name={t('correspondence.connector_google', { defaultValue: 'Google Workspace' })}
          status="coming_soon"
          icon={Cloud}
          description={t('correspondence.connector_google_desc', { defaultValue: 'Gmail & Google Chat' })}
        />
        <ConnectorCard
          name={t('correspondence.connector_webhook', { defaultValue: 'API Webhook' })}
          status="available"
          icon={Webhook}
          description={t('correspondence.connector_webhook_desc', { defaultValue: 'Receive correspondence via REST API' })}
        />
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
            placeholder={t('correspondence.search_placeholder', {
              defaultValue: 'Search correspondence...',
            })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Direction filter */}
        <div className="relative">
          <select
            value={directionFilter}
            onChange={(e) =>
              setDirectionFilter(e.target.value as CorrespondenceDirection | '')
            }
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-36"
          >
            <option value="">
              {t('correspondence.filter_all_dir', { defaultValue: 'All Directions' })}
            </option>
            <option value="incoming">
              {t('correspondence.dir_incoming', { defaultValue: 'Incoming' })}
            </option>
            <option value="outgoing">
              {t('correspondence.dir_outgoing', { defaultValue: 'Outgoing' })}
            </option>
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>

        {/* Type filter */}
        <div className="relative">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as CorrespondenceType | '')}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-36"
          >
            <option value="">
              {t('correspondence.filter_all_type', { defaultValue: 'All Types' })}
            </option>
            {(Object.keys(TYPE_LABELS) as CorrespondenceType[]).map((tp) => (
              <option key={tp} value={tp}>
                {t(`correspondence.type_${tp}`, { defaultValue: TYPE_LABELS[tp] })}
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
            icon={<Mail size={24} strokeWidth={1.5} />}
            title={
              searchQuery || directionFilter || typeFilter
                ? t('correspondence.no_results', { defaultValue: 'No matching entries' })
                : t('correspondence.no_entries', { defaultValue: 'No correspondence yet' })
            }
            description={
              searchQuery || directionFilter || typeFilter
                ? t('correspondence.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('correspondence.no_entries_hint', {
                    defaultValue: 'Log your first correspondence entry',
                  })
            }
            action={
              !searchQuery && !directionFilter && !typeFilter
                ? {
                    label: t('correspondence.new_entry', { defaultValue: 'New Entry' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('correspondence.showing_count', {
                defaultValue: '{{count}} entries',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface-secondary/50 text-xs font-medium text-content-tertiary uppercase tracking-wide min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('correspondence.col_subject', { defaultValue: 'Subject' })}
                </span>
                <span className="w-24 text-center">
                  {t('correspondence.col_direction', { defaultValue: 'Direction' })}
                </span>
                <span className="w-20 hidden md:block">
                  {t('correspondence.col_type', { defaultValue: 'Type' })}
                </span>
                <span className="w-24 hidden lg:block">
                  {t('correspondence.col_from', { defaultValue: 'From' })}
                </span>
                <span className="w-24 hidden lg:block">
                  {t('correspondence.col_to', { defaultValue: 'To' })}
                </span>
                <span className="w-20 hidden sm:block">
                  {t('correspondence.col_date', { defaultValue: 'Date' })}
                </span>
                <span className="w-10">
                  {t('correspondence.col_docs', { defaultValue: 'Docs' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((c) => (
                <CorrespondenceRow key={c.id} item={c} />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateCorrespondenceModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}
    </div>
  );
}

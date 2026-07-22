// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  Network,
  Plus,
  X,
  ChevronRight,
  Search,
  Trash2,
  Pencil,
  CheckCircle2,
  RotateCcw,
  AlertTriangle,
  Clock,
  Package,
  ArrowRight,
  ListChecks,
  Ban,
  HelpCircle,
  CalendarClock,
  ExternalLink,
  Link2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, ConfirmDialog } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchWorkPackageHealth,
  fetchInterfaces,
  fetchActions,
  createInterface,
  updateInterface,
  deleteInterface,
  createAction,
  updateAction,
  fetchRfiOptions,
  fetchScheduleActivityOptions,
  isInterfaceOverdue,
  parsePct,
  ALL_INTERFACE_TYPES,
  ALL_INTERFACE_STATUSES,
  ALL_PRIORITIES,
  UNASSIGNED,
  type LinkOption,
  type InterfaceRecord,
  type InterfaceAction,
  type InterfaceType,
  type InterfaceStatus,
  type InterfacePriority,
  type ActionStatus,
  type InterfaceWritePayload,
  type ActionWritePayload,
  type WorkPackageHealth,
} from './api';

/* -- Vocabulary display maps ---------------------------------------------- */

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_LABEL: Record<string, string> = {
  identified: 'Identified',
  open: 'Open',
  in_progress: 'In progress',
  agreed: 'Agreed',
  closed: 'Closed',
  disputed: 'Disputed',
  on_hold: 'On hold',
};
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  identified: 'neutral',
  open: 'blue',
  in_progress: 'blue',
  agreed: 'success',
  closed: 'success',
  disputed: 'error',
  on_hold: 'warning',
};

const PRIORITY_LABEL: Record<string, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};
const PRIORITY_VARIANT: Record<string, BadgeVariant> = {
  low: 'neutral',
  medium: 'blue',
  high: 'warning',
  critical: 'error',
};

const TYPE_LABEL: Record<string, string> = {
  physical: 'Physical',
  functional: 'Functional',
  contractual: 'Contractual',
  spatial: 'Spatial',
  information: 'Information',
  schedule: 'Schedule',
};

const ACTION_STATUS_LABEL: Record<string, string> = {
  open: 'Open',
  done: 'Done',
  cancelled: 'Cancelled',
};
const ACTION_STATUS_VARIANT: Record<string, BadgeVariant> = {
  open: 'warning',
  done: 'success',
  cancelled: 'neutral',
};

const humanize = (value: string): string => value.replace(/_/g, ' ');

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';
const selectCls =
  'h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const todayIso = (): string => new Date().toISOString().slice(0, 10);
const orNull = (s: string): string | null => (s.trim() ? s.trim() : null);

/* -- Health badge ---------------------------------------------------------- */

function HealthBadge({ open, overdue }: { open: number; overdue: number }) {
  const { t } = useTranslation();
  if (overdue > 0) {
    return (
      <Badge variant="error" size="sm" dot>
        {t('interface_management.health_at_risk', { defaultValue: 'At risk' })}
      </Badge>
    );
  }
  if (open > 0) {
    return (
      <Badge variant="warning" size="sm" dot>
        {t('interface_management.health_in_progress', { defaultValue: 'In progress' })}
      </Badge>
    );
  }
  return (
    <Badge variant="success" size="sm" dot>
      {t('interface_management.health_on_track', { defaultValue: 'On track' })}
    </Badge>
  );
}

/* -- Work-package health band (SIGNAL first) ------------------------------- */

function WorkPackageHealthCard({ wp }: { wp: WorkPackageHealth }) {
  const { t } = useTranslation();
  const score = parsePct(wp.health_score);
  const name =
    wp.work_package === UNASSIGNED
      ? t('interface_management.unassigned', { defaultValue: 'Unassigned' })
      : wp.work_package;
  return (
    <div
      className={clsx(
        'rounded-xl border bg-surface-elevated/90 p-4 shadow-xs animate-card-in',
        wp.overdue > 0 ? 'border-semantic-error/40' : 'border-border-light',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Package size={14} className="shrink-0 text-content-tertiary" />
          <span className="truncate text-sm font-semibold text-content-primary" title={name}>
            {name}
          </span>
        </div>
        <HealthBadge open={wp.open} overdue={wp.overdue} />
      </div>
      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        <div>
          <p className="text-base font-semibold tabular-nums text-content-primary">{wp.total}</p>
          <p className="text-2xs text-content-tertiary">
            {t('interface_management.stat_total', { defaultValue: 'Total' })}
          </p>
        </div>
        <div>
          <p className="text-base font-semibold tabular-nums text-content-primary">{wp.open}</p>
          <p className="text-2xs text-content-tertiary">
            {t('interface_management.stat_open', { defaultValue: 'Open' })}
          </p>
        </div>
        <div>
          <p
            className={clsx(
              'text-base font-semibold tabular-nums',
              wp.overdue > 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
          >
            {wp.overdue}
          </p>
          <p className="text-2xs text-content-tertiary">
            {t('interface_management.stat_overdue', { defaultValue: 'Overdue' })}
          </p>
        </div>
        <div>
          <p className="text-base font-semibold tabular-nums text-semantic-success">{wp.agreed}</p>
          <p className="text-2xs text-content-tertiary">
            {t('interface_management.stat_agreed', { defaultValue: 'Agreed' })}
          </p>
        </div>
      </div>
      {score != null && (
        <p className="mt-2 text-2xs text-content-tertiary">
          {t('interface_management.health_score', {
            defaultValue: 'Health {{score}}%',
            score: Math.round(score),
          })}
        </p>
      )}
    </div>
  );
}

/* -- Interface create / edit modal ---------------------------------------- */

interface InterfaceFormState {
  reference: string;
  title: string;
  interface_type: InterfaceType | '';
  status: InterfaceStatus;
  priority: InterfacePriority | '';
  owner_party: string;
  accepter_party: string;
  work_package_from: string;
  work_package_to: string;
  discipline_from: string;
  discipline_to: string;
  need_by_date: string;
  location: string;
  description: string;
  notes: string;
  rfi_id: string;
  schedule_activity_id: string;
}

const EMPTY_FORM: InterfaceFormState = {
  reference: '',
  title: '',
  interface_type: '',
  status: 'identified',
  priority: '',
  owner_party: '',
  accepter_party: '',
  work_package_from: '',
  work_package_to: '',
  discipline_from: '',
  discipline_to: '',
  need_by_date: '',
  location: '',
  description: '',
  notes: '',
  rfi_id: '',
  schedule_activity_id: '',
};

function formFromRecord(rec: InterfaceRecord): InterfaceFormState {
  const asType = ALL_INTERFACE_TYPES.includes(rec.interface_type as InterfaceType)
    ? (rec.interface_type as InterfaceType)
    : '';
  const asPriority = ALL_PRIORITIES.includes(rec.priority as InterfacePriority)
    ? (rec.priority as InterfacePriority)
    : '';
  const asStatus = ALL_INTERFACE_STATUSES.includes(rec.status as InterfaceStatus)
    ? (rec.status as InterfaceStatus)
    : 'identified';
  return {
    reference: rec.reference,
    title: rec.title,
    interface_type: asType,
    status: asStatus,
    priority: asPriority,
    owner_party: rec.owner_party ?? '',
    accepter_party: rec.accepter_party ?? '',
    work_package_from: rec.work_package_from ?? '',
    work_package_to: rec.work_package_to ?? '',
    discipline_from: rec.discipline_from ?? '',
    discipline_to: rec.discipline_to ?? '',
    need_by_date: rec.need_by_date ?? '',
    location: rec.location ?? '',
    description: rec.description ?? '',
    notes: rec.notes ?? '',
    rfi_id: rec.rfi_id ?? '',
    schedule_activity_id: rec.schedule_activity_id ?? '',
  };
}

function formToPayload(form: InterfaceFormState): InterfaceWritePayload {
  return {
    reference: form.reference.trim(),
    title: form.title.trim(),
    interface_type: form.interface_type || null,
    status: form.status,
    priority: form.priority || null,
    owner_party: orNull(form.owner_party),
    accepter_party: orNull(form.accepter_party),
    work_package_from: orNull(form.work_package_from),
    work_package_to: orNull(form.work_package_to),
    discipline_from: orNull(form.discipline_from),
    discipline_to: orNull(form.discipline_to),
    need_by_date: orNull(form.need_by_date),
    location: orNull(form.location),
    description: orNull(form.description),
    notes: orNull(form.notes),
    rfi_id: orNull(form.rfi_id),
    schedule_activity_id: orNull(form.schedule_activity_id),
  };
}

function InterfaceModal({
  initial,
  projectId,
  onClose,
  onSubmit,
  isPending,
}: {
  initial: InterfaceRecord | null;
  projectId: string;
  onClose: () => void;
  onSubmit: (payload: InterfaceWritePayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<InterfaceFormState>(
    initial ? formFromRecord(initial) : EMPTY_FORM,
  );
  const [touched, setTouched] = useState(false);

  // Linked-reference pickers. Both degrade to an empty list on failure (the
  // section still renders with a "nothing to link" note), so an unreadable RFI
  // or schedule module never blocks creating or editing an interface. If the
  // record already carries a link whose row is not in the loaded options (e.g.
  // it points at another schedule, or the user cannot read it), we still keep
  // it selectable so an edit does not silently drop the existing link.
  const rfiOptionsQuery = useQuery({
    queryKey: ['interface-management', 'rfi-options', projectId],
    queryFn: () => fetchRfiOptions(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const activityOptionsQuery = useQuery({
    queryKey: ['interface-management', 'activity-options', projectId],
    queryFn: () => fetchScheduleActivityOptions(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const rfiOptions = rfiOptionsQuery.data ?? [];
  const activityOptions = activityOptionsQuery.data ?? [];

  // Keep a selected-but-unlisted link visible in its dropdown so editing an
  // interface never quietly clears an id the picker did not load.
  const withCurrent = (options: LinkOption[], current: string): LinkOption[] =>
    current && !options.some((o) => o.id === current)
      ? [{ id: current, label: current }, ...options]
      : options;
  const rfiSelectOptions = withCurrent(rfiOptions, form.rfi_id);
  const activitySelectOptions = withCurrent(activityOptions, form.schedule_activity_id);

  const set = <K extends keyof InterfaceFormState>(key: K, value: InterfaceFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const refError = touched && form.reference.trim().length === 0;
  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.reference.trim().length > 0 && form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(formToPayload(form));
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const heading = initial
    ? t('interface_management.edit_interface', { defaultValue: 'Edit interface' })
    : t('interface_management.new_interface', { defaultValue: 'New interface' });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="mx-4 max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-surface-elevated shadow-xl animate-card-in"
        role="dialog"
        aria-modal="true"
        aria-label={heading}
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h2 className="text-lg font-semibold text-content-primary">{heading}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-6 py-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="if-reference" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_reference', { defaultValue: 'Reference' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                id="if-reference"
                value={form.reference}
                maxLength={40}
                onChange={(e) => {
                  set('reference', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('interface_management.reference_placeholder', { defaultValue: 'e.g. IF-014' })}
                className={clsx(inputCls, refError && 'border-semantic-error focus:ring-red-300')}
                autoFocus
              />
              {refError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('interface_management.reference_required', { defaultValue: 'Reference is required' })}
                </p>
              )}
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="if-title" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_title', { defaultValue: 'Title' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                id="if-title"
                value={form.title}
                maxLength={255}
                onChange={(e) => {
                  set('title', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('interface_management.title_placeholder', {
                  defaultValue: 'e.g. Duct penetration through core wall at Level 3',
                })}
                className={clsx(inputCls, titleError && 'border-semantic-error focus:ring-red-300')}
              />
              {titleError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('interface_management.title_required', { defaultValue: 'Title is required' })}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="if-type" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_type', { defaultValue: 'Type' })}
              </label>
              <select
                id="if-type"
                value={form.interface_type}
                onChange={(e) => set('interface_type', e.target.value as InterfaceType | '')}
                className={selectCls}
              >
                <option value="">{t('interface_management.type_none', { defaultValue: 'No type' })}</option>
                {ALL_INTERFACE_TYPES.map((ty) => (
                  <option key={ty} value={ty}>
                    {t(`interface_management.type_${ty}`, { defaultValue: TYPE_LABEL[ty] ?? humanize(ty) })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="if-status" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_status', { defaultValue: 'Status' })}
              </label>
              <select
                id="if-status"
                value={form.status}
                onChange={(e) => set('status', e.target.value as InterfaceStatus)}
                className={selectCls}
              >
                {ALL_INTERFACE_STATUSES.map((st) => (
                  <option key={st} value={st}>
                    {t(`interface_management.status_${st}`, { defaultValue: STATUS_LABEL[st] ?? humanize(st) })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="if-priority" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_priority', { defaultValue: 'Priority' })}
              </label>
              <select
                id="if-priority"
                value={form.priority}
                onChange={(e) => set('priority', e.target.value as InterfacePriority | '')}
                className={selectCls}
              >
                <option value="">{t('interface_management.priority_none', { defaultValue: 'No priority' })}</option>
                {ALL_PRIORITIES.map((pr) => (
                  <option key={pr} value={pr}>
                    {t(`interface_management.priority_${pr}`, { defaultValue: PRIORITY_LABEL[pr] ?? humanize(pr) })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="if-owner" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_owner_party', { defaultValue: 'Owner party' })}
              </label>
              <input
                id="if-owner"
                value={form.owner_party}
                maxLength={255}
                onChange={(e) => set('owner_party', e.target.value)}
                placeholder={t('interface_management.owner_placeholder', { defaultValue: 'Party responsible' })}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="if-accepter" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_accepter_party', { defaultValue: 'Accepter party' })}
              </label>
              <input
                id="if-accepter"
                value={form.accepter_party}
                maxLength={255}
                onChange={(e) => set('accepter_party', e.target.value)}
                placeholder={t('interface_management.accepter_placeholder', { defaultValue: 'Party that depends on it' })}
                className={inputCls}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="if-wp-from" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_work_package_from', { defaultValue: 'Work package (from)' })}
              </label>
              <input
                id="if-wp-from"
                value={form.work_package_from}
                maxLength={120}
                onChange={(e) => set('work_package_from', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="if-wp-to" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_work_package_to', { defaultValue: 'Work package (to)' })}
              </label>
              <input
                id="if-wp-to"
                value={form.work_package_to}
                maxLength={120}
                onChange={(e) => set('work_package_to', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="if-disc-from" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_discipline_from', { defaultValue: 'Discipline (from)' })}
              </label>
              <input
                id="if-disc-from"
                value={form.discipline_from}
                maxLength={60}
                onChange={(e) => set('discipline_from', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="if-disc-to" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_discipline_to', { defaultValue: 'Discipline (to)' })}
              </label>
              <input
                id="if-disc-to"
                value={form.discipline_to}
                maxLength={60}
                onChange={(e) => set('discipline_to', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="if-need-by" className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('interface_management.field_need_by_date', { defaultValue: 'Need-by date' })}
              </label>
              <input
                id="if-need-by"
                type="date"
                value={form.need_by_date}
                onChange={(e) => set('need_by_date', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          <div>
            <label htmlFor="if-location" className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('interface_management.field_location', { defaultValue: 'Location' })}
            </label>
            <input
              id="if-location"
              value={form.location}
              maxLength={500}
              onChange={(e) => set('location', e.target.value)}
              placeholder={t('interface_management.location_placeholder', { defaultValue: 'e.g. Building A, Level 3, Zone C' })}
              className={inputCls}
            />
          </div>

          <div>
            <label htmlFor="if-description" className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('interface_management.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              id="if-description"
              value={form.description}
              rows={3}
              onChange={(e) => set('description', e.target.value)}
              placeholder={t('interface_management.description_placeholder', {
                defaultValue: 'What must be agreed, and what depends on it',
              })}
              className={textareaCls}
            />
          </div>

          <div>
            <label htmlFor="if-notes" className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('interface_management.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              id="if-notes"
              value={form.notes}
              rows={2}
              onChange={(e) => set('notes', e.target.value)}
              className={textareaCls}
            />
          </div>

          {/* Linked references — connect this interface into the thread that
              resolves it: the RFI raising the technical question, and the
              programme activity whose need-by date it gates. Both are optional
              soft links the backend already stores. */}
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
            <div className="mb-2 flex items-center gap-1.5">
              <Link2 size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('interface_management.section_links', { defaultValue: 'Linked references' })}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="if-rfi" className="mb-1.5 block text-sm font-medium text-content-primary">
                  {t('interface_management.field_rfi', { defaultValue: 'Related RFI' })}
                </label>
                <select
                  id="if-rfi"
                  value={form.rfi_id}
                  onChange={(e) => set('rfi_id', e.target.value)}
                  className={selectCls}
                >
                  <option value="">{t('interface_management.link_none', { defaultValue: 'None' })}</option>
                  {rfiSelectOptions.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {rfiOptions.length === 0 && !rfiOptionsQuery.isLoading && (
                  <p className="mt-1 text-2xs text-content-tertiary">
                    {t('interface_management.no_rfis_to_link', { defaultValue: 'No RFIs in this project yet.' })}
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="if-activity" className="mb-1.5 block text-sm font-medium text-content-primary">
                  {t('interface_management.field_schedule_activity', { defaultValue: 'Schedule activity' })}
                </label>
                <select
                  id="if-activity"
                  value={form.schedule_activity_id}
                  onChange={(e) => set('schedule_activity_id', e.target.value)}
                  className={selectCls}
                >
                  <option value="">{t('interface_management.link_none', { defaultValue: 'None' })}</option>
                  {activitySelectOptions.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {activityOptions.length === 0 && !activityOptionsQuery.isLoading && (
                  <p className="mt-1 text-2xs text-content-tertiary">
                    {t('interface_management.no_activities_to_link', {
                      defaultValue: 'No schedule activities in this project yet.',
                    })}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit} loading={isPending}>
            {initial
              ? t('common.save', { defaultValue: 'Save' })
              : t('interface_management.create_interface', { defaultValue: 'Create interface' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Actions-to-close panel ------------------------------------------------ */

function ActionsPanel({
  interfaceId,
  actions,
  today,
  onCreate,
  onSetStatus,
  isPending,
}: {
  interfaceId: string;
  actions: InterfaceAction[];
  today: string;
  onCreate: (interfaceId: string, payload: ActionWritePayload) => void;
  onSetStatus: (action: InterfaceAction, status: ActionStatus) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [description, setDescription] = useState('');
  const [party, setParty] = useState('');
  const [due, setDue] = useState('');

  const submit = () => {
    if (!description.trim()) return;
    onCreate(interfaceId, {
      description: description.trim(),
      action_party: orNull(party),
      due_date: orNull(due),
    });
    setDescription('');
    setParty('');
    setDue('');
  };

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <ListChecks size={14} className="text-content-tertiary" />
        <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('interface_management.actions_to_close', { defaultValue: 'Actions to close' })}
        </span>
      </div>

      {actions.length === 0 ? (
        <p className="py-1 text-xs text-content-tertiary">
          {t('interface_management.no_actions', { defaultValue: 'No actions yet. Add the first one below.' })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {actions.map((a) => {
            const dueOverdue = a.status === 'open' && !!a.due_date && a.due_date < today;
            return (
              <li
                key={a.id}
                className="flex items-center gap-2 rounded-md bg-surface-primary/70 px-2.5 py-1.5"
              >
                <button
                  type="button"
                  disabled={isPending}
                  onClick={() => onSetStatus(a, a.status === 'done' ? 'open' : 'done')}
                  aria-label={
                    a.status === 'done'
                      ? t('interface_management.reopen_action', { defaultValue: 'Reopen action' })
                      : t('interface_management.mark_action_done', { defaultValue: 'Mark action done' })
                  }
                  className="shrink-0 text-content-tertiary hover:text-semantic-success transition-colors"
                >
                  {a.status === 'done' ? (
                    <CheckCircle2 size={16} className="text-semantic-success" />
                  ) : a.status === 'cancelled' ? (
                    <Ban size={16} className="text-content-tertiary" />
                  ) : (
                    <CheckCircle2 size={16} />
                  )}
                </button>
                <span
                  className={clsx(
                    'flex-1 min-w-0 truncate text-sm',
                    a.status === 'done' || a.status === 'cancelled'
                      ? 'text-content-tertiary line-through'
                      : 'text-content-primary',
                  )}
                  title={a.description}
                >
                  {a.description}
                </span>
                {a.action_party && (
                  <span className="hidden shrink-0 text-2xs text-content-tertiary sm:inline">
                    {a.action_party}
                  </span>
                )}
                {a.due_date && (
                  <span
                    className={clsx(
                      'hidden shrink-0 items-center gap-1 text-2xs sm:inline-flex',
                      dueOverdue ? 'text-semantic-error' : 'text-content-tertiary',
                    )}
                  >
                    <Clock size={11} />
                    <DateDisplay value={a.due_date} />
                  </span>
                )}
                <Badge variant={ACTION_STATUS_VARIANT[a.status] ?? 'neutral'} size="sm">
                  {t(`interface_management.action_status_${a.status}`, {
                    defaultValue: ACTION_STATUS_LABEL[a.status] ?? humanize(a.status),
                  })}
                </Badge>
                {a.status === 'open' && (
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => onSetStatus(a, 'cancelled')}
                    aria-label={t('interface_management.cancel_action', { defaultValue: 'Cancel action' })}
                    className="shrink-0 text-content-tertiary hover:text-semantic-error transition-colors"
                  >
                    <Ban size={13} />
                  </button>
                )}
                {a.status !== 'open' && (
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => onSetStatus(a, 'open')}
                    aria-label={t('interface_management.reopen_action', { defaultValue: 'Reopen action' })}
                    className="shrink-0 text-content-tertiary hover:text-oe-blue transition-colors"
                  >
                    <RotateCcw size={13} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Add action */}
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          placeholder={t('interface_management.action_placeholder', { defaultValue: 'Describe an action to close this interface' })}
          className={clsx(inputCls, 'h-9 flex-1')}
        />
        <input
          value={party}
          onChange={(e) => setParty(e.target.value)}
          placeholder={t('interface_management.action_party_placeholder', { defaultValue: 'Owner' })}
          className={clsx(inputCls, 'h-9 sm:w-32')}
        />
        <input
          type="date"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          aria-label={t('interface_management.action_due', { defaultValue: 'Due date' })}
          className={clsx(inputCls, 'h-9 sm:w-40')}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={submit}
          disabled={isPending || !description.trim()}
          icon={<Plus size={14} />}
        >
          {t('interface_management.add_action', { defaultValue: 'Add' })}
        </Button>
      </div>
    </div>
  );
}

/* -- Interface row (expandable) ------------------------------------------- */

function DetailField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

const InterfaceRow = React.memo(function InterfaceRow({
  iface,
  actions,
  today,
  onEdit,
  onDelete,
  onCreateAction,
  onSetActionStatus,
  actionPending,
}: {
  iface: InterfaceRecord;
  actions: InterfaceAction[];
  today: string;
  onEdit: (iface: InterfaceRecord) => void;
  onDelete: (iface: InterfaceRecord) => void;
  onCreateAction: (interfaceId: string, payload: ActionWritePayload) => void;
  onSetActionStatus: (action: InterfaceAction, status: ActionStatus) => void;
  actionPending: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const overdue = isInterfaceOverdue(iface, today);
  const openActions = actions.filter((a) => a.status === 'open').length;
  const notSet = t('interface_management.not_set', { defaultValue: 'Not set' });

  return (
    <div className="border-b border-border-light last:border-b-0">
      <div
        className={clsx(
          'flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-secondary/50',
          expanded && 'bg-surface-secondary/30',
          overdue && 'bg-semantic-error-bg/40',
        )}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <ChevronRight
          size={14}
          className={clsx('shrink-0 text-content-tertiary transition-transform', expanded && 'rotate-90')}
        />
        <span className="w-20 shrink-0 truncate font-mono text-sm font-semibold text-content-secondary" title={iface.reference}>
          {iface.reference}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-content-primary" title={iface.title}>
          {iface.title}
        </span>

        {/* Owner -> accepter */}
        <span className="hidden min-w-0 shrink items-center gap-1 text-xs text-content-tertiary lg:flex">
          <span className="truncate max-w-[9rem]">{iface.owner_party || notSet}</span>
          <ArrowRight size={11} className="shrink-0" />
          <span className="truncate max-w-[9rem]">{iface.accepter_party || notSet}</span>
        </span>

        {openActions > 0 && (
          <Badge variant="neutral" size="sm" className="hidden shrink-0 sm:inline-flex">
            {t('interface_management.open_actions_count', { defaultValue: '{{count}} open', count: openActions })}
          </Badge>
        )}

        {overdue && (
          <Badge variant="error" size="sm" className="shrink-0">
            {t('interface_management.overdue', { defaultValue: 'Overdue' })}
          </Badge>
        )}

        {/* Need-by */}
        <span className="hidden w-24 shrink-0 text-right text-xs text-content-tertiary md:block">
          {iface.need_by_date ? <DateDisplay value={iface.need_by_date} /> : notSet}
        </span>

        {iface.priority && (
          <Badge variant={PRIORITY_VARIANT[iface.priority] ?? 'neutral'} size="sm" className="hidden shrink-0 sm:inline-flex">
            {t(`interface_management.priority_${iface.priority}`, {
              defaultValue: PRIORITY_LABEL[iface.priority] ?? humanize(iface.priority),
            })}
          </Badge>
        )}

        <Badge variant={STATUS_VARIANT[iface.status] ?? 'neutral'} size="sm" className="shrink-0">
          {t(`interface_management.status_${iface.status}`, {
            defaultValue: STATUS_LABEL[iface.status] ?? humanize(iface.status),
          })}
        </Badge>
      </div>

      {expanded && (
        <div className="space-y-3 px-4 pb-4 pl-12 animate-fade-in">
          {iface.description && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="whitespace-pre-wrap text-sm text-content-primary">{iface.description}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <DetailField
              label={t('interface_management.field_type', { defaultValue: 'Type' })}
              value={
                iface.interface_type
                  ? t(`interface_management.type_${iface.interface_type}`, {
                      defaultValue: TYPE_LABEL[iface.interface_type] ?? humanize(iface.interface_type),
                    })
                  : notSet
              }
            />
            <DetailField
              label={t('interface_management.field_work_packages', { defaultValue: 'Work packages' })}
              value={
                iface.work_package_from || iface.work_package_to
                  ? `${iface.work_package_from || notSet} -> ${iface.work_package_to || notSet}`
                  : notSet
              }
            />
            <DetailField
              label={t('interface_management.field_disciplines', { defaultValue: 'Disciplines' })}
              value={
                iface.discipline_from || iface.discipline_to
                  ? `${iface.discipline_from || notSet} -> ${iface.discipline_to || notSet}`
                  : notSet
              }
            />
            <DetailField
              label={t('interface_management.field_location', { defaultValue: 'Location' })}
              value={iface.location || notSet}
            />
            <DetailField
              label={t('interface_management.field_need_by_date', { defaultValue: 'Need-by date' })}
              value={iface.need_by_date ? <DateDisplay value={iface.need_by_date} /> : notSet}
            />
            <DetailField
              label={t('interface_management.field_agreed_date', { defaultValue: 'Agreed date' })}
              value={iface.agreed_date ? <DateDisplay value={iface.agreed_date} /> : notSet}
            />
            <DetailField
              label={t('interface_management.field_created', { defaultValue: 'Created' })}
              value={<DateDisplay value={iface.created_at} />}
            />
            <DetailField
              label={t('interface_management.field_updated', { defaultValue: 'Updated' })}
              value={<DateDisplay value={iface.updated_at} />}
            />
          </div>

          {iface.notes && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('interface_management.field_notes', { defaultValue: 'Notes' })}
              </p>
              <p className="whitespace-pre-wrap text-sm text-content-primary">{iface.notes}</p>
            </div>
          )}

          {/* Linked references — deep links to the RFI and programme activity
              this interface is tied to (soft links, so we link out by id). */}
          {(iface.rfi_id || iface.schedule_activity_id) && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-center gap-1 text-2xs uppercase tracking-wide text-content-tertiary">
                <Link2 size={11} />
                {t('interface_management.section_links', { defaultValue: 'Linked references' })}
              </span>
              {iface.rfi_id && (
                <Link
                  to={`/rfi/${iface.rfi_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2 py-0.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/20 transition-colors"
                >
                  <HelpCircle size={11} />
                  {t('interface_management.view_rfi', { defaultValue: 'View RFI' })}
                  <ExternalLink size={10} aria-hidden="true" />
                </Link>
              )}
              {iface.schedule_activity_id && (
                <Link
                  to="/schedule"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2 py-0.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/20 transition-colors"
                >
                  <CalendarClock size={11} />
                  {t('interface_management.view_activity', { defaultValue: 'Open in schedule' })}
                  <ExternalLink size={10} aria-hidden="true" />
                </Link>
              )}
            </div>
          )}

          <ActionsPanel
            interfaceId={iface.id}
            actions={actions}
            today={today}
            onCreate={onCreateAction}
            onSetStatus={onSetActionStatus}
            isPending={actionPending}
          />

          <div className="flex items-center gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => onEdit(iface)} icon={<Pencil size={14} />}>
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onDelete(iface)} icon={<Trash2 size={14} />}>
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* -- Main page ------------------------------------------------------------- */

export function InterfaceManagementPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const today = useMemo(() => todayIso(), []);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<InterfaceRecord | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<InterfaceStatus | ''>('');
  const [wpFilter, setWpFilter] = useState('');

  const errorTitle = t('common.error', { defaultValue: 'Error' });

  /* Queries */
  const healthQuery = useQuery({
    queryKey: ['interface-management', 'health', projectId],
    queryFn: () => fetchWorkPackageHealth(projectId),
    enabled: !!projectId,
  });

  const interfacesQuery = useQuery({
    queryKey: ['interface-management', 'interfaces', projectId, statusFilter, wpFilter],
    queryFn: () =>
      fetchInterfaces(projectId, {
        status: statusFilter || undefined,
        work_package: wpFilter || undefined,
      }),
    enabled: !!projectId,
  });

  const actionsQuery = useQuery({
    queryKey: ['interface-management', 'actions', projectId],
    queryFn: () => fetchActions(projectId),
    enabled: !!projectId,
  });

  const interfaces = useMemo(() => interfacesQuery.data ?? [], [interfacesQuery.data]);
  const actions = useMemo(() => actionsQuery.data ?? [], [actionsQuery.data]);
  const report = healthQuery.data;

  // Surface load failures as toasts (queries have no onError in React Query v5).
  useEffect(() => {
    if (interfacesQuery.isError) {
      addToast({ type: 'error', title: errorTitle, message: getErrorMessage(interfacesQuery.error) });
    }
  }, [interfacesQuery.isError, interfacesQuery.error, addToast, errorTitle]);

  const actionsByInterface = useMemo(() => {
    const map: Record<string, InterfaceAction[]> = {};
    for (const a of actions) {
      const list = map[a.interface_id] ?? [];
      list.push(a);
      map[a.interface_id] = list;
    }
    return map;
  }, [actions]);

  // Work-package filter options from the (unfiltered) health report, minus the
  // synthetic "unassigned" bucket which has no real backend label to filter on.
  const wpOptions = useMemo(
    () => (report?.work_packages ?? []).map((w) => w.work_package).filter((w) => w !== UNASSIGNED),
    [report],
  );

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return interfaces;
    return interfaces.filter(
      (i) =>
        i.reference.toLowerCase().includes(q) ||
        i.title.toLowerCase().includes(q) ||
        (i.owner_party ?? '').toLowerCase().includes(q) ||
        (i.accepter_party ?? '').toLowerCase().includes(q),
    );
  }, [interfaces, searchQuery]);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['interface-management'] });
  }, [qc]);

  const toastError = useCallback(
    (e: unknown) => addToast({ type: 'error', title: errorTitle, message: getErrorMessage(e) }),
    [addToast, errorTitle],
  );

  /* Mutations */
  const createMut = useMutation({
    mutationFn: (payload: InterfaceWritePayload) => createInterface(projectId, payload),
    onSuccess: () => {
      invalidate();
      setModalOpen(false);
      addToast({ type: 'success', title: t('interface_management.created', { defaultValue: 'Interface created' }) });
    },
    onError: toastError,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<InterfaceWritePayload> }) =>
      updateInterface(projectId, id, payload),
    onSuccess: () => {
      invalidate();
      setModalOpen(false);
      setEditing(null);
      addToast({ type: 'success', title: t('interface_management.updated', { defaultValue: 'Interface updated' }) });
    },
    onError: toastError,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteInterface(projectId, id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('interface_management.deleted', { defaultValue: 'Interface deleted' }) });
    },
    onError: toastError,
  });

  const createActionMut = useMutation({
    mutationFn: ({ interfaceId, payload }: { interfaceId: string; payload: ActionWritePayload }) =>
      createAction(projectId, interfaceId, payload),
    onSuccess: () => invalidate(),
    onError: toastError,
  });

  const updateActionMut = useMutation({
    mutationFn: ({ actionId, payload }: { actionId: string; payload: Partial<ActionWritePayload> }) =>
      updateAction(projectId, actionId, payload),
    onSuccess: () => invalidate(),
    onError: toastError,
  });

  /* Handlers */
  const handleSubmit = useCallback(
    (payload: InterfaceWritePayload) => {
      if (editing) updateMut.mutate({ id: editing.id, payload });
      else createMut.mutate(payload);
    },
    [editing, updateMut, createMut],
  );

  const handleDelete = useCallback(
    async (iface: InterfaceRecord) => {
      const ok = await confirm({
        title: t('interface_management.confirm_delete_title', { defaultValue: 'Delete interface?' }),
        message: t('interface_management.confirm_delete_msg', {
          defaultValue: 'This interface and all of its actions will be permanently deleted.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(iface.id);
    },
    [confirm, deleteMut, t],
  );

  const handleCreateAction = useCallback(
    (interfaceId: string, payload: ActionWritePayload) => createActionMut.mutate({ interfaceId, payload }),
    [createActionMut],
  );

  const handleSetActionStatus = useCallback(
    (action: InterfaceAction, status: ActionStatus) => {
      const payload: Partial<ActionWritePayload> = {
        status,
        completed_date: status === 'done' ? today : null,
      };
      updateActionMut.mutate({ actionId: action.id, payload });
    },
    [updateActionMut, today],
  );

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };
  const openEdit = useCallback((iface: InterfaceRecord) => {
    setEditing(iface);
    setModalOpen(true);
  }, []);

  const hasFilters = !!statusFilter || !!wpFilter || !!searchQuery.trim();
  const actionPending = createActionMut.isPending || updateActionMut.isPending;

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('interface_management.title', { defaultValue: 'Interface management' })}
        subtitle={t('interface_management.subtitle', {
          defaultValue:
            'Track the handshakes between work packages and contractors, and drive each one to agreement',
        })}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={openCreate}
            disabled={!projectId}
            title={!projectId ? t('interface_management.select_project', { defaultValue: 'Open a project first' }) : undefined}
            icon={<Plus size={14} />}
          >
            {t('interface_management.new_interface', { defaultValue: 'New interface' })}
          </Button>
        }
      />

      <RequiresProject
        emptyHint={t('interface_management.select_project_hint', {
          defaultValue: 'Open a project first to view and manage its interface register.',
        })}
      >
        {/* SIGNAL: work-package health band */}
        <section className="rounded-xl border border-border-light bg-surface-secondary/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
              <Network size={15} className="text-oe-blue" />
              {t('interface_management.health_title', { defaultValue: 'Work package health' })}
            </h2>
            {report && (
              <div className="flex items-center gap-2">
                {report.overdue.length > 0 && (
                  <Badge variant="error" size="sm">
                    {t('interface_management.overdue_count', {
                      defaultValue: '{{count}} overdue',
                      count: report.overdue.length,
                    })}
                  </Badge>
                )}
                {report.disputed.length > 0 && (
                  <Badge variant="warning" size="sm">
                    {t('interface_management.disputed_count', {
                      defaultValue: '{{count}} disputed',
                      count: report.disputed.length,
                    })}
                  </Badge>
                )}
                <Badge variant={report.is_healthy ? 'success' : 'warning'} size="sm" dot>
                  {report.is_healthy
                    ? t('interface_management.overall_healthy', { defaultValue: 'Healthy' })
                    : t('interface_management.overall_attention', { defaultValue: 'Needs attention' })}
                </Badge>
              </div>
            )}
          </div>

          {healthQuery.isLoading ? (
            <p className="mt-3 text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : healthQuery.isError ? (
            <p className="mt-3 text-sm text-semantic-error">{getErrorMessage(healthQuery.error)}</p>
          ) : !report || report.work_packages.length === 0 ? (
            <p className="mt-3 text-sm text-content-tertiary">
              {t('interface_management.no_health', {
                defaultValue: 'No interfaces yet. Add one to see per-package health here.',
              })}
            </p>
          ) : (
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {report.work_packages.map((wp) => (
                <WorkPackageHealthCard key={wp.work_package} wp={wp} />
              ))}
            </div>
          )}
        </section>

        {/* Toolbar */}
        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative max-w-sm flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('interface_management.search_placeholder', { defaultValue: 'Search interfaces...' })}
              aria-label={t('interface_management.search_placeholder', { defaultValue: 'Search interfaces...' })}
              className={clsx(inputCls, 'pl-9')}
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as InterfaceStatus | '')}
            aria-label={t('interface_management.filter_all_statuses', { defaultValue: 'All statuses' })}
            className={clsx(selectCls, 'sm:w-44')}
          >
            <option value="">{t('interface_management.filter_all_statuses', { defaultValue: 'All statuses' })}</option>
            {ALL_INTERFACE_STATUSES.map((st) => (
              <option key={st} value={st}>
                {t(`interface_management.status_${st}`, { defaultValue: STATUS_LABEL[st] ?? humanize(st) })}
              </option>
            ))}
          </select>
          <select
            value={wpFilter}
            onChange={(e) => setWpFilter(e.target.value)}
            aria-label={t('interface_management.filter_all_packages', { defaultValue: 'All work packages' })}
            className={clsx(selectCls, 'sm:w-48')}
          >
            <option value="">{t('interface_management.filter_all_packages', { defaultValue: 'All work packages' })}</option>
            {wpOptions.map((wp) => (
              <option key={wp} value={wp}>
                {wp}
              </option>
            ))}
          </select>
        </div>

        {/* Register list */}
        <div className="mt-4">
          {interfacesQuery.isLoading ? (
            <p className="py-10 text-center text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          ) : interfacesQuery.isError ? (
            <EmptyState
              icon={<AlertTriangle size={28} strokeWidth={1.5} />}
              title={t('interface_management.load_failed', { defaultValue: 'Could not load interfaces' })}
              description={getErrorMessage(interfacesQuery.error)}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => void interfacesQuery.refetch(),
              }}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Network size={28} strokeWidth={1.5} />}
              title={
                hasFilters
                  ? t('interface_management.no_results', { defaultValue: 'No matching interfaces' })
                  : t('interface_management.no_interfaces', { defaultValue: 'No interfaces yet' })
              }
              description={
                hasFilters
                  ? t('interface_management.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })
                  : t('interface_management.no_interfaces_hint', {
                      defaultValue: 'Add the first interface between two work packages or contractors.',
                    })
              }
              action={
                hasFilters
                  ? undefined
                  : {
                      label: t('interface_management.new_interface', { defaultValue: 'New interface' }),
                      onClick: openCreate,
                    }
              }
            />
          ) : (
            <>
              <p className="mb-3 text-sm text-content-tertiary">
                {t('interface_management.showing_count', { defaultValue: '{{count}} interfaces', count: filtered.length })}
              </p>
              <Card padding="none" className="overflow-x-auto">
                <div className="flex min-w-[720px] items-center gap-3 border-b border-border-light bg-surface-secondary/30 px-4 py-2.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                  <span className="w-5" />
                  <span className="w-20">{t('interface_management.col_reference', { defaultValue: 'Ref' })}</span>
                  <span className="flex-1">{t('interface_management.col_title', { defaultValue: 'Title' })}</span>
                  <span className="hidden lg:block">{t('interface_management.col_parties', { defaultValue: 'Owner / Accepter' })}</span>
                  <span className="hidden w-24 text-right md:block">{t('interface_management.col_need_by', { defaultValue: 'Need by' })}</span>
                  <span className="w-20 text-center">{t('interface_management.col_status', { defaultValue: 'Status' })}</span>
                </div>
                {filtered.map((iface) => (
                  <InterfaceRow
                    key={iface.id}
                    iface={iface}
                    actions={actionsByInterface[iface.id] ?? []}
                    today={today}
                    onEdit={openEdit}
                    onDelete={handleDelete}
                    onCreateAction={handleCreateAction}
                    onSetActionStatus={handleSetActionStatus}
                    actionPending={actionPending}
                  />
                ))}
              </Card>
            </>
          )}
        </div>
      </RequiresProject>

      {modalOpen && (
        <InterfaceModal
          initial={editing}
          projectId={projectId}
          onClose={() => {
            setModalOpen(false);
            setEditing(null);
          }}
          onSubmit={handleSubmit}
          isPending={createMut.isPending || updateMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
